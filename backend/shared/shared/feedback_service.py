"""Thumbs-up/down feedback on coach messages and workout proposals.

One row per (user_id, target_type, target_id). Re-voting overwrites the prior
signal — we always reflect current sentiment, never a full history. A short
free-form `note` is supported (used by the UI on thumbs-down for "why?").
"""

from datetime import datetime, timezone
from typing import Optional

from shared.db import get_item, get_table, put_item
from shared.timezone import local_today_str

_USER_ID = "mateo"

_SIGNALS = ("up", "down")
_TARGET_TYPES = ("coach_msg", "proposal")
_MAX_TARGET_ID = 200
_MAX_NOTE = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _target_key(target_type: str, target_id: str) -> str:
    return f"{target_type}#{target_id}"


def save_feedback(
    signal: str,
    target_type: str,
    target_id: str,
    note: Optional[str] = None,
) -> dict:
    if signal not in _SIGNALS:
        raise ValueError(f"signal must be one of {_SIGNALS}")
    if target_type not in _TARGET_TYPES:
        raise ValueError(f"target_type must be one of {_TARGET_TYPES}")
    target_id = (target_id or "").strip()
    if not target_id:
        raise ValueError("target_id is required")
    if len(target_id) > _MAX_TARGET_ID:
        raise ValueError(f"target_id too long (max {_MAX_TARGET_ID})")

    clean_note: Optional[str] = None
    if note is not None:
        clean_note = str(note).strip()[:_MAX_NOTE] or None

    table = get_table("FEEDBACK_TABLE")
    key = {"user_id": _USER_ID, "target_key": _target_key(target_type, target_id)}
    existing = get_item(table, key) or {}

    now = _now_iso()
    item = {
        **key,
        "signal": signal,
        "target_type": target_type,
        "target_id": target_id,
        "date": local_today_str(),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    if clean_note is not None:
        item["note"] = clean_note

    put_item(table, item)
    return {"ok": True, "feedback": item}
