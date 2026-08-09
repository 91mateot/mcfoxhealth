"""
Hevy API client — pulls strength/gym workouts from the Hevy public API (v1)
and maps them onto BOTH the fitness-workouts row schema (rolled-up session
row) AND the fitness-exercises row schema (one row per canonical exercise per
date) that the existing lift-learning engine — lift_compute, coach_context,
workout_proposer, api/handler — already reads.

The set-level structure Hevy sends is the whole point: mapping it onto the
exercise-row shape ``workout_service._write_exercise_rows`` produces lights up
e1RM, PR detection, stall detection, weekly volume, and the coach for free,
because those consumers already query ``fitness-exercises``.

This module is HTTP-agnostic where it matters: the network call is isolated in
``_http_get`` and can be swapped out in tests via the ``http_get`` argument to
the fetch helpers, so no real API key is required to exercise parsing/mapping.

Hevy specifics:
  - Base URL: https://api.hevyapp.com, versioned under /v1
  - Auth: ``api-key`` request header (NOT a bearer token)
  - GET /v1/workouts?page=&pageSize=          → {page, page_count, workouts[]}
  - GET /v1/workouts/events?since=&page=      → {page, page_count, events[]}
      each event is {type:"updated", workout:{...}} or
      {type:"deleted", id, deleted_at}
  - GET /v1/exercise_templates?page=&pageSize= → {page, page_count,
      exercise_templates[]}
  - GET /v1/body_measurements?page=&pageSize=  → {page, page_count,
      body_measurements[]}
  - A workout carries: id, title, description, routine_id, start_time,
    end_time, created_at, updated_at, and exercises[] each with sets[].
  - Set: {index, type, weight_kg, reps, distance_meters, duration_seconds,
    rpe, custom_metric} — all value fields nullable.
  - Hevy does NOT expose heart-rate streams or calories, so strain is
    estimated and calories are flagged unavailable rather than reported 0.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from shared.exercise_canonical import MUSCLE_GROUPS, canonicalize
from shared.scoring import compute_strain
from shared.timezone import (
    analysis_date_for_timestamp,
    parse_timestamp,
    temporal_metadata,
)

logger = logging.getLogger("hevy_client")

HEVY_API_BASE = "https://api.hevyapp.com"
HEVY_API_VERSION = "v1"

# Hevy has no HR data. Treat a logged lifting session as sitting around the
# top of Zone 2 for TRIMP purposes (weight_zone_factor ~= 2 min of load per
# real minute). This keeps daily strain non-zero and roughly comparable to a
# low-cardio Strava session without over-claiming intensity we can't measure.
_LIFT_ZONE_WEIGHT = 2.0

# Hevy "Workout" == strength. We tag every Hevy row as strength so the
# de-dupe guard can prefer Hevy for strength and Strava for cardio.
HEVY_STRENGTH_TYPE = "Workout"

KG_TO_LB = 2.20462262
CM_TO_IN = 0.393700787

# Every public Hevy list endpoint (workouts, workouts/events, body_measurements,
# exercise_templates) caps ``pageSize`` at 10 (per the OpenAPI spec). Sending a
# larger value returns HTTP 400, which our fetch helpers treat as a hard stop
# and degrade to an empty collection. That is exactly why the first live poll
# returned ``measurements_written: 0`` — fetch_body_measurements defaulted to
# pageSize=100 and every page 400'd. Clamp requests to this ceiling so a
# generous caller-supplied page_size never silently zeroes out a fetch.
HEVY_MAX_PAGE_SIZE = 10


def _clamp_page_size(page_size: int) -> int:
    """Clamp a requested page size to Hevy's per-endpoint maximum (10). A value
    above the cap makes Hevy return 400, so we quietly reduce it rather than let
    the whole fetch fail."""
    try:
        ps = int(page_size)
    except (TypeError, ValueError):
        return HEVY_MAX_PAGE_SIZE
    if ps < 1:
        return 1
    return min(ps, HEVY_MAX_PAGE_SIZE)

# Exercise-template cache lives in fitness-user-config under this key. Templates
# are near-static (~226 rows on a typical account), so we refresh at most weekly.
TEMPLATE_CACHE_KEY = "hevy_exercise_templates"
TEMPLATE_CACHE_MAX_AGE_SEC = 7 * 24 * 3600

# Incremental-sync watermark key in fitness-user-config.
LAST_SYNC_KEY = "hevy_last_sync"


# ── Muscle-group mapping ────────────────────────────────────────────────────
#
# Hevy exposes a 20-value MuscleGroup enum. The rest of this app reasons over a
# 10-value vocabulary (shared.exercise_canonical.MUSCLE_GROUPS). This table maps
# every Hevy value onto the app vocabulary explicitly — no guessing, no silent
# "other" for a value we simply forgot to handle. The raw Hevy value is ALSO
# preserved on the exercise row (as ``hevy_muscle_group``) so nothing is lost.
#
#   Hevy enum       → app group   rationale
#   abdominals      → core        trunk flexion
#   shoulders       → shoulders   1:1
#   biceps          → arms        app folds bi/tri/forearm into "arms"
#   triceps         → arms
#   forearms        → arms
#   quadriceps      → legs
#   hamstrings      → legs
#   calves          → legs
#   glutes          → glutes      app tracks glutes distinctly
#   abductors       → glutes      hip abduction is glute-dominant (matches the
#                                 existing LLM parser: hip_abductor → glutes)
#   adductors       → legs        inner thigh reads as leg volume, not glute
#   lats            → back
#   upper_back      → back
#   traps           → back
#   lower_back      → back
#   chest           → chest       1:1
#   cardio          → cardio      1:1
#   neck            → other       no dedicated bucket
#   full_body       → other       no single group applies
#   other           → other       1:1
_HEVY_MUSCLE_GROUP_MAP = {
    "abdominals": "core",
    "shoulders": "shoulders",
    "biceps": "arms",
    "triceps": "arms",
    "forearms": "arms",
    "quadriceps": "legs",
    "hamstrings": "legs",
    "calves": "legs",
    "glutes": "glutes",
    "abductors": "glutes",
    "adductors": "legs",
    "lats": "back",
    "upper_back": "back",
    "traps": "back",
    "lower_back": "back",
    "chest": "chest",
    "cardio": "cardio",
    "neck": "other",
    "full_body": "other",
    "other": "other",
}


def map_muscle_group(hevy_value: Optional[str]) -> str:
    """Map a Hevy primary_muscle_group enum value onto the app vocabulary.

    Falls back to "other" for unknown/missing values — never raises. The
    result is always a member of shared.exercise_canonical.MUSCLE_GROUPS.
    """
    if not hevy_value or not isinstance(hevy_value, str):
        return "other"
    mapped = _HEVY_MUSCLE_GROUP_MAP.get(hevy_value.strip().lower(), "other")
    # Defensive: guarantee membership in the app vocabulary.
    return mapped if mapped in MUSCLE_GROUPS else "other"


# ── HTTP ────────────────────────────────────────────────────────────────────

def _http_get(url: str, api_key: str, timeout: int = 15):
    """Perform the actual HTTP GET against the Hevy API.

    Returns (parsed_json_or_None, http_status). Network/parse failures are
    surfaced as (None, status_code) so callers can log-and-continue rather
    than crash the whole ingest run.
    """
    req = urllib.request.Request(url, headers={"api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:  # noqa: BLE001 — network/DNS/timeout: log-and-continue at call site
        return None, -1


def _v1(path: str) -> str:
    return f"{HEVY_API_BASE}/{HEVY_API_VERSION}/{path.lstrip('/')}"


# ── Timestamp / duration helpers ────────────────────────────────────────────

def _iso_date(ts, *, allow_naive_source_date: bool = False) -> Optional[str]:
    """Derive a Hevy analysis date without truncating a UTC timestamp.

    Hevy workout timestamps are absolute instants and do not carry trustworthy
    event-local timezone context, so aware values are converted to the
    configured home timezone. Date-only body-measurement values may retain
    their explicit source date because no absolute instant is present.
    """
    return analysis_date_for_timestamp(
        ts,
        allow_naive_source_date=allow_naive_source_date,
    )


def _duration_min(workout: dict) -> float:
    """Minutes between start_time and end_time; 0 if unparseable."""
    start = workout.get("start_time")
    end = workout.get("end_time")
    if not start or not end:
        return 0.0
    s = parse_timestamp(start)
    e = parse_timestamp(end)
    if s is None or e is None:
        return 0.0
    if s.tzinfo is None or s.utcoffset() is None or e.tzinfo is None or e.utcoffset() is None:
        return 0.0
    delta = (e - s).total_seconds() / 60.0
    return round(delta, 1) if delta > 0 else 0.0


def _estimate_lift_strain(duration_min: float) -> tuple:
    """Estimate (trimp, strain) for a HR-less lifting session.

    Uses the same Edwards-style weighting the Strava fallback uses, assuming
    the session sits around Zone 2 (moderate) for its logged duration. This
    is deliberately conservative — real lifting strain is spiky and we have
    no HR to prove it, so we don't inflate it toward cardio numbers.
    """
    if duration_min <= 0:
        return 0.0, 0.0
    trimp = round(duration_min * _LIFT_ZONE_WEIGHT, 1)
    return trimp, compute_strain(trimp)


def _num(v):
    """Coerce to float or None (Hevy value fields are all nullable)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Set / exercise mapping ──────────────────────────────────────────────────

