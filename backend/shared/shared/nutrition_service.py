"""
Nutrition service — pure business logic for meals, water, journal, and estimation.

These functions are HTTP-agnostic. They're called from:
  - functions/nutrition/handler.py (the public REST API)
  - functions/coach/app.py         (Bedrock tool-use handlers)
"""

import ipaddress
import json
import logging
import os
import re
import socket
import urllib.parse
import urllib.request
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Optional

import boto3

from shared.db import get_table, put_item, get_item, query_items
from shared.timezone import local_now, local_today_str, LOCAL_TZ

logger = logging.getLogger("nutrition_service")

bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-west-2")
lambda_client = boto3.client("lambda", region_name="us-west-2")
secrets_client = boto3.client("secretsmanager", region_name="us-west-2")

ESTIMATOR_MODEL_ID = os.environ.get("ESTIMATOR_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
NUTRITION_FUNCTION_NAME = os.environ.get("NUTRITION_FUNCTION_NAME", "")
_SECRETS_CACHE: dict = {"data": None, "ts": 0}


def _get_secret_json() -> dict:
    """Read and cache the `fitness-api-key` Secrets Manager JSON (5 min TTL)."""
    now = int(time.time())
    if _SECRETS_CACHE["data"] is None or now - _SECRETS_CACHE["ts"] > 300:
        try:
            resp = secrets_client.get_secret_value(SecretId="fitness-api-key")
            _SECRETS_CACHE["data"] = json.loads(resp.get("SecretString") or "{}")
            _SECRETS_CACHE["ts"] = now
        except Exception:
            logger.exception("secret read failed")
            _SECRETS_CACHE["data"] = {}
            _SECRETS_CACHE["ts"] = now
    return _SECRETS_CACHE["data"] or {}


KNOWN_FOODS = {
    "oikos": {"name": "Oikos Vanilla Protein Shake", "cal": 170, "p": 30, "c": 8, "f": 3.5},
    "kirkland bar": {"name": "Kirkland PB Protein Bar", "cal": 190, "p": 21, "c": 22, "f": 7},
    "chicken bake": {"name": "Costco Chicken Bake", "cal": 770, "p": 61, "c": 78, "f": 25},
    "half chicken bake": {"name": "Costco Chicken Bake (half)", "cal": 385, "p": 31, "c": 39, "f": 13},
    "morning shake": {"name": "Morning Shake (full)", "cal": 712, "p": 53, "c": 102, "f": 17},
    "half shake": {"name": "Morning Shake (half)", "cal": 356, "p": 26.5, "c": 51, "f": 8.5},
    "gochujang bowl": {"name": "MasonFit Gochujang Bowl", "cal": 380, "p": 36, "c": 40, "f": 5},
}


def guess_tag(hour: int) -> str:
    if hour < 10:
        return "breakfast"
    if hour < 14:
        return "lunch"
    if hour < 17:
        return "snack"
    if hour < 21:
        return "dinner"
    return "snack"


# ── Estimator ──────────────────────────────────────────────────────────────

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
}

## Image input
If the user provides an image:
- **Nutrition facts panel visible** → read per-serving values directly. Set `confidence: "high"`, `source: "label_photo"`. Put a brief assumption like "Read directly from nutrition facts panel — per serving: N g".
- **Product name / front of package only** → use your knowledge of that specific product. Set `confidence: "medium"`, `source: "label_photo"`. Assumption: "Inferred from product name '{X}' — verify on the package."
- **Food photo (plate, bowl, etc.)** → estimate portions from visual cues. Set `confidence: "medium"` if portions are clear, `"low"` if ambiguous. Assumption must list portion sizes you inferred.
- **Blurry / unreadable** → return cal=0 p=0 c=0 f=0, `confidence: "low"`, and an assumption explaining you couldn't read the image. Never fabricate.

When an image is the only input (no text), pick `tag` from current context or default to "snack"."""


class _HTMLTextExtractor(HTMLParser):
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
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
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
        return parser.text()[:6000]
    except Exception:
        return ""


def _call_estimator(
    text: str,
    url_text: str,
    image_b64: Optional[str] = None,
    media_type: Optional[str] = None,
) -> dict:
    known_foods_context = "\n".join(
        f"- {k}: {v['name']} — {v['cal']} cal, {v['p']}p {v['c']}c {v['f']}f"
        for k, v in KNOWN_FOODS.items()
    )

    if image_b64:
        # Image-led estimation: the user sent a photo (with optional caption).
        # Image block first (Anthropic-recommended for better attention),
        # then the text context with known-foods reference.
        caption_txt = text.strip() or "(no caption — read everything you can from the image)"
        user_text = (
            f"User caption:\n{caption_txt}\n\n"
            f"Known foods reference (use these exact numbers if the image matches one):\n"
            f"{known_foods_context}"
        )
        content_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type or "image/jpeg",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": user_text},
        ]
    else:
        user_msg = f"""Meal description:
{text}

