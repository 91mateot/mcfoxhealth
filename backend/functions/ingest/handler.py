"""
Ingest Lambda — handles incoming health data from three sources:
  POST /ingest/health   — HealthAutoExport (Apple Health)
  POST /ingest/withings  — Withings webhook notifications
  POST /ingest/strava    — Strava webhook events
  GET  /ingest/strava    — Strava webhook verification
"""

import base64
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger("ingest")
logger.setLevel(logging.INFO)

from shared.db import (
    get_item,
    get_table,
    put_item,
    put_item_conditionally,
    query_items,
)
from shared.samples_ledger import read_merged_samples, write_sharded_ledger
from shared.hevy_client import (
    body_measurement_to_metrics,
    fetch_body_measurements,
    fetch_exercise_templates,
    fetch_recent_workouts_full,
    fetch_workout_events,
    templates_cache_is_stale,
    workout_to_exercise_rows,
    workout_to_row,
    LAST_SYNC_KEY,
    TEMPLATE_CACHE_KEY,
)
from shared.hae_daily import daily_activity_spec_for_raw_name, normalize_hae_metric_name
from shared.lift_compute import recompute_prs_for_canonicals, recompute_weekly_volume
from shared.oauth_service import OAuthCredentialCheckError, OAuthRefreshError, OAuthService
from shared.scoring import compute_trimp, compute_strain, classify_hr_zone, estimate_strain_simple, HR_ZONES, MAX_HR
from shared.sleep_quality import evaluate_quality as _eval_sleep_quality
from shared.timezone import (
    HOME_TIMEZONE,
    local_today_str,
    parse_timestamp,
    source_date_str,
    temporal_metadata,
)

secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")
oauth_service = OAuthService(
    secrets_client,
    lambda: get_table("USER_CONFIG_TABLE"),
)

COMPUTE_FN = os.environ.get("COMPUTE_FUNCTION_NAME", "")

# Strava sport_type values that represent strength training. Hevy is the
# source of truth for these, so the Strava webhook path drops them to avoid
# double-ingesting a session that's already logged in Hevy (de-dupe guard —
# Hevy preferred for strength, Strava for cardio).
STRAVA_STRENGTH_TYPES = {"weighttraining", "workout", "crossfit"}

HEVY_REPLAY_OVERLAP_HOURS = 48

# HAE metric-name → (metric_source, unit, aggregation kind)
# Aggregation kinds:
#   "avg"     — daily mean (HRV, RHR, resp, SpO2, temperature)
#   "sum_int" — daily total as integer (steps, kcal, minutes, counts)
#   "sum"     — daily total as float (distances, fractional quantities)
#   "last"    — keep the latest value of the day (weight, BMI — not cumulative)
#   "triple"  — expand into min/avg/max rows (heart_rate)
HAE_NAME_MAP = {
    # ── Scoring-critical vitals ──
    "heart rate variability": ("hrv#hae", "ms", "avg"),
    "heartratevariability":   ("hrv#hae", "ms", "avg"),
    "hrv":                    ("hrv#hae", "ms", "avg"),
    "resting heart rate":     ("rhr#hae", "bpm", "avg"),
    "restingheartrate":       ("rhr#hae", "bpm", "avg"),
    "respiratory rate":       ("resp#hae", "br/min", "avg"),
    "respiratoryrate":        ("resp#hae", "br/min", "avg"),
    "blood oxygen saturation":      ("spo2#hae", "%", "avg"),
    "bloodoxygensaturation":        ("spo2#hae", "%", "avg"),
    "oxygen saturation":            ("spo2#hae", "%", "avg"),
    "oxygensaturation":             ("spo2#hae", "%", "avg"),
    "apple sleeping wrist temperature": ("wrist_temp#hae", "degC", "avg"),
    "applesleepingwristtemperature":    ("wrist_temp#hae", "degC", "avg"),
    "wrist temperature":                ("wrist_temp#hae", "degC", "avg"),
    "wristtemperature":                 ("wrist_temp#hae", "degC", "avg"),
    # Do not conflate direct body temperature with the dedicated sleeping
    # wrist-temperature observation used by current recovery logic.
    "body temperature":                 ("body_temp#hae", "degC", "avg"),
    "bodytemperature":                  ("body_temp#hae", "degC", "avg"),

    # ── Daily heart-rate (triple expansion) ──
    "heart rate":             ("hr#hae", "bpm", "triple"),
    "heartrate":              ("hr#hae", "bpm", "triple"),

    # ── Activity ──
    "step count":             ("steps#hae", "count", "sum_int"),
    "steps":                  ("steps#hae", "count", "sum_int"),
    "stepcount":              ("steps#hae", "count", "sum_int"),
    "active energy":          ("active_cal#hae", "kcal", "sum_int"),
    "active energy burned":   ("active_cal#hae", "kcal", "sum_int"),
    "activeenergyburned":     ("active_cal#hae", "kcal", "sum_int"),
    "activeenergy":           ("active_cal#hae", "kcal", "sum_int"),
    "basal energy burned":    ("basal_cal#hae", "kcal", "sum_int"),
    "basalenergyburned":      ("basal_cal#hae", "kcal", "sum_int"),
    "basal energy":           ("basal_cal#hae", "kcal", "sum_int"),
    "apple exercise time":    ("exercise_min#hae", "min", "sum_int"),
    "appleexercisetime":      ("exercise_min#hae", "min", "sum_int"),
    "exercise time":          ("exercise_min#hae", "min", "sum_int"),
    "exercise minutes":       ("exercise_min#hae", "min", "sum_int"),
    # Apple Move Time is a duration, not active energy. It is supported but
    # currently sparse, so preserve it as its own raw aggregate.
    "apple move time":        ("move_min#hae", "min", "sum_int"),
    "applemovetime":          ("move_min#hae", "min", "sum_int"),
    "apple stand hour":       ("stand_hours#hae", "count", "sum_int"),
    "applestandhour":         ("stand_hours#hae", "count", "sum_int"),
    "apple stand time":       ("stand_min#hae", "min", "sum_int"),
    "applestandtime":         ("stand_min#hae", "min", "sum_int"),
    "stand hours":            ("stand_hours#hae", "count", "sum_int"),
    "flights climbed":        ("flights#hae", "count", "sum_int"),
    "flightsclimbed":         ("flights#hae", "count", "sum_int"),
    "walking running distance": ("walk_distance#hae", "mi", "sum"),
    "walkingrunningdistance":   ("walk_distance#hae", "mi", "sum"),
    "walking heart rate average": ("walk_hr#hae", "bpm", "avg"),
    "walkingheartrateaverage":    ("walk_hr#hae", "bpm", "avg"),
    # Direct Apple Health mobility / capacity observations. Keep these as
    # source observations; do not turn them into a derived score at ingest.
    "walking asymmetry percentage": ("walking_asymmetry#hae", "%", "avg"),
    "walkingasymmetrypercentage":  ("walking_asymmetry#hae", "%", "avg"),
    "vo2 max":                     ("vo2_max#hae", "ml/kg/min", "avg"),
    "vo2max":                       ("vo2_max#hae", "ml/kg/min", "avg"),
    "heart rate recovery one minute": ("hr_recovery#hae", "bpm/min", "avg"),
    "heartraterecoveryone minute":    ("hr_recovery#hae", "bpm/min", "avg"),
    "heart rate recovery":            ("hr_recovery#hae", "bpm/min", "avg"),
    # Cardio recovery is a source observation, distinct from the existing
    # one-minute heart-rate-recovery mapping above. Its HAE-declared unit is
    # preserved because it may vary by HealthKit export/version.
    "cardio recovery":                ("cardio_recovery#hae", None, "last"),
    "cardiorecovery":                 ("cardio_recovery#hae", None, "last"),
    # Mobility evidence is an observation series; none of these are
    # cumulative totals even though their values are numeric.
    "physical effort":                ("physical_effort#hae", "kcal/hr·kg", "avg"),
    "physicaleffort":                 ("physical_effort#hae", "kcal/hr·kg", "avg"),
    "walking speed":                  ("walking_speed#hae", "mi/hr", "avg"),
    "walkingspeed":                   ("walking_speed#hae", "mi/hr", "avg"),
    "walking step length":            ("walking_step_length#hae", "in", "avg"),
    "walkingsteplength":              ("walking_step_length#hae", "in", "avg"),
    "walking double support percentage": ("walking_double_support#hae", "%", "avg"),
    "walkingdoublesupportpercentage":   ("walking_double_support#hae", "%", "avg"),
    "stair speed up":                 ("stair_speed_up#hae", "ft/s", "avg"),
    "stairspeedup":                   ("stair_speed_up#hae", "ft/s", "avg"),
    "stair speed down":               ("stair_speed_down#hae", "ft/s", "avg"),
    "stairspeeddown":                 ("stair_speed_down#hae", "ft/s", "avg"),
    "six minute walking test distance": ("six_min_walk_distance#hae", None, "last"),
    "sixminutewalkingtestdistance":     ("six_min_walk_distance#hae", None, "last"),

    # ── Body composition (Apple Health, may overlap with Withings) ──
    "weight body mass":       ("weight_apple#hae", "lbs", "last"),
    "weightbodymass":         ("weight_apple#hae", "lbs", "last"),
    "weight & body mass":     ("weight_apple#hae", "lbs", "last"),
    "weight":                 ("weight_apple#hae", "lbs", "last"),
    "body mass index":        ("bmi#hae", "kg/m2", "last"),
    "bodymassindex":          ("bmi#hae", "kg/m2", "last"),
    "bmi":                    ("bmi#hae", "kg/m2", "last"),

    # ── Wellness enrichment ──
    "mindful minutes":        ("mindful_min#hae", "min", "sum_int"),
    "mindfulminutes":         ("mindful_min#hae", "min", "sum_int"),
}


def lambda_handler(event, context):
    action = event.get("action")

    if action == "oauth_credential_check":
        return _handle_oauth_credential_check()

    # Scheduled invoke (EventBridge daily cron) or direct async invoke with an
    # explicit action — used to poll Hevy for recent gym workouts. Workouts
    # come from two sources now: Hevy (strength) via this poll, Strava (cardio)
    # via the webhook path below.
    if (
        event.get("source") == "aws.events"
        or action in ("hevy_poll", "hevy_backfill")
    ):
        return _handle_hevy_sync(event)

    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if "/ingest/health" in path:
        return _handle_health(event)
    if "/ingest/withings" in path:
        return _handle_withings(event)
    if "/ingest/strava" in path:
        # Strava webhook. GET is the subscription-verify handshake; POST is an
        # activity event. Strava covers cardio/outdoor activities — strength
        # sessions come from Hevy, so the POST handler filters those out (see
        # _handle_strava) to keep Hevy the single source of truth for lifting.
        if method == "GET":
            return _handle_strava_verify(event)
        return _handle_strava(event)

    return _resp(404, {"error": "not found"})


def _handle_health(event):
    """Process HealthAutoExport JSON payload."""
    headers = _normalized_request_headers(event)
    api_key = headers.get("x-api-key", "")
    if not _verify_api_key(api_key):
        return _resp(401, {"error": "unauthorized"})

    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid JSON body"})

    # HAE v2 shape: {"data": {"metrics": [{"name": "...", "data": [...]}]}}
    # HAE v1 shape: {"data": [{"name": "...", "data": [...]}]}
    data_field = body.get("data")
    data_list = None
    if isinstance(data_field, list):
        data_list = data_field
    elif isinstance(data_field, dict):
        inner = data_field.get("metrics")
        if isinstance(inner, list):
            data_list = inner
    request_context = _hae_request_context(headers)
    if (
        isinstance(data_list, list)
        and request_context["semantics"] == "completed_daily_summary"
    ):
        return _handle_hae_daily_summary(data_list, request_context)
    if data_list and isinstance(data_list[0], dict) and "name" in data_list[0]:
        if request_context["semantics"] == "unsupported_or_ambiguous":
            _log_hae_stream_classification(request_context, len(data_list))
            return _resp(
                422,
                {
                    "error": "unsupported or ambiguous HAE aggregation",
                    "hae_semantics": request_context["semantics"],
                },
            )
        return _handle_hae_metrics_array(data_list, request_context=request_context)

    # Fallback: legacy dict shape (top-level keys per metric)
    table = get_table("HEALTH_METRICS_TABLE")
    metrics = body.get("data", body)
    date_str = _extract_date(metrics)

    if not date_str:
        return _resp(400, {"error": "no date found in payload"})

    # The legacy dict shape exposes only a calendar date at this point. Keep
    # that backward-compatible date, but mark it as an explicit source-date
    # fallback rather than pretending an absolute instant or timezone exists.
    legacy_temporal = _hae_temporal_metadata(date_str)

    items_written = 0

    if "heart_rate_variability" in metrics or "heartRateVariability" in metrics:
        hrv_data = metrics.get("heart_rate_variability") or metrics.get("heartRateVariability")
        hrv_val = _extract_value(hrv_data)
        if hrv_val is not None:
            # Merge-guard fix (2026-07-27): same overwrite bug as the main
            # HAE array path — this legacy dict-shape fallback also needs
            # the samples-ledger merge, not a bare put_item.
            _merge_samples_and_aggregate(
                table,
                date_str,
                "hrv#hae",
                "ms",
                "avg",
                [(_now_iso(), hrv_val)],
                temporal=legacy_temporal,
            )
            items_written += 1

    if "resting_heart_rate" in metrics or "restingHeartRate" in metrics:
        rhr_data = metrics.get("resting_heart_rate") or metrics.get("restingHeartRate")
        rhr_val = _extract_value(rhr_data)
        if rhr_val is not None:
            _merge_samples_and_aggregate(
                table,
                date_str,
                "rhr#hae",
                "bpm",
                "avg",
                [(_now_iso(), rhr_val)],
                temporal=legacy_temporal,
            )
            items_written += 1

    sleep = metrics.get("sleepAnalysis") or metrics.get("sleep_analysis") or metrics.get("sleep")
    if sleep:
        sleep_item = _normalize_sleep(sleep, date_str)
        if sleep_item:
            sleep_item.update(legacy_temporal)
            put_item(table, sleep_item)
            items_written += 1

    if "steps" in metrics or "stepCount" in metrics:
        steps_data = metrics.get("steps") or metrics.get("stepCount")
        steps_val = _extract_value(steps_data)
        if steps_val is not None:
            _merge_samples_and_aggregate(
                table,
                date_str,
                "steps#hae",
                "count",
                "sum_int",
                [(_now_iso(), int(steps_val))],
                temporal=legacy_temporal,
            )
            items_written += 1

    if "active_energy" in metrics or "activeEnergyBurned" in metrics:
        cal_data = metrics.get("active_energy") or metrics.get("activeEnergyBurned")
        cal_val = _extract_value(cal_data)
        if cal_val is not None:
            _merge_samples_and_aggregate(
                table,
                date_str,
                "active_cal#hae",
                "kcal",
                "sum_int",
                [(_now_iso(), round(cal_val))],
                temporal=legacy_temporal,
            )
            items_written += 1

    _trigger_compute(date_str)

    return _resp(200, {"date": date_str, "items_written": items_written})


