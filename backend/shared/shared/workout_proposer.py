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

from datetime import datetime, timedelta
from typing import Optional

from shared.db import get_table, get_item
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
# Pickleball is a valid WorkoutType Mateo can log, but the proposer should
# never recommend it — he plays socially when he wants to, not on a schedule.
_CARDIO_TYPES = {"run", "hiit", "walk"}

# Duration defaults by type (minutes).
_DEFAULT_DURATION = {
    "push": 45,
    "pull": 45,
    "legs": 50,
    "run": 30,
    "hiit": 25,
    "pilates": 45,
    "walk": 30,
    "mobility": 15,
    "sport_prep": 20,
    "rest": 20,
}


# ── Public entry point ────────────────────────────────────────────────

def propose_for_date(date_str: str) -> dict:
    """Return the planned_workout payload for `date_str` (YYYY-MM-DD)."""
    scores_table = get_table("DAILY_SCORES_TABLE")
    journal_table = get_table("JOURNAL_TABLE")
    config_table = get_table("USER_CONFIG_TABLE")
    exercises_table = get_table("EXERCISES_TABLE")

    scores = get_item(scores_table, {"date": date_str}) or {}
    recovery_zone = scores.get("recovery_zone", "yellow")

    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
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

    # Build the muscle-group history from the exercises table — ground truth.
    # The workouts table stores `type="Workout"` from Strava, which is useless
    # for classifying push/pull/legs; exercises rows carry the real signal.
    session_splits = _session_splits_from_exercises(exercises_table, target_dt, days=28)
    preferred_type = _detect_preferred_type(session_splits, target_dt)
    main = _build_main(preferred_type, recovery_zone, session_splits, target_dt)
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


# Muscle-group → split classification. Used to tag each training session
# as push/pull/legs based on the dominant groups worked, since the
# workouts table's `type` field from Strava is unreliable.
_MG_TO_SPLIT = {
    "chest": "push",
    "shoulders": "push",
    "triceps": "push",
    "arms": "push",       # only triceps live in `arms` currently
    "back": "pull",
    "biceps": "pull",
    "lats": "pull",
    "legs": "legs",
    "quads": "legs",
    "hamstrings": "legs",
    "glutes": "legs",
    "calves": "legs",
}


def _session_splits_from_exercises(exercises_table, target_dt: datetime, days: int = 28) -> list[dict]:
    """Read the exercises table and classify each session's split.

    Returns a list of {date, daysAgo, split, mgCounts} where split is
    "push" | "pull" | "legs" | "mixed" | "other" based on which muscle
    groups dominated that day.

    ExercisesTable schema: PK=canonical, SK=date. We don't have a date
    index, so we scan and filter by date range. Table is small (<500
    rows typical) so this is fine.
    """
    try:
        resp = exercises_table.scan(Limit=2000)
        rows = resp.get("Items", [])
    except Exception:
        return []

    cutoff = (target_dt - timedelta(days=days)).strftime("%Y-%m-%d")
    today_str = target_dt.strftime("%Y-%m-%d")

    # Group by date → list of muscle_groups.
    by_date: dict[str, list[str]] = {}
    for r in rows:
        d = r.get("date", "")
        if not d or d < cutoff or d >= today_str:
            continue
        mg = str(r.get("muscle_group", "")).lower()
        by_date.setdefault(d, []).append(mg)

    sessions: list[dict] = []
    for d, mgs in by_date.items():
        counts: dict[str, int] = {}
        for mg in mgs:
            counts[mg] = counts.get(mg, 0) + 1

        # Map each muscle group to its split, then tally.
        split_counts: dict[str, int] = {}
        for mg, n in counts.items():
            split = _MG_TO_SPLIT.get(mg)
            if split:
                split_counts[split] = split_counts.get(split, 0) + n

        if not split_counts:
            split = "other"
        else:
            top_split = max(split_counts, key=lambda s: split_counts[s])
            total = sum(split_counts.values())
            # If the top split is ≥60% of classifiable lifts, call it that
            # split. Otherwise "mixed" (e.g. a true full-body session).
            split = top_split if split_counts[top_split] / total >= 0.6 else "mixed"

        try:
            d_dt = datetime.strptime(d, "%Y-%m-%d")
            days_ago = (target_dt - d_dt).days
        except ValueError:
            continue

        sessions.append({
            "date": d,
            "daysAgo": days_ago,
            "split": split,
            "mgCounts": counts,
            "splitCounts": split_counts,
        })

    sessions.sort(key=lambda s: s["date"], reverse=True)
    return sessions


def _last_seen_split(session_splits: list[dict], split: str) -> Optional[dict]:
    """Most recent session where split matches (or mixed containing split).

    Returns the session dict, or None.
    """
    for s in session_splits:
        if s["split"] == split:
            return s
        if s["split"] == "mixed" and s["splitCounts"].get(split, 0) > 0:
            return s
    return None