def _map_set(s: dict) -> Optional[dict]:
    """Map one Hevy set onto the app's set-dict shape.

    Base shape matches what workout_service produces: {weight, reps, unit,
    warmup}. Weight is converted kg→lb. ``warmup`` is True ONLY for
    type=="warmup" — dropset/failure sets are real working sets and must still
    count toward top_weight / volume / e1RM. The Hevy ``type`` is preserved
    verbatim so dropset/failure information is not lost, and rpe /
    duration_seconds / distance_meters / custom_metric are carried when present.
    """
    if not isinstance(s, dict):
        return None
    set_type = str(s.get("type") or "normal").strip().lower()
    weight_kg = _num(s.get("weight_kg"))
    reps = s.get("reps")
    try:
        reps_int = int(reps) if reps is not None else 0
    except (TypeError, ValueError):
        reps_int = 0

    out = {
        "weight": round((weight_kg or 0.0) * KG_TO_LB, 1),
        "reps": reps_int,
        "unit": "lbs",
        "warmup": set_type == "warmup",
        # Preserve Hevy's set type verbatim so dropset/failure isn't erased.
        "type": set_type,
    }

    rpe = _num(s.get("rpe"))
    if rpe is not None:
        out["rpe"] = round(rpe, 1)
    dur = s.get("duration_seconds")
    if dur is not None:
        try:
            out["duration_sec"] = int(dur)
        except (TypeError, ValueError):
            pass
    dist = _num(s.get("distance_meters"))
    if dist is not None:
        out["distance_meters"] = round(dist, 1)
    cm = s.get("custom_metric")
    if cm is not None:
        out["custom_metric"] = cm
    return out


