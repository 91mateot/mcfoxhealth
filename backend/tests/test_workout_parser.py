"""Unit tests for the lift parser's sanitization layer.

We mock the Bedrock call (it's the LLM — trusting its JSON output is the whole
point) and assert that:
  1. _sanitize_exercise drops malformed rows and caps fields
  2. _canonicalize hits synonyms and falls back deterministically
  3. annotate_workout stores the expected data shape (with mocked DynamoDB)
"""
import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    """Import shared.workout_service with boto3 stubbed.

    Ingest tests (test_ingest_parser.py) insert backend/functions/ingest/ onto
    sys.path, where a synced copy of `shared/` can shadow the canonical
    backend/shared/shared. Drop any cached `shared*` entries and import from
    the authoritative location explicitly."""
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    # Drop any cached copy so a stale `shared` package from another test is
    # evicted before we re-import.
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.workout_service as ws
    return ws


def test_canonicalize_synonyms(monkeypatch):
    ws = _load_module(monkeypatch)
    assert ws._canonicalize("bench press") == "bench_press"
    assert ws._canonicalize("OHP") == "overhead_press"
    assert ws._canonicalize("seated row") == "seated_cable_row"
    assert ws._canonicalize("seated back row") == "seated_cable_row"
    assert ws._canonicalize("lat pulldown") == "lat_pulldown"


def test_canonicalize_fallback_strips_qualifiers(monkeypatch):
    ws = _load_module(monkeypatch)
    # "barbell bench" → strip "barbell" → "bench" → bench_press
    assert ws._canonicalize("barbell bench") == "bench_press"


def test_canonicalize_unknown_is_slugified(monkeypatch):
    ws = _load_module(monkeypatch)
    assert ws._canonicalize("Goblet Squat Pulse") == "goblet_squat_pulse"
    assert ws._canonicalize("Some Weird Thing!!") == "some_weird_thing"


def test_sanitize_set_bounds(monkeypatch):
    ws = _load_module(monkeypatch)
    assert ws._sanitize_set({"reps": 10, "weight": 205}) == {"reps": 10, "weight": 205.0, "unit": "lbs"}
    # Out-of-range reps/weight dropped.
    assert ws._sanitize_set({"reps": 9999, "weight": 100}) is None
    assert ws._sanitize_set({"reps": 5, "weight": -5}) is None
    # Warmup flag preserved.
    assert ws._sanitize_set({"reps": 8, "weight": 135, "warmup": True}).get("warmup") is True
    # Plank with duration.
    assert ws._sanitize_set({"reps": 1, "weight": 0, "duration_sec": 30}).get("duration_sec") == 30


def test_sanitize_exercise_empty_name_dropped(monkeypatch):
    ws = _load_module(monkeypatch)
    assert ws._sanitize_exercise({"name": "", "sets": []}) is None


def test_sanitize_exercise_invalid_muscle_falls_to_other(monkeypatch):
    ws = _load_module(monkeypatch)
    out = ws._sanitize_exercise({"name": "Bench Press", "canonical": "bench_press", "muscle_group": "biceps_tricep_fusion", "sets": []})
    assert out["muscle_group"] == "other"


def test_sanitize_cardio_strips_non_numeric_params(monkeypatch):
    ws = _load_module(monkeypatch)
    out = ws._sanitize_cardio({"name": "Treadmill", "params": {"speed_mph": 7.5, "pace_str": "fast"}, "duration_min": 20})
    assert out["params"] == {"speed_mph": 7.5}
    assert out["duration_min"] == 20.0


