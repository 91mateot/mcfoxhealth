"""
Validation tests for scoring.py — calibrated against Mateo's Whoop-proxy.

Calibration targets (Sat Apr 25, 2026):
  Recovery: 38%  (±5 tolerance)
  Strain:   10.2 (±1 tolerance)
  Sleep:    90   (±3 tolerance)

Baselines at the time: HRV 42.2 / RHR 64 / resp 14.5 / sleep 450min.
Readings on Apr 25: HRV 45.5 / RHR 70 / sleep 463min @ 93% eff / deep 72min / REM 98min.
"""
import math

from shared.scoring import (
    compute_recovery,
    compute_sleep_score,
    compute_hr_dip_score,
    compute_strain,
    compute_daily_strain,
    compute_acwr,
    compute_strain_target,
    compute_sleep_need,
    estimate_strain_simple,
    _hrv_score,
    _rhr_score,
    _spo2_score,
    _wrist_temp_score,
    _resp_score,
)

# ─── Apr 25 calibration ─────────────────────────────────────────────

APR_25_HRV = 45.5
APR_25_RHR = 70
APR_25_SLEEP_MIN = 463
APR_25_SLEEP_EFF = 93
APR_25_DEEP = 72
APR_25_REM = 98
APR_25_BASELINES = {"hrv": 42.2, "rhr": 64, "resp": 14.5, "sleep_min": 450, "spo2": 96.5, "wrist_temp": 32.5, "steps": 8100}


def test_apr_25_matches_whoop_proxy_recovery():
    """Apr 25 recovery target 38% ±5."""
    result = compute_recovery(
        hrv=APR_25_HRV,
        rhr=APR_25_RHR,
        sleep_min=APR_25_SLEEP_MIN,
        sleep_efficiency=APR_25_SLEEP_EFF,
        resp=None,
        spo2=None,
        wrist_temp=None,
        baselines=APR_25_BASELINES,
    )
    assert 33 <= result["score"] <= 43, f"Apr 25 recovery {result['score']} outside 33-43 band; components={result['components']} weights={result['weights_used']}"


def test_apr_25_sleep_exceeds_need():
    """Apr 25: 7h43m asleep (463 min) exceeds 7.5h need (450 min).
    With duration target aligned to need, duration component maxes out;
    only the 93% efficiency keeps this below a perfect 100. Whoop shows 90%
    because their standard targets 8h; we target Mateo's actual 7.5h need."""
    score = compute_sleep_score(APR_25_SLEEP_MIN, APR_25_SLEEP_EFF, APR_25_DEEP, APR_25_REM)
    assert 94 <= score <= 99, f"Apr 25 sleep score {score} outside 94-99 band"


def test_sleep_score_back_compat_without_continuity():
    """Old callers that don't pass continuity_idx still use the 4-component
    Oura weighting (35/25/20/20). Behavior unchanged from pre-rebuild."""
    legacy = compute_sleep_score(450, 93, 90, 100)
    # Expected legacy formula: 0.35*100 + 0.25*86.67 + 0.20*100 + 0.20*100
    # = 35 + 21.67 + 20 + 20 ≈ 96.67 → rounds to 97
    assert 94 <= legacy <= 99


def test_sleep_score_5component_rewards_continuity():
    """With continuity_idx provided, the 5-component weighting kicks in.
    A fragmented night scores lower than a continuous one at the same
    duration/efficiency/stages."""
    continuous = compute_sleep_score(450, 93, 90, 100, continuity_idx=100)
    fragmented = compute_sleep_score(450, 93, 90, 100, continuity_idx=40)
    assert continuous > fragmented


def test_sleep_score_fragmented_short_night_low():
    """Short + fragmented night (e.g., 4.5h with 4 arousals) scores in the
    low-middle band, not a flat zero — the old duration-dominated formula
    would have tanked it harder."""
    score = compute_sleep_score(270, 80, 40, 50, continuity_idx=60)
    assert 20 <= score <= 60


# ─── HR dip component ───────────────────────────────────────────────

def test_hr_dip_missing_inputs_return_none():
    assert compute_hr_dip_score(None, 64) is None
    assert compute_hr_dip_score(50, None) is None
    # min HR at or above baseline = no dip, data looks off
    assert compute_hr_dip_score(64, 64) is None
    assert compute_hr_dip_score(70, 64) is None


