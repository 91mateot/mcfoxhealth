"""Webhook authentication tests for /ingest/withings.

Withings doesn't sign notifications, but we reject them for unknown userids
when an allowlist is configured. Strava webhooks have no per-request
signature — auth is the verify_token handshake at subscription time + URL
secrecy + an activity re-fetch on every event — so there's nothing for us
to verify per-POST.
"""

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

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
    handler._ensure_oauth_access_token = lambda vendor, **_k: (
        handler._get_secret(f"{vendor}-oauth") or {}
    ).get("access_token", "")
    handler._refresh_strava_token = lambda: "tok"
    handler._now_iso = lambda: "2026-05-04T00:00:00Z"
    handler.put_item = lambda *_a, **_k: None
    handler.get_table = lambda _env: None
    return handler


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


def test_withings_absolute_timestamp_uses_home_analysis_date(monkeypatch):
    handler = _fresh_handler(monkeypatch)
    monkeypatch.setattr(handler, "_get_secret", lambda _n: {
        "access_token": "tok",
        "expires_at": int(time.time()) + 3600,
    })
    source_dt = datetime(2026, 7, 2, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(handler, "_withings_getmeas", lambda *_a: {
        "status": 0,
        "body": {
            "measuregrps": [{
                "date": int(source_dt.timestamp()),
                "measures": [{"type": 1, "value": 75, "unit": 0}],
            }],
        },
    })
    written = []
    monkeypatch.setattr(handler, "put_item", lambda _table, item: written.append(item))

    event = {
        "body": "userid=anything&appli=1&startdate=1&enddate=2",
        "isBase64Encoded": False,
    }
    response = handler._handle_withings(event)

    assert response["statusCode"] == 200
    assert len(written) == 1
    assert written[0]["date"] == "2026-07-01"
    assert written[0]["analysis_date"] == "2026-07-01"
    assert written[0]["source_date"] == "2026-07-02"
    assert written[0]["source_time"] == "2026-07-02T00:30:00+00:00"
    assert written[0]["date_derivation"] == "home_timezone"
