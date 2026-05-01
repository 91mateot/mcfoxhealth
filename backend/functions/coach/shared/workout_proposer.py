"""Daily workout proposer — intention-level recommendations.

Generates a `planned_workout` for a given date from recovery, recent
workout pattern, journal flags, and Mateo's Lateral Chain Rebuild
program phase. Runs in the morning compute job and on-demand from the
coach / Refresh button.

Design:
  - Intention-level for the main — type, duration, intensity, plus a
    short list of focus lifts (2-3) to point him in a direction without
    prescribing sets/reps. Actual lifts go through annotate_workout.
  - Activation circuit is prescribed (from the PDF protocol), so the
    exercise list IS returned.
  - Adaptive cadence: no hard weekly template. Reads last 28 days to
    detect patterns; falls back to muscle-group balance.
  - Red recovery or recent back_flare → regress to home bands.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from shared.db import get_table, get_item, query_items
from shared.timezone import local_now


# ── Lateral Chain Rebuild circuits (from uploads/Lateral Chain Rebuild Program.pdf) ──

_LATERAL_CHAIN_CIRCUITS = {
    1: {
        "gym": {
            "name": "Lateral Chain — Phase 1 Activation",
            "durationMin": 15,
            "location": "gym",
            "exercises": [
                {"name": "Wall-Supported Side-Lying Hip Abduction", "sets": 3, "reps": "12 ea", "cue": "Back on wall, R side first"},
                {"name": "Banded Clamshells", "sets": 3, "reps": "15 ea", "cue": "Don't let pelvis roll back"},
                {"name": "Single-Leg Glute Bridge (R emphasis)", "sets": 3, "reps": "10 ea", "cue": "3-5s hold at top"},
                {"name": "Pallof Press", "sets": 3, "reps": "8 ea", "cue": "5s hold each rep, anti-rotation"},
            ],
        },
        "home": {
            "name": "Lateral Chain — Phase 1 Home Bands",
            "durationMin": 8,
            "location": "home",
            "exercises": [
                {"name": "Standing Band Hip Abduction", "sets": 2, "reps": "12 ea", "cue": "1s pause at top, control the return"},
                {"name": "Monster Walks (fwd + lat)", "sets": 2, "reps": "10 steps ea", "cue": "Slight squat, keep tension"},
                {"name": "Side-Lying R Glute Med Isometric", "sets": 3, "reps": "20-30s hold", "cue": "Steady, breathing relaxed"},
            ],
        },
    },
    2: {
        "gym": {
            "name": "Lateral Chain — Phase 2 Strength",
            "durationMin": 18,
            "location": "gym",
            "exercises": [
                {"name": "Cable Hip Abduction", "sets": 3, "reps": "10-12 ea", "cue": "Progress weight weekly, 1s pause"},
                {"name": "Copenhagen Plank (bent knee)", "sets": 3, "reps": "10-15s ea", "cue": "Top KNEE on bench, spine neutral"},
                {"name": "Lateral Step-Ups (12-16\")", "sets": 3, "reps": "8 ea", "cue": "Drive through R hip, don't push off L"},
                {"name": "Single-Leg RDL (BW → DB)", "sets": 3, "reps": "8 ea", "cue": "3s lowering, hips square"},
            ],
        },
        "home": {
            "name": "Lateral Chain — Phase 2 Home Bands",
            "durationMin": 8,
            "location": "home",
            "exercises": [
                {"name": "Lateral Band Walks (squat)", "sets": 2, "reps": "15 steps ea", "cue": "Stay low, feet apart"},
                {"name": "Side Plank + Hip Abduction", "sets": 2, "reps": "8 ea", "cue": "Hips stacked, 3s hold each lift"},
                {"name": "Pelvic Drops (Trendelenburg)", "sets": 2, "reps": "12 ea", "cue": "Use R glute med to level pelvis"},
            ],
        },
    },
    3: {
        "gym": {
            "name": "Lateral Chain — Phase 3 Power",
            "durationMin": 18,
            "location": "gym",
            "exercises": [
                {"name": "Lateral Sled Push (both dirs)", "sets": 3, "reps": "20 yds ea", "cue": "Stay low, drive hips"},
                {"name": "Full Copenhagen Plank", "sets": 3, "reps": "15-20s ea", "cue": "Progress to slow hip dips"},
                {"name": "Skater Jumps", "sets": 3, "reps": "6 ea", "cue": "Explosive jump, 2s stick landing"},
                {"name": "Single-Leg Cable Rotation", "sets": 3, "reps": "10 ea", "cue": "Stand on R, rotate across body"},
            ],
        },
        "home": {
            "name": "Lateral Chain — Phase 3 Home",
            "durationMin": 8,
            "location": "home",
            "exercises": [
                {"name": "Banded Lateral Shuffles", "sets": 2, "reps": "10 steps ea", "cue": "Quick, reactive, stay low"},
                {"name": "Single-Leg Balance on Pillow", "sets": 3, "reps": "30s ea", "cue": "R leg, eyes closed for progression"},
                {"name": "Lateral Lunge (BW)", "sets": 2, "reps": "8 ea", "cue": "3s lowering, explosive return"},
            ],
        },
    },
}


# Workout types considered gym-based (activation belongs before main lifts).
_GYM_TYPES = {"push", "pull", "legs", "hiit"}
_UPPER_TYPES = {"push", "pull"}
_LOWER_TYPES = {"legs"}
_CARDIO_TYPES = {"run", "hiit", "pickleball", "walk"}

# Duration defaults by type (minutes).
_DEFAULT_DURATION = {
    "push": 45,
    "pull": 45,
    "legs": 50,
    "run": 30,
    "hiit": 25,
    "pilates": 45,
    "pickleball": 60,
    "walk": 30,
    "mobility": 15,
    "sport_prep": 20,
    "rest": 20,
}


# ── Public entry point ────────────────────────────────────────────────

def propose_for_date(date_str: str) -> dict:
    """Return the planned_workout payload for `date_str` (YYYY-MM-DD)."""
    scores_table = get_table("DAILY_SCORES_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    journal_table = get_table("JOURNAL_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")
    exercises_table = get_table("EXERCISES_TABLE")

    scores = get_item(scores_table, {"date": date_str}) or {}
    recovery_zone = scores.get("recovery_zone", "yellow")

    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    recent_workouts = _recent_workouts(workouts_table, target_dt, days=28)
    recent_journal = _recent_journal(journal_table, target_dt, days=2)

    config = get_item(config_table, {"key": "mateo"}) or {}
    program = config.get("lateral_chain_program") or {}
    phase = int(program.get("phase", 1))
    if phase not in (1, 2, 3):
        phase = 1

    regress = _should_regress(recent_journal)

    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    if recovery_zone == "red" or regress:
        reason_parts = []
        if recovery_zone == "red":
            reason_parts.append("Recovery red — active recovery only")
        if regress:
            reason_parts.append("Back flare logged — scale back loaded/explosive work")
        return {
            "main": {
                "type": "rest",
                "durationMin": 20,
                "intensity": "light",
                "reason": ". ".join(reason_parts) or "Easy day.",
                "focusMuscleGroups": ["glute_med", "adductors", "core"],
                "focusLifts": [],
            },
            "activation": _LATERAL_CHAIN_CIRCUITS[phase]["home"],
            "reason": "Easy day. Home bands + short walk.",
            "phase": phase,
            "generatedAt": generated_at,
            "matched": False,
            "matchedWorkoutId": None,
        }

    preferred_type = _detect_preferred_type(recent_workouts, target_dt)
    main = _build_main(preferred_type, recovery_zone, recent_workouts)
    main["focusLifts"] = _pick_focus_lifts(
        workout_type=preferred_type,
        scores_table=scores_table,
        config_table=config_table,
        exercises_table=exercises_table,
        target_dt=target_dt,
    )
    main_type = main["type"]

    if main_type in _GYM_TYPES:
        activation = _LATERAL_CHAIN_CIRCUITS[phase]["gym"]
    else:
        activation = _LATERAL_CHAIN_CIRCUITS[phase]["home"]

    return {
        "main": main,
        "activation": activation,
        "reason": _combined_reason(main, activation, recovery_zone),
        "phase": phase,
        "generatedAt": generated_at,
        "matched": False,
        "matchedWorkoutId": None,
    }


def write_proposal(date_str: str, proposal: dict) -> None:
    """Persist the proposal onto the DailyScoresTable row for `date_str`."""
    scores_table = get_table("DAILY_SCORES_TABLE")
    existing = get_item(scores_table, {"date": date_str}) or {"date": date_str}
    existing["planned_workout"] = proposal
    from shared.db import put_item
    put_item(scores_table, existing)


# ── Helpers ───────────────────────────────────────────────────────────

def _recent_workouts(workouts_table, target_dt: datetime, days: int) -> list[dict]:
    out: list[dict] = []
    for i in range(1, days + 1):
        d = (target_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        out.extend(query_items(workouts_table, "date", d))
    return out


def _recent_journal(journal_table, target_dt: datetime, days: int) -> list[dict]:
    out: list[dict] = []
    for i in range(days + 1):  # includes target day
        d = (target_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        row = get_item(journal_table, {"date": d})
        if row:
            out.append(row)
    return out


def _should_regress(recent_journal: list[dict]) -> bool:
    for row in recent_journal:
        tags = row.get("tags") or []
        if "back_flare" in tags:
            return True
    return False


def _normalize_type(workout_type: str) -> Optional[str]:
    """Map free-form workout types from Strava/annotate into our vocabulary."""
    t = (workout_type or "").strip().lower()
    if not t:
        return None
    # Direct matches first.
    if t in {"push", "pull", "legs", "run", "hiit", "pilates", "pickleball", "walk", "mobility", "sport_prep", "rest"}:
        return t
    # Heuristic mapping.
    if "push" in t or "chest" in t or "shoulders" in t:
        return "push"
    if "pull" in t or "back" in t or "biceps" in t:
        return "pull"
    if "leg" in t or "squat" in t or "lower" in t:
        return "legs"
    if "run" in t or "jog" in t:
        return "run"
    if "hiit" in t or "circuit" in t or "metcon" in t:
        return "hiit"
    if "pilates" in t or "reformer" in t:
        return "pilates"
    if "pickle" in t:
        return "pickleball"
    if "walk" in t:
        return "walk"
    if "mobility" in t or "stretch" in t or "yoga" in t:
        return "mobility"
    return None


def _detect_preferred_type(recent_workouts: list[dict], target_dt: datetime) -> str:
    """Choose the 'due' workout type based on recency patterns.

    Strategy:
      1. If any of push/pull/legs is missing from the last 7 days → propose it.
      2. If all three present, pick the one done least recently.
      3. If no gym work at all in last 7 days, default to 'push'.
      4. Day-of-week hint: if target is a weekend and last 2 weekends had no
         cardio/pickleball, nudge toward pickleball/run (Mateo's pattern).
    """
    last7_types: list[str] = []
    type_last_seen: dict[str, int] = {}  # days ago
    for w in recent_workouts:
        t = _normalize_type(w.get("type", ""))
        if not t:
            continue
        date_str = w.get("date", "")
        if not date_str:
            continue
        try:
            w_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        days_ago = (target_dt - w_dt).days
        if days_ago < 0:
            continue
        if days_ago <= 7:
            last7_types.append(t)
        if t not in type_last_seen or days_ago < type_last_seen[t]:
            type_last_seen[t] = days_ago

    gym_present = [t for t in ("push", "pull", "legs") if t in last7_types]

    # Weekend nudge: Saturday=5, Sunday=6.
    if target_dt.weekday() in (5, 6) and not any(t in last7_types for t in ("pickleball", "run")):
        return "pickleball" if target_dt.weekday() == 6 else "run"

    # No gym activity in the last week → start with push.
    if not gym_present:
        return "push"

    # Missing one of the three → fill the gap.
    missing = [t for t in ("push", "pull", "legs") if t not in last7_types]
    if missing:
        # If multiple missing, pick by what's been absent longest.
        missing.sort(key=lambda t: type_last_seen.get(t, 999), reverse=True)
        return missing[0]

    # All three present — pick the one done least recently.
    ordered = sorted(("push", "pull", "legs"), key=lambda t: type_last_seen.get(t, 0), reverse=True)
    return ordered[0]


def _build_main(workout_type: str, recovery_zone: str, recent_workouts: list[dict]) -> dict:
    duration = _DEFAULT_DURATION.get(workout_type, 30)
    intensity = "hard" if recovery_zone == "green" else "moderate"

    focus_map = {
        "push": ["chest", "shoulders", "triceps"],
        "pull": ["back", "biceps", "rear_delts"],
        "legs": ["quads", "hamstrings", "glutes"],
        "run": ["cardio"],
        "hiit": ["cardio", "conditioning"],
        "pilates": ["core", "mobility"],
        "pickleball": ["cardio", "lateral_stability"],
        "walk": ["cardio", "recovery"],
        "mobility": ["mobility"],
        "sport_prep": ["lateral_stability"],
        "rest": ["recovery"],
    }

    # Natural-language reason.
    type_counter = Counter(
        _normalize_type(w.get("type", "")) for w in recent_workouts
    )
    count_7d = _count_in_window(recent_workouts, days=7, type=workout_type)

    bits = []
    if recovery_zone == "green":
        bits.append("Recovery green — train hard")
    elif recovery_zone == "yellow":
        bits.append("Moderate recovery — train smart")
    if workout_type in _UPPER_TYPES and type_counter.get(workout_type, 0) == 0:
        bits.append(f"no {workout_type} day in the last 28")
    elif count_7d == 0 and workout_type in ("push", "pull", "legs"):
        bits.append(f"{workout_type} is due — none this week")
    reason = ". ".join(bits).strip() or f"{workout_type.capitalize()} day."

    return {
        "type": workout_type,
        "durationMin": duration,
        "intensity": intensity,
        "reason": reason,
        "focusMuscleGroups": focus_map.get(workout_type, []),
    }


def _count_in_window(workouts: list[dict], days: int, type: str) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    count = 0
    for w in workouts:
        if w.get("date", "") >= cutoff and _normalize_type(w.get("type", "")) == type:
            count += 1
    return count


# Workout type → which muscle groups the focus-lifts should come from.
_TYPE_TO_MUSCLE_GROUPS = {
    "push": ["chest", "shoulders", "triceps"],
    "pull": ["back", "biceps"],
    "legs": ["legs", "glutes", "hamstrings", "quads"],
    "hiit": ["legs", "back", "chest", "core"],
    "pilates": ["core", "glutes"],
}


def _pick_focus_lifts(
    workout_type: str,
    scores_table,
    config_table,
    exercises_table,
    target_dt: datetime,
    max_lifts: int = 3,
) -> list[dict]:
    """Suggest 2-3 focus lifts with a short reason tag.

    Priority:
      1. Active stalls in relevant muscle groups ("stalled" tag).
      2. Muscle groups behind on weekly volume ("volume behind").
      3. Top e1RM lifts in the relevant muscle groups ("anchor").

    Each item: {name, canonical, muscleGroup, tag}. No sets/reps.
    """
    muscle_groups = _TYPE_TO_MUSCLE_GROUPS.get(workout_type, [])
    if not muscle_groups:
        return []

    picks: list[dict] = []
    seen_canonicals: set[str] = set()

    # 1. Stalls.
    try:
        stalls_row = get_item(config_table, {"key": "lift_stalls"}) or {}
        for s in (stalls_row.get("stalls") or []):
            if len(picks) >= max_lifts:
                break
            mg = (s.get("muscle_group") or "").lower()
            if mg not in muscle_groups:
                continue
            canonical = s.get("canonical")
            if not canonical or canonical in seen_canonicals:
                continue
            picks.append({
                "name": s.get("name") or canonical.replace("_", " ").title(),
                "canonical": canonical,
                "muscleGroup": mg,
                "tag": "stalled",
            })
            seen_canonicals.add(canonical)
    except Exception:
        pass

    # 2. Volume-behind muscle groups (this week's roll-up).
    try:
        week_start = target_dt - timedelta(days=target_dt.weekday())
        week_row = get_item(scores_table, {"date": f"week_{week_start.strftime('%Y-%m-%d')}"}) or {}
        vol_by_mg = {k: float(v) for k, v in (week_row.get("volume_by_muscle_group") or {}).items()}
        # Rank muscle groups behind — lowest volume among the relevant set.
        relevant = [(mg, vol_by_mg.get(mg, 0)) for mg in muscle_groups]
        relevant.sort(key=lambda t: t[1])  # lowest first
        behind = [mg for mg, v in relevant if v < _median(list(vol_by_mg.values())) or v == 0]
    except Exception:
        behind = []

    # 3. Top e1RM anchor lifts in relevant muscle groups. Used for both
    #    "volume behind" picks and to round out to 2-3 items.
    try:
        resp = exercises_table.scan(Limit=500)
        rows = resp.get("Items", [])
    except Exception:
        rows = []

    # Normalize decimals (DynamoDB returns Decimal).
    candidates: list[dict] = []
    for r in rows:
        mg = str(r.get("muscle_group", "")).lower()
        if mg not in muscle_groups:
            continue
        canonical = r.get("canonical")
        if not canonical:
            continue
        e1rm = float(r.get("e1rm") or 0)
        top = float(r.get("top_weight") or 0)
        candidates.append({
            "canonical": canonical,
            "name": r.get("name") or canonical.replace("_", " ").title(),
            "muscleGroup": mg,
            "e1rm": e1rm,
            "top": top,
        })

    # Sort candidates by e1rm descending.
    candidates.sort(key=lambda c: c["e1rm"], reverse=True)

    # First pass: fill "volume behind" slots using candidates from those groups.
    if behind:
        for c in candidates:
            if len(picks) >= max_lifts:
                break
            if c["canonical"] in seen_canonicals:
                continue
            if c["muscleGroup"] not in behind:
                continue
            picks.append({
                "name": c["name"],
                "canonical": c["canonical"],
                "muscleGroup": c["muscleGroup"],
                "tag": "volume behind",
            })
            seen_canonicals.add(c["canonical"])

    # Second pass: top e1RM anchors to round out.
    for c in candidates:
        if len(picks) >= max_lifts:
            break
        if c["canonical"] in seen_canonicals:
            continue
        picks.append({
            "name": c["name"],
            "canonical": c["canonical"],
            "muscleGroup": c["muscleGroup"],
            "tag": "anchor",
        })
        seen_canonicals.add(c["canonical"])

    return picks


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2


def _combined_reason(main: dict, activation: Optional[dict], recovery_zone: str) -> str:
    parts = [main.get("reason", "")]
    if activation:
        parts.append(f"Pair with {activation['name'].split('—', 1)[-1].strip()}.")
    return " ".join(p for p in parts if p).strip()


def update_lateral_chain_phase(phase: int, reason: Optional[str] = None) -> dict:
    """Update the lateral_chain_program.phase in the mateo user-config row."""
    from shared.db import put_item
    if phase not in (1, 2, 3):
        return {"error": f"phase must be 1, 2, or 3; got {phase}"}

    config_table = get_table("USER_CONFIG_TABLE")
    config = get_item(config_table, {"key": "mateo"}) or {"key": "mateo"}
    program = config.get("lateral_chain_program") or {}
    prev_phase = int(program.get("phase", 1))
    today = local_now().strftime("%Y-%m-%d")

    program["phase"] = phase
    program["last_phase_change"] = today
    if not program.get("started_at"):
        program["started_at"] = today
    if reason:
        program["notes"] = reason
    config["lateral_chain_program"] = program
    put_item(config_table, config)

    return {
        "ok": True,
        "phase": phase,
        "previous_phase": prev_phase,
        "last_phase_change": today,
    }