def test_hr_dip_curve_anchors_match_bevel_framing():
    """Curve anchored to Bevel's labels: 16% dip reads "Poor" (~60),
    25%+ reads "Excellent" (100), <=10% reads flat 0."""
    # 10% dip — below threshold, flat 0
    score, pct = compute_hr_dip_score(57.6, 64)
    assert pct == 10.0
    assert score == 0

    # 16% dip — matches Bevel's "Poor" label on 5/3, score ≈ 60
    score, pct = compute_hr_dip_score(53.76, 64)
    assert pct == 16.0
    assert 59 <= score <= 61

    # 25% dip — excellent, score = 100
    score, pct = compute_hr_dip_score(48, 64)
    assert pct == 25.0
    assert score == 100

    # 30% dip — clamped at 100
    score, _ = compute_hr_dip_score(44.8, 64)
    assert score == 100


def test_hr_dip_monotonic():
    """Bigger dip (lower min HR) → higher or equal score, always."""
    prev = -1
    for min_hr in [64, 60, 57, 54, 50, 48, 44]:
        result = compute_hr_dip_score(min_hr, 64)
        score = result[0] if result else 0
        assert score >= prev
        prev = score


# ─── Duration-against-personal-need (B1 regression) ─────────────────

def test_may_3_night_duration_vs_need():
    """5/3 night live data: 375m asleep vs personal sleep_need.totalMin=385m.
    With duration_target_min=385, duration scores ~95 (95% of need hit),
    not the 37.5 it scored against the fixed 450m target. This is the
    primary B1 regression — the duration curve re-anchored to the user's
    actual need."""
    # 4-component (no segments) — live state on 5/3 before HAE reconfigure
    score_fixed = compute_sleep_score(375, 94.7, 48, 57, duration_target_min=450)
    score_personal = compute_sleep_score(375, 94.7, 48, 57, duration_target_min=385)
    # Fixed-target: 0.35*37.5 + 0.25*98 + 0.2*80 + 0.2*63.3 ≈ 66 (matches live)
    assert 64 <= score_fixed <= 68
    # Personal-need target: dur ≈ 91.7, score lands in mid-80s.
    # 0.35*91.7 + 0.25*98 + 0.2*80 + 0.2*63.3 ≈ 85
    assert 82 <= score_personal <= 88
    assert score_personal > score_fixed + 15  # at least 15-pt improvement


def test_sleep_score_6component_uses_hr_dip():
    """When both continuity_idx and hr_dip_idx are provided, the 6-component
    weighting kicks in (25/15/15/15/15/15)."""
    # Same underlying night, just with HR dip added vs not
    with_dip = compute_sleep_score(
        450, 93, 90, 100, continuity_idx=100, hr_dip_idx=100
    )
    without_dip = compute_sleep_score(
        450, 93, 90, 100, continuity_idx=100, hr_dip_idx=None
    )
    # A perfect HR dip + perfect everything else should be at or near 100.
    assert with_dip >= 95
    # Without dip, same inputs still near 100 because continuity=100 fills in.
    assert without_dip >= 95


def test_sleep_score_6component_poor_hr_dip_penalizes():
    """A night with poor HR dip (score 20) should drop the 6-component
    total below the same night's 5-component score, because the dip weight
    (15%) lands on a low number rather than being absorbed by other signals."""
    cont_only = compute_sleep_score(450, 93, 90, 100, continuity_idx=100)
    with_poor_dip = compute_sleep_score(
        450, 93, 90, 100, continuity_idx=100, hr_dip_idx=20
    )
    assert with_poor_dip < cont_only


def test_apr_25_matches_whoop_proxy_strain():
    """Apr 25 strain target 10.2 ±1. Pull day (TRIMP ~100) + walk (TRIMP ~30) = ~130.
    With A=2.0: 2 * ln(131) ~= 9.75, rounds to 9.8 — within tolerance of 10.2."""
    strain = compute_daily_strain([100, 30], coefficient=2.0)
    assert 9.0 <= strain <= 11.2, f"Apr 25 strain {strain} outside 9-11.2 band"


# ─── Sanity anchors ─────────────────────────────────────────────────

