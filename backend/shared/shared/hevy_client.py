"""
Hevy API client — pulls strength/gym workouts from the Hevy public API (v1)
and maps them onto the fitness-workouts row schema used by the rest of the
stack (see functions/ingest/handler.py Strava path + shared/workout_service.py).

Hevy is the source of truth for gym/lifting sessions; Strava covers
cardio/outdoor. This module is HTTP-agnostic where it matters: the network
call is isolated in ``_http_get`` and can be swapped out in tests via the
``http_get`` argument to :func:`fetch_recent_workouts`, so no real API key is
required to exercise the parsing/mapping logic.

Hevy specifics:
  - Base URL: https://api.hevyapp.com, versioned under /v1
  - Auth: ``api-key`` request header (NOT a bearer token)
  - Endpoint: GET /v1/workouts?page=<n>&pageSize=<n>
      → {"page": 1, "page_count": N, "workouts": [ {workout}, ... ]}
  - A workout carries: id, title, start_time, end_time (ISO-8601),
    and exercises[] each with sets[] (weight_kg, reps, duration_seconds, rpe).
  - Hevy does NOT expose heart-rate streams, so strain is estimated from
    session duration + a moderate-intensity zone assumption rather than
    Edwards TRIMP over a HR stream.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from shared.scoring import classify_hr_zone, compute_strain

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


def _iso_date(ts: str) -> Optional[str]:
    """Extract a YYYY-MM-DD date key from a Hevy ISO-8601 timestamp.

    Hevy emits UTC timestamps like ``2026-06-30T18:04:11+00:00``. We key
    workout rows by local calendar date elsewhere in the stack; Hevy doesn't
    carry a local offset, so we take the date portion as-is. Off-by-one at
    midnight UTC is acceptable for a lifting log and matches how the Strava
    path keys on ``start_date_local[:10]``.
    """
    if not ts or not isinstance(ts, str):
        return None
    head = ts.strip()[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        return head
    return None


def _duration_min(workout: dict) -> float:
    """Minutes between start_time and end_time; 0 if unparseable."""
    start = workout.get("start_time")
    end = workout.get("end_time")
    if not start or not end:
        return 0.0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (ValueError, TypeError):
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


def workout_to_row(workout: dict) -> Optional[dict]:
    """Map a single Hevy workout dict onto the fitness-workouts row schema.

    Schema mirrors the Strava path (date + strava_id composite key). For Hevy
    rows the sort key holds the Hevy id prefixed with ``hevy_`` so it can't
    collide with a numeric Strava activity id, while still living in the same
    ``strava_id`` attribute the table is keyed on.

    Returns None when the workout has no usable id or date.
    """
    hevy_id = workout.get("id")
    date = _iso_date(workout.get("start_time"))
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
        "cal": 0,  # Hevy public API does not report calories
        "exercise_count": len(exercises),
        "set_count": set_count,
        "volume_lb": round(total_volume_lb, 1),
        "trimp": trimp,
        "strain": strain,
        "strain_estimated": True,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return row


def fetch_recent_workouts(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 3,
    http_get: Callable[[str, str], tuple] = _http_get,
) -> list:
    """Fetch the most recent Hevy workouts, mapped to workout rows.

    Pages newest-first (Hevy returns page 1 = most recent). Stops after
    ``max_pages`` to bound the poll — a daily cron only needs the last day or
    two, and this keeps us well inside Hevy's rate limits.

    ``http_get`` is injectable for testing: it must accept (url, api_key) and
    return (parsed_json_or_None, status_code). On any non-200 page we log and
    stop rather than raise, so a transient Hevy outage degrades to "no new
    workouts today" instead of crashing the ingest run.

    Raises ValueError only when no api_key is supplied — that's a
    configuration error the caller should surface loudly (missing secret).
    """
    if not api_key:
        raise ValueError("hevy api key is empty")

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
