"""
Ingest Lambda — handles incoming health data from three sources:
  POST /ingest/health   — HealthAutoExport (Apple Health)
  POST /ingest/withings  — Withings webhook notifications
  POST /ingest/strava    — Strava webhook events
  GET  /ingest/strava    — Strava webhook verification
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3

from shared.db import get_table, put_item, query_items
from shared.scoring import compute_trimp, compute_strain, classify_hr_zone, estimate_strain_simple, HR_ZONES, MAX_HR
from shared.timezone import local_today_str

secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")

COMPUTE_FN = os.environ.get("COMPUTE_FUNCTION_NAME", "")

WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# HAE metric-name → (metric_source, unit, aggregation kind)
# Aggregation kinds:
#   "avg"     — daily mean (HRV, RHR, resp, SpO2, temperature)
#   "sum_int" — daily total as integer (steps, kcal, minutes, counts)
#   "sum"     — daily total as float (distances, fractional quantities)
#   "last"    — keep the latest value of the day (weight, BMI — not cumulative)
#   "triple"  — expand into min/avg/max rows (heart_rate)
HAE_NAME_MAP = {
    # ── Scoring-critical vitals ──
    "heart rate variability": ("hrv#hae", "ms", "avg"),
    "heartratevariability":   ("hrv#hae", "ms", "avg"),
    "hrv":                    ("hrv#hae", "ms", "avg"),
    "resting heart rate":     ("rhr#hae", "bpm", "avg"),
    "restingheartrate":       ("rhr#hae", "bpm", "avg"),
    "respiratory rate":       ("resp#hae", "br/min", "avg"),
    "respiratoryrate":        ("resp#hae", "br/min", "avg"),
    "blood oxygen saturation":      ("spo2#hae", "%", "avg"),
    "bloodoxygensaturation":        ("spo2#hae", "%", "avg"),
    "oxygen saturation":            ("spo2#hae", "%", "avg"),
    "oxygensaturation":             ("spo2#hae", "%", "avg"),
    "apple sleeping wrist temperature": ("wrist_temp#hae", "degC", "avg"),
    "applesleepingwristtemperature":    ("wrist_temp#hae", "degC", "avg"),
    "wrist temperature":                ("wrist_temp#hae", "degC", "avg"),
    "wristtemperature":                 ("wrist_temp#hae", "degC", "avg"),
    "body temperature":                 ("wrist_temp#hae", "degC", "avg"),
    "bodytemperature":                  ("wrist_temp#hae", "degC", "avg"),

    # ── Daily heart-rate (triple expansion) ──
    "heart rate":             ("hr#hae", "bpm", "triple"),
    "heartrate":              ("hr#hae", "bpm", "triple"),

    # ── Activity ──
    "step count":             ("steps#hae", "count", "sum_int"),
    "steps":                  ("steps#hae", "count", "sum_int"),
    "stepcount":              ("steps#hae", "count", "sum_int"),
    "active energy":          ("active_cal#hae", "kcal", "sum_int"),
    "active energy burned":   ("active_cal#hae", "kcal", "sum_int"),
    "activeenergyburned":     ("active_cal#hae", "kcal", "sum_int"),
    "basal energy burned":    ("basal_cal#hae", "kcal", "sum_int"),
    "basalenergyburned":      ("basal_cal#hae", "kcal", "sum_int"),
    "basal energy":           ("basal_cal#hae", "kcal", "sum_int"),
    "apple exercise time":    ("exercise_min#hae", "min", "sum_int"),
    "appleexercisetime":      ("exercise_min#hae", "min", "sum_int"),
    "exercise time":          ("exercise_min#hae", "min", "sum_int"),
    "exercise minutes":       ("exercise_min#hae", "min", "sum_int"),
    "apple stand hour":       ("stand_hours#hae", "count", "sum_int"),
    "applestandhour":         ("stand_hours#hae", "count", "sum_int"),
    "apple stand time":       ("stand_min#hae", "min", "sum_int"),
    "applestandtime":         ("stand_min#hae", "min", "sum_int"),
    "stand hours":            ("stand_hours#hae", "count", "sum_int"),
    "flights climbed":        ("flights#hae", "count", "sum_int"),
    "flightsclimbed":         ("flights#hae", "count", "sum_int"),
    "walking heart rate average": ("walk_hr#hae", "bpm", "avg"),
    "walkingheartrateaverage":    ("walk_hr#hae", "bpm", "avg"),
    "heart rate recovery one minute": ("hr_recovery#hae", "bpm/min", "avg"),
    "heartraterecoveryone minute":    ("hr_recovery#hae", "bpm/min", "avg"),
    "heart rate recovery":            ("hr_recovery#hae", "bpm/min", "avg"),

    # ── Body composition (Apple Health, may overlap with Withings) ──
    "weight body mass":       ("weight_apple#hae", "lbs", "last"),
    "weightbodymass":         ("weight_apple#hae", "lbs", "last"),
    "weight & body mass":     ("weight_apple#hae", "lbs", "last"),
    "weight":                 ("weight_apple#hae", "lbs", "last"),
    "body mass index":        ("bmi#hae", "kg/m2", "last"),
    "bodymassindex":          ("bmi#hae", "kg/m2", "last"),
    "bmi":                    ("bmi#hae", "kg/m2", "last"),

    # ── Wellness enrichment ──
    "mindful minutes":        ("mindful_min#hae", "min", "sum_int"),
    "mindfulminutes":         ("mindful_min#hae", "min", "sum_int"),
}


def lambda_handler(event, context):
    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if "/ingest/health" in path:
        return _handle_health(event)
    if "/ingest/withings" in path:
        return _handle_withings(event)
    if "/ingest/strava" in path:
        if method == "GET":
            return _handle_strava_verify(event)
        return _handle_strava(event)

    return _resp(404, {"error": "not found"})


def _handle_health(event):
    """Process HealthAutoExport JSON payload."""
    api_key = event.get("headers", {}).get("x-api-key", "")
    if not _verify_api_key(api_key):
        return _resp(401, {"error": "unauthorized"})

    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    # HAE v2 shape: {"data": {"metrics": [{"name": "...", "data": [...]}]}}
    # HAE v1 shape: {"data": [{"name": "...", "data": [...]}]}
    data_field = body.get("data")
    data_list = None
    if isinstance(data_field, list):
        data_list = data_field
    elif isinstance(data_field, dict):
        inner = data_field.get("metrics")
        if isinstance(inner, list):
            data_list = inner
    if data_list and isinstance(data_list[0], dict) and "name" in data_list[0]:
        return _handle_hae_metrics_array(data_list)

    # Fallback: legacy dict shape (top-level keys per metric)
    table = get_table("HEALTH_METRICS_TABLE")
    metrics = body.get("data", body)
    date_str = _extract_date(metrics)

    if not date_str:
        return _resp(400, {"error": "no date found in payload"})

    items_written = 0

    if "heart_rate_variability" in metrics or "heartRateVariability" in metrics:
        hrv_data = metrics.get("heart_rate_variability") or metrics.get("heartRateVariability")
        hrv_val = _extract_value(hrv_data)
        if hrv_val is not None:
            put_item(table, {
                "date": date_str,
                "metric_source": "hrv#hae",
                "value": hrv_val,
                "unit": "ms",
                "ingested_at": _now_iso(),
            })
            items_written += 1

    if "resting_heart_rate" in metrics or "restingHeartRate" in metrics:
        rhr_data = metrics.get("resting_heart_rate") or metrics.get("restingHeartRate")
        rhr_val = _extract_value(rhr_data)
        if rhr_val is not None:
            put_item(table, {
                "date": date_str,
                "metric_source": "rhr#hae",
                "value": rhr_val,
                "unit": "bpm",
                "ingested_at": _now_iso(),
            })
            items_written += 1

    sleep = metrics.get("sleepAnalysis") or metrics.get("sleep_analysis") or metrics.get("sleep")
    if sleep:
        sleep_item = _normalize_sleep(sleep, date_str)
        if sleep_item:
            put_item(table, sleep_item)
            items_written += 1

    if "steps" in metrics or "stepCount" in metrics:
        steps_data = metrics.get("steps") or metrics.get("stepCount")
        steps_val = _extract_value(steps_data)
        if steps_val is not None:
            put_item(table, {
                "date": date_str,
                "metric_source": "steps#hae",
                "value": int(steps_val),
                "unit": "count",
                "ingested_at": _now_iso(),
            })
            items_written += 1

    if "active_energy" in metrics or "activeEnergyBurned" in metrics:
        cal_data = metrics.get("active_energy") or metrics.get("activeEnergyBurned")
        cal_val = _extract_value(cal_data)
        if cal_val is not None:
            put_item(table, {
                "date": date_str,
                "metric_source": "active_cal#hae",
                "value": round(cal_val),
                "unit": "kcal",
                "ingested_at": _now_iso(),
            })
            items_written += 1

    _trigger_compute(date_str)

    return _resp(200, {"date": date_str, "items_written": items_written})


def _handle_hae_metrics_array(data_list):
    """Process HAE's real payload shape: top-level {data: [{name, units, data: [{qty|value, date|startDate, ...}]}]}.

    Groups each metric's points by date and writes one health-metrics row per (date, metric).
    Aggregates: avg for vitals (HRV/RHR/resp), sum for cumulative (steps/cal).
    """
    table = get_table("HEALTH_METRICS_TABLE")
    items_written = 0
    latest_date = None

    # Diagnostic: log a compact summary so we can tell empty pushes from
    # real ones without dumping full payloads (PII/token cost).
    _log_hae_summary(data_list)

    for entry in data_list:
        raw_name = (entry.get("name") or "").strip().lower()
        # HAE v2 uses snake_case (heart_rate_variability); v1 docs showed title case.
        # Map by both forms — with and without separators.
        name = raw_name
        name_no_sep = raw_name.replace("_", "").replace(" ", "").replace("-", "")
        points = entry.get("data") or []

        # Sleep Analysis — two HAE shapes:
        #   Aggregated (one record per night): {date, totalSleep, asleep, core, deep, rem, inBed, ...} in HOURS
        #   Unaggregated: [{startDate, endDate, value: "Deep"|"REM"|"Core"|"Awake"|"InBed"|"Asleep", qty}]
        # IMPORTANT: use exact match, NOT substring. "apple sleeping wrist temperature" contains "sleep"
        # but is not sleep analysis — it's wrist temperature.
        if raw_name in ("sleep_analysis", "sleep analysis", "sleepanalysis"):
            for p in points:
                # Aggregated form has totalSleep / inBed / asleep fields
                if any(k in p for k in ("totalSleep", "asleep", "inBed")):
                    d = _coerce_date(p.get("date") or p.get("sleepStart") or "")
                    if not d:
                        continue
                    # For stages "Asleep" etc. the date can be the following morning; keep it.
                    item = _normalize_sleep_aggregated(p, d)
                    if item:
                        put_item(table, item)
                        items_written += 1
                        latest_date = max(latest_date or d, d)
            # Collect per-stage segments (unaggregated) grouped by sleepStart's date
            by_date = {}
            for p in points:
                if any(k in p for k in ("totalSleep", "asleep", "inBed")):
                    continue  # already handled above
                anchor = p.get("sleepStart") or p.get("startDate") or p.get("date") or ""
                d = _coerce_date(anchor)
                if not d:
                    continue
                dur = (
                    p.get("duration_min")
                    or p.get("duration")
                    or (float(p.get("qty", 0)) * 60 if p.get("qty") else None)
                    or _minutes_between(p.get("startDate") or p.get("sleepStart"), p.get("endDate") or p.get("sleepEnd"))
                    or 0
                )
                value = p.get("value") or p.get("type") or p.get("stage") or ""
                by_date.setdefault(d, []).append({"value": value, "duration_min": float(dur)})
            for d, segs in by_date.items():
                item = _normalize_sleep(segs, d)
                if item:
                    put_item(table, item)
                    items_written += 1
                    latest_date = max(latest_date or d, d)
            continue

        mapping = HAE_NAME_MAP.get(name) or HAE_NAME_MAP.get(name_no_sep) or HAE_NAME_MAP.get(raw_name.replace("_", " "))
        if not mapping:
            continue
        metric_source, unit, kind = mapping

        # Triple expansion: HAE exports heart_rate entries with Min/Avg/Max per day.
        # Emit three rows: hr_min#hae, hr_avg#hae, hr_max#hae (metric_source "hr#hae" becomes the prefix).
        if kind == "triple":
            prefix = metric_source.rsplit("#", 1)[0]  # "hr"
            src_suffix = metric_source.split("#", 1)[1]  # "hae"
            by_date_triple = {}
            for p in points:
                d = _coerce_date(p.get("date") or p.get("startDate") or p.get("endDate") or "")
                if not d:
                    continue
                slot = by_date_triple.setdefault(d, {"min": [], "avg": [], "max": []})
                for key_raw, slot_key in (("Min", "min"), ("min", "min"),
                                          ("Avg", "avg"), ("avg", "avg"),
                                          ("Max", "max"), ("max", "max")):
                    v = p.get(key_raw)
                    if v is None:
                        continue
                    try:
                        slot[slot_key].append(float(v))
                    except (ValueError, TypeError):
                        continue
                # Single-value fallback (older HAE exports)
                if not any(p.get(k) is not None for k in ("Min", "min", "Avg", "avg", "Max", "max")):
                    q = p.get("qty") or p.get("value")
                    if q is not None:
                        try:
                            slot["avg"].append(float(q))
                        except (ValueError, TypeError):
                            pass
            for d, slots in by_date_triple.items():
                for slot_key, vals in slots.items():
                    if not vals:
                        continue
                    if slot_key == "min":
                        val = round(min(vals), 1)
                    elif slot_key == "max":
                        val = round(max(vals), 1)
                    else:
                        val = round(sum(vals) / len(vals), 1)
                    put_item(table, {
                        "date": d,
                        "metric_source": f"{prefix}_{slot_key}#{src_suffix}",
                        "value": val,
                        "unit": unit,
                        "ingested_at": _now_iso(),
                    })
                    items_written += 1
                    latest_date = max(latest_date or d, d)
            continue

        # Standard numeric aggregation (avg / sum_int / sum / last)
        by_date = {}
        for p in points:
            d = _coerce_date(p.get("date") or p.get("startDate") or p.get("endDate") or "")
            if not d:
                continue
            raw = p.get("qty") if p.get("qty") is not None else p.get("value")
            if raw is None:
                continue
            try:
                # For "last" we keep (timestamp_str, value) so we can pick the latest.
                if kind == "last":
                    ts = p.get("date") or p.get("endDate") or p.get("startDate") or ""
                    by_date.setdefault(d, []).append((ts, float(raw)))
                else:
                    by_date.setdefault(d, []).append(float(raw))
            except (ValueError, TypeError):
                continue

        for d, vals in by_date.items():
            if not vals:
                continue
            if kind == "avg":
                val = round(sum(vals) / len(vals), 1)
            elif kind == "sum_int":
                val = int(round(sum(vals)))
            elif kind == "last":
                # Pick latest by timestamp string (ISO-like sorts correctly)
                _ts, val = max(vals, key=lambda x: x[0])
                val = round(val, 2)
            else:  # "sum"
                val = round(sum(vals), 1)
            put_item(table, {
                "date": d,
                "metric_source": metric_source,
                "value": val,
                "unit": unit,
                "ingested_at": _now_iso(),
            })
            items_written += 1
            latest_date = max(latest_date or d, d)

    if latest_date:
        _trigger_compute(latest_date)

    return _resp(200, {"date": latest_date, "items_written": items_written})


def _log_hae_summary(data_list):
    """Print a compact one-line summary of an incoming HAE payload for CloudWatch.
    Shows metric names + point counts + a sample date so empty or malformed
    pushes are distinguishable from real data without dumping full bodies."""
    if not data_list:
        print("HAE_SUMMARY metrics=0 payload_empty=true")
        return
    summary_parts = []
    for entry in data_list:
        name = (entry.get("name") or "?").strip().lower().replace(" ", "_")[:30]
        points = entry.get("data") or []
        count = len(points)
        sample_date = ""
        if count:
            raw = (
                points[0].get("date")
                or points[0].get("startDate")
                or points[0].get("endDate")
                or ""
            )
            sample_date = _coerce_date(raw) or raw[:10]
        summary_parts.append(f"{name}:{count}@{sample_date}")
    print(f"HAE_SUMMARY metrics={len(data_list)} " + " ".join(summary_parts[:20]))


def _coerce_date(s):
    """Extract YYYY-MM-DD from any HAE date string."""
    if not s or not isinstance(s, str):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def _minutes_between(start, end):
    """Compute minute duration between two HAE datetime strings (various formats)."""
    if not start or not end:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            a = datetime.strptime(start, fmt)
            b = datetime.strptime(end, fmt)
            return round((b - a).total_seconds() / 60)
        except Exception:
            continue
    return None


def _normalize_sleep(sleep, date_str):
    """Normalize HAE sleep data into a single health-metrics item."""
    item = {
        "date": date_str,
        "metric_source": "sleep#hae",
        "ingested_at": _now_iso(),
    }

    if isinstance(sleep, dict):
        item["total_min"] = sleep.get("total_min") or sleep.get("asleep_min") or sleep.get("duration", 0)
        item["deep_min"] = sleep.get("deep_min") or sleep.get("deep", 0)
        item["rem_min"] = sleep.get("rem_min") or sleep.get("rem", 0)
        item["core_min"] = sleep.get("core_min") or sleep.get("core") or sleep.get("light", 0)
        item["awake_min"] = sleep.get("awake_min") or sleep.get("awake", 0)
        item["in_bed_min"] = sleep.get("in_bed_min") or sleep.get("inBed", 0)
        total = item["total_min"]
        in_bed = item["in_bed_min"]
        item["efficiency"] = round((total / in_bed) * 100, 1) if in_bed > 0 else 0
    elif isinstance(sleep, list):
        stage_totals = {"deep": 0, "rem": 0, "core": 0, "awake": 0, "inBed": 0, "asleep": 0}
        for entry in sleep:
            val = entry.get("value", "").lower().replace(" ", "")
            dur = entry.get("duration_min", entry.get("duration", 0))
            if "deep" in val:
                stage_totals["deep"] += dur
            elif "rem" in val:
                stage_totals["rem"] += dur
            elif "core" in val or "light" in val:
                stage_totals["core"] += dur
            elif "awake" in val:
                stage_totals["awake"] += dur
            elif "inbed" in val:
                stage_totals["inBed"] += dur
            elif "asleep" in val:
                stage_totals["asleep"] += dur

        total = stage_totals["deep"] + stage_totals["rem"] + stage_totals["core"]
        if stage_totals["asleep"] and not total:
            total = stage_totals["asleep"]

        item["total_min"] = round(total)
        item["deep_min"] = round(stage_totals["deep"])
        item["rem_min"] = round(stage_totals["rem"])
        item["core_min"] = round(stage_totals["core"])
        item["awake_min"] = round(stage_totals["awake"])
        in_bed = stage_totals["inBed"] or (total + stage_totals["awake"])
        item["in_bed_min"] = round(in_bed)
        item["efficiency"] = round((total / in_bed) * 100, 1) if in_bed > 0 else 0
    else:
        return None

    return item


def _normalize_sleep_aggregated(p, date_str):
    """Normalize HAE aggregated sleep record (hours-based) into health-metrics row."""
    def hours_to_min(v):
        try:
            return round(float(v) * 60)
        except (TypeError, ValueError):
            return 0

    asleep_min = hours_to_min(p.get("asleep"))
    total_min = hours_to_min(p.get("totalSleep")) or asleep_min
    deep_min = hours_to_min(p.get("deep"))
    rem_min = hours_to_min(p.get("rem"))
    core_min = hours_to_min(p.get("core"))
    in_bed_min = hours_to_min(p.get("inBed")) or (total_min + hours_to_min(p.get("awake")))
    awake_min = max(0, in_bed_min - (total_min or asleep_min)) if in_bed_min else hours_to_min(p.get("awake"))

    if not (total_min or deep_min or rem_min or core_min):
        return None

    return {
        "date": date_str,
        "metric_source": "sleep#hae",
        "total_min": total_min,
        "asleep_min": asleep_min or total_min,
        "deep_min": deep_min,
        "rem_min": rem_min,
        "core_min": core_min,
        "awake_min": awake_min,
        "in_bed_min": in_bed_min,
        "efficiency": round((total_min / in_bed_min) * 100, 1) if in_bed_min > 0 else 0,
        "sleep_start": p.get("sleepStart"),
        "sleep_end": p.get("sleepEnd"),
        "ingested_at": _now_iso(),
    }


def _handle_withings(event):
    """Process Withings webhook notification — fetch actual data via API."""
    body = _parse_body(event)
    # Withings verifies the callback URL with an empty or sparse form POST;
    # it expects a 2xx response before activating the subscription.
    if body is None:
        return _resp(200, {"status": "verified"})
    if not body:
        return _resp(200, {"status": "verified"})

    appli = body.get("appli")
    if appli is None:
        # Verification ping with no appli — respond 200 so Withings accepts the subscription
        return _resp(200, {"status": "verified"})
    if appli != 1:
        return _resp(200, {"status": "ignored", "appli": appli})

    startdate = body.get("startdate")
    enddate = body.get("enddate")

    secret = _get_secret("withings-oauth")
    if not secret:
        return _resp(500, {"error": "missing withings credentials"})

    # Proactive refresh if within 5 minutes of expiry (or already expired / missing)
    token = secret.get("access_token", "")
    expires_at = int(secret.get("expires_at", 0) or 0)
    if not token or expires_at - int(time.time()) < 300:
        try:
            token = _refresh_withings_token()
        except Exception as e:
            return _resp(500, {"error": f"withings token refresh failed: {str(e)}"})

    # First attempt; if auth fails, refresh and retry once.
    data = _withings_getmeas(token, startdate, enddate)
    if data.get("status") in (401, 601):
        try:
            token = _refresh_withings_token()
        except Exception as e:
            return _resp(500, {"error": f"withings token refresh failed: {str(e)}"})
        data = _withings_getmeas(token, startdate, enddate)

    if data.get("status") != 0:
        return _resp(502, {"error": "withings API returned error", "status": data.get("status")})

    table = get_table("HEALTH_METRICS_TABLE")
    items_written = 0

    measure_types = {1: "weight", 6: "fat_ratio", 8: "fat_mass", 76: "muscle_mass", 77: "hydration"}

    for grp in data.get("body", {}).get("measuregrps", []):
        grp_date = datetime.fromtimestamp(grp["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        for m in grp.get("measures", []):
            mtype = measure_types.get(m["type"])
            if not mtype:
                continue
            value = m["value"] * (10 ** m["unit"])
            if mtype == "weight":
                value = round(value * 2.20462, 1)  # kg → lbs
            elif mtype in ("fat_mass", "muscle_mass", "hydration"):
                value = round(value * 2.20462, 1)
            elif mtype == "fat_ratio":
                value = round(value, 1)

            put_item(table, {
                "date": grp_date,
                "metric_source": f"{mtype}#withings",
                "value": value,
                "unit": "lbs" if mtype != "fat_ratio" else "%",
                "ingested_at": _now_iso(),
            })
            items_written += 1

    return _resp(200, {"items_written": items_written})


def _withings_getmeas(token, startdate, enddate):
    """Call Withings getmeas. Returns parsed response (even on non-zero status)."""
    params = urllib.parse.urlencode({
        "action": "getmeas",
        "meastype": "1,6,8,76,77",
        "category": 1,
        "startdate": startdate or 0,
        "enddate": enddate or 0,
    })
    req = urllib.request.Request(
        f"https://wbsapi.withings.net/measure?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Withings normally returns 200 with status code in body, but surface 401 explicitly
        try:
            return json.loads(e.read())
        except Exception:
            return {"status": e.code}
    except Exception as e:
        return {"status": -1, "error": str(e)}


def _refresh_withings_token():
    """Refresh Withings access token using refresh_token grant. Updates the secret in place."""
    secret = _get_secret("withings-oauth") or {}
    client_id = secret.get("client_id", "")
    client_secret = secret.get("client_secret", "")
    refresh_token = secret.get("refresh_token", "")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("missing withings client credentials or refresh_token")

    data = urllib.parse.urlencode({
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(
        WITHINGS_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())

    if body.get("status") != 0:
        raise RuntimeError(f"withings refresh status {body.get('status')}: {body.get('error', '')}")

    new = body.get("body", {})
    updated = dict(secret)
    updated["access_token"] = new.get("access_token", "")
    updated["refresh_token"] = new.get("refresh_token", refresh_token)
    updated["userid"] = str(new.get("userid", updated.get("userid", "")))
    updated["expires_at"] = int(time.time()) + int(new.get("expires_in", 10800))

    secrets_client.update_secret(
        SecretId="withings-oauth",
        SecretString=json.dumps(updated),
    )
    _secret_cache["withings-oauth"] = updated
    return updated["access_token"]


def _strava_get(url, token):
    """GET Strava API endpoint; returns (parsed_body_or_None, http_status)."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, -1


