"""Sleep data quality flagging + segment-derived metrics.

Two jobs:
  1. Decide whether a sleep record is trustworthy enough to feed into the
     recovery composite. Output: quality_flag + reasons + confidence 0-1.
  2. When we have per-segment data from unaggregated HAE, derive the extra
     signals Bevel/Whoop expose: arousal count, sleep-onset latency,
     continuity index.

Keeps ingest-time parsing (no I/O) in `evaluate_quality` and the
segment math in `*_from_segments` so compute can call them on either
freshly-ingested or historic rows.

Vocabulary:
  - "segment" = one HAE stage record {start, end, stage, dur_min}
  - "stage" ∈ {deep, rem, core, awake, in_bed, asleep}
  - "arousal" = a transition into awake from an asleep stage, longer than
    the snore-threshold. We don't count 30-second stirs.
"""

from datetime import datetime
from typing import Optional

# Tunable thresholds. Parked here (not in user_config) since these are
# detection plumbing, not score weights — the user wouldn't hot-swap them.
TRUNCATION_FLOOR_MIN = 240          # <4h total + no wrist-temp → truncated
STAGES_SUM_TOLERANCE_MIN = 30       # stages ± 30m of in-bed is "sums OK"
PARTIAL_MIN_SEGMENTS_SPAN_MIN = 180 # segments spanning <3h on the clock = partial
AROUSAL_MIN_DURATION_MIN = 2.0      # awake < 2min is noise, not arousal
PLAUSIBLE_EFFICIENCY_MAX = 100.5    # rounding slack; >100.5 means math is off
ONSET_SEARCH_WINDOW_MIN = 120       # look at most 2h past first "in bed" for sleep onset


