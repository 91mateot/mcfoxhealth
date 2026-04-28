"""
API Lambda — read endpoints for the PWA frontend.

  GET /api/today         — Full today screen payload
  GET /api/trends        — 30-day trends + sparklines + correlations (deprecated, use /api/progress)
  GET /api/workouts      — Workout history
  GET /api/nutrition/:d  — Day's nutrition log
  GET /api/body          — Body composition history (deprecated, use /api/progress)
  GET /api/progress      — Union of body + trends for the Progress screen
"""

import json
import os
from datetime import datetime, timedelta, timezone

from shared.db import get_table, get_item, query_items
from shared.timezone import local_now, local_today_str


def lambda_handler(event, context):
    path = event.get("rawPath", "")
    params = event.get("pathParameters", {}) or {}

    if path == "/api/today":
        return _get_today()
    if path == "/api/trends":
        return _get_trends()
    if path == "/api/workouts":
        return _get_workouts()
    if path.startswith("/api/nutrition/"):
        date = params.get("date") or path.split("/")[-1]
        return _get_nutrition(date)
    if path == "/api/body":
        return _get_body()
    if path == "/api/progress":
        return _get_progress()

    return _resp(404, {"error": "not found"})


def _get_today():
    scores_table = get_table("DAILY_SCORES_TABLE")
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    nutrition_table = get_table("NUTRITION_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    baselines_table = get_table("BASELINES_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")

    today_dt = local_now()
    today_str = today_dt.strftime("%Y-%m-%d")

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    short_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    dow = today_dt.weekday()
    date_display = f"{short_days[dow]}, {months[today_dt.month - 1]} {today_dt.day}"
    date_full = f"{day_names[dow]}, {months[today_dt.month - 1]} {today_dt.day}, {today_dt.year}"

    scores = get_item(scores_table, {"date": today_str}) or {}
    baselines = get_item(baselines_table, {"type": "current"}) or {}

    recovery_week = []
    for i in range(6, -1, -1):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        d_dt = today_dt - timedelta(days=i)
        s = get_item(scores_table, {"date": d}) or {}
        rec = s.get("recovery", 0)
        zone = s.get("recovery_zone", "yellow")
        recovery_week.append({
            "d": short_days[d_dt.weekday()],
            "date": f"{d_dt.month}/{d_dt.day}",
            "rec": rec,
            "hrv": s.get("hrv"),
            "rhr": s.get("rhr"),
            "sleep": round(s.get("sleep", {}).get("total_min", 0) / 60, 1) if s.get("sleep") else None,
            "strain": s.get("strain", 0),
            "tag": zone,
            "today": i == 0,
        })

    hrv_30d = []
    for i in range(29, -1, -1):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        s = get_item(scores_table, {"date": d}) or {}
        hrv_30d.append(s.get("hrv") or baselines.get("hrv", 48))

    steps_week = []
    for i in range(6, -1, -1):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        d_dt = today_dt - timedelta(days=i)
        s = get_item(scores_table, {"date": d}) or {}
        steps_week.append({
            "d": short_days[d_dt.weekday()],
            "v": s.get("steps") or 0,
            "today": i == 0,
        })

    meals = query_items(nutrition_table, "date", today_str)
    meals_today = []
    water_total = 0
    caffeine_total = 0
    for m in meals:
        mid = m.get("meal_id", "")
        if mid.startswith("water_"):
            water_total += m.get("oz", 0)
        elif mid.startswith("meal_"):
            row = {
                "id": mid,
                "time": m.get("time", ""),
                "name": m.get("name", ""),
                "portion": m.get("portion", ""),
                "cal": m.get("cal", 0),
                "p": m.get("p", 0),
                "c": m.get("c", 0),
                "f": m.get("f", 0),
                "tag": m.get("tag", ""),
            }
            if m.get("validated_at"):
                row["validatedAt"] = m["validated_at"]
            if m.get("validated_source"):
                row["validatedSource"] = m["validated_source"]
            meals_today.append(row)
            if m.get("caffeine_mg"):
                caffeine_total += m.get("caffeine_mg", 0)
    meals_today.sort(key=lambda x: x.get("time") or "")

    config = get_item(config_table, {"key": "mateo"}) or {}
    targets = config.get("nutrition_targets", {"cal": 2200, "p": 180, "c": 190, "f": 65, "water": 100})
    supplements = config.get("supplements", [])

    protein_week = []
    for i in range(6, -1, -1):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        d_dt = today_dt - timedelta(days=i)
        s = get_item(scores_table, {"date": d}) or {}
        p = s.get("protein_total", 0)
        cal = s.get("cal_total", 0)
        protein_week.append({
            "d": short_days[d_dt.weekday()],
            "date": f"{d_dt.month}/{d_dt.day}",
            "p": p,
            "cal": cal,
            "flag": p < 100 if p else False,
            "today": i == 0,
            "inProgress": i == 0,
        })

    sleep = scores.get("sleep", {})
    sleep_hours = sleep.get("total_min", 0) // 60
    sleep_minutes = sleep.get("total_min", 0) % 60

    # Freshness indicator: max ingested_at across every source that writes
    # today's data (HAE metrics, Strava workouts, logged meals/water).
    todays_metrics = query_items(metrics_table, "date", today_str)
    todays_workouts = query_items(workouts_table, "date", today_str)
    updated_at = None
    for row in (*todays_metrics, *todays_workouts, *meals):
        ts = row.get("ingested_at") or row.get("logged_at")
        if ts and (updated_at is None or ts > updated_at):
            updated_at = ts

    coach_insights = _build_coach_insights(scores, baselines, targets, water_total)

    payload = {
        "date": date_display,
        "dateFull": date_full,
        "updatedAt": updated_at,
        "recovery": scores.get("recovery", 0),
        "recoveryZone": scores.get("recovery_zone", "yellow"),
        "strain": scores.get("strain", 0),
        "strainTarget": scores.get("strain_target", {"low": 8, "high": 12, "optimal": 10, "reason": "No data yet"}),
        "sleep": {
            "score": scores.get("sleep_score", 0),
            "hours": sleep_hours,
            "minutes": sleep_minutes,
            "efficiency": sleep.get("efficiency", 0),
            "deep": sleep.get("deep_min", 0),
            "rem": sleep.get("rem_min", 0),
            "core": sleep.get("core_min", 0),
            "awake": sleep.get("awake_min", 0),
        },
        "sleepNeedTonight": scores.get("sleep_need", {}),
        "hrv": scores.get("hrv"),
        "rhr": scores.get("rhr"),
        "resp": scores.get("resp"),
        "spo2": scores.get("spo2"),
        "wristTemp": scores.get("wrist_temp"),
        "recoveryComponents": scores.get("recovery_components"),
        "steps": scores.get("steps") or 0,
        "stepsGoal": baselines.get("steps", 10000),
        "calories": {
            "active": scores.get("active_cal") or 0,
            "resting": 1680,
        },
        "water": water_total,
        "waterGoal": targets.get("water", 100),
        "caffeineMg": caffeine_total,
        "caffeineGoal": targets.get("caffeine", 400),
        "recoveryWeek": recovery_week,
        "hrv30d": hrv_30d,
        "stepsWeek": steps_week,
        "mealsToday": meals_today,
        "nutritionTargets": targets,
        "proteinWeek": protein_week,
        "supplements": supplements,
        "coachInsights": coach_insights,
        "base": {
            "hrv": baselines.get("hrv", 48),
            "rhr": baselines.get("rhr", 64),
            "resp": baselines.get("resp", 14.5),
            "sleepNeed": 7.5,
            "steps": baselines.get("steps", 10000),
        },
    }

    return _resp(200, payload)


def _get_trends():
    return _resp(200, _progress_trend_body())


def _progress_trend_body():
    scores_table = get_table("DAILY_SCORES_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    today = local_now()

    def _avg_metric(days_back_start, days_back_end, key, sub_key=None):
        vals = []
        for i in range(days_back_start, days_back_end):
            d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            s = get_item(scores_table, {"date": d})
            if not s:
                continue
            if sub_key:
                v = s.get(key, {}).get(sub_key)
            else:
                v = s.get(key)
            if v is not None:
                vals.append(v)
        return round(sum(vals) / len(vals), 1) if vals else None

    metrics_config = {
        "hrv": {"key": "hrv", "unit": "ms", "better": "up"},
        "rhr": {"key": "rhr", "unit": "bpm", "better": "down"},
        "sleep": {"key": "sleep", "sub": "total_min", "unit": "min", "better": "up"},
        "recovery": {"key": "recovery", "unit": "%", "better": "up"},
        "strain": {"key": "strain", "unit": "", "better": "up"},
        "steps": {"key": "steps", "unit": "", "better": "up"},
        "protein": {"key": "protein_total", "unit": "g", "better": "up"},
        # Signals surfaced alongside the new HAE metrics on the Trends tab.
        # "better" is down for resp/temp (elevated = stressed/ill) and up
        # for spo2 (higher = better oxygenation).
        "resp": {"key": "resp", "unit": "/min", "better": "down"},
        "spo2": {"key": "spo2", "unit": "%", "better": "up"},
        "wristTemp": {"key": "wrist_temp", "unit": "°", "better": "down"},
    }

    trends_30d = {}
    for name, cfg in metrics_config.items():
        cur = _avg_metric(0, 30, cfg["key"], cfg.get("sub"))
        prev = _avg_metric(30, 60, cfg["key"], cfg.get("sub"))
        trends_30d[name] = {
            "cur": cur or 0,
            "prev": prev or 0,
            "unit": cfg["unit"],
            "better": cfg["better"],
        }

    trend_series = {}
    for name, cfg in metrics_config.items():
        series = []
        for i in range(29, -1, -1):
            d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            s = get_item(scores_table, {"date": d})
            if s:
                if cfg.get("sub"):
                    v = s.get(cfg["key"], {}).get(cfg["sub"], 0)
                else:
                    v = s.get(cfg["key"], 0)
                series.append(v or 0)
            else:
                series.append(0)
        trend_series[name] = series

    correlations = []
    journal_table = get_table("JOURNAL_TABLE")
    all_tags = set()
    for i in range(60):
        d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        j = get_item(journal_table, {"date": d})
        if j and j.get("tags"):
            all_tags.update(j["tags"])

    for tag in all_tags:
        items = query_items(corr_table, "tag", tag)
        correlations.extend(items)

    return {
        "trends30d": trends_30d,
        "trendSeries": trend_series,
        "correlations": correlations,
    }


def _get_workouts():
    table = get_table("WORKOUTS_TABLE")
    today = local_now()

    workouts = []
    for i in range(30):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(table, "date", d)
        workouts.extend(items)

    short_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    result = []
    for w in workouts:
        date_str = w.get("date", "")
        day_short = ""
        if date_str:
            try:
                dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()
                day_short = short_days[dow]
            except (ValueError, TypeError):
                pass
        sid = w.get("strava_id", "")
        source = w.get("source") or ("manual" if sid.startswith("manual_") else "strava")
        row = {
            "date": date_str,
            "day": day_short,
            "strava_id": sid,
            "title": w.get("title", ""),
            "type": w.get("type", ""),
            "dur": w.get("dur", 0),
            "avgHR": w.get("avgHR", 0),
            "maxHR": w.get("maxHR", 0),
            "cal": w.get("cal", 0),
            "strain": w.get("strain", 0),
            "trimp": w.get("trimp", 0),
            "zones": w.get("zones", {}),
            "notes": w.get("notes", ""),
            "exercises": w.get("exercises", []),
            "cardioIntervals": w.get("cardio_intervals", []),
            "sets": w.get("sets", 0),
            "source": source,
        }
        if w.get("session_notes"):
            row["sessionNotes"] = w["session_notes"]
        if w.get("annotated_at"):
            row["annotatedAt"] = w["annotated_at"]
        if w.get("original_text"):
            row["originalText"] = w["original_text"]
        if w.get("coach_feedback"):
            row["coachFeedback"] = w["coach_feedback"]
        if w.get("coach_feedback_at"):
            row["coachFeedbackAt"] = w["coach_feedback_at"]
        result.append(row)

    result.sort(key=lambda x: x["date"], reverse=True)
    return _resp(200, {"workouts": result})


def _get_nutrition(date_str):
    table = get_table("NUTRITION_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")

    items = query_items(table, "date", date_str)
    config = get_item(config_table, {"key": "mateo"}) or {}
    targets = config.get("nutrition_targets", {"cal": 2200, "p": 180, "c": 190, "f": 65, "water": 100})

    meals = []
    water_logs = []
    water_total = 0
    caffeine_total = 0
    totals = {"cal": 0, "p": 0, "c": 0, "f": 0}

    for m in items:
        mid = m.get("meal_id", "")
        if mid.startswith("water_"):
            oz = m.get("oz", 0)
            water_total += oz
            water_logs.append({
                "id": mid,
                "oz": oz,
                "loggedAt": m.get("logged_at"),
                "sourceMealId": m.get("source_meal_id"),
            })
        elif mid.startswith("meal_"):
            meal = {
                "id": mid,
                "time": m.get("time", ""),
                "name": m.get("name", ""),
                "portion": m.get("portion", ""),
                "cal": m.get("cal", 0),
                "p": m.get("p", 0),
                "c": m.get("c", 0),
                "f": m.get("f", 0),
                "tag": m.get("tag", ""),
            }
            if m.get("original_text"):
                meal["originalText"] = m["original_text"]
            if m.get("assumptions"):
                meal["assumptions"] = list(m["assumptions"])
            if m.get("confidence"):
                meal["confidence"] = m["confidence"]
            if m.get("source"):
                meal["source"] = m["source"]
            if m.get("source_url"):
                meal["sourceUrl"] = m["source_url"]
            if m.get("ingredients"):
                meal["ingredients"] = list(m["ingredients"])
            if m.get("water_oz") is not None:
                meal["waterOz"] = m["water_oz"]
            if m.get("caffeine_mg") is not None:
                meal["caffeineMg"] = m["caffeine_mg"]
                caffeine_total += m.get("caffeine_mg", 0)
            if m.get("validated_at"):
                meal["validatedAt"] = m["validated_at"]
            if m.get("validated_source"):
                meal["validatedSource"] = m["validated_source"]
            meals.append(meal)
            totals["cal"] += meal["cal"]
            totals["p"] += meal["p"]
            totals["c"] += meal["c"]
            totals["f"] += meal["f"]

    # Chronological sort so the Fuel timeline reads top-to-bottom by time-of-day.
    meals.sort(key=lambda x: x.get("time") or "")

    return _resp(200, {
        "date": date_str,
        "meals": meals,
        "totals": totals,
        "water": water_total,
        "waterLogs": water_logs,
        "caffeineMg": caffeine_total,
        "caffeineGoal": targets.get("caffeine", 400),
        "targets": targets,
    })


def _get_body():
    return _resp(200, _progress_now_body())


def _progress_now_body():
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    today = local_now()

    weight_14d = []
    body_fat_history = []

    for i in range(89, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(metrics_table, "date", d, sk_name="metric_source", sk_begins="weight#")
        for item in items:
            v = item.get("value")
            if v is not None:
                entry = {"date": d, "value": v}
                if i < 14:
                    weight_14d.append(v)
                body_fat_history.append(entry)
                break

    fat_entries = []
    for i in range(89, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(metrics_table, "date", d, sk_name="metric_source", sk_begins="fat_ratio#")
        for item in items:
            v = item.get("value")
            if v is not None:
                fat_entries.append({"date": d, "value": v})
                break

    lean_entries = []
    for i in range(89, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(metrics_table, "date", d, sk_name="metric_source", sk_begins="muscle_mass#")
        for item in items:
            v = item.get("value")
            if v is not None:
                lean_entries.append({"date": d, "value": v})
                break

    return {
        "weight14d": weight_14d,
        "weightHistory": body_fat_history,
        "fatHistory": fat_entries,
        "leanHistory": lean_entries,
    }


def _get_progress():
    return _resp(200, {
        "now": _progress_now_body(),
        "trend": _progress_trend_body(),
        "lifts": _progress_lifts_body(),
    })


def _progress_lifts_body():
    """Recent PRs, active stalls, weekly volume per muscle group.
    Compute job (daily) populates these."""
    exercises_table = get_table("EXERCISES_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")

    today = local_now()
    cutoff = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    # Recent PRs.
    recent_prs = []
    try:
        resp = exercises_table.scan(Limit=500)
        rows = resp.get("Items", [])
    except Exception:
        rows = []

    recent = [r for r in rows if r.get("date", "") >= cutoff]
    recent.sort(key=lambda r: r.get("date", ""), reverse=True)
    for r in recent:
        pr = r.get("pr") or {}
        kinds = []
        if pr.get("weight"):
            kinds.append("weight")
        if pr.get("e1rm"):
            kinds.append("e1rm")
        if pr.get("volume"):
            kinds.append("volume")
        if not kinds:
            continue
        recent_prs.append({
            "date": r.get("date"),
            "canonical": r.get("canonical"),
            "name": r.get("name", r.get("canonical", "?")),
            "muscleGroup": r.get("muscle_group", "other"),
            "topWeight": float(r.get("top_weight") or 0),
            "topReps": int(r.get("top_reps_at_top_weight") or 0),
            "e1rm": float(r.get("e1rm") or 0),
            "prKinds": kinds,
        })
        if len(recent_prs) >= 10:
            break

    # Stalls.
    stalls_row = get_item(config_table, {"key": "lift_stalls"}) or {}
    stalls = []
    for s in (stalls_row.get("stalls") or [])[:10]:
        stalls.append({
            "canonical": s.get("canonical"),
            "name": s.get("name", s.get("canonical", "?")),
            "muscleGroup": s.get("muscle_group", "other"),
            "weight": float(s.get("weight") or 0),
            "reps": int(s.get("reps") or 0),
            "sessions": int(s.get("sessions") or 0),
            "sinceDate": s.get("since_date"),
        })

    # Weekly volume (current week).
    week_start = today - timedelta(days=today.weekday())
    week_row = get_item(scores_table, {"date": f"week_{week_start.strftime('%Y-%m-%d')}"}) or {}
    volume_by_mg = week_row.get("volume_by_muscle_group") or {}
    sessions_by_mg = week_row.get("sessions_by_muscle_group") or {}

    # Previous week for comparison.
    prev_week_start = week_start - timedelta(days=7)
    prev_week_row = get_item(scores_table, {"date": f"week_{prev_week_start.strftime('%Y-%m-%d')}"}) or {}
    prev_volume = prev_week_row.get("volume_by_muscle_group") or {}

    weekly_volume = []
    for mg, vol in sorted(volume_by_mg.items(), key=lambda kv: float(kv[1]), reverse=True):
        prev = float(prev_volume.get(mg, 0) or 0)
        cur = float(vol)
        weekly_volume.append({
            "muscleGroup": mg,
            "volumeLb": round(cur, 0),
            "prevVolumeLb": round(prev, 0),
            "sessions": int(sessions_by_mg.get(mg, 0) or 0),
        })

    return {
        "recentPRs": recent_prs,
        "stalls": stalls,
        "weeklyVolume": weekly_volume,
        "weekStart": week_start.strftime("%Y-%m-%d"),
    }


def _build_coach_insights(scores, baselines, targets, water_total):
    """Generate coach insight cards based on current state."""
    insights = []

    recovery = scores.get("recovery", 0)
    zone = scores.get("recovery_zone", "yellow")
    hrv = scores.get("hrv")
    rhr = scores.get("rhr")
    strain_target = scores.get("strain_target", {})

    if zone == "green":
        body = f"Nervous system's fresh"
        if hrv:
            body += f" (HRV {hrv} ms"
            base_hrv = baselines.get("hrv", 48)
            if hrv > base_hrv:
                body += ", above your usual"
            body += ")"
        if rhr:
            body += f". Heart's relaxed (pulse {rhr})"
        body += f". {strain_target.get('reason', 'Train hard today')}."
        insights.append({"type": "recovery", "title": "You're recovered — go train", "body": body, "tag": "green", "icon": "🟢"})
    elif zone == "yellow":
        insights.append({"type": "recovery", "title": "Moderate recovery — train smart", "body": f"Recovery at {recovery}%. Keep intensity moderate, listen to your body.", "tag": "yellow", "icon": "🟡"})
    else:
        insights.append({"type": "recovery", "title": "Low recovery — rest day", "body": f"Recovery at {recovery}%. Your body needs rest. Walk or stretch only.", "tag": "red", "icon": "🔴"})

    protein = scores.get("protein_total", 0)
    if protein < 180:
        gap = 180 - protein
        insights.append({
            "type": "protein",
            "title": "You're behind on protein",
            "body": f"{protein}g so far, goal is 180g. {gap}g to go.",
            "tag": "yellow",
            "icon": "🥤",
        })

    water_goal = targets.get("water", 100)
    if water_total < water_goal * 0.5:
        remaining = water_goal - water_total
        insights.append({
            "type": "hydration",
            "title": "Water is lagging",
            "body": f"{water_total} oz down, {remaining} to go.",
            "tag": "blue",
            "icon": "💧",
        })

    return insights


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