_HAE_METADATA_HEADERS = {
    "automation-name": "hae_automation_name",
    "automation-id": "hae_automation_id",
    "automation-aggregation": "hae_automation_aggregation",
    "automation-period": "hae_automation_period",
    "session-id": "hae_session_id",
}

_HAE_DAILY_AGGREGATION_TOKENS = {
    "day",
    "days",
    "daily",
    "dailysummary",
}
_HAE_DAILY_PERIOD_TOKENS = {
    "yesterday",
    "previousday",
}
_HAE_RAW_AGGREGATION_TOKENS = {
    "default",
    "none",
    "off",
    "raw",
    "unaggregated",
    "disaggregated",
    "nogrouping",
}
_HAE_DAILY_SUMMARY_GUARD_PREFIX = "hae_daily_summary_guard"
_HAE_DAILY_SUMMARY_SUPERSEDED_SESSION_LIMIT = 16
_HAE_DAILY_SUMMARY_GUARD_MAX_ATTEMPTS = 3


def _normalized_request_headers(event):
    """Return request headers case-insensitively without retaining secrets."""
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return {}
    return {
        str(key).strip().lower(): value
        for key, value in headers.items()
        if isinstance(key, str)
    }


def _safe_hae_metadata_value(value, limit=256):
    """Bound a source label/header without ever including a request body."""
    if not isinstance(value, str):
        return None
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return value[:limit] or None


def _safe_hevy_fetch_reason(value, limit=192):
    """Bound a client-generated fetch diagnostic without logging provider data."""
    if not isinstance(value, str):
        return "unspecified"
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return value[:limit] or "unspecified"


def _hae_header_token(value):
    safe = _safe_hae_metadata_value(value, limit=128)
    return re.sub(r"[^a-z0-9]+", "", safe.lower()) if safe else ""


def _hae_metadata_fingerprint(value):
    """Return a short deterministic identifier suitable for bounded logs."""
    safe = _safe_hae_metadata_value(value, limit=256)
    if not safe:
        return "unknown"
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]


def _hae_daily_summary_session_identity(request_context):
    """Return the documented session identity required for guarded summaries."""
    metadata = request_context.get("metadata") or {}
    session_id = _safe_hae_metadata_value(metadata.get("hae_session_id"), 256)
    automation_id = _safe_hae_metadata_value(metadata.get("hae_automation_id"), 256)
    if not session_id:
        return None, "missing_session_id"
    if not automation_id:
        return None, "missing_automation_id"
    return {
        "session_id": session_id,
        "automation_id": automation_id,
    }, None


def _hae_daily_summary_guard_key(date_str, automation_id):
    """Use a private, deterministic automation fingerprint in the row key."""
    automation_hash = hashlib.sha256(
        automation_id.encode("utf-8"),
    ).hexdigest()
    return {
        "date": date_str,
        "metric_source": (
            f"{_HAE_DAILY_SUMMARY_GUARD_PREFIX}"
            f"#{automation_hash}"
        ),
    }


def _is_conditional_check_failure(exc):
    return (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    )


def _conditional_put_item(table, item, condition_expression):
    """Return false only for an expected DynamoDB conditional conflict."""
    try:
        put_item_conditionally(
            table,
            item,
            condition_expression=condition_expression,
        )
    except ClientError as exc:
        if _is_conditional_check_failure(exc):
            return False
        raise
    return True


def _hae_daily_summary_guard_version(item):
    try:
        version = int((item or {}).get("hae_session_guard_version"))
    except (TypeError, ValueError):
        return None
    return version if version > 0 else None


def _hae_daily_summary_superseded_sessions(item):
    raw_history = (item or {}).get("hae_superseded_session_ids")
    if not isinstance(raw_history, list):
        return None
    history = []
    for session_id in raw_history:
        safe = _safe_hae_metadata_value(session_id, 256)
        if safe and safe not in history:
            history.append(safe)
    return history[:_HAE_DAILY_SUMMARY_SUPERSEDED_SESSION_LIMIT]


def _new_hae_daily_summary_guard_item(
    *,
    date_str,
    request_context,
    session_identity,
    current_session_id,
    superseded_session_ids,
    version,
):
    """Build a same-table control row; it is not a health metric observation."""
    item = {
        "date": date_str,
        "metric_source": _hae_daily_summary_guard_key(
            date_str,
            session_identity["automation_id"],
        )["metric_source"],
        "hae_semantics": "completed_daily_summary_session_guard",
        "hae_current_session_id": current_session_id,
        "hae_superseded_session_ids": superseded_session_ids,
        "hae_session_guard_version": version,
        "ingested_at": _now_iso(),
    }
    item.update(request_context.get("metadata") or {})
    return item


def _acquire_hae_daily_summary_session_guard(
    table,
    date_str,
    request_context,
    session_identity,
):
    """Classify one automation/date session with optimistic concurrency.

    A guard update happens before any canonical summary metric row is written.
    Metric rows are additionally fenced by the accepted guard version so an
    in-flight older session cannot overwrite a later accepted correction.
    """
    session_id = session_identity["session_id"]
    guard_key = _hae_daily_summary_guard_key(
        date_str,
        session_identity["automation_id"],
    )

    for _attempt in range(_HAE_DAILY_SUMMARY_GUARD_MAX_ATTEMPTS):
        existing = get_item(table, guard_key)
        if not existing:
            item = _new_hae_daily_summary_guard_item(
                date_str=date_str,
                request_context=request_context,
                session_identity=session_identity,
                current_session_id=session_id,
                superseded_session_ids=[],
                version=1,
            )
            if _conditional_put_item(
                table,
                item,
                Attr("metric_source").not_exists(),
            ):
                return {"state": "new", "version": 1}
            continue

        current_session_id = _safe_hae_metadata_value(
            existing.get("hae_current_session_id"),
            256,
        )
        superseded_session_ids = _hae_daily_summary_superseded_sessions(existing)
        version = _hae_daily_summary_guard_version(existing)
        if not current_session_id or superseded_session_ids is None or version is None:
            return {"state": "conflict", "reason": "invalid_guard_state"}

        if session_id == current_session_id:
            return {"state": "current", "version": version}
        if session_id in superseded_session_ids:
            return {"state": "stale", "version": version}

        new_history = [current_session_id]
        new_history.extend(
            prior_session_id
            for prior_session_id in superseded_session_ids
            if prior_session_id not in {session_id, current_session_id}
        )
        item = _new_hae_daily_summary_guard_item(
            date_str=date_str,
            request_context=request_context,
            session_identity=session_identity,
            current_session_id=session_id,
            superseded_session_ids=(
                new_history[:_HAE_DAILY_SUMMARY_SUPERSEDED_SESSION_LIMIT]
            ),
            version=version + 1,
        )
        if _conditional_put_item(
            table,
            item,
            Attr("hae_session_guard_version").eq(version),
        ):
            return {"state": "new", "version": version + 1}

    return {"state": "conflict", "reason": "conditional_write_conflict"}


def _put_hae_daily_summary_metric(table, item, guard_version):
    """Write only if no later accepted daily-summary guard has fenced it out."""
    item["hae_session_guard_version"] = guard_version
    return _conditional_put_item(
        table,
        item,
        (
            Attr("hae_session_guard_version").not_exists()
            | Attr("hae_session_guard_version").lte(guard_version)
        ),
    )


def _log_hae_daily_summary_guard_event(
    level,
    *,
    request_context,
    analysis_date,
    reason,
):
    """Log sanitized, bounded session-guard diagnostics without health data."""
    metadata = request_context.get("metadata") or {}
    session_fingerprint = _hae_metadata_fingerprint(metadata.get("hae_session_id"))
    automation_fingerprint = _hae_metadata_fingerprint(
        metadata.get("hae_automation_id")
    )
    message = (
        "HAE_DAILY_SUMMARY_SESSION_GUARD "
        "automation_id_fp=%s session_fp=%s analysis_date=%s reason=%s"
    )
    getattr(logger, level)(
        message,
        automation_fingerprint,
        session_fingerprint,
        _safe_hae_metadata_value(analysis_date, 128) or "?",
        _safe_hae_metadata_value(reason, 64) or "?",
    )


def _log_hae_daily_summary_validation_error(
    *,
    raw_metric_name,
    analysis_date,
    reason,
    point_count,
):
    """Log a bounded structural error without observation values."""
    logger.warning(
        "HAE_DAILY_SUMMARY_REJECTED metric_name=%s analysis_date=%s "
        "point_count=%d reason=%s",
        _safe_hae_metadata_value(raw_metric_name, 128) or "?",
        _safe_hae_metadata_value(analysis_date, 128) or "?",
        int(point_count),
        _safe_hae_metadata_value(reason, 64) or "?",
    )


def _hae_daily_summary_unit_matches(expected_unit, raw_unit):
    """Accept the documented unit spelling, while allowing an omitted label."""
    if raw_unit is None:
        return True
    if not isinstance(raw_unit, str):
        return False
    normalized = re.sub(r"[\s_-]+", "", raw_unit.strip().lower())
    expected = re.sub(r"[\s_-]+", "", str(expected_unit).strip().lower())
    return bool(normalized) and normalized == expected


def _validate_hae_daily_summary_payload(data_list, request_context):
    """Validate and normalize the entire daily-summary payload before writes."""
    items_by_date = {}
    seen_metric_dates = set()

    for entry in data_list:
        if not isinstance(entry, dict):
            _log_hae_daily_summary_validation_error(
                raw_metric_name=None,
                analysis_date=None,
                reason="invalid_metric_shape",
                point_count=0,
            )
            return None, "invalid_metric_shape"

        raw_metric_name = entry.get("name")
        if not isinstance(raw_metric_name, str) or not raw_metric_name.strip():
            _log_hae_daily_summary_validation_error(
                raw_metric_name=raw_metric_name,
                analysis_date=None,
                reason="invalid_metric_shape",
                point_count=0,
            )
            return None, "invalid_metric_shape"
        raw_metric_name = raw_metric_name.strip()

        points = entry.get("data") if "data" in entry else None
        point_count = len(points) if isinstance(points, list) else 0
        spec = daily_activity_spec_for_raw_name(raw_metric_name)
        if not spec:
            _log_hae_unsupported_daily_metric(raw_metric_name, point_count)
            return None, "unsupported_daily_metric"
        if not _hae_daily_summary_unit_matches(spec["unit"], entry.get("units")):
            _log_hae_daily_summary_validation_error(
                raw_metric_name=raw_metric_name,
                analysis_date=None,
                reason="contradictory_units",
                point_count=point_count,
            )
            return None, "contradictory_units"
        if not isinstance(points, list):
            _log_hae_daily_summary_validation_error(
                raw_metric_name=raw_metric_name,
                analysis_date=None,
                reason="invalid_metric_shape",
                point_count=point_count,
            )
            return None, "invalid_metric_shape"

        for point in points:
            if not isinstance(point, dict):
                _log_hae_daily_summary_validation_error(
                    raw_metric_name=raw_metric_name,
                    analysis_date=None,
                    reason="invalid_row_shape",
                    point_count=point_count,
                )
                return None, "invalid_row_shape"

            source_ts = (
                point.get("date")
                or point.get("startDate")
                or point.get("endDate")
                or ""
            )
            temporal = _hae_temporal_metadata(source_ts)
            date_str = temporal.get("analysis_date")
            if not date_str:
                _log_hae_daily_summary_validation_error(
                    raw_metric_name=raw_metric_name,
                    analysis_date=None,
                    reason="unparseable_date",
                    point_count=point_count,
                )
                return None, "unparseable_date"

            raw_value = (
                point.get("qty")
                if point.get("qty") is not None
                else point.get("value")
            )
            if isinstance(raw_value, bool):
                value = None
            else:
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = None
            if value is None or not math.isfinite(value):
                _log_hae_daily_summary_validation_error(
                    raw_metric_name=raw_metric_name,
                    analysis_date=date_str,
                    reason="invalid_row_shape",
                    point_count=point_count,
                )
                return None, "invalid_row_shape"

            metric_date = (date_str, spec["summary_source"])
            if metric_date in seen_metric_dates:
                _log_hae_daily_summary_validation_error(
                    raw_metric_name=raw_metric_name,
                    analysis_date=date_str,
                    reason="duplicate_metric_date",
                    point_count=point_count,
                )
                return None, "duplicate_metric_date"
            seen_metric_dates.add(metric_date)

            # Counts are integral by contract. Preserve source precision for
            # energy, duration, and distance rather than manufacturing a
            # rounded total before any consumer sees it.
            if spec["unit"] == "count":
                value = int(round(value))
            else:
                value = round(value, 3)

            item = {
                "date": date_str,
                "metric_source": spec["summary_source"],
                "value": value,
                "unit": spec["unit"],
                "source_ts": _safe_hae_metadata_value(source_ts, 128),
                "hae_semantics": "completed_daily_summary",
                "hae_raw_metric_name": (
                    _safe_hae_metadata_value(raw_metric_name, 128) or "?"
                ),
                "ingested_at": _now_iso(),
            }
            raw_units = _safe_hae_metadata_value(entry.get("units"), 64)
            if raw_units:
                item["hae_raw_units"] = raw_units
            source = _safe_hae_metadata_value(point.get("source"), 256)
            if source:
                item["hae_source"] = source
            item.update(request_context.get("metadata") or {})
            item.update(temporal)
            items_by_date.setdefault(date_str, []).append(item)

    if not items_by_date:
        _log_hae_daily_summary_validation_error(
            raw_metric_name=None,
            analysis_date=None,
            reason="no_daily_summary_observations",
            point_count=0,
        )
        return None, "no_daily_summary_observations"

    for date_items in items_by_date.values():
        date_items.sort(key=lambda item: item["metric_source"])
    return items_by_date, None


