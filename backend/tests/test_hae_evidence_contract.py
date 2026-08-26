"""Sanitized contract tests for HAE Activity Daily and Vitals & Mobility."""

import copy
import json
import logging
import os
import sys

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


def _latest(table, metric_source):
    return [item for item in table.items if item["metric_source"] == metric_source][-1]


def test_activity_daily_writes_separate_completed_summary_rows_with_metadata():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")

    response = handler.lambda_handler(_hae_event(payload, DAILY_HEADERS), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["items_written"] == 7
    assert body["hae_semantics"] == "completed_daily_summary"

    sources = {item["metric_source"] for item in table.items}
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


def test_daily_summary_replay_is_idempotent_and_correction_replaces():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_activity_daily_sanitized.json")

    handler.lambda_handler(_hae_event(payload, DAILY_HEADERS), None)
    handler.lambda_handler(_hae_event(payload, DAILY_HEADERS), None)
    assert _latest(table, "steps#hae_daily_summary")["value"] == 303

    corrected = copy.deepcopy(payload)
    for metric in corrected["data"]["metrics"]:
        if metric["name"] == "step_count":
            metric["data"][0]["qty"] = 404
    handler.lambda_handler(_hae_event(corrected, DAILY_HEADERS), None)

    assert _latest(table, "steps#hae_daily_summary")["value"] == 404
    assert not any(
        item["metric_source"] == "steps#hae_daily_summary_samples"
        for item in table.items
    )


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


def test_raw_vitals_stream_preserves_metadata_and_does_not_sum_physical_effort():
    handler, table = _fresh_module()
    _patch_auth(handler)
    payload = _fixture("hae_v2_vitals_mobility_sanitized.json")

    handler.lambda_handler(_hae_event(payload, RAW_HEADERS), None)
    handler.lambda_handler(_hae_event(payload, RAW_HEADERS), None)

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


def test_missing_headers_keep_legacy_raw_compatibility_and_unsupported_aggregation_is_rejected():
    handler, table = _fresh_module()
    _patch_auth(handler)
    raw_payload = _fixture("hae_v2_vitals_mobility_sanitized.json")

    response = handler.lambda_handler(_event(raw_payload), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["hae_semantics"] == "legacy_unclassified"
    assert _latest(table, "physical_effort#hae")["hae_semantics"] == "legacy_unclassified"

    rejected = handler.lambda_handler(
        _hae_event(
            raw_payload,
            {
                "automation-aggregation": "Minutes",
                "automation-period": "Yesterday",
            },
        ),
        None,
    )
    assert rejected["statusCode"] == 422


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
