"""Sanitized contract tests for HAE Activity Daily and Vitals & Mobility."""

import copy
import json
import logging
import os
import sys

from botocore.exceptions import ClientError

from .test_ingest_parser import _event, _fresh_module, _patch_auth


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

from shared.hae_daily import resolve_hae_daily_activity


FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _hae_event(payload, headers):
    event = _event(payload)
    event["headers"].update(headers)
    return event


def _daily_headers(session_id):
    headers = dict(DAILY_HEADERS)
    headers["session-id"] = session_id
    return headers


DAILY_HEADERS = {
    # Exact HAE REST header names are lower-case at runtime. The classifier is
    # deliberately case-insensitive because API Gateway can normalize names.
    "automation-name": "PRISM Activity Daily",
    "automation-id": "sanitized-activity-daily",
    "automation-aggregation": "Days",
    "automation-period": "Yesterday",
    "session-id": "sanitized-session-daily",
}

RAW_HEADERS = {
    "automation-name": "PRISM Vitals & Mobility",
    "automation-id": "sanitized-vitals-mobility",
    "automation-aggregation": "None",
    "automation-period": "Since Last Sync",
    "session-id": "sanitized-session-vitals",
}

DEFAULT_RAW_HEADERS = {
    **RAW_HEADERS,
    "automation-aggregation": "Default",
}


def _latest(table, metric_source):
    return [item for item in table.items if item["metric_source"] == metric_source][-1]


def _daily_summary_sources(table):
    return {
        item["metric_source"]
        for item in table.items
        if not item["metric_source"].startswith("hae_daily_summary_guard#")
    }


def _daily_guard(table):
    return [
        item
        for item in table.items
        if item["metric_source"].startswith("hae_daily_summary_guard#")
    ][-1]


def _corrected_daily_payload(payload, *, metric_name, qty, source=None):
    corrected = copy.deepcopy(payload)
    for metric in corrected["data"]["metrics"]:
        if metric["name"] != metric_name:
            continue
        metric["data"][0]["qty"] = qty
        if source is not None:
            metric["data"][0]["source"] = source
        return corrected
    raise AssertionError(f"missing fabricated metric {metric_name}")


def _conditional_check_failed():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "test"}},
        "PutItem",
    )


