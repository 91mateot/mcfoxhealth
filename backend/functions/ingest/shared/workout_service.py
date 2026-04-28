"""
Workout service — pure business logic for lift annotation and exercise storage.

These functions are HTTP-agnostic. They're called from:
  - functions/nutrition/handler.py (the REST /api/workout/.../annotate route)
  - functions/coach/app.py         (Bedrock tool-use handler)

The parser turns free-form lift notes into structured sets and mirrors each
exercise to ExercisesTable so the compute layer can compute PRs, e1RM trends,
and correlations.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3

from shared.db import get_table, put_item, get_item, query_items
from shared.timezone import local_now, local_today_str

logger = logging.getLogger("workout_service")

bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-west-2")
ESTIMATOR_MODEL_ID = os.environ.get("ESTIMATOR_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


# ── Exercise canonicalization ─────────────────────────────────────────────

MUSCLE_GROUPS = {"chest", "back", "shoulders", "arms", "legs", "core", "glutes", "cardio", "mobility", "other"}

# The LLM is expected to canonicalize, but we normalize unknown names too.
_SYNONYMS = {
    "bench": "bench_press",
    "bench press": "bench_press",
    "barbell bench": "bench_press",
    "bb bench": "bench_press",
    "dumbbell bench": "db_bench_press",
    "db bench": "db_bench_press",
    "incline bench": "incline_bench_press",
    "incline db": "incline_db_press",
    "incline dumbbell": "incline_db_press",
    "ohp": "overhead_press",
    "press": "overhead_press",
    "overhead press": "overhead_press",
    "squat": "back_squat",
    "back squat": "back_squat",
    "front squat": "front_squat",
    "dl": "deadlift",
    "deadlift": "deadlift",
    "rdl": "romanian_deadlift",
    "romanian deadlift": "romanian_deadlift",
    "row": "barbell_row",
    "barbell row": "barbell_row",
    "bb row": "barbell_row",
    "seated row": "seated_cable_row",
    "seated back row": "seated_cable_row",
    "seated cable row": "seated_cable_row",
    "pullup": "pull_up",
    "pull-up": "pull_up",
    "pull up": "pull_up",
    "chin up": "chin_up",
    "lat pulldown": "lat_pulldown",
    "pulldown": "lat_pulldown",
    "dip": "dip",
    "dips": "dip",
    "leg press": "leg_press",
    "leg curl": "leg_curl",
    "leg extension": "leg_extension",
    "hip abductor": "hip_abductor",
    "hip abductors": "hip_abductor",
    "hip thrust": "hip_thrust",
    "plank": "plank",
    "curl": "biceps_curl",
    "bicep curl": "biceps_curl",
    "biceps curl": "biceps_curl",
    "tricep pushdown": "triceps_pushdown",
    "pushdown": "triceps_pushdown",
    "lateral raise": "lateral_raise",
    "side raise": "lateral_raise",
    "face pull": "face_pull",
    "single arm march": "single_arm_march",
    "single-arm march": "single_arm_march",
    "cable crossover": "cable_crossover",
    "back cable crossover": "cable_crossover",
}


def _canonicalize(name: str) -> str:
    """Slugify an exercise name. Looks up synonyms first; falls back to a
    deterministic lowercase/underscore slug."""
    if not name:
        return "unknown"
    lower = name.strip().lower()
    if lower in _SYNONYMS:
        return _SYNONYMS[lower]
    # Try stripping qualifiers (barbell/dumbbell/cable) to hit the synonyms map.
    stripped = re.sub(r"^(barbell|dumbbell|cable|machine|bb|db)\s+", "", lower)
    if stripped in _SYNONYMS:
        return _SYNONYMS[stripped]
    # Deterministic slug fallback.
    slug = re.sub(r"[^\w\s-]", "", lower)
    slug = re.sub(r"\s+", "_", slug).strip("_")
    return slug[:50] or "unknown"


# ── Lift parser (Bedrock) ─────────────────────────────────────────────────

_LIFT_PARSER_SYSTEM = """You convert free-form workout notes into structured JSON.

User profile:
- Mateo, 34, 5'8" 169lb. Training 4-5x/week push/pull/legs with supersets.
- Back injury history — tracks back_flare carefully.
- Weights are ALWAYS lbs unless he says kg.

Return ONLY valid JSON, no prose. Schema:

{
  "exercises": [
    {
      "name": "human-readable display name (≤40 chars)",
      "canonical": "lowercase_snake_case slug for joining across sessions",
      "muscle_group": "chest|back|shoulders|arms|legs|glutes|core|cardio|mobility|other",
      "sets": [
        {"reps": <int>, "weight": <number>, "unit": "lbs", "warmup": <bool optional>, "duration_sec": <int optional>}
      ],
      "superset_with": "<canonical of paired exercise> or null",
      "note": "≤140 char per-exercise note (user-provided only, no invention)"
    }
  ],
  "cardio_intervals": [
    {"name": "string", "params": { /* free-form key:value pairs */ }, "duration_min": <number or null>}
  ],
  "session_notes": "≤300 char summary of body/soreness/session-level notes the user wrote",
  "suggested_journal_tags": ["tag1", ...]
}

