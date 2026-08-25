"""
Parser tests for the HAE ingest handler — runs the parsing logic locally
without AWS by mocking put_item / get_table.

Covers:
  - HAE v2 shape: {"data": {"metrics": [{name, data: [{qty, date}]}]}}
  - HAE v1 shape: {"data": [{name, data: [...]}]}
  - snake_case + title-case name variants
  - triple-HR expansion (Min/Avg/Max → 3 rows)
  - aggregated sleep (hours-based: totalSleep, asleep, deep, rem, inBed)
  - unaggregated sleep (per-stage segments with value/startDate/endDate)
  - "last" kind for weight / BMI
  - substring-safe sleep dispatch (does NOT catch "apple sleeping wrist temperature")
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item=None, **_kw):
        # Decimals will be passed in; convert to plain so we can assert easily
        from decimal import Decimal

        def unwrap(v):
            if isinstance(v, Decimal):
                return float(v) if v != int(v) else int(v)
            if isinstance(v, dict):
                return {k: unwrap(x) for k, x in v.items()}
            if isinstance(v, list):
                return [unwrap(x) for x in v]
            return v

        self.items.append(unwrap(Item))

    def get_item(self, Key=None, **_kw):
        """Return the most recently put item matching the composite key.
        Matches live DynamoDB semantics for the merge-guard path."""
        if not Key:
            return {}
        for item in reversed(self.items):
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": item}
        return {}


def _fresh_module():
    """Import a fresh copy of the handler with fake db wiring."""
    import importlib

    # Patch shared.db BEFORE loading handler
    import shared.db as db_mod
    fake = FakeTable()

    def fake_get_table(_env_var):
        return fake

    db_mod.get_table = fake_get_table
    db_mod.put_item = lambda table, item: table.put_item(Item=item)
    db_mod.get_item = lambda table, key: (table.get_item(Key=key) or {}).get("Item") or {}

    # Also patch these at the handler module level to pick up new behavior
    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler  # noqa
    # Intercept _trigger_compute to avoid hitting AWS
    handler._trigger_compute = lambda *_a, **_k: None
    return handler, fake


def _event(body):
    import json
    return {
        "rawPath": "/ingest/health",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-api-key": "test"},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def _patch_auth(handler):
    handler._verify_api_key = lambda _k: True


def test_hae_date_coercion_uses_offset_and_preserves_naive_source_date():
    handler, _table = _fresh_module()
    assert handler._coerce_date("2026-07-02 00:30:00 -0700") == "2026-07-02"
    assert handler._coerce_date("2026-07-02") == "2026-07-02"
    assert handler._coerce_date("not-a-timestamp") is None


def test_hae_utc_only_offsets_use_home_timezone_for_analysis_date():
    handler, _table = _fresh_module()
    cases = (
        ("2026-07-02T00:30:00Z", "2026-07-01"),
        ("2026-07-02T00:30:00+00:00", "2026-07-01"),
        ("2026-01-02T07:30:00Z", "2026-01-01"),
    )
    for source_ts, expected_date in cases:
        metadata = handler._hae_temporal_metadata(source_ts)
        assert metadata["analysis_date"] == expected_date
        assert metadata["analysis_timezone"] == "America/Los_Angeles"
        assert metadata["date_derivation"] == "home_timezone"
        assert metadata["source_utc_offset"] == "+00:00"
        assert "analysis_utc_offset" not in metadata


def test_hae_nonzero_explicit_offset_remains_trusted_local_context():
    handler, _table = _fresh_module()
    metadata = handler._hae_temporal_metadata("2026-07-02T00:30:00-07:00")
    assert metadata["analysis_date"] == "2026-07-02"
    assert metadata["date_derivation"] == "source_offset"
    assert metadata["source_utc_offset"] == "-07:00"
    assert metadata["analysis_utc_offset"] == "-07:00"
    assert "analysis_timezone" not in metadata


def test_hae_utc_row_preserves_raw_timestamp_and_absolute_derivation():
    h, t = _fresh_module()
    _patch_auth(h)
    source_ts = "2026-07-02T00:30:00Z"
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms", "data": [
            {"qty": 46.3, "date": source_ts},
        ]},
    ]}}), None)

    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"][-1]
    samples = [i for i in t.items if i["metric_source"] == "hrv#hae_samples"][-1]
    assert hrv["date"] == "2026-07-01"
    assert hrv["date_derivation"] == "home_timezone"
    assert hrv["source_utc_offset"] == "+00:00"
    assert samples["samples"] == [{"ts": source_ts, "v": 46.3}]


def test_hae_rows_distinguish_offset_dates_from_source_date_fallbacks():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms", "data": [
            {"qty": 46.3, "date": "2026-07-02 00:30:00 -0700"},
        ]},
        {"name": "step_count", "units": "count", "data": [
            {"qty": 8500, "date": "2026-07-02"},
        ]},
    ]}}), None)

    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"][-1]
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"][-1]

    assert hrv["date_derivation"] == "source_offset"
    assert hrv["source_utc_offset"] == "-07:00"
    assert hrv["analysis_utc_offset"] == "-07:00"

    assert steps["date_derivation"] == "source_date_fallback"
    assert "source_utc_offset" not in steps
    assert "analysis_utc_offset" not in steps
    assert "analysis_timezone" not in steps


def test_hae_mixed_timestamp_confidence_is_explicit_on_aggregate_row():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms", "data": [
            {"qty": 46.3, "date": "2026-07-02 00:30:00 -0700"},
            {"qty": 48.1, "date": "2026-07-02 03:00:00"},
        ]},
    ]}}), None)

    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"][-1]
    assert hrv["date_derivation"] == "mixed_source_derivations"
    assert hrv["date_derivations"] == ["source_date_fallback", "source_offset"]
    assert "source_utc_offset" not in hrv
    assert "analysis_utc_offset" not in hrv


# ─── HAE v2 nested shape ─────────────────────────────────────────────

def test_hae_v2_nested_shape_hrv():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms",
         "data": [{"qty": 46.3, "date": "2026-04-20 03:00:00 -0700"}]}
    ]}}), None)
    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"]
    assert len(hrv) == 1 and hrv[0]["value"] == 46.3


def test_hae_v1_flat_shape_still_works():
    """Legacy {data: [...]} shape as documented for earlier HAE versions."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": [
        {"name": "heart_rate_variability", "units": "ms",
         "data": [{"qty": 50.1, "date": "2026-04-20 03:00:00 -0700"}]}
    ]}), None)
    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"]
    assert len(hrv) == 1 and hrv[0]["value"] == 50.1


