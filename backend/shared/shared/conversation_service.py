"""Conversation history for the coach.

Threads are a flat list of {from, t, text, imgCount?} items persisted to
ConversationsTable. A thread auto-rolls over after 6h of silence; long
threads get a summary prepended to future Bedrock context once they pass
a turn threshold.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.db import get_table, get_item, put_item, query_items

logger = logging.getLogger(__name__)

_USER_ID = "mateo"
_IDLE_CUTOFF = timedelta(hours=6)
_KEEP_VERBATIM = 20            # messages always sent verbatim
_SUMMARY_MIN_COUNT = 20        # only summarize once the thread exceeds this
_SUMMARY_STEP = 10             # re-summarize after this many new older-than-K messages accumulate
_MAX_PERSISTED_MESSAGES = 500  # hard cap to stay under DynamoDB item-size budget


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept both "...Z" and "...+00:00" forms.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _new_id() -> str:
    return f"conv_{int(time.time() * 1000)}"


def new_message_id() -> str:
    """Stable per-message ID used as a feedback target."""
    return f"msg_{uuid.uuid4().hex[:16]}"


def _blank_thread() -> dict:
    now = _now_iso()
    return {
        "user_id": _USER_ID,
        "conversation_id": _new_id(),
        "messages": [],
        "summary": None,
        "summarized_through": 0,
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }


def get_latest(user_id: str = _USER_ID) -> Optional[dict]:
    """Return the single most recent thread for this user, or None."""
    try:
        table = get_table("CONVERSATIONS_TABLE")
    except ValueError:
        return None
    rows = query_items(
        table,
        pk_name="user_id",
        pk_value=user_id,
        sk_name="updated_at",
        reverse=True,
        limit=1,
        index_name="by-updated",
    )
    return rows[0] if rows else None


def list_recent(user_id: str = _USER_ID, limit: int = 20) -> list[dict]:
    """Return recent threads for this user, newest first.

    Each entry is projected to keep payloads small: no full messages, just a
    preview string so the UI can render a list without hydrating thread bodies.
    """
    try:
        table = get_table("CONVERSATIONS_TABLE")
    except ValueError:
        return []
    rows = query_items(
        table,
        pk_name="user_id",
        pk_value=user_id,
        sk_name="updated_at",
        reverse=True,
        limit=limit,
        index_name="by-updated",
    )
    out = []
    for row in rows:
        out.append({
            "conversation_id": row.get("conversation_id"),
            "updated_at": row.get("updated_at"),
            "created_at": row.get("created_at"),
            "message_count": int(row.get("message_count") or 0),
            "preview": _build_preview(row.get("messages") or []),
        })
    return out


def _build_preview(messages: list) -> str:
    """Short preview — first user message if any, else the first message text."""
    for m in messages:
        if m.get("from") == "me":
            text = (m.get("text") or "").strip()
            if text:
                return text[:80]
    for m in messages:
        text = (m.get("text") or "").strip()
        if text:
            return text[:80]
    return ""


def load(conversation_id: str) -> Optional[dict]:
    if not conversation_id:
        return None
    try:
        table = get_table("CONVERSATIONS_TABLE")
    except ValueError:
        return None
    return get_item(table, {"user_id": _USER_ID, "conversation_id": conversation_id})


def resolve_thread(conversation_id: Optional[str]) -> dict:
    """Pick the thread we should append to for this turn.

    - Explicit conversation_id wins if it exists.
    - Else, resume the latest thread if it was active within 6h.
    - Else, start a fresh one.

    Returned thread is NOT yet persisted — the caller mutates and saves
    after the turn completes.
    """
    if conversation_id:
        existing = load(conversation_id)
        if existing is not None:
            return existing

    latest = get_latest()
    if latest is not None:
        updated = _parse_iso(latest.get("updated_at", ""))
        if updated and datetime.now(timezone.utc) - updated <= _IDLE_CUTOFF:
            return latest

    return _blank_thread()


def strip_images_for_storage(msg: dict) -> dict:
    """Drop image bytes but record a count so the UI can show a placeholder.

    Base64 payloads would blow the 400KB DynamoDB item limit on a 20-turn thread.
    """
    stripped = {
        "from": msg.get("from", "coach"),
        "t": msg.get("t", ""),
        "text": (msg.get("text") or "")[:8000],  # defensive truncation
        "id": msg.get("id") or new_message_id(),
    }
    imgs = msg.get("images")
    if isinstance(imgs, list) and imgs:
        stripped["imgCount"] = len(imgs)
    return stripped


def append_turn(thread: dict, user_msg: dict, assistant_msg: dict) -> dict:
    """Append a user/assistant pair and persist. Mutates thread in place."""
    messages = list(thread.get("messages") or [])
    messages.append(strip_images_for_storage(user_msg))
    messages.append(strip_images_for_storage(assistant_msg))

    if len(messages) > _MAX_PERSISTED_MESSAGES:
        # Drop oldest; the summary (if present) already captures them.
        excess = len(messages) - _MAX_PERSISTED_MESSAGES
        messages = messages[excess:]

    thread["messages"] = messages
    thread["message_count"] = int(thread.get("message_count") or 0) + 2
    thread["updated_at"] = _now_iso()
    if not thread.get("created_at"):
        thread["created_at"] = thread["updated_at"]
    if not thread.get("conversation_id"):
        thread["conversation_id"] = _new_id()
    thread["user_id"] = _USER_ID

    try:
        table = get_table("CONVERSATIONS_TABLE")
        put_item(table, thread)
    except Exception:
        logger.exception("failed to persist conversation %s", thread.get("conversation_id"))
    return thread


def messages_for_bedrock(thread: dict) -> list[dict]:
    """Build the Bedrock message list from persisted history.

    The caller appends the *current* user turn (with images) after this.
    """
    messages = list(thread.get("messages") or [])
    tail = messages[-_KEEP_VERBATIM:] if len(messages) > _KEEP_VERBATIM else messages

    out: list[dict] = []
    summary = thread.get("summary")
    if summary:
        out.append({
            "role": "user",
            "content": [{
                "text": f"[Summary of earlier conversation — for context only, do not reference verbatim]\n{summary}",
            }],
        })
        out.append({
            "role": "assistant",
            "content": [{"text": "Understood."}],
        })

    for m in tail:
        role = "user" if m.get("from") == "me" else "assistant"
        text = (m.get("text") or "").strip()
        if not text:
            # Skip image-only historical turns — we have no bytes to send.
            continue
        out.append({"role": role, "content": [{"text": text}]})

    return out


def maybe_summarize(
    thread: dict,
    bedrock_client,
    model_id: str,
    reasoning_effort: str = "low",
) -> None:
    """If the thread has grown enough, summarize older turns. Mutates + persists."""
    messages = list(thread.get("messages") or [])
    total = len(messages)
    if total <= _SUMMARY_MIN_COUNT:
        return

    older_count = total - _KEEP_VERBATIM
    last_summarized = int(thread.get("summarized_through") or 0)
    if older_count - last_summarized < _SUMMARY_STEP:
        return

    older = messages[:older_count]
    summary_prior = thread.get("summary") or ""
    transcript = _render_transcript(older)

    system = (
        "You compress a fitness-coaching chat transcript into a compact context summary. "
        "Keep concrete facts (meals, workouts, sleep, how Mateo felt), user preferences, "
        "and any commitments or open threads. Omit pleasantries. Third-person, 150 words max. "
        "If a prior summary exists, fold it in — do not duplicate."
    )
    user = f"Prior summary:\n{summary_prior or '(none)'}\n\nNew older turns to fold in:\n{transcript}"

    try:
        resp = bedrock_client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": 400},
            additionalModelRequestFields={"reasoning": {"effort": reasoning_effort}},
            requestMetadata={
                "application": "prism-coach",
                "purpose": "conversation-summary",
                "reasoning_effort": reasoning_effort,
            },
        )
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks if "text" in b).strip()
        if text:
            thread["summary"] = text
            thread["summarized_through"] = older_count
            try:
                table = get_table("CONVERSATIONS_TABLE")
                put_item(table, thread)
            except Exception:
                logger.exception("failed to persist summary for %s", thread.get("conversation_id"))
    except Exception:
        logger.exception("summarize call failed for %s", thread.get("conversation_id"))


def _render_transcript(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        who = "Mateo" if m.get("from") == "me" else "Coach"
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)
