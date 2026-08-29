"""Fabricated multi-date contract tests for HAE completed daily summaries."""

import copy
import json
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest
from boto3.dynamodb.conditions import (
    AttributeNotExists,
    Equals,
    LessThanEquals,
    Or,
)
from botocore.exceptions import ClientError

from .test_hae_evidence_contract import _daily_headers, _hae_event
from .test_ingest_parser import _fresh_module, _patch_auth


ACTIVITY_METRICS = (
    ("active_energy", "kcal", 101),
    ("apple_exercise_time", "min", 0),
    ("step_count", "count", 303),
    ("walking_running_distance", "mi", 4.5),
    ("apple_stand_time", "min", 41),
    ("apple_stand_hour", "count", 5),
    ("flights_climbed", "count", 2),
)


def _activity_payload(
    dates,
    *,
    missing=None,
    duplicate=None,
    offsets=None,
    step_delta=0,
):
    metrics = []
    for name, units, base_value in ACTIVITY_METRICS:
        points = []
        for index, date_str in enumerate(dates):
            if missing == (name, date_str):
                continue
            offset = offsets[index] if offsets else "-0700"
            point = {
                "date": f"{date_str} 00:00:00 {offset}",
                "qty": base_value + (step_delta if name == "step_count" else index),
                "source": "Sanitized Multi-Date Source",
            }
            points.append(point)
            if duplicate == (name, date_str):
                points.append(copy.deepcopy(point))
        metrics.append({"name": name, "units": units, "data": points})
    return {"data": {"metrics": metrics}}


def _canonical_rows(table):
    return [
        item
        for item in table.items
        if not item["metric_source"].startswith("hae_daily_summary_guard#")
    ]


def _body(response):
    return json.loads(response["body"])


def _metric_rows(table, metric_source):
    return [
        item for item in _canonical_rows(table)
        if item["metric_source"] == metric_source
    ]


def _set_metric_values(payload, metric_name, value):
    updated = copy.deepcopy(payload)
    for metric in updated["data"]["metrics"]:
        if metric["name"] == metric_name:
            for point in metric["data"]:
                point["qty"] = value
            return updated
    raise AssertionError(f"missing fabricated metric {metric_name}")


def _conditional_check_failed():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "test"}},
        "PutItem",
    )