Rules:
- **Weights**: strip "lbs"/"lb"/"#" suffixes. Numbers only. If a weight is obviously a typo ("190lbsp") — treat as 190.
- **Reps**: if unstated but an exercise is performed (e.g. "plank 30 seconds"), use duration_sec and reps=1.
- **Ramps**: "increasing from 80 to 100 by 10, 10 reps each" → three sets: [80x10, 90x10, 100x10]. Mark `ramp: true` on the sets if you want.
- **Drop sets**: weights going DOWN in a single line → single-set notation with dropset structure. Create one set per rung.
- **Warmup**: the first working-weight set is usually NOT warmup; explicit "warmup" label IS. A light first set that ramps up sharply — mark warmup.
- **Supersets**: when the user indents a second exercise with "Superset" or "paired with", set `superset_with` on BOTH exercises to each other's canonical.
- **Cardio**: treadmill, bike, skierg, erg, rower, walk, run → cardio_intervals. Strength machines (leg press, lat pulldown) → exercises.
  - Cardio params are free-form: distance_mi, distance_m, speed_mph, grade_pct, gear, pace, duration_sec. Include what the user stated.
- **Session notes**: ONLY user-provided notes about how the body felt (soreness, flare, fatigue, pain). Don't summarize the workout itself.
- **suggested_journal_tags**: map session notes to valid tags if obvious: back_flare, sick, stress. Empty array if nothing.
- **Canonical slugs**: use the most specific synonym you know.
  - bench press → bench_press | db bench → db_bench_press | incline db press → incline_db_press
  - overhead press/OHP → overhead_press
  - back squat → back_squat | front squat → front_squat
  - deadlift/DL → deadlift | RDL → romanian_deadlift
  - barbell row → barbell_row | seated cable row → seated_cable_row | pendlay row → pendlay_row
  - pull-up → pull_up | chin-up → chin_up | lat pulldown → lat_pulldown
  - dip → dip | leg press → leg_press | leg curl → leg_curl | leg extension → leg_extension
  - hip thrust → hip_thrust | hip abductor → hip_abductor
  - biceps curl → biceps_curl | triceps pushdown → triceps_pushdown
  - lateral raise → lateral_raise | face pull → face_pull
  - plank → plank | single arm march → single_arm_march | cable crossover → cable_crossover
