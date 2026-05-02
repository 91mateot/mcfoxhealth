"""Unit tests for the time-marked journal-note CRUD path.

Covers:
- append_note writes a new note with id + `at`, leaves morning/evening untouched
- append_note honors a client-supplied `at` when it falls on the same local day
- append_note rejects an `at` that crosses the date boundary
- update_note patches fields and bumps updated_at
- update_note raises KeyError when note id isn't found
- delete_note removes only the matching note
"""
import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.nutrition_service as ns
    return ns


def _wire_table(monkeypatch, ns, storage):
    """In-memory JOURNAL_TABLE stand-in keyed by date."""
    fake_table = MagicMock()

    def fake_get_item(_table, key):
        return storage.get(key.get("date"))

    def fake_put_item(_table, item):
        storage[item["date"]] = dict(item)

    monkeypatch.setattr(ns, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(ns, "get_item", fake_get_item)
    monkeypatch.setattr(ns, "put_item", fake_put_item)


def test_append_note_creates_row_and_does_not_touch_morning(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {"2026-05-02": {
        "date": "2026-05-02",
        "morning_text": "slept ok",
        "mood": 4,
        "morning_saved_at": "2026-05-02T13:00:00+00:00",
    }}
    _wire_table(monkeypatch, ns, storage)

    result = ns.append_note("back feels looser after walk", date="2026-05-02")
    row = storage["2026-05-02"]

    assert result["status"] == "saved"
    assert result["note"]["id"].startswith("note_")
    assert result["note"]["text"] == "back feels looser after walk"
    assert row["notes"][0]["id"] == result["note"]["id"]
    # Morning data must still be intact.
    assert row["morning_text"] == "slept ok"
    assert row["mood"] == 4


def test_append_note_with_client_at_same_local_day(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ns, storage)

    # 2026-05-02 10:00 PDT = 17:00 UTC — still the 2nd in LA.
    result = ns.append_note(
        "mid-morning check",
        date="2026-05-02",
        at="2026-05-02T17:00:00+00:00",
    )
    assert result["note"]["at"].startswith("2026-05-02T17:00")


def test_append_note_rejects_at_that_crosses_local_day(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ns, storage)

    # 2026-05-03 06:00 UTC = 2026-05-02 23:00 PDT — still 5/2 in LA, accepted.
    ns.append_note("ok", date="2026-05-02", at="2026-05-03T06:00:00+00:00")

    # 2026-05-03 12:00 UTC = 2026-05-03 05:00 PDT — now 5/3 in LA, rejected.
    with pytest.raises(ValueError):
        ns.append_note("bad", date="2026-05-02", at="2026-05-03T12:00:00+00:00")


def test_append_note_empty_text_rejected(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ns, storage)
    with pytest.raises(ValueError):
        ns.append_note("   ", date="2026-05-02")


def test_update_note_patches_fields(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ns, storage)

    first = ns.append_note("starter", date="2026-05-02")
    note_id = first["note"]["id"]

    edited = ns.update_note(
        date="2026-05-02",
        note_id=note_id,
        text="starter, but longer",
        mood=3,
        tags=["stretched"],
    )
    assert edited["note"]["text"] == "starter, but longer"
    assert edited["note"]["mood"] == 3
    assert edited["note"]["tags"] == ["stretched"]
    assert edited["note"].get("updated_at"), "updated_at should bump on edit"
    # created_at is preserved.
    assert edited["note"]["created_at"] == first["note"]["created_at"]


def test_update_note_missing_raises_keyerror(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {"2026-05-02": {"date": "2026-05-02", "notes": []}}
    _wire_table(monkeypatch, ns, storage)

    with pytest.raises(KeyError):
        ns.update_note(date="2026-05-02", note_id="note_nope", text="x")


def test_delete_note_removes_only_target(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, ns, storage)

    a = ns.append_note("a", date="2026-05-02")
    b = ns.append_note("b", date="2026-05-02")
    assert len(storage["2026-05-02"]["notes"]) == 2

    ns.delete_note(date="2026-05-02", note_id=a["note"]["id"])
    remaining = storage["2026-05-02"]["notes"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == b["note"]["id"]


def test_delete_note_missing_raises_keyerror(monkeypatch):
    ns = _load_module(monkeypatch)
    storage = {"2026-05-02": {"date": "2026-05-02", "notes": []}}
    _wire_table(monkeypatch, ns, storage)

    with pytest.raises(KeyError):
        ns.delete_note(date="2026-05-02", note_id="note_nope")