def test_activity_daily_writes_separate_completed_summary_rows_with_metadata():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")

    response = handler.lambda_handler(_hae_event(payload, DAILY_HEADERS), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["items_written"] == 7
    assert body["hae_semantics"] == "completed_daily_summary"

    sources = _daily_summary_sources(table)
    assert sources == {
        "active_cal#hae_daily_summary",
        "exercise_min#hae_daily_summary",
        "steps#hae_daily_summary",
        "walk_distance#hae_daily_summary",
        "stand_min#hae_daily_summary",
        "stand_hours#hae_daily_summary",
        "flights#hae_daily_summary",
    }
    assert not any(source.endswith("_samples") for source in sources)

    guard = _daily_guard(table)
    assert guard["hae_current_session_id"] == "sanitized-session-daily"
    assert guard["hae_superseded_session_ids"] == []
    assert guard["hae_session_guard_version"] == 1

    steps = _latest(table, "steps#hae_daily_summary")
    assert steps["value"] == 303
    assert steps["hae_semantics"] == "completed_daily_summary"
    assert steps["hae_raw_metric_name"] == "step_count"
    assert steps["hae_raw_units"] == "count"
    assert steps["hae_source"] == "Sanitized Watch + Sanitized Phone"
    assert steps["hae_automation_name"] == "PRISM Activity Daily"
    assert steps["hae_automation_id"] == "sanitized-activity-daily"
    assert steps["hae_automation_aggregation"] == "Days"
    assert steps["hae_automation_period"] == "Yesterday"
    assert steps["hae_session_id"] == "sanitized-session-daily"
    assert steps["source_ts"] == "2030-04-05 00:00:00 -0700"
    assert steps["analysis_date"] == "2030-04-05"
    assert steps["date_derivation"] == "source_offset"
    # An observed zero is a valid source-provided completed-day total.
    assert _latest(table, "exercise_min#hae_daily_summary")["value"] == 0


def test_daily_summary_current_session_replay_is_idempotent_and_repairs_missing_rows():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")

    headers_a = _daily_headers("sanitized-session-a")
    handler.lambda_handler(_hae_event(payload, headers_a), None)
    table.items[:] = [
        item
        for item in table.items
        if item["metric_source"] != "flights#hae_daily_summary"
    ]
    replay = handler.lambda_handler(_hae_event(payload, headers_a), None)
    assert replay["statusCode"] == 200
    assert json.loads(replay["body"])["items_written"] == 7
    assert _latest(table, "steps#hae_daily_summary")["value"] == 303
    assert _latest(table, "flights#hae_daily_summary")["value"] == 2
    assert _daily_guard(table)["hae_current_session_id"] == "sanitized-session-a"
    assert _daily_guard(table)["hae_session_guard_version"] == 1
    assert not any(
        item["metric_source"] == "steps#hae_daily_summary_samples"
        for item in table.items
    )


def test_daily_summary_new_session_correction_replaces_prior_total():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    corrected = _corrected_daily_payload(
        payload,
        metric_name="step_count",
        qty=404,
        source="Sanitized Correction Source",
    )

    handler.lambda_handler(_hae_event(payload, _daily_headers("sanitized-session-a")), None)
    handler.lambda_handler(
        _hae_event(corrected, _daily_headers("sanitized-session-b")),
        None,
    )
    assert _latest(table, "steps#hae_daily_summary")["value"] == 404
    assert _latest(table, "steps#hae_daily_summary")["hae_session_id"] == (
        "sanitized-session-b"
    )
    assert _daily_guard(table)["hae_current_session_id"] == "sanitized-session-b"
    assert _daily_guard(table)["hae_superseded_session_ids"] == [
        "sanitized-session-a"
    ]
    assert not any(
        item["metric_source"] == "steps#hae_daily_summary_samples"
        for item in table.items
    )


def test_daily_summary_stale_session_replay_is_a_successful_noop(caplog):
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    corrected = _corrected_daily_payload(
        payload,
        metric_name="step_count",
        qty=404,
        source="Sanitized Correction Source",
    )
    computed_dates = []
    handler._trigger_compute = computed_dates.append

    headers_a = _daily_headers("sanitized-session-a")
    headers_b = _daily_headers("sanitized-session-b")
    handler.lambda_handler(_hae_event(payload, headers_a), None)
    handler.lambda_handler(_hae_event(corrected, headers_b), None)

    before_steps = copy.deepcopy(_latest(table, "steps#hae_daily_summary"))
    before_guard = copy.deepcopy(_daily_guard(table))
    before_item_count = len(table.items)
    before_compute_count = len(computed_dates)
    with caplog.at_level(logging.INFO, logger="ingest"):
        stale = handler.lambda_handler(_hae_event(payload, headers_a), None)

    assert stale["statusCode"] == 200
    assert json.loads(stale["body"]) == {
        "date": "2030-04-05",
        "items_written": 0,
        "status": "stale_daily_summary_replay_ignored",
        "hae_semantics": "completed_daily_summary",
    }
    assert len(table.items) == before_item_count
    assert len(computed_dates) == before_compute_count
    assert _latest(table, "steps#hae_daily_summary") == before_steps
    assert _daily_guard(table) == before_guard
    assert all(
        _latest(table, source)["hae_session_id"] == "sanitized-session-b"
        for source in _daily_summary_sources(table)
    )
    assert "HAE_DAILY_SUMMARY_SESSION_GUARD" in caplog.text
    assert "sanitized-session-a" not in caplog.text
    assert "404" not in caplog.text


def test_daily_summary_current_corrected_session_replay_remains_safe():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    corrected = _corrected_daily_payload(
        payload,
        metric_name="step_count",
        qty=404,
    )

    handler.lambda_handler(_hae_event(payload, _daily_headers("sanitized-session-a")), None)
    handler.lambda_handler(
        _hae_event(corrected, _daily_headers("sanitized-session-b")),
        None,
    )
    replay = handler.lambda_handler(
        _hae_event(corrected, _daily_headers("sanitized-session-b")),
        None,
    )

    assert replay["statusCode"] == 200
    assert _latest(table, "steps#hae_daily_summary")["value"] == 404
    assert _daily_guard(table)["hae_current_session_id"] == "sanitized-session-b"
    assert _daily_guard(table)["hae_session_guard_version"] == 2


def test_daily_summary_correction_can_replace_nonzero_with_genuine_zero():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    corrected_zero = _corrected_daily_payload(
        payload,
        metric_name="step_count",
        qty=0,
    )

    handler.lambda_handler(_hae_event(payload, _daily_headers("sanitized-session-a")), None)
    handler.lambda_handler(
        _hae_event(corrected_zero, _daily_headers("sanitized-session-b")),
        None,
    )
    handler.lambda_handler(
        _hae_event(payload, _daily_headers("sanitized-session-a")),
        None,
    )

    steps = _latest(table, "steps#hae_daily_summary")
    assert steps["value"] == 0
    assert steps["hae_session_id"] == "sanitized-session-b"


def test_daily_summary_guard_history_is_bounded_and_never_evicts_current():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")

    for index in range(18):
        response = handler.lambda_handler(
            _hae_event(payload, _daily_headers(f"sanitized-session-{index:02d}")),
            None,
        )
        assert response["statusCode"] == 200

    guard = _daily_guard(table)
    assert guard["hae_current_session_id"] == "sanitized-session-17"
    assert len(guard["hae_superseded_session_ids"]) == 16
    assert guard["hae_superseded_session_ids"][0] == "sanitized-session-16"
    assert guard["hae_superseded_session_ids"][-1] == "sanitized-session-01"
    assert guard["hae_current_session_id"] not in guard["hae_superseded_session_ids"]

    current_replay = handler.lambda_handler(
        _hae_event(payload, _daily_headers("sanitized-session-17")),
        None,
    )
    assert current_replay["statusCode"] == 200
    assert _daily_guard(table)["hae_current_session_id"] == "sanitized-session-17"


def test_daily_summary_missing_session_identity_fails_closed_before_writes():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    missing_session = dict(DAILY_HEADERS)
    missing_session.pop("session-id")

    response = handler.lambda_handler(_hae_event(payload, missing_session), None)
    assert response["statusCode"] == 422
    assert json.loads(response["body"]) == {
        "error": "missing required HAE daily-summary session identity",
        "reason": "missing_session_id",
        "hae_semantics": "completed_daily_summary",
    }
    assert table.items == []


def test_daily_summary_guard_conditional_conflict_retries_and_reevaluates():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    original_conditional_put = handler.put_item_conditionally
    guard_calls = 0

    def conflict_once(table_arg, item, *, condition_expression):
        nonlocal guard_calls
        if item["metric_source"].startswith("hae_daily_summary_guard#"):
            guard_calls += 1
            if guard_calls == 1:
                concurrent = dict(item)
                concurrent["hae_current_session_id"] = "sanitized-session-b"
                concurrent["hae_session_id"] = "sanitized-session-b"
                concurrent["hae_session_guard_version"] = 1
                table_arg.put_item(Item=concurrent)
                raise _conditional_check_failed()
        return original_conditional_put(
            table_arg,
            item,
            condition_expression=condition_expression,
        )

    handler.put_item_conditionally = conflict_once
    response = handler.lambda_handler(
        _hae_event(payload, _daily_headers("sanitized-session-a")),
        None,
    )

    assert response["statusCode"] == 200
    assert guard_calls == 2
    guard = _daily_guard(table)
    assert guard["hae_current_session_id"] == "sanitized-session-a"
    assert guard["hae_superseded_session_ids"] == ["sanitized-session-b"]
    assert guard["hae_session_guard_version"] == 2
    assert _latest(table, "steps#hae_daily_summary")["hae_session_guard_version"] == 2


def test_daily_summary_unresolved_guard_conflict_fails_before_canonical_writes():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")
    original_conditional_put = handler.put_item_conditionally
    guard_calls = 0

    def always_conflict(table_arg, item, *, condition_expression):
        nonlocal guard_calls
        if item["metric_source"].startswith("hae_daily_summary_guard#"):
            guard_calls += 1
            raise _conditional_check_failed()
        return original_conditional_put(
            table_arg,
            item,
            condition_expression=condition_expression,
        )

    handler.put_item_conditionally = always_conflict
    response = handler.lambda_handler(
        _hae_event(payload, _daily_headers("sanitized-session-a")),
        None,
    )

    assert response["statusCode"] == 409
    assert guard_calls == 3
    assert table.items == []


def test_summary_resolver_prefers_completed_daily_over_legacy_raw_without_double_counting():
    handler, table = _fresh_module()
    _patch_auth(handler)
    # Existing feeds with no HAE routing headers retain the deployed raw path.
    legacy_raw = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {
                            "date": "2030-04-05 09:00:00 -0700",
                            "qty": 7,
                            "source": "Sanitized Watch",
                        }
                    ],
                }
            ]
        }
    }
    handler.lambda_handler(_event(legacy_raw), None)
    handler.lambda_handler(
        _hae_event(_fixture("hae_v2_activity_daily_sanitized.json"), DAILY_HEADERS),
        None,
    )
    metric_map = {item["metric_source"]: item for item in table.items}
    resolved = resolve_hae_daily_activity(metric_map, "steps")

    assert metric_map["steps#hae"]["value"] == 7
    assert metric_map["steps#hae_daily_summary"]["value"] == 303
    assert resolved == {
        "value": 303,
        "source": "hae_daily_summary",
        "metric_source": "steps#hae_daily_summary",
    }
    assert resolve_hae_daily_activity({}, "steps") == {
        "value": None,
        "source": "unavailable",
        "metric_source": None,
    }
    assert resolve_hae_daily_activity(
        {"steps#hae": {"value": 0}},
        "steps",
    )["value"] == 0
    assert resolve_hae_daily_activity(
        {"steps#hae": {"value": 7}},
        "steps",
    )["source"] == "legacy_hae_aggregate"


