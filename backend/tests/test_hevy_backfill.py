"""
Regression tests for the Hevy set-level ingest backfill fix.

These target the exact live-behavior bug PR #3's unit tests missed: the poller
skipped the per-exercise write whenever the rolled-up fitness-workouts row was
unchanged, so ~26 workouts that already had rolled-up rows (from the pre-PR#3
poller) never got fitness-exercises rows. "Session row unchanged" is NOT the
same condition as "exercise rows exist".

Covered here:
  - a workout whose rolled-up row is unchanged BUT has no exercise rows → the
    exercise rows MUST still be written (the backfill path)
  - a fully-synced workout (both rows present) → idempotent, no duplication,
    PR flags unchanged, cheap skip
  - the {"action": "hevy_backfill"} entrypoint ignoring the watermark and
    page-walking multiple pages via the real fetch_recent_workouts_full seam
  - body-measurement response-shape handling: pageSize is clamped to Hevy's
    max of 10 (the measurements_written: 0 root cause), and the summary
    distinguishes "genuinely empty" from a fetch/parse "error"

All offline: shared.db + the Hevy fetch/secret helpers are stubbed.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))

from shared import hevy_client as hc  # noqa: E402


# ── Fake DynamoDB harness (mirrors test_dual_source_ingest) ─────────

class FakeTable:
    def __init__(self, key_attrs=("date", "strava_id")):
        self.items = []
        self.key_attrs = key_attrs

    def _key(self, item):
        return tuple(item.get(k) for k in self.key_attrs)

    def put_item(self, Item=None, **_kw):
        key = self._key(Item)
        self.items = [i for i in self.items if self._key(i) != key]
        self.items.append(Item)

    def get_item(self, Key=None, **_kw):
        if not Key:
            return {}
        for item in reversed(self.items):
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": item}
        return {}

    def delete_item(self, Key=None, **_kw):
        if not Key:
            return
        self.items = [i for i in self.items if not all(i.get(k) == v for k, v in Key.items())]

    def scan(self, **_kw):
        return {"Items": list(self.items)}


_TABLE_KEYS = {
    "WORKOUTS_TABLE": ("date", "strava_id"),
    "EXERCISES_TABLE": ("canonical", "date"),
    "USER_CONFIG_TABLE": ("key",),
    "HEALTH_METRICS_TABLE": ("date", "metric_source"),
    "DAILY_SCORES_TABLE": ("date",),
}


def _fresh_module():
    import shared.db as db_mod
    tables = {env: FakeTable(keys) for env, keys in _TABLE_KEYS.items()}

    def _get_table(env):
        return tables.setdefault(env, FakeTable())

    db_mod.get_table = _get_table
    db_mod.put_item = lambda table, item: table.put_item(Item=item)
    db_mod.get_item = lambda table, key: (table.get_item(Key=key) or {}).get("Item") or {}
    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler  # noqa
    handler._trigger_compute = lambda *_a, **_k: None
    handler._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    return handler, tables


def _hevy_workout(wid, date="2026-06-30", exercises=None):
    return {
        "id": wid,
        "title": "Push Day",
        "start_time": f"{date}T18:00:00+00:00",
        "end_time": f"{date}T19:00:00+00:00",
        "exercises": exercises if exercises is not None else [
            {"title": "Bench", "sets": [{"weight_kg": 60, "reps": 10}]},
        ],
    }


def _stub_offline(h, workouts=None, events=None, measurements=None):
    """Stub the fetch + recompute helpers so the handler stays offline."""
    workouts = workouts or []
    h.fetch_recent_workouts_full = lambda key, **kw: list(workouts)
    if events is not None:
        h.fetch_workout_events = lambda key, since, **kw: events
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: list(measurements or [])
    h.recompute_prs_for_canonicals = lambda *_a, **_k: {}
    h.recompute_weekly_volume = lambda *_a, **_k: {}


# ── P0: the exact backfill bug ──────────────────────────────────────

def test_unchanged_rollup_but_missing_exercise_rows_still_backfills():
    """THE BUG. A rolled-up fitness-workouts row already exists and is
    identical (as the pre-PR#3 poller left it), but there are NO
    fitness-exercises rows. The exercise rows MUST be written — the dupe-check
    on the session row may not suppress the exercise write."""
    h, tables = _fresh_module()
    workouts_table = tables["WORKOUTS_TABLE"]
    exercises_table = tables["EXERCISES_TABLE"]

    workout = _hevy_workout("a")
    # Simulate the pre-PR#3 state: rolled-up row present (same volume + dur as
    # workout_to_row will produce), but zero exercise rows.
    seed = h.workout_to_row(workout)
    workouts_table.put_item(Item=seed)
    assert exercises_table.items == []  # nothing mirrored yet

    # Incremental poll re-delivers the identical workout as an "updated" event.
    _stub_offline(h, events={"updated": [workout], "deleted": []})
    # Force incremental mode by seeding a watermark.
    tables["USER_CONFIG_TABLE"].put_item(Item={"key": "hevy_last_sync",
                                               "last_sync": "2026-06-01T00:00:00Z"})
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])

    assert body["mode"] == "incremental"
    # Session row was a genuine duplicate → NOT rewritten...
    assert body["workouts_written"] == 0
    # ...but the missing exercise rows were backfilled.
    assert body["backfilled"] == 1
    assert body["exercise_rows_written"] >= 1
    ex = [i for i in exercises_table.items if i["canonical"] == "bench_press"]
    assert len(ex) == 1
    assert ex[0]["source"] == "hevy"
    # Backfilled canonicals feed the recompute.
    assert "bench_press" in body["canonicals_touched"]


def test_fully_synced_workout_is_idempotent_no_dup_no_pr_change():
    """Both the rolled-up row AND the exercise rows already exist and are
    unchanged → cheap skip, no duplicate rows, PR flags untouched."""
    h, tables = _fresh_module()
    exercises_table = tables["EXERCISES_TABLE"]
    workout = _hevy_workout("a")

    # First cold-start poll writes BOTH rows.
    _stub_offline(h, workouts=[workout])
    h.lambda_handler({"action": "hevy_poll"}, None)
    first = [i for i in exercises_table.items if i["canonical"] == "bench_press"]
    assert len(first) == 1
    # Stamp a sentinel PR flag to prove it survives a no-op re-poll.
    first[0]["pr"] = {"weight": True}

    # Second poll (now incremental) re-delivers the identical workout.
    _stub_offline(h, events={"updated": [workout], "deleted": []})
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])
    assert body["mode"] == "incremental"
    assert body["workouts_written"] == 0
    assert body["backfilled"] == 0
    assert body["exercise_rows_written"] == 0  # nothing rewritten
    second = [i for i in exercises_table.items if i["canonical"] == "bench_press"]
    assert len(second) == 1  # no duplicate
    assert second[0].get("pr") == {"weight": True}  # untouched


def test_changed_rollup_rewrites_both_rows():
    """A materially-changed workout (different volume) rewrites BOTH the
    session row and the exercise rows, idempotently."""
    h, tables = _fresh_module()
    workouts_table = tables["WORKOUTS_TABLE"]
    exercises_table = tables["EXERCISES_TABLE"]

    w1 = _hevy_workout("a", exercises=[{"title": "Bench",
                                        "sets": [{"weight_kg": 60, "reps": 10}]}])
    _stub_offline(h, workouts=[w1])
    h.lambda_handler({"action": "hevy_poll"}, None)

    # Re-deliver with more volume (extra set) → not a duplicate.
    w2 = _hevy_workout("a", exercises=[{"title": "Bench", "sets": [
        {"weight_kg": 60, "reps": 10}, {"weight_kg": 60, "reps": 10}]}])
    _stub_offline(h, events={"updated": [w2], "deleted": []})
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])
    assert body["workouts_written"] == 1
    # Still exactly one session row + one exercise row (overwrite, not dupe).
    assert len([i for i in workouts_table.items if i["strava_id"] == "hevy_a"]) == 1
    assert len([i for i in exercises_table.items if i["canonical"] == "bench_press"]) == 1


# ── P1: the explicit backfill entrypoint ────────────────────────────

def test_backfill_ignores_watermark_and_walks_multiple_pages():
    """{"action": "hevy_backfill"} ignores the incremental watermark and
    page-walks GET /v1/workouts. Uses the REAL fetch_recent_workouts_full via
    the http_get seam so multi-page walking is genuinely exercised."""
    h, tables = _fresh_module()

    # A watermark exists — a normal poll would go incremental and (per the live
    # bug) return fetched:0. Backfill must ignore it.
    tables["USER_CONFIG_TABLE"].put_item(Item={"key": "hevy_last_sync",
                                               "last_sync": "2026-07-27T00:00:00Z"})

    # Two pages of workouts served through the real page-walker's http seam.
    # Page 1 is FULL (pageSize=10 items) so the walker continues to page 2;
    # page 2 is short, which stops the walk.
    p1_workouts = [_hevy_workout(f"w{n}", date=f"2026-05-{10 + n:02d}")
                   for n in range(1, 11)]
    page1 = ({"page": 1, "page_count": 2, "workouts": p1_workouts}, 200)
    page2 = ({"page": 2, "page_count": 2, "workouts": [
        _hevy_workout("w99", date="2026-05-22"),
    ]}, 200)
    seq = [page1, page2]
    calls = {"n": 0}

    def _http(url, api_key):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else ({"page": 99, "page_count": 2}, 200)

    # Real page-walk, injected http. Body measurements genuinely empty here.
    h.fetch_recent_workouts_full = lambda key, **kw: hc.fetch_recent_workouts_full(
        key, http_get=_http, **kw)
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: []
    h.recompute_prs_for_canonicals = lambda *_a, **_k: {}
    h.recompute_weekly_volume = lambda *_a, **_k: {}

    resp = h.lambda_handler({"action": "hevy_backfill"}, None)
    body = json.loads(resp["body"])

    assert body["mode"] == "backfill"
    assert body["fetched"] == 11         # walked BOTH pages, ignored watermark
    assert body["workouts_written"] == 11
    assert body["exercise_rows_written"] == 11
    assert "2026-05-22" in body["dates"]  # page-2 workout landed
    assert calls["n"] >= 2               # more than one page fetched
    # Watermark advanced so subsequent normal polls resume incrementally.
    cfg = [i for i in tables["USER_CONFIG_TABLE"].items if i["key"] == "hevy_last_sync"]
    assert cfg and cfg[0]["last_sync"] != "2026-07-27T00:00:00Z"


def test_backfill_force_rewrites_even_fully_synced_workouts():
    """force_full re-writes both rows even when a workout is already fully
    synced (dupe-check bypassed), and stays idempotent (no duplicates)."""
    h, tables = _fresh_module()
    exercises_table = tables["EXERCISES_TABLE"]
    workout = _hevy_workout("a")

    # Seed a fully-synced state via a normal cold-start poll.
    _stub_offline(h, workouts=[workout])
    h.lambda_handler({"action": "hevy_poll"}, None)

    # force_full poll re-delivers the same workout.
    _stub_offline(h, workouts=[workout])
    resp = h.lambda_handler({"action": "hevy_poll", "force_full": True}, None)
    body = json.loads(resp["body"])
    assert body["mode"] == "backfill"
    assert body["workouts_written"] == 1        # forced rewrite
    # Still exactly one row each — idempotent overwrite.
    assert len([i for i in exercises_table.items if i["canonical"] == "bench_press"]) == 1


def test_backfill_default_page_span_covers_full_history():
    """The backfill default max_pages (20) × pageSize (10) covers >= 200
    workouts — enough for Mateo's full history — without an event override."""
    h, tables = _fresh_module()

    captured = {}

    def _capture(key, **kw):
        captured.update(kw)
        return []

    h.fetch_recent_workouts_full = _capture
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: []
    h.recompute_prs_for_canonicals = lambda *_a, **_k: {}
    h.recompute_weekly_volume = lambda *_a, **_k: {}

    h.lambda_handler({"action": "hevy_backfill"}, None)
    assert captured["page_size"] * captured["max_pages"] >= 200


# ── P1: body-measurement shape handling ─────────────────────────────

def test_measurements_pagesize_clamped_to_hevy_max():
    """The measurements_written: 0 root cause: fetch_body_measurements sent
    pageSize=100, which Hevy rejects with 400. The client now clamps to 10 so
    the request is valid and real measurements come through."""
    urls = []

    def _http(url, api_key):
        urls.append(url)
        # Emulate Hevy: 400 on pageSize>10, else one page of data.
        if "pageSize=100" in url or "pageSize=50" in url:
            return None, 400
        return ({"page": 1, "page_count": 1, "body_measurements": [
            {"date": "2026-05-20", "weight_kg": 80.0},
        ]}, 200)

    # Caller asks for an over-cap page size; the clamp must rescue it.
    result = hc.fetch_body_measurements("k", page_size=100, http_get=_http)
    assert len(result) == 1
    assert result[0]["weight_kg"] == 80.0
    assert all("pageSize=10" in u for u in urls)  # never sent the illegal 100


def test_measurements_summary_distinguishes_empty_from_error():
    """measurements_written: 0 must not be ambiguous. A genuinely-empty fetch
    reports status 'empty'; a raising fetch reports 'error'."""
    # Genuinely empty (Mateo has logged no body measurements).
    h, tables = _fresh_module()
    _stub_offline(h, workouts=[], measurements=[])
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])
    assert body["measurements_written"] == 0
    assert body["measurements_available"] == 0
    assert body["measurements_status"] == "empty"

    # Fetch failure (a real error, not empty data).
    h2, _ = _fresh_module()
    _stub_offline(h2, workouts=[])

    def _boom(key, **kw):
        raise RuntimeError("hevy 500 on body_measurements")

    h2.fetch_body_measurements = _boom
    resp2 = h2.lambda_handler({"action": "hevy_poll"}, None)
    body2 = json.loads(resp2["body"])
    assert body2["measurements_written"] == 0
    assert body2["measurements_status"] == "error"


def test_measurements_written_when_present():
    """When measurements exist, they are written and the summary reports 'ok'
    with the available count."""
    h, tables = _fresh_module()
    _stub_offline(h, workouts=[])
    h.fetch_body_measurements = lambda key, **kw: [
        {"date": "2026-05-20", "weight_kg": 80.0, "waist": 81.28},
    ]
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])
    assert body["measurements_status"] == "ok"
    assert body["measurements_available"] == 1
    assert body["measurements_written"] == 2  # weight + waist
    metrics = tables["HEALTH_METRICS_TABLE"]
    assert {"weight#hevy", "waist#hevy"} <= {i["metric_source"] for i in metrics.items}
