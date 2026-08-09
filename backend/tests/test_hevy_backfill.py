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

import pytest

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
    h.fetch_recent_workouts_full = lambda key, **kw: hc.HevyFetchResult.success(workouts)
    if events is not None:
        h.fetch_workout_events = lambda key, since, **kw: (
            events if isinstance(events, hc.HevyWorkoutEventsResult)
            else hc.HevyWorkoutEventsResult.success(
                events.get("updated", []), events.get("deleted", [])
            )
        )
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: hc.HevyFetchResult.success(
        measurements or []
    )
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
    h.fetch_body_measurements = lambda key, **kw: hc.HevyFetchResult.success([])
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


def test_backfill_preserves_legacy_utc_date_key_instead_of_rekeying_history():
    """A pre-temporal-semantics Hevy row may live under its UTC date. A future
    backfill can enrich that row, but must not create a second canonical-date
    row or move the historical primary key as a side effect."""
    h, tables = _fresh_module()
    workouts_table = tables["WORKOUTS_TABLE"]
    workout = {
        "id": "legacy-evening",
        "title": "Evening Lift",
        # July 1 at 17:30 PDT, represented by Hevy as a July 2 UTC instant.
        "start_time": "2026-07-02T00:30:00Z",
        "end_time": "2026-07-02T01:30:00Z",
        "exercises": [
            {"title": "Bench", "sets": [{"weight_kg": 60, "reps": 10}]},
        ],
    }

    legacy = h.workout_to_row(workout)
    assert legacy["analysis_date"] == "2026-07-01"
    legacy["date"] = "2026-07-02"  # old UTC-prefix partition key
    for key in (
        "analysis_date",
        "analysis_timezone",
        "date_derivation",
        "source_date",
        "source_utc_offset",
        "source_start_time",
        "source_end_time",
    ):
        legacy.pop(key, None)
    workouts_table.put_item(Item=legacy)

    _stub_offline(h, workouts=[workout])
    response = h.lambda_handler({"action": "hevy_backfill"}, None)
    body = json.loads(response["body"])

    rows = [i for i in workouts_table.items if i["strava_id"] == "hevy_legacy-evening"]
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-07-02"
    assert rows[0]["analysis_date"] == "2026-07-01"
    assert rows[0]["legacy_date_preserved"] is True
    assert body["dates"] == ["2026-07-02"]


def test_legacy_lookup_failure_stops_before_writes_and_watermark_advance():
    h, tables = _fresh_module()
    workout = {
        "id": "lookup-failure",
        "title": "Evening Lift",
        "start_time": "2026-07-02T00:30:00Z",
        "end_time": "2026-07-02T01:30:00Z",
        "exercises": [
            {"title": "Bench", "sets": [{"weight_kg": 60, "reps": 10}]},
        ],
    }
    legacy = h.workout_to_row(workout)
    assert legacy["analysis_date"] == "2026-07-01"
    legacy["date"] = "2026-07-02"
    for key in (
        "analysis_date",
        "analysis_timezone",
        "date_derivation",
        "source_date",
        "source_utc_offset",
        "source_start_time",
        "source_end_time",
    ):
        legacy.pop(key, None)
    tables["WORKOUTS_TABLE"].put_item(Item=legacy)
    tables["EXERCISES_TABLE"].put_item(Item={
        "canonical": "bench_press",
        "date": "2026-07-02",
        "source": "hevy",
    })
    old_watermark = "2026-07-27T00:00:00Z"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    _stub_offline(h, events={"updated": [workout], "deleted": []})

    def fail_scan(**_kwargs):
        raise RuntimeError("simulated DynamoDB scan failure")

    tables["WORKOUTS_TABLE"].scan = fail_scan
    with pytest.raises(h.HevySyncError, match="hevy legacy lookup failed"):
        h.lambda_handler({"action": "hevy_poll"}, None)
    workout_rows = [
        item for item in tables["WORKOUTS_TABLE"].items
        if item["strava_id"] == "hevy_lookup-failure"
    ]
    exercise_rows = [
        item for item in tables["EXERCISES_TABLE"].items
        if item["canonical"] == "bench_press"
    ]
    assert len(workout_rows) == 1
    assert workout_rows[0]["date"] == "2026-07-02"
    assert not any(item["date"] == "2026-07-01" for item in workout_rows)
    assert len(exercise_rows) == 1
    assert exercise_rows[0]["date"] == "2026-07-02"
    assert not any(item["date"] == "2026-07-01" for item in exercise_rows)
    watermark = tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]
    assert watermark["last_sync"] == old_watermark