Known foods reference (use these exact numbers if the description matches):
{known_foods_context}
"""
        if url_text:
            user_msg += f"\n\nRecipe page content (truncated):\n{url_text}\n"
        content_blocks = user_msg

    resp = bedrock_runtime.invoke_model(
        modelId=ESTIMATOR_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1800,
            "system": _ESTIMATOR_SYSTEM,
            "messages": [{"role": "user", "content": content_blocks}],
        }),
    )
    payload = json.loads(resp["body"].read())
    reply = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            reply += block["text"]
    reply = reply.strip()

    if reply.startswith("```"):
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply, flags=re.DOTALL)

    data = json.loads(reply)

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

    parsed_time = None
    raw_time = data.get("time")
    if isinstance(raw_time, str):
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw_time)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh < 24 and 0 <= mm < 60:
                parsed_time = f"{hh:02d}:{mm:02d}"

    water_oz = None
    raw_water = data.get("water_oz")
    if raw_water is not None:
        try:
            w = float(raw_water)
            if w > 0:
                water_oz = round(min(w, 200.0), 1)
        except (TypeError, ValueError):
            pass

    caffeine_mg = None
    raw_caf = data.get("caffeine_mg")
    if raw_caf is not None:
        try:
            c = float(raw_caf)
            if c > 0:
                caffeine_mg = round(min(c, 1000.0), 0)
        except (TypeError, ValueError):
            pass

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

    if ingredients:
        def _sum(key):
            return round(sum(i[key] for i in ingredients), 1)
        s_cal = _sum("cal")
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


_KNOWN_FAST_PATH_MAX_LEN = 30


def _known_foods_match(text: str) -> str:
    """Return a KNOWN_FOODS key if the text is short enough AND the key appears
    as the leading phrase (or the entire text is the key). Long recipe-style
    descriptions — e.g. 'morning shake with oikos pro yogurt, whey…' —
    bypass the fast path so the LLM estimates the real recipe."""
    lower = text.lower().strip()
    if not lower or len(lower) > _KNOWN_FAST_PATH_MAX_LEN:
        return ""
    for k in KNOWN_FOODS:
        # Whole text equals key, or text starts with "<key>" as a leading token.
        if lower == k or lower.startswith(k + " ") or lower.startswith(k + ","):
            return k
    return ""


def estimate_meal(
    text: str,
    known_hint: str = "",
    skip_known_foods: bool = False,
    image_b64: Optional[str] = None,
    media_type: Optional[str] = None,
) -> dict:
    """Estimate macros for free-form text and/or an image. Returns estimate
    dict (not saved).

    Fast path: KNOWN_FOODS dict (text-only inputs, short & unambiguous).
    Slow path: Bedrock estimator.

    When `image_b64` is provided, the known-foods fast path is bypassed and
    the estimator sees the image. The returned `source` defaults to
    "label_photo" for image-driven estimates, "llm" for text-only, or
    "known_foods" for fast-path matches.
    """
    text = (text or "").strip()
    if not text and not image_b64:
        raise ValueError("text or image is required")

    # Known-foods fast path is text-only. Images force the LLM path.
    if text and not skip_known_foods and not image_b64:
        known_key = (known_hint or "").lower().strip()
        if not known_key:
            known_key = _known_foods_match(text)
        if known_key and known_key in KNOWN_FOODS:
            food = KNOWN_FOODS[known_key]
            return {
                **food,
                "tag": guess_tag(local_now().hour),
                "confidence": "high",
                "assumptions": [f"Matched known food: {food['name']}"],
                "source": "known_foods",
            }

    url_text = ""
    source_url = None
    if text:
        for match in re.finditer(r"https?://\S+", text):
            candidate = match.group(0).rstrip(".,;:)]\"'")
            fetched = _fetch_url_text(candidate)
            if fetched:
                source_url = candidate
                url_text = fetched
                break

    estimate = _call_estimator(text, url_text, image_b64=image_b64, media_type=media_type)
    if source_url and "sourceUrl" not in estimate:
        estimate["sourceUrl"] = source_url
    if image_b64:
        estimate.setdefault("source", "label_photo")
    else:
        estimate.setdefault("source", "llm")
    return estimate


def sanitize_ingredients(raw) -> list:
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


# ── Saving ─────────────────────────────────────────────────────────────────


def save_meal(payload: dict, date: Optional[str] = None) -> dict:
    """Persist a meal (and companion water row when water_oz is set).

    `payload` mirrors the POST /api/meal body: name, cal, p, c, f, tag,
    optional time, portion, original_text, assumptions, confidence, source,
    sourceUrl, ingredients, water_oz, caffeine_mg, quick_add.

    Returns {meal, totals, alerts}.
    """
    body = dict(payload or {})
    table = get_table("NUTRITION_TABLE")
    today = local_today_str()
    date = date or body.get("date") or today

    quick = str(body.get("quick_add", "")).lower().strip()
    if quick and quick in KNOWN_FOODS:
        body = {**body, **KNOWN_FOODS[quick]}

    meal_id = f"meal_{int(time.time() * 1000)}"
    now_local = local_now()
    now_hour = now_local.hour
    time_str = body.get("time") or f"{now_local.hour:02d}:{now_local.minute:02d}"

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
    ingredients = sanitize_ingredients(body.get("ingredients"))
    if ingredients:
        item["ingredients"] = ingredients

    water_oz = None
    water_oz_raw = body.get("water_oz")
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

    # Canonical-source meals are already high-confidence (read directly from
    # OpenFoodFacts per-serving data or a photo of the nutrition panel).
    # Stamp as validated at save time and skip the async validator: that
    # path would waste Bedrock/USDA cycles and, via the known USDA per-100g
    # scaling bug, can actively regress correct numbers.
    src = body.get("source")
    is_canonical_source = src in ("barcode", "label_photo")
    if src == "barcode":
        item["validated_at"] = datetime.now(timezone.utc).isoformat()
        item["validated_source"] = "openfoodfacts"
    elif src == "label_photo":
        item["validated_at"] = datetime.now(timezone.utc).isoformat()
        item["validated_source"] = "bedrock_vision"

    put_item(table, item)

    if water_oz is not None:
        put_item(table, {
            "date": date,
            "meal_id": f"water_{int(time.time() * 1000)}",
            "oz": water_oz,
            "source_meal_id": meal_id,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        })

    # Fire-and-forget second-pass validator. Must never raise — a broken
    # validator should never block a log. Skipped for canonical-source meals
    # (barcode, label_photo) since they're already validated (see above).
    if NUTRITION_FUNCTION_NAME and not is_canonical_source:
        try:
            lambda_client.invoke(
                FunctionName=NUTRITION_FUNCTION_NAME,
                InvocationType="Event",
                Payload=json.dumps({"action": "validate_meal", "meal_id": meal_id, "date": date}).encode(),
            )
        except Exception:
            logger.exception("validator invoke failed for meal_id=%s", meal_id)

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
        pace = totals["p"] / max(1, now_hour - 7) * (22 - 7)
        if pace < 180 and now_hour >= 14:
            alerts.append(f"Protein behind pace: {totals['p']}g / 180g target")
    if totals["cal"] < 1800 and now_hour >= 18:
        alerts.append(f"Undereating alert: {totals['cal']} cal — below 1,800 minimum")

    return {"meal": item, "totals": totals, "alerts": alerts}


def log_meal(text: str, date: Optional[str] = None) -> dict:
    """Estimate + save in one call. Used by the coach tool."""
    estimate = estimate_meal(text)
    estimate["original_text"] = text
    return save_meal(estimate, date=date)


def log_water(oz: float, date: Optional[str] = None) -> dict:
    try:
        oz = float(oz)
    except (TypeError, ValueError):
        raise ValueError("oz must be numeric")
    if oz <= 0:
        raise ValueError("oz must be positive")

    table = get_table("NUTRITION_TABLE")
    date = date or local_today_str()

    put_item(table, {
        "date": date,
        "meal_id": f"water_{int(time.time() * 1000)}",
        "oz": oz,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })

    all_items = query_items(table, "date", date)
    total = sum(m.get("oz", 0) for m in all_items if m.get("meal_id", "").startswith("water_"))
    return {"water_oz": total, "goal": 100}


def log_journal(
    tags: Optional[list] = None,
    mood: Optional[int] = None,
    stress: Optional[int] = None,
    soreness: Optional[int] = None,
    date: Optional[str] = None,
    slot: Optional[str] = None,
    text: Optional[str] = None,
    prompts: Optional[list] = None,
) -> dict:
    """Write a journal entry. One row per date, slot-aware merge so morning
    and evening don't clobber each other.

    Morning slot writes: tags, mood, stress, soreness, morning_text, morning_prompts.
    Evening slot writes: evening_tags, evening_mood, evening_stress, evening_text, evening_prompts.
    Tags-only writes (slot="tags_only", or morning slot with only tags and nothing else)
    update `tags` without marking morning as submitted — used for live supplement chip
    toggles from Fuel so the Morning check-in card stays "pending" until Mateo actually
    does it.
    If slot is omitted, defaults to "morning" for backward compatibility with the
    pre-expansion call path that passes only tags/mood/stress/soreness.
    """
    journal_table = get_table("JOURNAL_TABLE")
    date = date or local_today_str()
    slot = (slot or "morning").lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = get_item(journal_table, {"date": date}) or {"date": date}
    item = dict(existing)

    clean_prompts = _sanitize_prompts(prompts)
    clean_text = _clean_text(text)

    if slot == "evening":
        if tags is not None:
            item["evening_tags"] = list(tags or [])
        if mood is not None:
            item["evening_mood"] = mood
        if stress is not None:
            item["evening_stress"] = stress
        if clean_text is not None:
            item["evening_text"] = clean_text
        if clean_prompts is not None:
            item["evening_prompts"] = clean_prompts
        item["evening_saved_at"] = now_iso
    elif slot == "tags_only":
        if tags is not None:
            item["tags"] = list(tags or [])
        item["tags_updated_at"] = now_iso
    else:
        if tags is not None:
            item["tags"] = list(tags or [])
        if mood is not None:
            item["mood"] = mood
        if stress is not None:
            item["stress"] = stress
        if soreness is not None:
            item["soreness"] = soreness
        if clean_text is not None:
            item["morning_text"] = clean_text
        if clean_prompts is not None:
            item["morning_prompts"] = clean_prompts
        item["submitted_at"] = now_iso
        item["morning_saved_at"] = now_iso

    put_item(journal_table, item)
    return {"status": "saved", "date": date, "slot": slot}


def _normalize_scale(value) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 5:
        return None
    return n


def _normalize_tags(tags) -> Optional[list]:
    if tags is None:
        return None
    if not isinstance(tags, list):
        return None
    return [str(t).strip() for t in tags if str(t).strip()]


def _parse_note_at(at_str: Optional[str], date: str) -> str:
    """Validate a client-supplied `at` ISO timestamp. If None, return server now.
    When provided, the timestamp must fall within the given `date` in local TZ,
    so a note can't drift onto the wrong day."""
    if not at_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(str(at_str).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid `at` timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(LOCAL_TZ)
    if local_dt.strftime("%Y-%m-%d") != date:
        raise ValueError("`at` falls outside `date` in America/Los_Angeles")
    return dt.astimezone(timezone.utc).isoformat()


def append_note(
    text: str,
    date: Optional[str] = None,
    at: Optional[str] = None,
    tags: Optional[list] = None,
    mood: Optional[int] = None,
    stress: Optional[int] = None,
) -> dict:
    """Append a time-marked note to a date's journal row. Notes live alongside
    morning/evening snapshots; they don't overwrite them."""
    clean_text = _clean_text(text)
    if not clean_text:
        raise ValueError("text is required")

    date = date or local_today_str()
    at_iso = _parse_note_at(at, date)
    now_iso = datetime.now(timezone.utc).isoformat()

    note = {
        "id": f"note_{uuid.uuid4().hex[:12]}",
        "at": at_iso,
        "created_at": now_iso,
        "text": clean_text,
    }
    clean_tags = _normalize_tags(tags)
    if clean_tags is not None:
        note["tags"] = clean_tags
    mood_val = _normalize_scale(mood)
    if mood_val is not None:
        note["mood"] = mood_val
    stress_val = _normalize_scale(stress)
    if stress_val is not None:
        note["stress"] = stress_val

    journal_table = get_table("JOURNAL_TABLE")
    existing = get_item(journal_table, {"date": date}) or {"date": date}
    notes = list(existing.get("notes") or [])
    notes.append(note)
    notes.sort(key=lambda n: n.get("at") or "")
    existing["notes"] = notes
    existing["date"] = date
    put_item(journal_table, existing)

    return {"status": "saved", "date": date, "note": note}


def update_note(
    date: str,
    note_id: str,
    text: Optional[str] = None,
    tags: Optional[list] = None,
    mood: Optional[int] = None,
    stress: Optional[int] = None,
    at: Optional[str] = None,
) -> dict:
    """Edit an existing note. Returns {status, note} on success; raises
    KeyError if the note isn't found, ValueError on bad input."""
    if not date or not note_id:
        raise ValueError("date and note_id required")

    journal_table = get_table("JOURNAL_TABLE")
    existing = get_item(journal_table, {"date": date})
    if not existing:
        raise KeyError("journal row not found")
    notes = list(existing.get("notes") or [])
    idx = next((i for i, n in enumerate(notes) if n.get("id") == note_id), -1)
    if idx < 0:
        raise KeyError("note not found")

    note = dict(notes[idx])

    if text is not None:
        clean_text = _clean_text(text)
        if not clean_text:
            raise ValueError("text cannot be empty")
        note["text"] = clean_text
    if tags is not None:
        note["tags"] = _normalize_tags(tags) or []
    if mood is not None:
        val = _normalize_scale(mood)
        if val is None:
            note.pop("mood", None)
        else:
            note["mood"] = val
    if stress is not None:
        val = _normalize_scale(stress)
        if val is None:
            note.pop("stress", None)
        else:
            note["stress"] = val
    if at is not None:
        note["at"] = _parse_note_at(at, date)

    note["updated_at"] = datetime.now(timezone.utc).isoformat()
    notes[idx] = note
    notes.sort(key=lambda n: n.get("at") or "")
    existing["notes"] = notes
    put_item(journal_table, existing)

    return {"status": "saved", "date": date, "note": note}


def delete_note(date: str, note_id: str) -> dict:
    if not date or not note_id:
        raise ValueError("date and note_id required")
    journal_table = get_table("JOURNAL_TABLE")
    existing = get_item(journal_table, {"date": date})
    if not existing:
        raise KeyError("journal row not found")
    notes = list(existing.get("notes") or [])
    remaining = [n for n in notes if n.get("id") != note_id]
    if len(remaining) == len(notes):
        raise KeyError("note not found")
    existing["notes"] = remaining
    put_item(journal_table, existing)
    return {"status": "deleted", "date": date, "id": note_id}


def _clean_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return ""
    return s[:2000]


def _sanitize_prompts(prompts: Optional[list]) -> Optional[list]:
    if prompts is None:
        return None
    out = []
    for p in prompts[:6]:
        if not isinstance(p, dict):
            continue
        q = str(p.get("q") or "").strip()[:300]
        a = str(p.get("a") or "").strip()[:2000]
        if q:
            out.append({"q": q, "a": a})
    return out


# Static fallback used when Bedrock is slow/unavailable. Rotates by day-of-year
# so consecutive mornings/evenings don't repeat.
_MORNING_FALLBACK_PROMPTS = [
    ("What's one thing on your mind heading into today?", "Anything you want to do differently today than yesterday?"),
    ("How does your body feel right now — sharper or heavier than usual?", "What would make today feel like a win by 6pm?"),
    ("What's the most important thing you want to show up for today?", "Anything you're avoiding that's worth facing?"),
    ("Where's your energy pointed — work, body, people?", "What would 'good enough' look like today?"),
]
_EVENING_FALLBACK_PROMPTS = [
    ("What actually happened today — the headline version?", "What's one thing that went better than expected?"),
    ("Where did the day get away from you?", "What would you change about tomorrow if you could?"),
    ("What's one thing you learned about yourself today?", "How's the body feeling now versus this morning?"),
    ("What's still unresolved as you close the day?", "What are you grateful for, even on a rough day?"),
]


def _fallback_prompts(slot: str, date: str) -> list:
    try:
        doy = datetime.strptime(date, "%Y-%m-%d").timetuple().tm_yday
    except Exception:
        doy = 0
    pool = _EVENING_FALLBACK_PROMPTS if slot == "evening" else _MORNING_FALLBACK_PROMPTS
    q1, q2 = pool[doy % len(pool)]
    return [{"q": q1, "a": ""}, {"q": q2, "a": ""}]


_PROMPT_SYSTEM = (
    "You generate short reflection prompts for a personal fitness journal. "
    "Output ONLY a JSON array of exactly 2 objects, each with a single 'q' field: "
    '[{"q":"..."},{"q":"..."}]. No prose, no markdown fences. '
    "Each question must be <120 characters, plain English, specific to the user's "
    "recent context when signal is present, and open-ended (not yes/no)."
)


def generate_journal_prompts(slot: str, date: Optional[str] = None) -> dict:
    """Generate 2 reflection prompts for the given slot ('morning'|'evening').

    Caches the result into today's fitness-journal row (morning_prompts /
    evening_prompts) so refreshing the UI doesn't re-invoke Bedrock. Falls
    back to a static rotating pair if Bedrock fails or times out.
    """
    slot = (slot or "morning").lower()
    if slot not in ("morning", "evening"):
        slot = "morning"
    date = date or local_today_str()

    journal_table = get_table("JOURNAL_TABLE")
    cache_key = "evening_prompts" if slot == "evening" else "morning_prompts"

    existing = get_item(journal_table, {"date": date}) or {}
    cached = existing.get(cache_key)
    if isinstance(cached, list) and cached:
        return {"prompts": [{"q": p.get("q", ""), "a": p.get("a", "")} for p in cached]}

    context_block = _build_prompt_context(date, slot)

    prompts = None
    try:
        resp = bedrock_runtime.invoke_model(
            modelId=ESTIMATOR_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 300,
                "system": _PROMPT_SYSTEM,
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Slot: {slot}\n\n"
                        f"Recent context:\n{context_block}\n\n"
                        "Produce the 2 questions now."
                    ),
                }],
            }),
        )
        payload = json.loads(resp["body"].read())
        reply = ""
        for block in payload.get("content", []):
            if block.get("type") == "text":
                reply += block["text"]
        reply = reply.strip()
        if reply.startswith("```"):
            reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply, flags=re.DOTALL)
        data = json.loads(reply)
        if isinstance(data, list):
            prompts = [
                {"q": str(p.get("q") or "").strip()[:280], "a": ""}
                for p in data[:2]
                if isinstance(p, dict) and str(p.get("q") or "").strip()
            ]
    except Exception:
        logger.exception("journal prompt generation failed; using fallback")

    if not prompts or len(prompts) < 2:
        prompts = _fallback_prompts(slot, date)

    existing[cache_key] = prompts
    existing["date"] = date
    put_item(journal_table, existing)
    return {"prompts": prompts}


