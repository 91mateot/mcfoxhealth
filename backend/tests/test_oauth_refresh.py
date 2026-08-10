"""Offline regression tests for concurrency-safe Withings/Strava OAuth."""

import importlib.util
import json
import os
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

from shared.oauth_service import OAuthRefreshError, OAuthService, VENDORS  # noqa: E402


NOW = 1_800_000_000
_INGEST_PATH = os.path.join(ROOT, "functions", "ingest", "handler.py")


class FakeSecrets:
    def __init__(self, values):
        self.values = deepcopy(values)
        self.get_calls = []
        self.update_calls = []
        self.fail_updates = 0

    def get_secret_value(self, SecretId):
        self.get_calls.append(SecretId)
        return {"SecretString": json.dumps(self.values[SecretId])}

    def update_secret(self, SecretId, SecretString):
        self.update_calls.append(SecretId)
        if self.fail_updates:
            self.fail_updates -= 1
            raise RuntimeError("simulated secret write failure")
        self.values[SecretId] = json.loads(SecretString)


class FakeConfigTable:
    def __init__(self):
        self.items = {}
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ClientError
                )
            )
        )

    def update_item(
        self,
        Key,
        UpdateExpression,
        ExpressionAttributeValues,
        ConditionExpression=None,
        ExpressionAttributeNames=None,
    ):
        key = Key["key"]
        item = self.items.setdefault(key, {"key": key})

        if key.startswith("oauth_refresh_lease#"):
            if "REMOVE lease_owner" in UpdateExpression:
                item["updated_at"] = ExpressionAttributeValues[":updated_at"]
                item.pop("lease_owner", None)
                item.pop("lease_expires_at", None)
                return {}

            now = (
                ExpressionAttributeValues[":lease_expires_at"]
                - OAuthService.LEASE_SECONDS
            )
            if item.get("lease_expires_at", -1) >= now:
                raise _conditional_failure()
            item.update(
                lease_owner=ExpressionAttributeValues[":owner"],
                lease_expires_at=ExpressionAttributeValues[":lease_expires_at"],
                updated_at=ExpressionAttributeValues[":updated_at"],
            )
            return {}

        for name_key, field_name in (ExpressionAttributeNames or {}).items():
            index = name_key.removeprefix("#f")
            item[field_name] = ExpressionAttributeValues[f":v{index}"]
        return {}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _conditional_failure():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "busy"}},
        "UpdateItem",
    )


def _secret(vendor, *, expires_at):
    return {
        "client_id": f"{vendor}-client",
        "client_secret": f"{vendor}-secret",
        "access_token": f"{vendor}-access-old",
        "refresh_token": f"{vendor}-refresh-old",
        "expires_at": expires_at,
        "verify_token": "preserve-me",
        "custom_metadata": {"owner": "mateo"},
    }


def _payload(vendor):
    body = {
        "access_token": f"{vendor}-access-new",
        "refresh_token": f"{vendor}-refresh-new",
        "expires_in": VENDORS[vendor].default_expires_in,
    }
    if vendor == "withings":
        body["userid"] = 42
        return {"status": 0, "body": body}
    body["expires_at"] = NOW + VENDORS[vendor].default_expires_in
    return body


def _service(vendor, *, expires_at, table=None, secrets=None, urlopen=None, sleep=None):
    table = table or FakeConfigTable()
    secrets = secrets or FakeSecrets({VENDORS[vendor].secret_id: _secret(vendor, expires_at=expires_at)})
    calls = []

    def default_urlopen(_request, timeout):
        calls.append(timeout)
        return FakeResponse(_payload(vendor))

    service = OAuthService(
        secrets,
        lambda: table,
        now=lambda: NOW,
        sleep=sleep or (lambda _seconds: None),
        urlopen=urlopen or default_urlopen,
    )
    return service, secrets, table, calls


@pytest.mark.parametrize("vendor", ["withings", "strava"])
def test_refresh_boundary_and_noop(vendor):
    buffer_seconds = VENDORS[vendor].refresh_buffer_seconds

    valid, _secrets, _table, calls = _service(
        vendor, expires_at=NOW + buffer_seconds + 1
    )
    assert valid.ensure_access_token(vendor) == f"{vendor}-access-old"
    assert calls == []

    due, secrets, table, calls = _service(
        vendor, expires_at=NOW + buffer_seconds
    )
    assert due.ensure_access_token(vendor) == f"{vendor}-access-new"
    assert calls == [15]
    assert secrets.values[VENDORS[vendor].secret_id]["refresh_token"] == f"{vendor}-refresh-new"
    assert table.items[f"oauth_status#{vendor}"]["state"] == "healthy"


