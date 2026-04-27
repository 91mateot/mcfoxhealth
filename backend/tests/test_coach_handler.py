"""
Unit tests for the Coach Lambda (backend/functions/coach/handler.py).

Strategy:
  - Bedrock is stubbed with botocore's Stubber at the module-level client.
  - DynamoDB reads (get_item, query_items) are monkey-patched on shared.db
    so the handler sees predictable scores/nutrition/user-config.
  - No AWS calls, no moto — just unit-level verification of the handler
    contract: input validation, system-prompt assembly, Bedrock wiring,
    response shape, error paths.

Covers:
  1. Happy path (valid messages → 200 with reply.text)
  2. Empty messages list → 400
  3. Malformed JSON body → 400
  4. Last message not from user → 400
  5. Bedrock raises ClientError → 500
  6. System prompt includes today's scores + Retatrutide context
"""
import importlib.util
import json
import os
import sys
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

COACH_HANDLER_PATH = os.path.join(ROOT, "functions", "coach", "handler.py")


def _load_coach_handler():
    """Load the coach handler under a unique module name so it doesn't collide
    with other lambdas' `handler` modules in the same pytest session."""
    spec = importlib.util.spec_from_file_location("coach_handler", COACH_HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["coach_handler"] = module
    spec.loader.exec_module(module)
    return module


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def seed_scores():
    return {
        "date": "2026-04-26",
        "recovery": 72,
        "recovery_zone": "green",
        "hrv": 48,
        "rhr": 62,
        "strain": 8.4,
        "strain_target": {"low": 14, "high": 17, "reason": "Recovered — train hard"},
        "sleep": {"total_min": 463, "efficiency": 93},
    }


@pytest.fixture
def seed_meals():
    return [
        {"meal_id": "meal_1", "p": 30, "cal": 170},
        {"meal_id": "meal_2", "p": 45, "cal": 500},
        {"meal_id": "water_1", "oz": 40},
    ]


@pytest.fixture
def seed_workouts():
    return [
        {
            "date": "2026-04-26",
            "strava_id": "12345",
            "title": "Morning Workout",
            "type": "Workout",
            "dur": 50,
            "avgHR": 112.4,
            "maxHR": 139,
            "cal": 0,
            "strain": 5.6,
            "trimp": 15.5,
            "zones": {"z1": 5, "z2": 3.8, "z3": 1, "z4": 0, "z5": 0},
        }
    ]


@pytest.fixture
def seed_baselines():
    return {
        "type": "current",
        "hrv": 42.0,
        "rhr": 64,
        "resp": 14.5,
        "sleep_min": 450,
        "steps": 10000,
        "spo2": 96.5,
        "wrist_temp": 32.5,
    }


@pytest.fixture
def seed_body_comp():
    """Withings body composition metrics keyed by date."""
    return {
        "2026-04-25": [
            {"metric_source": "weight#withings", "value": 169.2},
            {"metric_source": "fat_ratio#withings", "value": 13.6},
            {"metric_source": "muscle_mass#withings", "value": 142.3},
        ],
    }


@pytest.fixture
def seed_week_scores():
    """Last 7 days of scores for the history block."""
    return {
        "2026-04-25": {"recovery": 38, "recovery_zone": "red", "hrv": 45.5, "rhr": 70, "strain": 10.2, "sleep": {"total_min": 463}},
        "2026-04-24": {"recovery": 82, "recovery_zone": "green", "hrv": 49, "rhr": 60, "strain": 7.5, "sleep": {"total_min": 480}},
    }


@pytest.fixture
def seed_journal():
    return {"date": "2026-04-25", "tags": ["alcohol", "late_meal"], "mood": 3, "stress": 4, "soreness": 2}


@pytest.fixture
def seed_correlations():
    return [
        {"tag": "alcohol", "metric": "HRV", "effect": -18, "unit": "%", "n": 6, "confidence": "high", "direction": "negative"},
        {"tag": "sauna", "metric": "Deep", "effect": 11, "unit": "%", "n": 5, "confidence": "medium", "direction": "positive"},
    ]


@pytest.fixture
def handler_module(
    monkeypatch,
    seed_scores,
    seed_meals,
    seed_workouts,
    seed_baselines,
    seed_body_comp,
    seed_week_scores,
    seed_journal,
    seed_correlations,
):
    """Import a fresh coach.handler with shared.db stubbed and bedrock mocked."""
    import shared.db as db_mod

    def fake_get_table(env_name):
        mock = MagicMock(name=f"Table<{env_name}>")
        mock._env = env_name
        # Correlations block uses `.scan()` directly on the table object
        if env_name == "CORRELATIONS_TABLE":
            mock.scan.return_value = {"Items": seed_correlations}
        return mock

    def fake_get_item(table, key):
        env = getattr(table, "_env", "")
        if env == "DAILY_SCORES_TABLE":
            if key.get("date") == "2026-04-26":
                return seed_scores
            return seed_week_scores.get(key.get("date"))
        if env == "BASELINES_TABLE" and key.get("type") == "current":
            return seed_baselines
        if env == "JOURNAL_TABLE":
            # Most recent journal lookup walks today → 2 days back
            if key.get("date") == seed_journal["date"]:
                return seed_journal
            return None
        if env == "USER_CONFIG_TABLE" and key.get("key") == "mateo":
            return {"key": "mateo"}
        return None

    def fake_query_items(table, _sk, val, **_kw):
        env = getattr(table, "_env", "")
        if val == "2026-04-26":
            if env == "WORKOUTS_TABLE":
                return seed_workouts
            if env == "NUTRITION_TABLE":
                return seed_meals
        if env == "HEALTH_METRICS_TABLE":
            return seed_body_comp.get(val, [])
        return []

    monkeypatch.setattr(db_mod, "get_table", fake_get_table)
    monkeypatch.setattr(db_mod, "get_item", fake_get_item)
    monkeypatch.setattr(db_mod, "query_items", fake_query_items)

    import shared.timezone as tz_mod
    monkeypatch.setattr(tz_mod, "local_today_str", lambda: "2026-04-26")

    sys.modules.pop("coach_handler", None)
    return _load_coach_handler()


def _http_event(body):
    """API Gateway HTTP API v2 event shape."""
    if not isinstance(body, str):
        body = json.dumps(body)
    return {
        "requestContext": {"http": {"method": "POST"}},
        "routeKey": "POST /api/coach",
        "body": body,
        "isBase64Encoded": False,
    }


def _stub_bedrock_response(handler_module, text="Recovery 72% — go train."):
    """Replace the module-level bedrock client with a MagicMock that returns
    a Bedrock-style response body with the given text."""
    body_bytes = json.dumps({
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1234, "output_tokens": 12},
    }).encode()
    mock = MagicMock()
    mock.invoke_model.return_value = {"body": BytesIO(body_bytes)}
    handler_module.bedrock = mock
    return mock


