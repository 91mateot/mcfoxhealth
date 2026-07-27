"""
API Lambda — read endpoints for the PWA frontend.

  GET  /api/today                       — Full today screen payload
  GET  /api/workouts                    — Workout history
  GET  /api/nutrition/:d                — Day's nutrition log
  GET  /api/nutrition/history           — Last N days of nutrition (default 7)
  GET  /api/progress                    — Body composition + 30-day trends + lifts
  GET  /api/insights                    — Numeric + journal-tag correlations for the Insights modal
  GET  /api/conversation/latest         — Most recent coach thread (if active within 6h)
  GET  /api/conversation/list           — Recent coach threads (projected, newest first)
  GET  /api/conversation/{id}           — Full thread by id (no idle cutoff)
  POST /api/planned-workout/refresh     — Re-run the proposer for today
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3

from shared.cost_service import get_costs as _get_infra_costs
from shared.db import get_table, get_item, put_item, query_items
from shared.scoring import sleep_component_breakdown
from shared.timezone import local_now, local_today_str
from shared.conversation_service import (
    get_latest as get_latest_conversation,
    list_recent as list_recent_conversations,
    load as load_conversation,
)
from shared.workout_proposer import (
    propose_for_date as _propose_workout_for_date,
    set_rest_day as _set_rest_day,
)


_secrets_client = boto3.client("secretsmanager")
_api_key_cache = {"value": None, "ts": 0}


def _verify_api_key(event):
    key = (event.get("headers") or {}).get("x-api-key", "")
    if not key:
        return False
    now = int(time.time())
    if _api_key_cache["value"] is None or now - _api_key_cache["ts"] > 300:
        try:
            resp = _secrets_client.get_secret_value(SecretId="fitness-api-key")
            _api_key_cache["value"] = json.loads(resp["SecretString"]).get("api_key", "")
        except Exception:
            _api_key_cache["value"] = os.environ.get("INGEST_API_KEY", "")
        _api_key_cache["ts"] = now
    return bool(_api_key_cache["value"]) and key == _api_key_cache["value"]


def lambda_handler(event, context):
    if not _verify_api_key(event):
        return _resp(401, {"error": "unauthorized"})

    path = event.get("rawPath", "")
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
    params = event.get("pathParameters", {}) or {}

    if path == "/api/today":
        return _get_today()
    if path == "/api/workouts":
        return _get_workouts()
    if path == "/api/nutrition/history":
        return _get_nutrition_history(event)
    if path.startswith("/api/nutrition/"):
        date = params.get("date") or path.split("/")[-1]
        return _get_nutrition(date)
    if path == "/api/progress":
        return _get_progress()
    if path == "/api/insights":
        return _get_insights()
    if path == "/api/infra-cost":
        return _get_infra_cost(event)
    if path == "/api/conversation/latest":
        return _get_latest_conversation()
    if path == "/api/conversation/list":
        return _list_conversations(event)
    if path.startswith("/api/conversation/"):
        conv_id = params.get("conversationId") or path.rsplit("/", 1)[-1]
        return _get_conversation_by_id(conv_id)
    if path == "/api/journal/history":
        return _get_journal_history(event)
    if path == "/api/planned-workout/refresh" and method == "POST":
        return _refresh_planned_workout()
    if path == "/api/planned-workout/rest" and method == "POST":
        return _mark_rest_day(event)

    return _resp(404, {"error": "not found"})


def _get_infra_cost(event):
    qs = event.get("queryStringParameters") or {}
    force = str(qs.get("refresh") or "").lower() in ("1", "true", "yes")
    try:
        payload = _get_infra_costs(force=force)
    except Exception as e:
        return _resp(500, {"error": f"cost lookup failed: {e}"})
    return _resp(200, payload)


def _refresh_planned_workout():
    """Re-run the proposer for today and persist. Clears any manual
    rest-day override — Refresh = 'give me a fresh recommendation'."""
    today_str = local_today_str()
    try:
        proposal = _propose_workout_for_date(today_str)
    except Exception as e:
        return _resp(500, {"error": f"propose failed: {e}"})

    scores_table = get_table("DAILY_SCORES_TABLE")
    existing = get_item(scores_table, {"date": today_str}) or {"date": today_str}
    existing["planned_workout"] = proposal
    put_item(scores_table, existing)

    todays_workouts = query_items(get_table("WORKOUTS_TABLE"), "date", today_str)
    return _resp(200, {"plannedWorkout": _prepare_planned_workout(proposal, todays_workouts)})


def _mark_rest_day(event):
    """Mark today as a recovery day. Persists with rest_override=True so
    the nightly compute job doesn't regenerate a workout proposal on top."""
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, TypeError):
        body = {}
    reason = body.get("reason") if isinstance(body, dict) else None
    today_str = local_today_str()
    try:
        proposal = _set_rest_day(today_str, reason=reason if isinstance(reason, str) else None)
    except Exception as e:
        return _resp(500, {"error": f"set rest day failed: {e}"})

    todays_workouts = query_items(get_table("WORKOUTS_TABLE"), "date", today_str)
    return _resp(200, {"plannedWorkout": _prepare_planned_workout(proposal, todays_workouts)})


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

    # Nutrition data-integrity flag (2026-07-27): fitness-nutrition can be
    # a genuinely dead/unwired feed for extended periods (e.g. Mateo's
    # nutrition tracking gaps). A bare 0 total is indistinguishable from
    # "logged and ate nothing" — surface whether ANY row exists today so
    # downstream correlation work can tell "no data" from "zero intake".
    nutrition_has_data = bool(meals)

    config = get_item(config_table, {"key": "mateo"}) or {}
    targets = config.get("nutrition_targets", {"cal": 2200, "p": 180, "c": 190, "f": 65, "water": 100})
    # Canonical supplement list lives in user_config (name + tag + dose).
    # "taken today" is derived from whether the tag is present on today's
    # journal row so Fuel Stack and Journal sheet stay in sync without a
    # second write path. The journal row is read once below and reused.
    raw_supplements = config.get("supplements", [])

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

    # Component breakdown for the RingDetail 2×3 card grid. Uses the same
    # duration target the score was computed against, so the breakdown and
    # top-line score stay in sync even after tuning.
    sleep_component_scores = None
    if sleep:
        sleep_component_scores = sleep_component_breakdown(
            total_min=sleep.get("total_min", 0),
            efficiency=sleep.get("efficiency", 0),
            deep_min=sleep.get("deep_min", 0),
            rem_min=sleep.get("rem_min", 0),
            duration_target_min=sleep.get("duration_target_used") or 450,
            continuity_idx=sleep.get("continuity_idx"),
            hr_dip_idx=sleep.get("hr_dip_idx"),
        )

    # Sleep Bank — last 7 nights, exponentially decayed, of (actual − target).
    # Matches Bevel's published formula: 7d window with recent nights weighted
    # higher. Decay factor 0.85/day means today=1.00, yesterday=0.85, day-7≈0.32.
    # Target comes from compute via sleep_bank_delta (which uses fixed target +
    # strainMin per scoring config) so this layer just sums + decays.
    sleep_bank = None
    bank_weighted_sum = 0.0
    samples = 0
    decay = 0.85
    for i in range(7):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        row = get_item(scores_table, {"date": d}) or {}
        delta = row.get("sleep_bank_delta")
        if delta is None:
            continue
        bank_weighted_sum += float(delta) * (decay ** i)
        samples += 1
    if samples:
        bank_min = int(round(bank_weighted_sum))
        if bank_min > 30:
            trend = "surplus"
        elif bank_min < -30:
            trend = "deficit"
        else:
            trend = "balanced"
        sleep_bank = {"minutes": bank_min, "trend": trend, "samples": samples}

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

    planned_workout = _prepare_planned_workout(scores.get("planned_workout"), todays_workouts)

    journal_today, journal_last_night = _journal_for_today(today_dt)
    # Raw tag list from today's journal row, independent of morning-submitted
    # state. Needed for live supplement-chip toggles in Fuel that must know
    # the current tag set even before Mateo does his morning check-in.
    _journal_row = get_item(get_table("JOURNAL_TABLE"), {"date": today_str}) or {}
    today_journal_tags = list(_journal_row.get("tags") or [])
    _today_tag_set = set(today_journal_tags)
    supplements = []
    for s in raw_supplements:
        if not isinstance(s, dict):
            continue
        tag = s.get("tag") or ""
        supplements.append({
            "name": s.get("name", ""),
            "tag": tag,
            "dose": s.get("dose", ""),
            "taken": tag in _today_tag_set if tag else False,
        })

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
            "qualityFlag": sleep.get("quality_flag"),
            "qualityReasons": sleep.get("quality_reasons") or [],
            "confidence": sleep.get("confidence"),
            "arousalCount": sleep.get("arousal_count"),
            "onsetMin": sleep.get("onset_min"),
            "continuityIdx": sleep.get("continuity_idx"),
            "avgHrSleep": sleep.get("avg_hr_sleep"),
            "minHrSleep": sleep.get("min_hr_sleep"),
            "hrDipIdx": sleep.get("hr_dip_idx"),
            "hrDipPct": sleep.get("hr_dip_pct"),
            "durationTargetUsed": sleep.get("duration_target_used"),
            "componentScores": sleep_component_scores,
        },
        "sleepBank": sleep_bank,
        "sleepNeedTonight": scores.get("sleep_need", {}),
        "hrv": scores.get("hrv"),
        "rhr": scores.get("rhr"),
        "resp": scores.get("resp"),
        "spo2": scores.get("spo2"),
        "wristTemp": scores.get("wrist_temp"),
        "recoveryComponents": scores.get("recovery_components"),
        "steps": scores.get("steps") or 0,
        "stepsGoal": 10000,
        "calories": {
            "active": scores.get("active_cal") or 0,
            "resting": 1680,
        },
        "water": water_total,
        "waterGoal": targets.get("water", 100),
        "caffeineMg": caffeine_total,
        "caffeineGoal": targets.get("caffeine", 400),
        "nutritionHasData": nutrition_has_data,
        "recoveryWeek": recovery_week,
        "hrv30d": hrv_30d,
        "stepsWeek": steps_week,
        "mealsToday": meals_today,
        "nutritionTargets": targets,
        "proteinWeek": protein_week,
        "supplements": supplements,
        "coachInsights": coach_insights,
        "plannedWorkout": planned_workout,
        "journal": journal_today,
        "journalLastNight": journal_last_night,
        "journalTagsToday": today_journal_tags,
        "base": {
            "hrv": baselines.get("hrv", 48),
            "rhr": baselines.get("rhr", 64),
            "resp": baselines.get("resp", 14.5),
            "sleepNeed": 7.5,
            "steps": baselines.get("steps", 10000),
        },
    }

    return _resp(200, payload)


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


