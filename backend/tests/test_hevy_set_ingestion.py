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
        superset_id=None, notes=None):
    return {
        "index": 0,
        "title": title,
        "notes": notes,
        "exercise_template_id": template_id,
        # Real live-API key is ``superset_id`` (singular). Hevy's published
        # OpenAPI spec calls it ``supersets_id`` (plural) — the spec is wrong,
        # so fixtures use the real key the code reads from production payloads.
        "superset_id": superset_id,
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
        _ex(title="Seated Cable Row", template_id="t1", superset_id=7),
        _ex(title="Plank", template_id="t2", superset_id=7),
        _ex(title="Hip Abductor", template_id="t3", superset_id=None),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    assert by_canon["seated_cable_row"]["superset_with"] == "plank"
    assert by_canon["plank"]["superset_with"] == "seated_cable_row"
    # Non-superset exercise carries no pairing.
    assert "superset_with" not in by_canon["hip_abductor"]
    assert "superset_group" not in by_canon["hip_abductor"]


def test_no_superset_when_id_null():
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Bench Press", superset_id=None),
    ]))
    assert "superset_with" not in rows[0]
    assert "superset_group" not in rows[0]


def test_superset_group_id_zero_not_dropped():
    """Regression: ``superset_id`` starts at 0. A truthiness check (``if sid:``)
    would wrongly skip group 0 — which is the most common real group id. The
    resolver MUST use ``is not None`` so group 0 pairs correctly."""
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Hammer Curl (Cable)", template_id="t1", superset_id=0),
        _ex(title="Triceps Rope Pushdown", template_id="t2", superset_id=0),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    assert by_canon["hammer_curl"]["superset_with"] == "triceps_rope_pushdown"
    assert by_canon["triceps_rope_pushdown"]["superset_with"] == "hammer_curl"
    # superset_group carries the full grouping in both directions.
    assert by_canon["hammer_curl"]["superset_group"] == ["triceps_rope_pushdown"]
    assert by_canon["triceps_rope_pushdown"]["superset_group"] == ["hammer_curl"]


def test_superset_group_three_members_no_loss():
    """Regression: the real 2026-07-22 group had THREE members. superset_with
    (single canonical) alone loses the third — superset_group preserves ALL
    other members for each row."""
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Standing Calf Raise (Dumbbell)", template_id="t1", superset_id=0),
        _ex(title="Farmers Walk", template_id="t2", superset_id=0),
        _ex(title="Rowing Machine", template_id="t3", superset_id=0),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    # Every member's superset_group holds the other two, sorted, no loss.
    assert by_canon["standing_calf_raise"]["superset_group"] == [
        "farmers_walk", "rowing_machine",
    ]
    assert by_canon["farmers_walk"]["superset_group"] == [
        "rowing_machine", "standing_calf_raise",
    ]
    assert by_canon["rowing_machine"]["superset_group"] == [
        "farmers_walk", "standing_calf_raise",
    ]
    # superset_with stays a single canonical (backward compat) = sorted[0].
    assert by_canon["standing_calf_raise"]["superset_with"] == "farmers_walk"


def test_superset_mixed_grouped_and_ungrouped_in_one_workout():
    """A single workout mixes a grouped pair (id 0), a lone grouped exercise's
    absence, and ungrouped exercises. Only the grouped pair gets pairing."""
    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _ex(title="Push Up", template_id="t1", superset_id=0),
        _ex(title="Farmers Walk", template_id="t2", superset_id=0),
        _ex(title="Bench Press", template_id="t3", superset_id=None),
        _ex(title="Squat", template_id="t4", superset_id=None),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    assert by_canon["push_up"]["superset_with"] == "farmers_walk"
    assert by_canon["farmers_walk"]["superset_with"] == "push_up"
    assert "superset_with" not in by_canon["bench_press"]
    assert "superset_group" not in by_canon["bench_press"]
    assert "superset_with" not in by_canon["back_squat"]


def test_superset_legacy_supersets_id_fallback():
    """If Hevy ever conforms its API to its (wrong) spec and emits the plural
    ``supersets_id`` instead of ``superset_id``, the resolver must still pair
    via the fallback key. Group id 0 here also guards the truthiness bug."""
    def _legacy_ex(title, template_id, supersets_id):
        ex = _ex(title=title, template_id=template_id, superset_id=None)
        del ex["superset_id"]
        ex["supersets_id"] = supersets_id
        return ex

    rows = hc.workout_to_exercise_rows(_workout(exercises=[
        _legacy_ex("Push Up", "t1", 0),
        _legacy_ex("Farmers Walk", "t2", 0),
    ]))
    by_canon = {r["canonical"]: r for r in rows}
    assert by_canon["push_up"]["superset_with"] == "farmers_walk"
    assert by_canon["farmers_walk"]["superset_with"] == "push_up"
    assert by_canon["push_up"]["superset_group"] == ["farmers_walk"]


