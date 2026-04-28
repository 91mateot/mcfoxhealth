"""
Compute Lambda — calculates recovery, strain, sleep scores, baselines, and correlations.

Triggered by:
  - Ingest Lambda (async invoke after data write)
  - EventBridge daily at 2am PT (baselines)
  - EventBridge weekly Sunday 6am PT (correlations)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.db import get_table, put_item, get_item, query_items

logger = logging.getLogger("compute")
logger.setLevel(logging.INFO)
from shared.scoring import (
    compute_recovery,
    compute_sleep_score,
    compute_strain,
    compute_daily_strain,
    compute_strain_target,
    compute_sleep_need,
    compute_acwr,
    DEFAULT_BASELINES,
)
from shared.timezone import local_now, local_today_str, utc_now


def lambda_handler(event, context):
    if "source" in event and event["source"] == "aws.events":
        rule_arn = event.get("resources", [""])[0]
        if "DailyBaselines" in rule_arn or "daily" in rule_arn.lower():
            _compute_baselines()
            return _compute_lifts()
        if "WeeklyCorrelations" in rule_arn or "weekly" in rule_arn.lower() or "correlation" in rule_arn.lower():
            return _compute_correlations()
        return _compute_baselines()

    action = event.get("action", "compute_day")
    date_str = event.get("date")

    if not date_str:
        date_str = local_today_str()

    if action == "compute_day":
        return _compute_day(date_str)
    elif action == "compute_baselines":
        return _compute_baselines()
    elif action == "compute_correlations":
        return _compute_correlations()
    elif action == "compute_lifts":
        return _compute_lifts()

    return {"error": f"unknown action: {action}"}


def _compute_day(date_str):
    """Compute recovery, sleep score, and strain for a given date."""
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    nutrition_table = get_table("NUTRITION_TABLE")

    metrics = query_items(metrics_table, "date", date_str)
    metric_map = {m["metric_source"]: m for m in metrics}

    baselines = _get_baselines()

    hrv_item = metric_map.get("hrv#hae") or metric_map.get("hrv#manual")
    rhr_item = metric_map.get("rhr#hae") or metric_map.get("rhr#manual")
    sleep_item = metric_map.get("sleep#hae") or metric_map.get("sleep#manual")

    hrv = hrv_item["value"] if hrv_item else None
    rhr = rhr_item["value"] if rhr_item else None

    sleep_min = 0
    sleep_eff = 0
    deep_min = 0
    rem_min = 0
    core_min = 0
    awake_min = 0

    if sleep_item:
        sleep_min = sleep_item.get("total_min", 0)
        sleep_eff = sleep_item.get("efficiency", 0)
        deep_min = sleep_item.get("deep_min", 0)
        rem_min = sleep_item.get("rem_min", 0)
        core_min = sleep_item.get("core_min", 0)
        awake_min = sleep_item.get("awake_min", 0)

    resp_item = metric_map.get("resp#hae") or metric_map.get("resp#manual")
    resp = resp_item["value"] if resp_item else None

    spo2_item = metric_map.get("spo2#hae")
    spo2 = spo2_item["value"] if spo2_item else None

    wrist_temp_item = metric_map.get("wrist_temp#hae")
    wrist_temp = wrist_temp_item["value"] if wrist_temp_item else None

    scoring_config = _get_scoring_config()
    weights = scoring_config.get("recovery_weights") if scoring_config else None

    recovery_result = None
    if hrv is not None or rhr is not None:
        recovery_result = compute_recovery(
            hrv=hrv,
            rhr=rhr,
            sleep_min=sleep_min,
            sleep_efficiency=sleep_eff,
            resp=resp,
            spo2=spo2,
            wrist_temp=wrist_temp,
            baselines=baselines,
            weights=weights,
        )

    sleep_score_val = None
    if sleep_min > 0:
        sleep_score_val = compute_sleep_score(sleep_min, sleep_eff, deep_min, rem_min)

    workouts = query_items(workouts_table, "date", date_str)
    strain_coef = (scoring_config or {}).get("strain_coefficient", 2.0)
    today_trimps = [float(w.get("trimp", 0) or 0) for w in workouts]
    total_strain = compute_daily_strain(today_trimps, coefficient=strain_coef)

    # ACWR — Gabbett 2016 injury-risk ratio. Needs 28-day trimp history.
    acwr_result = _compute_acwr(workouts_table, date_str)

    strain_target = None
    if recovery_result:
        strain_target = compute_strain_target(recovery_result["score"])

    sleep_last_7 = _get_sleep_last_7(date_str)
    sleep_need = compute_sleep_need(
        sleep_last_7=sleep_last_7,
        today_strain=total_strain,
    )

    steps_item = metric_map.get("steps#hae") or metric_map.get("steps#manual")
    active_cal_item = metric_map.get("active_cal#hae") or metric_map.get("active_cal#manual")

    nutrition_items = query_items(nutrition_table, "date", date_str)
    protein_total = sum(m.get("p", 0) for m in nutrition_items if m.get("meal_id", "").startswith("meal_"))
    cal_total = sum(m.get("cal", 0) for m in nutrition_items if m.get("meal_id", "").startswith("meal_"))
    water_total = 0
    for n in nutrition_items:
        if n.get("meal_id", "").startswith("water_"):
            water_total += n.get("oz", 0)

    score_item = {
        "date": date_str,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    if recovery_result:
        score_item["recovery"] = recovery_result["score"]
        score_item["recovery_zone"] = recovery_result["zone"]
        score_item["recovery_components"] = recovery_result["components"]

    if sleep_score_val is not None:
        score_item["sleep_score"] = sleep_score_val

    score_item["strain"] = total_strain
    if strain_target:
        score_item["strain_target"] = strain_target
    score_item["sleep_need"] = sleep_need
    if acwr_result:
        score_item["acwr"] = acwr_result

    score_item["hrv"] = hrv
    score_item["rhr"] = rhr
    score_item["resp"] = resp
    score_item["spo2"] = spo2
    score_item["wrist_temp"] = wrist_temp
    score_item["steps"] = steps_item["value"] if steps_item else None
    score_item["active_cal"] = active_cal_item["value"] if active_cal_item else None
    score_item["protein_total"] = protein_total
    score_item["cal_total"] = cal_total
    score_item["water_oz"] = water_total

    if sleep_item:
        score_item["sleep"] = {
            "total_min": sleep_min,
            "efficiency": sleep_eff,
            "deep_min": deep_min,
            "rem_min": rem_min,
            "core_min": core_min,
            "awake_min": awake_min,
        }

    put_item(scores_table, score_item)

    return {
        "date": date_str,
        "recovery": recovery_result["score"] if recovery_result else None,
        "strain": total_strain,
        "sleep_score": sleep_score_val,
    }


def _compute_baselines():
    """Compute rolling N-day averages and write to baselines table.
    Window length is configurable via user-config scoring.baseline_window_days
    (default 14 — Altini/Oura convention; captures acute training stress without
    smoothing it out like a 30-day window would)."""
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    baselines_table = get_table("BASELINES_TABLE")

    scoring_config = _get_scoring_config()
    window_days = int((scoring_config or {}).get("baseline_window_days", 14))

    today = local_now()
    hrv_vals, rhr_vals, resp_vals = [], [], []
    sleep_vals, steps_vals = [], []
    spo2_vals, wrist_temp_vals = [], []

    for i in range(window_days):
        d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        metrics = query_items(metrics_table, "date", d)
        for m in metrics:
            src = m["metric_source"]
            v = m.get("value")
            if src.startswith("sleep#"):
                total = m.get("total_min", 0) or m.get("asleep_min", 0)
                if total and total > 0:
                    sleep_vals.append(total)
                continue
            if v is None:
                continue
            if src.startswith("hrv#"):
                hrv_vals.append(v)
            elif src.startswith("rhr#"):
                rhr_vals.append(v)
            elif src.startswith("resp#"):
                resp_vals.append(v)
            elif src.startswith("steps#"):
                steps_vals.append(v)
            elif src.startswith("spo2#"):
                spo2_vals.append(v)
            elif src.startswith("wrist_temp#"):
                wrist_temp_vals.append(v)

    def avg1(vals, default):
        return round(sum(vals) / len(vals), 1) if vals else default

    def avgi(vals, default):
        return round(sum(vals) / len(vals)) if vals else default

    baselines = {
        "type": "current",
        "computed_at": today.isoformat(),
        "window_days": window_days,
        "hrv": avg1(hrv_vals, DEFAULT_BASELINES["hrv"]),
        "rhr": avg1(rhr_vals, DEFAULT_BASELINES["rhr"]),
        "resp": avg1(resp_vals, DEFAULT_BASELINES["resp"]),
        "sleep_min": avgi(sleep_vals, DEFAULT_BASELINES["sleep_min"]),
        "steps": avgi(steps_vals, DEFAULT_BASELINES["steps"]),
        "spo2": avg1(spo2_vals, DEFAULT_BASELINES["spo2"]),
        "wrist_temp": avg1(wrist_temp_vals, DEFAULT_BASELINES["wrist_temp"]),
        "sample_counts": {
            "hrv": len(hrv_vals),
            "rhr": len(rhr_vals),
            "resp": len(resp_vals),
            "sleep": len(sleep_vals),
            "steps": len(steps_vals),
            "spo2": len(spo2_vals),
            "wrist_temp": len(wrist_temp_vals),
        },
    }

    put_item(baselines_table, baselines)
    return {"status": "baselines_computed", "baselines": baselines}


def _compute_correlations():
    """Compute journal tag → metric correlations + lift correlations over last 60/90 days."""
    _compute_journal_correlations()
    _compute_lift_correlations()
    return {"status": "correlations_computed"}


def _compute_journal_correlations():
    """Compute journal tag → metric correlations over last 60 days."""
    journal_table = get_table("JOURNAL_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    today = local_now()
    dates = [(today - timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(60)]

    tag_days = {}
    daily_data = {}

    for d in dates:
        journal = get_item(journal_table, {"date": d})
        score = get_item(scores_table, {"date": d})

        if not score:
            continue

        daily_data[d] = {
            "recovery": score.get("recovery"),
            "hrv": score.get("hrv"),
            "rhr": score.get("rhr"),
            "sleep_score": score.get("sleep_score"),
        }

        sleep = score.get("sleep", {})
        total = sleep.get("total_min", 0)
        if total > 0:
            daily_data[d]["deep_pct"] = round(sleep.get("deep_min", 0) / total * 100, 1)
            daily_data[d]["rem_pct"] = round(sleep.get("rem_min", 0) / total * 100, 1)

        if journal and journal.get("tags"):
            for tag in journal["tags"]:
                tag_days.setdefault(tag, []).append(d)

    metric_keys = ["recovery", "hrv", "sleep_score", "deep_pct", "rem_pct", "rhr"]
    metric_better = {
        "recovery": "up", "hrv": "up", "sleep_score": "up",
        "deep_pct": "up", "rem_pct": "up", "rhr": "down",
    }
    metric_units = {
        "recovery": "%", "hrv": "%", "sleep_score": "%",
        "deep_pct": "%", "rem_pct": "%", "rhr": "%",
    }
    metric_labels = {
        "recovery": "Recovery", "hrv": "HRV", "sleep_score": "Sleep",
        "deep_pct": "Deep", "rem_pct": "REM", "rhr": "RHR",
    }

    all_days_set = set(daily_data.keys())
    results = []

    for tag, tagged_dates in tag_days.items():
        if len(tagged_dates) < 5:
            continue

        tagged_set = set(tagged_dates)
        untagged_set = all_days_set - tagged_set

        for metric in metric_keys:
            tagged_vals = [daily_data[d][metric] for d in tagged_dates if d in daily_data and daily_data[d].get(metric) is not None]
            untagged_vals = [daily_data[d][metric] for d in untagged_set if d in daily_data and daily_data[d].get(metric) is not None]

            if len(tagged_vals) < 3 or len(untagged_vals) < 3:
                continue

            tagged_avg = sum(tagged_vals) / len(tagged_vals)
            untagged_avg = sum(untagged_vals) / len(untagged_vals)

            if untagged_avg == 0:
                continue

            effect = round(((tagged_avg - untagged_avg) / untagged_avg) * 100, 1)
            n = len(tagged_vals)

            if n >= 10:
                confidence = "high"
            elif n >= 5:
                confidence = "medium"
            else:
                confidence = "low"

            better = metric_better[metric]
            if better == "up":
                direction = "positive" if effect > 0 else "negative"
            else:
                direction = "positive" if effect < 0 else "negative"

            corr_item = {
                "tag": tag,
                "metric": metric_labels[metric],
                "effect": effect,
                "unit": metric_units[metric],
                "n": n,
                "confidence": confidence,
                "direction": direction,
            }
            put_item(corr_table, corr_item)
            results.append(corr_item)

    return {"status": "correlations_computed", "count": len(results)}


def _get_baselines():
    """Fetch current baselines or return defaults."""
    try:
        table = get_table("BASELINES_TABLE")
        item = get_item(table, {"type": "current"})
        if item:
            return {
                "hrv": item.get("hrv", DEFAULT_BASELINES["hrv"]),
                "rhr": item.get("rhr", DEFAULT_BASELINES["rhr"]),
                "resp": item.get("resp", DEFAULT_BASELINES["resp"]),
                "sleep_min": item.get("sleep_min", DEFAULT_BASELINES["sleep_min"]),
                "steps": item.get("steps", DEFAULT_BASELINES["steps"]),
                "spo2": item.get("spo2", DEFAULT_BASELINES["spo2"]),
                "wrist_temp": item.get("wrist_temp", DEFAULT_BASELINES["wrist_temp"]),
            }
    except Exception:
        pass
    return DEFAULT_BASELINES


def _get_sleep_last_7(date_str):
    """Get sleep durations for the 7 nights before date_str."""
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    vals = []
    for i in range(1, 8):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(metrics_table, "date", d, sk_name="metric_source", sk_begins="sleep#")
        for item in items:
            total = item.get("total_min", 0)
            if total > 0:
                vals.append(total)
                break
    return vals


# ─── Scoring config loader (hot-swappable via user-config) ──────────────

_scoring_config_cache: dict = {"ts": 0, "value": None}
_SCORING_CONFIG_TTL = 300  # seconds


def _get_scoring_config() -> dict:
    """Load scoring weights from fitness-user-config (PK key='scoring').
    Cached per-container for 5 min. Missing row → returns empty dict, caller
    uses defaults from shared.scoring."""
    import time
    now = int(time.time())
    if _scoring_config_cache["value"] is not None and now - _scoring_config_cache["ts"] < _SCORING_CONFIG_TTL:
        return _scoring_config_cache["value"]
    try:
        config_table = get_table("USER_CONFIG_TABLE")
        item = get_item(config_table, {"key": "scoring"}) or {}
    except Exception:
        item = {}
    _scoring_config_cache["value"] = item
    _scoring_config_cache["ts"] = now
    return item


def _compute_acwr(workouts_table, date_str: str):
    """Pull TRIMP totals from the last 28 days of workouts and call compute_acwr."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    daily_trimps = {}
    for i in range(28):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        day_workouts = query_items(workouts_table, "date", d)
        total = sum(float(w.get("trimp", 0) or 0) for w in day_workouts)
        daily_trimps[d] = total
    return compute_acwr(daily_trimps)