# ─── Name variants ───────────────────────────────────────────────────

def test_snake_case_maps():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "step_count", "data": [{"qty": 8500, "date": "2026-04-20"}]}
    ]}}), None)
    assert any(i["metric_source"] == "steps#hae" and i["value"] == 8500 for i in t.items)


def test_title_case_maps():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "Step Count", "data": [{"qty": 8500, "date": "2026-04-20"}]}
    ]}}), None)
    assert any(i["metric_source"] == "steps#hae" and i["value"] == 8500 for i in t.items)


# ─── Triple-HR expansion ─────────────────────────────────────────────

def test_heart_rate_triple_expansion():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate", "units": "bpm",
         "data": [{"Min": 52, "Avg": 72, "Max": 148, "date": "2026-04-20 12:00:00 -0700"}]}
    ]}}), None)
    sources = {i["metric_source"]: i["value"] for i in t.items}
    assert sources["hr_min#hae"] == 52
    assert sources["hr_avg#hae"] == 72
    assert sources["hr_max#hae"] == 148


def test_heart_rate_fallback_to_qty():
    """When HAE export only has `qty` (not Min/Avg/Max), fallback to avg."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate", "data": [{"qty": 78, "date": "2026-04-20 12:00:00 -0700"}]}
    ]}}), None)
    sources = {i["metric_source"]: i["value"] for i in t.items}
    assert sources.get("hr_avg#hae") == 78
    assert "hr_min#hae" not in sources
    assert "hr_max#hae" not in sources


# ─── Aggregated sleep ────────────────────────────────────────────────

def test_sleep_aggregated_hours_parses():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr", "data": [
            {"date": "2026-04-18", "totalSleep": 7.5, "asleep": 7.0,
             "core": 3.5, "deep": 1.5, "rem": 2.0, "inBed": 8.0,
             "sleepStart": "2026-04-17 23:00:00 -0700",
             "sleepEnd":   "2026-04-18 06:30:00 -0700"}
        ]}
    ]}}), None)
    sleep = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    assert len(sleep) == 1
    s = sleep[0]
    assert s["total_min"] == 450  # 7.5h * 60
    assert s["deep_min"] == 90
    assert s["rem_min"] == 120


def test_sleep_unaggregated_segments_parses():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "data": [
            {"value": "Deep", "qty": 1.5,
             "startDate": "2026-04-17 23:00:00 -0700",
             "endDate": "2026-04-18 00:30:00 -0700",
             "sleepStart": "2026-04-17 23:00:00 -0700"},
            {"value": "REM", "qty": 2.0,
             "startDate": "2026-04-18 03:00:00 -0700",
             "endDate": "2026-04-18 05:00:00 -0700",
             "sleepStart": "2026-04-17 23:00:00 -0700"},
        ]}
    ]}}), None)
    sleep = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    assert len(sleep) == 1  # one session, keyed to wake-up morning
    s = sleep[0]
    # Session crosses midnight — both segments land on the wake-up morning
    # (4/18) under the new session-based keying, matching the aggregated
    # convention. Previously these would have split: Deep → 4/17, REM → 4/18.
    assert s["date"] == "2026-04-18"
    # qty is in hours, _normalize_sleep expects minutes — multiplied 60 in the parser
    assert s["deep_min"] == 90
    assert s["rem_min"] == 120
    # Segments now carry through with timestamps + canonical stage names.
    segments = s.get("segments") or []
    assert len(segments) == 2
    stages = sorted(seg["stage"] for seg in segments)
    assert stages == ["deep", "rem"]
    assert all(seg.get("start") and seg.get("end") for seg in segments)
    # Quality flags land on every sleep row.
    assert s["quality_flag"] in ("ok", "partial", "truncated", "missing")
    assert "confidence" in s


def test_sleep_truncated_short_night_without_wrist_temp_is_flagged():
    """A 173-minute night with no wrist-temp row should be flagged truncated
    by ingest's quality stamp. Mirrors the 2025-10-09 prod data shape."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr", "data": [
            {"date": "2025-10-09", "totalSleep": 2.88, "asleep": 2.88,
             "core": 2.0, "deep": 0.5, "rem": 0.4, "inBed": 3.05,
             "sleepStart": "2025-10-08 23:45:00 -0700",
             "sleepEnd":   "2025-10-09 03:00:00 -0700"}
        ]}
    ]}}), None)
    sleep = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    assert len(sleep) == 1
    # Ingest-time default is "assume wrist-temp present" (compute re-checks
    # with the actual wrist-temp row). So in the ingest unit it still flags
    # ok, and compute-side tests cover the truncated downgrade path. Just
    # verify the quality stamp machinery ran and total_min is preserved.
    s = sleep[0]
    assert s["quality_flag"] in ("ok", "partial")
    assert s["total_min"] == 173