def test_confirmed_legacy_not_found_allows_legitimate_new_write():
    h, tables = _fresh_module()
    outcome = h._apply_hevy_workout(
        _hevy_workout("new-workout"),
        {},
        tables["WORKOUTS_TABLE"],
        tables["EXERCISES_TABLE"],
        force=False,
    )

    assert outcome["workout_written"] is True
    assert outcome["ex_rows_written"] == 1
    assert len(tables["WORKOUTS_TABLE"].items) == 1
    assert len(tables["EXERCISES_TABLE"].items) == 1


def test_lookup_exception_from_apply_is_distinct_from_confirmed_not_found():
    h, tables = _fresh_module()

    def fail_scan(**_kwargs):
        raise RuntimeError("simulated DynamoDB scan failure")

    tables["WORKOUTS_TABLE"].scan = fail_scan
    with pytest.raises(h.HevyLegacyLookupError):
        h._apply_hevy_workout(
            _hevy_workout("unsafe-identity"),
            {},
            tables["WORKOUTS_TABLE"],
            tables["EXERCISES_TABLE"],
            force=False,
        )
    assert tables["WORKOUTS_TABLE"].items == []
    assert tables["EXERCISES_TABLE"].items == []


def test_incremental_poll_preserves_existing_legacy_date_key():
    h, tables = _fresh_module()
    workout = {
        "id": "legacy-incremental",
        "title": "Evening Lift",
        "start_time": "2026-07-02T00:30:00Z",
        "end_time": "2026-07-02T01:30:00Z",
        "exercises": [
            {"title": "Bench", "sets": [{"weight_kg": 60, "reps": 10}]},
        ],
    }
    legacy = h.workout_to_row(workout)
    assert legacy["analysis_date"] == "2026-07-01"
    legacy["date"] = "2026-07-02"
    legacy["volume_lb"] = 0  # ensure the incremental update performs a write
    for key in (
        "analysis_date",
        "analysis_timezone",
        "date_derivation",
        "source_date",
        "source_utc_offset",
        "source_start_time",
        "source_end_time",
    ):
        legacy.pop(key, None)
    tables["WORKOUTS_TABLE"].put_item(Item=legacy)
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": "2026-07-27T00:00:00Z",
    })
    _stub_offline(h, events={"updated": [workout], "deleted": []})

    response = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(response["body"])
    rows = [
        item for item in tables["WORKOUTS_TABLE"].items
        if item["strava_id"] == "hevy_legacy-incremental"
    ]

    assert body["mode"] == "incremental"
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-07-02"
    assert rows[0]["analysis_date"] == "2026-07-01"
    assert rows[0]["legacy_date_preserved"] is True


# ── PR2: incremental sync integrity ────────────────────────────────

@pytest.mark.parametrize(
    ("status", "truncated"),
    [
        ("timeout", False),
        ("rate_limited", False),
        ("vendor_error", False),
        ("malformed", False),
        ("truncated", True),
    ],
)
def test_incomplete_incremental_fetch_never_advances_watermark(status, truncated):
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    failed = hc.HevyWorkoutEventsResult(
        updated=[_hevy_workout("partial")] if status != "timeout" else [],
        deleted=[],
        complete=False,
        truncated=truncated,
        pages_read=1 if status != "timeout" else 0,
        status=status,
        error="sanitized test failure",
    )
    _stub_offline(h, events=failed)

    with pytest.raises(h.HevySyncError, match=status):
        h.lambda_handler({"action": "hevy_poll"}, None)

    watermark = tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]
    assert watermark["last_sync"] == old_watermark
    assert tables["WORKOUTS_TABLE"].items == []
    assert tables["EXERCISES_TABLE"].items == []


