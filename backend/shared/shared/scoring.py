"""
Scoring algorithms for recovery, strain, sleep, and training targets.

Design philosophy — assembled from peer-reviewed + vendor-published components:

  • Strain (per-workout):  Edwards zone-weighted TRIMP (Edwards, 1993) —
    TRIMP = Σ minutes_in_zone × zone_weight, zones 1–5, weights 1–5.
  • Daily strain scale:    min(21, A · ln(TRIMP + 1)). The 0–21 logarithmic
    shape emulates Whoop's daily strain (proprietary coefficient; we tune A
    empirically). Form of log-law matches Banister's TRIMP family.
  • Recovery components:   HRV / RHR deviation from rolling baseline
    (Altini HRV4Training methodology, Kiviniemi 2007), sleep score, respiratory
    rate, SpO2, wrist temperature — each scored 0–100 vs individual baseline,
    then combined with weights loaded from user-config (hot-swappable).
  • ACWR:                  Gabbett 2016 acute:chronic workload ratio (7-day
    sum / 28-day mean) for injury-risk band.
  • Baselines:             14-day rolling (Oura convention; Altini research).

Default composite weights (starting point; tunable via fitness-user-config row
key="scoring" / recovery_weights):

    HRV          0.40   anchor: Oura 0.30; Shaffer & Ginsberg 2017
    RHR          0.25   anchor: Oura 0.20; Whoop publicly #2 signal
    Sleep        0.20   anchor: Oura 0.20
    Respiratory  0.05   anchor: Whoop publicly "small"; clinical range 12–20
    SpO2         0.05   anchor: Whoop illness detection; clinical ≥95%
    Wrist temp   0.05   anchor: Whoop cycle + illness; ≥0.5°C deviation

When a signal is unavailable, its weight is redistributed proportionally
across the remaining signals (so a missing metric doesn't null out recovery).
"""

import math
from typing import Optional

MATEO_AGE = 34
MAX_HR = 220 - MATEO_AGE  # 186 bpm

# HR zone boundaries as fraction of max HR (Karvonen + Edwards 5-zone model)
HR_ZONES = {
    1: (0.00, 0.60),
    2: (0.60, 0.70),
    3: (0.70, 0.80),
    4: (0.80, 0.90),
    5: (0.90, 1.00),
}

ZONE_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}  # Edwards 1993

DEFAULT_BASELINES = {
    "hrv": 48.0,
    "rhr": 64.0,
    "resp": 14.5,
    "sleep_min": 450,
    "steps": 10000,
    "spo2": 96.5,
    "wrist_temp": 32.5,
}

DEFAULT_WEIGHTS = {
    "hrv": 0.40,
    "rhr": 0.25,
    "sleep": 0.20,
    "resp": 0.05,
    "spo2": 0.05,
    "wrist_temp": 0.05,
}

DEFAULT_STRAIN_COEFFICIENT = 2.0
DEFAULT_BASELINE_WINDOW_DAYS = 14


def _clamp(lo: float, hi: float, val: float) -> float:
    return max(lo, min(hi, val))


# ─── Per-signal scoring functions ─────────────────────────────────────
# Each returns 0-100 (higher = better recovery contribution), or None if
# the input is missing so the caller can redistribute weights.


def _hrv_score(hrv: Optional[float], baseline: float) -> Optional[float]:
    """HRV vs baseline. Altini methodology: individual baseline deviation,
    not absolute thresholds. Higher HRV = more parasympathetic tone = better.

    Curve (piecewise linear, calibrated so:
      baseline deviations of ±10% matter more than +15% elevations).

      > +15%    → 80–100   (well above baseline)
      +5…+15%   → 55–80    (mild positive)
      ±5%       → 40–55    (neutral)
      −5…−15%   → 15–40    (yellow)
      < −15%    → 0–15     (deep red)
    """
    if hrv is None:
        return None
    pct = (hrv - baseline) / baseline
    if pct > 0.15:
        return _clamp(0, 100, 80 + (pct - 0.15) * 100)
    if pct > 0.05:
        return _clamp(0, 100, 55 + (pct - 0.05) * 250)
    if pct > -0.05:
        return _clamp(0, 100, 40 + (pct + 0.05) * 150)
    if pct > -0.15:
        return _clamp(0, 100, 15 + (pct + 0.15) * 250)
    return _clamp(0, 100, (pct + 0.30) * 100)