def _build_prompt_context(date: str, slot: str) -> str:
    """Compact recent-context block fed to the prompt generator. Pulls last 3
    days of scores, yesterday's journal, and most-recent workout."""
    scores_table = get_table("DAILY_SCORES_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    journal_table = get_table("JOURNAL_TABLE")

    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        dt = datetime.now()

    lines = []
    for i in range(3):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        s = get_item(scores_table, {"date": d}) or {}
        if not s:
            continue
        sleep_min = (s.get("sleep") or {}).get("total_min", 0)
        sleep_hours = round(sleep_min / 60, 1) if sleep_min else None
        parts = []
        if s.get("recovery") is not None:
            parts.append(f"recovery {s.get('recovery')}%")
        if s.get("strain") is not None:
            parts.append(f"strain {s.get('strain')}")
        if sleep_hours is not None:
            parts.append(f"sleep {sleep_hours}h")
        if s.get("hrv") is not None:
            parts.append(f"HRV {s.get('hrv')}ms")
        if parts:
            label = "today" if i == 0 else ("yesterday" if i == 1 else f"{i}d ago")
            lines.append(f"- {label}: {', '.join(parts)}")

    yest = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    yest_journal = get_item(journal_table, {"date": yest}) or {}
    if yest_journal.get("tags"):
        lines.append(f"- yesterday's journal tags: {', '.join(yest_journal['tags'])}")
    if slot == "evening":
        today_journal = get_item(journal_table, {"date": date}) or {}
        if today_journal.get("tags"):
            lines.append(f"- this morning's tags: {', '.join(today_journal['tags'])}")
        if today_journal.get("morning_text"):
            snippet = str(today_journal["morning_text"])[:240]
            lines.append(f"- this morning wrote: {snippet}")

    for i in range(3):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        workouts = query_items(workouts_table, "date", d) or []
        if workouts:
            w = workouts[-1]
            title = w.get("title") or w.get("type") or "workout"
            dur = w.get("dur")
            label = "today" if i == 0 else ("yesterday" if i == 1 else f"{i}d ago")
            dur_str = f" ({dur}min)" if dur else ""
            lines.append(f"- {label} workout: {title}{dur_str}")
            break

    return "\n".join(lines) if lines else "(no recent data)"


def delete_meal(meal_id: str, date: Optional[str] = None) -> dict:
    """Delete a meal row (and any companion water row that references it)."""
    if not meal_id or not meal_id.startswith("meal_"):
        raise ValueError("invalid meal_id")
    table = get_table("NUTRITION_TABLE")
    date = date or local_today_str()

    existing = get_item(table, {"date": date, "meal_id": meal_id})
    if not existing:
        return {"ok": False, "reason": "not found", "meal_id": meal_id}

    table.delete_item(Key={"date": date, "meal_id": meal_id})

    companions = 0
    for row in query_items(table, "date", date) or []:
        if row.get("meal_id", "").startswith("water_") and row.get("source_meal_id") == meal_id:
            table.delete_item(Key={"date": date, "meal_id": row["meal_id"]})
            companions += 1

    return {"ok": True, "meal_id": meal_id, "companions_deleted": companions}


def move_meal(
    meal_id: str,
    old_date: str,
    new_date: str,
    new_time: Optional[str] = None,
) -> dict:
    """Move a meal row (and any companion water row) from `old_date` to `new_date`.
    `date` is the DynamoDB partition key, so a cross-day move = copy + delete.
    `new_time` optionally overwrites `time` (HH:MM, local). Returns the relocated
    meal item so callers can echo it back."""
    if not meal_id or not meal_id.startswith("meal_"):
        raise ValueError("invalid meal_id")
    if not _valid_date(old_date) or not _valid_date(new_date):
        raise ValueError("date must be YYYY-MM-DD")
    if new_time is not None and not _valid_time(new_time):
        raise ValueError("time must be HH:MM")

    table = get_table("NUTRITION_TABLE")
    existing = get_item(table, {"date": old_date, "meal_id": meal_id})
    if not existing:
        raise KeyError("meal not found")

    if old_date == new_date:
        if new_time is not None:
            existing["time"] = new_time
            existing["edited_at"] = datetime.now(timezone.utc).isoformat()
            put_item(table, existing)
        return existing

    moved = dict(existing)
    moved["date"] = new_date
    if new_time is not None:
        moved["time"] = new_time
    moved["edited_at"] = datetime.now(timezone.utc).isoformat()
    put_item(table, moved)
    table.delete_item(Key={"date": old_date, "meal_id": meal_id})

    for row in query_items(table, "date", old_date) or []:
        if row.get("meal_id", "").startswith("water_") and row.get("source_meal_id") == meal_id:
            water_moved = dict(row)
            water_moved["date"] = new_date
            put_item(table, water_moved)
            table.delete_item(Key={"date": old_date, "meal_id": row["meal_id"]})

    return moved


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _valid_date(s: str) -> bool:
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_time(s: str) -> bool:
    return isinstance(s, str) and bool(_TIME_RE.match(s))


def delete_water(water_id: str, date: Optional[str] = None) -> dict:
    """Delete a standalone water row. Use for correcting duplicate log_water calls."""
    if not water_id or not water_id.startswith("water_"):
        raise ValueError("invalid water_id")
    table = get_table("NUTRITION_TABLE")
    date = date or local_today_str()

    existing = get_item(table, {"date": date, "meal_id": water_id})
    if not existing:
        return {"ok": False, "reason": "not found", "water_id": water_id}

    table.delete_item(Key={"date": date, "meal_id": water_id})
    return {"ok": True, "water_id": water_id}


def get_recent_meals(days: int = 1) -> list:
    """Return meal, water, AND workout rows for the last `days` days (today +
    days-1 prior), sorted by date desc then time desc. Each row has a `kind`
    discriminator so the coach knows which delete tool to use (delete_meal vs
    delete_water vs delete_workout)."""
    table = get_table("NUTRITION_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    today_dt = local_now()
    out = []
    for i in range(max(1, days)):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rows = query_items(table, "date", d) or []
        for m in rows:
            mid = m.get("meal_id", "")
            if mid.startswith("meal_"):
                out.append({
                    "kind": "meal",
                    "date": d,
                    "meal_id": mid,
                    "time": m.get("time"),
                    "name": m.get("name"),
                    "cal": m.get("cal"),
                    "p": m.get("p"),
                    "c": m.get("c"),
                    "f": m.get("f"),
                    "tag": m.get("tag"),
                    "water_oz": m.get("water_oz"),
                    "caffeine_mg": m.get("caffeine_mg"),
                })
            elif mid.startswith("water_"):
                out.append({
                    "kind": "water",
                    "date": d,
                    "water_id": mid,
                    "oz": m.get("oz"),
                    "logged_at": m.get("logged_at"),
                    "source_meal_id": m.get("source_meal_id"),
                })
        workouts = query_items(workouts_table, "date", d) or []
        for w in workouts:
            out.append({
                "kind": "workout",
                "date": d,
                "workout_id": w.get("strava_id", ""),
                "title": w.get("title"),
                "type": w.get("type"),
                "dur": w.get("dur"),
                "cal": w.get("cal"),
                "strain": w.get("strain"),
                "source": w.get("source", "strava"),
                "logged_at": w.get("logged_at") or w.get("ingested_at"),
            })
    out.sort(key=lambda m: (m["date"], m.get("time") or m.get("logged_at") or ""), reverse=True)
    return out


# ── Workout logging (manual entries via coach chat) ───────────────────────

_WORKOUT_ESTIMATOR_SYSTEM = """You classify free-form workout descriptions into
structured data. Return ONLY valid JSON, no prose.

User profile:
- Mateo, 34, 5'8" 169lb. Training 4-5x/week push/pull/legs with supersets.
- Back injury history — avoid loaded squats and heavy deadlifts.

Schema:
{
  "title": "short title (≤40 chars) like 'Push day' or 'Easy Z2 run'",
  "type": "push" | "pull" | "legs" | "upper" | "lower" | "full_body" | "cardio" | "mobility" | "other",
  "duration_min": number (minutes),
  "intensity": "low" | "moderate" | "high" | "max",
  "cal": number (estimated calories burned based on type/duration/intensity for a 169lb male),
  "strain_hint": number (Edwards TRIMP-style 0-21, rough guess: mobility<3, easy cardio 4-7, moderate 8-12, hard 13-17, max 18-21),
  "notes": "≤200 char summary of what was described",
  "exercises": [{"name": "string", "scheme": "sets x reps or duration"}, ...]  // empty array ok
}

Rules:
- Extract duration_min from phrases like "45 min", "half hour", "quick 20 min".
- If duration isn't stated, estimate from intensity+type (mobility 15, cardio 30, lifting 45-60).
- type: lifting references ("bench", "pull-ups", "squat pattern") → push/pull/legs/upper/lower/full_body. Running/cycling/rowing → cardio. Yoga/stretching → mobility.
- intensity: tune from verbs (crushed/went hard = high/max; easy/chill/recovery = low; default = moderate).
- Cap exercises at 10. Omit if not stated.
"""


def _call_workout_estimator(text: str) -> dict:
    resp = bedrock_runtime.invoke_model(
        modelId=ESTIMATOR_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "system": _WORKOUT_ESTIMATOR_SYSTEM,
            "messages": [{"role": "user", "content": f"Workout description:\n{text}"}],
        }),
    )
    payload = json.loads(resp["body"].read())
    reply = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            reply += block["text"]
    reply = reply.strip()
    if reply.startswith("```"):
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply, flags=re.DOTALL)
    return json.loads(reply)