def _hae_daily_summary_failure_response(
    *,
    code,
    error,
    reason,
    all_dates,
    completed_dates,
    stale_dates,
    items_written,
    failed_date,
):
    """Return a bounded, value-free per-request failure summary."""
    logger.error(
        "HAE_DAILY_SUMMARY_RESULT status=%s date_count=%d dates_completed=%d "
        "dates_stale_ignored=%d items_written=%d affected_date_start=%s "
        "affected_date_end=%s failed_date=%s reason=%s",
        "partial_failure" if completed_dates or stale_dates else "failed",
        len(all_dates),
        len(completed_dates),
        len(stale_dates),
        items_written,
        all_dates[0],
        all_dates[-1],
        failed_date,
        reason,
    )
    body = {
        "error": error,
        "status": "partial_failure" if completed_dates or stale_dates else "failed",
        "date_count": len(all_dates),
        "dates_completed": len(completed_dates),
        "dates_stale_ignored": len(stale_dates),
        "items_written": items_written,
        "affected_date_start": all_dates[0],
        "affected_date_end": all_dates[-1],
        "failed_date": failed_date,
        "reason": reason,
        "hae_semantics": "completed_daily_summary",
    }
    return _resp(code, body)


def _hae_request_context(headers):
    """Classify HAE export semantics from HAE's automation metadata.

    HAE supplies automation headers automatically. We use an explicit daily
    aggregate only when both aggregation and period identify a completed
    Yesterday run. A request with neither field keeps the deployed legacy
    behavior but is labelled ``legacy_unclassified``. Partial/unknown header
    combinations are rejected rather than silently becoming raw evidence.
    """
    metadata = {}
    for header_name, metadata_name in _HAE_METADATA_HEADERS.items():
        value = _safe_hae_metadata_value(headers.get(header_name))
        if value is not None:
            metadata[metadata_name] = value

    aggregation = _hae_header_token(headers.get("automation-aggregation"))
    period = _hae_header_token(headers.get("automation-period"))
    if not aggregation and not period:
        semantics = "legacy_unclassified"
    elif (
        aggregation in _HAE_DAILY_AGGREGATION_TOKENS
        and period in _HAE_DAILY_PERIOD_TOKENS
    ):
        semantics = "completed_daily_summary"
    elif aggregation in _HAE_RAW_AGGREGATION_TOKENS:
        semantics = "raw_observation"
    else:
        semantics = "unsupported_or_ambiguous"

    return {
        "semantics": semantics,
        "metadata": metadata,
    }


def _log_hae_stream_classification(request_context, metric_count):
    """Emit only bounded routing metadata; never health values or API keys."""
    metadata = request_context.get("metadata") or {}
    logger.info(
        "HAE_STREAM_CLASSIFIED semantics=%s metric_count=%d automation_name=%s "
        "automation_id=%s aggregation=%s period=%s",
        request_context.get("semantics") or "?",
        int(metric_count),
        metadata.get("hae_automation_name") or "?",
        metadata.get("hae_automation_id") or "?",
        metadata.get("hae_automation_aggregation") or "?",
        metadata.get("hae_automation_period") or "?",
    )


def _hae_raw_evidence_metadata(request_context, raw_metric_name, raw_units, sources):
    """Build additive, source-specific evidence fields for a raw HAE write."""
    metadata = {
        "hae_semantics": request_context.get("semantics") or "legacy_unclassified",
        "hae_raw_metric_names": [_safe_hae_metadata_value(raw_metric_name, 128) or "?"],
    }
    unit = _safe_hae_metadata_value(raw_units, 64)
    if unit:
        metadata["hae_raw_units"] = [unit]
    safe_sources = sorted(
        {
            safe
            for safe in (
                _safe_hae_metadata_value(source, 256) for source in (sources or [])
            )
            if safe
        }
    )
    if safe_sources:
        # A combined HAE source string is deliberately preserved as one string.
        metadata["hae_sources"] = safe_sources[:16]
    metadata.update(request_context.get("metadata") or {})
    return metadata


def _merge_hae_evidence_metadata(*items):
    """Merge bounded source-specific evidence metadata across raw replays."""
    metadata = [item for item in items if isinstance(item, dict) and item]
    if not metadata:
        return {}
    merged = {}
    for field in (
        "hae_raw_metric_names",
        "hae_raw_units",
        "hae_sources",
    ):
        values = sorted(
            {
                safe
                for item in metadata
                for safe in (item.get(field) or [])
                if isinstance(safe, str) and safe
            }
        )
        if values:
            merged[field] = values[:16]

    for field in (
        "hae_semantics",
        "hae_automation_name",
        "hae_automation_id",
        "hae_automation_aggregation",
        "hae_automation_period",
        "hae_session_id",
    ):
        values = {
            item.get(field)
            for item in metadata
            if isinstance(item.get(field), str) and item.get(field)
        }
        if len(values) == 1:
            merged[field] = values.pop()
        elif field == "hae_semantics" and values:
            merged[field] = "mixed_hae_semantics"
    return merged


def _handle_hae_daily_summary(data_list, request_context):
    """Write source-provided completed-day HAE totals without using raw ledgers.

    The storage identity is additive (``#hae_daily_summary``), which prevents
    historical raw HAE sample-ledger aggregates from being added to the new
    daily totals. A same-table automation/date session guard rejects a delayed
    replay that was already superseded by a later accepted correction. The
    guard's version fences metric writes so older in-flight requests cannot
    overwrite a newer accepted correction. Multi-date requests are validated
    in full, then processed in ascending source-local analysis-date order so a
    retry can safely resume after an observable infrastructure failure.
    """
    _log_hae_stream_classification(request_context, len(data_list))

    session_identity, identity_error = _hae_daily_summary_session_identity(
        request_context,
    )
    if identity_error:
        _log_hae_daily_summary_guard_event(
            "warning",
            request_context=request_context,
            analysis_date=None,
            reason=identity_error,
        )
        return _resp(
            422,
            {
                "error": "missing required HAE daily-summary session identity",
                "reason": identity_error,
                "hae_semantics": "completed_daily_summary",
            },
        )

    items_by_date, validation_error = _validate_hae_daily_summary_payload(
        data_list,
        request_context,
    )
    if validation_error:
        return _resp(
            422,
            {
                "error": "invalid HAE daily-summary payload",
                "reason": validation_error,
                "hae_semantics": "completed_daily_summary",
            },
        )

    _log_hae_summary(data_list, request_context=request_context)
    table = get_table("HEALTH_METRICS_TABLE")
    all_dates = sorted(items_by_date)
    items_written = 0
    completed_dates = []
    stale_dates = []

    for date_str in all_dates:
        try:
            decision = _acquire_hae_daily_summary_session_guard(
                table,
                date_str,
                request_context,
                session_identity,
            )
        except Exception:  # noqa: BLE001 - return a bounded retryable failure
            _log_hae_daily_summary_guard_event(
                "error",
                request_context=request_context,
                analysis_date=date_str,
                reason="session_guard_write_failed",
            )
            return _hae_daily_summary_failure_response(
                code=503,
                error="HAE daily-summary session guard unavailable",
                reason="session_guard_write_failed",
                all_dates=all_dates,
                completed_dates=completed_dates,
                stale_dates=stale_dates,
                items_written=items_written,
                failed_date=date_str,
            )

        if decision["state"] == "conflict":
            reason = decision.get("reason") or "conditional_write_conflict"
            _log_hae_daily_summary_guard_event(
                "error",
                request_context=request_context,
                analysis_date=date_str,
                reason=reason,
            )
            return _hae_daily_summary_failure_response(
                code=409,
                error="HAE daily-summary session guard conflict",
                reason=reason,
                all_dates=all_dates,
                completed_dates=completed_dates,
                stale_dates=stale_dates,
                items_written=items_written,
                failed_date=date_str,
            )

        if decision["state"] == "stale":
            stale_dates.append(date_str)
            _log_hae_daily_summary_guard_event(
                "info",
                request_context=request_context,
                analysis_date=date_str,
                reason="superseded_session_replay_ignored",
            )
            continue

        for item in items_by_date[date_str]:
            try:
                written = _put_hae_daily_summary_metric(
                    table,
                    item,
                    decision["version"],
                )
            except Exception:  # noqa: BLE001 - return a bounded retryable failure
                _log_hae_daily_summary_guard_event(
                    "error",
                    request_context=request_context,
                    analysis_date=date_str,
                    reason="metric_write_failed",
                )
                return _hae_daily_summary_failure_response(
                    code=503,
                    error="HAE daily-summary metric write unavailable",
                    reason="metric_write_failed",
                    all_dates=all_dates,
                    completed_dates=completed_dates,
                    stale_dates=stale_dates,
                    items_written=items_written,
                    failed_date=date_str,
                )
            if not written:
                # A concurrently accepted newer session has fenced this writer
                # out. Do not compute on a potentially partial older result; a
                # retry re-evaluates the guard and becomes a no-op if stale.
                _log_hae_daily_summary_guard_event(
                    "warning",
                    request_context=request_context,
                    analysis_date=date_str,
                    reason="metric_write_fenced_by_newer_guard",
                )
                return _hae_daily_summary_failure_response(
                    code=409,
                    error="HAE daily-summary metric write conflict",
                    reason="metric_write_fenced_by_newer_guard",
                    all_dates=all_dates,
                    completed_dates=completed_dates,
                    stale_dates=stale_dates,
                    items_written=items_written,
                    failed_date=date_str,
                )
            items_written += 1

        try:
            _trigger_compute(date_str)
        except Exception:  # noqa: BLE001 - tests can expose a failed trigger
            _log_hae_daily_summary_guard_event(
                "error",
                request_context=request_context,
                analysis_date=date_str,
                reason="recompute_trigger_failed",
            )
            return _hae_daily_summary_failure_response(
                code=503,
                error="HAE daily-summary recompute trigger unavailable",
                reason="recompute_trigger_failed",
                all_dates=all_dates,
                completed_dates=completed_dates,
                stale_dates=stale_dates,
                items_written=items_written,
                failed_date=date_str,
            )
        completed_dates.append(date_str)

    if completed_dates and stale_dates:
        result_status = "completed_with_stale_ignored"
    elif completed_dates:
        result_status = "completed"
    else:
        result_status = "stale_daily_summary_replay_ignored"
    logger.info(
        "HAE_DAILY_SUMMARY_RESULT status=%s date_count=%d dates_completed=%d "
        "dates_stale_ignored=%d items_written=%d affected_date_start=%s "
        "affected_date_end=%s",
        result_status,
        len(all_dates),
        len(completed_dates),
        len(stale_dates),
        items_written,
        all_dates[0],
        all_dates[-1],
    )

    if len(all_dates) == 1 and stale_dates:
        return _resp(
            200,
            {
                "date": stale_dates[0],
                "items_written": 0,
                "status": "stale_daily_summary_replay_ignored",
                "hae_semantics": "completed_daily_summary",
            },
        )

    if len(all_dates) == 1:
        return _resp(
            200,
            {
                "date": completed_dates[0],
                "items_written": items_written,
                "hae_semantics": "completed_daily_summary",
            },
        )

    return _resp(
        200,
        {
            "status": result_status,
            "date_count": len(all_dates),
            "dates_completed": len(completed_dates),
            "dates_stale_ignored": len(stale_dates),
            "items_written": items_written,
            "affected_date_start": all_dates[0],
            "affected_date_end": all_dates[-1],
            "hae_semantics": "completed_daily_summary",
        },
    )