def _rhr_score(rhr: Optional[float], baseline: float) -> Optional[float]:
    """Resting heart rate vs baseline. Lower = better autonomic recovery.

    Whoop-calibrated piecewise curve (derived from Mateo's calibration run
    Apr 25: RHR 70 vs baseline 64, +9.4%, should yield ~11 to match
    Whoop-proxy recovery 38%).

      < −5%     → 85–100 (excellent)
      0…−5%     → 60–85  (good)
      0…+3%     → 40–55  (neutral)
      +3…+6%    → 20–35  (elevated / caution)
      +6…+10%   → 4–20   (high stress / fatigue)
      > +10%    → 0–5    (illness / severe)
    """
    if rhr is None:
        return None
    pct = (rhr - baseline) / baseline
    if pct < -0.05:
        return _clamp(0, 100, 85 + abs(pct + 0.05) * 400)
    if pct < 0.00:
        return _clamp(0, 100, 60 + abs(pct) * 500)
    if pct < 0.03:
        return _clamp(0, 100, 55 - pct * 500)
    if pct < 0.06:
        return _clamp(0, 100, 35 - (pct - 0.03) * 500)
    if pct < 0.10:
        return _clamp(0, 100, 20 - (pct - 0.06) * 400)
    return _clamp(0, 100, 5 - (pct - 0.10) * 100)


def _sleep_component(sleep_min: Optional[float], efficiency: Optional[float]) -> Optional[float]:
    """Simplified sleep contribution used inside compute_recovery.
    Full sleep score (stages, etc) lives in compute_sleep_score."""
    if sleep_min is None or sleep_min <= 0:
        return None
    # Duration: 6h = 0, 8h = 100
    dur_score = _clamp(0, 100, ((sleep_min - 360) / 120) * 100)
    # Efficiency: 80% = 0, 95% = 100
    if efficiency is None or efficiency <= 0:
        return dur_score
    eff_score = _clamp(0, 100, ((efficiency - 80) / 15) * 100)
    return 0.6 * dur_score + 0.4 * eff_score


def _resp_score(resp: Optional[float], baseline: float = 14.5) -> Optional[float]:
    """Respiratory rate vs baseline. Gaussian — continuous, not piecewise.
    Center = baseline, std-dev 2 br/min. Clinical normal range 12–20."""
    if resp is None:
        return None
    # σ=3 br/min: at ±3 from baseline, score drops to ~60;
    # at ±6 drops to ~14. Avoids over-penalizing mild elevations.
    return round(100 * math.exp(-0.5 * ((resp - baseline) / 3.0) ** 2), 1)


def _spo2_score(spo2: Optional[float], baseline: float = 96.5) -> Optional[float]:
    """Blood oxygen. Clinical normal ≥95%, critical < 90%.
    Linear 90 → 0, 96 → 100, saturates above baseline."""
    if spo2 is None:
        return None
    return _clamp(0, 100, (spo2 - 90) / 6 * 100)


def _wrist_temp_score(temp: Optional[float], baseline: float = 32.5) -> Optional[float]:
    """Wrist/skin temperature vs baseline. Elevated = illness/inflammation.
    Gaussian centered on baseline with std-dev 0.6°C.
    (Whoop uses this for women's cycle tracking + general illness detection.)"""
    if temp is None:
        return None
    delta = abs(temp - baseline)
    return round(100 * math.exp(-0.5 * (delta / 0.6) ** 2), 1)


# ─── Recovery composite ────────────────────────────────────────────────


