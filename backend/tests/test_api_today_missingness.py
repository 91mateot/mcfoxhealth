"""Offline contract tests for missingness-safe /api/today semantics."""

import importlib.util
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API_PATH = os.path.join(ROOT, "functions", "api", "handler.py")


def _handler(monkeypatch, *, scores=None, baselines=None, config=None, nutrition=None):
    for mod in list(sys.modules):
        if mod == "api_handler_missingness_under_test":
            sys.modules.pop(mod, None)

    spec = importlib.util.spec_from_file_location("api_handler_missingness_under_test", _API_PATH)
    handler = importlib.util.module_from_spec(spec)
    sys.modules["api_handler_missingness_under_test"] = handler
    spec.loader.exec_module(handler)

    score_rows = scores or {}
    nutrition_rows = nutrition or {}
    fixed_now = datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(handler, "local_now", lambda: fixed_now)
    monkeypatch.setattr(handler, "get_table", lambda env_name: env_name)

    def fake_get_item(table, key):
        if table == "DAILY_SCORES_TABLE":
            return score_rows.get(key["date"])
        if table == "BASELINES_TABLE":
            return baselines
        if table == "USER_CONFIG_TABLE":
            return config
        return None

    def fake_query_items(table, _pk_name, date, *_args, **_kwargs):
        if table == "NUTRITION_TABLE":
            return nutrition_rows.get(date, [])
        return []

    monkeypatch.setattr(handler, "get_item", fake_get_item)
    monkeypatch.setattr(handler, "query_items", fake_query_items)
    monkeypatch.setattr(handler, "_journal_for_today", lambda _today: ({}, {}))
    monkeypatch.setattr(handler, "_prepare_planned_workout", lambda *_args: None)
    return handler


def _today_payload(handler):
    response = handler._get_today()
    assert response["statusCode"] == 200
    return json.loads(response["body"])


def test_missing_rows_are_null_and_do_not_generate_warnings(monkeypatch):
    payload = _today_payload(_handler(monkeypatch))

    assert payload["recovery"] is None
    assert payload["recoveryZone"] is None
    assert payload["strain"] is None
    assert payload["sleep"]["score"] is None
    assert payload["sleep"]["hours"] is None
    assert payload["sleepNeedTonight"] is None
    assert payload["steps"] is None
    assert payload["calories"] == {"active": None, "resting": None}
    assert payload["water"] is None
    assert payload["caffeineMg"] is None
    assert payload["base"]["hrv"] is None
    assert payload["base"]["rhr"] is None
    assert payload["hrv30d"] == [None] * 30
    assert all(day["rec"] is None and day["strain"] is None for day in payload["recoveryWeek"])
    assert all(day["v"] is None for day in payload["stepsWeek"])
    assert all(day["p"] is None and day["cal"] is None for day in payload["proteinWeek"])
    assert payload["coachInsights"] == []

    semantics = payload["metricSemantics"]
    assert semantics["recovery"]["availability"] == "unavailable"
    assert semantics["hrv30d"] == {"availability": "unavailable", "kind": "observed", "samples": 0, "expectedSamples": 30}
    assert semantics["baseHrv"]["availability"] == "insufficient_history"
    assert semantics["strainTarget"]["kind"] == "fallback"
    assert semantics["nutritionTargets"]["kind"] == "fallback"


def test_stored_zeroes_remain_available_zeroes(monkeypatch):
    scores = {
        "2026-08-09": {
            "date": "2026-08-09",
            "recovery": 0,
            "recovery_zone": "red",
            "strain": 0,
            "sleep_score": 0,
            "sleep": {"total_min": 0, "efficiency": 0, "deep_min": 0, "rem_min": 0, "core_min": 0, "awake_min": 0},
            "hrv": 0,
            "rhr": 0,
            "steps": 0,
            "active_cal": 0,
            "protein_total": 0,
            "cal_total": 0,
        }
    }
    nutrition = {
        "2026-08-09": [
            {"meal_id": "water_zero", "oz": 0},
            {"meal_id": "meal_zero", "caffeine_mg": 0},
        ]
    }
    payload = _today_payload(_handler(monkeypatch, scores=scores, nutrition=nutrition))

    assert payload["recovery"] == 0
    assert payload["strain"] == 0
    assert payload["sleep"]["score"] == 0
    assert payload["sleep"]["hours"] == 0
    assert payload["hrv"] == 0
    assert payload["steps"] == 0
    assert payload["calories"]["active"] == 0
    assert payload["water"] == 0
    assert payload["caffeineMg"] == 0
    assert payload["proteinWeek"][-1]["p"] == 0
    assert payload["metricSemantics"]["steps"] == {
        "availability": "available",
        "kind": "observed",
        "source": "legacy_hae_aggregate",
    }
    assert payload["metricSemantics"]["protein"] == {"availability": "available", "kind": "derived"}