def test_superset_prefers_singular_over_legacy_plural():
    """When BOTH keys are present, the real live key (``superset_id``) wins."""
    ex_a = _ex(title="Push Up", template_id="t1", superset_id=0)
    ex_a["supersets_id"] = 99  # stale spec key must be ignored
    ex_b = _ex(title="Farmers Walk", template_id="t2", superset_id=0)
    ex_b["supersets_id"] = 88
    rows = hc.workout_to_exercise_rows(_workout(exercises=[ex_a, ex_b]))
    by_canon = {r["canonical"]: r for r in rows}
    # Both share superset_id 0, so they pair despite differing plural values.
    assert by_canon["push_up"]["superset_with"] == "farmers_walk"
    assert by_canon["farmers_walk"]["superset_with"] == "push_up"


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
    assert result.complete is True
    assert [w["id"] for w in result.updated] == ["w1", "w3"]
    assert result.deleted == ["w2"]


def test_fetch_workout_events_reports_error_as_incomplete():
    http = _fake_http([(None, 503)])
    result = hc.fetch_workout_events("k", since="2026-06-01T00:00:00Z", http_get=http)
    assert result.updated == []
    assert result.deleted == []
    assert result.complete is False
    assert result.status == "vendor_error"


def test_fetch_workout_events_accepts_verified_empty_workouts_alias(caplog):
    """Hevy currently emits ``workouts: []`` for an empty events page."""
    body = {"page": 1, "page_count": 1, "workouts": []}

    with caplog.at_level("INFO"):
        result = hc.fetch_workout_events(
            "k",
            since="2026-06-01T00:00:00Z",
            http_get=_fake_http([(body, 200)]),
        )

    assert result.complete is True
    assert result.status == "empty"
    assert result.pages_read == 1
    assert result.updated == []
    assert result.deleted == []
    assert "accepted verified empty compatibility envelope" in caplog.text
    assert "expected=events actual=workouts" in caplog.text


def test_fetch_workout_events_rejects_unverified_zero_page_workouts_alias():
    body = {"page": 1, "page_count": 0, "workouts": []}

    result = hc.fetch_workout_events(
        "k",
        since="2026-06-01T00:00:00Z",
        http_get=_fake_http([(body, 200)]),
    )

    assert result.complete is False
    assert result.status == "malformed"
    assert result.pages_read == 0
    assert result.error == "response missing events list"


def test_fetch_workout_events_rejects_nonempty_workouts_alias(caplog):
    """Only the verified empty alias is compatible with the event feed."""
    body = {
        "page": 1,
        "page_count": 1,
        "workouts": [_workout("unexpected-workout")],
    }

    with caplog.at_level("WARNING"):
        result = hc.fetch_workout_events(
            "k",
            since="2026-06-01T00:00:00Z",
            http_get=_fake_http([(body, 200)]),
        )

    assert result.complete is False
    assert result.status == "malformed"
    assert result.pages_read == 0
    assert result.updated == []
    assert result.deleted == []
    assert result.error == "response missing events list"
    assert "rejected compatibility envelope" in caplog.text


def test_fetch_workout_events_isolates_unmappable_updated_workout():
    bad = _workout("bad-workout")
    bad["start_time"] = "not-a-timestamp"
    body = {"page": 1, "page_count": 1, "events": [
        {"type": "updated", "workout": _workout("good-workout")},
        {"type": "updated", "workout": bad},
    ]}

    result = hc.fetch_workout_events(
        "k", since="2026-06-01T00:00:00Z", http_get=_fake_http([(body, 200)])
    )

    assert result.complete is True
    assert result.status == "records_degraded"
    assert [workout["id"] for workout in result.updated] == ["good-workout"]
    assert result.record_issues == ({
        "record_id": "bad-workout",
        "event_type": "updated",
        "reason": "start_time cannot derive an analysis date",
    },)


def test_unknown_event_is_reported_and_does_not_block_known_events(caplog):
    body = {"page": 1, "page_count": 1, "events": [
        {"type": "updated", "workout": _workout("good-workout")},
        {"type": "deleted", "id": "deleted-workout"},
        {"type": "archived", "id": "future-event"},
    ]}

    result = hc.fetch_workout_events(
        "k", since="2026-06-01T00:00:00Z", http_get=_fake_http([(body, 200)])
    )

    assert result.complete is True
    assert result.status == "ok_with_ignored_events"
    assert [workout["id"] for workout in result.updated] == ["good-workout"]
    assert result.deleted == ["deleted-workout"]
    assert result.record_issues == ()
    assert result.ignored_events == ({
        "record_id": "future-event",
        "event_type": "archived",
        "reason": "unsupported event type",
    },)
    assert "id=future-event type=archived" in caplog.text


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