def compute_recovery(
    hrv: Optional[float] = None,
    rhr: Optional[float] = None,
    sleep_min: Optional[float] = None,
    sleep_efficiency: Optional[float] = None,
    resp: Optional[float] = None,
    spo2: Optional[float] = None,
    wrist_temp: Optional[float] = None,
    baselines: Optional[dict] = None,
    weights: Optional[dict] = None,
) -> dict:
    """Composite recovery score 0-100.

    Missing signals have their weight redistributed proportionally across
    the signals that DID report. This matches the module docstring and
    Oura/Whoop convention: a day without SpO2 isn't penalized, it's just
    scored from the remaining signals.

    Exception: if ONLY HRV is present (Day 1 of onboarding, no baselines),
    HRV becomes the full score with weight 1.0.
    """
    b = {**DEFAULT_BASELINES, **(baselines or {})}
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    components = {
        "hrv":       _hrv_score(hrv, b["hrv"]),
        "rhr":       _rhr_score(rhr, b["rhr"]),
        "sleep":     _sleep_component(sleep_min, sleep_efficiency or 0),
        "resp":      _resp_score(resp, b.get("resp", 14.5)),
        "spo2":      _spo2_score(spo2, b.get("spo2", 96.5)),
        "wrist_temp": _wrist_temp_score(wrist_temp, b.get("wrist_temp", 32.5)),
    }

    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return {"score": 0, "zone": "red", "components": components, "weights_used": {}}

    # Onboarding safety: if only HRV is available, don't force it through
    # the weight-redistribution path — just use it directly.
    if list(present.keys()) == ["hrv"]:
        score_val = components["hrv"]
        weights_used = {"hrv": 1.0}
    else:
        # Redistribute missing signals' weight proportionally across the
        # signals that reported. A day with only HRV+RHR+sleep is scored
        # from those three at their full relative weights — not dragged
        # toward 50 by missing SpO2/wrist_temp.
        w_present = {k: w.get(k, 0) for k in present}
        total_w = sum(w_present.values())
        if total_w <= 0:
            return {"score": 0, "zone": "red", "components": components, "weights_used": {}}
        score_val = sum((w_present[k] / total_w) * present[k] for k in present)
        weights_used = {k: round(w_present[k] / total_w, 3) for k in present}

    # "Weakest-link" penalty: if any core signal (HRV/RHR/sleep) is deep red (<20),
    # cap the composite to prevent one strong signal from whitewashing a red signal.
    # Emulates Whoop's behavior where elevated RHR alone keeps you yellow/red even
    # with good HRV. Clinically: a single strong red flag (e.g. RHR surge) shouldn't
    # be averaged away.
    core_signals = [components[k] for k in ("hrv", "rhr", "sleep") if components[k] is not None]
    if core_signals:
        weakest = min(core_signals)
        if weakest < 20:
            # Hard cap: one deep-red signal caps composite at (35 + weakest).
            # Calibrated against Apr 25 (RHR 6.5 → cap 41.5 ≈ Whoop-proxy 38).
            score_val = min(score_val, 35 + weakest)
        elif weakest < 35:
            score_val = min(score_val, 50 + weakest)

    score = int(round(_clamp(0, 100, score_val)))

    if score >= 67:
        zone = "green"
    elif score >= 34:
        zone = "yellow"
    else:
        zone = "red"

    return {
        "score": score,
        "zone": zone,
        "components": {k: (round(v, 1) if v is not None else None) for k, v in components.items()},
        "weights_used": weights_used,
    }


# ─── Strain ────────────────────────────────────────────────────────────


def classify_hr_zone(bpm: float) -> int:
    """Classify a HR sample into zone 1-5 (Karvonen 5-zone model).
    Uses max HR = 220 - age (Mateo 186 bpm)."""
    frac = bpm / MAX_HR
    for zone, (lo, hi) in HR_ZONES.items():
        if frac < hi:
            return zone
    return 5