- **Muscle group** per canonical:
  - bench_press/db_bench_press/incline_*_press → chest
  - overhead_press/lateral_raise/face_pull → shoulders
  - lat_pulldown/pull_up/chin_up/*_row → back
  - cable_crossover → chest OR back depending on movement; use "chest" if pushing forward, "back" if pulling back
  - back_squat/front_squat/leg_press/leg_curl/leg_extension → legs
  - hip_thrust/hip_abductor → glutes
  - deadlift/romanian_deadlift → back (compound pull; flag back_safety)
  - biceps_curl/triceps_pushdown → arms
  - plank/single_arm_march → core
- **Ambiguity**: if a line is too vague to parse, OMIT it from sets but add a note. Never invent numbers.

Example input:
'''
- Seated Back row: 90lbs for 10 reps, then 140lbs for 10 reps twice
    - Superset with single arm marches with 62lbs. 20 steps each side
- Lat pulldown: 90 lbs for 10 reps. 140lbs for 10 reps. 190lbsp
    - Superset with plank for 30 seconds
- Hip abductors, increasing from 80lbs to 100lbs every set by 10 lbs. 10 reps each
- Back cable crossover: each cable 13lbs (26lbs total) for 10 reps each. Note: always feels heavy
- Stationary bike for 10 minutes to cool down, 2 miles
Note: outer hips sore when I woke up, didn't affect workout
'''

Example output:
{
  "exercises": [
    {
      "name": "Seated Cable Row",
      "canonical": "seated_cable_row",
      "muscle_group": "back",
      "sets": [
        {"reps": 10, "weight": 90, "unit": "lbs", "warmup": true},
        {"reps": 10, "weight": 140, "unit": "lbs"},
        {"reps": 10, "weight": 140, "unit": "lbs"}
      ],
      "superset_with": "single_arm_march",
      "note": null
    },
    {
      "name": "Single Arm March",
      "canonical": "single_arm_march",
      "muscle_group": "core",
      "sets": [
        {"reps": 20, "weight": 62, "unit": "lbs"}
      ],
      "superset_with": "seated_cable_row",
      "note": "20 steps per side"
    },
    {
      "name": "Lat Pulldown",
      "canonical": "lat_pulldown",
      "muscle_group": "back",
      "sets": [
        {"reps": 10, "weight": 90, "unit": "lbs", "warmup": true},
        {"reps": 10, "weight": 140, "unit": "lbs"},
        {"reps": 10, "weight": 190, "unit": "lbs"}
      ],
      "superset_with": "plank",
      "note": null
    },
    {
      "name": "Plank",
      "canonical": "plank",
      "muscle_group": "core",
      "sets": [
        {"reps": 1, "weight": 0, "unit": "lbs", "duration_sec": 30}
      ],
      "superset_with": "lat_pulldown",
      "note": null
    },
    {
      "name": "Hip Abductor",
      "canonical": "hip_abductor",
      "muscle_group": "glutes",
      "sets": [
        {"reps": 10, "weight": 80, "unit": "lbs"},
        {"reps": 10, "weight": 90, "unit": "lbs"},
        {"reps": 10, "weight": 100, "unit": "lbs"}
      ],
      "superset_with": null,
      "note": null
    },
    {
      "name": "Cable Crossover",
      "canonical": "cable_crossover",
      "muscle_group": "back",
      "sets": [
        {"reps": 10, "weight": 26, "unit": "lbs"}
      ],
      "superset_with": null,
      "note": "13lbs per cable, 26lbs total. Always feels heavy."
    }
  ],
  "cardio_intervals": [
    {"name": "Stationary bike cooldown", "params": {"distance_mi": 2}, "duration_min": 10}
  ],
  "session_notes": "Outer hips sore when I woke up — didn't affect workout.",
  "suggested_journal_tags": []
}
"""


def _parse_lift_text(text: str) -> dict:
    """Call Bedrock to parse the free-form workout text into the structured
    schema above. Returns the parsed dict; raises on invalid JSON."""
    resp = bedrock_runtime.invoke_model(
        modelId=ESTIMATOR_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "system": _LIFT_PARSER_SYSTEM,
            "messages": [{"role": "user", "content": f"Parse this workout:\n\n{text}"}],
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


# ── Validation / sanitization ─────────────────────────────────────────────


def _sanitize_set(s: dict) -> Optional[dict]:
    if not isinstance(s, dict):
        return None
    try:
        reps = int(s.get("reps", 0))
        weight = float(s.get("weight", 0))
    except (TypeError, ValueError):
        return None
    if reps < 0 or reps > 500:
        return None
    if weight < 0 or weight > 2000:
        return None
    out = {"reps": reps, "weight": round(weight, 1), "unit": "lbs"}
    if s.get("warmup"):
        out["warmup"] = True
    if s.get("ramp"):
        out["ramp"] = True
    if s.get("dropset"):
        out["dropset"] = True
    if s.get("duration_sec") is not None:
        try:
            out["duration_sec"] = int(s["duration_sec"])
        except (TypeError, ValueError):
            pass
    return out


def _sanitize_exercise(e: dict) -> Optional[dict]:
    if not isinstance(e, dict):
        return None
    name = str(e.get("name", "")).strip()[:80]
    if not name:
        return None
    canonical = str(e.get("canonical") or "").strip().lower()
    if not canonical:
        canonical = _canonicalize(name)
    muscle = str(e.get("muscle_group") or "other").strip().lower()
    if muscle not in MUSCLE_GROUPS:
        muscle = "other"

    raw_sets = e.get("sets") or []
    sets = []
    if isinstance(raw_sets, list):
        for s in raw_sets[:30]:
            sane = _sanitize_set(s)
            if sane is not None:
                sets.append(sane)

    out = {
        "name": name,
        "canonical": canonical[:60],
        "muscle_group": muscle,
        "sets": sets,
    }
    sw = e.get("superset_with")
    if isinstance(sw, str) and sw.strip():
        out["superset_with"] = sw.strip().lower()[:60]
    note = e.get("note")
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()[:200]
    return out


def _sanitize_cardio(c: dict) -> Optional[dict]:
    if not isinstance(c, dict):
        return None
    name = str(c.get("name", "")).strip()[:60]
    if not name:
        return None
    params = c.get("params") if isinstance(c.get("params"), dict) else {}
    # Strip non-numeric params.
    clean_params = {}
    for k, v in list(params.items())[:10]:
        try:
            clean_params[str(k)[:30]] = round(float(v), 2)
        except (TypeError, ValueError):
            continue
    out = {"name": name, "params": clean_params}
    dur = c.get("duration_min")
    if dur is not None:
        try:
            out["duration_min"] = round(float(dur), 1)
        except (TypeError, ValueError):
            pass
    return out


# ── Storage ───────────────────────────────────────────────────────────────


def _find_or_create_workout(date: str) -> dict:
    """Return the first workout row for `date`. If none exists, create a
    manual shell row so annotation has somewhere to land."""
    table = get_table("WORKOUTS_TABLE")
    rows = query_items(table, "date", date) or []
    if rows:
        # Prefer the most recently logged row (by logged_at/ingested_at desc).
        rows.sort(key=lambda r: r.get("logged_at") or r.get("ingested_at") or "", reverse=True)
        return rows[0]
    # No row — create a manual shell.
    workout_id = f"manual_{int(time.time() * 1000)}"
    shell = {
        "date": date,
        "strava_id": workout_id,
        "title": "Workout",
        "type": "other",
        "dur": 0,
        "cal": 0,
        "strain": 0,
        "source": "manual",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(table, shell)
    return shell


def _write_exercise_rows(exercises: list, date: str) -> int:
    """Mirror each parsed exercise into ExercisesTable for fast per-exercise
    history queries. One row per (canonical, date). Overwrites on reruns."""
    table = get_table("EXERCISES_TABLE")
    now_iso = datetime.now(timezone.utc).isoformat()
    count = 0
    for ex in exercises:
        if not ex.get("canonical"):
            continue
        # Compute simple per-session metrics. 4b compute job will add e1rm + PR flags.
        working_sets = [s for s in ex.get("sets", []) if not s.get("warmup")]
        top_weight = max((s.get("weight", 0) for s in working_sets), default=0)
        top_reps_at_top = max(
            (s.get("reps", 0) for s in working_sets if s.get("weight", 0) == top_weight),
            default=0,
        )
        volume = sum(s.get("reps", 0) * s.get("weight", 0) for s in working_sets)
        row = {
            "canonical": ex["canonical"],
            "date": date,
            "name": ex["name"],
            "muscle_group": ex.get("muscle_group", "other"),
            "sets": ex.get("sets", []),
            "top_weight": round(top_weight, 1),
            "top_reps_at_top_weight": top_reps_at_top,
            "working_volume": round(volume, 1),
            "session_count": sum(1 for s in working_sets),
            "logged_at": now_iso,
        }
        if ex.get("superset_with"):
            row["superset_with"] = ex["superset_with"]
        if ex.get("note"):
            row["note"] = ex["note"]
        put_item(table, row)
        count += 1
    return count


# ── Public entry point ────────────────────────────────────────────────────


def annotate_workout(text: str, date: Optional[str] = None) -> dict:
    """Parse free-form lift notes and attach structured data to the workout
    row for `date`. Also mirrors each exercise to ExercisesTable."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")

    date = date or local_today_str()

    try:
        parsed = _parse_lift_text(text)
    except Exception as e:
        logger.exception("lift parser failed")
        raise RuntimeError(f"lift parser failed: {e}")

    exercises = []
    for e in (parsed.get("exercises") or [])[:30]:
        sane = _sanitize_exercise(e)
        if sane is not None:
            exercises.append(sane)

    cardio_intervals = []
    for c in (parsed.get("cardio_intervals") or [])[:20]:
        sane = _sanitize_cardio(c)
        if sane is not None:
            cardio_intervals.append(sane)

    session_notes = str(parsed.get("session_notes") or "")[:300] or None
    suggested_tags_raw = parsed.get("suggested_journal_tags") or []
    suggested_tags: list = []
    if isinstance(suggested_tags_raw, list):
        for t in suggested_tags_raw[:5]:
            if isinstance(t, str) and t.strip():
                suggested_tags.append(t.strip().lower()[:30])

    # Update the workout row (replace, not append — annotation is the record).
    workout = _find_or_create_workout(date)
    workouts_table = get_table("WORKOUTS_TABLE")
    merged = {
        **workout,
        "exercises": exercises,
        "cardio_intervals": cardio_intervals,
        "session_notes": session_notes,
        "annotated_at": datetime.now(timezone.utc).isoformat(),
        "original_text": text[:2000],
    }
    # If the row was a Strava cardio shell with no title, upgrade it.
    if not merged.get("title") or merged["title"].lower() in ("workout", "weight training"):
        # First exercise name or muscle group makes a decent title.
        if exercises:
            primary_mg = exercises[0].get("muscle_group", "").title() or "Lift"
            merged["title"] = f"{primary_mg} session"
    put_item(workouts_table, merged)

    # Mirror to ExercisesTable.
    mirror_count = _write_exercise_rows(exercises, date)

    muscle_groups = sorted({e.get("muscle_group") for e in exercises if e.get("muscle_group")})
    return {
        "ok": True,
        "workout_id": workout.get("strava_id"),
        "date": date,
        "exercise_count": len(exercises),
        "cardio_count": len(cardio_intervals),
        "mirrored": mirror_count,
        "muscle_groups": muscle_groups,
        "session_notes": session_notes,
        "suggested_journal_tags": suggested_tags,
    }