def workout_to_exercise_rows(workout: dict, templates: Optional[dict] = None) -> list:
    """Map a Hevy workout's ``exercises[]`` into exercise-row dicts shaped
    EXACTLY like ``workout_service._write_exercise_rows`` consumes.

    ``templates`` is the exercise-template cache (id → template dict) used to
    resolve real muscle groups. When absent/unknown, muscle_group degrades to
    "other" — never crashes.

    Returns a list of dicts with keys: canonical, name, muscle_group,
    hevy_muscle_group, sets[], note (optional), superset_with (optional),
    superset_group (optional, sorted list of the other member canonicals for
    3+ member groups), exercise_template_id (optional). The date is applied by the writer, matching
    how workout_service passes ``date`` separately to _write_exercise_rows.
    """
    templates = templates or {}
    exercises = workout.get("exercises") or []

    # First pass: build rows + record the superset group id → list of canonicals
    # so we can resolve superset_with in both directions afterward, mirroring how
    # the LLM parser sets superset_with on both paired exercises.
    #
    # Field name: the LIVE Hevy API returns ``superset_id`` (SINGULAR) on each
    # exercise. Hevy's published OpenAPI spec documents it as ``supersets_id``
    # (plural) — the spec is WRONG. We prefer the real key and fall back to the
    # spec key so this keeps working if Hevy ever conforms its API to its spec.
    # ``superset_id`` values start at 0, so grouping MUST be tested with
    # ``is not None`` — a truthiness check would silently drop group 0.
    rows = []
    superset_members: dict = {}
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        title = str(ex.get("title") or "").strip()
        if not title:
            continue
        canonical = canonicalize(title)
        template_id = ex.get("exercise_template_id")
        tmpl = templates.get(template_id) if template_id else None
        hevy_mg = (tmpl or {}).get("primary_muscle_group")

        mapped_sets = []
        for s in ex.get("sets") or []:
            m = _map_set(s)
            if m is not None:
                mapped_sets.append(m)

        row = {
            "canonical": canonical,
            "name": title[:80],
            "muscle_group": map_muscle_group(hevy_mg),
            "sets": mapped_sets,
        }
        if hevy_mg:
            row["hevy_muscle_group"] = hevy_mg
        if template_id:
            row["exercise_template_id"] = template_id
        note = ex.get("notes")
        if isinstance(note, str) and note.strip():
            row["note"] = note.strip()[:200]

        # Prefer the real live-API key (``superset_id``); fall back to the
        # spec's ``supersets_id``. ``is not None`` — group 0 is valid.
        sid = ex.get("superset_id")
        if sid is None:
            sid = ex.get("supersets_id")
        if sid is not None:
            superset_members.setdefault(sid, []).append(canonical)

        row["_superset_id"] = sid
        rows.append(row)

    # Second pass: resolve superset_with + superset_group. A group can hold 2+
    # exercises. ``superset_with`` stays a single canonical string for backward
    # compatibility with the lift engine, the LLM-parser convention, and the
    # frontend (src/types.ts / WorkoutDetail.tsx), which all treat it as a
    # string. ``superset_group`` is added alongside as the sorted list of ALL
    # other members' canonicals, so 3+ member groups lose no information.
    for row in rows:
        sid = row.pop("_superset_id", None)
        if sid is None:
            continue
        partners = sorted(
            c for c in superset_members.get(sid, []) if c != row["canonical"]
        )
        if partners:
            row["superset_with"] = partners[0]
            row["superset_group"] = partners

    return rows


