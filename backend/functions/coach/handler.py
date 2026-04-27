"""
Coach Lambda — AI chat powered by Bedrock Claude.

  POST /api/coach — Send messages, get streaming AI response
"""

import json
import os
from datetime import datetime, timedelta, timezone

import boto3

from shared.db import get_table, get_item, query_items
from shared.timezone import local_today_str

bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")
MODEL_ID = os.environ.get("COACH_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def lambda_handler(event, context):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    messages = body.get("messages", [])
    if not messages:
        return _resp(400, {"error": "no messages provided"})

    system_prompt = _build_system_prompt()

    bedrock_messages = []
    for m in messages:
        role = "user" if m.get("from") == "me" else "assistant"
        bedrock_messages.append({"role": role, "content": m.get("text", "")})

    if bedrock_messages and bedrock_messages[-1]["role"] != "user":
        return _resp(400, {"error": "last message must be from user"})

    try:
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": bedrock_messages,
            }),
        )

        result = json.loads(response["body"].read())
        reply_text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                reply_text += block["text"]

        return _resp(200, {
            "reply": {
                "from": "coach",
                "t": datetime.now(timezone.utc).strftime("%-I:%M%p").lower(),
                "text": reply_text,
            }
        })

    except Exception as e:
        return _resp(500, {"error": f"bedrock error: {str(e)}"})


def _build_system_prompt():
    """Build the coach system prompt with today's real data + 7-day context.

    Pulls from 6 DynamoDB tables: daily scores, workouts, nutrition, health
    metrics (for body composition), baselines (for deviation context),
    journal (last night's tags), and correlations (learned patterns).
    """
    today_str = local_today_str()

    scores_table = get_table("DAILY_SCORES_TABLE")
    nutrition_table = get_table("NUTRITION_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    baselines_table = get_table("BASELINES_TABLE")
    journal_table = get_table("JOURNAL_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    scores = get_item(scores_table, {"date": today_str}) or {}
    baselines = get_item(baselines_table, {"type": "current"}) or {}

    meals_today = query_items(nutrition_table, "date", today_str)
    workouts_today = query_items(workouts_table, "date", today_str)

    today_block = _today_block(today_str, scores, meals_today, workouts_today, baselines)
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


# ─── Prompt section builders ──────────────────────────────────────────


def _today_block(today_str, scores, meals_today, workouts_today, baselines):
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

    # Baseline deltas (so coach can say "above baseline" / "below baseline")
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

    # Sleep breakdown
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
    """Latest Withings body comp reading within the last 14 days."""
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
            if len(latest) >= 5:  # weight, fat_ratio, fat_mass, muscle_mass, hydration
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
    """Last 7 days of recovery/strain/sleep/HRV + last 7 workouts."""
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
    except Exception:
        return ""

    day_lines = []
    workout_lines = []
    for i in range(1, 8):  # yesterday → 7 days ago
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
        sections.append("## Last 7 Days (workouts)\n" + "\n".join(workout_lines[:10]))  # cap at 10
    return "\n\n".join(sections) if sections else "## Last 7 Days\nNo recent data."


def _last_night_journal_block(journal_table, today_str):
    """Most recent journal within the last 2 days."""
    try:
        dt = datetime.strptime(today_str, "%Y-%m-%d")
    except Exception:
        return ""

    for i in range(3):  # today, yesterday, 2 days ago
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
    """Top correlations by confidence, capped at 5. Table is tag+metric keyed,
    so we scan — it's tiny."""
    try:
        from shared.db import get_client
    except ImportError:
        get_client = None

    items = []
    try:
        # Scan is fine here; the table only contains tens of rows
        resp = corr_table.scan(Limit=50)
        items = resp.get("Items", [])
    except Exception:
        return ""

    if not items:
        return "## Learned Patterns\nNot enough data yet (need ~14 days of journal entries)."

    # Prefer high-confidence, then absolute effect size
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


def _parse_body(event):
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError):
        return None


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