def test_complete_empty_poll_advances_to_prefetch_boundary_and_replays_48_hours():
    h, tables = _fresh_module()
    old_watermark = "2026-08-05T12:00:00+00:00"
    sync_started_at = "2026-08-06T13:14:15+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    captured = {}

    def _events(_key, since, **_kwargs):
        captured["since"] = since
        return hc.HevyWorkoutEventsResult.success()

    _stub_offline(h, events=hc.HevyWorkoutEventsResult.success())
    h.fetch_workout_events = _events
    h._now_iso = lambda: sync_started_at

    response = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(response["body"])
    watermark = tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]

    assert body["status"] == "ok"
    assert body["fetched"] == 0
    assert body["fetch_status"] == "empty"
    assert captured["since"] == "2026-08-03T12:00:00+00:00"
    assert watermark["last_sync"] == sync_started_at
    assert watermark["replay_overlap_hours"] == 48


def test_real_empty_events_envelope_page_count_zero_advances_watermark():
    h, tables = _fresh_module()
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": "2026-08-05T12:00:00+00:00",
    })
    _stub_offline(h, events=hc.HevyWorkoutEventsResult.success())

    def _events(key, since, **kwargs):
        return hc.fetch_workout_events(
            key,
            since,
            page_size=kwargs["page_size"],
            max_pages=kwargs["max_pages"],
            http_get=lambda _url, _key: ({
                "page": 1,
                "page_count": 0,
                "events": [],
            }, 200),
        )

    h.fetch_workout_events = _events
    h._now_iso = lambda: "2026-08-06T12:00:00+00:00"

    body = json.loads(h.lambda_handler({"action": "hevy_poll"}, None)["body"])

    assert body["status"] == "ok"
    assert body["fetch_status"] == "empty"
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == "2026-08-06T12:00:00+00:00"


def test_overlap_replays_boundary_events_idempotently():
    h, tables = _fresh_module()
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": "2026-08-05T12:00:00+00:00",
    })
    around_boundary = [
        _hevy_workout("before-boundary", date="2026-08-05"),
        _hevy_workout("after-boundary", date="2026-08-06"),
    ]
    captured_since = []

    def _events(_key, since, **_kwargs):
        captured_since.append(since)
        return hc.HevyWorkoutEventsResult.success(updated=around_boundary)

    _stub_offline(h, events=hc.HevyWorkoutEventsResult.success())
    h.fetch_workout_events = _events
    h._now_iso = lambda: "2026-08-06T12:00:00+00:00"

    h.lambda_handler({"action": "hevy_poll"}, None)
    h.lambda_handler({"action": "hevy_poll"}, None)

    ids = [row["strava_id"] for row in tables["WORKOUTS_TABLE"].items]
    assert ids.count("hevy_before-boundary") == 1
    assert ids.count("hevy_after-boundary") == 1
    exercise_keys = {
        (row["canonical"], row["date"])
        for row in tables["EXERCISES_TABLE"].items
    }
    assert len(exercise_keys) == len(tables["EXERCISES_TABLE"].items)
    assert captured_since == [
        "2026-08-03T12:00:00+00:00",
        "2026-08-04T12:00:00+00:00",
    ]


def test_deletion_event_replay_is_idempotent():
    h, tables = _fresh_module()
    workout = _hevy_workout("deleted-workout")
    _stub_offline(h, workouts=[workout])
    h.lambda_handler({"action": "hevy_poll"}, None)
    assert tables["WORKOUTS_TABLE"].items
    assert tables["EXERCISES_TABLE"].items

    deletion = hc.HevyWorkoutEventsResult.success(deleted=["deleted-workout"])
    _stub_offline(h, events=deletion)
    first = json.loads(h.lambda_handler({"action": "hevy_poll"}, None)["body"])
    second = json.loads(h.lambda_handler({"action": "hevy_poll"}, None)["body"])

    assert first["deleted"] == 1
    assert second["deleted"] == 0
    assert tables["WORKOUTS_TABLE"].items == []
    assert tables["EXERCISES_TABLE"].items == []