def _handle_hae_metrics_array(data_list, *, request_context=None):
    """Process HAE's real payload shape: top-level {data: [{name, units, data: [{qty|value, date|startDate, ...}]}]}.

    Groups each metric's points by date and writes one health-metrics row per (date, metric).
    Aggregates: avg for vitals (HRV/RHR/resp), sum for cumulative (steps/cal).
    """
    table = get_table("HEALTH_METRICS_TABLE")
    items_written = 0
    latest_date = None
    request_context = request_context or {
        "semantics": "legacy_unclassified",
        "metadata": {},
    }

    # Diagnostic: log a compact summary so we can tell empty pushes from
    # real ones without dumping full payloads (PII/token cost).
    _log_hae_stream_classification(request_context, len(data_list))
    _log_hae_summary(data_list, request_context=request_context)

    for entry in data_list:
        raw_metric_name = str(entry.get("name") or "").strip()
        raw_name = raw_metric_name.lower()
        # HAE v2 uses snake_case (heart_rate_variability); v1 docs showed title case.
        # Map by both forms — with and without separators.
        name = raw_name
        name_no_sep = normalize_hae_metric_name(raw_name)
        points = entry.get("data") or []

        # Sleep Analysis — two HAE shapes:
        #   Aggregated (one record per night): {date, totalSleep, asleep, core, deep, rem, inBed, ...} in HOURS
        #   Unaggregated: [{startDate, endDate, value: "Deep"|"REM"|"Core"|"Awake"|"InBed"|"Asleep", qty}]
        # IMPORTANT: use exact match, NOT substring. "apple sleeping wrist temperature" contains "sleep"
        # but is not sleep analysis — it's wrist temperature.
        if raw_name in ("sleep_analysis", "sleep analysis", "sleepanalysis"):
            sleep_evidence = _hae_raw_evidence_metadata(
                request_context,
                raw_metric_name,
                entry.get("units"),
                [
                    point.get("source")
                    for point in points
                    if isinstance(point, dict)
                ],
            )
            for p in points:
                if not isinstance(p, dict):
                    continue
                # Aggregated form has totalSleep / inBed / asleep fields
                if any(k in p for k in ("totalSleep", "asleep", "inBed")):
                    raw_date = p.get("date") or p.get("sleepStart") or ""
                    sleep_temporal = _hae_temporal_metadata(raw_date)
                    d = sleep_temporal.get("analysis_date")
                    if not d:
                        continue
                    # For stages "Asleep" etc. the date can be the following morning; keep it.
                    item = _normalize_sleep_aggregated(p, d)
                    if item:
                        item.update(sleep_temporal)
                        item.update(sleep_evidence)
                        put_item(table, item)
                        items_written += 1
                        latest_date = max(latest_date or d, d)
            # Group segments into sessions using HAE's own `sleepStart`
            # field — every segment of the same overnight shares the same
            # sleepStart timestamp, so it's the reliable session key. Then
            # map each session to its wake-up morning (max endDate's date)
            # so overnights that cross midnight land on one date key, not two.
            # Falls back to gap-based clustering when sleepStart is absent
            # (older HAE versions) with a generous 180-min threshold so real
            # wake-ups inside a night don't split the session.
            segs_raw = []
            for p in points:
                if not isinstance(p, dict):
                    continue
                if any(k in p for k in ("totalSleep", "asleep", "inBed")):
                    continue  # already handled above
                start_ts = p.get("startDate") or p.get("sleepStart") or p.get("date")
                end_ts = p.get("endDate") or p.get("sleepEnd")
                if not start_ts or not end_ts:
                    continue
                dur = (
                    p.get("duration_min")
                    or p.get("duration")
                    or (float(p.get("qty", 0)) * 60 if p.get("qty") else None)
                    or _minutes_between(start_ts, end_ts)
                    or 0
                )
                value = p.get("value") or p.get("type") or p.get("stage") or ""
                segs_raw.append({
                    "value": value,
                    "duration_min": float(dur),
                    "startDate": start_ts,
                    "endDate": end_ts,
                    "sleepStart": p.get("sleepStart"),
                })
            # Cluster by sleepStart when present (preferred), falling back to
            # gap-based clustering (180min threshold) for legacy shapes.
            segs_raw.sort(key=lambda s: s.get("startDate") or "")
            sessions_map = {}
            gap_cluster = []
            last_end_min = None
            for seg in segs_raw:
                key = seg.get("sleepStart")
                if key:
                    sessions_map.setdefault(key, []).append(seg)
                    continue
                # Legacy fallback: gap-based clustering.
                start_min = _parse_ts_min(seg["startDate"])
                end_min = _parse_ts_min(seg["endDate"])
                if start_min is None or end_min is None:
                    continue
                if gap_cluster and last_end_min is not None and start_min - last_end_min > 180:
                    sessions_map[f"_gap_{len(sessions_map)}"] = gap_cluster
                    gap_cluster = []
                gap_cluster.append(seg)
                last_end_min = max(last_end_min or end_min, end_min)
            if gap_cluster:
                sessions_map[f"_gap_{len(sessions_map)}"] = gap_cluster
            # Map each session to its wake-up morning.
            by_date = {}
            for session in sessions_map.values():
                end_dates = [s["endDate"] for s in session if s.get("endDate")]
                if not end_dates:
                    continue
                wake_source = max(end_dates)
                wake_temporal = _hae_temporal_metadata(wake_source)
                wake_date = wake_temporal.get("analysis_date")
                if not wake_date:
                    continue
                # If multiple sessions land on the same wake date (rare —
                # e.g. a nap + a night), keep the longer one. The shorter
                # gets dropped rather than merged to avoid garbled totals.
                if wake_date not in by_date or len(session) > len(by_date[wake_date][0]):
                    by_date[wake_date] = (session, wake_temporal)
            for d, (segs, sleep_temporal) in by_date.items():
                item = _normalize_sleep(segs, d)
                if not item:
                    continue
                item.update(sleep_temporal)
                # Merge guard — HAE sometimes sends partial unaggregated sessions
                # (e.g. only the post-midnight slice of an overnight) that would
                # otherwise clobber the full-night aggregated totals already on
                # this date. When the existing row's total_min is materially
                # larger than what this unaggregated batch reports, keep the
                # existing totals and only enrich with segments. "Materially"
                # = more than 60m larger, which excludes rounding noise but
                # still lets true night-long unaggregated exports replace the
                # older aggregated row outright.
                existing = get_item(table, {"date": d, "metric_source": "sleep#hae"}) or {}
                existing_total = float(existing.get("total_min") or 0)
                incoming_total = float(item.get("total_min") or 0)
                if existing_total > incoming_total + 60 and existing_total > 0:
                    merged = dict(existing)
                    if item.get("segments"):
                        merged["segments"] = item["segments"]
                    # Carry over incoming sleep_start/end when the existing
                    # row was built from an aggregated push that didn't have
                    # them. Compute's HR-sidecar intersection needs these.
                    for k in ("sleep_start", "sleep_end"):
                        if item.get(k) and not merged.get(k):
                            merged[k] = item[k]
                    merged["ingested_at"] = _now_iso()
                    item = merged
                item.update(_merge_hae_evidence_metadata(item, sleep_evidence))
                put_item(table, item)
                items_written += 1
                latest_date = max(latest_date or d, d)
            continue

        mapping = HAE_NAME_MAP.get(name) or HAE_NAME_MAP.get(name_no_sep) or HAE_NAME_MAP.get(raw_name.replace("_", " "))
        if not mapping:
            _log_hae_unmapped_metric(
                raw_metric_name,
                len(points),
                request_context=request_context,
            )
            continue
        metric_source, unit, kind = mapping
        unit = unit or _safe_hae_metadata_value(entry.get("units"), 64)
        if not unit:
            _log_hae_invalid_metric(raw_metric_name, len(points), reason="missing_units")
            continue

        # Triple expansion: HAE exports heart_rate entries with Min/Avg/Max per day.
        # Emit three rows: hr_min#hae, hr_avg#hae, hr_max#hae (metric_source "hr#hae" becomes the prefix).
        # Also opportunistically collect per-sample HR points (timestamp + qty)
        # into a sidecar row so compute can intersect with the sleep window.
        if kind == "triple":
            prefix = metric_source.rsplit("#", 1)[0]  # "hr"
            src_suffix = metric_source.split("#", 1)[1]  # "hae"
            by_date_triple = {}
            by_date_temporal = {}
            by_date_evidence = {}
            by_date_samples = {}  # date → [{ts, bpm}] — only populated if HAE sends per-sample HR
            for p in points:
                if not isinstance(p, dict):
                    continue
                source_ts = p.get("date") or p.get("startDate") or p.get("endDate") or ""
                point_temporal = _hae_temporal_metadata(source_ts)
                d = point_temporal.get("analysis_date")
                if not d:
                    continue
                by_date_temporal[d] = _merge_hae_temporal_metadata(
                    by_date_temporal.get(d), point_temporal
                )
                by_date_evidence[d] = _merge_hae_evidence_metadata(
                    by_date_evidence.get(d),
                    _hae_raw_evidence_metadata(
                        request_context,
                        raw_metric_name,
                        entry.get("units"),
                        [p.get("source")],
                    ),
                )
                slot = by_date_triple.setdefault(d, {"min": [], "avg": [], "max": []})
                has_stats = False
                for key_raw, slot_key in (("Min", "min"), ("min", "min"),
                                          ("Avg", "avg"), ("avg", "avg"),
                                          ("Max", "max"), ("max", "max")):
                    v = p.get(key_raw)
                    if v is None:
                        continue
                    try:
                        slot[slot_key].append(float(v))
                        has_stats = True
                    except (ValueError, TypeError):
                        continue
                # Per-sample sidecar — collect whenever the date carries a clock
                # component (per-sample rows look like "2026-05-03 23:45:10",
                # daily rows are "2026-05-03"). HAE's unaggregated HR emits one
                # point per sample as {Min, Avg, Max, date} with Min=Avg=Max =
                # the sample value, so we can't require "no stats keys" like
                # before — that silently dropped every per-sample reading.
                sample_ts = p.get("date") or p.get("startDate") or ""
                is_per_sample = isinstance(sample_ts, str) and len(sample_ts) > 10
                sample_val = None
                if has_stats:
                    # Prefer Avg; fall back to Min/Max which equal Avg in the
                    # per-sample shape anyway.
                    for k in ("Avg", "avg", "Min", "min", "Max", "max"):
                        if p.get(k) is not None:
                            try:
                                sample_val = float(p.get(k))
                                break
                            except (ValueError, TypeError):
                                continue
                else:
                    q = p.get("qty") or p.get("value")
                    if q is not None:
                        try:
                            sample_val = float(q)
                            slot["avg"].append(sample_val)
                        except (ValueError, TypeError):
                            sample_val = None
                if sample_val is not None and is_per_sample:
                    by_date_samples.setdefault(d, []).append({
                        "ts": sample_ts,
                        "bpm": round(sample_val, 1),
                    })
            for d, slots in by_date_triple.items():
                for slot_key, vals in slots.items():
                    if not vals:
                        continue
                    if slot_key == "min":
                        val = round(min(vals), 1)
                    elif slot_key == "max":
                        val = round(max(vals), 1)
                    else:
                        val = round(sum(vals) / len(vals), 1)
                    item = {
                        "date": d,
                        "metric_source": f"{prefix}_{slot_key}#{src_suffix}",
                        "value": val,
                        "unit": unit,
                        "ingested_at": _now_iso(),
                    }
                    item.update(by_date_temporal.get(d) or {})
                    item.update(by_date_evidence.get(d) or {})
                    put_item(table, item)
                    items_written += 1
                    latest_date = max(latest_date or d, d)
            # Per-sample sidecar for heart rate. Only written when HAE actually
            # sends per-sample points (many timestamps/day); otherwise empty.
            # Compute intersects these with the sleep window for avg_hr_sleep.
            for d, samples in by_date_samples.items():
                if len(samples) < 5:
                    # Fewer than 5 timestamped samples in a day isn't worth
                    # storing — probably a single summary point misidentified.
                    continue
                item = {
                    "date": d,
                    "metric_source": f"{prefix}#hae_samples",
                    "samples": samples,
                    "ingested_at": _now_iso(),
                }
                item.update(by_date_temporal.get(d) or {})
                item.update(by_date_evidence.get(d) or {})
                put_item(table, item)
                items_written += 1
                latest_date = max(latest_date or d, d)
            continue

        # Standard numeric aggregation (avg / sum_int / sum / last).
        #
        # MERGE-GUARD FIX (2026-07-27): HAE fires multiple automations per
        # day, and each POST here only ever carried the points present in
        # THAT call. The old code aggregated only within a single payload
        # and did a bare put_item(), so the LAST webhook to land for a given
        # (date, metric) silently discarded every earlier same-day POST —
        # this is the confirmed root cause of the steps-undercount bug
        # (McFox showed 6,501 steps vs. the real ~21,267 on one affected
        # day) and the HRV-discrepancy bug (each payload only averaged an
        # arbitrary subset of the day's HRV samples). Fix: keep every
        # incoming (timestamp, value) point in a per-day samples ledger —
        # the same pattern already proven for the hr#hae_samples sidecar —
        # merge new points into it, then recompute the daily aggregate over
        # the FULL merged set before writing. This is correct regardless of
        # whether a given HAE automation sends a full-day resend or just an
        # incremental delta.
        by_date = {}
        by_date_temporal = {}
        by_date_evidence = {}
        for p in points:
            if not isinstance(p, dict):
                continue
            source_ts = p.get("date") or p.get("startDate") or p.get("endDate") or ""
            point_temporal = _hae_temporal_metadata(source_ts)
            d = point_temporal.get("analysis_date")
            if not d:
                continue
            by_date_temporal[d] = _merge_hae_temporal_metadata(
                by_date_temporal.get(d), point_temporal
            )
            raw = p.get("qty") if p.get("qty") is not None else p.get("value")
            if raw is None:
                continue
            ts = p.get("date") or p.get("endDate") or p.get("startDate") or ""
            try:
                by_date.setdefault(d, []).append((ts, float(raw)))
            except (ValueError, TypeError):
                continue
            by_date_evidence[d] = _merge_hae_evidence_metadata(
                by_date_evidence.get(d),
                _hae_raw_evidence_metadata(
                    request_context,
                    raw_metric_name,
                    entry.get("units"),
                    [p.get("source")],
                ),
            )

        for d, pairs in by_date.items():
            if not pairs:
                continue
            if kind == "last":
                # "last"-kind metrics (weight, BMI) aren't cumulative — a
                # samples ledger doesn't apply. Instead, guard against an
                # out-of-order webhook retry regressing a fresher value by
                # comparing against whatever's already stored.
                ts, val = max(pairs, key=lambda x: x[0])
                _write_last_with_ordering_guard(
                    table,
                    d,
                    metric_source,
                    unit,
                    ts,
                    round(val, 2),
                    temporal=by_date_temporal.get(d),
                    evidence=by_date_evidence.get(d),
                )
            else:
                _merge_samples_and_aggregate(
                    table,
                    d,
                    metric_source,
                    unit,
                    kind,
                    pairs,
                    temporal=by_date_temporal.get(d),
                    evidence=by_date_evidence.get(d),
                )
            items_written += 1
            latest_date = max(latest_date or d, d)

    if latest_date:
        _trigger_compute(latest_date)

    return _resp(
        200,
        {
            "date": latest_date,
            "items_written": items_written,
            "hae_semantics": request_context["semantics"],
        },
    )


def _merge_samples_and_aggregate(
    table,
    date_str,
    metric_source,
    unit,
    kind,
    new_pairs,
    *,
    temporal=None,
    evidence=None,
):
    """Merge-guard for cumulative/averaged HAE metrics (avg / sum_int / sum).

    HAE sends multiple automations per day, each carrying only the samples
    it collected in its own export window. A bare overwrite per POST means
    the LAST webhook wins and discards every earlier same-day POST's data —
    this is the confirmed root cause of the steps-undercount and HRV-
    discrepancy bugs. Fix: keep a timestamp-deduped samples ledger for the
    metric (sidecar row `<metric_source>_samples`), merge new points into
    it, then recompute the daily aggregate over the FULL merged set. This
    is correct whether a given automation sends a full-day resend or an
    incremental delta, since dedup-by-timestamp makes re-sends idempotent.

    Item-size cap (2026-08): a single high-frequency metric's daily ledger
    (~9,226 samples for steps#hae_samples) outgrew DynamoDB's 400KB per-item
    limit, so the unbounded single-row put_item raised ValidationException
    and aborted the WHOLE ingest request — silent data loss. The ledger is
    now SHARDED across `<metric_source>_samples`, `_samples#001`, `#002`, ...
    (shard 0 keeps the bare key for backward compatibility). Reads merge
    every shard and dedup runs over the full cross-shard set, so the
    recomputed aggregate is still over ALL samples, not one shard. A legacy
    single large `_samples` row is read as shard 0 and re-sharded forward on
    this write without dropping points. See shared.samples_ledger.
    """
    samples_key = f"{metric_source}_samples"
    # Read shard 0 (the legacy/base key) plus any overflow shards, merging
    # every stored point into one timestamp-keyed dict. Dedup therefore spans
    # all shards, and a large pre-existing shard-0 row migrates forward here.
    existing_samples, shard0_item = read_merged_samples(
        get_item, table, date_str, samples_key
    )
    stored_temporal = _merge_hae_temporal_metadata(shard0_item, temporal)
    stored_evidence = _merge_hae_evidence_metadata(shard0_item, evidence)
    for ts, val in new_pairs:
        if ts:
            existing_samples[ts] = val
        else:
            # No usable timestamp — still fold the value in under a synthetic
            # key so it isn't silently dropped, but it can't be deduped
            # against a future re-send of the same point. len() is the count
            # across ALL shards, so these keys stay unique cross-shard.
            existing_samples[f"_no_ts_{len(existing_samples)}"] = val

    write_sharded_ledger(
        put_item,
        table,
        date_str,
        samples_key,
        existing_samples,
        extra={**stored_temporal, **stored_evidence},
        ingested_at=_now_iso(),
    )

    vals = list(existing_samples.values())
    if kind == "avg":
        val = round(sum(vals) / len(vals), 1)
    elif kind == "sum_int":
        val = int(round(sum(vals)))
    else:  # "sum"
        val = round(sum(vals), 1)

    aggregate_item = {
        "date": date_str,
        "metric_source": metric_source,
        "value": val,
        "unit": unit,
        "ingested_at": _now_iso(),
    }
    aggregate_item.update(stored_temporal)
    aggregate_item.update(stored_evidence)
    put_item(table, aggregate_item)


