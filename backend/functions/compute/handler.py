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

from shared.db import get_table, put_item, get_item, query_items
from shared.insight_templates import PAIRS as NUMERIC_PAIRS, confidence_tier, render_insight
from shared.pearson import linreg, pearson_r
from shared.lift_compute import (
    detect_prs as _detect_prs_shared,
    detect_stall as _detect_stall_shared,
    epley_e1rm as _epley_e1rm_shared,
    recompute_prs_for_canonicals,
    recompute_weekly_volume,
    scan_exercise_history as _scan_history_shared,
    session_top_e1rm as _session_top_e1rm_shared,
)

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
from shared.workout_proposer import propose_for_date as _propose_workout_for_date


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
    elif action == "backfill_caffeine":
        return _backfill_caffeine_totals(int(event.get("days", 90)))

    return {"error": f"unknown action: {action}"}


def _backfill_caffeine_totals(days: int):
    """Walk the last N days of NutritionTable and populate DailyScoresTable.caffeine_total.

    One-shot migration: before this change, caffeine wasn't aggregated daily, so
    existing daily-score rows lack the field that numeric correlations read.
    Safe to rerun (upserts).
    """
    nutrition_table = get_table("NUTRITION_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    today = local_now()

    updated = 0
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        meals = query_items(nutrition_table, "date", d)
        caffeine = sum(
            m.get("caffeine_mg", 0) or 0
            for m in meals
            if m.get("meal_id", "").startswith("meal_")
        )
        if caffeine <= 0:
            continue
        existing = get_item(scores_table, {"date": d}) or {"date": d}
        existing["caffeine_total"] = caffeine
        put_item(scores_table, existing)
        updated += 1
    return {"status": "caffeine_backfilled", "days_updated": updated}


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

    sleep_history = _get_sleep_history(date_str, days=30)
    # Align recency-sensitive inputs: last-7 durations + wake hours from the
    # first 7 rows of the 30-day history, since it's ordered most-recent-first.
    sleep_last_7 = [h["totalMin"] for h in sleep_history[:7]]
    wake_hours_last_7 = [h["wakeHour"] for h in sleep_history[:7] if h.get("wakeHour") is not None]
    sleep_last_30 = [h["totalMin"] for h in sleep_history]
    sleep_need = compute_sleep_need(
        sleep_last_30=sleep_last_30,
        sleep_last_7=sleep_last_7,
        wake_hours_last_7=wake_hours_last_7,
        today_strain=total_strain,
    )

    steps_item = metric_map.get("steps#hae") or metric_map.get("steps#manual")
    active_cal_item = metric_map.get("active_cal#hae") or metric_map.get("active_cal#manual")

    nutrition_items = query_items(nutrition_table, "date", date_str)
    protein_total = sum(m.get("p", 0) for m in nutrition_items if m.get("meal_id", "").startswith("meal_"))
    cal_total = sum(m.get("cal", 0) for m in nutrition_items if m.get("meal_id", "").startswith("meal_"))
    caffeine_total = sum(m.get("caffeine_mg", 0) or 0 for m in nutrition_items if m.get("meal_id", "").startswith("meal_"))
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
        score_item["recovery_weights_used"] = recovery_result.get("weights_used") or {}

    if sleep_score_val is not None:
        score_item["sleep_score"] = sleep_score_val

    score_item["strain"] = total_strain
    score_item["strain_coefficient"] = strain_coef
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
    score_item["caffeine_total"] = caffeine_total

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

    # Planned workout for the day. Runs after the score write so the
    # proposer sees fresh recovery_zone. Isolated try/except so a
    # proposer bug never breaks the daily compute.
    try:
        existing = get_item(scores_table, {"date": date_str}) or {}
        existing_plan = existing.get("planned_workout") or {}
        # Respect a manual rest-day override — don't let the cron clobber
        # a recovery day Mateo set explicitly.
        if existing_plan.get("restOverride") or existing_plan.get("rest_override"):
            score_item["planned_workout"] = existing_plan
        else:
            score_item["planned_workout"] = _propose_workout_for_date(date_str)
        put_item(scores_table, score_item)
    except Exception:
        logger.exception("propose_for_date failed for %s", date_str)

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
    """Compute journal tag → metric correlations + lift correlations + numeric correlations."""
    _compute_journal_correlations()
    _compute_lift_correlations()
    _compute_numeric_correlations()
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


_NUMERIC_WINDOW_DAYS = 60
_NUMERIC_MIN_N = 10


def _compute_numeric_correlations():
    """Regress numeric daily inputs against outcomes (Pearson r + linear fit).

    Writes one row per pair to CorrelationsTable with `kind="numeric"` and a
    `tag` prefixed `numeric:` so existing journal-tag consumers (coach prompt,
    `/api/progress`) skip these rows cleanly.
    """
    scores_table = get_table("DAILY_SCORES_TABLE")
    corr_table = get_table("CORRELATIONS_TABLE")

    today = local_now()
    # Need one extra day so next-day (lag=1) pairs at the edge can resolve.
    dates = [(today - timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(_NUMERIC_WINDOW_DAYS + 1)]

    by_date: dict[str, dict] = {}
    for d in dates:
        s = get_item(scores_table, {"date": d})
        if not s:
            continue
        sleep = s.get("sleep") or {}
        total_min = float(sleep.get("total_min") or 0)
        entry = {
            "caffeine_mg": _num(s.get("caffeine_total")),
            "protein_total": _num(s.get("protein_total")),
            "water_oz": _num(s.get("water_oz")),
            "strain": _num(s.get("strain")),
            "sleep_hours": total_min / 60 if total_min > 0 else None,
            "sleep_score": _num(s.get("sleep_score")),
            "deep_pct": (float(sleep.get("deep_min") or 0) / total_min * 100) if total_min > 0 else None,
            "rem_pct": (float(sleep.get("rem_min") or 0) / total_min * 100) if total_min > 0 else None,
            "hrv": _num(s.get("hrv")),
            "recovery": _num(s.get("recovery")),
        }
        by_date[d] = entry

    computed_at = utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")
    results: list[dict] = []

    for pair in NUMERIC_PAIRS:
        input_key = pair["input"]
        outcome_key = pair["outcome"]
        lag = int(pair.get("lag_days", 0))

        points: list[dict] = []
        for d in sorted(by_date.keys()):
            input_row = by_date.get(d)
            if not input_row:
                continue
            x = input_row.get(input_key)
            if x is None:
                continue

            # Resolve the outcome date based on lag.
            out_date = d
            if lag:
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag)
                    out_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    continue
            out_row = by_date.get(out_date)
            if not out_row:
                continue
            y = out_row.get(outcome_key)
            if y is None:
                continue

            points.append({"x": round(float(x), 3), "y": round(float(y), 3), "date": d})

        if len(points) < _NUMERIC_MIN_N:
            continue

        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        r = pearson_r(xs, ys)
        fit = linreg(xs, ys)
        if r is None or fit is None:
            continue
        slope, intercept = fit

        n = len(points)
        x_mean = sum(xs) / n
        x_var = sum((x - x_mean) ** 2 for x in xs) / n
        x_std = x_var**0.5

        insight = render_insight(pair, r=r, slope=slope, n=n, x_mean=x_mean, x_std=x_std)

        corr_item = {
            "tag": f"numeric:{input_key}",
            "metric": outcome_key,
            "kind": "numeric",
            "input_label": pair["input_label"],
            "input_units": pair["input_units"],
            "outcome_label": pair["outcome_label"],
            "outcome_units": pair["outcome_units"],
            "lag_days": lag,
            "better": pair["better"],
            "n": n,
            "r": round(r, 4),
            "slope": round(slope, 6),
            "intercept": round(intercept, 4),
            "confidence": confidence_tier(n, abs(r)),
            "insight": insight,
            "points": points,
            "window_days": _NUMERIC_WINDOW_DAYS,
            "computed_at": computed_at,
        }
        put_item(corr_table, corr_item)
        results.append(corr_item)

    return {"status": "numeric_correlations_computed", "count": len(results)}


def _num(v):
    """Coerce DynamoDB numeric (int/Decimal/float) to float, skip None/0-like None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


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


def _get_sleep_history(date_str, days=30):
    """Sleep rows for the N nights before date_str, most-recent first.

    Each row: {date, totalMin, wakeHour}. Skips nights without data.
    wakeHour is parsed from the sleep `end` timestamp (local time) when
    available; otherwise None.
    """
    metrics_table = get_table("HEALTH_METRICS_TABLE")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    rows = []
    for i in range(1, days + 1):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        items = query_items(metrics_table, "date", d, sk_name="metric_source", sk_begins="sleep#")
        for item in items:
            total = item.get("total_min", 0)
            if total and total > 0:
                rows.append({
                    "date": d,
                    "totalMin": int(total),
                    "wakeHour": _parse_wake_hour(item.get("end") or item.get("sleep_end")),
                })
                break
    return rows


def _parse_wake_hour(ts):
    """Extract decimal hour-of-day (local) from a timestamp string."""
    if not ts:
        return None
    try:
        # Accept both "2026-04-30 09:07:13 -0700" and ISO formats.
        s = str(ts).strip()
        # Normalize the HealthAutoExport format to ISO-ish for fromisoformat.
        # "2026-04-30 09:07:13 -0700" → "2026-04-30T09:07:13-07:00"
        if " " in s and "T" not in s:
            parts = s.split(" ")
            date_part = parts[0]
            time_part = parts[1]
            tz_part = ""
            if len(parts) >= 3:
                tz = parts[2]
                # "-0700" → "-07:00"
                if len(tz) == 5 and tz[0] in "+-":
                    tz_part = tz[:3] + ":" + tz[3:]
                else:
                    tz_part = tz
            s = f"{date_part}T{time_part}{tz_part}"
        parsed = datetime.fromisoformat(s)
        return parsed.hour + parsed.minute / 60
    except Exception:
        return None


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
#
# Pure helpers live in shared.lift_compute so workout_service can reuse them
# for immediate PR recompute at annotate-time. This handler is the daily
# scheduled roll-up.


def _compute_lifts():
    """Daily lift roll-up:
    - For EVERY canonical exercise with any history (not just recent dates),
      recompute PR flags across its full 180-day history and write back.
      Scanning everything — not just the last-7-days session-date window —
      is critical for retroactive annotations: if Mateo annotates a 2-week-
      old workout today, its canonical may have a session-date outside any
      recent window, but its PR/e1RM status needs to be re-derived in the
      context of older sessions it now competes against.
    - Detect stalls for every exercise with ≥3 sessions; store to user_config.
    - Roll per-muscle-group weekly volume into DAILY_SCORES_TABLE (week_start key)."""
    exercises_table = get_table("EXERCISES_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")

    try:
        resp = exercises_table.scan(Limit=2000)
        all_rows = resp.get("Items", [])
    except Exception:
        logger.exception("ExercisesTable scan failed")
        return {"status": "lifts_compute_failed"}

    all_canonicals = sorted({r["canonical"] for r in all_rows if r.get("canonical")})

    stalls = []
    pr_count = 0

    for canonical in all_canonicals:
        history = _scan_history_shared(exercises_table, canonical, days=180)
        if not history:
            continue
        pr_flags = _detect_prs_shared(history)

        # Write PR flags and e1RM back to each session row.
        for row in history:
            flags = pr_flags.get(row["date"], {})
            e1rm = _session_top_e1rm_shared(row)
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

        stall = _detect_stall_shared(history)
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

    # Weekly per-muscle-group volume — delegated to the shared helper so
    # annotate_workout can call the same function inline and keep Progress
    # Strength fresh without waiting for tomorrow's cron.
    volume_row = recompute_weekly_volume()

    return {
        "status": "lifts_computed",
        "exercises_touched": len(all_canonicals),
        "prs_tagged": pr_count,
        "stalls": len(stalls),
        "volume_by_muscle_group": volume_row.get("volume_by_muscle_group", {}),
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