@pytest.mark.parametrize("vendor", ["withings", "strava"])
def test_rotation_preserves_unknown_secret_fields(vendor):
    service, secrets, table, _calls = _service(vendor, expires_at=NOW)

    service.ensure_access_token(vendor)

    saved = secrets.values[VENDORS[vendor].secret_id]
    assert saved["access_token"] == f"{vendor}-access-new"
    assert saved["refresh_token"] == f"{vendor}-refresh-new"
    assert saved["verify_token"] == "preserve-me"
    assert saved["custom_metadata"] == {"owner": "mateo"}
    status = table.items[f"oauth_status#{vendor}"]
    assert "access_token" not in status
    assert "refresh_token" not in status


def test_concurrent_force_refresh_uses_token_written_by_lease_owner():
    vendor = "withings"
    table = FakeConfigTable()
    table.items[f"oauth_refresh_lease#{vendor}"] = {
        "key": f"oauth_refresh_lease#{vendor}",
        "lease_owner": "other-invocation",
        "lease_expires_at": NOW + 30,
    }
    secrets = FakeSecrets({VENDORS[vendor].secret_id: _secret(vendor, expires_at=NOW)})
    sleeps = {"count": 0}

    def peer_finishes(_seconds):
        sleeps["count"] += 1
        if sleeps["count"] == 1:
            secrets.values[VENDORS[vendor].secret_id].update(
                access_token="withings-access-peer",
                refresh_token="withings-refresh-peer",
                expires_at=NOW + 10_800,
            )

    def must_not_refresh(*_args, **_kwargs):
        raise AssertionError("contending invocation must not call provider token endpoint")

    service = OAuthService(
        secrets,
        lambda: table,
        now=lambda: NOW,
        sleep=peer_finishes,
        urlopen=must_not_refresh,
    )

    token = service.ensure_access_token(
        vendor,
        force=True,
        failed_access_token="withings-access-old",
    )

    assert token == "withings-access-peer"
    assert secrets.update_calls == []


def test_failed_refresh_is_sanitized_and_releases_lease():
    vendor = "withings"
    service, secrets, table, _calls = _service(
        vendor,
        expires_at=NOW,
        urlopen=lambda *_a, **_k: FakeResponse(
            {"status": 500, "error": "do not persist vendor body"}
        ),
    )

    with pytest.raises(OAuthRefreshError) as exc_info:
        service.ensure_access_token(vendor)

    assert exc_info.value.code == "vendor_status_500"
    assert secrets.update_calls == []
    assert "lease_owner" not in table.items[f"oauth_refresh_lease#{vendor}"]
    status = table.items[f"oauth_status#{vendor}"]
    assert status["state"] == "error"
    assert status["failure_code"] == "vendor_status_500"
    assert "access_token" not in status
    assert "refresh_token" not in status


def test_secret_persistence_retries_before_returning_rotated_token():
    vendor = "strava"
    service, secrets, _table, _calls = _service(vendor, expires_at=NOW)
    secrets.fail_updates = 2

    assert service.ensure_access_token(vendor) == "strava-access-new"
    assert len(secrets.update_calls) == 3


def test_daily_check_is_safe_noop_for_usable_tokens():
    table = FakeConfigTable()
    secrets = FakeSecrets({
        VENDORS["withings"].secret_id: _secret(
            "withings", expires_at=NOW + VENDORS["withings"].refresh_buffer_seconds + 1
        ),
        VENDORS["strava"].secret_id: _secret(
            "strava", expires_at=NOW + VENDORS["strava"].refresh_buffer_seconds + 1
        ),
    })

    def must_not_refresh(*_args, **_kwargs):
        raise AssertionError("valid scheduled check must not call provider token endpoint")

    service = OAuthService(
        secrets,
        lambda: table,
        now=lambda: NOW,
        sleep=lambda _seconds: None,
        urlopen=must_not_refresh,
    )

    results = service.check_credentials()

    assert results == {
        "withings": {"state": "valid", "expires_at": NOW + 601},
        "strava": {"state": "valid", "expires_at": NOW + 3601},
    }
    assert secrets.update_calls == []
    assert table.items["oauth_status#withings"]["last_check_result"] == "valid"
    assert table.items["oauth_status#strava"]["last_check_result"] == "valid"


