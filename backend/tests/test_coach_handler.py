"""
Unit tests for the coach system-prompt builder (shared/coach_context.py).

The coach Lambda itself (functions/coach/app.py) is a FastAPI app that runs
behind Lambda Web Adapter and streams Bedrock responses; its request/response
shape is exercised end-to-end in deploy smoke tests. These tests focus on the
pure prompt-assembly logic, which is where the business rules live.

Covers:
  1. Snapshot path — TodayResponse-shaped dict yields today block with recovery,
     strain, macros, caffeine, hydration.
  2. DynamoDB fallback path — no snapshot → reads from DAILY_SCORES / NUTRITION
     / WORKOUTS / BASELINES and produces the legacy today block.
  3. All supporting sections: body composition, 7-day history, journal,
     correlations, Retatrutide context, nutrition targets.
"""
import sys
from unittest.mock import MagicMock

import pytest


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def seed_scores():
    return {
        "date": "2026-04-26",
        "recovery": 72,
        "recovery_zone": "green",
        "hrv": 48,
        "rhr": 62,
        "strain": 8.4,
        "strain_target": {"low": 14, "high": 17, "reason": "Recovered — train hard"},
        "sleep": {"total_min": 463, "efficiency": 93},
    }


@pytest.fixture
def seed_meals():
    return [
        {"meal_id": "meal_1", "p": 30, "cal": 170},
        {"meal_id": "meal_2", "p": 45, "cal": 500},
        {"meal_id": "water_1", "oz": 40},
    ]


@pytest.fixture
def seed_workouts():
    return [
        {
            "date": "2026-04-26",
            "strava_id": "12345",
            "title": "Morning Workout",
            "type": "Workout",
            "dur": 50,
            "avgHR": 112.4,
            "maxHR": 139,
            "cal": 0,
            "strain": 5.6,
            "trimp": 15.5,
            "zones": {"z1": 5, "z2": 3.8, "z3": 1, "z4": 0, "z5": 0},
        }
    ]


@pytest.fixture
def seed_baselines():
    return {
        "type": "current",
        "hrv": 42.0,
        "rhr": 64,
        "resp": 14.5,
        "sleep_min": 450,
        "steps": 10000,
        "spo2": 96.5,
        "wrist_temp": 32.5,
    }


@pytest.fixture
def seed_body_comp():
    return {
        "2026-04-25": [
            {"metric_source": "weight#withings", "value": 169.2},
            {"metric_source": "fat_ratio#withings", "value": 13.6},
            {"metric_source": "muscle_mass#withings", "value": 142.3},
        ],
    }


@pytest.fixture
def seed_week_scores():
    return {
        "2026-04-25": {"recovery": 38, "recovery_zone": "red", "hrv": 45.5, "rhr": 70, "strain": 10.2, "sleep": {"total_min": 463}},
        "2026-04-24": {"recovery": 82, "recovery_zone": "green", "hrv": 49, "rhr": 60, "strain": 7.5, "sleep": {"total_min": 480}},
    }


@pytest.fixture
def seed_journal():
    return {"date": "2026-04-25", "tags": ["alcohol", "late_meal"], "mood": 3, "stress": 4, "soreness": 2}


@pytest.fixture
def seed_correlations():
    return [
        {"tag": "alcohol", "metric": "HRV", "effect": -18, "unit": "%", "n": 6, "confidence": "high", "direction": "negative"},
        {"tag": "sauna", "metric": "Deep", "effect": 11, "unit": "%", "n": 5, "confidence": "medium", "direction": "positive"},
    ]