class ConditionAwareFakeTable:
    """Small DynamoDB fake for the exact guard/write-fence conditions in scope."""

    def __init__(self):
        self.items = []
        self.before_conditional_put = None
        self.conditional_put_count = 0

    @staticmethod
    def _unwrap(value):
        if isinstance(value, Decimal):
            return float(value) if value != int(value) else int(value)
        if isinstance(value, dict):
            return {
                key: ConditionAwareFakeTable._unwrap(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [ConditionAwareFakeTable._unwrap(item) for item in value]
        return value

    @staticmethod
    def _key(item):
        return item.get("date"), item.get("metric_source")

    def _existing_index(self, item):
        key = self._key(item)
        for index, existing in enumerate(self.items):
            if self._key(existing) == key:
                return index
        return None

    def _store(self, item):
        item = self._unwrap(item)
        index = self._existing_index(item)
        if index is None:
            self.items.append(item)
        else:
            self.items[index] = item

    def _condition_matches(self, expression, existing):
        if isinstance(expression, Or):
            return any(
                self._condition_matches(value, existing)
                for value in expression._values
            )
        if isinstance(expression, AttributeNotExists):
            attr = expression._values[0].name
            return existing is None or attr not in existing
        if isinstance(expression, Equals):
            attr, expected = expression._values
            return existing is not None and existing.get(attr.name) == expected
        if isinstance(expression, LessThanEquals):
            attr, expected = expression._values
            return (
                existing is not None
                and existing.get(attr.name) is not None
                and existing[attr.name] <= expected
            )
        raise AssertionError(f"unsupported condition {type(expression).__name__}")

    def put_item(self, Item=None, ConditionExpression=None, **_kwargs):
        item = self._unwrap(Item)
        if ConditionExpression is not None:
            self.conditional_put_count += 1
            if self.before_conditional_put:
                self.before_conditional_put(self, item, ConditionExpression)
            index = self._existing_index(item)
            existing = self.items[index] if index is not None else None
            if not self._condition_matches(ConditionExpression, existing):
                raise _conditional_check_failed()
        self._store(item)

    def get_item(self, Key=None, **_kwargs):
        for item in self.items:
            if all(item.get(key) == value for key, value in (Key or {}).items()):
                return {"Item": copy.deepcopy(item)}
        return {}

    def delete_key(self, date_str, metric_source):
        self.items[:] = [
            item
            for item in self.items
            if self._key(item) != (date_str, metric_source)
        ]


def _fresh_condition_module():
    import shared.db as db_mod

    table = ConditionAwareFakeTable()
    db_mod.get_table = lambda _env_var: table
    db_mod.put_item = lambda table_arg, item: table_arg.put_item(Item=item)
    db_mod.put_item_conditionally = (
        lambda table_arg, item, *, condition_expression: table_arg.put_item(
            Item=item,
            ConditionExpression=condition_expression,
        )
    )
    db_mod.get_item = lambda table_arg, key: (
        table_arg.get_item(Key=key).get("Item") or {}
    )

    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler

    handler._trigger_compute = lambda *_args, **_kwargs: None
    return handler, table


def _request(handler, payload, session_id):
    return handler.lambda_handler(
        _hae_event(payload, _daily_headers(session_id)),
        None,
    )


def test_multidate_activity_summary_writes_each_metric_date():
    handler, table = _fresh_module()
    _patch_auth(handler)
    dates = ["2031-01-01", "2031-01-02"]

    response = handler.lambda_handler(
        _hae_event(
            _activity_payload(dates),
            _daily_headers("sanitized-multidate-session"),
        ),
        None,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["items_written"] == 14
    assert body["date_count"] == 2
    assert body["dates_completed"] == 2
    assert {item["date"] for item in _canonical_rows(table)} == set(dates)


def test_forty_four_date_activity_summary_writes_all_expected_rows():
    handler, table = _fresh_module()
    _patch_auth(handler)
    start = date(2031, 2, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(44)]

    response = _request(
        handler,
        _activity_payload(dates),
        "sanitized-forty-four-date-session",
    )

    assert response["statusCode"] == 200
    body = _body(response)
    assert body == {
        "status": "completed",
        "date_count": 44,
        "dates_completed": 44,
        "dates_stale_ignored": 0,
        "items_written": 44 * 7,
        "affected_date_start": dates[0],
        "affected_date_end": dates[-1],
        "hae_semantics": "completed_daily_summary",
    }
    assert len(_canonical_rows(table)) == 44 * 7


def test_identical_multidate_replay_is_idempotent_with_real_conditions():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-01", "2031-04-02"]
    payload = _activity_payload(dates)

    first = _request(handler, payload, "sanitized-session-a")
    second = _request(handler, payload, "sanitized-session-a")

    assert first["statusCode"] == 200
    assert second["statusCode"] == 200
    assert len(_canonical_rows(table)) == 14
    guards = [
        item for item in table.items
        if item["metric_source"].startswith("hae_daily_summary_guard#")
    ]
    assert len(guards) == 2
    assert {item["hae_session_guard_version"] for item in guards} == {1}


def test_corrected_multidate_request_replaces_instead_of_adding():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-03", "2031-04-04"]
    original = _activity_payload(dates)
    corrected = _set_metric_values(original, "step_count", 909)

    _request(handler, original, "sanitized-session-a")
    response = _request(handler, corrected, "sanitized-session-b")

    assert response["statusCode"] == 200
    steps = _metric_rows(table, "steps#hae_daily_summary")
    assert len(steps) == 2
    assert {item["value"] for item in steps} == {909}
    assert {item["hae_session_id"] for item in steps} == {"sanitized-session-b"}


def test_multidate_nonzero_to_zero_correction_remains_zero():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-05", "2031-04-06"]
    original = _activity_payload(dates)
    corrected = _set_metric_values(original, "step_count", 0)

    _request(handler, original, "sanitized-session-a")
    _request(handler, corrected, "sanitized-session-b")
    _request(handler, original, "sanitized-session-a")

    steps = _metric_rows(table, "steps#hae_daily_summary")
    assert len(steps) == 2
    assert {item["value"] for item in steps} == {0}
    assert {item["hae_session_id"] for item in steps} == {"sanitized-session-b"}


def test_multidate_a_b_delayed_a_remains_b_for_every_date():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-07", "2031-04-08"]
    payload_a = _activity_payload(dates)
    payload_b = _set_metric_values(payload_a, "step_count", 707)

    _request(handler, payload_a, "sanitized-session-a")
    _request(handler, payload_b, "sanitized-session-b")
    stale = _request(handler, payload_a, "sanitized-session-a")

    assert stale["statusCode"] == 200
    assert _body(stale)["status"] == "stale_daily_summary_replay_ignored"
    assert _body(stale)["dates_stale_ignored"] == 2
    steps = _metric_rows(table, "steps#hae_daily_summary")
    assert {item["value"] for item in steps} == {707}
    assert {item["hae_session_id"] for item in steps} == {"sanitized-session-b"}


def test_same_session_multidate_replay_repairs_a_missing_metric_row():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-09", "2031-04-10"]
    payload = _activity_payload(dates)

    _request(handler, payload, "sanitized-session-a")
    table.delete_key("2031-04-10", "flights#hae_daily_summary")
    replay = _request(handler, payload, "sanitized-session-a")

    assert replay["statusCode"] == 200
    assert len(_canonical_rows(table)) == 14
    assert len(_metric_rows(table, "flights#hae_daily_summary")) == 2


def test_missing_metric_date_stays_missing_while_other_rows_write():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-11", "2031-04-12"]
    payload = _activity_payload(
        dates,
        missing=("flights_climbed", "2031-04-12"),
    )

    response = _request(handler, payload, "sanitized-session-a")

    assert response["statusCode"] == 200
    assert _body(response)["items_written"] == 13
    flights = _metric_rows(table, "flights#hae_daily_summary")
    assert len(flights) == 1
    assert flights[0]["date"] == "2031-04-11"
    assert len(_canonical_rows(table)) == 13


def test_duplicate_metric_date_rejects_whole_payload_before_any_write():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    payload = _activity_payload(
        ["2031-04-13", "2031-04-14"],
        duplicate=("step_count", "2031-04-14"),
    )

    response = _request(handler, payload, "sanitized-session-a")

    assert response["statusCode"] == 422
    assert _body(response) == {
        "error": "invalid HAE daily-summary payload",
        "reason": "duplicate_metric_date",
        "hae_semantics": "completed_daily_summary",
    }
    assert table.items == []


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (
            lambda payload: payload["data"]["metrics"].append(
                {
                    "name": "sleep_analysis",
                    "units": "hr",
                    "data": [],
                }
            ),
            "unsupported_daily_metric",
        ),
        (
            lambda payload: payload["data"]["metrics"][2].update(
                {"units": "kcal"}
            ),
            "contradictory_units",
        ),
        (
            lambda payload: payload["data"]["metrics"][2]["data"][0].update(
                {"date": "not-a-date"}
            ),
            "unparseable_date",
        ),
        (
            lambda payload: payload["data"]["metrics"][2].update(
                {"data": ["not-an-object"]}
            ),
            "invalid_row_shape",
        ),
        (
            lambda payload: payload["data"]["metrics"].insert(0, {}),
            "invalid_metric_shape",
        ),
    ],
)
def test_structural_errors_fail_before_guards_or_canonical_writes(
    mutate,
    expected_reason,
):
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    payload = _activity_payload(["2031-04-15"])
    mutate(payload)

    response = _request(handler, payload, "sanitized-session-a")

    assert response["statusCode"] == 422
    assert _body(response)["reason"] == expected_reason
    assert table.items == []


def test_empty_daily_summary_payload_fails_closed_without_writes():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)

    response = _request(
        handler,
        {"data": {"metrics": []}},
        "sanitized-session-a",
    )

    assert response["statusCode"] == 422
    assert _body(response)["reason"] == "no_daily_summary_observations"
    assert table.items == []