def _get_nutrition_history(event):
    """Return the last N days (default 7, max 30) of nutrition, newest first.

    Each day carries the same shape `_get_nutrition` returns, minus the
    supplements/targets which are day-invariant and can be pulled from /today.
    Used by the Meal history sheet.
    """
    try:
        days = int((event.get("queryStringParameters") or {}).get("days", "7"))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 30))

    table = get_table("NUTRITION_TABLE")
    today_dt = local_now()
    out = []
    for i in range(days):
        d_dt = today_dt - timedelta(days=i)
        d = d_dt.strftime("%Y-%m-%d")
        items = query_items(table, "date", d) or []
        meals = []
        water_total = 0
        caffeine_total = 0
        totals = {"cal": 0, "p": 0, "c": 0, "f": 0}
        for m in items:
            mid = m.get("meal_id", "")
            if mid.startswith("water_"):
                water_total += m.get("oz", 0)
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
                if m.get("caffeine_mg") is not None:
                    meal["caffeineMg"] = m["caffeine_mg"]
                    caffeine_total += m.get("caffeine_mg", 0)
                meals.append(meal)
                totals["cal"] += meal["cal"]
                totals["p"] += meal["p"]
                totals["c"] += meal["c"]
                totals["f"] += meal["f"]
        meals.sort(key=lambda x: x.get("time") or "")
        out.append({
            "date": d,
            "meals": meals,
            "totals": totals,
            "water": water_total,
            "caffeineMg": caffeine_total,
        })

    return _resp(200, {"days": out})


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
        "hasData": bool(items),
        "caffeineMg": caffeine_total,
        "caffeineGoal": targets.get("caffeine", 400),
        "targets": targets,
    })


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