# ─── Tests ─────────────────────────────────────────────────────────

def test_happy_path(handler_module):
    mock = _stub_bedrock_response(handler_module, "Recovery 72% — go train.")
    event = _http_event({"messages": [{"from": "me", "text": "am I clear to train?"}]})
    resp = handler_module.lambda_handler(event, None)

    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["reply"]["from"] == "coach"
    assert body["reply"]["text"] == "Recovery 72% — go train."
    assert "t" in body["reply"]

    # Verify Bedrock was called with the right model + messages
    mock.invoke_model.assert_called_once()
    call_kwargs = mock.invoke_model.call_args.kwargs
    assert call_kwargs["modelId"] == handler_module.MODEL_ID
    sent_body = json.loads(call_kwargs["body"])
    assert sent_body["messages"] == [{"role": "user", "content": "am I clear to train?"}]


def test_no_messages_returns_400(handler_module):
    _stub_bedrock_response(handler_module)
    event = _http_event({"messages": []})
    resp = handler_module.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    assert "no messages provided" in json.loads(resp["body"])["error"]


def test_malformed_json_returns_400(handler_module):
    _stub_bedrock_response(handler_module)
    event = _http_event("not valid json at all")
    resp = handler_module.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    assert "invalid JSON body" in json.loads(resp["body"])["error"]


def test_assistant_not_last_returns_400(handler_module):
    _stub_bedrock_response(handler_module)
    event = _http_event({
        "messages": [
            {"from": "me", "text": "hi"},
            {"from": "coach", "text": "morning"},  # assistant last → invalid
        ]
    })
    resp = handler_module.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    assert "last message must be from user" in json.loads(resp["body"])["error"]


def test_bedrock_exception_returns_500(handler_module):
    mock = MagicMock()
    mock.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad model"}},
        "InvokeModel",
    )
    handler_module.bedrock = mock
    event = _http_event({"messages": [{"from": "me", "text": "hi"}]})
    resp = handler_module.lambda_handler(event, None)

    assert resp["statusCode"] == 500
    assert "bedrock error" in json.loads(resp["body"])["error"]


