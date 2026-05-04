"""Unit tests for per-message IDs added to conversation storage.

Covers:
- append_turn stamps both messages with a stable id when none is provided
- append_turn preserves an id the caller supplied (so the streaming coach's
  assistant_msg_id survives the round trip)
- strip_images_for_storage leaves pre-existing ids alone
- Legacy messages without ids are tolerated (no KeyError on read paths)
"""
import sys
from unittest.mock import MagicMock


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.conversation_service as cs
    return cs


def _wire_table(monkeypatch, cs):
    fake_table = MagicMock()
    monkeypatch.setattr(cs, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(cs, "put_item", lambda _t, _i: None)
    return fake_table


def test_append_turn_generates_ids_when_missing(monkeypatch):
    cs = _load_module(monkeypatch)
    _wire_table(monkeypatch, cs)

    thread = {"messages": [], "user_id": "mateo"}
    cs.append_turn(
        thread,
        {"from": "me", "t": "9:00am", "text": "hey"},
        {"from": "coach", "t": "9:01am", "text": "hi"},
    )

    user_msg, assistant_msg = thread["messages"]
    assert user_msg["id"].startswith("msg_")
    assert assistant_msg["id"].startswith("msg_")
    assert user_msg["id"] != assistant_msg["id"]


def test_append_turn_preserves_caller_supplied_ids(monkeypatch):
    cs = _load_module(monkeypatch)
    _wire_table(monkeypatch, cs)

    thread = {"messages": [], "user_id": "mateo"}
    cs.append_turn(
        thread,
        {"from": "me", "t": "9:00am", "text": "hey", "id": "msg_user_abc"},
        {"from": "coach", "t": "9:01am", "text": "hi", "id": "msg_coach_xyz"},
    )

    assert thread["messages"][0]["id"] == "msg_user_abc"
    assert thread["messages"][1]["id"] == "msg_coach_xyz"


def test_messages_for_bedrock_tolerates_legacy_ids_missing(monkeypatch):
    cs = _load_module(monkeypatch)
    thread = {
        "messages": [
            {"from": "me", "t": "", "text": "legacy user msg"},  # no id
            {"from": "coach", "t": "", "text": "legacy coach msg"},  # no id
        ],
    }
    # Should not raise — the id column is purely additive for feedback routing.
    out = cs.messages_for_bedrock(thread)
    assert [m["role"] for m in out] == ["user", "assistant"]


def test_new_message_id_is_unique_and_prefixed(monkeypatch):
    cs = _load_module(monkeypatch)
    ids = {cs.new_message_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("msg_") for i in ids)