def compute_trimp(hr_stream: list, sample_interval_sec: float = 1.0) -> dict:
    """Edwards (1993) zone-weighted TRIMP.

    TRIMP = Σ (minutes_in_zone × zone_weight)
    zone_weight: z1=1, z2=2, z3=3, z4=4, z5=5

    Returns: {trimp: float, zone_minutes: dict[str, float]}"""
    zone_seconds = {z: 0.0 for z in range(1, 6)}
    for bpm in hr_stream:
        z = classify_hr_zone(bpm)
        zone_seconds[z] += sample_interval_sec
    zone_minutes = {z: s / 60.0 for z, s in zone_seconds.items()}
    trimp = sum(zone_minutes[z] * ZONE_WEIGHTS[z] for z in range(1, 6))
    return {
        "trimp": round(trimp, 1),
        "zone_minutes": {f"z{z}": round(m, 1) for z, m in zone_minutes.items()},
    }


def compute_strain(trimp: float, coefficient: float = DEFAULT_STRAIN_COEFFICIENT) -> float:
    """Per-workout strain 0-21 (Whoop-style logarithmic scale).
    strain = min(21, A · ln(TRIMP + 1))   where A is empirically tuned (default 2.0)."""
    if trimp <= 0:
        return 0.0
    return round(min(21.0, coefficient * math.log(trimp + 1)), 1)


def estimate_strain_simple(
    exercise_minutes: float,
    active_calories: float = 0,
    avg_hr: Optional[float] = None,
    max_hr_observed: Optional[float] = None,
    est_max_hr: float = MAX_HR,
) -> float:
    """Fallback strain estimate when second-by-second HR is unavailable.

    Combines four signals so the result is more defensible than a flat
    zone-assumption:
      • intensity = avg_hr / max_hr  (how hard relative to capacity)
      • duration  = 1 − exp(−minutes/60)  (diminishing returns over time)
      • peak      = bonus if observed max HR reached Z4/Z5
      • calories  = cross-check via active_cal / 800

    Usage: Strava workouts without HR streams, Apple Health workouts with
    only summary stats, manual entries.
    """
    if exercise_minutes <= 0 or not avg_hr:
        return 0.0

    intensity = avg_hr / est_max_hr
    duration_factor = 1 - math.exp(-exercise_minutes / 60)

    peak_factor = 1.0
    if max_hr_observed:
        if max_hr_observed > est_max_hr * 0.9:
            peak_factor = 1.15
        elif max_hr_observed > est_max_hr * 0.8:
            peak_factor = 1.08

    cal_factor = min(1.0, active_calories / 800) if active_calories else 0.5
    strain = 21 * intensity * duration_factor * peak_factor * (0.7 + 0.3 * cal_factor)
    return round(min(21.0, strain), 1)


def compute_daily_strain(
    workout_trimps: list,
    coefficient: float = DEFAULT_STRAIN_COEFFICIENT,
) -> float:
    """Aggregate daily strain from all workout TRIMPs for the day.

    Whoop shows a single 0-21 daily strain number that cumulates across
    all activity in the day. We emulate by summing TRIMP across workouts
    and applying the same log curve.

    If Mateo has 4 workouts of TRIMP 50 each = 200 total → strain ~10.6
    (matching Whoop-proxy target ~10.2 for Apr 25)."""
    if not workout_trimps:
        return 0.0
    total_trimp = sum(max(0.0, float(t)) for t in workout_trimps)
    return compute_strain(total_trimp, coefficient=coefficient)


# ─── Sleep score ───────────────────────────────────────────────────────


def compute_sleep_score(
    total_min: float,
    efficiency: float,
    deep_min: float,
    rem_min: float,
    duration_target_min: int = 450,
    efficiency_floor: float = 80.0,
    efficiency_ceiling: float = 95.0,
) -> int:
    """Standalone sleep performance score 0-100.
    Weights mirror Oura's published breakdown (35/25/20/20).

      Duration:    0 at (target - 2h), 100 at target (default 7.5h)
      Efficiency:  0 at 80%, 100 at 95%
      Deep:        target 60 min
      REM:         target 90 min

    Default target 450 min matches DEFAULT_BASELINES.sleep_min and
    compute_sleep_need.base_min — all three agree on 7.5h for Mateo.
    """
    dur = _clamp(0, 100, ((total_min - (duration_target_min - 120)) / 120) * 100)
    eff_range = max(1e-6, efficiency_ceiling - efficiency_floor)
    eff = _clamp(0, 100, ((efficiency - efficiency_floor) / eff_range) * 100)
    deep = _clamp(0, 100, (deep_min / 60) * 100)
    rem = _clamp(0, 100, (rem_min / 90) * 100)
    return int(round(0.35 * dur + 0.25 * eff + 0.20 * deep + 0.20 * rem))


