"""Temporal helpers for application-day attribution and source provenance.

Absolute instants are the temporal truth. DynamoDB ``date`` keys are analysis
context derived from those instants, normally in Mateo's configured home
timezone. A caller may explicitly trust a source-provided offset for event-local
day attribution; otherwise aware timestamps are converted to the home timezone.
Naive timestamps are never silently assigned a timezone.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

HOME_TIMEZONE = "America/Los_Angeles"
LOCAL_TZ = ZoneInfo(HOME_TIMEZONE)


def local_now() -> datetime:
    """Current datetime in Mateo's local timezone (tz-aware)."""
    return datetime.now(LOCAL_TZ)


def local_today_str() -> str:
    """Today's date as YYYY-MM-DD in Mateo's local timezone."""
    return local_now().strftime("%Y-%m-%d")


def utc_now() -> datetime:
    """Current UTC datetime — use for ISO timestamps like ingested_at, not for date boundaries."""
    return datetime.now(timezone.utc)


def parse_timestamp(value) -> datetime | None:
    """Parse a source timestamp without inventing missing timezone context.

    ISO-8601 strings (including ``Z`` and HAE's space-separated ``-0700``
    form), aware/naive ``datetime`` objects, and epoch seconds are accepted.
    Naive inputs remain naive so callers must choose an explicit fallback.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw[-1:] in ("Z", "z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def source_date_str(value) -> str | None:
    """Return a validated source-supplied YYYY-MM-DD prefix, if present.

    This is provenance only; it does not imply that the prefix is the
    canonical analysis date or that a naive timestamp is event-local.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if len(raw) < 10:
        return None
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _offset_str(value: datetime) -> str | None:
    offset = value.utcoffset()
    if offset is None:
        return None
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def temporal_metadata(
    value,
    *,
    source_timezone_trusted: bool = False,
    allow_naive_source_date: bool = False,
) -> dict:
    """Build additive provenance plus a canonical analysis date.

    Aware timestamps use their own represented day only when the caller knows
    the offset is trustworthy event-local context. Otherwise they are treated
    as absolute instants and converted to ``HOME_TIMEZONE``. If an input is
    naive, no absolute instant exists; callers may preserve its explicit source
    date as a backward-compatible fallback without claiming timezone context.
    """
    metadata = {}
    source_date = source_date_str(value)
    if source_date:
        metadata["source_date"] = source_date

    parsed = parse_timestamp(value)
    if parsed is None:
        return metadata

    aware = parsed.tzinfo is not None and parsed.utcoffset() is not None
    if aware:
        offset = _offset_str(parsed)
        if offset is not None:
            metadata["source_utc_offset"] = offset
        if source_timezone_trusted:
            metadata["analysis_date"] = parsed.date().isoformat()
            metadata["date_derivation"] = "source_offset"
            metadata["analysis_utc_offset"] = offset
            zone_key = getattr(parsed.tzinfo, "key", None)
            if zone_key:
                metadata["source_timezone"] = zone_key
        else:
            local_value = parsed.astimezone(LOCAL_TZ)
            metadata["analysis_date"] = local_value.date().isoformat()
            metadata["analysis_timezone"] = HOME_TIMEZONE
            metadata["date_derivation"] = "home_timezone"
    elif allow_naive_source_date and source_date:
        metadata["analysis_date"] = source_date
        metadata["date_derivation"] = "source_date_fallback"

    return metadata


def analysis_date_for_timestamp(
    value,
    *,
    source_timezone_trusted: bool = False,
    allow_naive_source_date: bool = False,
) -> str | None:
    """Return only the derived analysis date from :func:`temporal_metadata`."""
    return temporal_metadata(
        value,
        source_timezone_trusted=source_timezone_trusted,
        allow_naive_source_date=allow_naive_source_date,
    ).get("analysis_date")
