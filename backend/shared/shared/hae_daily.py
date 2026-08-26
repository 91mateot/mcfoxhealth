"""Source-specific HAE completed-day activity contract.

This is deliberately narrow: it resolves the seven approved Health Auto
Export Activity Daily metrics without creating a general provenance system.
Raw HAE observations continue to use their established ``#hae`` identities;
completed summaries use additive ``#hae_daily_summary`` identities.
"""

from __future__ import annotations

import re
from typing import Mapping


def normalize_hae_metric_name(value: object) -> str:
    """Normalize HAE's v1/v2 metric spellings without changing the raw name."""
    return re.sub(r"[\s_-]+", "", str(value or "").strip().lower())


# Canonical application key -> source-specific storage contract.
# Daily summary values are source-provided completed-day totals. They must not
# be merged into the raw sample ledgers that underpin legacy ``#hae`` rows.
HAE_DAILY_ACTIVITY_METRICS = {
    "active_cal": {
        "raw_names": ("active_energy",),
        "summary_source": "active_cal#hae_daily_summary",
        "legacy_source": "active_cal#hae",
        "unit": "kcal",
    },
    "exercise_min": {
        "raw_names": ("apple_exercise_time",),
        "summary_source": "exercise_min#hae_daily_summary",
        "legacy_source": "exercise_min#hae",
        "unit": "min",
    },
    "steps": {
        "raw_names": ("step_count",),
        "summary_source": "steps#hae_daily_summary",
        "legacy_source": "steps#hae",
        "unit": "count",
    },
    "walk_distance": {
        "raw_names": ("walking_running_distance",),
        "summary_source": "walk_distance#hae_daily_summary",
        "legacy_source": "walk_distance#hae",
        "unit": "mi",
    },
    "stand_min": {
        "raw_names": ("apple_stand_time",),
        "summary_source": "stand_min#hae_daily_summary",
        "legacy_source": "stand_min#hae",
        "unit": "min",
    },
    "stand_hours": {
        "raw_names": ("apple_stand_hour",),
        "summary_source": "stand_hours#hae_daily_summary",
        "legacy_source": "stand_hours#hae",
        "unit": "count",
    },
    "flights": {
        "raw_names": ("flights_climbed",),
        "summary_source": "flights#hae_daily_summary",
        "legacy_source": "flights#hae",
        "unit": "count",
    },
}

_DAILY_BY_RAW_NAME = {
    normalize_hae_metric_name(raw_name): spec
    for spec in HAE_DAILY_ACTIVITY_METRICS.values()
    for raw_name in spec["raw_names"]
}


def daily_activity_spec_for_raw_name(raw_name: object):
    """Return the approved completed-day spec for a raw HAE metric name."""
    return _DAILY_BY_RAW_NAME.get(normalize_hae_metric_name(raw_name))


def resolve_hae_daily_activity(
    metric_map: Mapping[str, Mapping[str, object]],
    metric_key: str,
):
    """Resolve one activity total without collapsing zero into missing.

    Returned source values are intentionally limited to the HAE contract:
    ``hae_daily_summary``, ``legacy_hae_aggregate``, and ``unavailable``.
    Callers may add a separate manual fallback after this resolver returns
    unavailable.
    """
    spec = HAE_DAILY_ACTIVITY_METRICS[metric_key]
    for source, source_label in (
        (spec["summary_source"], "hae_daily_summary"),
        (spec["legacy_source"], "legacy_hae_aggregate"),
    ):
        item = metric_map.get(source)
        if isinstance(item, Mapping) and item.get("value") is not None:
            return {
                "value": item["value"],
                "source": source_label,
                "metric_source": source,
            }
    return {
        "value": None,
        "source": "unavailable",
        "metric_source": None,
    }