def test_deletion_apply_failure_is_observable_and_preserves_watermark():
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    _stub_offline(
        h,
        events=hc.HevyWorkoutEventsResult.success(deleted=["cannot-delete"]),
    )

    def _fail_scan(**_kwargs):
        raise RuntimeError("simulated deletion lookup failure")

    tables["WORKOUTS_TABLE"].scan = _fail_scan
    with pytest.raises(h.HevySyncError, match="deletion apply failed"):
        h.lambda_handler({"action": "hevy_poll"}, None)

    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == old_watermark


def test_partial_run_recomputes_prior_write_then_fails_without_watermark_advance():
    h, tables = _fresh_module()
    workouts_table = tables["WORKOUTS_TABLE"]
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    workouts = [_hevy_workout("a"), _hevy_workout("b", date="2026-07-01")]
    _stub_offline(h, events={"updated": workouts, "deleted": []})

    scan_calls = {"count": 0}

    def _fail_second_lookup(**_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 2:
            raise RuntimeError("simulated legacy lookup failure")
        return {"Items": []}

    workouts_table.scan = _fail_second_lookup
    recomputes = {"prs": [], "weekly": 0, "dates": []}
    h.recompute_prs_for_canonicals = lambda names: recomputes["prs"].append(names)
    h.recompute_weekly_volume = lambda: recomputes.__setitem__(
        "weekly", recomputes["weekly"] + 1
    )
    h._trigger_compute = lambda date: recomputes["dates"].append(date)

    with pytest.raises(h.HevySyncError, match="legacy lookup failed"):
        h.lambda_handler({"action": "hevy_poll"}, None)

    assert {row["strava_id"] for row in workouts_table.items} == {"hevy_a"}
    assert recomputes == {
        "prs": [["bench_press"]],
        "weekly": 1,
        "dates": ["2026-06-30"],
    }
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == old_watermark

    # Retry: A cheap-skips, B safely lands, and identity-keyed rows stay unique.
    workouts_table.scan = lambda **_kwargs: {"Items": list(workouts_table.items)}
    h.lambda_handler({"action": "hevy_poll"}, None)
    ids = [row["strava_id"] for row in workouts_table.items]
    assert ids.count("hevy_a") == 1
    assert ids.count("hevy_b") == 1


def test_incomplete_measurement_fetch_does_not_advance_workout_watermark():
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    _stub_offline(h, events=hc.HevyWorkoutEventsResult.success())
    h.fetch_body_measurements = lambda _key, **_kwargs: hc.HevyFetchResult(
        [], False, False, 0, "vendor_error", "status 503"
    )

    with pytest.raises(h.HevySyncError, match="body-measurement sync incomplete"):
        h.lambda_handler({"action": "hevy_poll"}, None)

    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == old_watermark


def test_good_record_applies_before_bad_record_requires_operator_review(caplog):
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    issue = {
        "record_id": "bad-workout",
        "event_type": "updated",
        "reason": "start_time cannot derive an analysis date",
    }
    events = hc.HevyWorkoutEventsResult(
        updated=[_hevy_workout("good-workout")],
        deleted=[],
        complete=True,
        truncated=False,
        pages_read=1,
        status="records_degraded",
        record_issues=(issue,),
    )
    _stub_offline(h, events=events)
    recomputes = {"prs": [], "weekly": 0, "dates": []}
    h.recompute_prs_for_canonicals = lambda names: recomputes["prs"].append(names)
    h.recompute_weekly_volume = lambda: recomputes.__setitem__(
        "weekly", recomputes["weekly"] + 1
    )
    h._trigger_compute = lambda date: recomputes["dates"].append(date)

    with pytest.raises(h.HevyRecordIssueError) as raised:
        h.lambda_handler({"action": "hevy_poll"}, None)

    assert raised.value.record_issues == (issue,)
    assert "id=bad-workout" in str(raised.value)
    assert "start_time cannot derive an analysis date" in str(raised.value)
    assert "id=bad-workout type=updated" in caplog.text
    assert {row["strava_id"] for row in tables["WORKOUTS_TABLE"].items} == {
        "hevy_good-workout"
    }
    assert recomputes == {
        "prs": [["bench_press"]],
        "weekly": 1,
        "dates": ["2026-06-30"],
    }
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == old_watermark


def test_reviewed_bad_record_override_recovers_and_advances_watermark(caplog):
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    sync_started_at = "2026-08-06T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    issue = {
        "record_id": "bad-workout",
        "event_type": "updated",
        "reason": "start_time cannot derive an analysis date",
    }
    events = hc.HevyWorkoutEventsResult(
        updated=[_hevy_workout("good-workout")],
        deleted=[],
        complete=True,
        truncated=False,
        pages_read=1,
        status="records_degraded",
        record_issues=(issue,),
    )
    _stub_offline(h, events=events)
    h._now_iso = lambda: sync_started_at

    body = json.loads(h.lambda_handler({
        "action": "hevy_poll",
        "skip_invalid_workout_ids": ["bad-workout"],
    }, None)["body"])

    assert body["status"] == "ok_with_reviewed_skips"
    assert body["reviewed_skips"] == [issue]
    assert "intentionally skipped after review: id=bad-workout" in caplog.text
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == sync_started_at
    assert {row["strava_id"] for row in tables["WORKOUTS_TABLE"].items} == {
        "hevy_good-workout"
    }


