"""
Nutrition Lambda — meal logging, water tracking, journal, and calibration.

  POST /api/meal                    — Log a meal
  POST /api/water                   — Log water intake
  POST /api/journal                 — Submit morning journal check-in
  POST /api/calibration/reference   — Submit Whoop-proxy numbers for scoring calibration
  GET  /api/calibration/reference   — Return last 14 days of our scores vs proxy
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3

from shared.db import get_table, put_item, get_item, query_items
from shared.timezone import local_now, local_today_str

secrets_client = boto3.client("secretsmanager")
_api_key_cache = {"value": None, "ts": 0}


def _verify_api_key(event):
    """Same x-api-key validation as /ingest/health — fitness-api-key secret."""
    key = event.get("headers", {}).get("x-api-key", "")
    if not key:
        return False
    now = int(time.time())
    if _api_key_cache["value"] is None or now - _api_key_cache["ts"] > 300:
        try:
            resp = secrets_client.get_secret_value(SecretId="fitness-api-key")
            _api_key_cache["value"] = json.loads(resp["SecretString"]).get("api_key", "")
        except Exception:
            _api_key_cache["value"] = os.environ.get("INGEST_API_KEY", "")
        _api_key_cache["ts"] = now
    return bool(_api_key_cache["value"]) and key == _api_key_cache["value"]

KNOWN_FOODS = {
    "oikos": {"name": "Oikos Vanilla Protein Shake", "cal": 170, "p": 30, "c": 8, "f": 3.5},
    "kirkland bar": {"name": "Kirkland PB Protein Bar", "cal": 190, "p": 21, "c": 22, "f": 7},
    "chicken bake": {"name": "Costco Chicken Bake", "cal": 770, "p": 61, "c": 78, "f": 25},
    "half chicken bake": {"name": "Costco Chicken Bake (half)", "cal": 385, "p": 31, "c": 39, "f": 13},
    "morning shake": {"name": "Morning Shake (full)", "cal": 712, "p": 53, "c": 102, "f": 17},
    "half shake": {"name": "Morning Shake (half)", "cal": 356, "p": 26.5, "c": 51, "f": 8.5},
    "gochujang bowl": {"name": "MasonFit Gochujang Bowl", "cal": 380, "p": 36, "c": 40, "f": 5},
}


def lambda_handler(event, context):
    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")

    if "/api/meal" in path:
        return _post_meal(event)
    if "/api/water" in path:
        return _post_water(event)
    if "/api/journal" in path:
        return _post_journal(event)
    if "/api/calibration/reference" in path:
        if method == "GET":
            return _get_calibration(event)
        return _post_calibration(event)

    return _resp(404, {"error": "not found"})


def _post_calibration(event):
    """Store Mateo's Whoop-proxy reference numbers so we can compare vs our scores."""
    if not _verify_api_key(event):
        return _resp(401, {"error": "unauthorized"})

    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    date_str = body.get("date") or local_today_str()
    try:
        recovery = body.get("recovery")
        strain = body.get("strain")
        sleep = body.get("sleep")
        if recovery is not None:
            recovery = float(recovery)
        if strain is not None:
            strain = float(strain)
        if sleep is not None:
            sleep = float(sleep)
    except (ValueError, TypeError):
        return _resp(400, {"error": "recovery/strain/sleep must be numeric"})

    item = {"date": date_str, "ingested_at": datetime.now(timezone.utc).isoformat()}
    if recovery is not None:
        item["recovery"] = recovery
    if strain is not None:
        item["strain"] = strain
    if sleep is not None:
        item["sleep"] = sleep
    if body.get("source"):
        item["source"] = str(body["source"])
    if body.get("notes"):
        item["notes"] = str(body["notes"])[:500]

    put_item(get_table("CALIBRATION_TABLE"), item)
    return _resp(200, {"ok": True, "date": date_str, "stored": {k: v for k, v in item.items() if k not in ("ingested_at",)}})