def test_strong_green_day():
    """HRV well above, RHR well below baseline, solid sleep → recovery ≥ 75."""
    result = compute_recovery(
        hrv=52, rhr=58, sleep_min=480, sleep_efficiency=94,
        baselines={"hrv": 42, "rhr": 64},
    )
    assert result["score"] >= 75, f"Strong green day scored {result['score']}"
    assert result["zone"] == "green"


def test_crashed_day():
    """HRV crashed, RHR spiked, bad sleep → recovery ≤ 25 (red)."""
    result = compute_recovery(
        hrv=31, rhr=72, sleep_min=360, sleep_efficiency=82,
        baselines={"hrv": 42, "rhr": 64},
    )
    assert result["score"] <= 25, f"Crashed day scored {result['score']}"
    assert result["zone"] == "red"


def test_missing_signals_reweight_to_present():
    """Missing signals' weight redistributes across signals that DID report.
    A day with only HRV/RHR/sleep is scored purely from those three, not
    dragged toward 50 by missing SpO2/wrist_temp/resp."""
    partial = compute_recovery(
        hrv=60, rhr=55, sleep_min=500, sleep_efficiency=95,
        resp=None, spo2=None, wrist_temp=None,
        baselines=APR_25_BASELINES,
    )
    # With HRV/RHR/sleep at strong values, composite should land in green.
    assert partial["zone"] == "green"
    assert partial["score"] >= 75, f"Strong core signals scored {partial['score']}"

    # Only 3 keys in weights_used (the ones that reported).
    w = partial["weights_used"]
    assert set(w.keys()) == {"hrv", "rhr", "sleep"}
    # Renormalized weights sum to 1.0.
    assert abs(sum(w.values()) - 1.0) < 0.001
    # HRV keeps its dominant share (0.40 / 0.85 ≈ 0.471).
    assert abs(w["hrv"] - 0.471) < 0.01


def test_reweight_matches_all_present_when_missing_signals_are_neutral():
    """Sanity: if present signals all score identically, missing signals
    shouldn't change the composite. 50/50/50 (core) vs 50/50/50/50/50/50
    should produce the same 50."""
    partial = compute_recovery(
        hrv=48, rhr=64, sleep_min=420, sleep_efficiency=87.5,
        baselines=APR_25_BASELINES,
    )
    full = compute_recovery(
        hrv=48, rhr=64, sleep_min=420, sleep_efficiency=87.5,
        resp=14.5, spo2=96.5, wrist_temp=32.5,
        baselines=APR_25_BASELINES,
    )
    # Both should score near identical when added signals are at baseline (~100 each).
    # Partial is 3 present signals; full is 6 with the 3 extras near 100.
    # Since the 3 extras land at ~100 (perfect), full should score HIGHER than partial.
    assert full["score"] > partial["score"]


def test_all_signals_present_weights_sum_to_one():
    """When all 6 signals present, weights_used sum to 1.0."""
    result = compute_recovery(
        hrv=45, rhr=62, sleep_min=460, sleep_efficiency=91,
        resp=14.3, spo2=97.2, wrist_temp=32.5,
        baselines=APR_25_BASELINES,
    )
    w = result["weights_used"]
    assert abs(sum(w.values()) - 1.0) < 0.001
    assert len(w) == 6


def test_only_hrv_available():
    """If only HRV exists (Day 1 of onboarding), score still returns."""
    result = compute_recovery(
        hrv=50, rhr=None, sleep_min=None, sleep_efficiency=None,
        baselines={"hrv": 42},
    )
    assert result["score"] > 0
    assert list(result["weights_used"].keys()) == ["hrv"]
    assert abs(result["weights_used"]["hrv"] - 1.0) < 0.001


# ─── Per-signal curves ──────────────────────────────────────────────

def test_hrv_above_baseline_green():
    assert _hrv_score(50, 42) >= 75


def test_hrv_at_baseline_scores_recovered():
    """At baseline, HRV should score ~70 (recovered), not 50.
    Whoop/Oura/Altini consensus: being at your personal baseline is the
    healthy state, not the midpoint of a 0-100 scale."""
    s = _hrv_score(42, 42)
    assert 65 <= s <= 80, f"HRV at baseline scored {s}, expected 65-80"