def test_default_raw_vitals_stream_preserves_metadata_and_does_not_sum_physical_effort():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_vitals_mobility_sanitized.json")

    first = handler.lambda_handler(_hae_event(payload, DEFAULT_RAW_HEADERS), None)
    second = handler.lambda_handler(_hae_event(payload, DEFAULT_RAW_HEADERS), None)
    assert first["statusCode"] == 200
    assert second["statusCode"] == 200
    assert json.loads(first["body"])["hae_semantics"] == "raw_observation"

    effort = _latest(table, "physical_effort#hae")
    ledger = _latest(table, "physical_effort#hae_samples")
    assert effort["value"] == 3.0  # mean of two observation-series samples, never 6.0
    assert effort["unit"] == "kcal/hr·kg"
    assert effort["hae_semantics"] == "raw_observation"
    assert effort["hae_raw_metric_names"] == ["physical_effort"]
    assert effort["hae_raw_units"] == ["kcal/hr·kg"]
    assert effort["hae_sources"] == ["Sanitized Watch + Sanitized Phone"]
    assert effort["hae_automation_name"] == "PRISM Vitals & Mobility"
    assert effort["hae_automation_id"] == "sanitized-vitals-mobility"
    assert effort["hae_automation_period"] == "Since Last Sync"
    assert len(ledger["samples"]) == 2


