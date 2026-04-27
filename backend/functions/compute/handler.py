"""
Compute Lambda — calculates recovery, strain, sleep scores, baselines, and correlations.

Triggered by:
  - Ingest Lambda (async invoke after data write)
  - EventBridge daily at 2am PT (baselines)
  - EventBridge weekly Sunday 6am PT (correlations)
"""

import json
import os
from datetime import datetime, timedelta, timezone

from shared.db import get_table, put_item, get_item, query_items
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
            return _compute_baselines()
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
