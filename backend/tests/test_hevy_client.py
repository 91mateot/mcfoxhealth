"""
Tests for the Hevy API client (shared/shared/hevy_client.py).

These run fully offline — the HTTP layer is injected via the ``http_get``
argument to fetch_recent_workouts, so no real Hevy API key is required. We
assert on the workout-row mapping, strain estimation, pagination/stop logic,
and graceful degradation on API errors.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

from shared import hevy_client  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────

def _workout(wid="w1", title="Push Day", start="2026-06-30T18:00:00+00:00",
             end="2026-06-30T19:00:00+00:00", exercises=None):
    return {
        "id": wid,
        "title": title,
        "start_time": start,
        "end_time": end,
        "exercises": exercises if exercises is not None else [
            {"title": "Bench Press", "sets": [
                {"weight_kg": 60, "reps": 10},
                {"weight_kg": 60, "reps": 8},
            ]},
            {"title": "Overhead Press", "sets": [
                {"weight_kg": 40, "reps": 10},
            ]},
        ],
    }


def _fake_http(pages):
    """Build an http_get stub returning successive page bodies.

    ``pages`` is a list of (json_body, status) tuples returned in order.
    """
    calls = {"n": 0}

    def _get(url, api_key):
        i = calls["n"]
        calls["n"] += 1
        if i < len(pages):
            return pages[i]
        return {"workouts": []}, 200

    _get.calls = calls
    return _get


# ── Row mapping ─────────────────────────────────────────────────────

def test_workout_to_row_maps_core_fields():
    row = hevy_client.workout_to_row(_workout())
    assert row is not None
    assert row["date"] == "2026-06-30"
    assert row["strava_id"] == "hevy_w1"
    assert row["hevy_id"] == "w1"
    assert row["source"] == "hevy"
    assert row["type"] == hevy_client.HEVY_STRENGTH_TYPE == "Workout"
    assert row["dur"] == 60
    assert row["exercise_count"] == 2
    assert row["set_count"] == 3


def test_workout_to_row_computes_volume_in_lb():
    row = hevy_client.workout_to_row(_workout())
    # (60*10 + 60*8 + 40*10) kg * 2.20462 = 1480 kg → 3262.8 lb
    expected = round((60 * 10 + 60 * 8 + 40 * 10) * hevy_client.KG_TO_LB, 1)
    assert row["volume_lb"] == expected


def test_workout_to_row_estimates_nonzero_strain():
    row = hevy_client.workout_to_row(_workout())
    # 60 min lifting → trimp = 60 * 2.0 = 120 → strain > 0
    assert row["trimp"] == 120.0
    assert row["strain"] > 0
    assert row["strain_estimated"] is True


def test_workout_to_row_zero_duration_zero_strain():
    w = _workout(start="2026-06-30T18:00:00+00:00", end="2026-06-30T18:00:00+00:00")
    row = hevy_client.workout_to_row(w)
    assert row["dur"] == 0
    assert row["trimp"] == 0.0
    assert row["strain"] == 0.0


def test_workout_to_row_rejects_missing_id():
    w = _workout()
    del w["id"]
    assert hevy_client.workout_to_row(w) is None


def test_workout_to_row_rejects_bad_date():
    w = _workout(start="not-a-date")
    assert hevy_client.workout_to_row(w) is None


def test_workout_to_row_handles_z_suffix_timestamp():
    w = _workout(start="2026-07-01T12:00:00Z", end="2026-07-01T13:15:00Z")
    row = hevy_client.workout_to_row(w)
    assert row["date"] == "2026-07-01"
    assert row["dur"] == 75


def test_workout_to_row_tolerates_garbage_sets():
    w = _workout(exercises=[{"title": "X", "sets": [
        {"weight_kg": "bad", "reps": 10},   # non-numeric weight → excluded
        {"weight_kg": 50, "reps": None},    # missing reps → counted, 0 volume
        {"weight_kg": 50, "reps": 5},       # valid
    ]}])
    row = hevy_client.workout_to_row(w)
    # The non-numeric weight is dropped; the missing-reps set counts with 0
    # volume; the valid set contributes its volume. So 2 counted sets, and
    # volume comes only from the valid set.
    assert row["set_count"] == 2
    assert row["volume_lb"] == round(50 * 5 * hevy_client.KG_TO_LB, 1)


# ── fetch_recent_workouts ───────────────────────────────────────────

def test_fetch_requires_api_key():
    try:
        hevy_client.fetch_recent_workouts("")
    except ValueError:
        pass
    else:
        assert False, "expected ValueError for empty api key"


def test_fetch_single_page():
    body = {"page": 1, "page_count": 1, "workouts": [_workout("a"), _workout("b")]}
    rows = hevy_client.fetch_recent_workouts(
        "key", page_size=10, http_get=_fake_http([(body, 200)])
    )
    assert len(rows) == 2
    assert {r["hevy_id"] for r in rows} == {"a", "b"}


def test_fetch_stops_on_page_count():
    p1 = ({"page": 1, "page_count": 2, "workouts": [_workout("a")] * 10}, 200)
    p2 = ({"page": 2, "page_count": 2, "workouts": [_workout("b")]}, 200)
    http = _fake_http([p1, p2])
    rows = hevy_client.fetch_recent_workouts("key", page_size=10, max_pages=5, http_get=http)
    # Should fetch exactly 2 pages then stop (page >= page_count).
    assert http.calls["n"] == 2
    assert len(rows) == 11


def test_fetch_stops_on_short_page():
    # Page returns fewer than page_size → no more pages exist.
    body = {"page": 1, "workouts": [_workout("a")]}  # 1 < page_size
    http = _fake_http([(body, 200)])
    rows = hevy_client.fetch_recent_workouts("key", page_size=10, max_pages=5, http_get=http)
    assert http.calls["n"] == 1
    assert len(rows) == 1


def test_fetch_degrades_on_api_error():
    # Non-200 → log-and-stop, return whatever we had (nothing here).
    http = _fake_http([(None, 401)])
    rows = hevy_client.fetch_recent_workouts("key", http_get=http)
    assert rows == []


def test_fetch_degrades_on_server_error_mid_pagination():
    p1 = ({"page": 1, "page_count": 3, "workouts": [_workout("a")] * 10}, 200)
    p2 = (None, 500)
    http = _fake_http([p1, p2])
    rows = hevy_client.fetch_recent_workouts("key", page_size=10, max_pages=5, http_get=http)
    # Keeps page 1's rows, stops when page 2 fails.
    assert len(rows) == 10
    assert http.calls["n"] == 2


def test_fetch_respects_max_pages():
    full = {"page": 1, "page_count": 99, "workouts": [_workout("a")] * 10}
    http = _fake_http([(full, 200)] * 10)
    rows = hevy_client.fetch_recent_workouts("key", page_size=10, max_pages=2, http_get=http)
    assert http.calls["n"] == 2
    assert len(rows) == 20
