"""App-action telemetry.

One row per client-emitted interaction (tab switch, modal open, button tap,
etc.). Used to answer "which surfaces are actually used" and drive the weekly
rarely-used-feature rollup in compute. Single-user app, so no user_id PK.

Schema (DynamoDB):
  date       (HASH)   YYYY-MM-DD, user-local
  event_id   (RANGE)  <ts_ms>#<uuid4-hex8>  — sortable by time within a day
  action     (S)      short snake_case identifier, e.g. "tab.switch"
  props      (M)      optional freeform attributes (tab, source, duration_ms…)
  ts         (S)      ISO-8601 UTC
  ttl        (N)      epoch seconds; rows expire after 90 days

Writes are idempotent per (date, event_id). The event_id includes a timestamp
so a replayed put overwrites cleanly; we don't dedupe by action.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.db import get_table, put_item
from shared.timezone import local_today_str

_TTL_DAYS = 90
_MAX_ACTION = 64
_MAX_PROPS = 32
_MAX_PROP_KEY = 32
_MAX_PROP_VALUE = 200
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clean_props(props: Optional[dict]) -> dict:
    if not isinstance(props, dict):
        return {}
    out: dict = {}
    for k, v in list(props.items())[:_MAX_PROPS]:
        key = str(k).strip()[:_MAX_PROP_KEY]
        if not key:
            continue
        if v is None:
            continue
        if isinstance(v, bool):
            out[key] = v
        elif isinstance(v, (int, float)):
            out[key] = v
        else:
            out[key] = str(v)[:_MAX_PROP_VALUE]
    return out


def record_event(
    action: str,
    props: Optional[dict] = None,
    date: Optional[str] = None,
    ts: Optional[datetime] = None,
) -> dict:
    """Persist a single event. Returns the stored row.

    Raises ValueError on invalid action. Validation is intentionally strict
    so call sites don't drift into freeform labels.
    """
    if not action or not isinstance(action, str):
        raise ValueError("action is required")
    if len(action) > _MAX_ACTION:
        raise ValueError(f"action too long (max {_MAX_ACTION})")
    if not _ACTION_RE.match(action):
        raise ValueError(
            "action must be snake_case with optional dots, starting with a letter"
        )

    now = ts or _now_utc()
    day = date or local_today_str()
    event_id = f"{int(now.timestamp() * 1000)}#{uuid.uuid4().hex[:8]}"

    item = {
        "date": day,
        "event_id": event_id,
        "action": action,
        "ts": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "ttl": int((now + timedelta(days=_TTL_DAYS)).timestamp()),
    }
    cleaned = _clean_props(props)
    if cleaned:
        item["props"] = cleaned

    put_item(get_table("EVENTS_TABLE"), item)
    return item