def _refresh_strava_token():
    """Refresh Strava access token using refresh_token grant. Updates the secret in place."""
    secret = _get_secret("strava-oauth") or {}
    client_id = secret.get("client_id", "")
    client_secret = secret.get("client_secret", "")
    refresh_token = secret.get("refresh_token", "")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("missing strava client credentials or refresh_token")

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(
        STRAVA_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())

    updated = dict(secret)
    updated["access_token"] = body.get("access_token", "")
    updated["refresh_token"] = body.get("refresh_token", refresh_token)
    updated["expires_at"] = int(body.get("expires_at", int(time.time()) + int(body.get("expires_in", 21600))))

    secrets_client.update_secret(
        SecretId="strava-oauth",
        SecretString=json.dumps(updated),
    )
    _secret_cache["strava-oauth"] = updated
    return updated["access_token"]


def _handle_strava_verify(event):
    """Strava webhook subscription verification."""
    qs = event.get("queryStringParameters", {}) or {}
    mode = qs.get("hub.mode")
    token = qs.get("hub.verify_token")
    challenge = qs.get("hub.challenge")

    secret = _get_secret("strava-oauth")
    verify_token = secret.get("verify_token", "fitness-strava-verify") if secret else "fitness-strava-verify"

    if mode == "subscribe" and token == verify_token:
        return _resp(200, {"hub.challenge": challenge})

    return _resp(403, {"error": "verification failed"})