def test_unknown_event_does_not_wedge_known_workout_or_watermark():
    h, tables = _fresh_module()
    sync_started_at = "2026-08-06T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": "2026-08-01T12:00:00+00:00",
    })
    ignored = {
        "record_id": "future-event",
        "event_type": "archived",
        "reason": "unsupported event type",
    }
    _stub_offline(h, events=hc.HevyWorkoutEventsResult(
        updated=[_hevy_workout("known-workout")],
        deleted=[],
        complete=True,
        truncated=False,
        pages_read=1,
        status="ok_with_ignored_events",
        ignored_events=(ignored,),
    ))
    h._now_iso = lambda: sync_started_at

    body = json.loads(h.lambda_handler({"action": "hevy_poll"}, None)["body"])

    assert body["status"] == "ok_with_ignored_events"
    assert body["ignored_events"] == [ignored]
    assert {row["strava_id"] for row in tables["WORKOUTS_TABLE"].items} == {
        "hevy_known-workout"
    }
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == sync_started_at


def test_bad_record_override_cannot_skip_unreported_healthy_id():
    h, tables = _fresh_module()
    issue = {
        "record_id": "bad-workout",
        "event_type": "updated",
        "reason": "start_time cannot derive an analysis date",
    }
    _stub_offline(h, events=hc.HevyWorkoutEventsResult(
        updated=[_hevy_workout("healthy-workout")],
        deleted=[],
        complete=True,
        truncated=False,
        pages_read=1,
        status="records_degraded",
        record_issues=(issue,),
    ))
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": "2026-08-01T12:00:00+00:00",
    })

    with pytest.raises(ValueError, match="IDs not present in record issues"):
        h.lambda_handler({
            "action": "hevy_poll",
            "skip_invalid_workout_ids": ["healthy-workout"],
        }, None)

    assert tables["WORKOUTS_TABLE"].items == []