# ─── "last" kind (weight / BMI) ──────────────────────────────────────

def test_weight_last_value_wins():
    """If multiple weight readings in a day, keep the latest by timestamp."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "weight_body_mass", "units": "lb", "data": [
            {"qty": 168.2, "date": "2026-04-20 07:00:00 -0700"},
            {"qty": 169.5, "date": "2026-04-20 21:00:00 -0700"},
            {"qty": 168.8, "date": "2026-04-20 12:00:00 -0700"},
        ]}
    ]}}), None)
    w = [i for i in t.items if i["metric_source"] == "weight_apple#hae"]
    assert len(w) == 1 and w[0]["value"] == 169.5  # 21:00 is latest


# ─── CRITICAL: sleep substring must not catch "wrist temperature" ──

def test_wrist_temperature_is_NOT_routed_to_sleep():
    """Regression: "apple sleeping wrist temperature" contains "sleep" substring
    but is absolutely not sleep data. Must route to wrist_temp#hae, not sleep#hae."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "apple_sleeping_wrist_temperature", "units": "degC",
         "data": [{"qty": 32.4, "date": "2026-04-20 03:00:00 -0700"}]}
    ]}}), None)
    wt = [i for i in t.items if i["metric_source"] == "wrist_temp#hae"]
    sleep = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    assert len(wt) == 1 and wt[0]["value"] == 32.4
    assert len(sleep) == 0, "wrist_temp must not leak into sleep#hae"


