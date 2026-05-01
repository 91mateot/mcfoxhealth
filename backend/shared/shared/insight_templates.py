"""Natural-language templates for numeric correlations.

One template per (input, outcome) pair. Inputs carry a `numeric:` prefix on the
`tag` field in CorrelationsTable so they don't collide with journal-tag rows.

`render_insight` receives the correlation r, regression slope (output units per
input unit), and sample mean/std so templates can express the effect in
real-world terms ("Every 100mg of caffeine costs ~6 min deep sleep" rather
than "r = -0.42").
"""

from typing import Optional


# ─── Pair definitions ───────────────────────────────────────────────
#
# Each entry describes one correlation pair the compute job evaluates.
# `lag_days` shifts the outcome forward relative to the input date.
# `units_label` is read-only metadata surfaced in the UI.

PAIRS: list[dict] = [
    # Caffeine consumed during the day → that night's sleep.
    {
        "input": "caffeine_mg",
        "input_label": "Caffeine",
        "input_units": "mg",
        "outcome": "sleep_score",
        "outcome_label": "Sleep score",
        "outcome_units": "%",
        "lag_days": 0,
        "better": "down",  # more caffeine → lower sleep is "expected negative"
    },
    {
        "input": "caffeine_mg",
        "input_label": "Caffeine",
        "input_units": "mg",
        "outcome": "deep_pct",
        "outcome_label": "Deep sleep",
        "outcome_units": "%",
        "lag_days": 0,
        "better": "down",
    },
    {
        "input": "caffeine_mg",
        "input_label": "Caffeine",
        "input_units": "mg",
        "outcome": "rem_pct",
        "outcome_label": "REM sleep",
        "outcome_units": "%",
        "lag_days": 0,
        "better": "down",
    },
    # Protein intake on day N → recovery markers on day N+1.
    {
        "input": "protein_total",
        "input_label": "Protein",
        "input_units": "g",
        "outcome": "hrv",
        "outcome_label": "HRV next morning",
        "outcome_units": "ms",
        "lag_days": 1,
        "better": "up",
    },
    {
        "input": "protein_total",
        "input_label": "Protein",
        "input_units": "g",
        "outcome": "recovery",
        "outcome_label": "Recovery next morning",
        "outcome_units": "%",
        "lag_days": 1,
        "better": "up",
    },
    # Hydration → same-day recovery / HRV. Journal "hydrated" tag already
    # captures the binary case; this adds the continuous dose-response.
    {
        "input": "water_oz",
        "input_label": "Water",
        "input_units": "oz",
        "outcome": "recovery",
        "outcome_label": "Recovery",
        "outcome_units": "%",
        "lag_days": 0,
        "better": "up",
    },
    {
        "input": "water_oz",
        "input_label": "Water",
        "input_units": "oz",
        "outcome": "hrv",
        "outcome_label": "HRV",
        "outcome_units": "ms",
        "lag_days": 0,
        "better": "up",
    },
    # Today's strain → tomorrow's recovery / HRV. Whoop staple.
    {
        "input": "strain",
        "input_label": "Strain",
        "input_units": "",
        "outcome": "recovery",
        "outcome_label": "Recovery next morning",
        "outcome_units": "%",
        "lag_days": 1,
        "better": "down",
    },
    {
        "input": "strain",
        "input_label": "Strain",
        "input_units": "",
        "outcome": "hrv",
        "outcome_label": "HRV next morning",
        "outcome_units": "ms",
        "lag_days": 1,
        "better": "down",
    },
    # Sleep duration (hrs) → same-day strain capacity.
    {
        "input": "sleep_hours",
        "input_label": "Sleep",
        "input_units": "hrs",
        "outcome": "strain",
        "outcome_label": "Strain",
        "outcome_units": "",
        "lag_days": 0,
        "better": "up",
    },
]


# ─── Plain-English insight rendering ─────────────────────────────────


def render_insight(
    pair: dict,
    r: float,
    slope: float,
    n: int,
    x_mean: float,
    x_std: float,
) -> str:
    """Return one plain-English sentence describing the correlation.

    We frame the effect in per-real-unit terms so the reader sees a number they
    can act on. Step sizes are chosen per-input (100 mg caffeine, 10 g protein,
    8 oz water, 1 pt strain, 1 hr sleep).
    """
    input_key = pair["input"]
    step, unit_phrase = _STEP_BY_INPUT.get(input_key, (1, f"{pair['input_units']}"))
    direction = "raises" if slope > 0 else "lowers"
    effect = abs(slope) * step

    outcome_units = pair["outcome_units"]
    effect_str = _fmt_effect(effect, outcome_units)

    # Same-day vs. next-day phrasing — next-day reads more naturally as
    # "the morning after" than as "next-day X".
    if pair["lag_days"] >= 1:
        subject = f"each extra {unit_phrase}"
        verb_phrase = f"{direction} your {pair['outcome_label'].lower()}"
    else:
        subject = f"each extra {unit_phrase}"
        verb_phrase = f"{direction} your {pair['outcome_label'].lower()}"

    base = f"{subject.capitalize()} {verb_phrase} by about {effect_str}"

    # Append a soft confidence qualifier so the reader can weight the claim.
    qualifier = _confidence_phrase(n, abs(r))
    if qualifier:
        base += f" ({qualifier})"
    return base + "."


_STEP_BY_INPUT: dict[str, tuple[float, str]] = {
    "caffeine_mg": (100, "100 mg of caffeine"),
    "protein_total": (10, "10 g of protein"),
    "water_oz": (8, "8 oz of water"),
    "strain": (1, "1 point of strain"),
    "sleep_hours": (1, "1 hour of sleep"),
}


def _fmt_effect(val: float, units: str) -> str:
    if units == "%":
        return f"{val:.1f}%"
    if units == "ms":
        return f"{val:.1f} ms"
    if units == "hrs":
        return f"{val:.1f} hrs"
    if units == "":
        return f"{val:.1f}"
    return f"{val:.1f} {units}"


def _confidence_phrase(n: int, abs_r: float) -> Optional[str]:
    if n >= 30 and abs_r >= 0.4:
        return "strong pattern"
    if n >= 15 and abs_r >= 0.3:
        return "moderate pattern"
    if n >= 10 and abs_r >= 0.2:
        return "early signal"
    return None


def confidence_tier(n: int) -> str:
    if n >= 30:
        return "high"
    if n >= 15:
        return "medium"
    return "low"