def test_system_prompt_has_today_data_and_reta(handler_module):
    mock = _stub_bedrock_response(handler_module)
    event = _http_event({"messages": [{"from": "me", "text": "briefing"}]})
    handler_module.lambda_handler(event, None)

    sent_body = json.loads(mock.invoke_model.call_args.kwargs["body"])
    system = sent_body["system"]
    # System may be either a string (pre-cache) or a list of blocks (post-cache).
    # Concatenate for assertion so the test is resilient to Phase C changes.
    if isinstance(system, list):
        system_str = "".join(block.get("text", "") for block in system)
    else:
        system_str = system
    assert "Recovery: 72%" in system_str
    assert "Strain so far: 8.4" in system_str
    assert "Retatrutide" in system_str
    assert "180g" in system_str  # protein target anchor


def test_system_prompt_includes_todays_workouts(handler_module):
    mock = _stub_bedrock_response(handler_module)
    event = _http_event({"messages": [{"from": "me", "text": "did i work out"}]})
    handler_module.lambda_handler(event, None)

    sent_body = json.loads(mock.invoke_model.call_args.kwargs["body"])
    system = sent_body["system"]
    system_str = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    # Workout section header + record details
    assert "Today's Workouts" in system_str
    assert "Morning Workout" in system_str
    assert "50 min" in system_str
    assert "avg HR 112" in system_str
    assert "strain 5.6" in system_str


def test_system_prompt_includes_baselines_and_deltas(handler_module):
    mock = _stub_bedrock_response(handler_module)
    event = _http_event({"messages": [{"from": "me", "text": "how do i look"}]})
    handler_module.lambda_handler(event, None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    # HRV 45.5 vs baseline 42.0 → ~8% above
    assert "baseline 42.0" in s or "baseline 42" in s
    # RHR 70 vs baseline 64 → ~9% above
    assert "baseline 64" in s


def test_system_prompt_includes_sleep_composition(handler_module):
    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "sleep"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    # Deep, REM, Core, Awake must appear
    assert "Deep:" in s
    assert "REM:" in s


def test_system_prompt_includes_extended_vitals(handler_module, seed_scores):
    # Add resp/spo2/wrist_temp to scores so they render
    seed_scores["resp"] = 14.3
    seed_scores["spo2"] = 97.2
    seed_scores["wrist_temp"] = 32.5

    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "vitals"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    assert "Respiratory rate:" in s and "14.3" in s
    assert "SpO2:" in s and "97.2" in s
    assert "Wrist temperature:" in s


def test_system_prompt_includes_body_composition(handler_module):
    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "weight"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    assert "Body Composition" in s
    assert "169.2" in s  # weight
    assert "13.6" in s   # fat ratio


def test_system_prompt_includes_week_history(handler_module):
    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "week"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    assert "Last 7 Days" in s
    assert "2026-04-25" in s  # yesterday


def test_system_prompt_includes_last_journal(handler_module):
    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "what did i do"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    assert "Most Recent Journal" in s
    assert "alcohol" in s
    assert "Mood: 3/5" in s


def test_system_prompt_includes_correlations(handler_module):
    mock = _stub_bedrock_response(handler_module)
    handler_module.lambda_handler(_http_event({"messages": [{"from": "me", "text": "patterns"}]}), None)
    system = json.loads(mock.invoke_model.call_args.kwargs["body"])["system"]
    s = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    assert "Learned Patterns" in s
    assert "alcohol" in s and "HRV" in s
    assert "-18" in s


def test_system_prompt_when_no_workouts_today(handler_module, monkeypatch):
    # Swap the workouts fixture to empty without rewriting the whole chain
    import shared.db as db_mod
    original = db_mod.query_items

    def no_workouts(table, sk, val, **kw):
        env = getattr(table, "_env", "")
        if env == "WORKOUTS_TABLE":
            return []
        return original(table, sk, val, **kw)

    monkeypatch.setattr(db_mod, "query_items", no_workouts)
    # Reload handler so it picks up the patched db
    sys.modules.pop("coach_handler", None)
    fresh = _load_coach_handler()

    mock = _stub_bedrock_response(fresh)
    event = _http_event({"messages": [{"from": "me", "text": "am i clear"}]})
    fresh.lambda_handler(event, None)

    sent_body = json.loads(mock.invoke_model.call_args.kwargs["body"])
    system_str = sent_body["system"] if isinstance(sent_body["system"], str) else "".join(
        b.get("text", "") for b in sent_body["system"]
    )
    assert "No workout logged today yet." in system_str