def _detect_preferred_type(session_splits: list[dict], target_dt: datetime) -> str:
    """Choose the 'due' workout type from muscle-group classified sessions.

    Strategy:
      1. Weekend nudge to easy cardio if gym volume is heavy (≥4 in 7 days).
      2. Among push/pull/legs: pick the one not seen in longest (including
         any "mixed" session that touched it).
      3. If all three seen in last 3 days, pick the one done least
         recently to space things out.
      4. No gym activity at all in last 7 days → default to push.
    """
    # Weekend nudge (Sat=5, Sun=6). Cardio sessions don't hit the exercises
    # table, so we rely on pattern inference from the splits we do see.
    # If the last 7 days are gym-heavy, propose an easy outdoor session to
    # balance load — a walk on Sunday, a short run on Saturday.
    recent_7 = [s for s in session_splits if s["daysAgo"] <= 7]
    if target_dt.weekday() in (5, 6) and len(recent_7) >= 4:
        return "walk" if target_dt.weekday() == 6 else "run"

    if not recent_7:
        return "push"

    # Find last-seen days_ago for each split (including mixed with that split).
    last_seen: dict[str, int] = {}
    for split in ("push", "pull", "legs"):
        s = _last_seen_split(session_splits, split)
        if s is not None:
            last_seen[split] = s["daysAgo"]

    # Pick the split that's been absent longest (or never seen → priority).
    def _rank(split: str) -> int:
        return last_seen.get(split, 999)

    ordered = sorted(("push", "pull", "legs"), key=_rank, reverse=True)
    preferred = ordered[0]

    # Guardrail: if every split we'd consider has been hit within the last day
    # (e.g. a full-body session yesterday), don't force another lift session —
    # suggest mobility instead of recommending push-after-push.
    if last_seen.get(preferred, 999) <= 1:
        return "mobility"

    return preferred


def _build_main(
    workout_type: str,
    recovery_zone: str,
    session_splits: list[dict],
    target_dt: datetime,
) -> dict:
    duration = _DEFAULT_DURATION.get(workout_type, 30)
    intensity = "hard" if recovery_zone == "green" else "moderate"

    focus_map = {
        "push": ["chest", "shoulders", "triceps"],
        "pull": ["back", "biceps", "rear_delts"],
        "legs": ["quads", "hamstrings", "glutes"],
        "run": ["cardio"],
        "hiit": ["cardio", "conditioning"],
        "pilates": ["core", "mobility"],
        "walk": ["cardio", "recovery"],
        "mobility": ["mobility"],
        "sport_prep": ["lateral_stability"],
        "rest": ["recovery"],
    }

    # Verifiable, date-grounded reason. No "last 28" counts that mislead.
    bits = []
    if recovery_zone == "green":
        bits.append("Recovery green — train hard")
    elif recovery_zone == "yellow":
        bits.append("Moderate recovery — train smart")

    if workout_type in ("push", "pull", "legs"):
        last = _last_seen_split(session_splits, workout_type)
        if last is None:
            bits.append(f"no {workout_type} work in last 28d")
        else:
            when = _fmt_when(last["daysAgo"], last["date"], target_dt)
            mg_detail = _fmt_mg_counts(last.get("mgCounts") or {}, workout_type)
            bits.append(
                f"last {workout_type}: {when} ({mg_detail})" if mg_detail
                else f"last {workout_type}: {when}"
            )

    reason = ". ".join(bits).strip() or f"{workout_type.capitalize()} day."

    return {
        "type": workout_type,
        "durationMin": duration,
        "intensity": intensity,
        "reason": reason,
        "focusMuscleGroups": focus_map.get(workout_type, []),
    }


def _fmt_when(days_ago: int, date_str: str, target_dt: datetime) -> str:
    """Human-readable 'when' string: 'yesterday', 'Mon 4/27', etc."""
    if days_ago == 0:
        return "today"
    if days_ago == 1:
        return "yesterday"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return f"{days_ago}d ago"
    # Within the current week → day name; else MM/DD.
    if days_ago <= 6:
        return f"{d.strftime('%a')} {d.month}/{d.day}"
    return f"{d.month}/{d.day}"


def _fmt_mg_counts(mg_counts: dict, workout_type: str) -> str:
    """Compact muscle-group breakdown for the proposal's reason line.

    Filters to groups relevant to the workout type, sorts by count desc, caps
    at 3 entries. Returns '' when nothing relevant to surface.
    """
    relevant = set(_TYPE_TO_MUSCLE_GROUPS.get(workout_type, []))
    if not relevant or not mg_counts:
        return ""
    ordered = sorted(
        ((mg, int(n)) for mg, n in mg_counts.items() if mg in relevant),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not ordered:
        return ""
    return ", ".join(f"{mg} {n}" for mg, n in ordered[:3])


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

    # 2. Volume-behind muscle groups.
    # Baseline: average per-group volume across the last 4 weeks (excluding
    # this one). Flag as "behind" when this week's volume is < 70% of the
    # 4-week average — or the group is completely missing this week and
    # the 4-week average shows it's normally trained. Never "behind" when
    # we don't have enough history (avoid false positives for new groups).
    behind: list[str] = []
    try:
        week_start = target_dt - timedelta(days=target_dt.weekday())
        cur_week_row = get_item(scores_table, {"date": f"week_{week_start.strftime('%Y-%m-%d')}"}) or {}
        cur_vol = {k: float(v) for k, v in (cur_week_row.get("volume_by_muscle_group") or {}).items()}

        prior_vol_sum: dict[str, float] = {}
        prior_vol_weeks: dict[str, int] = {}
        for i in range(1, 5):  # 4 prior weeks
            ws = (week_start - timedelta(days=7 * i)).strftime("%Y-%m-%d")
            row = get_item(scores_table, {"date": f"week_{ws}"}) or {}
            wk_vol = row.get("volume_by_muscle_group") or {}
            for mg, v in wk_vol.items():
                try:
                    prior_vol_sum[mg] = prior_vol_sum.get(mg, 0) + float(v)
                    prior_vol_weeks[mg] = prior_vol_weeks.get(mg, 0) + 1
                except (TypeError, ValueError):
                    continue

        for mg in muscle_groups:
            weeks = prior_vol_weeks.get(mg, 0)
            if weeks < 2:
                # Not enough history — don't claim "behind".
                continue
            baseline = prior_vol_sum[mg] / weeks
            this_week = cur_vol.get(mg, 0)
            if baseline > 0 and this_week < baseline * 0.7:
                behind.append(mg)
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
