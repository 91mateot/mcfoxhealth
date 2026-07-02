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
    def __init__(self):
        self.items = []

    def put_item(self, Item=None, **_kw):
        # Upsert by composite key (date, strava_id) to mirror DynamoDB.
        key = (Item.get("date"), Item.get("strava_id"))
        self.items = [i for i in self.items if (i.get("date"), i.get("strava_id")) != key]
        self.items.append(Item)

    def get_item(self, Key=None, **_kw):
        if not Key:
            return {}
        for item in reversed(self.items):
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": item}
        return {}


def _fresh_module():
    import importlib  # noqa: F401
    import shared.db as db_mod
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


# ── Hevy sync ───────────────────────────────────────────────────────

def test_hevy_sync_writes_rows():
    h, t = _fresh_module()
    from shared.hevy_client import workout_to_row
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    h._fetch_hevy_workouts = lambda key, **kw: [
        workout_to_row(_hevy_workout("a")),
        workout_to_row(_hevy_workout("b")),
    ]
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "ok"
    assert body["written"] == 2
    assert {i["strava_id"] for i in t.items} == {"hevy_a", "hevy_b"}


def test_hevy_sync_is_idempotent():
    h, t = _fresh_module()
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    from shared.hevy_client import workout_to_row
    row = workout_to_row(_hevy_workout("a"))
    h._fetch_hevy_workouts = lambda key, **kw: [dict(row)]
    h.lambda_handler({"action": "hevy_poll"}, None)
    # Second identical run should skip the write (no change).
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert body["written"] == 0
    assert len([i for i in t.items if i["strava_id"] == "hevy_a"]) == 1


def test_hevy_sync_missing_key_degrades():
    h, t = _fresh_module()
    h._get_secret = lambda name: None  # secret not created yet
    resp = h.lambda_handler({"action": "hevy_poll"}, None)
    import json
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "skipped"
    assert "missing" in body["reason"]
    assert t.items == []


def test_hevy_sync_via_eventbridge_source():
    h, t = _fresh_module()
    h._get_secret = lambda name: {"api_key": "k"} if name == "hevy-api-key" else None
    from shared.hevy_client import workout_to_row
    h._fetch_hevy_workouts = lambda key, **kw: [workout_to_row(_hevy_workout("a"))]
    resp = h.lambda_handler({"source": "aws.events", "resources": ["x"]}, None)
    import json
    assert json.loads(resp["body"])["written"] == 1


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