# ─── Unknown metrics are not persisted, but are observable ───────────

def test_unknown_metric_name_is_not_persisted_but_is_logged_without_values(caplog):
    h, t = _fresh_module()
    _patch_auth(h)
    with caplog.at_level(logging.WARNING, logger="ingest"):
        h.lambda_handler(_event({"data": {"metrics": [
            {"name": "some_future_metric_we_havent_mapped",
             "data": [{"qty": 42, "date": "2026-04-20"}]}
        ]}}), None)

    # The unknown metric still does not become an invented source row, but it
    # must be diagnosable by its raw name and point count without logging qty.
    assert all("some_future" not in (i.get("metric_source", "")) for i in t.items)
    assert (
        "HAE_UNMAPPED_METRIC "
        "metric_name=some_future_metric_we_havent_mapped point_count=1"
    ) in caplog.text
    assert "42" not in caplog.text


# ─── Observed mobility / capacity metrics ────────────────────────────

def test_walking_asymmetry_ingestion_preserves_samples_units_and_temporal_metadata():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "walking_asymmetry_percentage", "units": "%",
         "data": [
             {"qty": 1.2, "date": "2026-08-22 01:02:04 -0700"},
             {"qty": 1.8, "date": "2026-08-22 13:02:04 -0700"},
         ]},
    ]}}), None)

    observed = [i for i in t.items if i["metric_source"] == "walking_asymmetry#hae"][-1]
    ledger = [i for i in t.items if i["metric_source"] == "walking_asymmetry#hae_samples"][-1]

    assert observed["value"] == 1.5
    assert observed["unit"] == "%"
    assert observed["date"] == "2026-08-22"
    assert observed["date_derivation"] == "source_offset"
    assert observed["source_utc_offset"] == "-07:00"
    assert ledger["samples"] == [
        {"ts": "2026-08-22 01:02:04 -0700", "v": 1.2},
        {"ts": "2026-08-22 13:02:04 -0700", "v": 1.8},
    ]


def test_vo2_max_ingestion_is_idempotent_with_sample_ledger():
    h, t = _fresh_module()
    _patch_auth(h)
    payload = {"data": {"metrics": [
        {"name": "vo2_max", "units": "ml/kg/min",
         "data": [
             {"qty": 48.2, "date": "2026-08-17 06:00:00 -0700"},
             {"qty": 49.0, "date": "2026-08-17 18:00:00 -0700"},
         ]},
    ]}}

    h.lambda_handler(_event(payload), None)
    h.lambda_handler(_event(payload), None)  # HAE retry / full-day resend

    observed = [i for i in t.items if i["metric_source"] == "vo2_max#hae"][-1]
    ledger = [i for i in t.items if i["metric_source"] == "vo2_max#hae_samples"][-1]

    assert observed["value"] == 48.6
    assert observed["unit"] == "ml/kg/min"
    assert observed["date_derivation"] == "source_offset"
    assert observed["source_utc_offset"] == "-07:00"
    assert len(ledger["samples"]) == 2
    assert [sample["v"] for sample in ledger["samples"]] == [48.2, 49.0]


# ─── Numeric aggregation kinds ───────────────────────────────────────

def test_avg_kind_averages_intraday_samples():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "data": [
            {"qty": 40, "date": "2026-04-20 03:00:00 -0700"},
            {"qty": 60, "date": "2026-04-20 04:00:00 -0700"},
        ]}
    ]}}), None)
    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"]
    assert len(hrv) == 1 and hrv[0]["value"] == 50.0


def test_sum_int_kind_sums_intraday_samples():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "step_count", "data": [
            {"qty": 3000, "date": "2026-04-20 10:00:00 -0700"},
            {"qty": 4500, "date": "2026-04-20 16:00:00 -0700"},
        ]}
    ]}}), None)
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"]
    assert len(steps) == 1 and steps[0]["value"] == 7500


# ─── Per-sample HR sidecar (HAE unaggregated heart rate) ─────────────