def _handle_strava(event):
    """Process Strava webhook event — fetch activity and compute strain."""
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid body"})

    obj_type = body.get("object_type")
    aspect_type = body.get("aspect_type")
    obj_id = body.get("object_id")

    if obj_type != "activity" or aspect_type not in ("create", "update"):
        return _resp(200, {"status": "ignored"})

    secret = _get_secret("strava-oauth")
    if not secret:
        return _resp(500, {"error": "missing strava credentials"})

    token = secret.get("access_token", "")
    expires_at = int(secret.get("expires_at", 0) or 0)
    if not token or expires_at - int(time.time()) < 300:
        try:
            token = _refresh_strava_token()
        except Exception as e:
            return _resp(500, {"error": f"strava token refresh failed: {str(e)}"})

    activity, status = _strava_get(f"https://www.strava.com/api/v3/activities/{obj_id}", token)
    if status == 401:
        try:
            token = _refresh_strava_token()
        except Exception as e:
            return _resp(500, {"error": f"strava token refresh failed: {str(e)}"})
        activity, status = _strava_get(f"https://www.strava.com/api/v3/activities/{obj_id}", token)
    if status != 200 or activity is None:
        return _resp(502, {"error": f"strava activity fetch failed (status {status})"})

    streams, _ = _strava_get(
        f"https://www.strava.com/api/v3/activities/{obj_id}/streams?keys=heartrate&key_type=time",
        token,
    )
    hr_stream = []
    if isinstance(streams, list):
        for s in streams:
            if s.get("type") == "heartrate":
                hr_stream = s.get("data", [])
                break

    start_date = activity.get("start_date_local", "")[:10]
    if not start_date:
        start_date = local_today_str()

    workout_item = {
        "date": start_date,
        "strava_id": str(obj_id),
        "title": activity.get("name", ""),
        "type": activity.get("sport_type", activity.get("type", "")),
        "dur": round(activity.get("elapsed_time", 0) / 60),
        "avgHR": round(activity.get("average_heartrate", 0), 1),
        "maxHR": round(activity.get("max_heartrate", 0)),
        "cal": round(activity.get("calories", 0)),
        "ingested_at": _now_iso(),
    }

    if hr_stream:
        trimp_data = compute_trimp(hr_stream, sample_interval_sec=1.0)
        workout_item["trimp"] = trimp_data["trimp"]
        workout_item["strain"] = compute_strain(trimp_data["trimp"])
        workout_item["zones"] = trimp_data["zone_minutes"]
    elif workout_item["avgHR"] > 0:
        # No stream — fall back to summary-stat strain estimate.
        # Also back-fill a TRIMP so downstream daily/ACWR math still works.
        dur_min = workout_item["dur"]
        avg_zone = classify_hr_zone(workout_item["avgHR"])
        estimated_trimp = dur_min * {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}[avg_zone]
        workout_item["trimp"] = round(estimated_trimp, 1)
        workout_item["strain"] = estimate_strain_simple(
            exercise_minutes=dur_min,
            active_calories=workout_item.get("cal", 0),
            avg_hr=workout_item["avgHR"],
            max_hr_observed=workout_item.get("maxHR") or None,
        )
        workout_item["zones_estimated"] = True

    table = get_table("WORKOUTS_TABLE")
    put_item(table, workout_item)

    _trigger_compute(start_date)

    return _resp(200, {"date": start_date, "strava_id": str(obj_id), "strain": workout_item.get("strain")})