def test_hae_stream_classifier_accepts_default_no_grouping_and_keeps_fail_closed_matrix():
    handler, _table = _fresh_module()

    cases = [
        ("Default", "Since Last Sync", "raw_observation"),
        ("default", "Since Last Sync", "raw_observation"),
        ("  DeFaUlT  ", "  Since Last Sync  ", "raw_observation"),
        ("None", "Since Last Sync", "raw_observation"),
        ("Days", "Since Last Sync", "unsupported_or_ambiguous"),
        ("Days", "Yesterday", "completed_daily_summary"),
    ]
    for aggregation, period, expected_semantics in cases:
        request_context = handler._hae_request_context(
            {
                "automation-aggregation": aggregation,
                "automation-period": period,
            }
        )
        assert request_context["semantics"] == expected_semantics

    assert handler._hae_request_context({})["semantics"] == "legacy_unclassified"


def test_new_raw_metric_mappings_are_source_observations_not_scores():
    handler, table = _fresh_module()
    _patch_auth(handler)
    observations = [
        ("walking_running_distance", "mi", "walk_distance#hae"),
        ("apple_move_time", "min", "move_min#hae"),
        ("cardio_recovery", "source-declared-unit", "cardio_recovery#hae"),
        ("walking_speed", "mi/hr", "walking_speed#hae"),
        ("walking_step_length", "in", "walking_step_length#hae"),
        ("walking_double_support_percentage", "%", "walking_double_support#hae"),
        ("stair_speed_up", "ft/s", "stair_speed_up#hae"),
        ("stair_speed_down", "ft/s", "stair_speed_down#hae"),
        ("six_minute_walking_test_distance", "source-declared-unit", "six_min_walk_distance#hae"),
        ("body_temperature", "degC", "body_temp#hae"),
    ]
    payload = {
        "data": {
            "metrics": [
                {
                    "name": name,
                    "units": unit,
                    "data": [
                        {
                            "date": "2030-04-06 12:00:00 -0700",
                            "qty": index + 1,
                            "source": "Sanitized Watch",
                        }
                    ],
                }
                for index, (name, unit, _source) in enumerate(observations)
            ]
        }
    }

    response = handler.lambda_handler(_hae_event(payload, RAW_HEADERS), None)
    assert response["statusCode"] == 200
    sources = {item["metric_source"] for item in table.items}
    assert {source for _name, _unit, source in observations}.issubset(sources)
    assert "body_temp#hae" in sources
    assert "wrist_temp#hae" not in sources
    assert _latest(table, "cardio_recovery#hae")["unit"] == "source-declared-unit"
    assert _latest(table, "six_min_walk_distance#hae")["unit"] == "source-declared-unit"