def _fresh_handler():
    for name in list(sys.modules):
        if name == "ingest_oauth_handler_under_test":
            sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        "ingest_oauth_handler_under_test", _INGEST_PATH
    )
    handler = importlib.util.module_from_spec(spec)
    sys.modules["ingest_oauth_handler_under_test"] = handler
    spec.loader.exec_module(handler)
    handler._trigger_compute = lambda *_a, **_k: None
    handler.put_item = lambda *_a, **_k: None
    handler.get_table = lambda _env: None
    return handler


def test_strava_401_forces_one_refresh_and_retries_with_new_token(monkeypatch):
    handler = _fresh_handler()
    monkeypatch.setattr(handler, "_ensure_oauth_access_token", lambda *_a, **_k: "old-token")
    refresh_calls = []
    monkeypatch.setattr(
        handler,
        "_refresh_strava_token",
        lambda failed=None: refresh_calls.append(failed) or "new-token",
    )
    fetch_tokens = []

    def fake_get(url, token):
        fetch_tokens.append(token)
        if "streams" in url:
            return [], 200
        if token == "old-token":
            return None, 401
        return {
            "name": "Run",
            "sport_type": "Run",
            "elapsed_time": 1800,
            "average_heartrate": 140,
            "max_heartrate": 160,
            "calories": 250,
            "start_date_local": "2026-08-09T07:00:00Z",
        }, 200

    monkeypatch.setattr(handler, "_strava_get", fake_get)
    event = {
        "body": json.dumps(
            {"object_type": "activity", "aspect_type": "create", "object_id": 123}
        )
    }

    response = handler._handle_strava(event)

    assert response["statusCode"] == 200
    assert refresh_calls == ["old-token"]
    assert fetch_tokens[:2] == ["old-token", "new-token"]


def test_withings_401_forces_one_refresh_and_retries_with_new_token(monkeypatch):
    handler = _fresh_handler()
    monkeypatch.setattr(
        handler,
        "_get_secret",
        lambda _name: {"access_token": "old-token", "userid": "42"},
    )
    monkeypatch.setattr(handler, "_ensure_oauth_access_token", lambda *_a, **_k: "old-token")
    refresh_calls = []
    monkeypatch.setattr(
        handler,
        "_refresh_withings_token",
        lambda failed=None: refresh_calls.append(failed) or "new-token",
    )
    fetch_tokens = []

    def fake_getmeas(token, *_args):
        fetch_tokens.append(token)
        if token == "old-token":
            return {"status": 401}
        return {"status": 0, "body": {"measuregrps": []}}

    monkeypatch.setattr(handler, "_withings_getmeas", fake_getmeas)
    response = handler._handle_withings(
        {"body": "userid=42&appli=1&startdate=1&enddate=2", "isBase64Encoded": False}
    )

    assert response["statusCode"] == 200
    assert refresh_calls == ["old-token"]
    assert fetch_tokens == ["old-token", "new-token"]


def test_oauth_secrets_bypass_warm_handler_cache(monkeypatch):
    handler = _fresh_handler()
    handler._secret_cache["strava-oauth"] = {"access_token": "stale"}
    monkeypatch.setattr(
        handler.oauth_service,
        "get_secret",
        lambda vendor: {"access_token": f"fresh-{vendor}"},
    )

    assert handler._get_secret("strava-oauth") == {"access_token": "fresh-strava"}


def test_scheduled_action_dispatches_to_oauth_check(monkeypatch):
    handler = _fresh_handler()
    monkeypatch.setattr(
        handler.oauth_service,
        "check_credentials",
        lambda: {
            "withings": {"state": "valid", "expires_at": NOW + 601},
            "strava": {"state": "valid", "expires_at": NOW + 3601},
        },
    )
    monkeypatch.setattr(
        handler,
        "_handle_hevy_sync",
        lambda _event: pytest.fail("OAuth schedule must not dispatch to Hevy"),
    )

    response = handler.lambda_handler({"action": "oauth_credential_check"}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ok"