@pytest.fixture
def patched_context(
    monkeypatch,
    seed_scores,
    seed_meals,
    seed_workouts,
    seed_baselines,
    seed_body_comp,
    seed_week_scores,
    seed_journal,
    seed_correlations,
):
    """Stub shared.db so coach_context sees deterministic data."""
    # Force a fresh import so the monkeypatching takes effect on the module's
    # own imports of get_table/get_item/query_items.
    for name in ("shared.coach_context",):
        sys.modules.pop(name, None)

    import shared.db as db_mod

    def fake_get_table(env_name):
        mock = MagicMock(name=f"Table<{env_name}>")
        mock._env = env_name
        if env_name == "CORRELATIONS_TABLE":
            mock.scan.return_value = {"Items": seed_correlations}
        return mock

    def fake_get_item(table, key):
        env = getattr(table, "_env", "")
        if env == "DAILY_SCORES_TABLE":
            if key.get("date") == "2026-04-26":
                return seed_scores
            return seed_week_scores.get(key.get("date"))
        if env == "BASELINES_TABLE" and key.get("type") == "current":
            return seed_baselines
        if env == "JOURNAL_TABLE":
            if key.get("date") == seed_journal["date"]:
                return seed_journal
            return None
        return None

    def fake_query_items(table, _sk, val, **_kw):
        env = getattr(table, "_env", "")
        if val == "2026-04-26":
            if env == "WORKOUTS_TABLE":
                return seed_workouts
            if env == "NUTRITION_TABLE":
                return seed_meals
        if env == "HEALTH_METRICS_TABLE":
            return seed_body_comp.get(val, [])
        return []

    monkeypatch.setattr(db_mod, "get_table", fake_get_table)
    monkeypatch.setattr(db_mod, "get_item", fake_get_item)
    monkeypatch.setattr(db_mod, "query_items", fake_query_items)

    import shared.timezone as tz_mod
    monkeypatch.setattr(tz_mod, "local_today_str", lambda: "2026-04-26")

    # shared.coach_context binds get_table/get_item/query_items at import time
    # so we patch the already-bound names too.
    import shared.coach_context as ctx
    monkeypatch.setattr(ctx, "get_table", fake_get_table)
    monkeypatch.setattr(ctx, "get_item", fake_get_item)
    monkeypatch.setattr(ctx, "query_items", fake_query_items)
    monkeypatch.setattr(ctx, "local_today_str", lambda: "2026-04-26")
    return ctx


# ─── Tests: DynamoDB fallback path (no snapshot) ────────────────────

