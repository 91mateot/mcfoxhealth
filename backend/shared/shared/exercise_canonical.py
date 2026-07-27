"""Shared exercise canonicalization vocabulary.

The single source of truth for turning a human-readable exercise name into a
stable ``canonical`` slug, plus the app's muscle-group vocabulary. Extracted
from workout_service.py so BOTH the LLM lift-parser path AND the Hevy poller
path canonicalize identically — a divergent second canonicalizer would split
the same exercise across two keys in ``fitness-exercises`` and quietly break
PR/e1RM history joins.

workout_service.py re-exports ``_canonicalize``, ``_SYNONYMS`` and
``MUSCLE_GROUPS`` from here for backwards compatibility.
"""

import re

# The muscle-group vocabulary the app reasons over end-to-end (coach context,
# workout proposer, weekly volume roll-up). Hevy's own 20-value enum is mapped
# ONTO this set in hevy_client.py; keep the two in sync.
MUSCLE_GROUPS = {
    "chest",
    "back",
    "shoulders",
    "arms",
    "legs",
    "core",
    "glutes",
    "cardio",
    "mobility",
    "other",
}

# Human phrasings → canonical slug. The LLM lift-parser is expected to
# canonicalize, but we normalize free-form / Hevy titles through here too.
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


def canonicalize(name: str) -> str:
    """Slugify an exercise name. Looks up synonyms first; falls back to a
    deterministic lowercase/underscore slug.

    Hevy titles carry a parenthetical equipment qualifier, e.g.
    ``"Bench Press (Barbell)"``. We strip that trailing qualifier before the
    synonym lookup so it collapses onto the same slug the LLM parser produces
    for "bench press".
    """
    if not name:
        return "unknown"
    lower = name.strip().lower()
    # Strip a trailing "(equipment)" qualifier Hevy appends to its titles.
    lower = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
    if lower in _SYNONYMS:
        return _SYNONYMS[lower]
    # Try stripping leading qualifiers (barbell/dumbbell/cable) to hit synonyms.
    stripped = re.sub(r"^(barbell|dumbbell|cable|machine|bb|db)\s+", "", lower)
    if stripped in _SYNONYMS:
        return _SYNONYMS[stripped]
    # Deterministic slug fallback.
    slug = re.sub(r"[^\w\s-]", "", lower)
    slug = re.sub(r"\s+", "_", slug).strip("_")
    return slug[:50] or "unknown"
