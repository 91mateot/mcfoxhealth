"""
Nutrition service — pure business logic for meals, water, journal, and estimation.

These functions are HTTP-agnostic. They're called from:
  - functions/nutrition/handler.py (the public REST API)
  - functions/coach/app.py         (Bedrock tool-use handlers)
"""

import ipaddress
import json
import os
import re
import socket
import urllib.parse
import urllib.request
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Optional

import boto3

from shared.db import get_table, put_item, get_item, query_items
from shared.timezone import local_now, local_today_str

bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-west-2")

ESTIMATOR_MODEL_ID = os.environ.get("ESTIMATOR_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


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
}"""


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


def _call_estimator(text: str, url_text: str) -> dict:
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


def estimate_meal(text: str, known_hint: str = "") -> dict:
    """Estimate macros for free-form text. Returns estimate dict (not saved).

    Fast path: known-foods dict. Slow path: Bedrock.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")

    known_key = (known_hint or "").lower().strip()
    if not known_key:
        lower = text.lower()
        for k in KNOWN_FOODS:
            if k in lower:
                known_key = k
                break
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
    for match in re.finditer(r"https?://\S+", text):
        candidate = match.group(0).rstrip(".,;:)]\"'")
        fetched = _fetch_url_text(candidate)
        if fetched:
            source_url = candidate
            url_text = fetched
            break

    estimate = _call_estimator(text, url_text)
    if source_url and "sourceUrl" not in estimate:
        estimate["sourceUrl"] = source_url
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
    now_hour = local_now().hour
    time_str = body.get("time") or f"{now_hour}:00"

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

    put_item(table, item)

    if water_oz is not None:
        put_item(table, {
            "date": date,
            "meal_id": f"water_{int(time.time() * 1000)}",
            "oz": water_oz,
            "source_meal_id": meal_id,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        })

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
) -> dict:
    journal_table = get_table("JOURNAL_TABLE")
    date = date or local_today_str()

    item = {
        "date": date,
        "tags": list(tags or []),
        "mood": mood,
        "stress": stress,
        "soreness": soreness,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(journal_table, item)
    return {"status": "saved", "date": date}


def get_recent_meals(days: int = 1) -> list:
    """Return meal rows for the last `days` days (today + days-1 prior),
    sorted by date desc then time desc. Water rows excluded."""
    table = get_table("NUTRITION_TABLE")
    today_dt = local_now()
    out = []
    for i in range(max(1, days)):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rows = query_items(table, "date", d) or []
        for m in rows:
            if not m.get("meal_id", "").startswith("meal_"):
                continue
            out.append({
                "date": d,
                "meal_id": m.get("meal_id"),
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
    out.sort(key=lambda m: (m["date"], m.get("time") or ""), reverse=True)
    return out