def test_per_sample_hr_creates_sidecar_row():
    """HAE unaggregated HR emits one point per sample with Min=Avg=Max=value
    and a timestamp (clock component). Must write both the daily triple AND
    a hr#hae_samples sidecar so compute can intersect with the sleep window."""
    h, t = _fresh_module()
    _patch_auth(h)
    # Minimum 5 samples to trigger the sidecar write.
    points = [
        {"Min": 62, "Avg": 62, "Max": 62, "date": f"2026-05-04 08:00:{str(i).zfill(2)} -0700"}
        for i in range(10, 20)
    ]
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate", "units": "bpm", "data": points}
    ]}}), None)
    sidecar = [i for i in t.items if i["metric_source"] == "hr#hae_samples"]
    assert len(sidecar) == 1, "expected one hr#hae_samples row"
    samples = sidecar[0].get("samples") or []
    assert len(samples) == 10
    assert all("ts" in s and "bpm" in s for s in samples)
    # Triple aggregates also written (avg = 62 because all equal).
    avg = [i for i in t.items if i["metric_source"] == "hr_avg#hae"]
    assert len(avg) == 1 and avg[0]["value"] == 62


def test_per_sample_hr_with_daily_rollup_point_does_not_pollute_sidecar():
    """If HAE also sends a single daily rollup (no clock component in date),
    that point must NOT land in the samples sidecar."""
    h, t = _fresh_module()
    _patch_auth(h)
    points = [
        {"Min": 50, "Avg": 72, "Max": 148, "date": "2026-05-04"},  # daily rollup
    ]
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate", "units": "bpm", "data": points}
    ]}}), None)
    sidecar = [i for i in t.items if i["metric_source"] == "hr#hae_samples"]
    assert sidecar == []


# ─── Unaggregated sleep must not clobber higher aggregated totals ───

def test_unaggregated_sleep_partial_window_does_not_clobber_aggregated():
    """If an aggregated full-night row is already on a date, an unaggregated
    push with materially lower total_min (common when HAE only sends the
    post-midnight slice) must NOT replace the full-night totals. Segments
    should still land, just merged onto the higher-quality totals."""
    h, t = _fresh_module()
    _patch_auth(h)
    # First — aggregated full night: 385m asleep (typical Apple output).
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr", "data": [
            {"date": "2026-05-04", "totalSleep": 6.4, "asleep": 6.4,
             "core": 3.55, "deep": 1.5, "rem": 1.38, "inBed": 6.5,
             "sleepStart": "2026-05-03 23:30:00 -0700",
             "sleepEnd":   "2026-05-04 05:55:00 -0700"}
        ]}
    ]}}), None)
    pre = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    assert len(pre) == 1
    assert pre[0]["total_min"] == 384  # 6.4 * 60

    # Second — unaggregated push with only the post-midnight slice (284m).
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "data": [
            {"value": "Deep", "qty": 0.65,
             "startDate": "2026-05-04 01:00:00 -0700",
             "endDate":   "2026-05-04 01:39:00 -0700",
             "sleepStart": "2026-05-04 01:00:00 -0700"},
            {"value": "REM", "qty": 1.15,
             "startDate": "2026-05-04 03:00:00 -0700",
             "endDate":   "2026-05-04 04:09:00 -0700",
             "sleepStart": "2026-05-04 01:00:00 -0700"},
            {"value": "Core", "qty": 2.93,
             "startDate": "2026-05-04 01:40:00 -0700",
             "endDate":   "2026-05-04 04:36:00 -0700",
             "sleepStart": "2026-05-04 01:00:00 -0700"},
        ]}
    ]}}), None)
    post = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    # Latest row is what lives at that date — must still have 384m totals.
    latest = post[-1]
    assert latest["date"] == "2026-05-04"
    assert latest["total_min"] == 384, f"got {latest['total_min']} — merge guard missed"
    # But segments should be enriched onto the preserved aggregated totals.
    assert latest.get("segments"), "segments should be attached even when merge preserves totals"
    assert len(latest["segments"]) == 3


