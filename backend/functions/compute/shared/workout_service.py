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
from shared.lift_compute import recompute_prs_for_canonicals
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


# ── Coach feedback (summary + critique) ──────────────────────────────────

_COACH_SUMMARY_SYSTEM = """You are Mateo's personal fitness coach AI, writing a brief post-workout debrief.

## Who Mateo Is
- 34, 5'8" 169lb, 13.6% body fat. Recomp goal: sub-12% BF while defending lean mass.
- Back injury history — avoid loaded squats / heavy deadlifts. Be alert to back_flare signals.
- Training 4-5x/week push/pull/legs with supersets.
- On retatrutide (GLP-1 triple agonist) — appetite suppressed.

## Your Task
Given the structured session data, per-exercise history, and today's readiness
metrics, produce a short debrief (4-6 sentences, plain prose, no bullets or
headers). Lead with what the session was, cite the strongest signal (PR, stall,
volume bump, or notable superset pairing), tie it to readiness if relevant
(e.g. "solid output given recovery was only 58%"), and end with ONE specific
forward-looking note (e.g. "next week push the top set to 145 on lat pulldown"
or "if the hip soreness persists, back off hip abductor volume").

## Voice
- Direct, coach-reviewing-game-film.
- Specific numbers, not "good job" / "great session".
- No preamble, no pleasantries, no disclaimers, no "I noticed".
- Reference the back-injury risk ONLY if something in the session plausibly triggered it.
- Do NOT invent data. If you don't have history for an exercise, say "first time logged — baseline set at X."

Return ONLY the debrief text. No JSON, no markdown.
"""


def _recent_history_summary(canonical: str, days: int = 60) -> str:
    """Pull last N days of an exercise's sessions and return a short line
    summarizing the trajectory. Used as context in the coach prompt."""
    table = get_table("EXERCISES_TABLE")
    rows = query_items(table, "canonical", canonical) or []
    cutoff = (local_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("date", "") >= cutoff]
    rows.sort(key=lambda r: r.get("date", ""))
    if len(rows) < 2:
        return f"{canonical}: first-ever session logged" if len(rows) == 1 else f"{canonical}: no history"

    # Build a compact trajectory: "canonical: 2026-04-08 140x10 → 2026-04-15 140x10 → 2026-04-22 145x10"
    parts = []
    for r in rows[-5:]:
        parts.append(f"{r.get('date')} {r.get('top_weight', 0)}x{r.get('top_reps_at_top_weight', 0)}")
    return f"{canonical} last 5: " + " → ".join(parts)


def _readiness_for_date(date: str) -> dict:
    """Pull recovery/HRV/sleep/strain_target for the date. Returns {} if missing."""
    scores_table = get_table("DAILY_SCORES_TABLE")
    s = get_item(scores_table, {"date": date}) or {}
    sleep = s.get("sleep") or {}
    return {
        "recovery": s.get("recovery"),
        "recovery_zone": s.get("recovery_zone"),
        "hrv": s.get("hrv"),
        "rhr": s.get("rhr"),
        "sleep_min": sleep.get("total_min"),
        "sleep_efficiency": sleep.get("efficiency"),
        "strain_target": s.get("strain_target") or {},
    }