def log_workout(text: str, date: Optional[str] = None) -> dict:
    """Estimate + persist a free-form workout description. Writes to
    WORKOUTS_TABLE with strava_id = 'manual_<ms>' so it coexists with real
    Strava-sourced rows."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")

    try:
        est = _call_workout_estimator(text)
    except Exception as e:
        logger.exception("workout estimator failed")
        raise RuntimeError(f"workout estimator failed: {e}")

    def _num(v, default=0):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return float(default)

    title = str(est.get("title") or text)[:40]
    wtype = str(est.get("type") or "other").lower()
    if wtype not in {"push", "pull", "legs", "upper", "lower", "full_body", "cardio", "mobility", "other"}:
        wtype = "other"
    intensity = str(est.get("intensity") or "moderate").lower()
    if intensity not in {"low", "moderate", "high", "max"}:
        intensity = "moderate"
    dur = int(_num(est.get("duration_min"), 30))
    cal = int(_num(est.get("cal"), 0))
    strain = _num(est.get("strain_hint"), 0)
    notes = str(est.get("notes") or text)[:200]

    exercises = []
    raw_ex = est.get("exercises")
    if isinstance(raw_ex, list):
        for ex in raw_ex[:10]:
            if not isinstance(ex, dict):
                continue
            name = str(ex.get("name", "")).strip()
            if not name:
                continue
            exercises.append({
                "name": name[:60],
                "scheme": str(ex.get("scheme", ""))[:40],
            })

    date = date or local_today_str()
    workout_id = f"manual_{int(time.time() * 1000)}"
    item = {
        "date": date,
        "strava_id": workout_id,
        "title": title,
        "type": wtype,
        "dur": dur,
        "cal": cal,
        "strain": strain,
        "intensity": intensity,
        "notes": notes,
        "exercises": exercises,
        "original_text": text[:2000],
        "source": "manual",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(get_table("WORKOUTS_TABLE"), item)
    return {
        "workout_id": workout_id,
        "title": title,
        "type": wtype,
        "duration_min": dur,
        "intensity": intensity,
        "cal": cal,
        "strain": strain,
    }


def delete_workout(workout_id: str, date: Optional[str] = None) -> dict:
    """Delete a workout row. Accepts manual_* or numeric strava IDs."""
    if not workout_id:
        raise ValueError("invalid workout_id")
    table = get_table("WORKOUTS_TABLE")
    date = date or local_today_str()

    existing = get_item(table, {"date": date, "strava_id": workout_id})
    if not existing:
        return {"ok": False, "reason": "not found", "workout_id": workout_id}
    table.delete_item(Key={"date": date, "strava_id": workout_id})
    return {"ok": True, "workout_id": workout_id}


# ── Meal validation (async second-pass) ───────────────────────────────────

_USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
_USDA_MIN_SCORE = 500.0


def _fetch_usda_nutrients(query: str, api_key: str) -> Optional[dict]:
    """Query USDA FoodData Central. Returns normalized macros for the top
    result if the score clears _USDA_MIN_SCORE, else None.

    Only Branded foods with `labelNutrients` (per-serving) are returned.
    SR Legacy / Foundation / FNDDS report nutrients per 100g, and without
    knowing the user's portion we can't scale those correctly — writing
    per-100g numbers as a meal total is worse than skipping the audit."""
    if not query or not api_key:
        return None
    try:
        params = urllib.parse.urlencode({
            "query": query[:200],
            "pageSize": "1",
            "api_key": api_key,
            "dataType": "Branded",
        })
        url = f"{_USDA_SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "mcfoxhealth-validator/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        logger.exception("USDA fetch failed for query=%s", query[:50])
        return None

    foods = data.get("foods") or []
    if not foods:
        return None
    top = foods[0]
    score = float(top.get("score") or 0)
    if score < _USDA_MIN_SCORE:
        return None

    # Branded foods expose `labelNutrients` with per-serving values that match
    # what's printed on the nutrition panel — the only USDA field safe to use
    # as a meal total without knowing the user's portion.
    label = top.get("labelNutrients")
    if not isinstance(label, dict):
        return None

    def _lbl(key):
        entry = label.get(key)
        if not isinstance(entry, dict):
            return None
        val = entry.get("value")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    cal = _lbl("calories")
    p = _lbl("protein")
    c = _lbl("carbohydrates")
    f = _lbl("fat")

    if cal is None and p is None and c is None and f is None:
        return None

    return {
        "cal": round(cal or 0, 1),
        "p": round(p or 0, 1),
        "c": round(c or 0, 1),
        "f": round(f or 0, 1),
        "description": str(top.get("description", ""))[:100],
        "score": score,
    }


_VALIDATOR_SYSTEM_APPEND = """

