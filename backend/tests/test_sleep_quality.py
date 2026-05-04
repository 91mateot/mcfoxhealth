"""Sleep quality flagging + segment-derived metrics.

Exercises:
  - evaluate_quality branches: ok, partial, truncated, missing
  - arousal_count_from_segments (mid-night awake blocks)
  - onset_min_from_segments (in_bed → first asleep)
  - continuity_index ramp
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

from shared.sleep_quality import (  # noqa: E402
    arousal_count_from_segments,
    continuity_index,
    evaluate_quality,
    onset_min_from_segments,
)


def test_quality_ok_for_clean_night():
    row = {
        "total_min": 420, "in_bed_min": 450,
        "deep_min": 90, "rem_min": 100, "core_min": 215, "awake_min": 30,
        "efficiency": 93.3,
    }
    q = evaluate_quality(row, has_wrist_temp_today=True)
    assert q["quality_flag"] == "ok"
    assert q["confidence"] == 1.0


def test_quality_truncated_when_short_and_no_wrist_temp():
    row = {
        "total_min": 173, "in_bed_min": 183,
        "deep_min": 20, "rem_min": 30, "core_min": 123, "awake_min": 10,
        "efficiency": 94.5,
    }
    q = evaluate_quality(row, has_wrist_temp_today=False)
    assert q["quality_flag"] == "truncated"
    assert "below_floor" in q["quality_reasons"]
    assert q["confidence"] == 0.0


def test_quality_partial_short_night_with_wrist_temp_is_not_truncated():
    # Same short night but the watch stayed on the wrist — probably a
    # genuinely short night (3am bedtime), not a truncated HealthKit query.
    row = {
        "total_min": 173, "in_bed_min": 183,
        "deep_min": 20, "rem_min": 30, "core_min": 123, "awake_min": 10,
        "efficiency": 94.5,
    }
    q = evaluate_quality(row, has_wrist_temp_today=True)
    assert q["quality_flag"] == "ok"  # short, but plausible


def test_quality_partial_when_stages_dont_sum():
    row = {
        "total_min": 420, "in_bed_min": 600,  # in-bed 600, stages 385 → off by 215
        "deep_min": 90, "rem_min": 100, "core_min": 150, "awake_min": 45,
        "efficiency": 70.0,
    }
    q = evaluate_quality(row, has_wrist_temp_today=True)
    assert q["quality_flag"] == "partial"
    assert "stages_dont_sum" in q["quality_reasons"]


def test_quality_missing_when_no_sleep_data():
    row = {"total_min": 0, "in_bed_min": 0, "deep_min": 0, "rem_min": 0,
           "core_min": 0, "awake_min": 0, "efficiency": 0}
    q = evaluate_quality(row, has_wrist_temp_today=True)
    assert q["quality_flag"] == "missing"


def test_arousal_count_counts_sleep_to_awake_transitions():
    segments = [
        {"start": "2026-05-03 23:30:00 -0700", "end": "2026-05-03 23:45:00 -0700", "stage": "in_bed", "dur_min": 15},
        {"start": "2026-05-03 23:45:00 -0700", "end": "2026-05-04 00:30:00 -0700", "stage": "core", "dur_min": 45},
        {"start": "2026-05-04 00:30:00 -0700", "end": "2026-05-04 00:35:00 -0700", "stage": "awake", "dur_min": 5},
        {"start": "2026-05-04 00:35:00 -0700", "end": "2026-05-04 02:00:00 -0700", "stage": "deep", "dur_min": 85},
        {"start": "2026-05-04 02:00:00 -0700", "end": "2026-05-04 02:04:00 -0700", "stage": "awake", "dur_min": 4},
        {"start": "2026-05-04 02:04:00 -0700", "end": "2026-05-04 04:00:00 -0700", "stage": "rem", "dur_min": 116},
    ]
    assert arousal_count_from_segments(segments) == 2


def test_arousal_count_ignores_brief_stirs():
    segments = [
        {"start": "2026-05-03 23:30:00 -0700", "end": "2026-05-04 00:30:00 -0700", "stage": "core", "dur_min": 60},
        {"start": "2026-05-04 00:30:00 -0700", "end": "2026-05-04 00:30:45 -0700", "stage": "awake", "dur_min": 0.75},
        {"start": "2026-05-04 00:30:45 -0700", "end": "2026-05-04 02:00:00 -0700", "stage": "deep", "dur_min": 89},
    ]
    assert arousal_count_from_segments(segments) == 0


def test_onset_min_from_in_bed_to_first_asleep():
    segments = [
        {"start": "2026-05-03 23:00:00 -0700", "end": "2026-05-03 23:18:00 -0700", "stage": "in_bed", "dur_min": 18},
        {"start": "2026-05-03 23:18:00 -0700", "end": "2026-05-03 23:48:00 -0700", "stage": "core", "dur_min": 30},
    ]
    assert onset_min_from_segments(segments) == 18.0


def test_onset_min_none_when_no_in_bed_marker():
    segments = [
        {"start": "2026-05-03 23:18:00 -0700", "end": "2026-05-03 23:48:00 -0700", "stage": "core", "dur_min": 30},
    ]
    assert onset_min_from_segments(segments) is None


def test_continuity_index_drops_with_arousals():
    assert continuity_index(0, 420) == 100.0  # zero arousals = perfect
    # 7h sleep with 1 arousal = ~0.14/h → ~97
    idx_1 = continuity_index(1, 420)
    assert 95 <= idx_1 <= 100
    # 7h with 4 arousals = ~0.57/h → ~89
    idx_4 = continuity_index(4, 420)
    assert idx_4 < idx_1
    # Enough arousals to force the score to the 0 floor
    # 36 arousals in 7h = 5.14/h → score hits 0 cap.
    assert continuity_index(36, 420) == 0.0


def test_continuity_index_zero_sleep_returns_zero():
    assert continuity_index(0, 0) == 0.0