def _write_last_with_ordering_guard(
    table,
    date_str,
    metric_source,
    unit,
    incoming_ts,
    incoming_val,
    *,
    temporal=None,
    evidence=None,
):
    """Merge-guard for "last"-kind metrics (weight, BMI).

    These aren't cumulative, so a samples ledger doesn't apply — but a
    Lambda/API-Gateway webhook retry can still deliver an OLDER payload
    after a newer one already landed. Guard against regressing a fresher
    stored value by comparing timestamps before overwriting.
    """
    existing = get_item(table, {"date": date_str, "metric_source": metric_source}) or {}
    existing_ts = existing.get("source_ts") or ""
    if existing_ts and incoming_ts and incoming_ts < existing_ts:
        # Incoming payload is older than what's already stored — ignore it
        # rather than regress to a stale value.
        return
    item = {
        "date": date_str,
        "metric_source": metric_source,
        "value": incoming_val,
        "unit": unit,
        "source_ts": incoming_ts,
        "ingested_at": _now_iso(),
    }
    item.update(temporal or {})
    item.update(_merge_hae_evidence_metadata(existing, evidence))
    put_item(table, item)


def _log_hae_summary(data_list, *, request_context=None):
    """Print a compact one-line summary of an incoming HAE payload for CloudWatch.
    Shows metric names + point counts + a sample date so empty or malformed
    pushes are distinguishable from real data without dumping full bodies."""
    semantics = (request_context or {}).get("semantics") or "legacy_unclassified"
    if not data_list:
        print(f"HAE_SUMMARY semantics={semantics} metrics=0 payload_empty=true")
        return
    summary_parts = []
    for entry in data_list:
        name = (entry.get("name") or "?").strip().lower().replace(" ", "_")[:30]
        points = entry.get("data") or []
        count = len(points)
        sample_date = ""
        if count:
            raw = (
                points[0].get("date")
                or points[0].get("startDate")
                or points[0].get("endDate")
                or ""
            )
            sample_date = _coerce_date(raw) or source_date_str(raw) or ""
        summary_parts.append(f"{name}:{count}@{sample_date}")
    print(
        f"HAE_SUMMARY semantics={semantics} metrics={len(data_list)} "
        + " ".join(summary_parts[:20])
    )


def _log_hae_unmapped_metric(raw_metric_name, point_count, *, request_context=None):
    """Warn about a dropped HAE metric without logging observation values.

    Unknown metric names are useful configuration/coverage evidence. Keep the
    name readable for diagnosis, but remove control characters and bound it so
    an unexpected sender cannot forge log lines or create unbounded log data.
    """
    metric_name = re.sub(r"[\x00-\x1f\x7f]+", " ", str(raw_metric_name)).strip()[:128]
    metadata = (request_context or {}).get("metadata") or {}
    logger.warning(
        "HAE_UNMAPPED_METRIC metric_name=%s point_count=%d semantics=%s "
        "automation_name=%s automation_id=%s",
        metric_name or "?",
        int(point_count),
        (request_context or {}).get("semantics") or "legacy_unclassified",
        metadata.get("hae_automation_name") or "?",
        metadata.get("hae_automation_id") or "?",
    )


def _log_hae_invalid_metric(raw_metric_name, point_count, *, reason):
    logger.warning(
        "HAE_INVALID_METRIC metric_name=%s point_count=%d reason=%s",
        _safe_hae_metadata_value(raw_metric_name, 128) or "?",
        int(point_count),
        _safe_hae_metadata_value(reason, 64) or "?",
    )


def _log_hae_unsupported_daily_metric(raw_metric_name, point_count):
    logger.warning(
        "HAE_UNSUPPORTED_DAILY_SUMMARY_METRIC metric_name=%s point_count=%d",
        _safe_hae_metadata_value(raw_metric_name, 128) or "?",
        int(point_count),
    )


def _log_hae_invalid_daily_metric(raw_metric_name, point_count):
    logger.warning(
        "HAE_INVALID_DAILY_SUMMARY_METRIC metric_name=%s point_count=%d",
        _safe_hae_metadata_value(raw_metric_name, 128) or "?",
        int(point_count),
    )


def _hae_temporal_metadata(value):
    """Derive HAE context without mistaking UTC for event-local time.

    HAE's non-zero device offsets carry useful local-day context. A bare UTC
    representation (``Z`` / ``+00:00``) supplies only an absolute instant, so
    it must use the configured home timezone unless separate local context is
    added in a future payload contract.
    """
    parsed = parse_timestamp(value)
    source_offset_trusted = False
    if parsed is not None and parsed.tzinfo is not None:
        offset = parsed.utcoffset()
        source_offset_trusted = offset is not None and offset.total_seconds() != 0
    return temporal_metadata(
        value,
        source_timezone_trusted=source_offset_trusted,
        allow_naive_source_date=True,
    )


def _merge_hae_temporal_metadata(*items):
    """Combine derivation markers for values aggregated into one HAE row.

    A daily row can merge samples from multiple webhook deliveries. Preserve a
    confident derivation only when every contributing sample agrees; otherwise
    record the contributing derivations without retaining a misleading offset.
    """
    metadata = [item for item in items if isinstance(item, dict) and item]
    if not metadata:
        return {}

    derivations = set()
    for item in metadata:
        derivation = item.get("date_derivation")
        if derivation == "mixed_source_derivations":
            derivations.update(item.get("date_derivations") or [])
        elif derivation:
            derivations.add(derivation)

    merged = {}
    for field in ("source_date", "analysis_date"):
        values = {item.get(field) for item in metadata if item.get(field)}
        if len(values) == 1:
            merged[field] = values.pop()

    if len(derivations) == 1:
        merged["date_derivation"] = next(iter(derivations))
        for field in (
            "source_utc_offset",
            "analysis_utc_offset",
            "source_timezone",
            "analysis_timezone",
        ):
            values = {item.get(field) for item in metadata if item.get(field)}
            if len(values) == 1:
                merged[field] = values.pop()
    elif derivations:
        merged["date_derivation"] = "mixed_source_derivations"
        merged["date_derivations"] = sorted(derivations)

    return merged


def _coerce_date(s):
    """Derive an HAE analysis date while preserving its existing contract.

    HAE's normal point timestamps carry a device/source offset, which is
    treated as event-local context. Legacy date-only and naive values retain
    their explicit source date without claiming a timezone; malformed values
    remain unusable instead of falling back to string slicing.
    """
    return _hae_temporal_metadata(s).get("analysis_date")


def _minutes_between(start, end):
    """Compute minute duration between two HAE datetime strings (various formats)."""
    a = _parse_ts_min(start)
    b = _parse_ts_min(end)
    if a is None or b is None:
        return None
    return round(b - a)


def _parse_ts_min(ts):
    """Parse an HAE timestamp into an absolute minute count for ordering +
    gap arithmetic. Returns None on unparseable input. Handles the 4 formats
    HAE has shipped historically: naive local, ISO with zone, ISO Z, and
    'YYYY-MM-DD HH:MM:SS ±HHMM'."""
    dt = parse_timestamp(ts)
    if dt is None:
        return None
    if dt.tzinfo is not None and dt.utcoffset() is not None:
        return dt.timestamp() / 60
    # Duration/gap arithmetic between naive HAE values does not require a
    # timezone. Use a naive epoch solely as an ordering coordinate rather than
    # letting datetime.timestamp() silently assume the Lambda host timezone.
    return (dt - datetime(1970, 1, 1)).total_seconds() / 60


def _normalize_sleep(sleep, date_str):
    """Normalize HAE sleep data into a single health-metrics item.

    Accepts two shapes:
      - dict: already-aggregated stage totals (used by internal callers)
      - list: per-segment records from HAE unaggregated mode, with
        start/end timestamps. Segment objects are preserved on the
        returned row so compute can derive arousal count + onset latency.
    """
    item = {
        "date": date_str,
        "metric_source": "sleep#hae",
        "ingested_at": _now_iso(),
    }

    if isinstance(sleep, dict):
        item["total_min"] = sleep.get("total_min") or sleep.get("asleep_min") or sleep.get("duration", 0)
        item["deep_min"] = sleep.get("deep_min") or sleep.get("deep", 0)
        item["rem_min"] = sleep.get("rem_min") or sleep.get("rem", 0)
        item["core_min"] = sleep.get("core_min") or sleep.get("core") or sleep.get("light", 0)
        item["awake_min"] = sleep.get("awake_min") or sleep.get("awake", 0)
        item["in_bed_min"] = sleep.get("in_bed_min") or sleep.get("inBed", 0)
        total = item["total_min"]
        in_bed = item["in_bed_min"]
        item["efficiency"] = round((total / in_bed) * 100, 1) if in_bed > 0 else 0
    elif isinstance(sleep, list):
        stage_totals = {"deep": 0, "rem": 0, "core": 0, "awake": 0, "inBed": 0, "asleep": 0}
        segments = []
        for entry in sleep:
            raw_val = entry.get("value", "")
            val = raw_val.lower().replace(" ", "")
            dur = entry.get("duration_min", entry.get("duration", 0))
            if "deep" in val:
                stage_totals["deep"] += dur
                stage = "deep"
            elif "rem" in val:
                stage_totals["rem"] += dur
                stage = "rem"
            elif "core" in val or "light" in val:
                stage_totals["core"] += dur
                stage = "core"
            elif "awake" in val:
                stage_totals["awake"] += dur
                stage = "awake"
            elif "inbed" in val:
                stage_totals["inBed"] += dur
                stage = "in_bed"
            elif "asleep" in val:
                stage_totals["asleep"] += dur
                stage = "asleep"
            else:
                continue
            start = entry.get("start") or entry.get("startDate") or entry.get("sleepStart")
            end = entry.get("end") or entry.get("endDate") or entry.get("sleepEnd")
            if start:
                segments.append({
                    "start": str(start),
                    "end": str(end) if end else None,
                    "stage": stage,
                    "dur_min": round(float(dur), 1),
                })

        total = stage_totals["deep"] + stage_totals["rem"] + stage_totals["core"]
        if stage_totals["asleep"] and not total:
            total = stage_totals["asleep"]

        item["total_min"] = round(total)
        item["deep_min"] = round(stage_totals["deep"])
        item["rem_min"] = round(stage_totals["rem"])
        item["core_min"] = round(stage_totals["core"])
        item["awake_min"] = round(stage_totals["awake"])
        in_bed = stage_totals["inBed"] or (total + stage_totals["awake"])
        item["in_bed_min"] = round(in_bed)
        item["efficiency"] = round((total / in_bed) * 100, 1) if in_bed > 0 else 0
        if segments:
            item["segments"] = segments
            starts = [s["start"] for s in segments if s.get("start")]
            ends = [s["end"] for s in segments if s.get("end")]
            if starts:
                item["sleep_start"] = min(starts)
            if ends:
                item["sleep_end"] = max(ends)
    else:
        return None

    _stamp_quality(item)
    return item


def _normalize_sleep_aggregated(p, date_str):
    """Normalize HAE aggregated sleep record (hours-based) into health-metrics row."""
    def hours_to_min(v):
        try:
            return round(float(v) * 60)
        except (TypeError, ValueError):
            return 0

    asleep_min = hours_to_min(p.get("asleep"))
    total_min = hours_to_min(p.get("totalSleep")) or asleep_min
    deep_min = hours_to_min(p.get("deep"))
    rem_min = hours_to_min(p.get("rem"))
    core_min = hours_to_min(p.get("core"))
    in_bed_min = hours_to_min(p.get("inBed")) or (total_min + hours_to_min(p.get("awake")))
    awake_min = max(0, in_bed_min - (total_min or asleep_min)) if in_bed_min else hours_to_min(p.get("awake"))

    if not (total_min or deep_min or rem_min or core_min):
        return None

    item = {
        "date": date_str,
        "metric_source": "sleep#hae",
        "total_min": total_min,
        "asleep_min": asleep_min or total_min,
        "deep_min": deep_min,
        "rem_min": rem_min,
        "core_min": core_min,
        "awake_min": awake_min,
        "in_bed_min": in_bed_min,
        "efficiency": round((total_min / in_bed_min) * 100, 1) if in_bed_min > 0 else 0,
        "sleep_start": p.get("sleepStart"),
        "sleep_end": p.get("sleepEnd"),
        "ingested_at": _now_iso(),
    }
    _stamp_quality(item)
    return item


def _stamp_quality(item: dict) -> None:
    """Attach quality_flag, quality_reasons, confidence to a sleep row
    built by one of the normalizers. Mutates in place.

    We can't query the wrist-temp table from inside ingest (the caller
    processes metrics in a single pass and the wrist-temp row may or may
    not have been written yet). So we trust-but-verify here: assume
    watch-was-on-wrist unless segments clearly contradict. Compute later
    re-checks against the actual wrist-temp row and can downgrade a row
    that passed ingest but fails the stricter daily check.
    """
    q = _eval_sleep_quality(item, has_wrist_temp_today=True)
    item["quality_flag"] = q["quality_flag"]
    item["quality_reasons"] = q["quality_reasons"]
    item["confidence"] = q["confidence"]


