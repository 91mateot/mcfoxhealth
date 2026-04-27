"""
Nutrition Lambda — meal logging, water tracking, journal, and calibration.

  POST   /api/meal                       — Log a meal
  PATCH  /api/meal/{date}/{meal_id}      — Edit a meal (macros, name, tag)
  DELETE /api/meal/{date}/{meal_id}      — Delete a meal
  POST   /api/meal/estimate              — Estimate macros from free-form text (no save)
  POST   /api/water                      — Log water intake
  POST   /api/journal                    — Submit morning journal check-in
  GET    /api/favorites                  — List saved quick-add favorites
  POST   /api/favorites                  — Save a meal as a favorite
  DELETE /api/favorites/{id}             — Remove a favorite
  POST   /api/calibration/reference      — Submit Whoop-proxy numbers for scoring calibration
  GET    /api/calibration/reference      — Return last 14 days of our scores vs proxy
"""

import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

import boto3

from shared.db import get_table, put_item, get_item, query_items
from shared.timezone import local_now, local_today_str

secrets_client = boto3.client("secretsmanager")
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-west-2")
_api_key_cache = {"value": None, "ts": 0}

ESTIMATOR_MODEL_ID = os.environ.get("ESTIMATOR_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


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
    if path == "/api/journal":
        return _post_journal(event)
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

    # Optional metadata from the estimator or re-estimate flow.
    if body.get("original_text"):
        item["original_text"] = str(body["original_text"])[:2000]
    if isinstance(body.get("assumptions"), list):
        item["assumptions"] = [str(a)[:200] for a in body["assumptions"] if str(a).strip()][:10]
    if body.get("confidence") in ("high", "medium", "low"):
        item["confidence"] = body["confidence"]
    if body.get("source"):
        item["source"] = str(body["source"])[:30]
    if body.get("sourceUrl"):
        item["source_url"] = str(body["sourceUrl"])[:500]
    ingredients = _sanitize_ingredients(body.get("ingredients"))
    if ingredients:
        item["ingredients"] = ingredients
    water_oz_raw = body.get("water_oz")
    water_oz = None
    if water_oz_raw is not None:
        try:
            w = float(water_oz_raw)
            if w > 0:
                water_oz = round(min(w, 200.0), 1)
        except (TypeError, ValueError):
            pass
    if water_oz is not None:
        item["water_oz"] = water_oz

    caffeine_raw = body.get("caffeine_mg")
    if caffeine_raw is not None:
        try:
            cmg = float(caffeine_raw)
            if cmg > 0:
                item["caffeine_mg"] = round(min(cmg, 1000.0), 0)
        except (TypeError, ValueError):
            pass

    put_item(table, item)

    # Auto-log a water_ row for hydrating beverages so the Today hydration panel counts it.
    if water_oz is not None:
        water_row = {
            "date": date,
            "meal_id": f"water_{int(time.time() * 1000)}",
            "oz": water_oz,
            "source_meal_id": meal_id,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        put_item(table, water_row)

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


def _post_meal_estimate(event):
    """Estimate macros for a free-form meal description (no save).

    Body: {"text": "guacamole from 1 avocado + 15 tortilla chips"}
    Optionally: {"text": "...", "known_hint": "oikos"} to force a known-food hit.

    Returns: {name, cal, p, c, f, tag, confidence, assumptions[], sourceUrl?}
    """
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    text = (body.get("text") or "").strip()
    if not text:
        return _resp(400, {"error": "text is required"})

    # Fast path: known-foods exact match on either the hint or the lowercased text.
    known_key = (body.get("known_hint") or "").lower().strip()
    if not known_key:
        lower = text.lower()
        for k in KNOWN_FOODS:
            if k in lower:
                known_key = k
                break
    if known_key and known_key in KNOWN_FOODS:
        food = KNOWN_FOODS[known_key]
        return _resp(200, {
            **food,
            "tag": _guess_tag(local_now().hour),
            "confidence": "high",
            "assumptions": [f"Matched known food: {food['name']}"],
            "source": "known_foods",
        })

    # Pull URL content if present.
    url_text = ""
    source_url = None
    for match in re.finditer(r"https?://\S+", text):
        candidate = match.group(0).rstrip(".,;:)]\"'")
        fetched = _fetch_url_text(candidate)
        if fetched:
            source_url = candidate
            url_text = fetched
            break  # first fetchable URL wins

    try:
        estimate = _estimate_macros(text, url_text)
    except Exception as e:
        return _resp(502, {"error": f"estimator error: {str(e)}"})

    if source_url and "sourceUrl" not in estimate:
        estimate["sourceUrl"] = source_url
    estimate.setdefault("source", "llm")
    return _resp(200, estimate)


_PATCHABLE_FIELDS = {"name", "cal", "p", "c", "f", "tag", "portion", "time",
                     "original_text", "assumptions", "confidence", "source_url",
                     "ingredients", "water_oz", "caffeine_mg"}


def _sanitize_ingredients(raw) -> list:
    """Accept a list of ingredient dicts; drop anything malformed. Cap at 15."""
    if not isinstance(raw, list):
        return []
    out = []
    for ing in raw[:15]:
        if not isinstance(ing, dict):
            continue
        name = str(ing.get("name", "")).strip()
        if not name:
            continue
        def _n(v):
            try:
                return round(float(v), 1)
            except (TypeError, ValueError):
                return 0.0
        out.append({
            "name": name[:80],
            "portion": str(ing.get("portion", ""))[:60],
            "cal": _n(ing.get("cal")),
            "p": _n(ing.get("p")),
            "c": _n(ing.get("c")),
            "f": _n(ing.get("f")),
        })
    return out


def _patch_meal(date_str: str, meal_id: str, event):
    """Edit a meal's macros, name, or related metadata.

    Body: any subset of {name, cal, p, c, f, tag, portion, time,
                        original_text, assumptions, confidence, source_url}
    """
    body = _parse_body(event)
    if body is None:
        return _resp(400, {"error": "invalid JSON body"})
    if not meal_id.startswith("meal_"):
        return _resp(400, {"error": "invalid meal_id"})

    table = get_table("NUTRITION_TABLE")
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
                v = _sanitize_ingredients(v)
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

    if not updates:
        return _resp(400, {"error": "no valid fields to update"})

    updates["edited_at"] = datetime.now(timezone.utc).isoformat()

    merged = {**existing, **updates}
    put_item(table, merged)

    return _resp(200, {"meal": _serialize_meal(merged)})


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
    """Convert a DynamoDB row back to the API meal shape."""
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
    # Dedup by name (case-insensitive) — updating the numbers if user saves same name again.
    items = [i for i in items if str(i.get("name", "")).strip().lower() != name.lower()]
    items.insert(0, fav)
    # Cap at 24 to keep the list tidy.
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


def _guess_tag(hour: int) -> str:
    if hour < 10:
        return "breakfast"
    if hour < 14:
        return "lunch"
    if hour < 17:
        return "snack"
    if hour < 21:
        return "dinner"
    return "snack"


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML→text: skip script/style, keep visible text."""

    _SKIP = {"script", "style", "noscript", "head", "meta", "link", "svg"}

    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._chunks)).strip()


def _fetch_url_text(url: str, max_bytes: int = 150_000, timeout: float = 5.0) -> str:
    """Safely fetch a URL and return extracted text, or empty string on failure.

    - HTTPS only
    - Blocks private/loopback/link-local IPs (SSRF guard)
    - 5s timeout, 150KB hard cap
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
        # SSRF guard — resolve hostname, reject private/loopback.
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror:
            return ""
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return ""

        req = urllib.request.Request(url, headers={"User-Agent": "mcfoxhealth-estimator/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return ""
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
        html = raw.decode("utf-8", errors="ignore")
        parser = _HTMLTextExtractor()
        parser.feed(html)
        text = parser.text()
        # Cap text length passed to the model (~6KB ≈ ~1500 tokens).
        return text[:6000]
    except Exception:
        return ""


_ESTIMATOR_SYSTEM = """You are a nutrition-accuracy assistant for a fitness app.

User profile:
- Mateo, 34, 5'8" 169lb, 13.6% body fat
- Goal: recomp (sub-12% body fat while defending lean mass)
- On retatrutide (GLP-1 triple agonist) — appetite is suppressed, so portions typed may be smaller than average unless explicitly large

Your job: given a free-form meal description (and optional recipe webpage content), return calories, macros, per-ingredient breakdown, the time the user ate it, and (for beverages) hydration volume in strict JSON.

General rules:
- Be precise about portions. "½ cup cooked jasmine rice" ≈ 100g ≈ 128 cal, 2.7g P, 28g C, 0.3g F.
- If the user pasted a recipe URL, the webpage content will be provided. Use it but assume the user ate ONE serving unless they specified otherwise.
- If the description lists multiple components, sum them.
- Pick a `tag` from: breakfast, lunch, dinner, snack. Default based on stated time if given; else snack.
- Confidence:
  - "high" when portions are unambiguous and ingredients are common
  - "medium" when you made reasonable estimates but portions were vague
  - "low" when the description is too vague to estimate well
- Always return assumptions so the user can verify. Be specific: include portion sizes you inferred.
- Numbers only (not ranges). Round to 1 decimal.
- If the text is clearly not a meal (e.g. "coffee, black" is fine; "walked the dog" is not), return cal=0 p=0 c=0 f=0 with confidence="low" and an assumption explaining why.

Time parsing:
- If the text states a time (e.g., "at 3pm", "7pm dinner", "10:30am breakfast", "around noon"), extract it into `time` as 24-hour "HH:MM".
- If no time is stated, return `time: null` — the app will fall back to the current moment.
- "breakfast" without a time ⇒ null; "breakfast at 7am" ⇒ "07:00".

Hydration (beverages only):
- `water_oz` is the beverage's HYDRATION VALUE — usually just fluid volume, except alcohol.
- Water, tea (any kind), coffee, latte, cappuccino, juice, soda, sports drink, kombucha, milk, smoothies: `water_oz` = the full fluid volume. Caffeine does NOT reduce this — recent research (IOM, Killer 2014) shows caffeinated drinks hydrate nearly as well as water in habitual drinkers.
- Alcohol is the exception. Apply a penalty based on ABV:
  - Beer (~5% ABV, 12 oz): water_oz ≈ volume × 0.85 (so 12 oz beer ⇒ 10.2)
  - Strong beer / cider (7–9% ABV): × 0.70
  - Wine (12–14% ABV, 5 oz pour): × 0.60 (so 5 oz wine ⇒ 3.0)
  - Spirits neat (40%+ ABV, 1.5 oz shot): × 0 (0 oz — net dehydrating)
  - Mixed drink: estimate water contribution from the mixer only (Jack+Coke with 1.5 oz spirit in 8 oz total ≈ 6.5 oz mixer × 1.0)
- Typical fluid volumes: cup of coffee/tea 8 oz; grande latte 16 oz; venti 20 oz; bottle of water 16.9 oz; can of soda/beer 12 oz; pint of beer 16 oz; wine pour 5 oz; shot 1.5 oz.
- Bone broth, soup, and solid food ⇒ `water_oz: null` (they're food, not a beverage).
- If unsure, return null.

Caffeine (any drink or food with caffeine):
- Return `caffeine_mg` as the total milligrams of caffeine in what the user consumed. Null if none.
- Reference amounts:
  - Drip coffee, 8 oz: ~95 mg (12 oz ~140 mg, 16 oz ~180 mg)
  - Espresso shot, 1 oz: ~63 mg
  - Latte / cappuccino: 1 shot = 63 mg; 2 shots = 126 mg; larger sizes often have 2 shots default
  - Cold brew, 8 oz: ~155 mg
  - Black tea, 8 oz: ~50 mg
  - Green tea, 8 oz: ~30 mg
  - Matcha latte, 8 oz: ~70 mg
  - Herbal/rooibos tea: 0 mg
  - Soda (Coke, Pepsi) 12 oz: ~35 mg; Diet Coke 12 oz: ~45 mg
  - Energy drinks (Celsius, Red Bull, Monster) 12 oz: typically 80–200 mg
  - Dark chocolate, pre-workout supplements, some protein bars: check if user mentions them
- Decaf coffee still has ~5 mg per 8 oz — round down to 0 unless they specify "half-caf".

Per-ingredient breakdown:
- `ingredients` is an array of the components that make up the meal. Each has `{name, portion, cal, p, c, f}`.
- `portion` is a short human-readable string like "1/2 cup cooked", "4 oz", "1 medium", "15 chips".
- Ingredient cal/p/c/f MUST sum to the top-level totals (within rounding). Be consistent.
- Single-item meals still return a one-element `ingredients` array (e.g., "oikos shake" ⇒ one ingredient).
- Skip the breakdown for pure beverages (coffee, tea, water) — return `ingredients: []`.
- Cap at 15 ingredients. Combine minor items into "seasonings/oil" if needed.

Return ONLY valid JSON, no prose. Schema:
{
  "name": "short descriptive meal name (≤60 chars)",
  "cal": number,
  "p": number,
  "c": number,
  "f": number,
  "tag": "breakfast"|"lunch"|"dinner"|"snack",
  "time": "HH:MM" | null,
  "water_oz": number | null,
  "caffeine_mg": number | null,
  "confidence": "high"|"medium"|"low",
  "assumptions": ["string", ...],
  "ingredients": [{"name": "string", "portion": "string", "cal": number, "p": number, "c": number, "f": number}, ...]
}"""


def _estimate_macros(text: str, url_text: str) -> dict:
    """Call Bedrock Claude Sonnet 4.6 with the estimator system prompt.

    Returns a dict matching the schema in _ESTIMATOR_SYSTEM.
    Raises on fatal errors (caller converts to 502).
    """
    known_foods_context = "\n".join(
        f"- {k}: {v['name']} — {v['cal']} cal, {v['p']}p {v['c']}c {v['f']}f"
        for k, v in KNOWN_FOODS.items()
    )

    user_msg = f"""Meal description:
{text}

Known foods reference (use these exact numbers if the description matches):
{known_foods_context}
"""
    if url_text:
        user_msg += f"\n\nRecipe page content (truncated):\n{url_text}\n"

    resp = bedrock_runtime.invoke_model(
        modelId=ESTIMATOR_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1800,
            "system": _ESTIMATOR_SYSTEM,
            "messages": [{"role": "user", "content": user_msg}],
        }),
    )
    payload = json.loads(resp["body"].read())
    reply = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            reply += block["text"]
    reply = reply.strip()

    # Tolerate code-fence wrapping.
    if reply.startswith("```"):
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply, flags=re.DOTALL)

    data = json.loads(reply)

    # Coerce + validate.
    def _num(v, default=0.0):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return float(default)

    tag = str(data.get("tag", "snack")).lower()
    if tag not in {"breakfast", "lunch", "dinner", "snack"}:
        tag = "snack"
    conf = str(data.get("confidence", "medium")).lower()
    if conf not in {"high", "medium", "low"}:
        conf = "medium"

    assumptions = data.get("assumptions") or []
    if isinstance(assumptions, str):
        assumptions = [assumptions]
    assumptions = [str(a)[:200] for a in assumptions if str(a).strip()][:10]

    # Time — accept "HH:MM" 24-hour, else drop.
    parsed_time = None
    raw_time = data.get("time")
    if isinstance(raw_time, str):
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw_time)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh < 24 and 0 <= mm < 60:
                parsed_time = f"{hh:02d}:{mm:02d}"

    # Water — non-negative, capped at 200 oz; treat 0 the same as null so the frontend
    # can show the "will also log X oz" hint only when there's something to log.
    water_oz = None
    raw_water = data.get("water_oz")
    if raw_water is not None:
        try:
            w = float(raw_water)
            if w > 0:
                water_oz = round(min(w, 200.0), 1)
        except (TypeError, ValueError):
            pass

    # Caffeine — non-negative mg, capped at 1000 (sanity).
    caffeine_mg = None
    raw_caf = data.get("caffeine_mg")
    if raw_caf is not None:
        try:
            c = float(raw_caf)
            if c > 0:
                caffeine_mg = round(min(c, 1000.0), 0)
        except (TypeError, ValueError):
            pass

    # Ingredients — sanitize to [{name, portion, cal, p, c, f}], cap at 15.
    ingredients = []
    raw_ings = data.get("ingredients")
    if isinstance(raw_ings, list):
        for ing in raw_ings[:15]:
            if not isinstance(ing, dict):
                continue
            name = str(ing.get("name", "")).strip()
            if not name:
                continue
            ingredients.append({
                "name": name[:80],
                "portion": str(ing.get("portion", ""))[:60],
                "cal": _num(ing.get("cal")),
                "p": _num(ing.get("p")),
                "c": _num(ing.get("c")),
                "f": _num(ing.get("f")),
            })

    totals_cal = _num(data.get("cal"))
    totals_p = _num(data.get("p"))
    totals_c = _num(data.get("c"))
    totals_f = _num(data.get("f"))

    # If ingredients exist and disagree with totals by >5%, trust the ingredient sums.
    if ingredients:
        def _sum(key):
            return round(sum(i[key] for i in ingredients), 1)
        s_cal = _sum("cal")
        # Only override when there's a meaningful disagreement AND the totals aren't trivially small.
        if totals_cal > 20 and abs(s_cal - totals_cal) / totals_cal > 0.05:
            totals_cal, totals_p, totals_c, totals_f = s_cal, _sum("p"), _sum("c"), _sum("f")

    out = {
        "name": str(data.get("name") or text)[:80],
        "cal": totals_cal,
        "p": totals_p,
        "c": totals_c,
        "f": totals_f,
        "tag": tag,
        "confidence": conf,
        "assumptions": assumptions,
        "ingredients": ingredients,
    }
    if parsed_time is not None:
        out["time"] = parsed_time
    if water_oz is not None:
        out["water_oz"] = water_oz
    if caffeine_mg is not None:
        out["caffeine_mg"] = caffeine_mg
    return out


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