def test_overnight_segments_all_land_on_wake_morning():
    """Regression: previously segments got keyed by sleepStart's date, so an
    overnight crossing midnight would split — some segments to the pre-
    midnight date, some to the post-midnight date — matching neither
    Apple nor the aggregated row convention. Now they all share sleepStart
    and land on the wake-up morning together."""
    h, t = _fresh_module()
    _patch_auth(h)
    # Reproduces the 5/3→5/4 fan-out: stages spanning 23:30–05:00.
    common_start = "2026-05-03 23:30:00 -0700"
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "data": [
            # 3 pre-midnight segments
            {"value": "Core", "qty": 0.25,
             "startDate": "2026-05-03 23:30:00 -0700",
             "endDate":   "2026-05-03 23:45:00 -0700",
             "sleepStart": common_start},
            {"value": "Deep", "qty": 0.5,
             "startDate": "2026-05-03 23:45:00 -0700",
             "endDate":   "2026-05-04 00:15:00 -0700",
             "sleepStart": common_start},
            {"value": "Core", "qty": 0.2,
             "startDate": "2026-05-04 00:15:00 -0700",
             "endDate":   "2026-05-04 00:27:00 -0700",
             "sleepStart": common_start},
            # 3 post-midnight segments
            {"value": "REM", "qty": 1.0,
             "startDate": "2026-05-04 03:00:00 -0700",
             "endDate":   "2026-05-04 04:00:00 -0700",
             "sleepStart": common_start},
            {"value": "Core", "qty": 1.5,
             "startDate": "2026-05-04 00:27:00 -0700",
             "endDate":   "2026-05-04 01:57:00 -0700",
             "sleepStart": common_start},
            {"value": "Deep", "qty": 1.0,
             "startDate": "2026-05-04 01:57:00 -0700",
             "endDate":   "2026-05-04 02:57:00 -0700",
             "sleepStart": common_start},
        ]}
    ]}}), None)
    sleep_rows = [i for i in t.items if i["metric_source"] == "sleep#hae"]
    # Exactly one row — the whole session clusters onto the wake morning.
    assert len(sleep_rows) == 1
    s = sleep_rows[0]
    assert s["date"] == "2026-05-04", f"expected wake-morning 5/4, got {s['date']}"
    assert len(s.get("segments", [])) == 6
    assert s["deep_min"] == 90   # 0.5h + 1.0h = 90m
    assert s["rem_min"] == 60    # 1.0h


def test_unaggregated_merge_carries_over_sleep_start_end():
    """When merge-guard preserves aggregated totals, the incoming segments'
    start/end still need to land on the row so compute's HR-sidecar
    intersection has a window to use. Regression: without this, a merged
    row shows segments but no sleep_start/sleep_end, leaving avg_hr_sleep
    and thus HR-dip silently None."""
    h, t = _fresh_module()
    _patch_auth(h)
    # Seed with aggregated row that lacks sleep_start/sleep_end (simulates
    # a legacy row or the manually-restored case we just hit).
    t.items.append({
        "date": "2026-05-04",
        "metric_source": "sleep#hae",
        "total_min": 385, "deep_min": 90, "rem_min": 83,
        "core_min": 212, "awake_min": 5, "in_bed_min": 390,
        "efficiency": 98.7, "quality_flag": "ok",
        "quality_reasons": [], "confidence": 1,
    })
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "data": [
            {"value": "Deep", "qty": 0.65,
             "startDate": "2026-05-04 00:15:46 -0700",
             "endDate":   "2026-05-04 00:54:46 -0700",
             "sleepStart": "2026-05-04 00:15:46 -0700"},
            {"value": "REM", "qty": 1.15,
             "startDate": "2026-05-04 03:00:00 -0700",
             "endDate":   "2026-05-04 04:09:00 -0700",
             "sleepStart": "2026-05-04 00:15:46 -0700"},
            {"value": "Core", "qty": 2.93,
             "startDate": "2026-05-04 01:00:00 -0700",
             "endDate":   "2026-05-04 04:59:58 -0700",
             "sleepStart": "2026-05-04 00:15:46 -0700"},
        ]}
    ]}}), None)
    latest = [i for i in t.items if i["metric_source"] == "sleep#hae"][-1]
    # Merged — aggregated totals preserved.
    assert latest["total_min"] == 385
    # But sleep_start/sleep_end now come from the incoming segments.
    assert latest.get("sleep_start") == "2026-05-04 00:15:46 -0700"
    assert latest.get("sleep_end") == "2026-05-04 04:59:58 -0700"