def test_prompt_includes_today_data_and_reta(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Recovery: 72%" in prompt
    assert "Strain so far: 8.4" in prompt
    assert "Retatrutide" in prompt
    assert "180g" in prompt


def test_prompt_includes_todays_workouts(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Today's Workouts" in prompt
    assert "Morning Workout" in prompt
    assert "50 min" in prompt
    assert "avg HR 112" in prompt
    assert "strain 5.6" in prompt


def test_prompt_includes_baselines_and_deltas(patched_context):
    prompt = patched_context.build_system_prompt(None)
    # Week history has HRV 45.5 vs baseline 42.0, RHR 70 vs 64 → deltas rendered
    # on today's vitals.
    assert "baseline 42.0" in prompt or "baseline 42" in prompt
    assert "baseline 64" in prompt


def test_prompt_includes_sleep_composition(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Deep:" in prompt
    assert "REM:" in prompt


def test_prompt_includes_extended_vitals(patched_context, seed_scores):
    seed_scores["resp"] = 14.3
    seed_scores["spo2"] = 97.2
    seed_scores["wrist_temp"] = 32.5
    prompt = patched_context.build_system_prompt(None)
    assert "Respiratory rate:" in prompt and "14.3" in prompt
    assert "SpO2:" in prompt and "97.2" in prompt
    assert "Wrist temperature:" in prompt


def test_prompt_includes_body_composition(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Body Composition" in prompt
    assert "169.2" in prompt
    assert "13.6" in prompt


def test_prompt_includes_week_history(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Last 7 Days" in prompt
    assert "2026-04-25" in prompt


def test_prompt_includes_last_journal(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Most Recent Journal" in prompt
    assert "alcohol" in prompt
    assert "Mood: 3/5" in prompt


def test_prompt_includes_correlations(patched_context):
    prompt = patched_context.build_system_prompt(None)
    assert "Learned Patterns" in prompt
    assert "alcohol" in prompt and "HRV" in prompt
    assert "-18" in prompt


def test_prompt_no_workouts_today(patched_context, monkeypatch):
    import shared.db as db_mod
    original = db_mod.query_items

    def no_workouts(table, sk, val, **kw):
        env = getattr(table, "_env", "")
        if env == "WORKOUTS_TABLE":
            return []
        return original(table, sk, val, **kw)

    monkeypatch.setattr(db_mod, "query_items", no_workouts)
    monkeypatch.setattr(patched_context, "query_items", no_workouts)

    prompt = patched_context.build_system_prompt(None)
    assert "No workout logged today yet." in prompt


# ─── Tests: snapshot path (client-sent TodayResponse) ────────────────

def test_snapshot_path_replaces_today_block(patched_context):
    snapshot = {
        "date": "Mon, Apr 27",
        "recovery": 84,
        "recoveryZone": "green",
        "hrv": 55,
        "rhr": 58,
        "strain": 5.1,
        "strainTarget": {"low": 13, "high": 16, "reason": "Recovered — push it"},
        "sleep": {"score": 91, "hours": 7, "minutes": 50, "efficiency": 95, "deep": 110, "rem": 92, "core": 180, "awake": 8},
        "sleepNeedTonight": {"totalMin": 460, "bedtimeBy": "10:00p"},
        "steps": 8421,
        "stepsGoal": 10000,
        "calories": {"active": 420, "resting": 1680},
        "water": 72,
        "waterGoal": 100,
        "caffeineMg": 180,
        "caffeineGoal": 400,
        "mealsToday": [
            {"time": "08:00", "name": "Oikos Shake", "cal": 170, "p": 30, "c": 8, "f": 3},
            {"time": "12:30", "name": "Chicken Bake", "cal": 770, "p": 61, "c": 78, "f": 25},
        ],
        "nutritionTargets": {"cal": 2200, "p": 180, "c": 190, "f": 65, "water": 100},
        "base": {"hrv": 42.0, "rhr": 64, "resp": 14.5, "sleepNeed": 7.5, "steps": 10000},
    }

    prompt = patched_context.build_system_prompt(snapshot)
    assert "live client snapshot" in prompt
    assert "Recovery: 84%" in prompt
    assert "HRV: 55 ms" in prompt
    assert "baseline 42" in prompt  # delta rendered vs baseline
    assert "Oikos Shake" in prompt
    assert "Chicken Bake" in prompt
    # Protein 30+61=91, calories 170+770=940
    assert "Protein: 91g" in prompt
    assert "Calories: 940" in prompt
    assert "Caffeine: 180 mg" in prompt
    assert "Water: 72 oz" in prompt
    # Retatrutide / coach context still intact
    assert "Retatrutide" in prompt
    assert "Body Composition" in prompt  # still DB-driven


def test_snapshot_with_null_vitals(patched_context):
    """A snapshot with no HRV/RHR yet should degrade gracefully."""
    snapshot = {
        "date": "Tue, Apr 28",
        "recovery": None,
        "recoveryZone": None,
        "hrv": None,
        "rhr": None,
        "strain": None,
        "strainTarget": {},
        "sleep": {},
        "sleepNeedTonight": {},
        "calories": {},
        "mealsToday": [],
        "nutritionTargets": {},
        "base": {},
        "metricSemantics": {
            "recovery": {"availability": "unavailable"},
            "strain": {"availability": "unavailable"},
            "protein": {"availability": "unavailable"},
        },
    }
    prompt = patched_context.build_system_prompt(snapshot)
    assert "HRV: n/a" in prompt
    assert "Resting HR: n/a" in prompt
    assert "Recovery: n/a" in prompt
    assert "Strain so far: n/a" in prompt
    assert "Protein: n/a" in prompt
    assert "Water: n/a" in prompt
    assert "None%" not in prompt
    assert "No meals logged yet today." in prompt
