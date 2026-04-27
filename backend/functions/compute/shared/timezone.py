"""Mateo lives in San Diego (America/Los_Angeles). When the app needs "today",
use local time — not UTC, which flips at 5pm PDT / 4pm PST."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def local_now() -> datetime:
    """Current datetime in Mateo's local timezone (tz-aware)."""
    return datetime.now(LOCAL_TZ)


def local_today_str() -> str:
    """Today's date as YYYY-MM-DD in Mateo's local timezone."""
    return local_now().strftime("%Y-%m-%d")


def utc_now() -> datetime:
    """Current UTC datetime — use for ISO timestamps like ingested_at, not for date boundaries."""
    return datetime.now(timezone.utc)