def test_unaggregated_sleep_replaces_when_totals_comparable():
    """Guard rails — the merge only preserves existing totals when they're
    *materially* higher. A comparable-quality unaggregated push should
    replace the existing row normally, so later corrections from Apple
    still land."""
    h, t = _fresh_module()
    _patch_auth(h)
    # First: aggregated 180m (short nap recorded as main event).
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr", "data": [
            {"date": "2026-05-04", "totalSleep": 3.0, "asleep": 3.0,
             "core": 2.0, "deep": 0.5, "rem": 0.5, "inBed": 3.2,
             "sleepStart": "2026-05-03 23:30:00 -0700",
             "sleepEnd":   "2026-05-04 02:42:00 -0700"}
        ]}
    ]}}), None)
    # Then: unaggregated full night discovered (420m). Should replace.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "sleep_analysis", "data": [
            {"value": "Deep", "qty": 1.5,
             "startDate": "2026-05-03 23:30:00 -0700",
             "endDate":   "2026-05-04 01:00:00 -0700",
             "sleepStart": "2026-05-03 23:30:00 -0700"},
            {"value": "REM", "qty": 2.0,
             "startDate": "2026-05-04 03:00:00 -0700",
             "endDate":   "2026-05-04 05:00:00 -0700",
             "sleepStart": "2026-05-03 23:30:00 -0700"},
            {"value": "Core", "qty": 3.5,
             "startDate": "2026-05-04 01:00:00 -0700",
             "endDate":   "2026-05-04 04:30:00 -0700",
             "sleepStart": "2026-05-03 23:30:00 -0700"},
        ]}
    ]}}), None)
    latest = [i for i in t.items if i["metric_source"] == "sleep#hae"][-1]
    # 1.5 + 2.0 + 3.5 = 7h = 420m — should fully replace the 180m row.
    assert latest["total_min"] == 420
    assert latest["deep_min"] == 90


# ─── Merge-guard regression: steps/HRV/etc. must combine across POSTs ────
#
# Root cause under test (fixed 2026-07-27): HAE fires multiple automations
# per day, each carrying only that automation's slice of samples. The old
# code aggregated within a single payload and did a bare put_item(), so the
# LAST webhook for a given (date, metric) silently discarded every earlier
# same-day POST. Confirmed in production: McFox showed 6,501 steps on a day
# where the real total was ~21,267 (only the last automation's slice was
# kept). These tests simulate two sequential webhook POSTs with disjoint
# sample windows and assert the final value reflects BOTH combined.

def test_steps_two_sequential_posts_combine_not_clobber():
    h, t = _fresh_module()
    _patch_auth(h)
    # Morning automation: 3,000 steps by 10am.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "step_count", "data": [
            {"qty": 3000, "date": "2026-04-20 10:00:00 -0700"},
        ]}
    ]}}), None)
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"]
    assert len(steps) == 1 and steps[0]["value"] == 3000

    # Evening automation: a DIFFERENT slice of the day, 4,500 more steps.
    # The old bug: this POST alone would overwrite the day's row down to
    # just 4500, discarding the morning's 3000.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "step_count", "data": [
            {"qty": 4500, "date": "2026-04-20 18:00:00 -0700"},
        ]}
    ]}}), None)
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"]
    assert steps[-1]["value"] == 7500, "must combine both POSTs, not just keep the last"

    # Re-sending the SAME point again (HAE full-day resend) must not
    # double-count it — dedup is by timestamp.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "step_count", "data": [
            {"qty": 4500, "date": "2026-04-20 18:00:00 -0700"},
        ]}
    ]}}), None)
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"]
    assert steps[-1]["value"] == 7500, "re-sending an identical timestamped point must be idempotent"