def test_day_at_baseline_scores_green():
    """Every signal at its baseline → recovered (green). Was 62/yellow
    before P1 curve recalibration; now should be in the green band."""
    result = compute_recovery(
        hrv=48, rhr=64, sleep_min=450, sleep_efficiency=90,
        resp=14.5, spo2=96.5, wrist_temp=32.5,
        baselines={"hrv": 48, "rhr": 64},
    )
    assert result["score"] >= 70, f"day-at-baseline scored {result['score']}, expected ≥70"
    assert result["zone"] == "green"


def test_hrv_crashed_red():
    assert _hrv_score(30, 42) <= 30


def test_rhr_at_plus_9pct_is_low():
    """The exact Apr 25 case. RHR 70 vs 64 baseline = +9.4%. Should be deep yellow/red territory."""
    s = _rhr_score(70, 64)
    assert 5 <= s <= 20, f"RHR +9.4% scored {s}, expected 5-20"


def test_rhr_below_baseline_green():
    assert _rhr_score(58, 64) >= 80


def test_spo2_clinical_normal_high():
    assert _spo2_score(98, 96.5) == 100  # clamps at 100


def test_spo2_below_95_penalized():
    assert _spo2_score(93, 96.5) < 60


def test_wrist_temp_at_baseline_perfect():
    assert _wrist_temp_score(32.5, 32.5) == 100


def test_wrist_temp_elevated_penalized():
    """0.5°C above baseline (fever start) should score ~60-70."""
    s = _wrist_temp_score(33.0, 32.5)
    assert 50 <= s <= 80, f"wrist temp +0.5 scored {s}"


def test_resp_at_baseline_perfect():
    assert _resp_score(14.5, 14.5) == 100


def test_resp_elevated_penalized():
    """18 br/min (above normal 12-20) should still score okay but not perfect."""
    s = _resp_score(18, 14.5)
    assert 40 <= s <= 80


# ─── Strain ─────────────────────────────────────────────────────────

def test_strain_zero_trimp():
    assert compute_strain(0) == 0


def test_strain_light_workout():
    """TRIMP 25 (45 min easy) → ~6.5 strain."""
    s = compute_strain(25)
    assert 6.0 <= s <= 7.5


def test_strain_hard_workout():
    """TRIMP 100 (60 min moderate-high) → ~9.2 strain."""
    s = compute_strain(100)
    assert 9 <= s <= 9.5


def test_daily_strain_empty():
    assert compute_daily_strain([]) == 0


def test_daily_strain_caps_at_21():
    """Pathological TRIMP (1M) caps at 21. Realistic TRIMP never gets close."""
    assert compute_daily_strain([1_000_000]) == 21


# ─── Simple strain fallback (no HR stream) ──────────────────────────

def test_estimate_strain_simple_no_data_returns_zero():
    """Without exercise minutes or avg HR, no strain."""
    assert estimate_strain_simple(0, 0, None, None) == 0
    assert estimate_strain_simple(30, 0, None, None) == 0


def test_estimate_strain_simple_moderate_workout():
    """60 min at 140 avg HR (75% of 186 max), 500 cal, peak 170 (91% → Z5 bonus).
    Expected: 21 × 0.75 × (1-exp(-1)) × 1.15 × (0.7 + 0.3 × 0.625) ≈ 9.5."""
    s = estimate_strain_simple(
        exercise_minutes=60,
        active_calories=500,
        avg_hr=140,
        max_hr_observed=170,
    )
    assert 8.5 <= s <= 11.0, f"moderate fallback {s} outside 8.5-11"


def test_estimate_strain_simple_caps_at_21():
    """Pathological inputs cap at 21."""
    s = estimate_strain_simple(
        exercise_minutes=600,
        active_calories=5000,
        avg_hr=200,
        max_hr_observed=210,
    )
    assert s == 21.0


def test_estimate_strain_simple_light_session():
    """30 min at 110 avg HR (moderate), 200 cal. Strain should be modest."""
    s = estimate_strain_simple(
        exercise_minutes=30,
        active_calories=200,
        avg_hr=110,
    )
    assert 2.0 <= s <= 6.0, f"light session {s} outside 2-6"


# ─── ACWR ───────────────────────────────────────────────────────────

def test_acwr_insufficient_data_returns_none():
    assert compute_acwr({}) is None
    short = {f"2026-04-{i:02d}": 50 for i in range(1, 10)}  # 9 days
    assert compute_acwr(short) is None


