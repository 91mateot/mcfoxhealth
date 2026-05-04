"""Webhook authentication tests for /ingest/strava and /ingest/withings.

Strava signs event POSTs with X-Strava-Signature (HMAC-SHA256 of `t.body`).
Withings doesn't sign, but we reject notifications for unknown userids when
an allowlist is configured. These tests exercise the handler verification
paths without hitting AWS.
"""

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

# Load the ingest handler under a stable, unique name so we never collide
# with the compute or api handlers (all named `handler` in their packages).
_INGEST_PATH = os.path.join(ROOT, "functions", "ingest", "handler.py")


def _fresh_handler(monkeypatch):
    """Reload the ingest handler with db + Strava API + compute-trigger
    stubbed so the tests only exercise verification logic."""
    for mod in list(sys.modules):
        if mod == "shared" or mod.startswith("shared.") or mod == "ingest_handler_under_test":
            sys.modules.pop(mod, None)

    spec = importlib.util.spec_from_file_location("ingest_handler_under_test", _INGEST_PATH)
    handler = importlib.util.module_from_spec(spec)
    sys.modules["ingest_handler_under_test"] = handler
    spec.loader.exec_module(handler)

    handler._trigger_compute = lambda *_a, **_k: None
    handler._strava_get = lambda *_a, **_k: (None, 502)  # force short-circuit if verification passes
    handler._refresh_strava_token = lambda: "tok"
    handler._now_iso = lambda: "2026-05-04T00:00:00Z"
    handler.put_item = lambda *_a, **_k: None
    handler.get_table = lambda _env: None
    return handler


def _sign_strava_body(secret: str, ts: int, raw_body: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{ts}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _strava_event(raw_body: str, headers: dict | None = None) -> dict:
    return {
        "rawPath": "/ingest/strava",
        "requestContext": {"http": {"method": "POST"}},
        "headers": headers or {},
        "body": raw_body,
        "isBase64Encoded": False,
    }


def test_strava_webhook_rejects_missing_signature(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {"client_secret": "topsecret"})

    body = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 123})
    resp = handler._handle_strava(_strava_event(body))
    assert resp["statusCode"] == 401


def test_strava_webhook_accepts_valid_signature(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    secret_val = "topsecret"
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "client_secret": secret_val,
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
    })

    body = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 123})
    ts = int(time.time())
    sig = _sign_strava_body(secret_val, ts, body)
    resp = handler._handle_strava(_strava_event(body, {
        "x-strava-signature": f"t={ts},v1={sig}",
    }))
    # Verification passes → handler proceeds; the stubbed _strava_get returns
    # 502, which is what we expect here. 401 would mean verification failed.
    assert resp["statusCode"] != 401


def test_strava_webhook_rejects_expired_timestamp(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    secret_val = "topsecret"
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {"client_secret": secret_val})

    body = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 1})
    ts = int(time.time()) - 3600  # 1h ago, well outside 5min tolerance
    sig = _sign_strava_body(secret_val, ts, body)
    resp = handler._handle_strava(_strava_event(body, {
        "x-strava-signature": f"t={ts},v1={sig}",
    }))
    assert resp["statusCode"] == 401


def test_strava_webhook_rejects_tampered_body(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    secret_val = "topsecret"
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {"client_secret": secret_val})

    original = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 1})
    tampered = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 9999})
    ts = int(time.time())
    # Sign the original, send the tampered body.
    sig = _sign_strava_body(secret_val, ts, original)
    resp = handler._handle_strava(_strava_event(tampered, {
        "x-strava-signature": f"t={ts},v1={sig}",
    }))
    assert resp["statusCode"] == 401


def test_strava_webhook_prefers_signing_secret_when_present(monkeypatch):
    """If the secret carries an explicit signing_secret, we use that over
    client_secret. Otherwise we fall back. Both shapes should verify."""
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "client_secret": "wrong_key",
        "signing_secret": "right_key",
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
    })

    body = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 1})
    ts = int(time.time())
    sig = _sign_strava_body("right_key", ts, body)
    resp = handler._handle_strava(_strava_event(body, {
        "x-strava-signature": f"t={ts},v1={sig}",
    }))
    assert resp["statusCode"] != 401


def test_strava_webhook_verification_bypass_flag(monkeypatch):
    """Setting STRAVA_WEBHOOK_VERIFY=0 skips the signature check. Useful for
    local invocation only; not enabled in prod."""
    monkeypatch.setenv("STRAVA_WEBHOOK_VERIFY", "0")
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "client_secret": "x",
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
    })

    body = json.dumps({"object_type": "activity", "aspect_type": "create", "object_id": 1})
    resp = handler._handle_strava(_strava_event(body))  # no signature header
    assert resp["statusCode"] != 401


def test_withings_rejects_unknown_userid_when_allowlist_set(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
        "user_id": "42",
    })

    event = {
        "rawPath": "/ingest/withings",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": "userid=9999&appli=1&startdate=1&enddate=2",
        "isBase64Encoded": False,
    }
    resp = handler._handle_withings(event)
    # We return 200 with status=ignored so Withings doesn't retry forever, but
    # the inner getmeas call is skipped — resp body reflects that.
    assert resp["statusCode"] == 200
    assert "ignored" in resp["body"]


def test_withings_userid_key_matches_withings_native_field(monkeypatch):
    """The secret written by Withings OAuth uses `userid` (not `user_id`).
    Confirm the native key name is respected as an allowlist source."""
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
        "userid": "42",  # Withings-native snake-less casing
    })
    called = {"n": 0}

    def fake_getmeas(_tok, _s, _e):
        called["n"] += 1
        return {"status": 0, "body": {"measuregrps": []}}

    monkeypatch.setattr(handler, "_withings_getmeas", fake_getmeas)

    event = {
        "rawPath": "/ingest/withings",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": "userid=42&appli=1&startdate=1&enddate=2",
        "isBase64Encoded": False,
    }
    resp = handler._handle_withings(event)
    assert resp["statusCode"] == 200
    assert called["n"] == 1  # passed the allowlist, reached getmeas


def test_withings_accepts_when_no_allowlist_configured(monkeypatch):
    """Backwards-compat path: if the secret has no user_id/userids fields,
    we don't reject on userid (older deployments may not have recorded it)."""
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
    })
    # Stub the Withings API fetch so we don't hit the network; we just want
    # to confirm the handler got past the allowlist gate.
    called = {"n": 0}

    def fake_getmeas(_tok, _s, _e):
        called["n"] += 1
        return {"status": 0, "body": {"measuregrps": []}}

    monkeypatch.setattr(handler, "_withings_getmeas", fake_getmeas)

    event = {
        "rawPath": "/ingest/withings",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": "userid=anything&appli=1&startdate=1&enddate=2",
        "isBase64Encoded": False,
    }
    resp = handler._handle_withings(event)
    assert resp["statusCode"] == 200
    assert called["n"] == 1
