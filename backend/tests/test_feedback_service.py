"""Unit tests for thumbs-up/down feedback.

Covers:
- save_feedback writes (user_id, target_key) composite key with signal + metadata
- Re-voting overwrites: same target_key, new signal, preserved created_at
- Optional note is stored when provided, dropped when empty/whitespace
- Invalid signal / target_type / target_id raise ValueError
"""

import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.feedback_service as fb
    return fb


def _wire_table(monkeypatch, fb, storage):
    fake_table = MagicMock()

    def fake_get_item(_table, key):
        return storage.get((key["user_id"], key["target_key"]))

    def fake_put_item(_table, item):
        storage[(item["user_id"], item["target_key"])] = dict(item)

    monkeypatch.setattr(fb, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(fb, "get_item", fake_get_item)
    monkeypatch.setattr(fb, "put_item", fake_put_item)


def test_save_coach_msg_thumbs_up(monkeypatch):
    fb = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, fb, storage)

    result = fb.save_feedback("up", "coach_msg", "msg_abc")
    assert result["ok"] is True
    row = storage[("mateo", "coach_msg#msg_abc")]
    assert row["signal"] == "up"
    assert row["target_type"] == "coach_msg"
    assert row["target_id"] == "msg_abc"
    assert row["created_at"] == row["updated_at"]
    assert "note" not in row


def test_revote_overwrites_signal_and_preserves_created_at(monkeypatch):
    fb = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, fb, storage)

    first = fb.save_feedback("up", "proposal", "2026-05-03#t1")
    first_created = storage[("mateo", "proposal#2026-05-03#t1")]["created_at"]

    second = fb.save_feedback("down", "proposal", "2026-05-03#t1", note="too intense")
    row = storage[("mateo", "proposal#2026-05-03#t1")]
    assert row["signal"] == "down"
    assert row["note"] == "too intense"
    assert row["created_at"] == first_created, "created_at should survive a re-vote"
    assert row["updated_at"] >= first_created


def test_note_whitespace_dropped(monkeypatch):
    fb = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, fb, storage)

    fb.save_feedback("down", "coach_msg", "msg_x", note="   ")
    row = storage[("mateo", "coach_msg#msg_x")]
    assert "note" not in row


def test_note_truncated_to_max(monkeypatch):
    fb = _load_module(monkeypatch)
    storage = {}
    _wire_table(monkeypatch, fb, storage)

    fb.save_feedback("down", "coach_msg", "msg_x", note="a" * 1000)
    row = storage[("mateo", "coach_msg#msg_x")]
    assert len(row["note"]) == 500


def test_invalid_signal_rejected(monkeypatch):
    fb = _load_module(monkeypatch)
    _wire_table(monkeypatch, fb, {})
    with pytest.raises(ValueError):
        fb.save_feedback("maybe", "coach_msg", "msg_x")


def test_invalid_target_type_rejected(monkeypatch):
    fb = _load_module(monkeypatch)
    _wire_table(monkeypatch, fb, {})
    with pytest.raises(ValueError):
        fb.save_feedback("up", "random", "msg_x")


def test_missing_target_id_rejected(monkeypatch):
    fb = _load_module(monkeypatch)
    _wire_table(monkeypatch, fb, {})
    with pytest.raises(ValueError):
        fb.save_feedback("up", "coach_msg", "   ")
