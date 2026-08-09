"""
Handler-level tests for the dual-source workout ingest wiring:
  - Hevy scheduled sync (_handle_hevy_sync) upserts rows + is idempotent
  - Missing hevy-api-key secret degrades gracefully (no crash, clear status)
  - Strava webhook drops strength activities (Hevy owns strength)

Runs offline: shared.db and the Hevy fetch/secret helpers are stubbed, so no
AWS and no real Hevy key are required.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))


class FakeTable:
    def __init__(self, key_attrs=("date", "strava_id")):
        self.items = []
        self.key_attrs = key_attrs

    def _key(self, item):
        return tuple(item.get(k) for k in self.key_attrs)

    def put_item(self, Item=None, **_kw):
        # Upsert by composite key to mirror DynamoDB.
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
        # Tests that need filtered scans stub this per-case; default returns all.
        return {"Items": list(self.items)}


# Key schema per DynamoDB table (env-var name → key attribute names).
_TABLE_KEYS = {
    "WORKOUTS_TABLE": ("date", "strava_id"),
    "EXERCISES_TABLE": ("canonical", "date"),
    "USER_CONFIG_TABLE": ("key",),
    "HEALTH_METRICS_TABLE": ("date", "metric_source"),
    "DAILY_SCORES_TABLE": ("date",),
}


def _fresh_module(multi_table=False):
    """Load a fresh handler with stubbed db.

    When ``multi_table`` is False (legacy Strava tests), every get_table call
    returns ONE shared FakeTable. When True, each env var gets its own
    correctly-keyed FakeTable, returned as a dict so Hevy tests can assert on
    the right table.
    """
    import importlib  # noqa: F401
    import shared.db as db_mod

    if multi_table:
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
        return handler, tables

    fake = FakeTable()
    db_mod.get_table = lambda _env: fake
    db_mod.put_item = lambda table, item: table.put_item(Item=item)
    db_mod.get_item = lambda table, key: (table.get_item(Key=key) or {}).get("Item") or {}
    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler  # noqa
    handler._trigger_compute = lambda *_a, **_k: None
    return handler, fake


def _hevy_workout(wid, date="2026-06-30"):
    return {
        "id": wid,
        "title": "Push Day",
        "start_time": f"{date}T18:00:00+00:00",
        "end_time": f"{date}T19:00:00+00:00",
        "exercises": [{"title": "Bench", "sets": [{"weight_kg": 60, "reps": 10}]}],
    }


def _stub_hevy_fetches(h, workouts=None, events=None):
    """Stub the hevy_client fetch functions imported into the handler namespace.

    Also stub the lift recompute + body-measurement helpers so tests stay
    offline and focused on the sync wiring.
    """
    workouts = workouts or []
    h.fetch_recent_workouts_full = lambda key, **kw: list(workouts)
    if events is not None:
        h.fetch_workout_events = lambda key, since, **kw: events
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: []
    h.recompute_prs_for_canonicals = lambda *_a, **_k: {}
    h.recompute_weekly_volume = lambda *_a, **_k: {}


# ── Hevy sync ───────────────────────────────────────────────────────

def test_hevy_sync_writes_rows():
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    _stub_hevy_fetches(h, workouts=[_hevy_workout("a"), _hevy_workout("b")])
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "ok"
    assert body["mode"] == "cold_start"
    assert body["written"] == 2
    workouts = tables["WORKOUTS_TABLE"]
    assert {i["strava_id"] for i in workouts.items} == {"hevy_a", "hevy_b"}
    # Per-exercise rows mirrored into fitness-exercises.
    exercises = tables["EXERCISES_TABLE"]
    assert {i["canonical"] for i in exercises.items} == {"bench_press"}
    assert all(i["source"] == "hevy" for i in exercises.items)
    # Watermark persisted so the next poll goes incremental.
    cfg = tables["USER_CONFIG_TABLE"]
    assert any(i["key"] == "hevy_last_sync" for i in cfg.items)


def test_hevy_sync_is_idempotent():
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    # First poll: cold start (no watermark) writes the workout.
    _stub_hevy_fetches(h, workouts=[_hevy_workout("a")])
    h.lambda_handler({"action": "hevy_poll"}, None)
    # Second poll now sees a watermark → incremental. Re-deliver the SAME
    # workout as an "updated" event; unchanged row must be skipped, not dupe'd.
    _stub_hevy_fetches(h, events={"updated": [_hevy_workout("a")], "deleted": []})
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert body["mode"] == "incremental"
    assert body["written"] == 0
    workouts = tables["WORKOUTS_TABLE"]
    assert len([i for i in workouts.items if i["strava_id"] == "hevy_a"]) == 1


def test_hevy_sync_missing_key_degrades():
    h, fake = _fresh_module()
    h._get_secret = lambda name: None  # secret not created yet
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "skipped"
    assert "missing" in body["reason"]
    assert fake.items == []


def test_hevy_sync_via_eventbridge_source():
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    _stub_hevy_fetches(h, workouts=[_hevy_workout("a")])
    resp = h.lambda_handler({"source": "aws.events", "resources": ["x"]}, None)
    import json
    assert json.loads(resp["body"])["written"] == 1


def test_hevy_sync_deletes_workout_via_events():
    """A workout deleted in Hevy must leave both fitness-workouts AND its
    mirrored fitness-exercises rows."""
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    # Cold-start poll writes workout "a" + its bench_press exercise row.
    _stub_hevy_fetches(h, workouts=[_hevy_workout("a")])
    h.lambda_handler({"action": "hevy_poll"}, None)
    workouts, exercises = tables["WORKOUTS_TABLE"], tables["EXERCISES_TABLE"]
    assert any(i["strava_id"] == "hevy_a" for i in workouts.items)
    assert any(i["canonical"] == "bench_press" for i in exercises.items)

    # Wire the scan filters the delete path relies on (FakeTable.scan ignores
    # filters, so restrict manually to mimic DynamoDB filter semantics).
    def _wk_scan(**kw):
        return {"Items": [i for i in workouts.items if i.get("strava_id") == "hevy_a"]}
    workouts.scan = _wk_scan

    def _ex_scan(**kw):
        return {"Items": [i for i in exercises.items if i.get("source") == "hevy"]}
    exercises.scan = _ex_scan

    # Next poll (incremental) delivers a delete event for "a".
    _stub_hevy_fetches(h, events={"updated": [], "deleted": ["a"]})
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert body["deleted"] == 1
    assert not any(i["strava_id"] == "hevy_a" for i in workouts.items)
    assert not any(i["canonical"] == "bench_press" for i in exercises.items)


def test_hevy_sync_ingests_body_measurements():
    """Body measurements land in fitness-health-metrics under #hevy sources via
    the merge/ordering-guard path (never a bare overwrite)."""
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    _stub_hevy_fetches(h, workouts=[])
    # Override the body-measurement fetch with a real payload.
    h.fetch_body_measurements = lambda key, **kw: [
        {"date": "2026-06-30", "weight_kg": 76.66, "waist": 81.28},
    ]
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert body["measurements_written"] == 2
    metrics = tables["HEALTH_METRICS_TABLE"]
    sources = {i["metric_source"] for i in metrics.items}
    assert "weight#hevy" in sources
    assert "waist#hevy" in sources
    # Ordering guard writes a source_ts so a stale re-fetch can't regress it.
    weight_rows = [i for i in metrics.items if i["metric_source"] == "weight#hevy"]
    assert weight_rows and "source_ts" in weight_rows[0]


def test_hevy_sync_degrades_when_endpoint_errors():
    """A Hevy outage on the cold-start fetch must not crash the cron — the
    handler returns 200 and simply writes nothing."""
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None

    def _boom(*_a, **_k):
        raise RuntimeError("hevy 500")

    h.fetch_recent_workouts_full = _boom
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: []
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "error"
    assert tables["WORKOUTS_TABLE"].items == []


def test_hevy_sync_template_cache_reused_when_fresh():
    """A fresh template cache row is reused — fetch_exercise_templates is NOT
    called again on the poll."""
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    # Seed a fresh cache row.
    from datetime import datetime, timezone
    tables["USER_CONFIG_TABLE"].put_item(Item={
        "key": "hevy_exercise_templates",
        "templates": {"tmpl-bench": {"primary_muscle_group": "chest"}},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })
    calls = {"n": 0}

    def _fetch(*_a, **_k):
        calls["n"] += 1
        return {}

    h.fetch_exercise_templates = _fetch
    workout = _hevy_workout("a")
    workout["exercises"][0]["exercise_template_id"] = "tmpl-bench"
    _stub_hevy_fetches(h, workouts=[workout])
    h.fetch_exercise_templates = _fetch  # re-apply after stub reset
    h.lambda_handler({"action": "hevy_poll"}, None)
    assert calls["n"] == 0  # cache was fresh → no refetch
    # The cached template gave bench_press a real muscle group.
    ex = [i for i in tables["EXERCISES_TABLE"].items if i["canonical"] == "bench_press"]
    assert ex and ex[0]["muscle_group"] == "chest"


def test_hevy_sync_repoll_keeps_pr_flags_clean():
    """Re-polling the same workout must not duplicate exercise rows or corrupt
    PR flags. Uses the REAL recompute so we exercise the full engine path."""
    h, tables = _fresh_module(multi_table=True)
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None

    # Stub fetches but keep the real recompute functions.
    h.fetch_recent_workouts_full = lambda key, **kw: [_hevy_workout("a")]
    h.fetch_workout_events = lambda key, since, **kw: {
        "updated": [_hevy_workout("a")], "deleted": []
    }
    h.fetch_exercise_templates = lambda key, **kw: {}
    h.fetch_body_measurements = lambda key, **kw: []
    # scan_exercise_history queries by canonical; wire lift_compute's OWN
    # db references (it bound get_table/put_item/query_items at import time).
    import shared.db as db_mod
    import shared.lift_compute as lc
    ex_table = tables["EXERCISES_TABLE"]
    scores_table = tables["DAILY_SCORES_TABLE"]

    def _query_items(table, pk_name, pk_value, **kw):
        return [i for i in table.items if i.get(pk_name) == pk_value]

    lc.query_items = _query_items
    lc.put_item = lambda table, item: table.put_item(Item=item)
    lc.get_table = lambda env: ex_table if env == "EXERCISES_TABLE" else scores_table
    db_mod.query_items = _query_items

    h.lambda_handler({"action": "hevy_poll"}, None)
    first = [i for i in ex_table.items if i["canonical"] == "bench_press"]
    assert len(first) == 1
    assert first[0]["pr"]["weight"] is True  # first-ever session is a PR

    # Second poll (incremental) re-delivers the identical workout.
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    assert json.loads(resp["body"])["written"] == 0  # unchanged → skipped
    second = [i for i in ex_table.items if i["canonical"] == "bench_press"]
    assert len(second) == 1  # no duplicate row
    assert second[0]["pr"]["weight"] is True  # PR flag unchanged


# ── Strava strength de-dupe ─────────────────────────────────────────

def _strava_event(body):
    import json
    return {
        "rawPath": "/ingest/strava",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def test_strava_drops_strength_activity():
    h, t = _fresh_module()
    h._get_secret = lambda name: {"access_token": "tok", "expires_at": 9999999999}
    # Return a WeightTraining activity — should be dropped, not written.
    h._strava_get = lambda url, token: (
        {"id": 111, "name": "Lift", "sport_type": "WeightTraining",
         "elapsed_time": 3600, "average_heartrate": 110, "max_heartrate": 150,
         "calories": 200, "start_date_local": "2026-06-30T10:00:00Z"},
        200,
    )
    resp = h.lambda_handler(_strava_event(
        {"object_type": "activity", "aspect_type": "create", "object_id": 111}
    ), None)
    import json
    body = json.loads(resp["body"])
    assert body["status"] == "ignored"
    assert "strength" in body["reason"]
    assert t.items == []


def test_strava_keeps_cardio_activity():
    h, t = _fresh_module()
    h._get_secret = lambda name: {"access_token": "tok", "expires_at": 9999999999}
    calls = {"n": 0}

    def _sget(url, token):
        calls["n"] += 1
        if "streams" in url:
            return [{"type": "heartrate", "data": [140] * 600}], 200
        return (
            {"id": 222, "name": "Morning Run", "sport_type": "Run",
             "elapsed_time": 1800, "average_heartrate": 145, "max_heartrate": 165,
             "calories": 300, "start_date_local": "2026-06-30T07:00:00Z"},
            200,
        )

    h._strava_get = _sget
    resp = h.lambda_handler(_strava_event(
        {"object_type": "activity", "aspect_type": "create", "object_id": 222}
    ), None)
    import json
    body = json.loads(resp["body"])
    assert body.get("strava_id") == "222"
    assert len(t.items) == 1
    assert t.items[0]["type"] == "Run"
    assert t.items[0]["source"] == "strava"
    assert t.items[0]["strain"] > 0
    assert t.items[0]["date"] == "2026-06-30"
    assert t.items[0]["analysis_date"] == "2026-06-30"
    assert t.items[0]["source_date"] == "2026-06-30"
    assert t.items[0]["source_start_time"] == "2026-06-30T07:00:00Z"
    assert t.items[0]["date_derivation"] == "strava_start_date_local"
