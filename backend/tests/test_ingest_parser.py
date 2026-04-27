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
    assert len(sleep) == 1  # grouped by sleepStart's date
    s = sleep[0]
    # qty is in hours, _normalize_sleep expects minutes — multiplied 60 in the parser
    assert s["deep_min"] == 90
    assert s["rem_min"] == 120


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


# ─── Unknown metrics are silently ignored ────────────────────────────

def test_unknown_metric_name_is_ignored():
    h, t = _fresh_module()
    _patch_auth(h)
    h.lambda_handler(_event({"data": {"metrics": [
        {"name": "some_future_metric_we_havent_mapped",
         "data": [{"qty": 42, "date": "2026-04-20"}]}
    ]}}), None)
    # No rows written for the unmapped metric; handler returned 200
    assert all("some_future" not in (i.get("metric_source", "")) for i in t.items)


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