def test_annotate_workout_end_to_end(monkeypatch):
    """Mock the Bedrock parser response and confirm:
    - workout row gets exercises/cardio_intervals/session_notes
    - ExercisesTable gets one put per exercise"""
    ws = _load_module(monkeypatch)

    # Seed the Bedrock call.
    parsed = {
        "exercises": [
            {
                "name": "Seated Cable Row",
                "canonical": "seated_cable_row",
                "muscle_group": "back",
                "sets": [
                    {"reps": 10, "weight": 90, "warmup": True},
                    {"reps": 10, "weight": 140},
                    {"reps": 10, "weight": 140},
                ],
                "superset_with": "single_arm_march",
            },
            {
                "name": "Hip Abductor",
                "canonical": "hip_abductor",
                "muscle_group": "glutes",
                "sets": [
                    {"reps": 10, "weight": 80},
                    {"reps": 10, "weight": 90},
                    {"reps": 10, "weight": 100},
                ],
                "superset_with": None,
            },
        ],
        "cardio_intervals": [
            {"name": "Stationary bike", "params": {"distance_mi": 2}, "duration_min": 10},
        ],
        "session_notes": "Outer hips sore, didn't affect workout.",
        "suggested_journal_tags": [],
    }
    monkeypatch.setattr(ws, "_parse_lift_text", lambda text: parsed)

    workouts_puts = []
    exercises_puts = []
    seed_workout = {"date": "2026-04-27", "strava_id": "12345", "title": "Workout", "type": "cardio", "source": "strava"}

    workouts_table = MagicMock()
    workouts_table.query = MagicMock(return_value={"Items": [seed_workout]})
    exercises_table = MagicMock()

    def fake_get_table(env_var):
        if env_var == "WORKOUTS_TABLE":
            return workouts_table
        if env_var == "EXERCISES_TABLE":
            return exercises_table
        raise ValueError(f"unexpected table {env_var}")

    def fake_put_item(table, item):
        if table is workouts_table:
            workouts_puts.append(item)
        elif table is exercises_table:
            exercises_puts.append(item)

    def fake_query_items(table, pk_name, pk_val, **kw):
        if table is workouts_table and pk_val == "2026-04-27":
            return [seed_workout]
        return []

    monkeypatch.setattr(ws, "get_table", fake_get_table)
    monkeypatch.setattr(ws, "put_item", fake_put_item)
    monkeypatch.setattr(ws, "query_items", fake_query_items)

    result = ws.annotate_workout("paste", date="2026-04-27")

    assert result["ok"] is True
    assert result["exercise_count"] == 2
    assert result["cardio_count"] == 1
    assert sorted(result["muscle_groups"]) == ["back", "glutes"]

    # Workout row was patched with structured data.
    assert len(workouts_puts) == 1
    w = workouts_puts[0]
    assert len(w["exercises"]) == 2
    assert w["exercises"][0]["canonical"] == "seated_cable_row"
    assert w["exercises"][0]["superset_with"] == "single_arm_march"
    assert w["cardio_intervals"][0]["name"] == "Stationary bike"
    assert "outer hips" in w["session_notes"].lower()
    assert w["date"] == "2026-04-27"
    assert w["strava_id"] == "12345"  # Existing Strava row preserved.

    # ExercisesTable gets one row per exercise.
    assert len(exercises_puts) == 2
    ex_row = exercises_puts[0]
    assert ex_row["canonical"] == "seated_cable_row"
    assert ex_row["date"] == "2026-04-27"
    # Working volume: (140*10) + (140*10) = 2800. Warmup (90*10) excluded.
    assert ex_row["working_volume"] == 2800.0
    assert ex_row["top_weight"] == 140.0
    # Hip abductor: ramp, no warmups marked → all count. 80*10 + 90*10 + 100*10 = 2700.
    assert exercises_puts[1]["working_volume"] == 2700.0
    assert exercises_puts[1]["top_weight"] == 100.0


def test_annotate_creates_shell_when_no_workout_exists(monkeypatch):
    ws = _load_module(monkeypatch)

    parsed = {
        "exercises": [
            {"name": "Bench", "canonical": "bench_press", "muscle_group": "chest",
             "sets": [{"reps": 5, "weight": 205}]},
        ],
        "cardio_intervals": [],
        "session_notes": None,
        "suggested_journal_tags": [],
    }
    monkeypatch.setattr(ws, "_parse_lift_text", lambda t: parsed)

    workouts_puts = []
    exercises_puts = []

    workouts_table = MagicMock()
    exercises_table = MagicMock()

    monkeypatch.setattr(ws, "get_table",
        lambda n: workouts_table if n == "WORKOUTS_TABLE" else exercises_table)
    monkeypatch.setattr(ws, "put_item",
        lambda t, i: (workouts_puts if t is workouts_table else exercises_puts).append(i))
    monkeypatch.setattr(ws, "query_items", lambda *a, **k: [])  # No existing workout.

    result = ws.annotate_workout("bench 5x5 @ 205", date="2026-04-28")

    # _find_or_create_workout put a shell, then annotate patched it → 2 puts.
    assert len(workouts_puts) == 2
    assert workouts_puts[0]["strava_id"].startswith("manual_")
    assert workouts_puts[0]["source"] == "manual"
    # Final row has exercises.
    assert len(workouts_puts[1]["exercises"]) == 1
    assert result["exercise_count"] == 1
