"""
Coach context builder — assembles the system prompt for the coach Lambda.

Today's block is built from a client-supplied snapshot (TodayResponse shape
from src/types.ts) so the coach sees the same data that's on Mateo's screen.
Body composition, 7-day history, journal, and correlations are still read
from DynamoDB since they change on daily cadence, not minute-by-minute.
"""

from datetime import datetime, timedelta
from typing import Optional

from shared.db import get_table, get_item, query_items
from shared.timezone import local_today_str


def build_system_prompt(snapshot: Optional[dict]) -> str:
    today_str = local_today_str()

    scores_table = get_table("DAILY_SCORES_TABLE")
    nutrition_table = get_table("NUTRITION_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    baselines_table = get_table("BASELINES_TABLE")
    journal_table = get_table("JOURNAL_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    if snapshot and isinstance(snapshot, dict):
        today_block = _today_block_from_snapshot(snapshot)
    else:
        scores = get_item(scores_table, {"date": today_str}) or {}
        baselines = get_item(baselines_table, {"type": "current"}) or {}
        meals_today = query_items(nutrition_table, "date", today_str)
        workouts_today = query_items(workouts_table, "date", today_str)
        today_block = _today_block_from_db(today_str, scores, meals_today, workouts_today, baselines)

    body_block = _body_composition_block(metrics_table, today_str)
    week_block = _week_history_block(scores_table, workouts_table, today_str)
    journal_block = _last_night_journal_block(journal_table, today_str)
    correlations_block = _correlations_block(corr_table)

    return f"""You are Mateo's personal fitness coach AI. You live inside his fitness dashboard app.

## Who Mateo Is
- 34 years old, 5'8", currently 169 lbs at 13.6% body fat
- Goal: sub-12% body fat while defending lean mass
- Location: Pacific Beach, San Diego
- Training: 4-5x/week, push/pull/legs split with supersets
- Back injury history: avoid loaded squats and heavy deadlifts

## Active Medication
Retatrutide (GLP-1/GIP/Glucagon triple agonist), 2mg dose, started April 21, 2026.
- Appetite is heavily suppressed — he will NOT feel hungry
- Protein (180g/day) is NON-NEGOTIABLE to protect lean mass
- Smaller frequent meals work better than large ones
- Suggest liquid protein (shakes, Oikos) when appetite is low

## Your Tools
You have tools to take action for Mateo. Use them proactively when he mentions consuming something or notes a feeling.

- log_meal(text): Free-form meal description → estimates macros AND logs it. Use this the moment Mateo says "had a …", "just ate …", "drank a …". Includes hydration and caffeine automatically.
- log_water(oz): Log water intake in ounces. Use for "drank a glass of water" type messages with no food.
- log_journal(tags, mood?, stress?, soreness?): Tag how he's feeling. Use when he mentions mood, stress, soreness, alcohol, back flare, travel, etc. Valid tags: alcohol, caffeine_late, ate_late, heavy_meal, hydrated, screens_bed, late_bedtime, meditated, stretched, sauna, cold, sunlight_am, stress, social, travel, sick, back_flare.
- get_recent_meals(days): Look up the last N days of meals. Use when Mateo asks about what he ate or when you need context on recent intake.

When you log something, confirm what you did with specific numbers (e.g. "Logged: green tea — 2 cal, 12 oz water, 30 mg caffeine."). Don't ask for confirmation first; he can edit in the Fuel tab if you got it wrong.

{today_block}

{body_block}

{week_block}

{journal_block}

{correlations_block}

## Nutrition Targets
- Calories: 2,200/day | Protein: 180g | Carbs: 190g | Fat: 65g | Water: 80-100oz

## Known Quick Foods
- Oikos Vanilla Protein Shake: 170 cal, 30g P
- Kirkland PB Protein Bar: 190 cal, 21g P
- Half morning shake: 356 cal, 26.5g P
- MasonFit gochujang bowl: 380 cal, 36g P

## Your Tone
Direct, data-first. Like a coach reviewing game film.
- Lead with numbers and context
- Skip preamble and pleasantries
- No guilt about food choices — just data and suggestions
- Be specific: "add one Oikos between meals" not "try to eat more protein"
- Keep responses concise (2-4 sentences for simple questions, more for briefings)"""


def _today_block_from_snapshot(s: dict) -> str:
    """Build today's data block from the client-sent TodayResponse shape."""
    recovery = s.get("recovery", "unknown")
    zone = s.get("recoveryZone", "unknown")
    hrv = s.get("hrv")
    rhr = s.get("rhr")
    resp = s.get("resp")
    spo2 = s.get("spo2")
    wrist = s.get("wristTemp")
    strain = s.get("strain", 0)
    strain_target = s.get("strainTarget") or {}
    sleep = s.get("sleep") or {}
    sleep_need = s.get("sleepNeedTonight") or {}
    steps = s.get("steps")
    steps_goal = s.get("stepsGoal")
    calories = s.get("calories") or {}
    meals = s.get("mealsToday") or []
    water = s.get("water", 0)
    water_goal = s.get("waterGoal", 100)
    caffeine = s.get("caffeineMg", 0)
    caffeine_goal = s.get("caffeineGoal", 400)
    nutrition_targets = s.get("nutritionTargets") or {}
    base = s.get("base") or {}

    protein = sum(m.get("p", 0) for m in meals)
    carbs = sum(m.get("c", 0) for m in meals)
    fat = sum(m.get("f", 0) for m in meals)
    cals = sum(m.get("cal", 0) for m in meals)

    def _delta(val, base_val):
        if val is None or base_val is None:
            return ""
        try:
            d = float(val) - float(base_val)
            pct = (d / float(base_val)) * 100 if float(base_val) else 0
            sign = "+" if d >= 0 else ""
            return f" (baseline {base_val}, {sign}{pct:.0f}%)"
        except Exception:
            return ""

    hrv_str = f"{hrv} ms{_delta(hrv, base.get('hrv'))}" if hrv is not None else "n/a"
    rhr_str = f"{rhr} bpm{_delta(rhr, base.get('rhr'))}" if rhr is not None else "n/a"
    resp_str = f"{resp} br/min{_delta(resp, base.get('resp'))}" if resp is not None else "n/a"
    spo2_str = f"{spo2}%" if spo2 is not None else "n/a"
    wrist_str = f"{wrist}°C" if wrist is not None else "n/a"

    hours = sleep.get("hours", 0)
    minutes = sleep.get("minutes", 0)
    sleep_str = f"{hours}h {minutes}m" if (hours or minutes) else "n/a"

    meal_lines = []
    for m in meals:
        meal_lines.append(
            f"- {m.get('time', '')} {m.get('name', '')}: "
            f"{m.get('cal', 0)} cal, {m.get('p', 0)}P / {m.get('c', 0)}C / {m.get('f', 0)}F"
        )
    meals_block = "\n".join(meal_lines) if meal_lines else "No meals logged yet today."

    target_cal = nutrition_targets.get("cal", 2200)
    target_p = nutrition_targets.get("p", 180)
    target_c = nutrition_targets.get("c", 190)
    target_f = nutrition_targets.get("f", 65)

    return f"""## Today's Data (from live client snapshot — {s.get('date', '')})

### Recovery & Readiness
- Recovery: {recovery}% ({zone})
- HRV: {hrv_str}
- Resting HR: {rhr_str}
- Respiratory rate: {resp_str}
- SpO2: {spo2_str}
- Wrist temperature: {wrist_str}

### Sleep Last Night
- Score: {sleep.get('score', 'n/a')}/100
- Duration: {sleep_str} ({sleep.get('efficiency', 0)}% efficiency)
- Deep: {sleep.get('deep', 0)} min | REM: {sleep.get('rem', 0)} min | Core: {sleep.get('core', 0)} min | Awake: {sleep.get('awake', 0)} min
- Sleep need tonight: {sleep_need.get('totalMin', 'n/a')} min (bed by {sleep_need.get('bedtimeBy', 'n/a')})

### Strain & Activity
- Strain so far: {strain}/21 (target {strain_target.get('low', '?')}-{strain_target.get('high', '?')}: {strain_target.get('reason', '')})
- Steps: {steps if steps is not None else 'n/a'} / {steps_goal if steps_goal else '—'}
- Active calories: {calories.get('active', 'n/a')} kcal

### Nutrition So Far
{meals_block}

- Calories: {cals} / {target_cal} target
- Protein: {protein}g / {target_p}g target
- Carbs: {carbs}g / {target_c}g target
- Fat: {fat}g / {target_f}g target
- Water: {water} oz / {water_goal} oz target
- Caffeine: {caffeine} mg / {caffeine_goal} mg cap"""


def _today_block_from_db(today_str, scores, meals_today, workouts_today, baselines):
    """Fallback today block if the client didn't send a snapshot."""
    protein = sum(m.get("p", 0) for m in meals_today if m.get("meal_id", "").startswith("meal_"))
    carbs = sum(m.get("c", 0) for m in meals_today if m.get("meal_id", "").startswith("meal_"))
    fat = sum(m.get("f", 0) for m in meals_today if m.get("meal_id", "").startswith("meal_"))
    cals = sum(m.get("cal", 0) for m in meals_today if m.get("meal_id", "").startswith("meal_"))
    water = sum(m.get("oz", 0) for m in meals_today if m.get("meal_id", "").startswith("water_"))

    recovery = scores.get("recovery", "unknown")
    zone = scores.get("recovery_zone", "unknown")
    hrv = scores.get("hrv")
    rhr = scores.get("rhr")
    resp = scores.get("resp")
    spo2 = scores.get("spo2")
    wrist_temp = scores.get("wrist_temp")
    strain = scores.get("strain", 0)
    strain_target = scores.get("strain_target", {})
    sleep = scores.get("sleep", {})
    sleep_score = scores.get("sleep_score")
    sleep_need = scores.get("sleep_need", {})
    steps = scores.get("steps")
    active_cal = scores.get("active_cal")

    def delta(val, base):
        if val is None or base is None:
            return ""
        try:
            d = float(val) - float(base)
            pct = (d / float(base)) * 100 if float(base) else 0
            sign = "+" if d >= 0 else ""
            return f" (baseline {base}, {sign}{pct:.0f}%)"
        except Exception:
            return ""

    hrv_str = f"{hrv} ms{delta(hrv, baselines.get('hrv'))}" if hrv is not None else "n/a"
    rhr_str = f"{rhr} bpm{delta(rhr, baselines.get('rhr'))}" if rhr is not None else "n/a"
    resp_str = f"{resp} br/min{delta(resp, baselines.get('resp'))}" if resp is not None else "n/a"
    spo2_str = f"{spo2}%{delta(spo2, baselines.get('spo2'))}" if spo2 is not None else "n/a"
    wrist_str = (
        f"{wrist_temp}°C{delta(wrist_temp, baselines.get('wrist_temp'))}"
        if wrist_temp is not None else "n/a"
    )

    total_min = sleep.get("total_min", 0)
    sleep_hours = f"{total_min // 60}h {total_min % 60}m" if total_min else "n/a"
    deep = sleep.get("deep_min", 0)
    rem = sleep.get("rem_min", 0)
    core = sleep.get("core_min", 0)
    awake = sleep.get("awake_min", 0)

    if workouts_today:
        workout_lines = []
        for w in workouts_today:
            zones = w.get("zones") or {}
            zone_str = " ".join(
                f"{z}:{int(round(float(zones[z])))}m"
                for z in ("z1", "z2", "z3", "z4", "z5")
                if zones.get(z) and float(zones[z]) > 0
            )
            workout_lines.append(
                f"- {w.get('title', 'Workout')} ({w.get('type', 'unknown')}): "
                f"{int(w.get('dur', 0))} min, "
                f"avg HR {int(round(float(w.get('avgHR', 0))))}, "
                f"max HR {int(round(float(w.get('maxHR', 0))))}, "
                f"strain {w.get('strain', 0)}, "
                f"{int(w.get('cal', 0))} cal"
                + (f" — zones: {zone_str}" if zone_str else "")
            )
        workouts_block = "\n".join(workout_lines)
    else:
        workouts_block = "No workout logged today yet."

    return f"""## Today's Data ({today_str})

### Recovery & Readiness
- Recovery: {recovery}% ({zone})
- HRV: {hrv_str}
- Resting HR: {rhr_str}
- Respiratory rate: {resp_str}
- SpO2: {spo2_str}
- Wrist temperature: {wrist_str}

### Sleep Last Night
- Score: {sleep_score if sleep_score is not None else 'n/a'}/100
- Duration: {sleep_hours} ({sleep.get('efficiency', 0)}% efficiency)
- Deep: {deep} min | REM: {rem} min | Core: {core} min | Awake: {awake} min
- Sleep need tonight: {sleep_need.get('totalMin', 'n/a')} min (bed by {sleep_need.get('bedtimeBy', 'n/a')})

### Strain & Activity
- Strain so far: {strain}/21 (target {strain_target.get('low', '?')}-{strain_target.get('high', '?')}: {strain_target.get('reason', '')})
- Steps: {steps if steps is not None else 'n/a'}
- Active calories: {active_cal if active_cal is not None else 'n/a'} kcal

### Today's Workouts
{workouts_block}

### Nutrition So Far
- Calories: {cals} / 2200 target
- Protein: {protein}g / 180g target
- Carbs: {carbs}g / 190g target
- Fat: {fat}g / 65g target
- Water: {water} oz / 100 oz target"""


def _body_composition_block(metrics_table, today_str):
    latest = {}
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
        for i in range(14):
            d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
            items = query_items(metrics_table, "date", d)
            for m in items:
                src = m.get("metric_source", "")
                if src.endswith("#withings") and src.replace("#withings", "") not in latest:
                    key = src.replace("#withings", "")
                    latest[key] = (m.get("value"), d)
            if len(latest) >= 5:
                break
    except Exception:
        pass

    if not latest:
        return "## Body Composition\nNo recent body composition data."

    lines = ["## Body Composition (most recent Withings reads)"]
    labels = {
        "weight": "Weight",
        "fat_ratio": "Body fat",
        "fat_mass": "Fat mass",
        "muscle_mass": "Lean mass",
        "hydration": "Body water",
    }
    units = {"weight": "lbs", "fat_ratio": "%", "fat_mass": "lbs", "muscle_mass": "lbs", "hydration": "lbs"}
    for key in ("weight", "fat_ratio", "muscle_mass", "fat_mass", "hydration"):
        if key in latest:
            val, d = latest[key]
            lines.append(f"- {labels[key]}: {val} {units[key]} ({d})")
    return "\n".join(lines)


def _week_history_block(scores_table, workouts_table, today_str):
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
    except Exception:
        return ""

    day_lines = []
    workout_lines = []
    for i in range(1, 8):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        s = get_item(scores_table, {"date": d}) or {}
        if s:
            sleep = s.get("sleep", {})
            total_min = sleep.get("total_min", 0)
            sleep_hm = f"{total_min // 60}h{total_min % 60:02d}m" if total_min else "—"
            day_lines.append(
                f"- {d}: recovery {s.get('recovery', '—')}% ({s.get('recovery_zone', '—')}), "
                f"HRV {s.get('hrv', '—')}, RHR {s.get('rhr', '—')}, "
                f"strain {s.get('strain', '—')}, sleep {sleep_hm}"
            )
        ws = query_items(workouts_table, "date", d) or []
        for w in ws:
            workout_lines.append(
                f"- {d}: {w.get('title', 'Workout')} ({w.get('type', '?')}) — "
                f"{int(w.get('dur', 0))} min, strain {w.get('strain', '—')}, "
                f"avg HR {int(round(float(w.get('avgHR', 0))))}"
            )

    sections = []
    if day_lines:
        sections.append("## Last 7 Days (daily summary)\n" + "\n".join(day_lines))
    if workout_lines:
        sections.append("## Last 7 Days (workouts)\n" + "\n".join(workout_lines[:10]))
    return "\n\n".join(sections) if sections else "## Last 7 Days\nNo recent data."


def _last_night_journal_block(journal_table, today_str):
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
    except Exception:
        return ""

    for i in range(3):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        j = get_item(journal_table, {"date": d})
        if j and (j.get("tags") or j.get("mood") is not None):
            tags = j.get("tags") or []
            mood = j.get("mood")
            stress = j.get("stress")
            soreness = j.get("soreness")
            lines = [f"## Most Recent Journal ({d})"]
            if tags:
                lines.append(f"- Tags: {', '.join(tags)}")
            if mood is not None:
                lines.append(f"- Mood: {mood}/5")
            if stress is not None:
                lines.append(f"- Stress: {stress}/5")
            if soreness is not None:
                lines.append(f"- Soreness: {soreness}/5")
            return "\n".join(lines)

    return "## Journal\nNo recent journal entries."


def _correlations_block(corr_table):
    items = []
    try:
        resp = corr_table.scan(Limit=50)
        items = resp.get("Items", [])
    except Exception:
        return ""

    if not items:
        return "## Learned Patterns\nNot enough data yet (need ~14 days of journal entries)."

    conf_rank = {"high": 3, "medium": 2, "low": 1}
    items.sort(key=lambda x: (conf_rank.get(x.get("confidence"), 0), abs(float(x.get("effect", 0)))), reverse=True)

    lines = ["## Learned Patterns (journal tag → outcome)"]
    for c in items[:5]:
        effect = c.get("effect", 0)
        sign = "+" if float(effect) > 0 else ""
        lines.append(
            f"- {c.get('tag')} → {c.get('metric')}: {sign}{effect}{c.get('unit', '')} "
            f"(n={c.get('n')}, {c.get('confidence')} confidence)"
        )
    return "\n".join(lines)
