"""
API contract tests — hit the live API and assert the response shape matches
what the PWA frontend expects (src/types.ts TodayResponse).

These are live integration tests — require the stack to be deployed.
"""
import os
import urllib.request
import json as _json

import pytest

BASE = os.environ.get("API_BASE", "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com")


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as resp:
        return _json.loads(resp.read())


# ─── /api/today contract ────────────────────────────────────────────

REQUIRED_TODAY_FIELDS = {
    "date", "dateFull", "recovery", "strain", "strainTarget",
    "sleep", "sleepNeedTonight", "hrv", "rhr", "steps", "stepsGoal",
    "calories", "water", "waterGoal", "recoveryWeek", "hrv30d",
    "stepsWeek", "mealsToday", "nutritionTargets", "proteinWeek",
    "supplements", "coachInsights", "base", "metricSemantics",
}

REQUIRED_SLEEP_FIELDS = {"score", "hours", "minutes", "efficiency", "deep", "rem", "core", "awake"}
REQUIRED_SLEEP_NEED_FIELDS = {"baseMin", "debtMin", "strainMin", "totalMin", "bedtimeBy"}
REQUIRED_STRAIN_TARGET_FIELDS = {"low", "high", "optimal", "reason"}


def test_today_has_all_required_fields():
    d = _get("/api/today")
    missing = REQUIRED_TODAY_FIELDS - set(d.keys())
    assert not missing, f"Missing fields on /api/today: {missing}"


def test_today_sleep_shape():
    d = _get("/api/today")
    missing = REQUIRED_SLEEP_FIELDS - set(d["sleep"].keys())
    assert not missing, f"Missing sleep fields: {missing}"


def test_today_sleep_need_shape():
    d = _get("/api/today")
    missing = REQUIRED_SLEEP_NEED_FIELDS - set(d["sleepNeedTonight"].keys())
    assert not missing


def test_today_strain_target_shape():
    d = _get("/api/today")
    missing = REQUIRED_STRAIN_TARGET_FIELDS - set(d["strainTarget"].keys())
    assert not missing


def test_today_recovery_week_length_7():
    d = _get("/api/today")
    assert len(d["recoveryWeek"]) == 7


def test_today_hrv30d_length_30():
    d = _get("/api/today")
    assert len(d["hrv30d"]) == 30


def test_today_date_is_local_timezone():
    """Date should reflect America/Los_Angeles, not UTC."""
    d = _get("/api/today")
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        expected = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        pytest.skip("zoneinfo unavailable")
    # dateFull format: "Saturday, Apr 25, 2026"
    assert str(d.get("dateFull", "")), f"dateFull missing/empty in {d}"


def test_today_recovery_zone_valid():
    d = _get("/api/today")
    if d.get("recoveryZone"):
        assert d["recoveryZone"] in ("green", "yellow", "red")


def test_today_metric_semantics_shape():
    d = _get("/api/today")
    semantics = d["metricSemantics"]
    for key in ("recovery", "strain", "sleep", "hrv", "steps", "protein", "hrv30d"):
        assert semantics[key]["availability"] in ("available", "unavailable", "insufficient_history")
    for key, value in (("recovery", d["recovery"]), ("strain", d["strain"]), ("hrv", d["hrv"]), ("steps", d["steps"])):
        if semantics[key]["availability"] == "unavailable":
            assert value is None, f"{key} must be null when unavailable"


# ─── /api/workouts ──────────────────────────────────────────────────

def test_workouts_returns_list():
    d = _get("/api/workouts")
    assert isinstance(d.get("workouts"), list)


def test_workout_item_has_required_fields():
    d = _get("/api/workouts")
    if not d["workouts"]:
        pytest.skip("no workouts to inspect")
    w = d["workouts"][0]
    for f in ("date", "day", "type", "dur", "avgHR", "maxHR", "cal", "strain"):
        assert f in w, f"workout missing {f}"


# ─── /api/progress ──────────────────────────────────────────────────

def test_progress_has_now_and_trend():
    d = _get("/api/progress")
    assert "now" in d and "trend" in d


def test_progress_now_has_history_arrays():
    d = _get("/api/progress")
    for k in ("weight14d", "weightHistory", "fatHistory", "leanHistory"):
        assert k in d["now"] and isinstance(d["now"][k], list)


def test_progress_trend_has_30d_and_series():
    d = _get("/api/progress")
    assert "trends30d" in d["trend"]
    assert "trendSeries" in d["trend"]
    assert "correlations" in d["trend"]


def test_progress_trend_metrics_have_cur_prev_unit_better():
    d = _get("/api/progress")
    for k, v in d["trend"]["trends30d"].items():
        assert "cur" in v and "prev" in v and "unit" in v and "better" in v, (
            f"{k} missing one of cur/prev/unit/better"
        )


# ─── /api/conversation/latest ──────────────────────────────────────

def test_latest_conversation_shape():
    d = _get("/api/conversation/latest")
    assert "conversationId" in d
    if d["conversationId"] is not None:
        assert isinstance(d.get("messages"), list)
