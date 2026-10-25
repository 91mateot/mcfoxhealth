"""Offline receiver contract tests using synthetic source rows, never athlete data."""

import copy
import hashlib
import importlib.util
import json
from decimal import Decimal
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prism_steps", ROOT / "functions/prism_steps/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)
DAY = "2026-10-23"
TOKEN = "x" * 43  # Synthetic authentication fixture, not a usable credential.
SUMMARY = "steps#hae_daily_summary"
LEGACY = "steps#hae"


@pytest.fixture
def setup(monkeypatch):
    state = SimpleNamespace(rows={}, reads=[], secret_reads=0, fail=False,
                            secret={"enabled": True, "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                                    "expires_at": "2099-01-01T00:00:00Z"})
    monkeypatch.setenv("PRISM_STEPS_SECRET_ARN", "synthetic-secret")
    monkeypatch.setenv("PRISM_STEPS_ALLOWED_DATE", DAY)
    monkeypatch.setenv("HEALTH_METRICS_TABLE", "fitness-health-metrics")

    class Table:
        def get_item(self, **kwargs):
            state.reads.append(kwargs)
            if state.fail:
                raise RuntimeError("must not be logged")
            row = state.rows.get((kwargs["Key"]["date"], kwargs["Key"]["metric_source"]),
                                 state.rows.get(kwargs["Key"]["metric_source"]))
            return {"Item": copy.deepcopy(row)} if row is not None else {}

    class Secrets:
        def get_secret_value(self, **kwargs):
            state.secret_reads += 1
            assert kwargs == {"SecretId": "synthetic-secret"}
            return {"SecretString": json.dumps(state.secret)}

    def resource(service):
        assert service == "dynamodb"
        return SimpleNamespace(Table=lambda name: Table())

    monkeypatch.setattr(handler.boto3, "resource", resource)
    monkeypatch.setattr(handler.boto3, "client", lambda name: Secrets() if name == "secretsmanager" else None)
    return state


def event(**changes):
    data = {"version": "2.0", "rawPath": handler.PATH,
            "rawQueryString": "date=" + DAY,
            "requestContext": {"http": {"method": "GET"}},
            "headers": {"x-prism-steps-key": TOKEN}}
    data.update(changes)
    return data


def call(data=None):
    result = handler.lambda_handler(data or event(), None)
    assert result["headers"]["cache-control"] == "no-store"
    assert len(result["body"].encode()) < 16384
    return result["statusCode"], json.loads(result["body"])


def row(source=SUMMARY, value=Decimal(0), **metadata):
    return {"date": DAY, "metric_source": source, "value": value, "unit": "count",
            "hae_semantics": "completed_daily_summary" if source == SUMMARY else "raw_observation",
            **metadata}


def test_missing_is_null_and_lookup_is_bounded(setup):
    status, body = call()
    assert status == 200
    assert body["availability"] == "unavailable" and body["observation"] is None
    assert body["completeness"] == {"lookup_complete": True, "next_cursor": None,
                                    "phone_data_complete": "unknown"}
    assert [x["Key"] for x in setup.reads] == [
        {"date": DAY, "metric_source": SUMMARY}, {"date": DAY, "metric_source": LEGACY}]
    assert all(x["ConsistentRead"] is True for x in setup.reads)
    assert all(set(x["ExpressionAttributeNames"].values()) == set(handler.FIELDS) for x in setup.reads)


def test_zero_summary_preferred_without_adding_legacy(setup):
    setup.rows = {SUMMARY: row(), LEGACY: row(LEGACY, 123)}
    status, body = call()
    assert status == 200 and body["observation"]["value"] == 0
    assert body["observation"]["source_policy"] == "hae_daily_summary"
    assert len(setup.reads) == 1
    assert body["observation"]["provenance"]["hae_source"] is None


def test_legacy_is_labeled_and_never_given_summary_semantics(setup):
    setup.rows = {LEGACY: row(LEGACY, 123)}
    _, body = call()
    assert body["observation"]["value"] == 123
    assert body["observation"]["semantics"] == "legacy_hae_aggregate"
    assert body["observation"]["provenance"]["ingested_at"] is None


def test_legacy_writer_provenance_lists_are_preserved(setup):
    metadata = {"hae_raw_units": ["count"],
                "hae_raw_metric_names": ["step_count"],
                "hae_sources": ["Synthetic Watch"]}
    setup.rows = {LEGACY: row(LEGACY, 0, **metadata)}
    status, body = call()
    assert status == 200 and body["observation"]["value"] == 0
    provenance = body["observation"]["provenance"]
    assert {key: provenance[key] for key in metadata} == metadata
    assert body["observation"]["semantics"] == "legacy_hae_aggregate"
    assert len(setup.reads) == 2


@pytest.mark.parametrize("metadata", [
    {"hae_raw_units": ["count"] * 17},
    {"hae_raw_units": ["x" * 65]},
    {"hae_raw_metric_names": ["x" * 129]},
    {"hae_sources": ["x" * 257]},
    {"hae_sources": [{"unexpected": "shape"}]},
    {"hae_raw_units": [1]},
])
def test_legacy_metadata_lists_remain_bounded_and_typed(setup, metadata):
    setup.rows = {LEGACY: row(LEGACY, **metadata)}
    assert call() == (503, {"error": "source_unavailable"})


def test_combined_legacy_metadata_cannot_exceed_response_bound(setup):
    metadata = {field: "x" * 512 for field in handler.FIELDS
                if field not in {"date", "metric_source", "value", "unit",
                                 "hae_semantics", *handler.LEGACY_LIST_FIELDS}}
    metadata.update({field: ["x" * limit] * 16
                     for field, limit in handler.LEGACY_LIST_FIELDS.items()})
    # Escaping can make a valid-length metadata string larger on the wire.
    metadata["hae_source"] = "\\" * 512
    setup.rows = {LEGACY: row(LEGACY, **metadata)}
    assert call() == (503, {"error": "source_unavailable"})


def test_repeat_fingerprint_stable_and_changed_source_changes_fingerprint(setup):
    setup.rows[SUMMARY] = row(value=123)
    first = call()[1]
    assert call()[1] == first
    setup.rows[SUMMARY]["value"] = 124
    assert call()[1]["observation"]["content_fingerprint"] != first["observation"]["content_fingerprint"]


@pytest.mark.parametrize("source_ts", ["2026-11-01 01:30:00 -0700", "2026-11-01 01:30:00 -0800", "2026-10-23"])
def test_source_time_preserved_without_fabricated_timezone(setup, source_ts):
    setup.rows[SUMMARY] = row(source_ts=source_ts, ingested_at="2026-10-25T01:24:27Z")
    _, body = call()
    provenance = body["observation"]["provenance"]
    assert provenance["source_ts"] == source_ts
    assert provenance["analysis_timezone"] is None
    assert provenance["ingested_at"] == "2026-10-25T01:24:27Z"
    assert "fetched_at" not in provenance


@pytest.mark.parametrize("query", ["", "date=2026-02-30", "date=2026-1-1", "date=2026-10-23&date=2026-10-23",
                                    "date=2026-10-23&metric=hr", "start=2026-10-23&end=2026-10-24",
                                    "date=2026-10-23&x=1&y=2", "date=", "date"])
def test_rejects_invalid_or_broadened_queries_before_data_read(setup, query):
    assert call(event(rawQueryString=query))[0] == 400
    assert setup.reads == []


def test_other_day_denied_even_with_valid_token(setup):
    assert call(event(rawQueryString="date=2026-10-24"))[0] == 403
    assert setup.reads == []


@pytest.mark.parametrize("path", ["/api/today", "/api/progress", "/ingest/health", "/api/meal"])
def test_broad_routes_never_dispatch(setup, path):
    assert call(event(rawPath=path))[0] == 404
    assert setup.reads == [] and setup.secret_reads == 0


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD"])
def test_write_and_other_methods_denied(setup, method):
    assert call(event(requestContext={"http": {"method": method}}))[0] == 405
    assert setup.reads == []


@pytest.mark.parametrize("headers", [{}, {"x-api-key": TOKEN}, {"x-prism-steps-key": "invalid"},
                                     {"x-prism-steps-key": "y" * 43},
                                     {"x-prism-steps-key": TOKEN, "X-Prism-Steps-Key": TOKEN}])
def test_bad_or_broad_credentials_denied(setup, headers):
    assert call(event(headers=headers))[0] == 401
    assert setup.reads == []


def test_revocation_rotation_expiration_have_no_warm_cache(setup):
    assert call()[0] == 200
    setup.secret["enabled"] = False
    assert call()[0] == 401
    setup.secret["enabled"] = True
    setup.secret["token_sha256"] = hashlib.sha256(("z" * 43).encode()).hexdigest()
    assert call()[0] == 401
    setup.secret["token_sha256"] = hashlib.sha256(TOKEN.encode()).hexdigest()
    setup.secret["expires_at"] = "2000-01-01T00:00:00Z"
    assert call()[0] == 401
    assert setup.secret_reads == 4


@pytest.mark.parametrize("changes", [{"value": -1}, {"value": Decimal("NaN")}, {"value": True},
                                     {"value": Decimal("1.5")}, {"value": "12"}, {"unit": "miles"},
                                     {"hae_semantics": "raw_observation"}, {"hae_source": "x" * 513},
                                     {"date": "2026-10-24"}, {"value": 2**53}])
def test_malformed_summary_fails_closed_not_legacy_fallback(setup, changes):
    setup.rows = {SUMMARY: row(**changes), LEGACY: row(LEGACY, 999)}
    assert call() == (503, {"error": "source_unavailable"})
    assert len(setup.reads) == 1


def test_dependency_failure_returns_no_data_or_exception_details(setup, capsys):
    setup.fail = True
    assert call() == (503, {"error": "source_unavailable"})
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_template_is_independent_and_iam_read_only():
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, tag, node:
                                 {tag: loader.construct_scalar(node)} if isinstance(node, yaml.ScalarNode)
                                 else {tag: loader.construct_sequence(node)})
    template = yaml.load((ROOT / "prism-steps.template.yaml").read_text(), Loader=Loader)
    assert "Globals" not in template
    resources = template["Resources"]
    assert set(resources) == {"StepsApi", "SharedLayer", "StepsFunction"}
    function = resources["StepsFunction"]["Properties"]
    env = function["Environment"]["Variables"]
    assert set(env) == {"HEALTH_METRICS_TABLE", "PRISM_STEPS_ALLOWED_DATE", "PRISM_STEPS_SECRET_ARN", "PRISM_STEPS_ACCESS_MODE", "PRISM_STEPS_DAILY_ANCHOR", "PRISM_STEPS_DAILY_APPROVED_DATES"}
    statements = function["Policies"][0]["Statement"]
    assert [x["Action"] for x in statements] == ["dynamodb:GetItem", "secretsmanager:GetSecretValue"]
    assert statements[0]["Condition"]["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == {"If": ["DailyMode", {"Ref": "DailyApprovedDates"}, [{"Ref": "AllowedDate"}]]}
    assert statements[0]["Condition"]["Null"]["dynamodb:LeadingKeys"] is False
    assert template["Parameters"]["AccessMode"]["Default"] == "pilot"
    parameters = json.loads((ROOT / "release/prism-steps-daily.parameters.json").read_text())
    assert template["Parameters"]["DailyApprovedDates"]["Default"] == parameters["DailyApprovedDates"]
    dates = parameters["DailyApprovedDates"].split(",")
    assert len(dates) == len(set(dates)) == 92
    assert dates[0] == "2026-10-22" and dates[-1] == "2027-01-21"
    assert len(parameters["DailyApprovedDates"]) < 4096
    # Local evaluation of this exact allow statement, not a live IAM simulator.
    assert len(json.dumps(statements)) < 10240
    def permits(action, keys):
        return action == "dynamodb:GetItem" and bool(keys) and all(k in dates for k in keys)
    assert permits("dynamodb:GetItem", ["2026-10-22"])
    assert permits("dynamodb:GetItem", ["2027-01-21"])
    assert not permits("dynamodb:GetItem", ["2026-10-21"])
    assert not permits("dynamodb:GetItem", ["2027-01-22"])
    assert not permits("dynamodb:Query", ["2026-10-23"])
    assert not permits("dynamodb:PutItem", ["2026-10-23"])
    assert not permits("dynamodb:GetItem", [])
    routes = function["Events"]
    assert len(routes) == 1
    assert routes["GetSteps"]["Properties"]["Method"] == "GET"
    assert routes["GetSteps"]["Properties"]["Path"] == handler.PATH


@pytest.fixture
def daily(setup, monkeypatch):
    monkeypatch.setenv("PRISM_STEPS_ACCESS_MODE", "daily")
    monkeypatch.setenv("PRISM_STEPS_DAILY_ANCHOR", "2026-10-25")
    parameters = json.loads((ROOT / "release/prism-steps-daily.parameters.json").read_text())
    monkeypatch.setenv("PRISM_STEPS_DAILY_APPROVED_DATES", parameters["DailyApprovedDates"])
    setup.secret.update(issued_at="2026-10-25T07:00:00Z", expires_at="2027-01-23T07:00:00Z")
    return setup


def daily_call(day, instant):
    result = handler.lambda_handler(event(rawQueryString="date=" + day), None,
                                    now=datetime.fromisoformat(instant))
    return result["statusCode"], json.loads(result["body"])


@pytest.mark.parametrize("day,allowed", [("2026-10-22", True), ("2026-10-23", True),
    ("2026-10-24", True), ("2026-10-21", False), ("2026-10-25", False), ("2026-10-26", False)])
def test_daily_three_completed_dates_before_storage(daily, day, allowed):
    status, body = daily_call(day, "2026-10-25T09:00:00+00:00")
    assert status == (200 if allowed else 403)
    assert bool(daily.reads) == allowed
    assert "expires_at" not in json.dumps(body) and TOKEN not in json.dumps(body)


@pytest.mark.parametrize("instant,day,allowed", [
    ("2026-10-25T06:59:59+00:00", "2026-10-23", False),
    ("2026-10-25T07:00:00+00:00", "2026-10-24", True),
    ("2026-11-01T06:59:59+00:00", "2026-10-31", False),
    ("2026-11-01T07:00:00+00:00", "2026-10-31", True),
    ("2026-11-01T08:30:00+00:00", "2026-10-31", True),
    ("2026-11-01T09:30:00+00:00", "2026-10-31", True),
    ("2027-01-01T08:00:00+00:00", "2026-12-31", True),
    ("2027-01-22T20:00:00+00:00", "2027-01-21", True),
    ("2027-01-23T08:00:00+00:00", "2027-01-21", False),
])
def test_daily_pacific_boundaries(daily, instant, day, allowed):
    # Calendar checks independently of credential expiry/issuance boundaries.
    assert handler._day_allowed(day, datetime.fromisoformat(instant)) is allowed


@pytest.mark.parametrize("anchor,instant,day", [
    ("2028-02-28", "2028-03-01T08:00:00+00:00", "2028-02-29"),
    ("2027-03-01", "2027-03-14T10:01:00+00:00", "2027-03-13"),
    ("2027-03-01", "2027-03-14T09:59:00+00:00", "2027-03-13"),
])
def test_calendar_leap_and_spring_dst(daily, monkeypatch, anchor, instant, day):
    start = date.fromisoformat(anchor)
    monkeypatch.setenv("PRISM_STEPS_DAILY_ANCHOR", anchor)
    monkeypatch.setenv("PRISM_STEPS_DAILY_APPROVED_DATES", ",".join(
        (start + timedelta(days=i)).isoformat() for i in range(-3, 89)))
    assert handler._day_allowed(day, datetime.fromisoformat(instant))


@pytest.mark.parametrize("remaining,renewal", [(14*86400+1, False), (14*86400, True), (1, True)])
def test_daily_renewal_boolean_only(daily, remaining, renewal):
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    daily.secret["expires_at"] = (now + timedelta(seconds=remaining)).isoformat()
    status, body = daily_call("2026-11-08", now.isoformat())
    assert status == 200 and body["credential"] == {"renewal_due": renewal}
    assert daily.secret["expires_at"] not in json.dumps(body)


@pytest.mark.parametrize("change", [
    {"enabled": False}, {"expires_at": "2026-10-25T09:00:00Z"},
    {"issued_at": "2026-10-26T00:00:00Z"}, {"issued_at": "2026-01-01T00:00:00Z"},
    {"expires_at": "2027-01-24T00:00:00Z"}, {"issued_at": "bad"},
])
def test_daily_credential_fails_closed(daily, change, capsys):
    daily.secret.update(change)
    assert daily_call(DAY, "2026-10-25T09:00:00+00:00")[0] in (401, 503)
    assert daily.reads == []
    assert capsys.readouterr() == ("", "")


def test_daily_staged_rotation_and_rollback(daily):
    now = "2026-10-25T09:00:00+00:00"
    assert daily_call(DAY, now)[0] == 200
    original = copy.deepcopy(daily.secret)
    daily.secret["token_sha256"] = hashlib.sha256(("z"*43).encode()).hexdigest()
    assert daily_call(DAY, now)[0] == 401
    daily.secret = original
    assert daily_call(DAY, now)[0] == 200
    daily.secret["enabled"] = False
    assert daily_call(DAY, now)[0] == 401
    assert daily.secret_reads == 4


def test_daily_malformed_perimeter_and_clock_fail_closed(daily, monkeypatch):
    monkeypatch.setenv("PRISM_STEPS_DAILY_APPROVED_DATES", DAY)
    assert daily_call(DAY, "2026-10-25T09:00:00+00:00")[0] == 503
    assert daily.reads == []
    assert daily_call(DAY, "2026-10-25T09:00:00")[0] == 503
    monkeypatch.setenv("PRISM_STEPS_ACCESS_MODE", "unexpected")
    assert daily_call(DAY, "2026-10-25T09:00:00+00:00")[0] == 403
    assert daily.reads == []


def test_rolling_guard_is_narrower_than_static_iam(daily):
    assert "2026-10-23" in handler._daily_config()[1]
    assert daily_call("2026-10-23", "2026-11-01T12:00:00+00:00")[0] == 403
    assert daily.reads == []


def test_three_daily_days_preserve_identity_zero_and_source_preference(daily):
    for index, day in enumerate(["2026-10-22", "2026-10-23", "2026-10-24"]):
        daily.rows[(day, SUMMARY)] = row(date=day, value=index, source_date=day)
        daily.rows[(day, LEGACY)] = row(LEGACY, date=day, value=999)
        status, body = daily_call(day, "2026-10-25T09:00:00+00:00")
        assert status == 200 and body["date"] == day
        assert body["observation"]["value"] == index
        assert body["observation"]["source_policy"] == "hae_daily_summary"
    assert len(daily.reads) == 3
