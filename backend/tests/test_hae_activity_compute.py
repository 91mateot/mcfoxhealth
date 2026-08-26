"""Compute-path tests for the narrow HAE Activity Daily resolver."""

import importlib.util
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
_COMPUTE_PATH = os.path.join(ROOT, "functions", "compute", "handler.py")


def _handler():
    module_name = "compute_handler_hae_activity_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, _COMPUTE_PATH)
    handler = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = handler
    spec.loader.exec_module(handler)
    return handler


def test_compute_resolver_prefers_daily_summary_preserves_zero_and_manual_fallback():
    handler = _handler()

    assert handler._resolve_activity_for_compute(
        {
            "steps#hae": {"value": 7},
            "steps#hae_daily_summary": {"value": 303},
        },
        "steps",
        "steps#manual",
    ) == {
        "value": 303,
        "source": "hae_daily_summary",
        "metric_source": "steps#hae_daily_summary",
    }
    assert handler._resolve_activity_for_compute(
        {"steps#hae": {"value": 0}},
        "steps",
        "steps#manual",
    )["value"] == 0
    assert handler._resolve_activity_for_compute(
        {"steps#manual": {"value": 5}},
        "steps",
        "steps#manual",
    ) == {
        "value": 5,
        "source": "manual",
        "metric_source": "steps#manual",
    }


def test_baselines_count_completed_daily_activity_once_not_raw_plus_summary(monkeypatch):
    handler = _handler()
    written = []
    previous_day = "2030-04-05"
    metric_rows = {
        previous_day: [
            {"metric_source": "steps#hae", "value": 7},
            {"metric_source": "steps#hae_daily_summary", "value": 303},
        ]
    }

    monkeypatch.setattr(
        handler,
        "local_now",
        lambda: datetime(2030, 4, 6, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    monkeypatch.setattr(handler, "get_table", lambda name: name)
    monkeypatch.setattr(handler, "_get_scoring_config", lambda: {"baseline_window_days": 1})
    monkeypatch.setattr(
        handler,
        "query_items",
        lambda _table, _key, date: metric_rows.get(date, []),
    )
    monkeypatch.setattr(handler, "put_item", lambda _table, item: written.append(item))

    result = handler._compute_baselines()

    assert result["baselines"]["steps"] == 303
    assert result["baselines"]["sample_counts"]["steps"] == 1
    assert written[-1]["steps"] == 303