# ─── ACWR (Gabbett 2016 acute:chronic workload ratio) ─────────────────


def compute_acwr(daily_trimps: dict) -> Optional[dict]:
    """Injury-risk ratio from Gabbett et al. 2016 (Br J Sports Med).

    acute   = sum(TRIMP over last 7 days)
    chronic = mean(daily TRIMP totals over 28 days)
    acwr    = acute / chronic

    Zones (from Gabbett):
      0.8 – 1.3  sweet spot (green)
      < 0.8      detraining (yellow)
      1.3 – 1.5  overload (yellow)
      > 1.5      injury risk spike (red)

    Input: dict mapping date_str → total TRIMP for that date (last 28+ days)
    Returns None if insufficient data (< 14 days of chronic window)."""
    if not daily_trimps:
        return None
    sorted_dates = sorted(daily_trimps.keys(), reverse=True)[:28]
    if len(sorted_dates) < 14:
        return None

    last_28 = [daily_trimps.get(d, 0.0) for d in sorted_dates]
    last_7 = last_28[:7]
    acute = sum(last_7)
    chronic = sum(last_28) / len(last_28)
    if chronic <= 0:
        return None
    ratio = acute / (chronic * 7)  # normalize: acute sum vs chronic daily-avg × 7
    if ratio < 0.8:
        zone = "yellow"
        interpretation = "Detraining — below maintenance"
    elif ratio <= 1.3:
        zone = "green"
        interpretation = "Sweet spot — sustainable load"
    elif ratio <= 1.5:
        zone = "yellow"
        interpretation = "Overload — dial back or cross-train"
    else:
        zone = "red"
        interpretation = "Injury risk — reduce volume 48h"
    return {
        "ratio": round(ratio, 2),
        "acute": round(acute, 1),
        "chronic": round(chronic, 1),
        "zone": zone,
        "interpretation": interpretation,
    }


# ─── Strain target + sleep need (recovery-adjusted coaching) ──────────


def compute_strain_target(recovery_score: int) -> dict:
    """Whoop-style recovery-adjusted strain target band."""
    if recovery_score >= 67:
        return {"low": 14, "high": 17, "optimal": 15.5, "reason": "Recovered — train hard"}
    if recovery_score >= 34:
        return {"low": 8, "high": 12, "optimal": 10.0, "reason": "Moderate — train smart"}
    return {"low": 0, "high": 6, "optimal": 3.0, "reason": "Depleted — active recovery"}


_SLEEP_BASE_FLOOR_MIN = 360   # 6h — don't let baseline slide below this
_SLEEP_BASE_CEIL_MIN = 540    # 9h — cap baseline so illness weeks don't corrupt it
_SLEEP_BASE_FALLBACK_MIN = 420  # 7h — when we don't have enough history
_MIN_BASELINE_NIGHTS = 7
_ACUTE_DEBT_WINDOW = 2        # look back 2 nights for acute debt
_ACUTE_DEBT_CAP_MIN = 60      # max 1h of recovery sleep added for acute debt
_DEFAULT_WAKE_HOUR = 6.5      # 6:30 AM fallback


