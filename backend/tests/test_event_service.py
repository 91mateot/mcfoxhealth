"""Unit tests for app-action telemetry.

Covers:
- record_event writes a (date, event_id) row with action + ts + ttl
- Invalid action strings raise ValueError
- Props are cleaned: Nones stripped, values truncated, size-capped
- event_id is sortable by time within a day
"""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.event_service as ev
    return ev


def _wire_table(monkeypatch, ev, storage):
    fake_table = MagicMock()

    def fake_put_item(_table, item):
        storage[(item["date"], item["event_id"])] = dict(item)

    monkeypatch.setattr(ev, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(ev, "put_item", fake_put_item)


def test_record_event_writes_minimal_row(monkeypatch):
    ev = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ev, storage)

    item = ev.record_event("tab.view", date="2026-05-03")
    assert item["action"] == "tab.view"
    assert item["date"] == "2026-05-03"
    assert "#" in item["event_id"]
    assert item["ttl"] > 0
    assert "props" not in item


def test_record_event_stores_props(monkeypatch):
    ev = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ev, storage)

    item = ev.record_event(
        "tab.view",
        props={"tab": "today", "duration_ms": 1234, "active": True, "nope": None},
    )
    assert item["props"] == {"tab": "today", "duration_ms": 1234, "active": True}


def test_invalid_action_rejected(monkeypatch):
    ev = _load_module(monkeypatch)
    _wire_table(monkeypatch, ev, {})
    with pytest.raises(ValueError):
        ev.record_event("Tab.View")  # caps not allowed
    with pytest.raises(ValueError):
        ev.record_event("tab view")  # space not allowed
    with pytest.raises(ValueError):
        ev.record_event("")
    with pytest.raises(ValueError):
        ev.record_event("1.starts.with.digit")


def test_event_id_is_time_sortable(monkeypatch):
    ev = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ev, storage)

    a = ev.record_event("x", ts=datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc))
    b = ev.record_event("x", ts=datetime(2026, 5, 3, 10, 0, 1, tzinfo=timezone.utc))
    assert a["event_id"] < b["event_id"]


def test_props_truncated(monkeypatch):
    ev = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ev, storage)

    long_val = "a" * 1000
    item = ev.record_event("x", props={"note": long_val})
    assert len(item["props"]["note"]) == 200