def test_partial_history_keeps_gaps_and_reports_sample_count(monkeypatch):
    scores = {
        "2026-08-08": {"date": "2026-08-08", "hrv": 41, "steps": 7000, "recovery": 55, "strain": 6, "protein_total": 120},
        "2026-08-09": {"date": "2026-08-09", "hrv": 43, "steps": 0, "recovery": 0, "strain": 0, "protein_total": 0},
    }
    payload = _today_payload(_handler(monkeypatch, scores=scores))

    assert payload["hrv30d"][-3:] == [None, 41, 43]
    assert payload["stepsWeek"][-2]["v"] == 7000
    assert payload["stepsWeek"][-1]["v"] == 0
    assert payload["metricSemantics"]["hrv30d"]["availability"] == "insufficient_history"
    assert payload["metricSemantics"]["hrv30d"]["samples"] == 2
    assert payload["metricSemantics"]["recoveryWeek"]["samples"] == 2
    assert payload["metricSemantics"]["proteinWeek"]["samples"] == 2


def test_partial_sleep_does_not_invent_component_values(monkeypatch):
    payload = _today_payload(_handler(monkeypatch, scores={
        "2026-08-09": {
            "date": "2026-08-09",
            "sleep_score": 72,
            "sleep": {"total_min": 420, "deep_min": 70},
        }
    }))

    assert payload["sleep"]["hours"] == 7
    assert payload["sleep"]["deep"] == 70
    assert payload["sleep"]["efficiency"] is None
    assert payload["sleep"]["rem"] is None
    assert payload["sleep"]["componentScores"] is None
    assert payload["metricSemantics"]["sleep"] == {"availability": "available", "kind": "derived"}


def test_configured_targets_and_derived_baselines_are_labeled(monkeypatch):
    payload = _today_payload(_handler(
        monkeypatch,
        baselines={"type": "current", "hrv": 52, "rhr": 58, "resp": 14.1, "steps": 9000},
        config={"key": "mateo", "nutrition_targets": {"cal": 2300, "p": 190, "c": 200, "f": 70, "water": 110, "caffeine": 350}},
        scores={"2026-08-09": {"strain_target": {"low": 7, "high": 11, "optimal": 9, "reason": "Derived from recovery"}}},
    ))

    assert payload["base"] == {"hrv": 52, "rhr": 58, "resp": 14.1, "sleepNeed": 7.5, "steps": 9000}
    assert payload["metricSemantics"]["baseHrv"]["kind"] == "derived"
    assert payload["metricSemantics"]["strainTarget"]["kind"] == "derived"
    assert payload["metricSemantics"]["nutritionTargets"]["kind"] == "configured_target"
    assert payload["metricSemantics"]["baseSleepNeed"]["kind"] == "configured_target"


def test_populated_today_values_keep_the_existing_response_shape(monkeypatch):
    score = {
        "date": "2026-08-09",
        "recovery": 82,
        "recovery_zone": "green",
        "strain": 6.4,
        "strain_target": {"low": 12, "high": 16, "optimal": 14, "reason": "Recovered"},
        "sleep_score": 88,
        "sleep": {"total_min": 455, "efficiency": 92, "deep_min": 78, "rem_min": 91, "core_min": 268, "awake_min": 18},
        "sleep_need": {"baseMin": 450, "debtMin": 0, "strainMin": 10, "totalMin": 460, "bedtimeBy": "10:15p"},
        "hrv": 54,
        "rhr": 57,
        "resp": 14.0,
        "spo2": 97,
        "wrist_temp": 32.4,
        "steps": 8421,
        "active_cal": 420,
        "protein_total": 135,
        "cal_total": 1750,
    }
    payload = _today_payload(_handler(monkeypatch, scores={"2026-08-09": score}))

    assert payload["recovery"] == 82
    assert payload["recoveryZone"] == "green"
    assert payload["strain"] == 6.4
    assert payload["strainTarget"] == score["strain_target"]
    assert payload["sleep"]["score"] == 88
    assert payload["sleep"]["hours"] == 7
    assert payload["sleep"]["minutes"] == 35
    assert payload["sleepNeedTonight"] == score["sleep_need"]
    assert payload["hrv"] == 54
    assert payload["steps"] == 8421
    assert payload["calories"]["active"] == 420
    assert len(payload["recoveryWeek"]) == 7
    assert len(payload["hrv30d"]) == 30
    assert payload["metricSemantics"]["recovery"] == {"availability": "available", "kind": "derived"}
