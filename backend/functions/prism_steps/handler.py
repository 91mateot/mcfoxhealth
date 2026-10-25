"""Single-day Steps source evidence. No writes or broad dashboard credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl

import boto3

from shared.hae_daily import HAE_DAILY_ACTIVITY_METRICS, resolve_hae_daily_activity


PATH = "/api/prism/steps"
FIELDS = (
    "date", "metric_source", "value", "unit", "source_ts", "hae_semantics",
    "hae_raw_metric_name", "hae_raw_units", "hae_source", "ingested_at",
    "updated_at", "source_date", "analysis_date", "source_utc_offset",
    "analysis_utc_offset", "source_timezone", "analysis_timezone",
    "date_derivation", "hae_automation_name", "hae_automation_aggregation",
    "hae_automation_period",
)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, separators=(",", ":"), allow_nan=False),
    }


def _valid_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _authorized(headers):
    """Read each time: disabling/rotating the secret must not leave a warm cache."""
    supplied = [v for k, v in headers.items() if k.lower() == "x-prism-steps-key"]
    if len(supplied) != 1 or not isinstance(supplied[0], str):
        return False
    token = supplied[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        return False
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["PRISM_STEPS_SECRET_ARN"]
    )["SecretString"]
    if len(secret) > 2048:
        return False
    config = json.loads(secret)
    digest = config.get("token_sha256")
    expiry = config.get("expires_at")
    if config.get("enabled") is not True or not isinstance(digest, str):
        return False
    if not re.fullmatch(r"[a-f0-9]{64}", digest) or not isinstance(expiry, str):
        return False
    expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    if expires.utcoffset() is None or expires <= datetime.now(timezone.utc):
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), digest)


def _get_row(table, day, source):
    aliases = {f"#f{i}": field for i, field in enumerate(FIELDS)}
    return table.get_item(
        Key={"date": day, "metric_source": source},
        ConsistentRead=True,
        ProjectionExpression=", ".join(aliases),
        ExpressionAttributeNames=aliases,
    ).get("Item")


def _observation(row, resolved, day):
    value = row.get("value")
    # DynamoDB numbers arrive as Decimal. Reject bool, NaN, fractional and
    # negative counts, rather than rounding corrupt storage into an observation.
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("invalid stored count")
    number = Decimal(value)
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError("invalid stored count")
    if number > 2**53 - 1 or row.get("unit") != "count":
        raise ValueError("invalid stored count/unit")
    if row.get("date") != day or row.get("metric_source") != resolved["metric_source"]:
        raise ValueError("source identity mismatch")
    if resolved["source"] == "hae_daily_summary" and row.get("hae_semantics") != "completed_daily_summary":
        raise ValueError("invalid summary semantics")
    provenance = {}
    for field in FIELDS:
        if field in ("date", "metric_source", "value", "unit"):
            continue
        raw = row.get(field)
        if raw is not None and (not isinstance(raw, str) or len(raw) > 512):
            raise ValueError("invalid stored metadata")
        provenance[field] = raw
    observation = {
        "value": int(number), "unit": "count", "metric_source": row["metric_source"],
        "source_policy": resolved["source"],
        "semantics": "completed_daily_summary" if resolved["source"] == "hae_daily_summary"
        else "legacy_hae_aggregate",
        "quality": "stored_value_valid", "provenance": provenance,
    }
    # A deterministic content fingerprint, not a monotonic source revision.
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"))
    observation["content_fingerprint"] = hashlib.sha256(encoded.encode()).hexdigest()
    return observation


def lambda_handler(event, context):
    if event.get("version") != "2.0" or event.get("rawPath") != PATH:
        return _response(404, {"error": "not_found"})
    if event.get("requestContext", {}).get("http", {}).get("method") != "GET":
        return _response(405, {"error": "method_not_allowed"})
    if event.get("body"):
        return _response(400, {"error": "body_not_allowed"})
    try:
        pairs = parse_qsl(event.get("rawQueryString", ""), keep_blank_values=True,
                          strict_parsing=True, max_num_fields=2)
    except (TypeError, ValueError):
        return _response(400, {"error": "invalid_query"})
    if len(pairs) != 1 or pairs[0][0] != "date" or not _valid_day(pairs[0][1]):
        return _response(400, {"error": "single_date_required"})
    day = pairs[0][1]
    try:
        if not _authorized(event.get("headers") or {}):
            return _response(401, {"error": "unauthorized"})
        allowed_day = os.environ["PRISM_STEPS_ALLOWED_DATE"]
        if not _valid_day(allowed_day) or day != allowed_day:
            return _response(403, {"error": "date_not_allowed"})
        table = boto3.resource("dynamodb").Table(os.environ["HEALTH_METRICS_TABLE"])
        spec = HAE_DAILY_ACTIVITY_METRICS["steps"]
        rows = {}
        for source in (spec["summary_source"], spec["legacy_source"]):
            row = _get_row(table, day, source)
            if row:
                rows[source] = row
            if row and row.get("value") is not None:
                break
        resolved = resolve_hae_daily_activity(rows, "steps")
        observation = None
        if resolved["metric_source"] is not None:
            observation = _observation(rows[resolved["metric_source"]], resolved, day)
        return _response(200, {
            "version": 1, "backend": "mcfox", "transport": "health_auto_export",
            "metric": "step_count", "date": day,
            "availability": "available" if observation is not None else "unavailable",
            "observation": observation,
            "completeness": {"lookup_complete": True, "next_cursor": None,
                             "phone_data_complete": "unknown"},
        })
    except Exception:
        # Do not log event, credentials, source row, exceptions or AWS response.
        return _response(503, {"error": "source_unavailable"})