def compute_sleep_need(
    sleep_last_30: Optional[list] = None,
    sleep_last_7: Optional[list] = None,
    wake_hours_last_7: Optional[list] = None,
    today_strain: float = 0.0,
    base_min: Optional[int] = None,
) -> dict:
    """Tonight's sleep need, grounded in the user's personal pattern.

    Inputs:
      sleep_last_30  — list of nightly totals (min) from the last 30 nights
                       where data exists. Used to derive the baseline via
                       median, so the algorithm adapts to the user's actual
                       sleep pattern rather than assuming a 7.5h norm.
      sleep_last_7   — last 7 nights (most-recent first). Last 2 are used
                       for acute debt — the only kind of debt a single
                       recovery night can address (Banks & Dinges 2007;
                       Van Dongen 2003).
      wake_hours_last_7 — decimal hours (e.g. 6.5 = 6:30 AM) for when the
                          user actually woke up each of the last 7 nights.
                          Median is used as the wake-time anchor.
      today_strain   — 0-21 daily strain; adds ~1.5 min per strain point
                       (Tanaka & Watanabe 2002).
      base_min       — optional explicit override (testing).

    Returns dict with baseMin, debtMin, strainMin, totalMin, bedtimeBy,
    plus baselineSource ("personal" | "fallback") so callers/UI can
    explain the number.
    """
    if base_min is not None:
        baseline_src = "explicit"
        base = max(_SLEEP_BASE_FLOOR_MIN, min(_SLEEP_BASE_CEIL_MIN, int(base_min)))
    else:
        base, baseline_src = _derive_sleep_baseline(sleep_last_30)

    debt_min = _acute_sleep_debt(sleep_last_7, base)
    strain_min = round(max(0.0, today_strain) * 1.5)
    total_min = base + debt_min + strain_min

    wake_hour = _infer_wake_hour(wake_hours_last_7)
    bedtime_str = _fmt_bedtime(wake_hour, total_min)

    return {
        "baseMin": base,
        "baselineSource": baseline_src,
        "debtMin": debt_min,
        "strainMin": strain_min,
        "totalMin": total_min,
        "bedtimeBy": bedtime_str,
        "wakeHour": round(wake_hour, 2),
    }


def _derive_sleep_baseline(sleep_last_30: Optional[list]) -> tuple[int, str]:
    """Median of last 30 nights with data, clamped to [floor, ceil].

    Returns (base_min, source) where source is 'personal' if we had
    enough nights or 'fallback' if we used the default.
    """
    vals = [int(v) for v in (sleep_last_30 or []) if isinstance(v, (int, float)) and v > 0]
    if len(vals) < _MIN_BASELINE_NIGHTS:
        return _SLEEP_BASE_FALLBACK_MIN, "fallback"

    vals.sort()
    n = len(vals)
    median = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) // 2
    base = max(_SLEEP_BASE_FLOOR_MIN, min(_SLEEP_BASE_CEIL_MIN, int(median)))
    return base, "personal"


def _acute_sleep_debt(sleep_last_7: Optional[list], base_min: int) -> int:
    """Sum of deficits vs baseline over the last 2 nights, capped at 60 min.

    Chronic debt (weeks of under-sleeping) cannot be repaid in one night
    (Banks & Dinges 2007), so we deliberately ignore anything older.
    """
    if not sleep_last_7:
        return 0
    recent = [v for v in sleep_last_7[:_ACUTE_DEBT_WINDOW] if isinstance(v, (int, float)) and v > 0]
    if not recent:
        return 0
    raw = sum(max(0, base_min - int(v)) for v in recent)
    return int(min(_ACUTE_DEBT_CAP_MIN, raw))


def _infer_wake_hour(wake_hours_last_7: Optional[list]) -> float:
    """Median wake hour from recent data, fall back to 6:30 AM."""
    vals = [float(v) for v in (wake_hours_last_7 or []) if isinstance(v, (int, float)) and 0 <= v < 24]
    if not vals:
        return _DEFAULT_WAKE_HOUR
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _fmt_bedtime(wake_hour: float, total_min: int) -> str:
    bedtime_hour = wake_hour - (total_min / 60)
    if bedtime_hour < 0:
        bedtime_hour += 24
    h = int(bedtime_hour)
    m = int(round((bedtime_hour - h) * 60))
    if m == 60:
        h = (h + 1) % 24
        m = 0
    suffix = "a" if h < 12 else "p"
    display_h = 12 if h == 0 else (h - 12 if h > 12 else h)
    return f"{display_h}:{m:02d}{suffix}"