def test_reviewed_bad_record_override_recovers_backfill():
    h, tables = _fresh_module()
    issue = {
        "record_id": "bad-backfill",
        "event_type": "workout",
        "reason": "start_time cannot derive an analysis date",
    }
    h.fetch_recent_workouts_full = lambda _key, **_kwargs: hc.HevyFetchResult(
        [_hevy_workout("good-backfill")],
        True,
        False,
        1,
        "records_degraded",
        record_issues=(issue,),
    )
    h.fetch_exercise_templates = lambda _key, **_kwargs: {}
    h.fetch_body_measurements = lambda _key, **_kwargs: hc.HevyFetchResult.success([])
    h.recompute_prs_for_canonicals = lambda *_args, **_kwargs: {}
    h.recompute_weekly_volume = lambda *_args, **_kwargs: {}

    body = json.loads(h.lambda_handler({
        "action": "hevy_backfill",
        "skip_invalid_workout_ids": ["bad-backfill"],
    }, None)["body"])

    assert body["status"] == "ok_with_reviewed_skips"
    assert {row["strava_id"] for row in tables["WORKOUTS_TABLE"].items} == {
        "hevy_good-backfill"
    }


def test_repeated_transport_failures_freeze_then_success_uses_its_own_boundary():
    h, tables = _fresh_module()
    old_watermark = "2026-08-01T12:00:00+00:00"
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_last_sync",
        "last_sync": old_watermark,
    })
    results = iter([
        hc.HevyWorkoutEventsResult([], [], False, False, 0, "timeout"),
        hc.HevyWorkoutEventsResult([], [], False, False, 0, "vendor_error"),
        hc.HevyWorkoutEventsResult.success(),
    ])
    _stub_offline(h, events=hc.HevyWorkoutEventsResult.success())
    h.fetch_workout_events = lambda *_args, **_kwargs: next(results)
    now_values = iter([
        "2026-08-02T10:00:00+00:00",
        "2026-08-03T11:00:00+00:00",
        "2026-08-04T12:00:00+00:00",
        "2026-08-04T12:00:01+00:00",
    ])
    h._now_iso = lambda: next(now_values)

    for expected_status in ("timeout", "vendor_error"):
        with pytest.raises(h.HevySyncError, match=expected_status):
            h.lambda_handler({"action": "hevy_poll"}, None)
        assert tables["USER_CONFIG_TABLE"].get_item(
            Key={"key": "hevy_last_sync"}
        )["Item"]["last_sync"] == old_watermark

    body = json.loads(h.lambda_handler({"action": "hevy_poll"}, None)["body"])
    assert body["sync_started_at"] == "2026-08-04T12:00:00+00:00"
    assert tables["USER_CONFIG_TABLE"].get_item(
        Key={"key": "hevy_last_sync"}
    )["Item"]["last_sync"] == "2026-08-04T12:00:00+00:00"


def test_backfill_default_page_span_covers_full_history():
    """The backfill default max_pages (20) × pageSize (10) covers >= 200
    workouts — enough for Mateo's full history — without an event override."""
    h, tables = _fresh_module()

    captured = {}

    def _capture(key, **kw):
        captured.update(kw)
        return hc.HevyFetchResult.success([])

    h.fetch_recent_workouts_full = _capture
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: hc.HevyFetchResult.success([])
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
    assert result.complete is True
    assert len(result.items) == 1
    assert result.items[0]["weight_kg"] == 80.0
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
    with pytest.raises(h2.HevySyncError, match="body-measurement sync incomplete"):
        h2.lambda_handler({"action": "hevy_poll"}, None)


def test_measurements_written_when_present():
    """When measurements exist, they are written and the summary reports 'ok'
    with the available count."""
    h, tables = _fresh_module()
    _stub_offline(h, workouts=[])
    h.fetch_body_measurements = lambda key, **kw: hc.HevyFetchResult.success([
        {"date": "2026-05-20", "weight_kg": 80.0, "waist": 81.28},
    ])
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    body = json.loads(resp["body"])
    assert body["measurements_status"] == "ok"
    assert body["measurements_available"] == 1
    assert body["measurements_written"] == 2  # weight + waist
    metrics = tables["HEALTH_METRICS_TABLE"]
    assert {"weight#hevy", "waist#hevy"} <= {i["metric_source"] for i in metrics.items}