def test_existing_tier_one_mappings_remain_distinct_and_unchanged():
    handler, _table = _fresh_module()
    expected = {
        "heartratevariability": ("hrv#hae", "ms", "avg"),
        "restingheartrate": ("rhr#hae", "bpm", "avg"),
        "bloodoxygensaturation": ("spo2#hae", "%", "avg"),
        "respiratoryrate": ("resp#hae", "br/min", "avg"),
        "applesleepingwristtemperature": ("wrist_temp#hae", "degC", "avg"),
        "bodytemperature": ("body_temp#hae", "degC", "avg"),
        "walkingheartrateaverage": ("walk_hr#hae", "bpm", "avg"),
        "walkingasymmetrypercentage": ("walking_asymmetry#hae", "%", "avg"),
        "vo2max": ("vo2_max#hae", "ml/kg/min", "avg"),
        "activeenergy": ("active_cal#hae", "kcal", "sum_int"),
        "stepcount": ("steps#hae", "count", "sum_int"),
        "applestandtime": ("stand_min#hae", "min", "sum_int"),
        "applestandhour": ("stand_hours#hae", "count", "sum_int"),
        "flightsclimbed": ("flights#hae", "count", "sum_int"),
    }
    for raw_name, mapping in expected.items():
        assert handler.HAE_NAME_MAP[raw_name] == mapping


def test_missing_headers_keep_legacy_raw_compatibility():
    handler, table = _fresh_module()
    _patch_auth(handler)
    raw_payload = _fixture("hae_v2_vitals_mobility_sanitized.json")

    response = handler.lambda_handler(_event(raw_payload), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["hae_semantics"] == "legacy_unclassified"
    assert _latest(table, "physical_effort#hae")["hae_semantics"] == "legacy_unclassified"


def test_days_since_last_sync_remains_rejected_without_writes():
    handler, table = _fresh_module()
    _patch_auth(handler)
    raw_payload = _fixture("hae_v2_vitals_mobility_sanitized.json")

    rejected = handler.lambda_handler(
        _hae_event(
            raw_payload,
            {
                "automation-aggregation": "Days",
                "automation-period": "Since Last Sync",
            },
        ),
        None,
    )
    assert rejected["statusCode"] == 422
    assert json.loads(rejected["body"])["hae_semantics"] == "unsupported_or_ambiguous"
    assert table.items == []



def test_unknown_metric_logging_retains_routing_context_without_health_values(caplog):
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "sanitized_future_metric",
                    "data": [
                        {
                            "date": "2030-04-06 12:00:00 -0700",
                            "qty": 314159,
                        }
                    ],
                }
            ]
        }
    }
    with caplog.at_level(logging.WARNING, logger="ingest"):
        handler.lambda_handler(_hae_event(payload, RAW_HEADERS), None)

    assert table.items == []
    assert "HAE_UNMAPPED_METRIC metric_name=sanitized_future_metric point_count=1" in caplog.text
    assert "semantics=raw_observation" in caplog.text
    assert "automation_name=PRISM Vitals & Mobility" in caplog.text
    assert "314159" not in caplog.text
