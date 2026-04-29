"""Shared lift-learning helpers.

Pure functions for Epley e1RM, PR detection, stall detection, and a
`recompute_prs_for_canonicals` routine used by both:

  - compute/handler.py → daily full roll-up (all canonicals in table)
  - workout_service.annotate_workout → immediate recompute for just the
    exercises that were annotated, so the coach debrief and PR chips
    reflect the new session without waiting for the next daily job.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.db import get_table, put_item, query_items
from shared.timezone import local_now


def epley_e1rm(weight: float, reps: int) -> float:
    """Epley formula for estimated 1-rep max.
    e1RM = weight * (1 + reps/30). Good for 2-10 reps.
    reps=1 returns weight unchanged. reps=0 returns 0 (no work done)."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return round(float(weight), 1)
    return round(float(weight) * (1.0 + reps / 30.0), 1)


def session_top_e1rm(row: dict) -> float:
    """Best Epley-e1RM across all working sets in a session."""
    best = 0.0
    for s in row.get("sets") or []:
        if s.get("warmup"):
            continue
        w = float(s.get("weight") or 0)
        r = int(s.get("reps") or 0)
        e = epley_e1rm(w, r)
        if e > best:
            best = e
    return best


def scan_exercise_history(exercises_table, canonical: str, days: int = 180) -> list:
    """Return all sessions for a canonical exercise in the last `days`,
    sorted by date ascending. ExercisesTable is (PK=canonical, SK=date) so
    this is a single Query."""
    rows = query_items(exercises_table, "canonical", canonical) or []
    cutoff = (local_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("date", "") >= cutoff]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def detect_prs(history: list) -> dict:
    """For each session in history (ascending date), decide whether it set
    a PR vs all prior sessions. Returns {date: {weight, e1rm, volume}}.

    Important: sessions are processed in *date* order, so a retroactively-
    added session from March still gets a chance to be a PR against
    whatever preceded it — and anything after March that was previously
    flagged a PR may lose its flag if March's numbers beat it."""
    out: dict = {}
    best_weight = 0.0
    best_e1rm = 0.0
    best_volume = 0.0
    for row in history:
        top_weight = float(row.get("top_weight") or 0)
        top_e1rm = session_top_e1rm(row)
        volume = float(row.get("working_volume") or 0)

        flags = {
            "weight": top_weight > best_weight,
            "e1rm": top_e1rm > best_e1rm,
            "volume": volume > best_volume,
        }
        out[row["date"]] = flags

        if top_weight > best_weight:
            best_weight = top_weight
        if top_e1rm > best_e1rm:
            best_e1rm = top_e1rm
        if volume > best_volume:
            best_volume = volume
    return out


def detect_stall(history: list, min_sessions: int = 3) -> Optional[dict]:
    """A stall = last `min_sessions` sessions have top_weight equal or
    decreasing with similar rep range (±2). Returns dict or None."""
    if len(history) < min_sessions:
        return None
    tail = history[-min_sessions:]
    weights = [float(r.get("top_weight") or 0) for r in tail]
    reps_at = [int(r.get("top_reps_at_top_weight") or 0) for r in tail]
    if any(w == 0 for w in weights):
        return None
    if max(weights) > weights[0]:
        return None
    if max(reps_at) - min(reps_at) > 2:
        return None
    return {
        "weight": weights[-1],
        "reps": reps_at[-1],
        "sessions": min_sessions,
        "since_date": tail[0]["date"],
    }


def recompute_weekly_volume(now=None) -> dict:
    """Roll up per-muscle-group working volume for the current week (Monday
    through Sunday, user-local time) and write as a single row in
    DAILY_SCORES_TABLE keyed `week_<YYYY-MM-DD>`.

    Called by both:
      - compute_lifts (daily 2am PT) — batch refresh for all users' exercises
      - annotate_workout — inline after an annotation so the Progress tab's
        Strength section reflects the new workout immediately (without
        waiting for the overnight cron).

    This is a full rescan of ExercisesTable, not an incremental update — the
    table is small (hundreds of rows at most at current usage) and idempotent
    rewrites are simpler than maintaining a running counter on every put.
    """
    exercises_table = get_table("EXERCISES_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    now = now or local_now()
    week_start = now - timedelta(days=now.weekday())  # Monday
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = (week_start + timedelta(days=6)).strftime("%Y-%m-%d")

    try:
        resp = exercises_table.scan(Limit=2000)
        all_rows = resp.get("Items", [])
    except Exception:
        return {"status": "scan_failed"}

    volume_by_mg: dict = {}
    sessions_by_mg: dict = {}
    for row in all_rows:
        d = row.get("date", "")
        if not (week_start_str <= d <= week_end_str):
            continue
        mg = row.get("muscle_group", "other")
        vol = float(row.get("working_volume") or 0)
        volume_by_mg[mg] = volume_by_mg.get(mg, 0) + vol
        sessions_by_mg.setdefault(mg, set()).add(d)

    volume_row = {
        "date": f"week_{week_start_str}",
        "week_start": week_start_str,
        "week_end": week_end_str,
        "volume_by_muscle_group": {k: round(v, 1) for k, v in volume_by_mg.items()},
        "sessions_by_muscle_group": {k: len(v) for k, v in sessions_by_mg.items()},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    put_item(scores_table, volume_row)
    return volume_row


def recompute_prs_for_canonicals(canonicals: list) -> dict:
    """For each canonical, re-scan its full history and rewrite each
    session row with refreshed e1rm + pr flags. Idempotent. Returns
    {canonical: {pr_count, total_sessions}}."""
    table = get_table("EXERCISES_TABLE")
    summary: dict = {}
    for canonical in canonicals:
        if not canonical:
            continue
        history = scan_exercise_history(table, canonical, days=365)
        if not history:
            continue
        flags_by_date = detect_prs(history)
        pr_count = 0
        for row in history:
            flags = flags_by_date.get(row["date"], {})
            merged = {
                **row,
                "e1rm": session_top_e1rm(row),
                "pr": {
                    "weight": bool(flags.get("weight")),
                    "e1rm": bool(flags.get("e1rm")),
                    "volume": bool(flags.get("volume")),
                },
            }
            put_item(table, merged)
            if any(flags.values()):
                pr_count += 1
        summary[canonical] = {"pr_count": pr_count, "total_sessions": len(history)}
    return summary