def _generate_coach_feedback(workout: dict) -> Optional[str]:
    """Call Bedrock to produce a coach-voice debrief. Returns the text, or
    None on failure (caller should treat absence gracefully)."""
    exercises = workout.get("exercises") or []
    if not exercises and not workout.get("cardio_intervals"):
        return None

    # Compact session description.
    exercise_lines = []
    for ex in exercises:
        sets = ex.get("sets") or []
        working = [s for s in sets if not s.get("warmup")]
        set_strs = []
        for s in working:
            if s.get("duration_sec"):
                set_strs.append(f"{s.get('weight', 0)}x{s.get('duration_sec')}s")
            else:
                set_strs.append(f"{s.get('weight', 0)}x{s.get('reps', 0)}")
        line = f"- {ex.get('name')} ({ex.get('muscle_group', 'other')}): " + ", ".join(set_strs)
        if ex.get("superset_with"):
            line += f" [paired with {ex['superset_with']}]"
        if ex.get("note"):
            line += f" — note: {ex['note']}"
        exercise_lines.append(line)

    cardio_lines = []
    for c in workout.get("cardio_intervals") or []:
        params_str = ", ".join(f"{k}={v}" for k, v in (c.get("params") or {}).items())
        dur_str = f" ({c.get('duration_min')}min)" if c.get("duration_min") else ""
        cardio_lines.append(f"- {c.get('name')}: {params_str}{dur_str}")

    # Per-exercise history summaries (capped to avoid prompt bloat).
    history_lines = []
    for ex in exercises[:8]:
        canonical = ex.get("canonical")
        if canonical:
            history_lines.append(_recent_history_summary(canonical))

    readiness = _readiness_for_date(workout.get("date", ""))

    session_block = f"""## Today's Session ({workout.get('date')}, {workout.get('title', 'Workout')})

Duration: {workout.get('dur', 0)} min
Strain: {workout.get('strain', 0)}
Avg HR: {workout.get('avgHR', 0)}
Source: {workout.get('source', 'strava')}

### Lifts
{chr(10).join(exercise_lines) if exercise_lines else '(none)'}

### Cardio
{chr(10).join(cardio_lines) if cardio_lines else '(none)'}

### Session notes
{workout.get('session_notes') or '(none)'}

## Recent history (top 5 sessions per exercise)
{chr(10).join(history_lines) if history_lines else '(no prior history)'}

## Today's readiness
Recovery: {readiness.get('recovery')}% ({readiness.get('recovery_zone') or 'unknown'})
HRV: {readiness.get('hrv')} ms
RHR: {readiness.get('rhr')} bpm
Sleep: {readiness.get('sleep_min', 0)} min ({readiness.get('sleep_efficiency', 0)}% efficiency)
Strain target today: {readiness.get('strain_target', {}).get('low', '?')}-{readiness.get('strain_target', {}).get('high', '?')} — {readiness.get('strain_target', {}).get('reason', '')}
"""

    try:
        resp = bedrock_runtime.invoke_model(
            modelId=ESTIMATOR_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 400,
                "system": _COACH_SUMMARY_SYSTEM,
                "messages": [{"role": "user", "content": session_block}],
            }),
        )
        payload = json.loads(resp["body"].read())
        reply = ""
        for block in payload.get("content", []):
            if block.get("type") == "text":
                reply += block["text"]
        reply = reply.strip()
        if not reply:
            return None
        return reply[:1500]
    except Exception:
        logger.exception("coach feedback generation failed")
        return None


def summarize_workout(date: str, workout_id: Optional[str] = None) -> dict:
    """Generate coach feedback for an already-annotated workout row.
    Stores result as coach_feedback + coach_feedback_at on the row."""
    table = get_table("WORKOUTS_TABLE")
    if workout_id:
        workout = get_item(table, {"date": date, "strava_id": workout_id})
    else:
        rows = query_items(table, "date", date) or []
        rows.sort(key=lambda r: r.get("logged_at") or r.get("ingested_at") or "", reverse=True)
        workout = rows[0] if rows else None

    if not workout:
        return {"ok": False, "reason": "workout not found", "date": date}

    feedback = _generate_coach_feedback(workout)
    if not feedback:
        return {"ok": False, "reason": "feedback generation failed", "date": date, "workout_id": workout.get("strava_id")}

    merged = {
        **workout,
        "coach_feedback": feedback,
        "coach_feedback_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(table, merged)
    return {
        "ok": True,
        "date": date,
        "workout_id": workout.get("strava_id"),
        "coach_feedback": feedback,
        "coach_feedback_at": merged["coach_feedback_at"],
    }


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

    # Recompute PR flags + e1RM for each affected canonical across its full
    # history. Critical for retroactive annotations: if Mateo annotates an
    # older session, existing PR flags on newer sessions may no longer be
    # correct (e.g. an old 210lb bench beats last week's 205lb PR flag).
    # Also means the coach debrief below sees fresh PR status.
    affected_canonicals = sorted({e["canonical"] for e in exercises if e.get("canonical")})
    if affected_canonicals:
        try:
            recompute_prs_for_canonicals(affected_canonicals)
        except Exception:
            logger.exception("inline PR recompute failed for %s", affected_canonicals)

    # Generate coach feedback against the freshly-written row + history.
    # Reload from the same dict so history reads already include this session.
    coach_feedback = _generate_coach_feedback(merged)
    if coach_feedback:
        merged["coach_feedback"] = coach_feedback
        merged["coach_feedback_at"] = datetime.now(timezone.utc).isoformat()
        put_item(workouts_table, merged)

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
        "coach_feedback": coach_feedback,
    }
