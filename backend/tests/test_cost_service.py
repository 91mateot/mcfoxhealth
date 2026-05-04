"""Unit tests for the infra-cost service.

Covers:
- compute_costs shapes CE response into month-to-date + trailing-4-week
- MTD breakdown collapses services beyond the top-N into "other"
- Weekly buckets are Monday-anchored and cover exactly 4 weeks
- get_costs returns a cached payload inside the TTL window, refreshes after
- Stale fallback when a fresh CE call fails but a prior cache exists
"""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(boto3, "resource", lambda *a, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.cost_service as cs
    return cs


def _pin_now(monkeypatch, cs, dt: datetime):
    monkeypatch.setattr(cs, "_now_utc", lambda: dt.replace(tzinfo=timezone.utc))


def _stub_ce(cs, responses: list, capture: list | None = None):
    """Queue up CE responses; each call to get_cost_and_usage pops the next.
    Optionally records the kwargs each call was made with (for filter asserts)."""
    client = MagicMock()
    calls = {"i": 0}

    def fake_get(**kwargs):
        if capture is not None:
            capture.append(kwargs)
        i = calls["i"]
        calls["i"] += 1
        return responses[i]

    client.get_cost_and_usage.side_effect = fake_get
    cs._ce_client = client


def _monthly_row(period_start, period_end, services):
    return {
        "TimePeriod": {"Start": period_start, "End": period_end},
        "Groups": [
            {"Keys": [name], "Metrics": {"UnblendedCost": {"Amount": str(amt), "Unit": "USD"}}}
            for name, amt in services.items()
        ],
    }


def test_compute_costs_mtd_breakdown(monkeypatch):
    cs = _load_module(monkeypatch)
    _pin_now(monkeypatch, cs, datetime(2026, 5, 15, 12, 0, 0))

    mtd = {"ResultsByTime": [_monthly_row("2026-05-01", "2026-05-16", {
        "AWS Lambda": 1.23,
        "Amazon DynamoDB": 0.45,
        "Amazon Bedrock": 4.56,
    })]}
    daily = {"ResultsByTime": []}  # Empty weekly is fine; just exercising shapes.
    captured: list = []
    _stub_ce(cs, [mtd, daily], capture=captured)

    out = cs.compute_costs()
    assert out["month_to_date"]["period_start"] == "2026-05-01"
    assert out["month_to_date"]["total"] == pytest.approx(6.24)
    services = [b["service"] for b in out["month_to_date"]["breakdown"]]
    assert services == ["Bedrock", "Lambda", "DynamoDB"]

    # Both calls should be service-filtered so co-tenant workloads don't pollute.
    for call in captured:
        filt = call.get("Filter", {}).get("Dimensions", {})
        assert filt.get("Key") == "SERVICE"
        assert "AWS Lambda" in filt.get("Values", [])
        assert "Amazon Bedrock" in filt.get("Values", [])


def test_compute_costs_tail_bucketed_into_other(monkeypatch):
    cs = _load_module(monkeypatch)
    _pin_now(monkeypatch, cs, datetime(2026, 5, 15, tzinfo=None))

    # 8 services — expect top 6 kept, remaining 2 rolled into "other".
    services = {f"Svc{i}": 1.0 + i * 0.1 for i in range(8)}
    mtd = {"ResultsByTime": [_monthly_row("2026-05-01", "2026-05-16", services)]}
    _stub_ce(cs, [mtd, {"ResultsByTime": []}])

    out = cs.compute_costs()
    breakdown = out["month_to_date"]["breakdown"]
    assert len(breakdown) == 7  # top 6 + "other"
    assert breakdown[-1]["service"] == "other"


def test_compute_costs_weekly_has_four_buckets(monkeypatch):
    cs = _load_module(monkeypatch)
    # Wed 2026-05-13 → current week Monday = 2026-05-11.
    _pin_now(monkeypatch, cs, datetime(2026, 5, 13))

    daily = {"ResultsByTime": [
        _monthly_row("2026-04-28", "2026-04-29", {"AWS Lambda": 0.10}),
        _monthly_row("2026-05-05", "2026-05-06", {"AWS Lambda": 0.20}),
        _monthly_row("2026-05-12", "2026-05-13", {"AWS Lambda": 0.30}),
    ]}
    _stub_ce(cs, [{"ResultsByTime": []}, daily])

    out = cs.compute_costs()
    assert len(out["weekly"]) == 4
    week_starts = [w["week_start"] for w in out["weekly"]]
    assert week_starts == ["2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11"]
    # 0.10 falls in week starting 2026-04-27 (Mon 4/27 – Sun 5/3).
    totals = {w["week_start"]: w["total"] for w in out["weekly"]}
    assert totals["2026-04-27"] == pytest.approx(0.10)
    assert totals["2026-05-04"] == pytest.approx(0.20)
    assert totals["2026-05-11"] == pytest.approx(0.30)
    assert totals["2026-04-20"] == 0


def test_get_costs_uses_cache_within_ttl(monkeypatch):
    cs = _load_module(monkeypatch)
    _pin_now(monkeypatch, cs, datetime(2026, 5, 15, 12, 0, 0))

    cache_store = {
        ("infra_cost_cache",): {
            "key": "infra_cost_cache",
            "payload": {"month_to_date": {"total": 1.0}, "weekly": [], "computed_at": "x"},
            "fetched_at_epoch": int(datetime(2026, 5, 15, 11, 0, 0, tzinfo=timezone.utc).timestamp()),
        }
    }
    fake_table = MagicMock()
    monkeypatch.setattr(cs, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(cs, "get_item", lambda _t, key: cache_store.get((key["key"],)))
    monkeypatch.setattr(cs, "put_item", lambda _t, item: cache_store.__setitem__((item["key"],), item))

    # No CE call needed; the stub would blow up if invoked.
    cs._ce_client = MagicMock(side_effect=AssertionError("should not hit CE"))
    out = cs.get_costs()
    assert out["cached"] is True
    assert out["month_to_date"]["total"] == 1.0


def test_get_costs_refetches_when_cache_expires(monkeypatch):
    cs = _load_module(monkeypatch)
    _pin_now(monkeypatch, cs, datetime(2026, 5, 15, 12, 0, 0))

    cache_store = {
        ("infra_cost_cache",): {
            "key": "infra_cost_cache",
            "payload": {"month_to_date": {"total": 1.0}, "weekly": [], "computed_at": "x"},
            # 7 hours ago — past the 6h TTL.
            "fetched_at_epoch": int(datetime(2026, 5, 15, 5, 0, 0, tzinfo=timezone.utc).timestamp()),
        }
    }
    fake_table = MagicMock()
    monkeypatch.setattr(cs, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(cs, "get_item", lambda _t, key: cache_store.get((key["key"],)))
    monkeypatch.setattr(cs, "put_item", lambda _t, item: cache_store.__setitem__((item["key"],), item))

    mtd = {"ResultsByTime": [_monthly_row("2026-05-01", "2026-05-16", {"AWS Lambda": 2.0})]}
    _stub_ce(cs, [mtd, {"ResultsByTime": []}])

    out = cs.get_costs()
    assert out["cached"] is False
    assert out["month_to_date"]["total"] == pytest.approx(2.0)


def test_get_costs_stale_fallback_on_ce_error(monkeypatch):
    cs = _load_module(monkeypatch)
    _pin_now(monkeypatch, cs, datetime(2026, 5, 15, 12, 0, 0))

    cache_store = {
        ("infra_cost_cache",): {
            "key": "infra_cost_cache",
            "payload": {"month_to_date": {"total": 1.0}, "weekly": [], "computed_at": "x"},
            "fetched_at_epoch": int(datetime(2026, 5, 15, 5, 0, 0, tzinfo=timezone.utc).timestamp()),
        }
    }
    fake_table = MagicMock()
    monkeypatch.setattr(cs, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(cs, "get_item", lambda _t, key: cache_store.get((key["key"],)))
    monkeypatch.setattr(cs, "put_item", lambda _t, item: cache_store.__setitem__((item["key"],), item))

    client = MagicMock()
    client.get_cost_and_usage.side_effect = RuntimeError("CE unavailable")
    cs._ce_client = client

    out = cs.get_costs()
    assert out["stale"] is True
    assert out["cached"] is True
    assert out["month_to_date"]["total"] == 1.0