def _set_type_breakdown(exercises: list) -> dict:
    """Count sets by Hevy type across the whole session (normal/warmup/
    dropset/failure/…). Useful session-level texture the rolled-up row
    currently discards."""
    breakdown: dict = {}
    for ex in exercises or []:
        for s in ex.get("sets") or []:
            t = str((s or {}).get("type") or "normal").strip().lower()
            breakdown[t] = breakdown.get(t, 0) + 1
    return breakdown


def _rpe_stats(exercises: list) -> dict:
    """avg_rpe / max_rpe across WORKING sets (type != warmup) that carry an
    RPE. Returns {} when no RPE is present so we never fabricate intensity."""
    rpes = []
    for ex in exercises or []:
        for s in ex.get("sets") or []:
            if str((s or {}).get("type") or "normal").strip().lower() == "warmup":
                continue
            rpe = _num((s or {}).get("rpe"))
            if rpe is not None:
                rpes.append(rpe)
    if not rpes:
        return {}
    return {"avg_rpe": round(sum(rpes) / len(rpes), 1), "max_rpe": round(max(rpes), 1)}


def workout_to_row(workout: dict) -> Optional[dict]:
    """Map a single Hevy workout dict onto the fitness-workouts row schema.

    Schema mirrors the Strava path (date + strava_id composite key). For Hevy
    rows the sort key holds the Hevy id prefixed with ``hevy_`` so it can't
    collide with a numeric Strava activity id, while still living in the same
    ``strava_id`` attribute the table is keyed on.

    Preserves the richer session-level fields Hevy sends that the earlier
    roll-up discarded: description (subjective session notes), routine_id,
    start_time, end_time, updated_at, a per-set-type breakdown, and
    avg_rpe/max_rpe when RPE is present.

    Returns None when the workout has no usable id or date.
    """
    hevy_id = workout.get("id")
    source_start_time = workout.get("start_time")
    temporal = temporal_metadata(source_start_time)
    date = temporal.get("analysis_date")
    if not hevy_id or not date:
        return None

    duration_min = _duration_min(workout)
    exercises = workout.get("exercises") or []

    # Volume is a cheap proxy for how much work was done — sum(reps * weight)
    # across all sets, converted to lbs to match the rest of the app.
    total_volume_lb = 0.0
    set_count = 0
    for ex in exercises:
        for s in ex.get("sets") or []:
            reps = s.get("reps") or 0
            weight_kg = s.get("weight_kg") or 0
            try:
                total_volume_lb += float(reps) * float(weight_kg) * KG_TO_LB
                set_count += 1
            except (TypeError, ValueError):
                continue

    trimp, strain = _estimate_lift_strain(duration_min)

    row = {
        "date": date,
        "strava_id": f"hevy_{hevy_id}",
        "hevy_id": str(hevy_id),
        "title": (workout.get("title") or "Workout")[:120],
        "type": HEVY_STRENGTH_TYPE,
        "source": "hevy",
        "dur": round(duration_min),
        # Hevy's public API reports NO calories. Emitting a bare 0 reads as
        # "burned nothing" and silently drags energy-balance math down (same
        # class of bug as the nutrition dead-zero). Flag it honestly instead.
        "cal": 0,
        "cal_unavailable": True,
        "exercise_count": len(exercises),
        "set_count": set_count,
        "volume_lb": round(total_volume_lb, 1),
        "trimp": trimp,
        "strain": strain,
        "strain_estimated": True,
        "set_type_breakdown": _set_type_breakdown(exercises),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    row.update(temporal)

    # Keep the vendor values verbatim even though start_time/end_time already
    # exist for backward compatibility. The explicit source_* names make it
    # clear these are preserved source instants, not fabricated event-local
    # times. analysis_timezone records the home-timezone fallback separately.
    row["source_start_time"] = source_start_time
    source_end_time = workout.get("end_time")
    if source_end_time:
        row["source_end_time"] = source_end_time

    # Session-level fields that used to be discarded. ``description`` is
    # Mateo's free-text "went hard today" note — high-value subjective load.
    description = workout.get("description")
    if isinstance(description, str) and description.strip():
        row["description"] = description.strip()[:2000]
    for src_key, dst_key in (
        ("routine_id", "routine_id"),
        ("start_time", "start_time"),
        ("end_time", "end_time"),
        ("updated_at", "updated_at"),
    ):
        val = workout.get(src_key)
        if val:
            row[dst_key] = val

    row.update(_rpe_stats(exercises))
    return row


# ── Body measurements ───────────────────────────────────────────────────────

def body_measurement_to_metrics(measurement: dict) -> list:
    """Map a Hevy body_measurement onto health-metric samples.

    Returns a list of (metric_source, unit, kind, date, value) tuples ready to
    be routed through the ingest handler's merge/ordering-guard helpers. All
    are "last"-kind metrics (a measurement is a point-in-time reading, not a
    cumulative daily total). cm→in and kg→lb conversions match app conventions.
    Unknown/missing fields are simply skipped — never crashes.
    """
    if not isinstance(measurement, dict):
        return []
    date = _iso_date(measurement.get("date"), allow_naive_source_date=True)
    if not date:
        return []

    out = []

    def add(metric_source, unit, value, scale=1.0):
        v = _num(value)
        if v is None:
            return
        out.append((metric_source, unit, "last", date, round(v * scale, 2)))

    # Mass metrics → lb.
    add("weight#hevy", "lb", measurement.get("weight_kg"), KG_TO_LB)
    add("lean_mass#hevy", "lb", measurement.get("lean_mass_kg"), KG_TO_LB)
    # Body fat percent — unit is percent, no conversion.
    add("bodyfat_hevy#hevy", "pct", measurement.get("fat_percent"))

    # Circumference metrics → inches. Suffix each with #hevy so they stay
    # distinct from hand-typed check-in values.
    cm_fields = {
        "neck_cm": "neck",
        "shoulder_cm": "shoulder",
        "chest_cm": "chest",
        "left_bicep_cm": "left_bicep",
        "right_bicep_cm": "right_bicep",
        "left_forearm_cm": "left_forearm",
        "right_forearm_cm": "right_forearm",
        "abdomen": "abdomen",
        "waist": "waist",
        "hips": "hips",
        "left_thigh": "left_thigh",
        "right_thigh": "right_thigh",
        "left_calf": "left_calf",
        "right_calf": "right_calf",
    }
    for field, label in cm_fields.items():
        add(f"{label}#hevy", "in", measurement.get(field), CM_TO_IN)

    return out


# ── Paginated fetch helper ──────────────────────────────────────────────────

def _fetch_paginated(
    path: str,
    api_key: str,
    collection_key: str,
    http_get: Callable[[str, str], tuple],
    page_size: int = 100,
    max_pages: int = 20,
    extra_query: Optional[dict] = None,
) -> list:
    """Walk a Hevy paginated endpoint fully (or until max_pages), returning the
    concatenated collection. Stops on any non-200, on an empty page, or once
    ``page >= page_count``. Never raises — degrades to whatever was collected.
    """
    items: list = []
    page_size = _clamp_page_size(page_size)
    for page in range(1, max_pages + 1):
        query = {"page": page, "pageSize": page_size}
        if extra_query:
            query.update({k: v for k, v in extra_query.items() if v is not None})
        url = _v1(path) + "?" + urllib.parse.urlencode(query)
        body, status = http_get(url, api_key)
        if status != 200 or not isinstance(body, dict):
            logger.warning("hevy %s page %s returned status %s — stopping", path, page, status)
            break
        chunk = body.get(collection_key) or []
        if not chunk:
            break
        items.extend(chunk)
        page_count = body.get("page_count")
        if isinstance(page_count, int) and page >= page_count:
            break
        if len(chunk) < page_size:
            break
    return items


# ── Exercise-template cache ─────────────────────────────────────────────────

def fetch_exercise_templates(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 30,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> dict:
    """Fetch ALL exercise templates and return id → template dict.

    Each template dict holds {title, type, primary_muscle_group,
    secondary_muscle_groups, equipment_category, is_custom}. Degrades to {} on
    API failure — callers then fall back to muscle_group "other".
    """
    if not api_key:
        raise ValueError("hevy api key is empty")
    raw = _fetch_paginated(
        "exercise_templates", api_key, "exercise_templates",
        http_get, page_size=page_size, max_pages=max_pages,
    )
    out: dict = {}
    for t in raw:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        if not tid:
            continue
        out[tid] = {
            "title": t.get("title"),
            "type": t.get("type"),
            "primary_muscle_group": t.get("primary_muscle_group"),
            "secondary_muscle_groups": t.get("secondary_muscle_groups") or [],
            "equipment_category": t.get("equipment_category"),
            "is_custom": bool(t.get("is_custom")),
        }
    return out


def templates_cache_is_stale(cache_row: Optional[dict], now_ts: Optional[float] = None) -> bool:
    """True when the cached template row is missing, empty, or older than
    TEMPLATE_CACHE_MAX_AGE_SEC. Templates are near-static, so we avoid
    re-fetching ~226 rows on every poll."""
    if not cache_row or not cache_row.get("templates"):
        return True
    fetched_at = cache_row.get("fetched_at")
    if not fetched_at:
        return True
    try:
        fetched_dt = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    now = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    return (now - fetched_dt.timestamp()) > TEMPLATE_CACHE_MAX_AGE_SEC


# ── Incremental sync via events ─────────────────────────────────────────────

def fetch_workout_events(
    api_key: str,
    since: str,
    page_size: int = 10,
    max_pages: int = 20,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> dict:
    """Fetch workout events since ``since`` (ISO-8601), classifying them into
    updated workouts and deleted ids.

    Returns {"updated": [workout, ...], "deleted": [hevy_id, ...]}. The events
    endpoint is newest-first and paged; we walk it fully (bounded by
    max_pages). Degrades to empty lists on API failure.
    """
    if not api_key:
        raise ValueError("hevy api key is empty")
    events = _fetch_paginated(
        "workouts/events", api_key, "events",
        http_get, page_size=page_size, max_pages=max_pages,
        extra_query={"since": since},
    )
    updated = []
    deleted = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("type") or "").strip().lower()
        if etype == "deleted":
            eid = ev.get("id")
            if eid:
                deleted.append(str(eid))
        elif etype == "updated":
            w = ev.get("workout")
            if isinstance(w, dict):
                updated.append(w)
    return {"updated": updated, "deleted": deleted}


# ── Recent-workout page walk (cold-start fallback) ──────────────────────────

def fetch_recent_workouts(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 3,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> list:
    """Fetch the most recent Hevy workouts, mapped to rolled-up workout rows.

    Kept as the cold-start / fallback path when no incremental watermark
    exists. Pages newest-first (Hevy returns page 1 = most recent). Stops after
    ``max_pages`` to bound the poll.

    ``http_get`` is injectable for testing: it must accept (url, api_key) and
    return (parsed_json_or_None, status_code). On any non-200 page we log and
    stop rather than raise, so a transient Hevy outage degrades to "no new
    workouts today" instead of crashing the ingest run.

    Raises ValueError only when no api_key is supplied — a configuration error
    the caller should surface loudly (missing secret).
    """
    if not api_key:
        raise ValueError("hevy api key is empty")

    page_size = _clamp_page_size(page_size)
    rows: list = []
    for page in range(1, max_pages + 1):
        url = f"{HEVY_API_BASE}/{HEVY_API_VERSION}/workouts?page={page}&pageSize={page_size}"
        body, status = http_get(url, api_key)
        if status != 200 or not isinstance(body, dict):
            logger.warning("hevy fetch page %s returned status %s — stopping", page, status)
            break
        workouts = body.get("workouts") or []
        if not workouts:
            break
        for w in workouts:
            row = workout_to_row(w)
            if row is not None:
                rows.append(row)
        page_count = body.get("page_count")
        if isinstance(page_count, int) and page >= page_count:
            break
        if len(workouts) < page_size:
            break
    return rows


def fetch_recent_workouts_full(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 3,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> list:
    """Like fetch_recent_workouts, but returns the RAW workout dicts (not the
    rolled-up rows) so the caller can also extract exercise-level rows and
    session enrichment. Used by the ingest handler's cold-start path.
    """
    if not api_key:
        raise ValueError("hevy api key is empty")

    page_size = _clamp_page_size(page_size)
    workouts: list = []
    for page in range(1, max_pages + 1):
        url = f"{HEVY_API_BASE}/{HEVY_API_VERSION}/workouts?page={page}&pageSize={page_size}"
        body, status = http_get(url, api_key)
        if status != 200 or not isinstance(body, dict):
            logger.warning("hevy fetch page %s returned status %s — stopping", page, status)
            break
        chunk = body.get("workouts") or []
        if not chunk:
            break
        workouts.extend(chunk)
        page_count = body.get("page_count")
        if isinstance(page_count, int) and page >= page_count:
            break
        if len(chunk) < page_size:
            break
    return workouts


def fetch_body_measurements(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 10,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> list:
    """Fetch all body measurements as raw Hevy dicts. Degrades to [] on error.

    ``page_size`` is clamped to Hevy's per-endpoint max (10) by _fetch_paginated;
    the default here already sits at the ceiling so the request is always valid.
    """
    if not api_key:
        raise ValueError("hevy api key is empty")
    return _fetch_paginated(
        "body_measurements", api_key, "body_measurements",
        http_get, page_size=page_size, max_pages=max_pages,
    )