## Validator mode
You are auditing a prior estimate for the same meal. Be conservative:
- Prefer well-known brand/ingredient data over creative guesses.
- If the original estimate looks reasonable, return numbers close to it.
- Only deviate meaningfully when you're confident the prior estimate under- or over-counted.
- The top-level `assumptions` array should explicitly list what you changed vs. the prior estimate (e.g. "reduced protein from 25g to 20g — Oikos vanilla is 20g not 25g")."""


_VALIDATOR_DIFF_THRESHOLD_PCT = 0.05  # 5%
_VALIDATOR_DIFF_THRESHOLD_G = 5.0


def _macro_changed(prev: float, new: float) -> bool:
    try:
        prev_f = float(prev or 0)
        new_f = float(new or 0)
    except (TypeError, ValueError):
        return False
    diff = abs(new_f - prev_f)
    if diff >= _VALIDATOR_DIFF_THRESHOLD_G:
        return True
    if prev_f > 0 and diff / prev_f >= _VALIDATOR_DIFF_THRESHOLD_PCT:
        return True
    return False


def validate_meal(meal_id: str, date: Optional[str] = None) -> dict:
    """Idempotent second-pass validator. Called via async Lambda invoke from
    `save_meal`. Tries USDA first for brand/ingredient ground truth, falls
    back to a Claude audit pass. Silently PATCHes the row when macros differ
    meaningfully; always sets `validated_at` + `validated_source`."""
    if not meal_id or not meal_id.startswith("meal_"):
        return {"ok": False, "reason": "invalid meal_id", "meal_id": meal_id}

    table = get_table("NUTRITION_TABLE")
    date = date or local_today_str()
    existing = get_item(table, {"date": date, "meal_id": meal_id})
    if not existing:
        return {"ok": False, "reason": "not found", "meal_id": meal_id}
    if existing.get("validated_at"):
        return {"ok": True, "reason": "already validated", "meal_id": meal_id}

    prev = {
        "cal": float(existing.get("cal") or 0),
        "p": float(existing.get("p") or 0),
        "c": float(existing.get("c") or 0),
        "f": float(existing.get("f") or 0),
    }
    text = str(existing.get("original_text") or existing.get("name") or "").strip()

    source = None
    new_macros = None
    description = None

    # 1) Try USDA if we have an API key AND the description looks brandable.
    secrets = _get_secret_json()
    usda_key = secrets.get("usda_api_key") or os.environ.get("USDA_API_KEY", "")
    if usda_key and text:
        hit = _fetch_usda_nutrients(text, usda_key)
        if hit:
            new_macros = {"cal": hit["cal"], "p": hit["p"], "c": hit["c"], "f": hit["f"]}
            description = hit.get("description")
            source = "usda"

    # 2) Fall back to a Claude audit pass.
    if new_macros is None and text:
        try:
            audit_system = _ESTIMATOR_SYSTEM + _VALIDATOR_SYSTEM_APPEND
            resp = bedrock_runtime.invoke_model(
                modelId=ESTIMATOR_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1800,
                    "system": audit_system,
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"Prior estimate for this meal:\n"
                            f"- name: {existing.get('name', '')}\n"
                            f"- cal: {prev['cal']} | protein: {prev['p']}g | carbs: {prev['c']}g | fat: {prev['f']}g\n\n"
                            f"Original description:\n{text}\n\n"
                            f"Audit and return your corrected estimate in the same JSON schema."
                        ),
                    }],
                }),
            )
            payload = json.loads(resp["body"].read())
            reply = ""
            for block in payload.get("content", []):
                if block.get("type") == "text":
                    reply += block["text"]
            reply = reply.strip()
            if reply.startswith("```"):
                reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply, flags=re.DOTALL)
            data = json.loads(reply)

            def _n(v):
                try:
                    return round(float(v), 1)
                except (TypeError, ValueError):
                    return None

            new_macros = {
                "cal": _n(data.get("cal")),
                "p": _n(data.get("p")),
                "c": _n(data.get("c")),
                "f": _n(data.get("f")),
            }
            if any(v is None for v in new_macros.values()):
                new_macros = None
            else:
                source = "llm_audit"
        except Exception:
            logger.exception("llm audit failed for meal_id=%s", meal_id)
            new_macros = None

    now_iso = datetime.now(timezone.utc).isoformat()

    if new_macros is None or source is None:
        # Couldn't validate — mark checked so we don't loop forever.
        merged = {**existing, "validated_at": now_iso, "validated_source": "none"}
        put_item(table, merged)
        return {"ok": True, "meal_id": meal_id, "changed": False, "source": "none"}

    changed_fields = [k for k in ("cal", "p", "c", "f") if _macro_changed(prev[k], new_macros[k])]
    merged = {**existing, "validated_at": now_iso, "validated_source": source}

    if changed_fields:
        for k in ("cal", "p", "c", "f"):
            merged[k] = new_macros[k]
        diff_parts = []
        for k in changed_fields:
            label = {"cal": "cals", "p": "protein", "c": "carbs", "f": "fat"}[k]
            diff_parts.append(f"{label} {int(round(prev[k]))}→{int(round(new_macros[k]))}")
        src_label = "USDA" if source == "usda" else "LLM audit"
        audit_line = f"Validated against {src_label}: {', '.join(diff_parts)}"
        if description:
            audit_line += f" (match: {description})"
        existing_assumptions = list(existing.get("assumptions") or [])
        existing_assumptions.append(audit_line[:200])
        merged["assumptions"] = existing_assumptions[-10:]

    put_item(table, merged)
    return {
        "ok": True,
        "meal_id": meal_id,
        "changed": bool(changed_fields),
        "source": source,
        "changed_fields": changed_fields,
    }
