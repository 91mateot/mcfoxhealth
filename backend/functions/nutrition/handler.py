"""
Nutrition Lambda — meal logging, water tracking, journal, and calibration.

  POST   /api/meal                       — Log a meal
  PATCH  /api/meal/{date}/{meal_id}      — Edit a meal (macros, name, tag)
  DELETE /api/meal/{date}/{meal_id}      — Delete a meal
  POST   /api/meal/estimate              — Estimate macros from free-form text (no save)
  POST   /api/water                      — Log water intake
  POST   /api/journal                    — Submit morning journal check-in
  POST   /api/workout                    — Log a manual workout (free-form text)
  GET    /api/favorites                  — List saved quick-add favorites
  POST   /api/favorites                  — Save a meal as a favorite
  DELETE /api/favorites/{id}             — Remove a favorite
  POST   /api/calibration/reference      — Submit Whoop-proxy numbers for scoring calibration
  GET    /api/calibration/reference      — Return last 14 days of our scores vs proxy
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3

from shared.db import get_table, put_item, get_item
from shared.timezone import local_now, local_today_str
from shared.nutrition_service import (
    estimate_meal,
    save_meal,
    log_water as svc_log_water,
    log_journal as svc_log_journal,
    log_workout as svc_log_workout,
    delete_water as svc_delete_water,
    move_meal as svc_move_meal,
    validate_meal as svc_validate_meal,
    sanitize_ingredients,
    generate_journal_prompts as svc_generate_journal_prompts,
    append_note as svc_append_note,
    update_note as svc_update_note,
    delete_note as svc_delete_note,
)
from shared.workout_service import (
    annotate_workout as svc_annotate_workout,
    summarize_workout as svc_summarize_workout,
)
from shared.event_service import record_event as svc_record_event
from shared.feedback_service import save_feedback as svc_save_feedback

secrets_client = boto3.client("secretsmanager")
_api_key_cache = {"value": None, "ts": 0}


def _verify_api_key(event):
    """x-api-key validation matching the /ingest/health endpoint."""
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


def lambda_handler(event, context):
    # Direct Lambda invoke path: payloads with {"action": "..."} skip HTTP
    # routing. Used by save_meal's fire-and-forget validator kick-off.
    action = event.get("action") if isinstance(event, dict) else None
    if action == "validate_meal":
        try:
            result = svc_validate_meal(event.get("meal_id", ""), event.get("date"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return result

    if not _verify_api_key(event):
        return _resp(401, {"error": "unauthorized"})

    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
    params = event.get("pathParameters") or {}

    if path.endswith("/api/meal/estimate"):
        return _post_meal_estimate(event)
    if path.startswith("/api/meal/") and params.get("date") and params.get("meal_id"):
        if method == "PATCH":
            return _patch_meal(params["date"], params["meal_id"], event)
        if method == "DELETE":
            return _delete_meal(params["date"], params["meal_id"])
    if path == "/api/meal" or path.endswith("/api/meal"):
        return _post_meal(event)
    if path == "/api/water":
        return _post_water(event)
    if path.startswith("/api/water/") and params.get("date") and params.get("water_id"):
        if method == "DELETE":
            return _delete_water(params["date"], params["water_id"])
    if path == "/api/journal":
        return _post_journal(event)
    if path == "/api/journal/prompts":
        return _post_journal_prompts(event)
    if path == "/api/journal/note":
        if method == "PATCH":
            return _patch_journal_note(event)
        if method == "DELETE":
            return _delete_journal_note(event)
    if path == "/api/workout":
        return _post_workout(event)
    if path.startswith("/api/workout/") and path.endswith("/annotate"):
        parts = path.split("/")
        # /api/workout/{date}/{workout_id}/annotate
        if len(parts) == 6 and parts[5] == "annotate":
            return _post_workout_annotate(parts[3], parts[4], event)
    if path.startswith("/api/workout/") and path.endswith("/feedback"):
        parts = path.split("/")
        # /api/workout/{date}/{workout_id}/feedback
        if len(parts) == 6 and parts[5] == "feedback":
            return _post_workout_feedback(parts[3], parts[4])
    if path == "/api/favorites":
        if method == "GET":
            return _get_favorites()
        return _post_favorite(event)
    if path.startswith("/api/favorites/") and params.get("id"):
        if method == "DELETE":
            return _delete_favorite(params["id"])
    if "/api/calibration/reference" in path:
        if method == "GET":
            return _get_calibration(event)
        return _post_calibration(event)
    if path == "/api/feedback" and method == "POST":
        return _post_feedback(event)
    if path == "/api/event" and method == "POST":
        return _post_event(event)

    return _resp(404, {"error": "not found"})


def _post_feedback(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    try:
        result = svc_save_feedback(
            signal=str(body.get("signal") or ""),
            target_type=str(body.get("target_type") or ""),
            target_id=str(body.get("target_id") or ""),
            note=body.get("note"),
        )
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    return _resp(200, result)


def _post_event(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    events = body.get("events") if isinstance(body.get("events"), list) else [body]
    stored = []
    for raw in events[:50]:
        if not isinstance(raw, dict):
            continue
        try:
            stored.append(
                svc_record_event(
                    action=str(raw.get("action") or ""),
                    props=raw.get("props") if isinstance(raw.get("props"), dict) else None,
                )
            )
        except ValueError:
            continue
    return _resp(200, {"ok": True, "stored": len(stored)})


def _post_calibration(event):
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
    try:
        limit = int(event.get("queryStringParameters", {}).get("days", "14"))
    except (ValueError, TypeError):
        limit = 14

    today = local_now()
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
    return _resp(200, save_meal(body))


_MAX_IMAGE_B64_BYTES = 1_500_000  # ~1.1 MB raw JPEG after base64
_ALLOWED_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _post_meal_estimate(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    text = (body.get("text") or "").strip()
    img = body.get("image") or {}
    image_b64 = str(img.get("data") or "") if isinstance(img, dict) else ""
    media_type = str(img.get("media_type") or "image/jpeg") if isinstance(img, dict) else "image/jpeg"

    if not text and not image_b64:
        return _resp(400, {"error": "text or image is required"})

    if image_b64:
        if len(image_b64) > _MAX_IMAGE_B64_BYTES:
            return _resp(413, {"error": "image too large; compress client-side"})
        if media_type not in _ALLOWED_IMAGE_MEDIA_TYPES:
            return _resp(400, {"error": f"unsupported media_type {media_type}"})

    try:
        estimate = estimate_meal(
            text,
            body.get("known_hint", ""),
            skip_known_foods=bool(body.get("skip_known_foods")) or bool(image_b64),
            image_b64=image_b64 or None,
            media_type=media_type if image_b64 else None,
        )
    except Exception as e:
        return _resp(502, {"error": f"estimator error: {str(e)}"})
    return _resp(200, estimate)


_PATCHABLE_FIELDS = {"name", "cal", "p", "c", "f", "tag", "portion", "time",
                     "original_text", "assumptions", "confidence", "source_url",
                     "ingredients", "water_oz", "caffeine_mg"}


def _patch_meal(date_str: str, meal_id: str, event):
    body = _parse_body(event)
    if body is None:
        return _resp(400, {"error": "invalid JSON body"})
    if not meal_id.startswith("meal_"):
        return _resp(400, {"error": "invalid meal_id"})

    table = get_table("NUTRITION_TABLE")

    # `date` in the body means the client wants to move this meal to a different
    # day. Route through move_meal (copy + delete) since `date` is the partition
    # key and can't be updated in place. The rest of the patch then applies to
    # the relocated row.
    new_date = body.pop("date", None)
    new_time = body.get("time")
    moved_dates = False
    if new_date is not None and new_date != date_str:
        try:
            moved = svc_move_meal(meal_id, date_str, new_date, new_time=new_time if isinstance(new_time, str) else None)
        except KeyError:
            return _resp(404, {"error": "meal not found"})
        except ValueError as e:
            return _resp(400, {"error": str(e)})
        date_str = new_date
        existing = moved
        moved_dates = True
        # `time` was handled by move_meal; don't double-apply.
        body.pop("time", None)
    else:
        existing = get_item(table, {"date": date_str, "meal_id": meal_id})
        if not existing:
            return _resp(404, {"error": "meal not found"})

    updates = {}
    for k, v in body.items():
        if k in _PATCHABLE_FIELDS:
            if k == "assumptions":
                if not isinstance(v, list):
                    continue
                v = [str(a)[:200] for a in v if str(a).strip()][:10]
            elif k == "ingredients":
                v = sanitize_ingredients(v)
            elif k == "confidence" and v not in ("high", "medium", "low"):
                continue
            elif k in ("cal", "p", "c", "f", "water_oz", "caffeine_mg"):
                try:
                    v = float(v)
                    if k == "water_oz":
                        if v <= 0:
                            continue
                        v = round(min(v, 200.0), 1)
                    elif k == "caffeine_mg":
                        if v <= 0:
                            continue
                        v = round(min(v, 1000.0), 0)
                except (TypeError, ValueError):
                    continue
            elif isinstance(v, str):
                v = v[:2000]
            updates[k] = v

    if not updates and not moved_dates:
        return _resp(400, {"error": "no valid fields to update"})

    if updates:
        updates["edited_at"] = datetime.now(timezone.utc).isoformat()
        merged = {**existing, **updates}
        put_item(table, merged)
    else:
        merged = existing

    return _resp(200, {"meal": _serialize_meal(merged), "date": date_str})


def _delete_meal(date_str: str, meal_id: str):
    if not meal_id.startswith("meal_"):
        return _resp(400, {"error": "invalid meal_id"})
    table = get_table("NUTRITION_TABLE")
    existing = get_item(table, {"date": date_str, "meal_id": meal_id})
    if not existing:
        return _resp(404, {"error": "meal not found"})
    table.delete_item(Key={"date": date_str, "meal_id": meal_id})
    return _resp(200, {"ok": True, "date": date_str, "meal_id": meal_id})


def _serialize_meal(item: dict) -> dict:
    out = {
        "id": item.get("meal_id", ""),
        "time": item.get("time", ""),
        "name": item.get("name", ""),
        "portion": item.get("portion", ""),
        "cal": item.get("cal", 0),
        "p": item.get("p", 0),
        "c": item.get("c", 0),
        "f": item.get("f", 0),
        "tag": item.get("tag", ""),
    }
    if item.get("original_text"):
        out["originalText"] = item["original_text"]
    if item.get("assumptions"):
        out["assumptions"] = list(item["assumptions"])
    if item.get("confidence"):
        out["confidence"] = item["confidence"]
    if item.get("source"):
        out["source"] = item["source"]
    if item.get("source_url"):
        out["sourceUrl"] = item["source_url"]
    if item.get("ingredients"):
        out["ingredients"] = list(item["ingredients"])
    if item.get("water_oz") is not None:
        out["waterOz"] = item["water_oz"]
    if item.get("caffeine_mg") is not None:
        out["caffeineMg"] = item["caffeine_mg"]
    if item.get("validated_at"):
        out["validatedAt"] = item["validated_at"]
    if item.get("validated_source"):
        out["validatedSource"] = item["validated_source"]
    return out


# ── Favorites (quick-add list) ──────────────────────────────────────────────
# Stored as a single row in USER_CONFIG_TABLE with key="favorites" and an
# "items" attribute that is a list of {id, name, cal, p, c, f, tag}.

def _get_favorites():
    table = get_table("USER_CONFIG_TABLE")
    row = get_item(table, {"key": "favorites"}) or {}
    items = row.get("items") or []
    return _resp(200, {"favorites": items})


def _post_favorite(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    name = str(body.get("name", "")).strip()
    if not name:
        return _resp(400, {"error": "name required"})

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    fav = {
        "id": f"fav_{int(time.time() * 1000)}",
        "name": name[:80],
        "cal": _num(body.get("cal")),
        "p": _num(body.get("p")),
        "c": _num(body.get("c")),
        "f": _num(body.get("f")),
        "tag": str(body.get("tag") or "snack")[:20],
    }

    table = get_table("USER_CONFIG_TABLE")
    row = get_item(table, {"key": "favorites"}) or {"key": "favorites", "items": []}
    items = list(row.get("items") or [])
    items = [i for i in items if str(i.get("name", "")).strip().lower() != name.lower()]
    items.insert(0, fav)
    items = items[:24]
    put_item(table, {"key": "favorites", "items": items})
    return _resp(200, {"favorite": fav, "count": len(items)})


def _delete_favorite(fav_id: str):
    table = get_table("USER_CONFIG_TABLE")
    row = get_item(table, {"key": "favorites"}) or {"key": "favorites", "items": []}
    items = [i for i in (row.get("items") or []) if i.get("id") != fav_id]
    put_item(table, {"key": "favorites", "items": items})
    return _resp(200, {"ok": True, "count": len(items)})


def _post_water(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    try:
        result = svc_log_water(body.get("oz", 0), date=body.get("date"))
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    return _resp(200, result)


def _delete_water(date_str: str, water_id: str):
    try:
        result = svc_delete_water(water_id, date=date_str)
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    if not result.get("ok"):
        return _resp(404, result)
    return _resp(200, result)


def _post_journal(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    slot = str(body.get("slot") or "morning").lower()
    if slot == "note":
        try:
            result = svc_append_note(
                text=body.get("text") or "",
                date=body.get("date"),
                at=body.get("at"),
                tags=body.get("tags"),
                mood=body.get("mood"),
                stress=body.get("stress"),
            )
        except ValueError as e:
            return _resp(400, {"error": str(e)})
        return _resp(200, result)
    if slot not in ("morning", "evening", "tags_only"):
        slot = "morning"
    tags = body.get("tags")
    if slot == "evening" and tags is None:
        tags = body.get("evening_tags")
    prompts = body.get("prompts")
    text = body.get("text")
    result = svc_log_journal(
        tags=tags if tags is not None else None,
        mood=body.get("mood"),
        stress=body.get("stress"),
        soreness=body.get("soreness"),
        date=body.get("date"),
        slot=slot,
        text=text,
        prompts=prompts if isinstance(prompts, list) else None,
    )
    return _resp(200, result)


def _patch_journal_note(event):
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    date = body.get("date")
    note_id = body.get("id")
    if not date or not note_id:
        return _resp(400, {"error": "date and id required"})
    try:
        result = svc_update_note(
            date=date,
            note_id=note_id,
            text=body.get("text"),
            tags=body.get("tags"),
            mood=body.get("mood"),
            stress=body.get("stress"),
            at=body.get("at"),
        )
    except KeyError:
        return _resp(404, {"error": "note not found"})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    return _resp(200, result)


def _delete_journal_note(event):
    qs = event.get("queryStringParameters") or {}
    body = _parse_body(event) or {}
    date = qs.get("date") or body.get("date")
    note_id = qs.get("id") or body.get("id")
    if not date or not note_id:
        return _resp(400, {"error": "date and id required"})
    try:
        result = svc_delete_note(date=date, note_id=note_id)
    except KeyError:
        return _resp(404, {"error": "note not found"})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    return _resp(200, result)


def _post_journal_prompts(event):
    body = _parse_body(event) or {}
    slot = str(body.get("slot") or "morning").lower()
    if slot not in ("morning", "evening"):
        slot = "morning"
    try:
        result = svc_generate_journal_prompts(slot, date=body.get("date"))
    except Exception as e:
        return _resp(502, {"error": f"prompt generation failed: {e}"})
    return _resp(200, result)


def _post_workout(event):
    """Log a manually-entered workout. Body: {text: str, date?: "YYYY-MM-DD"}."""
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    text = (body.get("text") or "").strip()
    if not text:
        return _resp(400, {"error": "text is required"})
    date = body.get("date")
    try:
        result = svc_log_workout(text, date=date)
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception as e:
        return _resp(502, {"error": f"workout estimator failed: {e}"})
    return _resp(200, result)


def _post_workout_feedback(date_str: str, workout_id: str):
    """Regenerate coach feedback for a workout. Useful for backfilled
    workouts that were annotated before the feedback loop existed."""
    try:
        result = svc_summarize_workout(date_str, workout_id)
    except Exception as e:
        return _resp(502, {"error": f"feedback failed: {e}"})
    if not result.get("ok"):
        return _resp(404, result)
    return _resp(200, result)


def _post_workout_annotate(date_str: str, workout_id: str, event):
    """Parse free-form lift notes and attach them to the workout row for
    date_str + workout_id. The workout_id pins the exact row — necessary
    when a date has multiple Strava sessions (Morning Workout + Lunch Walk)
    and the user tapped a specific one."""
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})
    text = (body.get("text") or "").strip()
    if not text:
        return _resp(400, {"error": "text is required"})
    try:
        result = svc_annotate_workout(text, date=date_str, workout_id=workout_id)
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception as e:
        return _resp(502, {"error": f"annotator failed: {e}"})
    return _resp(200, result)


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