def _prepare_planned_workout(proposal, todays_workouts):
    """Camel-case the proposal + flip `matched` if today has a logged workout.

    The proposer writes a dict of the shape described in workout_proposer.
    We transform it into the camelCase payload the frontend expects and
    overlay match status from actual workouts logged today.
    """
    if not proposal or not isinstance(proposal, dict):
        return None

    main = proposal.get("main") or {}
    activation = proposal.get("activation")

    def _camel_exercise(e: dict) -> dict:
        return {
            "name": e.get("name", ""),
            "sets": e.get("sets"),
            "reps": e.get("reps"),
            "cue": e.get("cue"),
        }

    camel_activation = None
    if activation:
        camel_activation = {
            "name": activation.get("name", ""),
            "durationMin": activation.get("durationMin") or activation.get("duration_min"),
            "location": activation.get("location", "gym"),
            "exercises": [_camel_exercise(e) for e in (activation.get("exercises") or [])],
        }

    matched = False
    matched_id = None
    if todays_workouts:
        matched = True
        first = todays_workouts[0]
        matched_id = first.get("strava_id") or first.get("workout_id")

    focus_lifts_raw = main.get("focusLifts") or main.get("focus_lifts") or []
    focus_lifts = [
        {
            "name": fl.get("name", ""),
            "canonical": fl.get("canonical", ""),
            "muscleGroup": fl.get("muscleGroup") or fl.get("muscle_group") or "",
            "tag": fl.get("tag", ""),
        }
        for fl in focus_lifts_raw
        if isinstance(fl, dict) and fl.get("name")
    ]

    return {
        "main": {
            "type": main.get("type", "rest"),
            "durationMin": main.get("durationMin") or main.get("duration_min"),
            "intensity": main.get("intensity", "moderate"),
            "reason": main.get("reason", ""),
            "focusMuscleGroups": main.get("focusMuscleGroups") or main.get("focus_muscle_groups") or [],
            "focusLifts": focus_lifts,
        },
        "activation": camel_activation,
        "reason": proposal.get("reason", ""),
        "phase": proposal.get("phase"),
        "generatedAt": proposal.get("generatedAt") or proposal.get("generated_at"),
        "matched": matched,
        "matchedWorkoutId": matched_id,
        "restOverride": bool(proposal.get("restOverride") or proposal.get("rest_override")),
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


def _get_insights():
    """Return both numeric and journal-tag correlations for the Insights modal.

    Numeric rows carry `kind="numeric"` and `tag="numeric:<input>"`; journal
    rows are everything else. We keep the coach's `/api/progress` payload
    free of scatterplot points to hold that endpoint's size down.
    """
    corr_table = get_table("CORRELATIONS_TABLE")

    try:
        resp = corr_table.scan(Limit=500)
        items = resp.get("Items", [])
    except Exception:
        items = []

    def _num(v):
        if v is None:
            return None
        try:
            f = float(v)
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return None

    numeric = []
    journal = []
    computed_at = None
    for it in items:
        kind = it.get("kind")
        if kind == "numeric":
            numeric.append({
                "tag": it.get("tag"),
                "input": (it.get("tag") or "").removeprefix("numeric:"),
                "inputLabel": it.get("input_label"),
                "inputUnits": it.get("input_units"),
                "outcome": it.get("metric"),
                "outcomeLabel": it.get("outcome_label"),
                "outcomeUnits": it.get("outcome_units"),
                "lagDays": _num(it.get("lag_days")) or 0,
                "better": it.get("better"),
                "n": _num(it.get("n")),
                "r": _num(it.get("r")),
                "slope": _num(it.get("slope")),
                "intercept": _num(it.get("intercept")),
                "confidence": it.get("confidence"),
                "insight": it.get("insight"),
                "points": [
                    {"x": _num(p.get("x")), "y": _num(p.get("y")), "date": p.get("date")}
                    for p in (it.get("points") or [])
                    if p.get("x") is not None and p.get("y") is not None
                ],
                "windowDays": _num(it.get("window_days")),
                "computedAt": it.get("computed_at"),
            })
            ca = it.get("computed_at")
            if ca and (computed_at is None or ca > computed_at):
                computed_at = ca
        else:
            journal.append({
                "tag": it.get("tag"),
                "metric": it.get("metric"),
                "effect": _num(it.get("effect")),
                "unit": it.get("unit"),
                "n": _num(it.get("n")),
                "confidence": it.get("confidence"),
                "direction": it.get("direction"),
            })

    # Sort numeric by |r| × confidence rank so the UI can "take the top N".
    conf_rank = {"high": 3, "medium": 2, "low": 1}
    numeric.sort(
        key=lambda c: (conf_rank.get(c.get("confidence"), 0), abs(c.get("r") or 0)),
        reverse=True,
    )
    journal.sort(
        key=lambda c: (conf_rank.get(c.get("confidence"), 0), abs(c.get("effect") or 0)),
        reverse=True,
    )

    return _resp(200, {
        "numeric": numeric,
        "journal": journal,
        "computedAt": computed_at,
    })


_CONVERSATION_IDLE_HOURS = 6


def _get_latest_conversation():
    """Return the resumable thread, or a null conversationId if none/stale."""
    thread = get_latest_conversation()
    if not thread:
        return _resp(200, {"conversationId": None})

    updated = thread.get("updated_at", "")
    try:
        updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except Exception:
        updated_dt = None

    now = datetime.now(timezone.utc)
    if updated_dt and (now - updated_dt) > timedelta(hours=_CONVERSATION_IDLE_HOURS):
        return _resp(200, {"conversationId": None})

    messages = []
    for m in thread.get("messages") or []:
        row = {
            "from": m.get("from"),
            "t": m.get("t", ""),
            "text": m.get("text", ""),
        }
        if m.get("id"):
            row["id"] = m["id"]
        if m.get("imgCount"):
            row["imgCount"] = int(m["imgCount"])
        messages.append(row)

    return _resp(200, {
        "conversationId": thread.get("conversation_id"),
        "messages": messages,
        "summary": thread.get("summary"),
        "messageCount": int(thread.get("message_count") or 0),
        "updatedAt": updated,
    })


def _list_conversations(event):
    """Return recent coach threads with preview text, newest first."""
    try:
        limit = int((event.get("queryStringParameters") or {}).get("limit", "20"))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))

    rows = list_recent_conversations(limit=limit)
    threads = [
        {
            "conversationId": r.get("conversation_id"),
            "updatedAt": r.get("updated_at"),
            "createdAt": r.get("created_at"),
            "messageCount": int(r.get("message_count") or 0),
            "preview": r.get("preview") or "",
        }
        for r in rows
    ]
    return _resp(200, {"threads": threads})