def _handle_withings(event):
    """Process Withings webhook notification — fetch actual data via API.

    Withings does not sign notification POSTs (verified 2026-05 against their
    developer docs). Our trust anchor is therefore the OAuth `access_token`
    on the downstream `getmeas` call, not the webhook itself — the webhook
    only tells us *when* to fetch, not *what* the data is. A spoofed
    notification at worst causes a spurious Withings API round-trip for a
    user-id we own. Still, we layer defensive checks:

    - `appli` allowlist (only `1` = weight measurement is acted on)
    - optional `userid` allowlist from the secret, rejecting notifications
      for userids we didn't link
    - callback URL obscurity (existing; no change)
    """
    body = _parse_body(event)
    # Withings verifies the callback URL with an empty or sparse form POST;
    # it expects a 2xx response before activating the subscription.
    if body is None:
        return _resp(200, {"status": "verified"})
    if not body:
        return _resp(200, {"status": "verified"})

    appli = body.get("appli")
    if appli is None:
        # Verification ping with no appli — respond 200 so Withings accepts the subscription
        return _resp(200, {"status": "verified"})
    if appli != 1:
        return _resp(200, {"status": "ignored", "appli": appli})

    startdate = body.get("startdate")
    enddate = body.get("enddate")

    secret = _get_secret("withings-oauth")
    if not secret:
        return _resp(500, {"error": "missing withings credentials"})

    # Userid allowlist — Withings puts the linked user on `userid` (Withings'
    # own field name, kept verbatim in our secret by the OAuth handshake).
    # We also accept `user_id` (snake-case) and `userids` (list) for flexibility.
    # Absent → skip the check (backwards-compatible; older deploys without a
    # recorded userid still work). Present → reject mismatches.
    notif_userid = str(body.get("userid") or "").strip()
    allowed: list[str] = []
    for scalar_key in ("userid", "user_id"):
        if secret.get(scalar_key):
            allowed.append(str(secret[scalar_key]))
    if isinstance(secret.get("userids"), list):
        allowed.extend(str(u) for u in secret["userids"])
    if allowed and notif_userid and notif_userid not in allowed:
        logger.warning("rejected withings notification for userid=%s (not in allowlist)", notif_userid)
        return _resp(200, {"status": "ignored", "reason": "userid not in allowlist"})

    # Ensure the access token is usable. OAuth secrets bypass the warm-process
    # cache, and refresh-token rotation is serialized by a DynamoDB lease.
    try:
        token = _ensure_oauth_access_token("withings")
    except OAuthRefreshError as exc:
        logger.error("withings token refresh failed code=%s", exc.code)
        return _resp(500, {"error": "withings token refresh failed", "code": exc.code})

    # First attempt; if auth fails, refresh and retry once.
    data = _withings_getmeas(token, startdate, enddate)
    if data.get("status") in (401, 601):
        try:
            token = _refresh_withings_token(token)
        except OAuthRefreshError as exc:
            logger.error("withings forced token refresh failed code=%s", exc.code)
            return _resp(500, {"error": "withings token refresh failed", "code": exc.code})
        data = _withings_getmeas(token, startdate, enddate)

    if data.get("status") != 0:
        return _resp(502, {"error": "withings API returned error", "status": data.get("status")})

    table = get_table("HEALTH_METRICS_TABLE")
    items_written = 0

    measure_types = {1: "weight", 6: "fat_ratio", 8: "fat_mass", 76: "muscle_mass", 77: "hydration"}

    for grp in data.get("body", {}).get("measuregrps", []):
        source_time = datetime.fromtimestamp(grp["date"], tz=timezone.utc)
        temporal = temporal_metadata(source_time)
        grp_date = temporal.get("analysis_date")
        if not grp_date:
            continue
        for m in grp.get("measures", []):
            mtype = measure_types.get(m["type"])
            if not mtype:
                continue
            value = m["value"] * (10 ** m["unit"])
            if mtype == "weight":
                value = round(value * 2.20462, 1)  # kg → lbs
            elif mtype in ("fat_mass", "muscle_mass", "hydration"):
                value = round(value * 2.20462, 1)
            elif mtype == "fat_ratio":
                value = round(value, 1)

            item = {
                "date": grp_date,
                "metric_source": f"{mtype}#withings",
                "value": value,
                "unit": "lbs" if mtype != "fat_ratio" else "%",
                "source_time": source_time.isoformat(),
                "ingested_at": _now_iso(),
            }
            item.update(temporal)
            put_item(table, item)
            items_written += 1

    return _resp(200, {"items_written": items_written})