def test_mixed_explicit_offsets_retain_each_source_local_calendar_date():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-16", "2031-04-17"]
    payload = _activity_payload(dates, offsets=("-0700", "+0530"))

    response = _request(handler, payload, "sanitized-session-a")

    assert response["statusCode"] == 200
    steps = sorted(
        _metric_rows(table, "steps#hae_daily_summary"),
        key=lambda item: item["date"],
    )
    assert [item["date"] for item in steps] == dates
    assert [item["source_utc_offset"] for item in steps] == ["-07:00", "+05:30"]
    assert all(item["date_derivation"] == "source_offset" for item in steps)


def test_stale_date_plus_unseen_date_uses_independent_guard_decisions():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    first_date = ["2031-04-18"]
    both_dates = ["2031-04-18", "2031-04-19"]
    original_first = _activity_payload(first_date)
    corrected_first = _set_metric_values(original_first, "step_count", 818)
    computed_dates = []
    handler._trigger_compute = computed_dates.append

    _request(handler, original_first, "sanitized-session-a")
    _request(handler, corrected_first, "sanitized-session-b")
    computed_dates.clear()
    response = _request(
        handler,
        _activity_payload(both_dates),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 200
    assert _body(response) == {
        "status": "completed_with_stale_ignored",
        "date_count": 2,
        "dates_completed": 1,
        "dates_stale_ignored": 1,
        "items_written": 7,
        "affected_date_start": "2031-04-18",
        "affected_date_end": "2031-04-19",
        "hae_semantics": "completed_daily_summary",
    }
    assert computed_dates == ["2031-04-19"]
    steps = {
        item["date"]: item["value"]
        for item in _metric_rows(table, "steps#hae_daily_summary")
    }
    assert steps == {"2031-04-18": 818, "2031-04-19": 303}


def test_condition_aware_guard_conflict_retries_and_reevaluates():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    date_str = "2031-04-20"
    injected = False

    def inject_concurrent_guard(table_arg, item, _condition):
        nonlocal injected
        if (
            not injected
            and item["metric_source"].startswith("hae_daily_summary_guard#")
        ):
            injected = True
            concurrent = dict(item)
            concurrent["hae_current_session_id"] = "sanitized-session-b"
            concurrent["hae_session_id"] = "sanitized-session-b"
            concurrent["hae_session_guard_version"] = 1
            table_arg._store(concurrent)

    table.before_conditional_put = inject_concurrent_guard
    response = _request(
        handler,
        _activity_payload([date_str]),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 200
    guard = [
        item for item in table.items
        if item["metric_source"].startswith("hae_daily_summary_guard#")
    ][0]
    assert guard["hae_current_session_id"] == "sanitized-session-a"
    assert guard["hae_superseded_session_ids"] == ["sanitized-session-b"]
    assert guard["hae_session_guard_version"] == 2
    assert {
        item["hae_session_guard_version"] for item in _canonical_rows(table)
    } == {2}


def test_condition_aware_metric_write_fence_rejects_older_guard_version():
    handler, table = _fresh_condition_module()
    existing = {
        "date": "2031-04-20",
        "metric_source": "steps#hae_daily_summary",
        "value": 820,
        "hae_session_guard_version": 2,
    }
    table._store(existing)
    delayed = {
        "date": "2031-04-20",
        "metric_source": "steps#hae_daily_summary",
        "value": 120,
    }

    written = handler._put_hae_daily_summary_metric(table, delayed, 1)

    assert written is False
    assert _metric_rows(table, "steps#hae_daily_summary") == [existing]


def test_unresolved_second_date_guard_conflict_returns_partial_non_2xx():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-21", "2031-04-22"]
    conflict_version = 0

    def keep_advancing_second_guard(table_arg, item, _condition):
        nonlocal conflict_version
        if (
            item["date"] == dates[1]
            and item["metric_source"].startswith("hae_daily_summary_guard#")
        ):
            conflict_version += 1
            concurrent = dict(item)
            concurrent["hae_current_session_id"] = (
                f"sanitized-concurrent-{conflict_version}"
            )
            concurrent["hae_session_id"] = concurrent["hae_current_session_id"]
            concurrent["hae_superseded_session_ids"] = []
            concurrent["hae_session_guard_version"] = conflict_version
            table_arg._store(concurrent)

    table.before_conditional_put = keep_advancing_second_guard
    computed_dates = []
    handler._trigger_compute = computed_dates.append
    response = _request(
        handler,
        _activity_payload(dates),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 409
    assert _body(response) == {
        "error": "HAE daily-summary session guard conflict",
        "status": "partial_failure",
        "date_count": 2,
        "dates_completed": 1,
        "dates_stale_ignored": 0,
        "items_written": 7,
        "affected_date_start": dates[0],
        "affected_date_end": dates[1],
        "failed_date": dates[1],
        "reason": "conditional_write_conflict",
        "hae_semantics": "completed_daily_summary",
    }
    assert computed_dates == [dates[0]]
    assert {item["date"] for item in _canonical_rows(table)} == {dates[0]}


def test_partial_metric_conflict_is_observable_and_same_session_resume_is_safe():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-23", "2031-04-24"]
    payload = _activity_payload(dates)
    original_put = handler._put_hae_daily_summary_metric
    calls = 0
    computed_dates = []
    handler._trigger_compute = computed_dates.append

    def fail_after_two_second_date_metrics(table_arg, item, guard_version):
        nonlocal calls
        calls += 1
        if calls == 10:
            return False
        return original_put(table_arg, item, guard_version)

    handler._put_hae_daily_summary_metric = fail_after_two_second_date_metrics
    failed = _request(handler, payload, "sanitized-session-a")

    assert failed["statusCode"] == 409
    assert _body(failed)["dates_completed"] == 1
    assert _body(failed)["failed_date"] == dates[1]
    assert _body(failed)["reason"] == "metric_write_fenced_by_newer_guard"
    assert _body(failed)["items_written"] == 9
    assert computed_dates == [dates[0]]

    handler._put_hae_daily_summary_metric = original_put
    resumed = _request(handler, payload, "sanitized-session-a")

    assert resumed["statusCode"] == 200
    assert len(_canonical_rows(table)) == 14
    assert computed_dates == [dates[0], dates[0], dates[1]]
    assert not any(
        item["metric_source"].endswith("_samples")
        for item in _canonical_rows(table)
    )


def test_infrastructure_failure_after_prior_date_returns_bounded_partial_result():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-25", "2031-04-26"]
    original_put = handler._put_hae_daily_summary_metric
    calls = 0

    def raise_on_second_date(table_arg, item, guard_version):
        nonlocal calls
        calls += 1
        if calls == 8:
            raise RuntimeError("fabricated write outage")
        return original_put(table_arg, item, guard_version)

    handler._put_hae_daily_summary_metric = raise_on_second_date
    response = _request(
        handler,
        _activity_payload(dates),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 503
    assert _body(response)["status"] == "partial_failure"
    assert _body(response)["dates_completed"] == 1
    assert _body(response)["failed_date"] == dates[1]
    assert _body(response)["reason"] == "metric_write_failed"
    assert "fabricated write outage" not in response["body"]
    assert {item["date"] for item in _canonical_rows(table)} == {dates[0]}


def test_recompute_runs_once_per_successfully_affected_date_and_never_for_stale():
    handler, _table = _fresh_condition_module()
    _patch_auth(handler)
    dates = ["2031-04-27", "2031-04-28"]
    computed_dates = []
    handler._trigger_compute = computed_dates.append

    response = _request(
        handler,
        _activity_payload(dates),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 200
    assert computed_dates == dates


def test_multidate_summary_creates_no_raw_aggregate_or_sample_ledger_rows():
    handler, table = _fresh_condition_module()
    _patch_auth(handler)

    response = _request(
        handler,
        _activity_payload(["2031-04-29", "2031-04-30"]),
        "sanitized-session-a",
    )

    assert response["statusCode"] == 200
    sources = {item["metric_source"] for item in _canonical_rows(table)}
    assert all(source.endswith("#hae_daily_summary") for source in sources)
    assert not any(source.endswith("#hae") for source in sources)
    assert not any(source.endswith("_samples") for source in sources)
