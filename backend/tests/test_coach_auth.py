"""Auth tests for the coach FastAPI app.

The Coach Function URL is AuthType=NONE (required for streaming) + a custom
x-api-key header check in the app itself. These tests exercise the header
dependency via FastAPI's TestClient so we don't need AWS, Bedrock, or the
Lambda Web Adapter in the loop.
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
_COACH_PATH = os.path.join(ROOT, "functions", "coach", "app.py")


def _fresh_coach(monkeypatch, api_key: str = "test-key", auth_required: str = "1"):
    """Reload the coach app with a mocked api-key loader and env flag."""
    monkeypatch.setenv("COACH_AUTH_REQUIRED", auth_required)
    monkeypatch.setenv("INGEST_API_KEY", api_key)
    # Kill cached modules so env mutations stick and we don't get a stale app.
    for mod in list(sys.modules):
        if mod in ("coach_under_test",) or mod == "shared" or mod.startswith("shared."):
            sys.modules.pop(mod, None)

    # Stub boto3 before the app imports it (it builds a bedrock + secrets client
    # at module load).
    import boto3
    from unittest.mock import MagicMock
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())

    spec = importlib.util.spec_from_file_location("coach_under_test", _COACH_PATH)
    coach = importlib.util.module_from_spec(spec)
    sys.modules["coach_under_test"] = coach
    spec.loader.exec_module(coach)

    # Secret lookup: skip Secrets Manager, fall back to INGEST_API_KEY.
    coach._api_key_cache["value"] = api_key
    coach._api_key_cache["ts"] = 2 ** 31  # far future so it never refreshes
    return coach


def test_health_is_public(monkeypatch):
    from fastapi.testclient import TestClient
    coach = _fresh_coach(monkeypatch)
    client = TestClient(coach.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_coach_endpoint_rejects_without_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    coach = _fresh_coach(monkeypatch)
    client = TestClient(coach.app)
    r = client.post("/api/coach", json={"messages": [{"from": "me", "text": "hi"}]})
    assert r.status_code == 401


def test_coach_endpoint_rejects_wrong_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    coach = _fresh_coach(monkeypatch, api_key="correct")
    client = TestClient(coach.app)
    r = client.post(
        "/api/coach",
        json={"messages": [{"from": "me", "text": "hi"}]},
        headers={"x-api-key": "wrong"},
    )
    assert r.status_code == 401


def test_coach_endpoint_accepts_correct_api_key(monkeypatch):
    """With a valid key, the auth dep passes and execution proceeds into
    handler body validation. We stop short of a full Bedrock invocation
    by sending an invalid payload, which should yield 400 not 401."""
    from fastapi.testclient import TestClient
    coach = _fresh_coach(monkeypatch, api_key="correct")
    client = TestClient(coach.app)
    r = client.post(
        "/api/coach",
        json={"messages": []},  # empty — handler returns 400
        headers={"x-api-key": "correct"},
    )
    assert r.status_code == 400


def test_coach_auth_bypass_flag(monkeypatch):
    """COACH_AUTH_REQUIRED=0 lets requests through with no header. Used for
    local sam-local / uvicorn invocations only; prod keeps it on."""
    from fastapi.testclient import TestClient
    coach = _fresh_coach(monkeypatch, auth_required="0")
    client = TestClient(coach.app)
    r = client.post("/api/coach", json={"messages": []})
    assert r.status_code == 400  # past auth, fails at empty-body check