# ── Lift compute (PRs, stalls, e1RM, weekly volume) ──────────────────────


def _epley_e1rm(weight: float, reps: int) -> float:
    """Epley formula for estimated 1-rep max.
    e1RM = weight * (1 + reps/30). Good for 2-10 reps.
    reps=1 returns weight unchanged. reps=0 returns 0 (no work done)."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return round(float(weight), 1)
    return round(float(weight) * (1.0 + reps / 30.0), 1)


def _scan_exercise_history(exercises_table, canonical: str, days: int = 180) -> list:
    """Return all sessions for a canonical exercise in the last `days`, sorted
    by date ascending. ExercisesTable is (PK=canonical, SK=date) so this is a
    single Query."""
    rows = query_items(exercises_table, "canonical", canonical) or []
    cutoff = (local_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("date", "") >= cutoff]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def _session_top_e1rm(row: dict) -> float:
    """Best Epley-e1RM across all working sets in a session."""
    best = 0.0
    for s in row.get("sets") or []:
        if s.get("warmup"):
            continue
        w = float(s.get("weight") or 0)
        r = int(s.get("reps") or 0)
        e = _epley_e1rm(w, r)
        if e > best:
            best = e
    return best


def _detect_prs(history: list) -> dict[str, dict]:
    """For each session in history, decide whether it set a PR vs all prior
    sessions. Returns {date: {weight: bool, e1rm: bool, volume: bool}}."""
    out = {}
    best_weight = 0.0
    best_e1rm = 0.0
    best_volume = 0.0
    for row in history:
        top_weight = float(row.get("top_weight") or 0)
        top_e1rm = _session_top_e1rm(row)
        volume = float(row.get("working_volume") or 0)

        flags = {
            "weight": top_weight > best_weight,
            "e1rm": top_e1rm > best_e1rm,
            "volume": volume > best_volume,
        }
        out[row["date"]] = flags

        if top_weight > best_weight:
            best_weight = top_weight
        if top_e1rm > best_e1rm:
            best_e1rm = top_e1rm
        if volume > best_volume:
            best_volume = volume
    return out


def _detect_stall(history: list, min_sessions: int = 3) -> Optional[dict]:
    """A stall = last `min_sessions` sessions have top_weight equal or
    decreasing with similar rep range (±2). Returns dict or None."""
    if len(history) < min_sessions:
        return None
    tail = history[-min_sessions:]
    weights = [float(r.get("top_weight") or 0) for r in tail]
    reps_at = [int(r.get("top_reps_at_top_weight") or 0) for r in tail]
    if any(w == 0 for w in weights):
        return None
    # No progression = max weight in tail is not strictly greater than first.
    if max(weights) > weights[0]:
        return None
    # Rep range similar.
    if max(reps_at) - min(reps_at) > 2:
        return None
    return {
        "weight": weights[-1],
        "reps": reps_at[-1],
        "sessions": min_sessions,
        "since_date": tail[0]["date"],
    }


def _compute_lifts():
    """Daily lift roll-up:
    - For every exercise that has a session in the last 7 days, recompute PR
      flags across its full 180-day history and write back to each row.
    - Detect stalls for every exercise with ≥3 recent sessions; store to user_config.
    - Roll per-muscle-group weekly volume into DAILY_SCORES_TABLE (week_start key)."""
    exercises_table = get_table("EXERCISES_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")

    # Find exercises touched in the last 7 days. We don't have a GSI, so scan
    # the recent window via per-day queries on WORKOUTS_TABLE would be cleaner,
    # but scanning the small ExercisesTable once a day is acceptable at this scale.
    try:
        resp = exercises_table.scan(Limit=500)
        all_rows = resp.get("Items", [])
    except Exception:
        logger.exception("ExercisesTable scan failed")
        return {"status": "lifts_compute_failed"}

    recent_cutoff = (local_now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_canonicals = sorted({r["canonical"] for r in all_rows if r.get("date", "") >= recent_cutoff and r.get("canonical")})

    stalls = []
    pr_count = 0

    for canonical in recent_canonicals:
        history = _scan_exercise_history(exercises_table, canonical, days=180)
        if not history:
            continue
        pr_flags = _detect_prs(history)

        # Write PR flags and e1RM back to each session row.
        for row in history:
            flags = pr_flags.get(row["date"], {})
            e1rm = _session_top_e1rm(row)
            updated = {
                **row,
                "e1rm": e1rm,
                "pr": {
                    "weight": bool(flags.get("weight")),
                    "e1rm": bool(flags.get("e1rm")),
                    "volume": bool(flags.get("volume")),
                },
            }
            put_item(exercises_table, updated)
            if any(flags.values()):
                pr_count += 1

        stall = _detect_stall(history)
        if stall:
            stalls.append({
                "canonical": canonical,
                "name": history[-1].get("name", canonical),
                "muscle_group": history[-1].get("muscle_group", "other"),
                **stall,
            })

    # Persist stalls list to user-config as a single row.
    put_item(config_table, {
        "key": "lift_stalls",
        "stalls": stalls,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    })

    # Weekly volume per muscle group (Monday-based week).
    today_local = local_now()
    week_start = today_local - timedelta(days=today_local.weekday())  # Monday
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = (week_start + timedelta(days=6)).strftime("%Y-%m-%d")

    volume_by_mg: dict = {}
    sessions_by_mg: dict = {}
    for row in all_rows:
        d = row.get("date", "")
        if not (week_start_str <= d <= week_end_str):
            continue
        mg = row.get("muscle_group", "other")
        vol = float(row.get("working_volume") or 0)
        volume_by_mg[mg] = volume_by_mg.get(mg, 0) + vol
        sessions_by_mg.setdefault(mg, set()).add(d)

    volume_row = {
        "date": f"week_{week_start_str}",
        "week_start": week_start_str,
        "week_end": week_end_str,
        "volume_by_muscle_group": {k: round(v, 1) for k, v in volume_by_mg.items()},
        "sessions_by_muscle_group": {k: len(v) for k, v in sessions_by_mg.items()},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(scores_table, volume_row)

    return {
        "status": "lifts_computed",
        "exercises_touched": len(recent_canonicals),
        "prs_tagged": pr_count,
        "stalls": len(stalls),
        "volume_by_muscle_group": volume_row["volume_by_muscle_group"],
    }


# ── Lift correlations (Sunday) ───────────────────────────────────────────


def _compute_lift_correlations():
    """Correlate lift signals with readiness metrics.

    1. For each exercise with ≥10 sessions: compare HRV/sleep on PR-session
       mornings vs non-PR mornings. Write CorrelationsTable rows tagged
       "exercise:<canonical>".
    2. back_flare journal tag: check whether loaded-lower-body exercises
       (squat, deadlift, rdl, leg_press, front_squat) in the prior 3 days
       precede the flare. Write with tag "back_flare", metric
       "Loaded lower body 3d prior".
    """
    exercises_table = get_table("EXERCISES_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    journal_table = get_table("JOURNAL_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    try:
        resp = exercises_table.scan(Limit=1000)
        all_rows = resp.get("Items", [])
    except Exception:
        logger.exception("ExercisesTable scan failed")
        return

    # Group by canonical.
    by_canonical: dict = {}
    for r in all_rows:
        c = r.get("canonical")
        if c:
            by_canonical.setdefault(c, []).append(r)

    for canonical, history in by_canonical.items():
        if len(history) < 10:
            continue
        history.sort(key=lambda r: r.get("date", ""))

        pr_dates = [r["date"] for r in history if (r.get("pr") or {}).get("e1rm")]
        nonpr_dates = [r["date"] for r in history if not (r.get("pr") or {}).get("e1rm")]
        if len(pr_dates) < 3 or len(nonpr_dates) < 3:
            continue

        for metric_key, metric_label, better in [
            ("hrv", "HRV", "up"),
            ("recovery", "Recovery", "up"),
            ("sleep_score", "Sleep", "up"),
        ]:
            pr_vals = []
            for d in pr_dates:
                s = get_item(scores_table, {"date": d})
                if s and s.get(metric_key) is not None:
                    pr_vals.append(float(s[metric_key]))
            nonpr_vals = []
            for d in nonpr_dates:
                s = get_item(scores_table, {"date": d})
                if s and s.get(metric_key) is not None:
                    nonpr_vals.append(float(s[metric_key]))
            if len(pr_vals) < 3 or len(nonpr_vals) < 3:
                continue
            pr_avg = sum(pr_vals) / len(pr_vals)
            nonpr_avg = sum(nonpr_vals) / len(nonpr_vals)
            if nonpr_avg == 0:
                continue
            effect = round(((pr_avg - nonpr_avg) / nonpr_avg) * 100, 1)
            n = len(pr_vals)
            confidence = "high" if n >= 10 else "medium" if n >= 5 else "low"
            direction = "positive" if (effect > 0) == (better == "up") else "negative"
            put_item(corr_table, {
                "tag": f"exercise:{canonical}",
                "metric": metric_label,
                "effect": effect,
                "unit": "%",
                "n": n,
                "confidence": confidence,
                "direction": direction,
            })

    # back_flare vs loaded lower-body prior 3 days.
    loaded_lower = {"back_squat", "front_squat", "deadlift", "romanian_deadlift", "leg_press"}
    today = local_now()
    flare_dates = []
    nonflare_dates = []
    for i in range(90):
        d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        j = get_item(journal_table, {"date": d})
        if not j:
            continue
        tags = j.get("tags") or []
        if "back_flare" in tags:
            flare_dates.append(d)
        else:
            nonflare_dates.append(d)

    if len(flare_dates) >= 3:
        def loaded_in_prior_3(date_str: str) -> bool:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            for delta in range(1, 4):
                d_prior = (dt - timedelta(days=delta)).strftime("%Y-%m-%d")
                for canonical in loaded_lower:
                    row = get_item(exercises_table, {"canonical": canonical, "date": d_prior})
                    if row:
                        return True
            return False

        flare_loaded = sum(1 for d in flare_dates if loaded_in_prior_3(d))
        nonflare_loaded = sum(1 for d in nonflare_dates if loaded_in_prior_3(d))
        flare_rate = flare_loaded / len(flare_dates)
        nonflare_rate = nonflare_loaded / max(1, len(nonflare_dates))
        if nonflare_rate > 0:
            effect = round(((flare_rate - nonflare_rate) / max(nonflare_rate, 0.01)) * 100, 1)
        else:
            effect = round(flare_rate * 100, 1)
        n = len(flare_dates)
        confidence = "high" if n >= 10 else "medium" if n >= 5 else "low"
        direction = "negative"  # loaded-lower-body → flare is always a bad association
        put_item(corr_table, {
            "tag": "back_flare",
            "metric": "Loaded lower body 3d prior",
            "effect": effect,
            "unit": "%",
            "n": n,
            "confidence": confidence,
            "direction": direction,
        })