def _withings_getmeas(token, startdate, enddate):
    """Call Withings getmeas. Returns parsed response (even on non-zero status)."""
    params = urllib.parse.urlencode({
        "action": "getmeas",
        "meastype": "1,6,8,76,77",
        "category": 1,
        "startdate": startdate or 0,
        "enddate": enddate or 0,
    })
    req = urllib.request.Request(
        f"https://wbsapi.withings.net/measure?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Withings normally returns 200 with status code in body, but surface 401 explicitly
        try:
            return json.loads(e.read())
        except Exception:
            return {"status": e.code}
    except Exception as e:
        return {"status": -1, "error": str(e)}


def _ensure_oauth_access_token(vendor, *, force=False, failed_access_token=None):
    return oauth_service.ensure_access_token(
        vendor,
        force=force,
        failed_access_token=failed_access_token,
    )


def _refresh_withings_token(failed_access_token=None):
    """Force refresh after Withings rejects an access token."""
    return _ensure_oauth_access_token(
        "withings",
        force=True,
        failed_access_token=failed_access_token,
    )


def _strava_get(url, token):
    """GET Strava API endpoint; returns (parsed_body_or_None, http_status)."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, -1


def _refresh_strava_token(failed_access_token=None):
    """Force refresh after Strava rejects an access token."""
    return _ensure_oauth_access_token(
        "strava",
        force=True,
        failed_access_token=failed_access_token,
    )


def _handle_strava_verify(event):
    """Strava webhook subscription verification."""
    qs = event.get("queryStringParameters", {}) or {}
    mode = qs.get("hub.mode")
    token = qs.get("hub.verify_token")
    challenge = qs.get("hub.challenge")

    secret = _get_secret("strava-oauth")
    verify_token = secret.get("verify_token", "fitness-strava-verify") if secret else "fitness-strava-verify"

    if mode == "subscribe" and token == verify_token:
        return _resp(200, {"hub.challenge": challenge})

    return _resp(403, {"error": "verification failed"})


def _handle_strava(event):
    """Process Strava webhook event — fetch activity and compute strain.

    Strava webhooks don't carry a per-request signature; the auth model is
    the verify_token handshake at subscription time (see _strava_verify) +
    the secrecy of the webhook URL. We re-fetch the activity from Strava's
    API before writing, so a spoofed POST can't inject fake data — at worst
    it triggers a token refresh + a 200 ignore for unknown ids.
    """
    body = _parse_body(event)
    if not body:
        return _resp(400, {"error": "invalid body"})

    obj_type = body.get("object_type")
    aspect_type = body.get("aspect_type")
    obj_id = body.get("object_id")

    if obj_type != "activity" or aspect_type not in ("create", "update"):
        return _resp(200, {"status": "ignored"})

    try:
        token = _ensure_oauth_access_token("strava")
    except OAuthRefreshError as exc:
        logger.error("strava token refresh failed code=%s", exc.code)
        return _resp(500, {"error": "strava token refresh failed", "code": exc.code})

    activity, status = _strava_get(f"https://www.strava.com/api/v3/activities/{obj_id}", token)
    if status == 401:
        try:
            token = _refresh_strava_token(token)
        except OAuthRefreshError as exc:
            logger.error("strava forced token refresh failed code=%s", exc.code)
            return _resp(500, {"error": "strava token refresh failed", "code": exc.code})
        activity, status = _strava_get(f"https://www.strava.com/api/v3/activities/{obj_id}", token)
    if status != 200 or activity is None:
        return _resp(502, {"error": f"strava activity fetch failed (status {status})"})

    streams, _ = _strava_get(
        f"https://www.strava.com/api/v3/activities/{obj_id}/streams?keys=heartrate&key_type=time",
        token,
    )
    hr_stream = []
    if isinstance(streams, list):
        for s in streams:
            if s.get("type") == "heartrate":
                hr_stream = s.get("data", [])
                break

    source_start_time = activity.get("start_date_local")
    absolute_start_time = activity.get("start_date")
    source_date = source_date_str(source_start_time)
    if source_date:
        start_date = source_date
        temporal = {
            "source_date": source_date,
            "analysis_date": source_date,
            "date_derivation": "strava_start_date_local",
        }
    else:
        temporal = temporal_metadata(absolute_start_time)
        start_date = temporal.get("analysis_date") or local_today_str()
        if not temporal.get("analysis_date"):
            temporal = {
                "analysis_date": start_date,
                "analysis_timezone": HOME_TIMEZONE,
                "date_derivation": "ingest_home_date_fallback",
            }

    workout_item = {
        "date": start_date,
        "strava_id": str(obj_id),
        "title": activity.get("name", ""),
        "type": activity.get("sport_type", activity.get("type", "")),
        "dur": round(activity.get("elapsed_time", 0) / 60),
        "avgHR": round(activity.get("average_heartrate", 0), 1),
        "maxHR": round(activity.get("max_heartrate", 0)),
        "cal": round(activity.get("calories", 0)),
        "source": "strava",
        "ingested_at": _now_iso(),
    }
    workout_item.update(temporal)
    if source_start_time:
        workout_item["source_start_time"] = source_start_time
    if absolute_start_time:
        workout_item["start_time"] = absolute_start_time
    elif source_start_time:
        workout_item["start_time"] = source_start_time
    source_timezone = activity.get("timezone")
    if isinstance(source_timezone, str) and source_timezone.strip():
        workout_item["source_timezone"] = source_timezone.strip()
    if activity.get("utc_offset") is not None:
        workout_item["source_utc_offset_seconds"] = activity.get("utc_offset")

    # De-dupe guard: Hevy is the source of truth for strength/lifting sessions.
    # If Strava classified this activity as strength (e.g. a "Workout" or
    # "WeightTraining" logged from the watch), drop it so it doesn't collide
    # with the Hevy row for the same session. Cardio/outdoor stays on Strava.
    strava_type = str(workout_item["type"] or "").strip().lower()
    if strava_type in STRAVA_STRENGTH_TYPES:
        logger.info(
            "strava activity %s type=%s is strength — skipping (Hevy owns strength)",
            obj_id, workout_item["type"],
        )
        return _resp(200, {"status": "ignored", "reason": "strength activity handled by Hevy"})

    if hr_stream:
        trimp_data = compute_trimp(hr_stream, sample_interval_sec=1.0)
        workout_item["trimp"] = trimp_data["trimp"]
        workout_item["strain"] = compute_strain(trimp_data["trimp"])
        workout_item["zones"] = trimp_data["zone_minutes"]
    elif workout_item["avgHR"] > 0:
        # No stream — fall back to summary-stat strain estimate.
        # Also back-fill a TRIMP so downstream daily/ACWR math still works.
        dur_min = workout_item["dur"]
        avg_zone = classify_hr_zone(workout_item["avgHR"])
        estimated_trimp = dur_min * {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}[avg_zone]
        workout_item["trimp"] = round(estimated_trimp, 1)
        workout_item["strain"] = estimate_strain_simple(
            exercise_minutes=dur_min,
            active_calories=workout_item.get("cal", 0),
            avg_hr=workout_item["avgHR"],
            max_hr_observed=workout_item.get("maxHR") or None,
        )
        workout_item["zones_estimated"] = True

    table = get_table("WORKOUTS_TABLE")
    put_item(table, workout_item)

    _trigger_compute(start_date)

    return _resp(200, {"date": start_date, "strava_id": str(obj_id), "strain": workout_item.get("strain")})


def _handle_oauth_credential_check():
    """Daily idempotent OAuth check; fails observably if either vendor fails."""
    try:
        results = oauth_service.check_credentials()
    except OAuthCredentialCheckError as exc:
        logger.error("OAuth credential check failed results=%s", exc.results)
        raise
    return _resp(200, {"status": "ok", "vendors": results})


# ── Hevy sync (scheduled poll) ─────────────────────────────────

def _handle_hevy_sync(event):
    """Poll the Hevy API for strength workouts + body measurements and upsert.

    Runs from the EventBridge daily schedule (source == "aws.events") or an
    explicit async invoke with {"action": "hevy_poll"}. Hevy has no webhooks on
    its public API, so this poll is how gym/lifting sessions reach the stack.

    Three sync modes:
      • INCREMENTAL (default when a ``hevy_last_sync`` watermark exists): pull
        GET /v1/workouts/events?since=<watermark>, applying updates AND
        deletions. This is Hevy's purpose-built incremental feed and is the
        only way a workout deleted in Hevy ever gets removed from McFox.
      • COLD START (no watermark): page-walk GET /v1/workouts newest-first as a
        bounded backfill, then set the watermark so subsequent polls go
        incremental.
      • BACKFILL ({"action": "hevy_backfill"} or force_full/reset_watermark on a
        poll): IGNORE the watermark, full page-walk of GET /v1/workouts, and
        write BOTH rolled-up and per-exercise rows for EVERY workout regardless
        of dupe state (force=True). Sized by default to cover Mateo's full
        history (pageSize 10 × 20 pages = up to 200 workouts); page_size and
        max_pages are event-overridable. Idempotent, so safely re-runnable.

    Each workout is written to BOTH:
      • fitness-workouts — the rolled-up session row (dur/volume/strain/etc.)
      • fitness-exercises — one row per canonical exercise, in the exact shape
        the existing lift engine (lift_compute / coach / proposer / api) reads.
        Writing here lights up e1RM, PR detection, stall detection and weekly
        volume for free. We recompute PR flags for the touched canonicals
        exactly as workout_service.annotate_workout does.

    Also ingests GET /v1/body_measurements into fitness-health-metrics under a
    ``#hevy`` source suffix, routed through the same merge/ordering-guard
    helpers the HAE path uses (never a bare put_item overwrite).

    Missing credentials remain a configuration skip. Once a vendor read starts,
    incomplete fetches and apply failures raise so EventBridge/Lambda telemetry
    records a failed check rather than a success-looking empty poll.
    """
    secret = _get_secret("hevy-api-key")
    api_key = (secret or {}).get("api_key") or (secret or {}).get("key") or ""
    if not api_key:
        logger.warning(
            "hevy-api-key secret missing or has no 'api_key' field — skipping Hevy "
            "sync. Create the 'hevy-api-key' secret in Secrets Manager (us-west-2) "
            "with an {\"api_key\": \"...\"} value to enable gym/lifting ingest."
        )
        return _resp(200, {"status": "skipped", "reason": "hevy-api-key secret missing"})

    # This is the safe upper boundary for the current poll. It must be captured
    # before any vendor retrieval (including template refresh), then persisted
    # only after the whole sync completes.
    sync_started_at = _now_iso()

    # Backfill mode: an explicit {"action": "hevy_backfill"} invoke, or a normal
    # poll carrying force_full / reset_watermark. It IGNORES the watermark and
    # does a full page-walk of GET /v1/workouts, writing BOTH rolled-up and
    # per-exercise rows for every workout regardless of dupe state. Defaults are
    # sized to cover Mateo's full history (~32+ sessions): pageSize 10 × 20 pages
    # = up to 200 workouts, both overridable by the event. Safely re-runnable —
    # every write is an idempotent overwrite.
    backfill = (
        event.get("action") == "hevy_backfill"
        or bool(event.get("force_full"))
        or bool(event.get("reset_watermark"))
    )
    if backfill:
        page_size = int(event.get("page_size", 10) or 10)
        max_pages = int(event.get("max_pages", 20) or 20)
    else:
        page_size = int(event.get("page_size", 10) or 10)
        max_pages = int(event.get("max_pages", 3) or 3)

    config_table = get_table("USER_CONFIG_TABLE")

    # 1) Refresh the exercise-template cache if stale (templates are near-static;
    #    never re-fetch ~226 rows on every poll). A backfill forces a refresh so
    #    muscle-group resolution is current for the whole history walk.
    templates = _load_hevy_templates(config_table, api_key, force_refresh=backfill)

    # 2) Fetch workouts. Backfill always page-walks GET /v1/workouts and ignores
    #    the watermark; a normal poll goes incremental when a watermark exists,
    #    else cold-start page-walk.
    watermark_row = get_item(config_table, {"key": LAST_SYNC_KEY}) or {}
    last_sync = watermark_row.get("last_sync")

    updated_workouts: list = []
    deleted_ids: list = []
    mode = "incremental"
    replay_since = None
    fetch_status = "unknown"
    fetch_pages_read = 0
    record_issues = []
    ignored_events = []
    try:
        if backfill:
            mode = "backfill"
            fetch_result = fetch_recent_workouts_full(
                api_key, page_size=page_size, max_pages=max_pages
            )
            updated_workouts = fetch_result.items
        elif last_sync:
            replay_since = _hevy_replay_since(last_sync)
            ev = fetch_workout_events(
                api_key,
                since=replay_since,
                page_size=page_size,
                max_pages=int(event.get("max_pages", 20) or 20),
            )
            fetch_result = ev
            updated_workouts = ev.updated
            deleted_ids = ev.deleted
        else:
            mode = "cold_start"
            fetch_result = fetch_recent_workouts_full(
                api_key, page_size=page_size, max_pages=max_pages
            )
            updated_workouts = fetch_result.items
    except ValueError as e:
        logger.error("hevy sync configuration/boundary error: %s", e)
        raise HevySyncError("hevy sync configuration is invalid") from e
    except Exception as exc:  # noqa: BLE001 — surface an observable invocation failure
        logger.exception("hevy sync failed unexpectedly")
        raise HevySyncError("hevy workout fetch failed") from exc

    fetch_status = fetch_result.status
    fetch_pages_read = fetch_result.pages_read
    if not fetch_result.complete:
        logger.error(
            "hevy %s fetch incomplete: status=%s pages_read=%s truncated=%s reason=%s",
            mode,
            fetch_result.status,
            fetch_result.pages_read,
            fetch_result.truncated,
            _safe_hevy_fetch_reason(fetch_result.error),
        )
        raise HevySyncError(f"hevy workout fetch incomplete: {fetch_result.status}")

    record_issues = list(fetch_result.record_issues)
    ignored_events = list(getattr(fetch_result, "ignored_events", ()))
    pending_record_issues, reviewed_skips = _reviewed_hevy_record_overrides(
        event, record_issues
    )
    for issue in record_issues:
        logger.error(
            "hevy record unusable: id=%s type=%s reason=%s",
            issue["record_id"], issue["event_type"], issue["reason"],
        )

    workouts_table = get_table("WORKOUTS_TABLE")
    exercises_table = get_table("EXERCISES_TABLE")

    written = 0
    ex_rows_written = 0
    backfilled = 0
    affected_dates = set()
    affected_canonicals = set()
    sync_failure = None

    # 3) Apply updates: rolled-up row + per-exercise rows.
    #
    #    The two writes are DECOUPLED. The rolled-up fitness-workouts row and the
    #    per-exercise fitness-exercises rows are independent stores with
    #    different keys and different consumers (session view vs the lift
    #    engine). "The rolled-up row is unchanged" does NOT imply "the exercise
    #    rows exist" — the pre-PR#3 poller wrote rolled-up rows with no exercise
    #    rows at all, which is exactly why the first cold-start poll backfilled
    #    only a handful of dates (the dupe-check short-circuited before the
    #    exercise write). So the dupe-check may only suppress the redundant
    #    fitness-workouts put_item; it must NEVER gate the exercise-row write.
    for workout in updated_workouts:
        try:
            outcome = _apply_hevy_workout(
                workout, templates, workouts_table, exercises_table, force=backfill
            )
        except HevyLegacyLookupError:
            # Identity is unknown, so writing under the newly derived date can
            # duplicate a legacy UTC-keyed row. Stop before either store or the
            # watermark advances; an ordinary future poll can retry safely.
            logger.exception(
                "hevy sync stopped: legacy identity lookup failed for %s",
                workout.get("id"),
            )
            sync_failure = HevySyncError("hevy legacy lookup failed")
            break
        if outcome is None:
            continue
        if outcome["workout_written"]:
            written += 1
        if outcome["backfilled"]:
            backfilled += 1
        ex_rows_written += outcome["ex_rows_written"]
        if outcome["touched"]:
            affected_dates.add(outcome["date"])
            affected_canonicals.update(outcome["canonicals"])

    # 4) Apply deletions: a workout removed in Hevy must leave McFox too.
    deleted = 0
    if sync_failure is None:
        for hevy_id in deleted_ids:
            try:
                removed_dates = _delete_hevy_workout(
                    workouts_table, exercises_table, hevy_id
                )
            except HevyDeleteError:
                logger.exception("hevy sync stopped: deletion apply failed for %s", hevy_id)
                sync_failure = HevySyncError("hevy deletion apply failed")
                break
            if removed_dates:
                deleted += 1
                affected_dates.update(removed_dates)

    # 5) Recompute PR flags + e1RM for touched canonicals and refresh the
    #    weekly volume roll-up, exactly as workout_service.annotate_workout does.
    _finalize_hevy_recomputations(affected_canonicals, affected_dates)

    # A failure discovered after earlier writes remains a failed invocation,
    # but only after those safe writes receive their required derived updates.
    if sync_failure is not None:
        raise sync_failure

    # Transport was complete, so valid records were safe to apply. A bad
    # individual record still requires explicit operator review before the
    # watermark can advance; this keeps it visible without stranding valid
    # records. The exception carries sanitized record diagnostics.
    if pending_record_issues:
        raise HevyRecordIssueError(pending_record_issues)

    # 6) Body measurements → health-metrics via the merge/ordering-guard path.
    #    Distinguish "Mateo has genuinely never logged a body measurement" from
    #    "the fetch/parse failed" so measurements_written: 0 is never silently
    #    ambiguous (that ambiguity is exactly what hid the pageSize>10 → HTTP 400
    #    bug behind an innocent-looking zero on the first live runs).
    #
    #    NOTE ON ORDERING: unlike the two fail-closed paths above (a legacy
    #    identity failure or an unusable record legitimately must NOT advance the
    #    watermark, so they raise before step 8), a body-measurement fetch that
    #    is merely *truncated* by a vendor pagination limit is growth-triggered
    #    and self-perpetuating: if it blocked the watermark, every later poll
    #    would re-read an ever-growing replay window and die on the same line
    #    forever. So we ingest whatever complete records we have, ADVANCE THE
    #    WATERMARK (step 8) regardless, and only THEN surface the incompleteness
    #    as a failed invocation — forward progress is preserved while the error
    #    stays visible in CloudWatch. The watermark boundary (sync_started_at)
    #    was captured before any vendor retrieval, so no data is skipped.
    measurements = _ingest_hevy_body_measurements(api_key)
    if not measurements["complete"]:
        logger.error(
            "hevy body-measurement sync incomplete: status=%s",
            measurements["status"],
        )

    # 8) Advance only to the boundary captured before vendor retrieval. The
    #    next incremental poll subtracts the replay overlap from this value.
    #    This runs BEFORE the body-measurement completeness raise below so a
    #    vendor pagination limit can never again permanently freeze the sync.
    put_item(config_table, {
        "key": LAST_SYNC_KEY,
        "last_sync": sync_started_at,
        "mode": mode,
        "updated_at": _now_iso(),
        "replay_overlap_hours": HEVY_REPLAY_OVERLAP_HOURS,
    })

    # Now that forward progress is durably recorded, surface an incomplete
    # body-measurement fetch as an observable invocation failure. The watermark
    # has already advanced, so this does NOT re-freeze the sync — it just keeps
    # the failure visible instead of degrading to a silent success.
    if not measurements["complete"]:
        raise HevySyncError(
            f"hevy body-measurement sync incomplete: {measurements['status']}"
        )

    logger.info(
        "hevy sync complete (%s): %s written (%s backfilled), %s exercise rows, "
        "%s deleted across %s dates, %s measurements (%s)",
        mode, written, backfilled, ex_rows_written, deleted,
        len(affected_dates), measurements["written"], measurements["status"],
    )
    response_status = "ok"
    if reviewed_skips:
        response_status = "ok_with_reviewed_skips"
    elif ignored_events:
        response_status = "ok_with_ignored_events"
    return _resp(200, {
        "status": response_status,
        "mode": mode,
        "fetched": len(updated_workouts),
        "written": written,
        "workouts_written": written,
        "backfilled": backfilled,
        "exercise_rows_written": ex_rows_written,
        "deleted": deleted,
        "measurements_written": measurements["written"],
        "measurements_available": measurements["available"],
        "measurements_status": measurements["status"],
        "fetch_status": fetch_status,
        "fetch_pages_read": fetch_pages_read,
        "record_issues": record_issues,
        "reviewed_skips": reviewed_skips,
        "ignored_events": ignored_events,
        "sync_started_at": sync_started_at,
        "watermark": sync_started_at,
        "replay_since": replay_since,
        "canonicals_touched": sorted(affected_canonicals),
        "dates": sorted(affected_dates),
    })


def _reviewed_hevy_record_overrides(event, record_issues):
    """Validate an intentional operator acknowledgment of known bad IDs.

    Only IDs present in this completely retrieved response may be acknowledged;
    a typo or healthy ID fails closed and cannot cause a record to be skipped.
    """
    requested = event.get("skip_invalid_workout_ids", [])
    if requested is None:
        requested = []
    if not isinstance(requested, list) or any(
        not isinstance(value, str) or not value.strip() for value in requested
    ):
        raise ValueError("skip_invalid_workout_ids must be a list of non-empty strings")
    requested_ids = {value.strip() for value in requested}
    issue_ids = {issue["record_id"] for issue in record_issues}
    unknown_ids = sorted(requested_ids - issue_ids)
    if unknown_ids:
        raise ValueError(
            "skip_invalid_workout_ids contains IDs not present in record issues: "
            + ",".join(unknown_ids)
        )

    pending = []
    reviewed = []
    for issue in record_issues:
        if issue["record_id"] in requested_ids:
            reviewed.append(issue)
            logger.warning(
                "hevy unusable record intentionally skipped after review: "
                "id=%s type=%s reason=%s",
                issue["record_id"], issue["event_type"], issue["reason"],
            )
        else:
            pending.append(issue)
    return pending, reviewed


def _hevy_replay_since(last_sync):
    """Return the bounded replay start for a stored absolute watermark."""
    parsed = parse_timestamp(last_sync)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("hevy_last_sync must be an absolute timestamp")
    return (parsed.astimezone(timezone.utc) - timedelta(
        hours=HEVY_REPLAY_OVERLAP_HOURS
    )).isoformat()


def _finalize_hevy_recomputations(affected_canonicals, affected_dates):
    """Finish derived state for writes already completed in this invocation."""
    if affected_canonicals:
        try:
            recompute_prs_for_canonicals(sorted(affected_canonicals))
        except Exception:
            logger.exception("hevy PR recompute failed for %s", sorted(affected_canonicals))
        try:
            recompute_weekly_volume()
        except Exception:
            logger.exception("hevy weekly volume recompute failed")
    for date in sorted(affected_dates):
        _trigger_compute(date)


def _hevy_exercise_rows_exist(exercises_table, date, canonicals):
    """True only when EVERY expected canonical already has a fitness-exercises
    row for ``date``. Used to decide whether a workout whose rolled-up row is
    unchanged can be cheaply skipped, or must be backfilled.

    "Rolled-up row unchanged" is NOT the same condition as "exercise rows
    exist": the pre-PR#3 poller wrote rolled-up rows with zero exercise rows.
    So we check the exercise store directly rather than inferring from the
    session row. Empty ``canonicals`` (a workout with no parseable exercises)
    returns True — there is nothing to backfill.
    """
    if not canonicals:
        return True
    for canonical in canonicals:
        existing = get_item(exercises_table, {"canonical": canonical, "date": date})
        if not existing:
            return False
    return True


class HevySyncError(RuntimeError):
    """Raised so a scheduled Hevy invocation is observably unsuccessful."""


class HevyRecordIssueError(HevySyncError):
    """A complete vendor response contained records requiring review."""

    def __init__(self, record_issues):
        self.record_issues = tuple(record_issues)
        summary = "; ".join(
            f"id={issue['record_id']} type={issue['event_type']} "
            f"reason={issue['reason']}"
            for issue in self.record_issues
        )
        super().__init__(f"hevy records require operator review: {summary}")


class HevyLegacyLookupError(RuntimeError):
    """Raised when legacy Hevy identity cannot be determined safely."""


class HevyDeleteError(RuntimeError):
    """Raised when a deletion cannot be applied safely and should replay."""


def _find_existing_hevy_row(table, row):
    """Find an existing Hevy row even when its historical date key differs.

    Before temporal normalization, Hevy rows used the UTC timestamp prefix as
    the partition key. Re-keying those rows is explicitly a separate migration,
    so an update/backfill must discover the legacy key and keep writing there.
    New Hevy ids use the canonical home-timezone date from ``workout_to_row``.
    """
    try:
        existing = get_item(table, {"date": row["date"], "strava_id": row["strava_id"]})
        if existing:
            return existing

        params = {
            "FilterExpression": "strava_id = :sid",
            "ExpressionAttributeValues": {":sid": row["strava_id"]},
            "Limit": 1000,
        }
        while True:
            resp = table.scan(**params)
            for item in resp.get("Items", []):
                if item.get("strava_id") == row["strava_id"]:
                    return item
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
    except Exception as exc:
        logger.exception("hevy legacy-date lookup failed for %s", row["strava_id"])
        raise HevyLegacyLookupError(row["strava_id"]) from exc
    return None


def _apply_hevy_workout(workout, templates, workouts_table, exercises_table, force=False):
    """Upsert a single Hevy workout into BOTH stores, keeping the two writes
    decoupled.

    Decision table (per workout):
      • rolled-up row changed / absent  → write BOTH rows.
      • rolled-up row unchanged, exercise rows MISSING → backfill: write the
        exercise rows, skip the redundant fitness-workouts put_item.
      • rolled-up row unchanged, exercise rows PRESENT → skip both (cheap
        no-op), UNLESS ``force`` (the explicit backfill entrypoint), which
        always rewrites both. Existing Hevy ids retain a legacy date key when
        one exists, preventing this forward-only change from re-keying history.
        All writes remain idempotent overwrites keyed on (date, strava_id) and
        (canonical, date).

    Returns None when the workout is unusable (no id/date), else a dict:
      {workout_written, backfilled, ex_rows_written, touched, date, canonicals}
    where ``touched`` means the exercise store changed for this workout, so its
    canonicals must feed the PR / weekly-volume recompute.
    """
    row = workout_to_row(workout)
    if row is None:
        return None

    existing = _find_existing_hevy_row(workouts_table, row)
    canonical_date = row["date"]
    date = (existing or {}).get("date") or canonical_date
    if date != canonical_date:
        # Preserve the historical primary key while retaining the newly
        # derived canonical date as additive context for a future migration.
        row["date"] = date
        row["legacy_date_preserved"] = True

    ex_rows = workout_to_exercise_rows(workout, templates)
    canonicals = {er["canonical"] for er in ex_rows if er.get("canonical")}

    is_dupe = (not force) and _hevy_row_is_duplicate(row, existing=existing)
    rows_exist = _hevy_exercise_rows_exist(exercises_table, date, canonicals)

    # Fully synced and nothing changed → cheap skip (only when not forced).
    if is_dupe and rows_exist:
        logger.info(
            "hevy workout %s on %s unchanged and fully synced — skipping",
            row.get("hevy_id"), date,
        )
        return {
            "workout_written": False,
            "backfilled": False,
            "ex_rows_written": 0,
            "touched": False,
            "date": date,
            "canonicals": set(),
        }

    # Rolled-up row: write unless it's a genuine no-op duplicate. The dupe-check
    # ONLY suppresses this redundant session-row put — never the exercise write.
    workout_written = False
    if not is_dupe:
        put_item(workouts_table, row)
        workout_written = True

    # Exercise rows: always (re)written when we reach here. Idempotent overwrite
    # on (canonical, date). This is the backfill path when the session row was a
    # duplicate but its exercise rows were missing.
    ex_rows_written = _write_hevy_exercise_rows(exercises_table, ex_rows, date)
    backfilled = is_dupe and not workout_written

    if backfilled:
        logger.info(
            "hevy workout %s on %s: session row unchanged but exercise rows "
            "missing — backfilled %s exercise rows",
            row.get("hevy_id"), date, ex_rows_written,
        )

    return {
        "workout_written": workout_written,
        "backfilled": backfilled,
        "ex_rows_written": ex_rows_written,
        "touched": True,
        "date": date,
        "canonicals": canonicals,
    }


def _load_hevy_templates(config_table, api_key, force_refresh=False):
    """Return the exercise-template cache (id → template dict), refreshing it
    from Hevy only when the cached row is missing, older than ~7 days, or when
    ``force_refresh`` is set (the backfill entrypoint re-fetches so muscle-group
    resolution is current for the whole history walk).
    Degrades to whatever is cached (or {}) if the refresh call fails."""
    cache_row = get_item(config_table, {"key": TEMPLATE_CACHE_KEY}) or {}
    if not force_refresh and not templates_cache_is_stale(cache_row):
        return cache_row.get("templates") or {}
    try:
        templates = fetch_exercise_templates(api_key)
    except Exception:
        logger.exception("hevy exercise-template fetch failed — using cached/empty")
        return cache_row.get("templates") or {}
    if templates:
        put_item(config_table, {
            "key": TEMPLATE_CACHE_KEY,
            "templates": templates,
            "fetched_at": _now_iso(),
            "count": len(templates),
        })
        return templates
    # Empty fetch (e.g. transient 5xx) — keep whatever we had.
    return cache_row.get("templates") or {}


def _write_hevy_exercise_rows(table, exercise_rows, date):
    """Mirror Hevy-derived exercise rows into fitness-exercises, one row per
    (canonical, date). Mirrors workout_service._write_exercise_rows so the
    existing lift engine consumes them unchanged. Overwrites on re-poll
    (idempotent). Returns the number of rows written.

    Working-set metrics (top_weight / volume / session_count) EXCLUDE warmups
    but INCLUDE dropset/failure sets, matching how the LLM-parser path treats
    them and how lift_compute reads them.
    """
    now_iso = _now_iso()
    count = 0
    for ex in exercise_rows:
        if not ex.get("canonical"):
            continue
        sets = ex.get("sets", [])
        working_sets = [s for s in sets if not s.get("warmup")]
        top_weight = max((s.get("weight", 0) for s in working_sets), default=0)
        top_reps_at_top = max(
            (s.get("reps", 0) for s in working_sets if s.get("weight", 0) == top_weight),
            default=0,
        )
        volume = sum(s.get("reps", 0) * s.get("weight", 0) for s in working_sets)
        row = {
            "canonical": ex["canonical"],
            "date": date,
            "name": ex["name"],
            "muscle_group": ex.get("muscle_group", "other"),
            "sets": sets,
            "top_weight": round(top_weight, 1),
            "top_reps_at_top_weight": top_reps_at_top,
            "working_volume": round(volume, 1),
            "session_count": len(working_sets),
            "logged_at": now_iso,
            "source": "hevy",
        }
        if ex.get("superset_with"):
            row["superset_with"] = ex["superset_with"]
        if ex.get("superset_group"):
            row["superset_group"] = ex["superset_group"]
        if ex.get("note"):
            row["note"] = ex["note"]
        if ex.get("hevy_muscle_group"):
            row["hevy_muscle_group"] = ex["hevy_muscle_group"]
        if ex.get("exercise_template_id"):
            row["exercise_template_id"] = ex["exercise_template_id"]
        put_item(table, row)
        count += 1
    return count


def _delete_hevy_workout(workouts_table, exercises_table, hevy_id):
    """Remove a Hevy workout (and its mirrored exercise rows) that was deleted
    in Hevy. Returns the set of dates touched so daily scores can be recomputed.

    The workout row key is (date, strava_id="hevy_<id>") but we don't know the
    date up front, so we resolve it: the strava_id GSI isn't guaranteed, so we
    scan for the matching hevy_id. This is bounded (the table is small) and only
    runs for genuinely-deleted workouts, which are rare.
    """
    strava_id = f"hevy_{hevy_id}"
    touched = set()
    try:
        resp = workouts_table.scan(
            FilterExpression="strava_id = :sid",
            ExpressionAttributeValues={":sid": strava_id},
            Limit=1000,
        )
        matches = resp.get("Items", [])
    except Exception:
        logger.exception("hevy delete scan failed for %s", strava_id)
        raise HevyDeleteError(strava_id)

    for item in matches:
        date = item.get("date")
        if not date:
            continue
        # Remove mirrored exercise rows for this session's date that came from
        # Hevy. Exercise rows are keyed (canonical, date); only delete rows we
        # sourced from Hevy so a same-day manual annotation isn't clobbered.
        # Delete these first: if this step fails, retaining the workout row
        # preserves the date needed for a safe event replay.
        _delete_hevy_exercise_rows_for_date(exercises_table, date)
        try:
            workouts_table.delete_item(Key={"date": date, "strava_id": strava_id})
        except Exception as exc:
            logger.exception("failed to delete workout row %s/%s", date, strava_id)
            raise HevyDeleteError(strava_id) from exc
        touched.add(date)
    return touched


def _delete_hevy_exercise_rows_for_date(exercises_table, date):
    """Delete Hevy-sourced fitness-exercises rows for a given date. Scoped to
    source=="hevy" so manual/LLM-parsed rows for the same date survive."""
    try:
        resp = exercises_table.scan(
            FilterExpression="#d = :date AND #src = :src",
            ExpressionAttributeNames={"#d": "date", "#src": "source"},
            ExpressionAttributeValues={":date": date, ":src": "hevy"},
            Limit=1000,
        )
        rows = resp.get("Items", [])
    except Exception:
        logger.exception("hevy exercise-row delete scan failed for %s", date)
        raise HevyDeleteError(date)
    for r in rows:
        canonical = r.get("canonical")
        if not canonical:
            continue
        try:
            exercises_table.delete_item(Key={"canonical": canonical, "date": date})
        except Exception:
            logger.exception("failed to delete exercise row %s/%s", canonical, date)
            raise HevyDeleteError(date)


def _ingest_hevy_body_measurements(api_key):
    """Fetch Hevy body measurements and write each field into
    fitness-health-metrics under a ``#hevy`` source suffix, routed through the
    existing merge/ordering-guard helpers (NOT a bare put_item overwrite —
    that regression was fixed in PR #2 and must not return).

    Returns a summary dict so ``measurements_written: 0`` is never silently
    ambiguous:
      {"written": int, "available": int, "status": str, "complete": bool}
    where ``status`` is one of:
      • "ok"    — measurements were fetched and written
      • "empty" — the fetch succeeded but Mateo has genuinely logged none
      • other failure status — incomplete fetch/write (never an empty success)
    ``available`` is the count of raw measurement records Hevy returned.
    """
    try:
        result = fetch_body_measurements(api_key)
    except Exception:
        logger.exception("hevy body-measurement fetch failed")
        return {"written": 0, "available": 0, "status": "error", "complete": False}

    if not result.complete:
        return {
            "written": 0,
            "available": len(result.items),
            "status": result.status,
            "complete": False,
        }

    measurements = result.items

    if not measurements:
        # A valid, empty result. With the pageSize clamp in place this now
        # genuinely means "no measurements logged" rather than a masked 400.
        return {"written": 0, "available": 0, "status": "empty", "complete": True}

    table = get_table("HEALTH_METRICS_TABLE")
    written = 0
    try:
        for m in measurements:
            for metric_source, unit, kind, date, value in body_measurement_to_metrics(m):
                if kind == "last":
                    # Body measurements are point-in-time; guard against an
                    # out-of-order re-fetch regressing a fresher stored value.
                    _write_last_with_ordering_guard(
                        table, date, metric_source, unit, _now_iso(), value
                    )
                else:
                    _merge_samples_and_aggregate(
                        table, date, metric_source, unit, kind, [(_now_iso(), value)]
                    )
                written += 1
    except Exception:
        logger.exception("hevy body-measurement write failed")
        return {
            "written": written,
            "available": len(measurements),
            "status": "write_error",
            "complete": False,
        }

    return {
        "written": written,
        "available": len(measurements),
        "status": "ok",
        "complete": True,
    }


def _hevy_row_is_duplicate(row, existing=None):
    """Idempotency check for a Hevy row against what's already stored.

    Hevy rows are keyed on their own id (strava_id = "hevy_<id>"), so an
    upsert of the same Hevy workout is naturally idempotent — re-running the
    poll overwrites the same key rather than creating a dupe.

    Cross-source collisions (the same session in BOTH Hevy and Strava) are
    handled on the Strava side: the webhook drops strength activities, so a
    strength session only ever lands as a Hevy row. Hevy therefore always
    wins for strength and Strava owns cardio — no conflicting rows are created.

    This function returns True only when an identical Hevy row is already
    present (same volume + duration), meaning nothing changed and we can skip
    the redundant write. Any material change still upserts.
    """
    if not existing:
        return False
    same_volume = float(existing.get("volume_lb", -1) or -1) == float(row.get("volume_lb", 0) or 0)
    same_dur = int(existing.get("dur", -1) or -1) == int(row.get("dur", 0) or 0)
    return same_volume and same_dur


# ── Helpers ────────────────────────────────────────────────────

def _parse_body(event):
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    if not isinstance(body, str):
        return body
    if not body.strip():
        return {}
    # Try JSON first
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to form-encoded (Withings webhooks use this)
    try:
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        # parse_qs returns list values — unwrap singletons
        out = {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}
        # Coerce numerics that Withings sends
        for key in ("appli", "startdate", "enddate"):
            if key in out:
                try:
                    out[key] = int(out[key])
                except (ValueError, TypeError):
                    pass
        return out if out else None
    except Exception:
        return None


def _extract_date(data):
    """Extract YYYY-MM-DD date from various HAE payload formats."""
    for key in ("date", "dateFrom", "start_date", "timestamp"):
        val = data.get(key, "")
        if not val:
            continue
        parsed_date = _coerce_date(val)
        if parsed_date:
            return parsed_date
    return local_today_str()


def _extract_value(data):
    """Pull a numeric value from HAE metric data (handles dict, list, or scalar)."""
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        for key in ("qty", "value", "avg", "mean"):
            v = data.get(key)
            if v is not None:
                return float(v)
    if isinstance(data, list) and data:
        last = data[-1]
        if isinstance(last, dict):
            return _extract_value(last)
        return float(last)
    return None


def _verify_api_key(key):
    if not key:
        return False
    secret = _get_secret("fitness-api-key")
    if secret and secret.get("api_key") == key:
        return True
    expected = os.environ.get("INGEST_API_KEY", "")
    return expected and key == expected


_secret_cache = {}

def _get_secret(name):
    # OAuth refresh tokens rotate. Always bypass the warm-process cache so a
    # Lambda execution environment cannot keep using a superseded token.
    if name == "withings-oauth":
        try:
            return oauth_service.get_secret("withings")
        except OAuthRefreshError:
            return None
    if name == "strava-oauth":
        try:
            return oauth_service.get_secret("strava")
        except OAuthRefreshError:
            return None
    if name in _secret_cache:
        return _secret_cache[name]
    secrets_arn = os.environ.get("SECRETS_ARN", "")
    try:
        resp = secrets_client.get_secret_value(SecretId=name)
        val = json.loads(resp["SecretString"])
        _secret_cache[name] = val
        return val
    except Exception:
        return None


def _trigger_compute(date_str):
    if not COMPUTE_FN:
        return
    try:
        lambda_client.invoke(
            FunctionName=COMPUTE_FN,
            InvocationType="Event",
            Payload=json.dumps({"action": "compute_day", "date": date_str}),
        )
    except Exception:
        pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