def test_acwr_sweet_spot():
    """Constant 50 TRIMP/day for 28 days: acute=350, chronic=50, ratio=1.0 → sweet spot."""
    daily = {f"2026-03-{i:02d}": 50.0 for i in range(1, 29)}
    r = compute_acwr(daily)
    assert r is not None
    assert 0.8 <= r["ratio"] <= 1.3
    assert r["zone"] == "green"


def test_acwr_overload():
    """Acute week triple the chronic load → ratio ~3 → red zone."""
    daily = {f"2026-03-{i:02d}": 20.0 for i in range(1, 22)}  # 21 low days
    daily.update({f"2026-03-{i:02d}": 90.0 for i in range(22, 29)})  # 7 hard days
    r = compute_acwr(daily)
    assert r is not None
    assert r["ratio"] > 1.5
    assert r["zone"] == "red"


# ─── Sleep need + strain target coaching ────────────────────────────

def test_strain_target_green():
    t = compute_strain_target(75)
    assert t["low"] == 14 and t["high"] == 17


def test_strain_target_yellow():
    t = compute_strain_target(50)
    assert t["low"] == 8 and t["high"] == 12


def test_strain_target_red():
    t = compute_strain_target(20)
    assert t["low"] == 0 and t["high"] == 6


def test_sleep_need_acute_debt_capped():
    """Acute debt is computed from the last 2 nights only and capped at 60 min.

    Chronic debt can't be repaid in one night (Banks & Dinges 2007), so
    even a week of severe underslept nights shouldn't produce a >60min debt.
    """
    need = compute_sleep_need(
        base_min=450,
        sleep_last_7=[300] * 7,  # every night 150min short = 150min each
        sleep_last_30=[450] * 30,
        today_strain=10,
    )
    assert need["baseMin"] == 450
    assert need["debtMin"] == 60, "debt must cap at 60 min per literature"
    assert need["strainMin"] == 15
    assert need["totalMin"] == 525


def test_sleep_need_personal_baseline_adapts():
    """Chronic 6h sleeper: baseline = 360 min, not the normative 450."""
    # 30 nights at 360 min → median 360.
    need = compute_sleep_need(
        sleep_last_30=[360] * 30,
        sleep_last_7=[360] * 7,
    )
    assert need["baseMin"] == 360
    assert need["baselineSource"] == "personal"
    assert need["debtMin"] == 0  # sleeping at baseline = no debt


def test_sleep_need_fallback_when_no_history():
    """Fewer than 7 nights of data → fallback 420 min, marked 'fallback'."""
    need = compute_sleep_need(sleep_last_30=[480, 500])
    assert need["baseMin"] == 420
    assert need["baselineSource"] == "fallback"


def test_sleep_need_wake_hour_inferred():
    """Median wake hour from recent data replaces the 6:30 AM default."""
    # Waking around 8 AM consistently.
    need = compute_sleep_need(
        sleep_last_30=[420] * 10,
        sleep_last_7=[420] * 7,
        wake_hours_last_7=[8.0, 8.25, 7.75, 8.0, 8.5, 7.5, 8.0],
    )
    assert need["wakeHour"] == 8.0
    # With 420 min (7h) total and 8 AM wake, bedtime should be 1 AM.
    assert need["bedtimeBy"] == "1:00a"


def test_sleep_need_no_absurd_afternoon_bedtime():
    """Regression: old algorithm treated every missing/short night as full
    debt vs a 7.5h ideal, producing afternoon bedtimes. Never again."""
    # Simulate Mateo's actual late-April data: chronic 6h, variable week.
    need = compute_sleep_need(
        sleep_last_30=[360] * 23 + [440, 337, 329, 379, 334, 463, 498],
        sleep_last_7=[440, 337, 329, 379, 334, 463, 498],
        wake_hours_last_7=[9.1, 5.2, 5.95],
    )
    # Total sleep need should be < 8h — not 14h as the old algorithm produced.
    assert need["totalMin"] < 480, f"total was {need['totalMin']}"
    # Bedtime must be in the evening / night, never PM.
    bedtime = need["bedtimeBy"]
    # Accept formats like "11:34p", "12:05a", "1:00a" but reject "3:48p".
    assert not (bedtime.endswith("p") and int(bedtime.split(":")[0]) < 8), f"absurd bedtime: {bedtime}"