def _parse_ts(s) -> Optional[datetime]:
    """HAE timestamps come as strings like '2026-05-03 23:45:10 -0700'.
    We don't care about tz conversion — all we need is ordering + deltas,
    both of which are preserved by parsing the naive local form."""
    if not s or not isinstance(s, str):
        return None
    try:
        core = s[:19]  # drop tz suffix; keep YYYY-MM-DD HH:MM:SS
        return datetime.strptime(core, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None


def _normalize_stage(val: str) -> str:
    v = (val or "").lower().replace(" ", "").replace("_", "")
    if "deep" in v:
        return "deep"
    if "rem" in v:
        return "rem"
    if "core" in v or "light" in v:
        return "core"
    if "awake" in v:
        return "awake"
    if "inbed" in v:
        return "in_bed"
    if "asleep" in v:
        return "asleep"
    return "unknown"


def evaluate_quality(row: dict, has_wrist_temp_today: bool = True) -> dict:
    """Inspect a freshly-built sleep row and return quality metadata.

    Args:
      row: the partially-built sleep#hae row — must contain total_min,
           in_bed_min, deep_min, rem_min, core_min, awake_min, efficiency.
           May contain segments[] for tighter checks.
      has_wrist_temp_today: whether a wrist_temp#hae sample exists for
           the same date. Used as a secondary "watch was on wrist"
           signal when judging very short nights.

    Returns:
      {quality_flag, quality_reasons, confidence}
    """
    total = float(row.get("total_min") or 0)
    in_bed = float(row.get("in_bed_min") or 0)
    deep = float(row.get("deep_min") or 0)
    rem = float(row.get("rem_min") or 0)
    core = float(row.get("core_min") or 0)
    awake = float(row.get("awake_min") or 0)
    eff = float(row.get("efficiency") or 0)
    segments = row.get("segments") or []

    reasons = []

    if total <= 0 and not segments:
        return {"quality_flag": "missing", "quality_reasons": ["no_sleep_data"], "confidence": 0.0}

    # Truncation signal: very short total AND we can't confirm the watch
    # was on the wrist (no temperature sample). A genuine 3am bedtime
    # still produces wrist-temp samples.
    if total > 0 and total < TRUNCATION_FLOOR_MIN and not has_wrist_temp_today:
        reasons.append("below_floor")
        reasons.append("no_wrist_temp")

    # Stage sum sanity — if stages don't add up to in-bed within tolerance,
    # HAE likely reported a partial window.
    stages_sum = deep + rem + core + awake
    if in_bed > 0 and stages_sum > 0 and abs(stages_sum - in_bed) > STAGES_SUM_TOLERANCE_MIN:
        reasons.append("stages_dont_sum")

    if eff > PLAUSIBLE_EFFICIENCY_MAX:
        reasons.append("implausible_efficiency")

    # Segment-span check: the window covered by the segments should span
    # at least PARTIAL_MIN_SEGMENTS_SPAN_MIN of wall-clock time. If we have
    # 7h reported in an hour of segments, something's off.
    if segments:
        span = _segments_span_min(segments)
        if span is not None and span < PARTIAL_MIN_SEGMENTS_SPAN_MIN:
            reasons.append("segments_short_span")

    if "below_floor" in reasons and "no_wrist_temp" in reasons:
        return {"quality_flag": "truncated", "quality_reasons": reasons, "confidence": 0.0}
    if reasons:
        return {"quality_flag": "partial", "quality_reasons": reasons, "confidence": 0.5}
    return {"quality_flag": "ok", "quality_reasons": [], "confidence": 1.0}


def _segments_span_min(segments: list) -> Optional[float]:
    earliest = None
    latest = None
    for s in segments:
        start = _parse_ts(s.get("start"))
        end = _parse_ts(s.get("end"))
        if start and (earliest is None or start < earliest):
            earliest = start
        if end and (latest is None or end > latest):
            latest = end
    if earliest is None or latest is None:
        return None
    return (latest - earliest).total_seconds() / 60.0


def arousal_count_from_segments(segments: list) -> int:
    """Count transitions from an asleep stage into awake where the awake
    block is long enough to matter. Matches Whoop's 'disturbances'."""
    if not segments:
        return 0
    count = 0
    prev_stage = None
    for s in sorted(segments, key=lambda x: x.get("start") or ""):
        stage = _normalize_stage(s.get("stage"))
        dur = float(s.get("dur_min") or 0)
        if stage == "awake" and dur >= AROUSAL_MIN_DURATION_MIN and prev_stage in ("deep", "rem", "core", "asleep"):
            count += 1
        if stage in ("deep", "rem", "core", "awake", "asleep"):
            prev_stage = stage
    return count


def onset_min_from_segments(segments: list) -> Optional[float]:
    """Minutes from 'in bed' to first asleep stage. Only meaningful when
    HAE sends an explicit in_bed segment — Apple Watch usually does.
    Falls back to None when there's no in_bed marker."""
    if not segments:
        return None
    sorted_segs = sorted(segments, key=lambda x: x.get("start") or "")
    in_bed_start = None
    for s in sorted_segs:
        stage = _normalize_stage(s.get("stage"))
        if stage == "in_bed":
            in_bed_start = _parse_ts(s.get("start"))
            break
    if in_bed_start is None:
        return None
    for s in sorted_segs:
        stage = _normalize_stage(s.get("stage"))
        if stage in ("deep", "rem", "core", "asleep"):
            sleep_start = _parse_ts(s.get("start"))
            if sleep_start is None:
                continue
            delta = (sleep_start - in_bed_start).total_seconds() / 60.0
            if delta < 0 or delta > ONSET_SEARCH_WINDOW_MIN:
                return None
            return round(delta, 1)
    return None


def continuity_index(arousal_count: int, total_sleep_min: float) -> float:
    """0-100 scalar: fewer arousals per hour = closer to 100.

    Anchors (from Whoop's published disturbance-per-hour bins):
      - 0 arousals/h → 100
      - 1 arousal/h  → 80
      - 2 arousals/h → 60
      - 4+ arousals/h → ≤ 20

    Done as a linear ramp on arousals-per-hour, capped 0-100.
    """
    if total_sleep_min <= 0:
        return 0.0
    per_hour = arousal_count / (total_sleep_min / 60.0)
    score = 100 - (per_hour * 20)
    if score < 0:
        return 0.0
    if score > 100:
        return 100.0
    return round(score, 1)