def _get_conversation_by_id(conversation_id):
    """Return a full thread by id, with no idle cutoff."""
    if not conversation_id:
        return _resp(400, {"error": "missing conversation id"})
    thread = load_conversation(conversation_id)
    if not thread:
        return _resp(404, {"error": "not found"})

    messages = []
    for m in thread.get("messages") or []:
        row = {
            "from": m.get("from"),
            "t": m.get("t", ""),
            "text": m.get("text", ""),
        }
        if m.get("id"):
            row["id"] = m["id"]
        if m.get("imgCount"):
            row["imgCount"] = int(m["imgCount"])
        messages.append(row)

    return _resp(200, {
        "conversationId": thread.get("conversation_id"),
        "messages": messages,
        "summary": thread.get("summary"),
        "messageCount": int(thread.get("message_count") or 0),
        "updatedAt": thread.get("updated_at", ""),
    })


def _journal_for_today(today_dt):
    """Return (journalToday, journalLastNight) projection for TodayResponse.

    journalToday is today's row with both morning and evening slots if submitted.
    journalLastNight is the most-recent-past row with any tag or mood for the
    coach card's "last night logged" state. Looks back up to 3 days.
    """
    journal_table = get_table("JOURNAL_TABLE")
    today_str = today_dt.strftime("%Y-%m-%d")

    row = get_item(journal_table, {"date": today_str}) or {}
    today_out = _project_entry(row) if row else None

    last_night = None
    for i in range(1, 4):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        past = get_item(journal_table, {"date": d}) or {}
        if past and (past.get("tags") or past.get("mood") is not None or past.get("morning_text") or past.get("evening_text")):
            last_night = {
                "date": d,
                "tags": past.get("tags") or [],
                "mood": past.get("mood"),
                "stress": past.get("stress"),
                "soreness": past.get("soreness"),
            }
            break

    return today_out, last_night