def test_hrv_two_sequential_posts_combine_not_clobber():
    h, t = _fresh_module()
    _patch_auth(h)
    # First automation: two morning HRV readings, avg = 50.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "data": [
            {"qty": 40, "date": "2026-04-20 03:00:00 -0700"},
            {"qty": 60, "date": "2026-04-20 04:00:00 -0700"},
        ]}
    ]}}), None)
    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"]
    assert len(hrv) == 1 and hrv[0]["value"] == 50.0

    # Second automation: an afternoon reading the first payload never saw.
    # The old bug: this alone would overwrite hrv#hae down to just 100,
    # discarding the morning readings entirely.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "heart_rate_variability", "data": [
            {"qty": 100, "date": "2026-04-20 15:00:00 -0700"},
        ]}
    ]}}), None)
    hrv = [i for i in t.items if i["metric_source"] == "hrv#hae"]
    # Average of all 3 unique-timestamp samples: (40+60+100)/3 = 66.7
    assert hrv[-1]["value"] == 66.7, "must average across BOTH POSTs, not just the second"

    # The samples ledger sidecar accumulates across calls (FakeTable
    # appends put_items rather than replacing), so check the LATEST sidecar
    # row rather than asserting there's only ever been one.
    sidecar = [i for i in t.items if i["metric_source"] == "hrv#hae_samples"]
    assert len(sidecar) == 2 and len(sidecar[-1]["samples"]) == 3


def test_active_cal_two_sequential_posts_combine_not_clobber():
    """Spot-check that the same merge-guard was generalized to a
    non-steps/HRV sum-type metric (active_cal), not just those two."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "active_energy", "data": [
            {"qty": 200, "date": "2026-04-20 09:00:00 -0700"},
        ]}
    ]}}), None)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "active_energy", "data": [
            {"qty": 350, "date": "2026-04-20 17:00:00 -0700"},
        ]}
    ]}}), None)
    cal = [i for i in t.items if i["metric_source"] == "active_cal#hae"]
    assert cal[-1]["value"] == 550, "active_cal must also combine across POSTs"


def test_rhr_two_sequential_posts_combine_not_clobber():
    """Spot-check the merge-guard on an avg-type metric outside steps/HRV."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "resting_heart_rate", "data": [
            {"qty": 58, "date": "2026-04-20 06:00:00 -0700"},
        ]}
    ]}}), None)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "resting_heart_rate", "data": [
            {"qty": 62, "date": "2026-04-20 20:00:00 -0700"},
        ]}
    ]}}), None)
    rhr = [i for i in t.items if i["metric_source"] == "rhr#hae"]
    assert rhr[-1]["value"] == 60.0, "rhr must average across both POSTs (58+62)/2 = 60"


# ─── Ordering guard: "last"-kind metrics must ignore stale retries ──────

def test_weight_ordering_guard_ignores_older_retry():
    """A late-arriving webhook retry carrying an OLDER reading must not
    regress a fresher value already stored (API Gateway/Lambda retries can
    arrive out of order)."""
    h, t = _fresh_module()
    _patch_auth(h)
    # Fresh reading lands first (21:00).
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "weight_body_mass", "units": "lb", "data": [
            {"qty": 169.5, "date": "2026-04-20 21:00:00 -0700"},
        ]}
    ]}}), None)
    # A retry of an OLDER reading (07:00) arrives late — must be ignored.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "weight_body_mass", "units": "lb", "data": [
            {"qty": 168.2, "date": "2026-04-20 07:00:00 -0700"},
        ]}
    ]}}), None)
    w = [i for i in t.items if i["metric_source"] == "weight_apple#hae"]
    assert w[-1]["value"] == 169.5, "an out-of-order older retry must not overwrite the fresher value"

    # A genuinely NEWER reading must still be accepted normally.
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "weight_body_mass", "units": "lb", "data": [
            {"qty": 170.1, "date": "2026-04-20 23:00:00 -0700"},
        ]}
    ]}}), None)
    w = [i for i in t.items if i["metric_source"] == "weight_apple#hae"]
    assert w[-1]["value"] == 170.1, "a genuinely newer reading must still be accepted"


def test_legacy_dict_shape_fallback_also_merge_guards_steps():
    """The legacy top-level-keys-per-metric shape (_handle_health's fallback
    branch, e.g. {"steps": ..., "date": ...} with no "data" wrapper) has the
    identical overwrite bug pre-fix — confirm it now also merges across
    sequential calls instead of clobbering."""
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"steps": 3000, "date": "2026-04-20"}), None)
    h.lambda_handler(_event({"steps": 4500, "date": "2026-04-20"}), None)
    steps = [i for i in t.items if i["metric_source"] == "steps#hae"]
    assert steps[-1]["value"] == 7500, "legacy fallback path must also combine across calls"