def _get_calibration(event):
    """Return last N days of calibration rows alongside our daily-scores for the same dates."""
    try:
        limit = int(event.get("queryStringParameters", {}).get("days", "14"))
    except (ValueError, TypeError):
        limit = 14

    today = local_now()
    from datetime import timedelta
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(limit)]

    cal_table = get_table("CALIBRATION_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")

    rows = []
    for d in dates:
        ref = get_item(cal_table, {"date": d})
        ours = get_item(scores_table, {"date": d})
        if ref is None and ours is None:
            continue
        rows.append({
            "date": d,
            "reference": {
                "recovery": (ref or {}).get("recovery"),
                "strain":   (ref or {}).get("strain"),
                "sleep":    (ref or {}).get("sleep"),
                "source":   (ref or {}).get("source"),
            } if ref else None,
            "ours": {
                "recovery": (ours or {}).get("recovery"),
                "strain":   (ours or {}).get("strain"),
                "sleep_score": (ours or {}).get("sleep_score"),
            } if ours else None,
        })
    return _resp(200, {"days": limit, "rows": rows})


def _post_meal(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    table = get_table("NUTRITION_TABLE")
    today = local_today_str()
    date = body.get("date", today)

    quick = body.get("quick_add", "").lower().strip()
    if quick and quick in KNOWN_FOODS:
        food = KNOWN_FOODS[quick]
        body = {**body, **food}

    meal_id = f"meal_{int(time.time() * 1000)}"
    now_hour = local_now().hour
    time_str = body.get("time", f"{now_hour}:00")

    item = {
        "date": date,
        "meal_id": meal_id,
        "time": time_str,
        "name": body.get("name", ""),
        "portion": body.get("portion", ""),
        "cal": body.get("cal", 0),
        "p": body.get("p", 0),
        "c": body.get("c", 0),
        "f": body.get("f", 0),
        "tag": body.get("tag", ""),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }

    put_item(table, item)

    all_meals = query_items(table, "date", date)
    totals = {"cal": 0, "p": 0, "c": 0, "f": 0}
    for m in all_meals:
        if m.get("meal_id", "").startswith("meal_"):
            totals["cal"] += m.get("cal", 0)
            totals["p"] += m.get("p", 0)
            totals["c"] += m.get("c", 0)
            totals["f"] += m.get("f", 0)

    alerts = []
    if totals["p"] < 180:
        hours_left = max(1, 22 - now_hour)
        pace = totals["p"] / max(1, now_hour - 7) * (22 - 7)
        if pace < 180 and now_hour >= 14:
            alerts.append(f"Protein behind pace: {totals['p']}g / 180g target")
    if totals["cal"] < 1800 and now_hour >= 18:
        alerts.append(f"Undereating alert: {totals['cal']} cal — below 1,800 minimum")

    return _resp(200, {
        "meal": item,
        "totals": totals,
        "alerts": alerts,
    })


def _post_water(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    table = get_table("NUTRITION_TABLE")
    today = local_today_str()
    date = body.get("date", today)

    water_id = f"water_{int(time.time() * 1000)}"
    oz = body.get("oz", 0)

    item = {
        "date": date,
        "meal_id": water_id,
        "oz": oz,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }

    put_item(table, item)

    all_items = query_items(table, "date", date)
    total_water = sum(m.get("oz", 0) for m in all_items if m.get("meal_id", "").startswith("water_"))

    return _resp(200, {"water_oz": total_water, "goal": 100})


def _post_journal(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    journal_table = get_table("JOURNAL_TABLE")
    today = local_today_str()
    date = body.get("date", today)

    item = {
        "date": date,
        "tags": body.get("tags", []),
        "mood": body.get("mood"),
        "stress": body.get("stress"),
        "soreness": body.get("soreness"),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    put_item(journal_table, item)

    return _resp(200, {"status": "saved", "date": date})


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