def _project_entry(row: dict) -> dict:
    """Shape a raw journal row for the frontend JournalEntry type.

    The `morning` object is only returned when Mateo has actually done a
    morning entry — identified by a `morning_saved_at` or `submitted_at`
    timestamp. Rows with only a `tags` list (from the Fuel supplement-chip
    live toggle, which uses slot="tags_only") do NOT count as a submitted
    morning entry; the JournalCard stays in the "pending-morning" state.
    """
    has_morning_submit = bool(row.get("morning_saved_at") or row.get("submitted_at"))
    morning = None
    if has_morning_submit or row.get("mood") is not None or row.get("morning_text"):
        morning = {
            "tags": row.get("tags") or [],
            "mood": row.get("mood"),
            "stress": row.get("stress"),
            "soreness": row.get("soreness"),
            "text": row.get("morning_text") or "",
            "prompts": row.get("morning_prompts") or [],
            "savedAt": row.get("morning_saved_at") or row.get("submitted_at"),
        }
    evening = None
    if row.get("evening_tags") or row.get("evening_mood") is not None or row.get("evening_text") or row.get("evening_saved_at"):
        evening = {
            "tags": row.get("evening_tags") or [],
            "mood": row.get("evening_mood"),
            "stress": row.get("evening_stress"),
            "text": row.get("evening_text") or "",
            "prompts": row.get("evening_prompts") or [],
            "savedAt": row.get("evening_saved_at"),
        }
    notes = []
    for n in (row.get("notes") or []):
        if not isinstance(n, dict) or not n.get("id") or not n.get("text"):
            continue
        out = {
            "id": n.get("id"),
            "at": n.get("at"),
            "text": n.get("text") or "",
            "createdAt": n.get("created_at"),
        }
        if n.get("updated_at"):
            out["updatedAt"] = n["updated_at"]
        if n.get("tags"):
            out["tags"] = list(n["tags"])
        if n.get("mood") is not None:
            out["mood"] = n["mood"]
        if n.get("stress") is not None:
            out["stress"] = n["stress"]
        notes.append(out)
    notes.sort(key=lambda n: n.get("at") or "")
    return {
        "date": row.get("date", ""),
        "submitted": morning is not None,
        "morning": morning,
        "evening": evening,
        "notes": notes,
    }


def _get_journal_history(event):
    """Return the last N days of journal entries, newest first."""
    try:
        limit = int((event.get("queryStringParameters") or {}).get("limit", "30"))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 120))

    journal_table = get_table("JOURNAL_TABLE")
    today = local_now()

    entries = []
    for i in range(limit):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        row = get_item(journal_table, {"date": d})
        if not row:
            continue
        entry = _project_entry(row)
        if entry.get("morning") or entry.get("evening") or entry.get("notes"):
            entries.append(entry)

    return _resp(200, {"entries": entries})


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