# ── Helpers ────────────────────────────────────────────────────

def _parse_body(event):
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    if not isinstance(body, str):
        return body
    if not body.strip():
        return {}
    # Try JSON first
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to form-encoded (Withings webhooks use this)
    try:
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        # parse_qs returns list values — unwrap singletons
        out = {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}
        # Coerce numerics that Withings sends
        for key in ("appli", "startdate", "enddate"):
            if key in out:
                try:
                    out[key] = int(out[key])
                except (ValueError, TypeError):
                    pass
        return out if out else None
    except Exception:
        return None


def _extract_date(data):
    """Extract YYYY-MM-DD date from various HAE payload formats."""
    for key in ("date", "dateFrom", "start_date", "timestamp"):
        val = data.get(key, "")
        if not val:
            continue
        if isinstance(val, str):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", val)
            if m:
                return m.group(1)
            # HAE format: yyyy-MM-dd HH:mm:ss Z
            m2 = re.match(r"(\d{4}-\d{2}-\d{2})\s", val)
            if m2:
                return m2.group(1)
    return local_today_str()


def _extract_value(data):
    """Pull a numeric value from HAE metric data (handles dict, list, or scalar)."""
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        for key in ("qty", "value", "avg", "mean"):
            v = data.get(key)
            if v is not None:
                return float(v)
    if isinstance(data, list) and data:
        last = data[-1]
        if isinstance(last, dict):
            return _extract_value(last)
        return float(last)
    return None


def _verify_api_key(key):
    if not key:
        return False
    secret = _get_secret("fitness-api-key")
    if secret and secret.get("api_key") == key:
        return True
    expected = os.environ.get("INGEST_API_KEY", "")
    return expected and key == expected


_secret_cache = {}

def _get_secret(name):
    if name in _secret_cache:
        return _secret_cache[name]
    secrets_arn = os.environ.get("SECRETS_ARN", "")
    try:
        resp = secrets_client.get_secret_value(SecretId=name)
        val = json.loads(resp["SecretString"])
        _secret_cache[name] = val
        return val
    except Exception:
        return None


def _trigger_compute(date_str):
    if not COMPUTE_FN:
        return
    try:
        lambda_client.invoke(
            FunctionName=COMPUTE_FN,
            InvocationType="Event",
            Payload=json.dumps({"action": "compute_day", "date": date_str}),
        )
    except Exception:
        pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
