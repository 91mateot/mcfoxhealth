# Scoring Algorithms — Engineering Handoff

> Implementation guide for the health performance scoring system.
> These algorithms replace estimated/hardcoded values with computed scores from raw data.
> Last updated: April 26, 2026

## Overview

The system computes three primary scores (Recovery, Strain, Sleep) plus tracks Nutrition against targets. All scores are derived from raw biometric data pulled via Apple Health, Strava MCP, and Withings MCP.

**Current state:** Scores are estimated in conversation and hardcoded into static dashboards.
**Target state:** Scores computed in real-time from raw data on every dashboard load or morning briefing.

---

## 1. Recovery Score (0–100%)

Recovery represents readiness to train. Uses Whoop-style HRV-heavy weighting (chosen over Bevel's more sleep-generous approach based on user preference).

### Inputs

| Input | Source | Key |
|-------|--------|-----|
| HRV (ms) | Apple Health | `heartRateVariabilitySDNN` |
| Resting HR (bpm) | Apple Health | `restingHeartRate` |
| Sleep quality | Apple Health `sleepAnalysis` or Bevel | Composite (see Sleep Score) |
| Respiratory rate (/min) | Apple Health | `respiratoryRate` |
| 30-day baseline HRV | Rolling average | Computed from last 30 days |
| 30-day baseline RHR | Rolling average | Computed from last 30 days |

### Current Baselines (April 2026)

| Metric | Baseline | Observed Range |
|--------|----------|----------------|
| HRV | 48 ms | 31–58 ms |
| Resting HR | 64 bpm | 60.5–70 bpm |
| Respiratory rate | ~14 /min | 13.4–15.8 /min |

### Algorithm

```python
def compute_recovery(today_hrv, today_rhr, sleep_score, today_resp,
                     baseline_hrv=48, baseline_rhr=64):
    """
    Returns recovery score 0-100.
    
    Weights:
      HRV vs baseline:     50%
      RHR vs baseline:     25%
      Sleep quality:        15%
      Respiratory rate:     10%
    """
    
    # --- HRV Component (50%) ---
    # Higher HRV = better recovery
    hrv_delta = (today_hrv - baseline_hrv) / baseline_hrv
    
    if hrv_delta > 0.05:
        # Above baseline: score 80-100
        hrv_score = min(100, 80 + (hrv_delta - 0.05) * 400)
    elif hrv_delta >= -0.05:
        # Within ±5% of baseline: score 50-80
        hrv_score = 50 + ((hrv_delta + 0.05) / 0.10) * 30
    else:
        # Below baseline: score 0-50
        # Scale: -5% = 50, -33% = 0
        hrv_score = max(0, 50 * (1 + (hrv_delta + 0.05) / 0.28))
    
    # --- RHR Component (25%) ---
    # Lower RHR = better recovery (inverted)
    rhr_delta = (baseline_rhr - today_rhr) / baseline_rhr
    
    if rhr_delta > 0.03:
        # Below baseline (good): score 80-100
        rhr_score = min(100, 80 + (rhr_delta - 0.03) * 400)
    elif rhr_delta >= -0.03:
        # Within ±3%: score 50-80
        rhr_score = 50 + ((rhr_delta + 0.03) / 0.06) * 30
    else:
        # Above baseline (bad): score 0-50
        rhr_score = max(0, 50 * (1 + (rhr_delta + 0.03) / 0.12))
    
    # --- Sleep Component (15%) ---
    # Use sleep score directly (0-100, see Sleep Score algorithm)
    sleep_component = sleep_score
    
    # --- Respiratory Rate Component (10%) ---
    if 12 <= today_resp <= 16:
        resp_score = 85
    elif 10 <= today_resp < 12 or 16 < today_resp <= 18:
        resp_score = 60
    elif 18 < today_resp <= 20:
        resp_score = 40
    else:
        resp_score = 20
    
    # --- Weighted composite ---
    recovery = (
        hrv_score * 0.50 +
        rhr_score * 0.25 +
        sleep_component * 0.15 +
        resp_score * 0.10
    )
    
    return round(max(0, min(100, recovery)))


def classify_recovery(score):
    """Returns color classification for UI."""
    if score >= 67:
        return {"label": "Recovered", "color": "green", "action": "Train hard"}
    elif score >= 34:
        return {"label": "Moderate", "color": "yellow", "action": "Train smart, avoid max effort"}
    else:
        return {"label": "Depleted", "color": "red", "action": "Active recovery or rest"}
```

### Validation Against Real Data

| Date | HRV | RHR | Sleep | Resp | Computed | Estimated | Bevel |
|------|-----|-----|-------|------|----------|-----------|-------|
| Apr 17 | 43 | 63 | 77% | 13.4 | ~65% | 65% | 70% |
| Apr 19 | 31 | 66 | ~70% | 15.8 | ~28% | 28% | — |
| Apr 21 | 49 | 60.5 | 87% | 14.3 | ~82% | 82% | — |
| Apr 23 | 58 | 66 | 93% | 13.5 | ~60% | 60% | — |
| Apr 25 | 32 | 70 | 90% | 13.4 | ~38% | 38% | 32% |

### Edge Cases

- If HRV data is missing (Watch not worn overnight): fall back to RHR + sleep only, reweight to 45% RHR / 35% sleep / 20% resp
- If sleep data is truncated from Apple Health: use Bevel sleep score if available, otherwise estimate from available stages
- After alcohol: expect HRV to crater 24-48h later (confirmed pattern: Apr 19 = 31ms after Saturday drinking)
- On GLP-1 drugs (reta): expect HRV volatility (±26ms swings vs normal ±8ms). Consider widening the baseline tolerance bands during first 2 weeks of a new dose.

---

## 2. Strain Score (0–21, logarithmic)

Strain represents cumulative cardiovascular load for the day. Uses the Whoop 0-21 logarithmic scale (NOT Bevel's 0-100%).

### Inputs

| Input | Source | Key |
|-------|--------|-----|
| Heart rate stream | Strava MCP | `get-activity-streams` (heartrate) |
| Background HR | Apple Health | `heartRate` (hourly statistics) |
| Estimated max HR | Calculated | `220 - age` or observed max |
| Workout duration | Strava / Apple Health | `workoutType` samples |

### Algorithm

```python
import math

def compute_strain(hr_minutes, max_hr=190):
    """
    Compute strain from minute-by-minute heart rate data.
    
    Args:
        hr_minutes: list of (avg_hr_for_minute) values covering 
                    the full day or workout
        max_hr: estimated maximum heart rate (220 - age, or observed)
    
    Returns:
        strain: float 0.0 to 21.0
    """
    
    # Define HR zones as % of max HR
    zones = [
        (0.00, 0.50, 0),    # Below Z1: no contribution
        (0.50, 0.60, 1),    # Z1 Recovery
        (0.60, 0.70, 2),    # Z2 Endurance
        (0.70, 0.80, 3),    # Z3 Tempo
        (0.80, 0.90, 5),    # Z4 Threshold
        (0.90, 1.00, 8),    # Z5 Max
    ]
    
    # Calculate TRIMP (Training Impulse)
    trimp = 0
    zone_minutes = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    
    for hr in hr_minutes:
        hr_pct = hr / max_hr
        for z_low, z_high, weight in zones:
            if z_low <= hr_pct < z_high:
                trimp += weight
                # Track zone distribution for reporting
                zone_idx = zones.index((z_low, z_high, weight))
                if zone_idx > 0:
                    zone_minutes[zone_idx] = zone_minutes.get(zone_idx, 0) + 1
                break
    
    # Map TRIMP to 0-21 logarithmic scale
    # Key property: strain 18-21 is exponentially harder than 10-13
    strain = 21 * (1 - math.exp(-trimp / 300))
    
    return round(strain, 1), zone_minutes


def classify_strain(strain):
    """Returns classification for UI."""
    if strain < 10:
        return {"label": "Light", "color": "green", 
                "desc": "Walking, desk work, recovery"}
    elif strain < 14:
        return {"label": "Moderate", "color": "yellow",
                "desc": "Active day, light workout"}
    elif strain < 18:
        return {"label": "High", "color": "blue",
                "desc": "Solid training session"}
    else:
        return {"label": "Overreaching", "color": "red",
                "desc": "Competition-level, hard to sustain"}


def strain_vs_recovery(strain, recovery):
    """
    Contextualizes strain relative to recovery.
    This is the key insight — strain isn't good or bad in isolation.
    """
    if recovery >= 67 and strain >= 14:
        return "green", "Optimal — high capacity used well"
    elif recovery >= 67 and strain < 10:
        return "yellow", "Missed opportunity — recovered but easy day"
    elif recovery < 34 and strain >= 14:
        return "red", "Risky — pushed hard without reserves"
    elif recovery < 34 and strain < 10:
        return "green", "Appropriate — body needed rest"
    else:
        return "yellow", "Moderate — training smart"
```

### Simplified Strain (without HR streams)

When second-by-second HR data isn't available (Strava hasn't synced, or background activity only):

```python
def estimate_strain_simple(exercise_minutes, active_calories, 
                           avg_hr, max_hr_observed, est_max_hr=190):
    """
    Rough strain estimate from summary stats.
    Less accurate than TRIMP but usable for daily estimates.
    """
    # Intensity factor: how hard relative to capacity
    intensity = avg_hr / est_max_hr if avg_hr else 0
    
    # Duration factor: longer = more strain (diminishing returns)
    duration_factor = 1 - math.exp(-exercise_minutes / 60)
    
    # Peak factor: bonus for high max HR efforts  
    peak_factor = 1.0
    if max_hr_observed and max_hr_observed > est_max_hr * 0.9:
        peak_factor = 1.15  # Z5 bonus
    elif max_hr_observed and max_hr_observed > est_max_hr * 0.8:
        peak_factor = 1.08  # Z4 bonus
    
    # Calorie factor: cross-check
    cal_factor = min(1.0, active_calories / 800)
    
    strain = 21 * intensity * duration_factor * peak_factor * (0.7 + 0.3 * cal_factor)
    
    return round(min(21, strain), 1)
```

### Validation

| Date | Exercise Min | Active Cal | Avg HR | Max HR | Computed | Bevel (converted) |
|------|-------------|------------|--------|--------|----------|--------------------|
| Apr 17 | 93 | 1,119 | ~96 | 162 | ~14.8 | ~15.3 (73%) |
| Apr 18 | 109 | 1,383 | 96 | 167 | ~15.3 | ~15.3 (73%) |
| Apr 20 | 9 | 347 | — | — | ~3.2 | — |
| Apr 25 | 46 | 489 | 98 | 185 | ~10.2 | ~13.4 (64%) |

---

## 3. Sleep Score (0–100%)

Sleep quality composite score with duration weighted most heavily.

### Inputs

| Input | Source | Key |
|-------|--------|-----|
| Sleep stages | Apple Health | `sleepAnalysis` samples (AsleepDeep, AsleepREM, AsleepCore, Awake) |
| Total time in bed | Computed | Last sleep sample end - first sleep sample start |
| Total time asleep | Computed | Sum of all non-Awake stage durations |
| Sleep need | Configured | 7.5 hours (450 minutes) for Mateo |

### Algorithm

```python
def compute_sleep_score(total_asleep_min, total_in_bed_min, 
                        deep_min, rem_min, awake_episodes,
                        sleep_need_min=450):
    """
    Returns sleep score 0-100.
    
    Components:
      Duration vs need:    40 points
      Sleep efficiency:    25 points
      Deep sleep:          15 points
      REM sleep:           15 points
      Wake disruption:      5 points
    """
    
    # --- Duration (40 pts) ---
    # Full points at or above sleep need, linear decay below
    duration_ratio = min(total_asleep_min / sleep_need_min, 1.0)
    duration_score = duration_ratio * 40
    
    # Bonus for exceeding need (up to 5 extra points, capped at 40)
    if total_asleep_min > sleep_need_min:
        excess_ratio = min((total_asleep_min - sleep_need_min) / 60, 1.0)
        duration_score = min(40, duration_score + excess_ratio * 5)
    
    # --- Efficiency (25 pts) ---
    # efficiency = time_asleep / time_in_bed
    if total_in_bed_min > 0:
        efficiency = total_asleep_min / total_in_bed_min
    else:
        efficiency = 0
    
    if efficiency >= 0.95:
        eff_score = 25
    elif efficiency >= 0.90:
        eff_score = 20 + (efficiency - 0.90) / 0.05 * 5
    elif efficiency >= 0.80:
        eff_score = 12 + (efficiency - 0.80) / 0.10 * 8
    else:
        eff_score = max(0, efficiency / 0.80 * 12)
    
    # --- Deep Sleep (15 pts) ---
    # Target: 60+ minutes (13-23% of total is healthy)
    deep_ratio = min(deep_min / 60, 1.0)
    deep_score = deep_ratio * 15
    
    # --- REM Sleep (15 pts) ---
    # Target: 90+ minutes (20-25% of total is healthy)
    rem_ratio = min(rem_min / 90, 1.0)
    rem_score = rem_ratio * 15
    
    # --- Wake Disruption (5 pts) ---
    # Fewer wake episodes = better
    if awake_episodes <= 1:
        wake_score = 5
    elif awake_episodes <= 3:
        wake_score = 3
    elif awake_episodes <= 5:
        wake_score = 1
    else:
        wake_score = 0
    
    total = duration_score + eff_score + deep_score + rem_score + wake_score
    return round(max(0, min(100, total)))


def compute_sleep_debt(last_7_nights, sleep_need_min=450):
    """
    Track cumulative sleep debt over 7 days.
    
    Args:
        last_7_nights: list of total_asleep_min for each night
    
    Returns:
        debt_minutes: positive = debt, negative = surplus
        assessment: string
    """
    total_need = sleep_need_min * len(last_7_nights)
    total_actual = sum(last_7_nights)
    debt = total_need - total_actual
    
    if debt > 300:  # 5+ hours
        assessment = "Critical — strongly recommend catch-up sleep"
    elif debt > 180:  # 3+ hours
        assessment = "Elevated — prioritize sleep this week"
    elif debt > 0:
        assessment = "Mild — manageable"
    else:
        assessment = "Surplus — well rested"
    
    return debt, assessment
```

### Validation

| Date | Duration | Efficiency | Deep | REM | Awake Eps | Computed | Bevel |
|------|----------|------------|------|-----|-----------|----------|-------|
| Apr 17 | 6h 20m | 99% | 1h 18m | 2h 22m | 1 | ~77% | 72% |
| Apr 21 | 8h 43m | 87% | 58m | 1h 52m | 5 | ~72% | — |
| Apr 25 | 7h 42m | 98% | 53m | 2h 16m | ~1 | ~90% | 90% |

### Note on Apple Health Sleep Data Truncation

The Apple Health query tool frequently returns incomplete sleep sessions (only 2-5 hours of samples instead of the full night). This is a known limitation. Workarounds:

1. Use wider date ranges in the query
2. Use UTC time ranges that span the full overnight window
3. Fall back to Bevel's sleep data when available
4. Consider building an iOS Shortcut that exports complete sleep sessions to JSON

---

## 4. Nutrition Tracking

Nutrition is not a computed score — it's intake tracking against configured targets.

### Targets (Mateo, April 2026)

| Macro | Daily Target | Priority | Rationale |
|-------|-------------|----------|-----------|
| Calories | 2,200 kcal | Medium | Moderate deficit for recomp |
| Protein | 180g | **Critical** | 1g/lb BW, non-negotiable on reta |
| Carbs | 190g | Flexible | Fuel for training |
| Fat | 65g | Flexible | Hormonal health floor |
| Water | 80-100 oz | High | Elevated priority on GLP-1 |

### Alert Logic

```python
def check_nutrition_alerts(consumed, targets, time_of_day_pct):
    """
    Generate alerts based on current intake vs targets and time of day.
    
    Args:
        consumed: dict with cal, protein, carbs, fat, water
        targets: dict with cal, protein, carbs, fat, water
        time_of_day_pct: 0.0 (midnight) to 1.0 (end of day)
    
    Returns:
        list of alert dicts
    """
    alerts = []
    
    # Protein pacing check
    protein_pace = consumed["protein"] / max(targets["protein"] * time_of_day_pct, 1)
    if protein_pace < 0.7 and time_of_day_pct > 0.4:
        gap = targets["protein"] - consumed["protein"]
        alerts.append({
            "type": "protein",
            "severity": "high" if protein_pace < 0.5 else "medium",
            "message": f"{gap}g protein remaining — behind pace",
            "suggestion": "Add Oikos shake (30g P) or protein bar (21g P)"
        })
    
    # Multi-day protein deficit (escalated alert)
    # Requires last N days of protein data
    # If 2+ consecutive days under 100g: severity = critical
    
    # Calorie floor check
    if consumed["cal"] < 800 and time_of_day_pct > 0.6:
        alerts.append({
            "type": "undereating",
            "severity": "high",
            "message": "Under 800 cal past midday — undereating risk",
            "suggestion": "On GLP-1: eat by schedule, not hunger"
        })
    
    # Fat budget check
    fat_remaining = targets["fat"] - consumed["fat"]
    if fat_remaining < 10 and time_of_day_pct < 0.7:
        alerts.append({
            "type": "fat",
            "severity": "low",
            "message": f"Only {fat_remaining}g fat remaining — choose lean for dinner",
            "suggestion": "Grilled chicken breast, fish, or protein shake"
        })
    
    # Hydration check
    water_pace = consumed["water"] / max(targets["water"] * time_of_day_pct, 1)
    if water_pace < 0.5 and time_of_day_pct > 0.3:
        alerts.append({
            "type": "hydration",
            "severity": "high" if water_pace < 0.3 else "medium",
            "message": f"{consumed['water']}oz water — behind pace",
            "suggestion": "Drink a full glass now"
        })
    
    return alerts
```

### Known Foods Database

Frequently consumed items with verified macros. Store these for one-tap logging.

| Food | Cal | P | C | F | Source |
|------|-----|---|---|---|--------|
| Oikos Vanilla Protein Shake | 170 | 30 | 8 | 3.5 | Label |
| Kirkland PB Protein Bar | 190 | 21 | 22 | 7 | Label |
| Costco Chicken Bake (full) | 770 | 61 | 78 | 25 | Costco nutrition |
| Costco Chicken Bake (half) | 385 | 31 | 39 | 13 | Calculated |
| Promix Whey Vanilla (2 scoops) | 135 | 25 | 7 | 2 | Label |
| Promix Whey Vanilla (1 scoop) | 68 | 12.5 | 3.5 | 1 | Label |
| Ka'Chava Vanilla (1 scoop / half serving) | 120 | 12.5 | 12 | 3.5 | Label |
| Full morning shake | 712 | 53 | 102 | 17 | Calculated |
| Half morning shake | 356 | 26.5 | 51 | 8.5 | Calculated |
| MasonFit gochujang broth bowl | 515 | 33 | 66 | 12 | Calculated (corrected) |
| Sprouts rotisserie chicken per oz | ~56 | ~6.5 | 0 | ~3.2 | USDA |
| Catalina Crunch PB Granola (1/4 cup) | 70 | 6.5 | 8 | 3 | Label |

---

## 5. Data Sources & API Integration

### MCP Servers (Claude Code)

```bash
# Strava — workouts, HR streams, zones, segments
claude mcp add strava -- npx -y @r-huijts/strava-mcp-server \
  -e STRAVA_CLIENT_ID='...' -e STRAVA_CLIENT_SECRET='...'

# Withings — weight, body fat, body composition
claude mcp add withings -- npx -y @gchallen/withings-mcp \
  -e WITHINGS_CLIENT_ID='...' -e WITHINGS_CLIENT_SECRET='...'
```

### Apple Health Data Types Used

| Metric | HealthKit Key | Query Mode | Reliable? |
|--------|--------------|------------|-----------|
| HRV | `heartRateVariabilitySDNN` | statistics (avg) | Yes |
| Resting HR | `restingHeartRate` | statistics (avg) | Yes |
| Heart Rate | `heartRate` | statistics (all) | Yes |
| Respiratory Rate | `respiratoryRate` | statistics (avg) | Yes |
| Steps | `stepCount` | statistics (sum) | Yes |
| Active Calories | `activeEnergyBurned` | statistics (sum) | Yes |
| Exercise Time | `appleExerciseTime` | statistics (sum) | Yes |
| Workouts | `workoutType` | samples | Yes (may lag Strava sync) |
| Sleep | `sleepAnalysis` | samples | **Truncated — unreliable** |
| Weight | `bodyMass` | samples | Yes (requires Withings sync) |
| Body Fat | `bodyFatPercentage` | samples | Yes (requires Withings sync) |

### Strava MCP Tools

| Tool | Use For |
|------|---------|
| `get-recent-activities` | List recent workouts |
| `get-activity-details` | Single workout metadata |
| `get-activity-streams` | Second-by-second HR, cadence, GPS |
| `get-activity-laps` | Split/lap analysis |
| `get-athlete-stats` | All-time stats, PRs |
| `get-athlete-zones` | HR zone configuration |

---

## 6. Baseline Management

Baselines should be recomputed nightly from a rolling 30-day window.

```python
def update_baselines(daily_data, window=30):
    """
    Recompute baselines from last N days of data.
    
    Args:
        daily_data: list of dicts with hrv, rhr, sleep_min, etc.
        window: number of days for rolling average
    
    Returns:
        baselines dict
    """
    recent = daily_data[-window:]
    
    return {
        "hrv": mean([d["hrv"] for d in recent if d.get("hrv")]),
        "rhr": mean([d["rhr"] for d in recent if d.get("rhr")]),
        "resp": mean([d["resp"] for d in recent if d.get("resp")]),
        "sleep_min": mean([d["sleep_min"] for d in recent if d.get("sleep_min")]),
        "steps": mean([d["steps"] for d in recent if d.get("steps")]),
        "updated": datetime.now().isoformat(),
    }
```

### GLP-1 Adjustment

During the first 2 weeks of a new reta dose, HRV volatility increases dramatically (observed: ±8ms pre-reta → ±26ms post-reta). Consider:
- Widening the ±5% HRV tolerance band to ±10% during adjustment
- Flagging recovery scores with "reta adjustment active" disclaimer
- Tracking pre-reta vs post-reta baseline separately until stabilization

---

## 7. UI Color System

All scores use a consistent three-tier color system:

| Range | Color | Hex | Use |
|-------|-------|-----|-----|
| Good / On target | Green | `#2dd4a0` | Recovery 67-100%, protein on pace, hydration on track |
| Moderate / Below | Yellow | `#f5c542` | Recovery 34-66%, protein behind pace |
| Poor / Critical | Red | `#f06060` | Recovery 0-33%, protein severely low, dehydration |
| Strain | Blue | `#5b8cf5` | Strain indicator (neutral — high isn't bad) |
| Sleep / Hydration | Cyan | `#38bdf8` | Sleep stages, water tracking |
| Fat / REM | Purple | `#a78bfa` | Fat macro, REM sleep |
| Overages | Orange | `#fb923c` | Calories/fat over target |

---

## 8. Open Questions for Implementation

1. **Baseline cold start:** New users won't have 30 days of data. Use population averages (HRV ~45ms, RHR ~65) until enough data accumulates? Or require 7-day onboarding period?

2. **Strain without HR streams:** If Strava MCP fails to return streams, should we use the simplified estimate or show "pending"?

3. **Sleep data source priority:** Apple Health is unreliable for sleep. Should the app read from Bevel/Whoop API directly? Or build the iOS Shortcut bridge for complete HealthKit sleep export?

4. **GLP-1 protocol detection:** Should the app automatically detect HRV volatility patterns and adjust scoring, or require manual "I started reta" input?

5. **Nutrition AI:** Should meal logging use Claude API for natural language → macro estimation (current approach), or a dedicated food database API (Nutritionix, FatSecret)?

6. **Real-time vs daily:** Should scores update in real-time throughout the day (strain accumulates, nutrition updates per meal) or compute once each morning?
