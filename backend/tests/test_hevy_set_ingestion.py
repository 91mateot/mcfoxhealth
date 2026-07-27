"""
Tests for Hevy set-level ingestion (shared/shared/hevy_client.py + the
ingest handler wiring in functions/ingest/handler.py).

All offline: the HTTP layer is injected via the ``http_get`` seam and the DB is
stubbed, so no real Hevy key or AWS is required. Covers:
  - exercise-row mapping fidelity (kg→lb, warmup vs dropset/failure, RPE)
  - superset pairing both directions
  - muscle-group mapping for all 20 Hevy enum values
  - template cache hit / miss / staleness
  - idempotent re-poll + deleted-workout handling via the events endpoint
  - body-measurement unit conversion (cm→in, kg→lb)
  - graceful degradation when a Hevy endpoint returns non-200
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))

from shared import hevy_client as hc  # noqa: E402
from shared.exercise_canonical import MUSCLE_GROUPS  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────

def _ex(title="Bench Press (Barbell)", template_id="tmpl-bench", sets=None,
        supersets_id=None, notes=None):
    return {
        "index": 0,
        "title": title,
        "notes": notes,
        "exercise_template_id": template_id,
        "supersets_id": supersets_id,
        "sets": sets if sets is not None else [
            {"index": 0, "type": "normal", "weight_kg": 60, "reps": 10},
        ],
    }


def _workout(wid="w1", start="2026-06-30T18:00:00+00:00",
             end="2026-06-30T19:00:00+00:00", exercises=None, **extra):
    w = {
        "id": wid,
        "title": "Push Day",
        "start_time": start,
        "end_time": end,
        "exercises": exercises if exercises is not None else [_ex()],
    }
    w.update(extra)
    return w


def _fake_http(pages):
    """http_get stub returning successive (body, status) tuples in order."""
    calls = {"n": 0}

    def _get(url, api_key):
        i = calls["n"]
        calls["n"] += 1
        if i < len(pages):
            return pages[i]
        return {"page": 1, "page_count": 1}, 200

    _get.calls = calls
    return _get


# ── Exercise-row mapping fidelity ───────────────────────────────────

def test_set_kg_to_lb_conversion():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(sets=[{"type": "normal", "weight_kg": 100, "reps": 5}])
    ]))
    assert len(rows) == 1
    s = rows[0]["sets"][0]
    assert s["weight"] == round(100 * hc.KG_TO_LB, 1)
    assert s["reps"] == 5
    assert s["unit"] == "lbs"


def test_warmup_vs_dropset_failure_classification():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[_ex(sets=[
        {"type": "warmup", "weight_kg": 40, "reps": 10},
        {"type": "normal", "weight_kg": 60, "reps": 8},
        {"type": "dropset", "weight_kg": 50, "reps": 6},
        {"type": "failure", "weight_kg": 60, "reps": 3},
    ])]))
    sets = rows[0]["sets"]
    # Only the warmup is flagged warmup=True.
    assert sets[0]["warmup"] is True
    assert sets[1]["warmup"] is False
    assert sets[2]["warmup"] is False  # dropset is a working set
    assert sets[3]["warmup"] is False  # failure is a working set
    # Hevy type preserved verbatim on every set.
    assert [s["type"] for s in sets] == ["warmup", "normal", "dropset", "failure"]


def test_rpe_and_extra_fields_preserved():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[_ex(sets=[
        {"type": "normal", "weight_kg": 60, "reps": 8, "rpe": 8.5,
         "duration_seconds": 45, "distance_meters": 12.5, "custom_metric": 3},
    ])]))
    s = rows[0]["sets"][0]
    assert s["rpe"] == 8.5
    assert s["duration_sec"] == 45
    assert s["distance_meters"] == 12.5
    assert s["custom_metric"] == 3


def test_null_weight_and_reps_tolerated():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[_ex(sets=[
        {"type": "normal", "weight_kg": None, "reps": None},
    ])]))
    s = rows[0]["sets"][0]
    assert s["weight"] == 0.0
    assert s["reps"] == 0


def test_exercise_note_and_template_id_preserved():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(template_id="tmpl-xyz", notes="felt heavy today")
    ]))
    assert rows[0]["note"] == "felt heavy today"
    assert rows[0]["exercise_template_id"] == "tmpl-xyz"


# ── Superset pairing (both directions) ──────────────────────────────

def test_superset_pairing_both_directions():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Seated Cable Row", template_id="t1", supersets_id=7),
        _ex(title="Plank", template_id="t2", supersets_id=7),
        _ex(title="Hip Abductor", template_id="t3", supersets_id=None),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    assert by_canon["seated_cable_row"]["superset_with"] == "plank"
    assert by_canon["plank"]["superset_with"] == "seated_cable_row"
    # Non-superset exercise carries no pairing.
    assert "superset_with" not in by_canon["hip_abductor"]


def test_no_superset_when_id_null():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Bench Press", supersets_id=None),
    ]))
    assert "superset_with" not in rows[0]


# ── Muscle-group mapping: all 20 Hevy enum values ───────────────────

def test_muscle_group_mapping_all_20_enum_values():
    expected = {
        "abdominals": "core",
        "shoulders": "shoulders",
        "biceps": "arms",
        "triceps": "arms",
        "forearms": "arms",
        "quadriceps": "legs",
        "hamstrings": "legs",
        "calves": "legs",
        "glutes": "glutes",
        "abductors": "glutes",
        "adductors": "legs",
        "lats": "back",
        "upper_back": "back",
        "traps": "back",
        "lower_back": "back",
        "chest": "chest",
        "cardio": "cardio",
        "neck": "other",
        "full_body": "other",
        "other": "other",
    }
    assert len(expected) == 20
    for hevy_val, app_val in expected.items():
        got = hc.map_muscle_group(hevy_val)
        assert got == app_val, f"{hevy_val} → {got}, expected {app_val}"
        assert got in MUSCLE_GROUPS


def test_muscle_group_unknown_falls_back_to_other():
    assert hc.map_muscle_group("not_a_real_group") == "other"
    assert hc.map_muscle_group(None) == "other"
    assert hc.map_muscle_group("") == "other"


def test_muscle_group_resolved_from_template_cache():
    templates = {"tmpl-bench": {"primary_muscle_group": "chest"}}
    rows = hc.workout_to_exercise_rows(_workout(exercises=[_ex(template_id="tmpl-bench")]),
                                       templates)
    assert rows[0]["muscle_group"] == "chest"
    assert rows[0]["hevy_muscle_group"] == "chest"


def test_muscle_group_defaults_other_without_template():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[_ex(template_id="unknown")]),
                                       templates={})
    assert rows[0]["muscle_group"] == "other"
    assert "hevy_muscle_group" not in rows[0]


# ── Template cache: fetch + staleness ───────────────────────────────

def test_fetch_exercise_templates_paginates_and_indexes():
    p1 = ({"page": 1, "page_count": 2, "exercise_templates": [
        {"id": "a", "title": "Bench", "primary_muscle_group": "chest",
         "type": "weight_reps", "equipment_category": "barbell", "is_custom": False},
    ] * 100}, 200)
    p2 = ({"page": 2, "page_count": 2, "exercise_templates": [
        {"id": "z", "title": "Curl", "primary_muscle_group": "biceps"},
    ]}, 200)
    http = _fake_http([p1, p2])
    templates = hc.fetch_exercise_templates("k", page_size=100, http_get=http)
    assert "a" in templates and "z" in templates
    assert templates["z"]["primary_muscle_group"] == "biceps"
    assert http.calls["n"] == 2


def test_fetch_exercise_templates_degrades_on_error():
    http = _fake_http([(None, 500)])
    assert hc.fetch_exercise_templates("k", http_get=http) == {}


def test_templates_cache_staleness():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    fresh = {"templates": {"a": {}}, "fetched_at": now.isoformat()}
    stale = {"templates": {"a": {}},
             "fetched_at": (now - timedelta(days=8)).isoformat()}
    assert hc.templates_cache_is_stale(None) is True
    assert hc.templates_cache_is_stale({}) is True
    assert hc.templates_cache_is_stale({"templates": {}}) is True
    assert hc.templates_cache_is_stale(fresh) is False
    assert hc.templates_cache_is_stale(stale) is True


# ── Events endpoint: updates + deletions ────────────────────────────

def test_fetch_workout_events_classifies_updates_and_deletes():
    events_body = {"page": 1, "page_count": 1, "events": [
        {"type": "updated", "workout": _workout("w1")},
        {"type": "deleted", "id": "w2", "deleted_at": "2026-06-30T12:00:00Z"},
        {"type": "updated", "workout": _workout("w3")},
    ]}
    http = _fake_http([(events_body, 200)])
    result = hc.fetch_workout_events("k", since="2026-06-01T00:00:00Z", http_get=http)
    assert [w["id"] for w in result["updated"]] == ["w1", "w3"]
    assert result["deleted"] == ["w2"]


def test_fetch_workout_events_degrades_on_error():
    http = _fake_http([(None, 503)])
    result = hc.fetch_workout_events("k", since="2026-06-01T00:00:00Z", http_get=http)
    assert result == {"updated": [], "deleted": []}


# ── Body-measurement unit conversion ────────────────────────────────

def test_body_measurement_unit_conversion():
    m = {
        "date": "2026-06-30",
        "weight_kg": 76.66,
        "lean_mass_kg": 66.0,
        "fat_percent": 13.6,
        "waist": 81.28,   # cm → 32.0 in
        "left_bicep_cm": 35.0,
    }
    metrics = hc.body_measurement_to_metrics(m)
    by_source = {ms: (unit, kind, date, val) for ms, unit, kind, date, val in metrics}
    # weight kg → lb
    assert by_source["weight#hevy"][0] == "lb"
    assert by_source["weight#hevy"][3] == round(76.66 * hc.KG_TO_LB, 2)
    # lean mass kg → lb
    assert by_source["lean_mass#hevy"][3] == round(66.0 * hc.KG_TO_LB, 2)
    # body fat percent — no conversion
    assert by_source["bodyfat_hevy#hevy"] == ("pct", "last", "2026-06-30", 13.6)
    # waist cm → in
    assert by_source["waist#hevy"][0] == "in"
    assert by_source["waist#hevy"][3] == round(81.28 * hc.CM_TO_IN, 2)
    # bicep cm → in, distinct source
    assert by_source["left_bicep#hevy"][0] == "in"
    # all are "last" kind
    assert all(kind == "last" for _, _, kind, _, _ in metrics)


def test_body_measurement_skips_null_fields_and_bad_date():
    assert hc.body_measurement_to_metrics({"date": None, "weight_kg": 80}) == []
    metrics = hc.body_measurement_to_metrics({"date": "2026-06-30", "weight_kg": None,
                                              "waist": None})
    assert metrics == []


# ── Enriched rolled-up workout row ──────────────────────────────────

def test_workout_row_flags_calories_unavailable():
    row = hc.workout_to_row(_workout())
    assert row["cal"] == 0
    assert row["cal_unavailable"] is True


def test_workout_row_preserves_session_fields():
    w = _workout(description="went hard today", routine_id="r1",
                 updated_at="2026-06-30T19:05:00Z", exercises=[_ex(sets=[
                     {"type": "normal", "weight_kg": 60, "reps": 8, "rpe": 8},
                     {"type": "warmup", "weight_kg": 40, "reps": 10, "rpe": 3},
                     {"type": "dropset", "weight_kg": 50, "reps": 6, "rpe": 9},
                 ])])
    row = hc.workout_to_row(w)
    assert row["description"] == "went hard today"
    assert row["routine_id"] == "r1"
    assert row["updated_at"] == "2026-06-30T19:05:00Z"
    assert row["start_time"] == w["start_time"]
    assert row["end_time"] == w["end_time"]
    # set-type breakdown across the session
    assert row["set_type_breakdown"] == {"normal": 1, "warmup": 1, "dropset": 1}
    # avg/max RPE over WORKING sets only (warmup RPE excluded)
    assert row["max_rpe"] == 9.0
    assert row["avg_rpe"] == round((8 + 9) / 2, 1)


def test_workout_row_no_rpe_stats_when_absent():
    row = hc.workout_to_row(_workout(exercises=[_ex(sets=[
        {"type": "normal", "weight_kg": 60, "reps": 8},
    ])]))
    assert "avg_rpe" not in row
    assert "max_rpe" not in row
