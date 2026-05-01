"""Unit tests for the numeric-correlations compute path.

Scope:
  - Pearson r sign/strength on synthetic monotonic data
  - Next-day lag alignment (caffeine day N → sleep night N; protein day N → HRV day N+1)
  - CorrelationsTable write shape (kind="numeric", points length == n, insight populated)
"""
import os
import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "resource", lambda name, **kw: MagicMock())
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    os.environ.setdefault("DAILY_SCORES_TABLE", "test-daily-scores")
    os.environ.setdefault("CORRELATIONS_TABLE", "test-correlations")
    os.environ.setdefault("JOURNAL_TABLE", "test-journal")
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    # Also drop any cached handler import.
    sys.modules.pop("handler", None)
    # Add the compute handler path so we can import it directly.
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    sys.path.insert(0, os.path.join(root, "functions", "compute"))
    import handler as h
    return h


# ─── Pearson helper — pure math ──────────────────────────────────────


def test_pearson_r_perfect_positive():
    from shared.pearson import pearson_r
    xs = [1, 2, 3, 4, 5]
    ys = [2, 4, 6, 8, 10]
    assert pearson_r(xs, ys) == pytest.approx(1.0, abs=1e-9)


def test_pearson_r_perfect_negative():
    from shared.pearson import pearson_r
    xs = [1, 2, 3, 4, 5]
    ys = [10, 8, 6, 4, 2]
    assert pearson_r(xs, ys) == pytest.approx(-1.0, abs=1e-9)


def test_pearson_r_zero_variance_returns_none():
    from shared.pearson import pearson_r
    assert pearson_r([1, 1, 1], [2, 3, 4]) is None
    assert pearson_r([1, 2, 3], [5, 5, 5]) is None


def test_pearson_r_known_value():
    """Compare against a manually computed reference (r = 0.8728...)."""
    from shared.pearson import pearson_r
    xs = [1, 2, 3, 4, 5, 6]
    ys = [2, 1, 4, 3, 6, 5]
    # Computed offline: r ≈ 0.8285714
    assert pearson_r(xs, ys) == pytest.approx(0.8285714, abs=1e-4)


def test_linreg_slope_intercept():
    from shared.pearson import linreg
    xs = [0, 1, 2, 3, 4]
    ys = [1, 3, 5, 7, 9]  # y = 2x + 1
    slope, intercept = linreg(xs, ys)
    assert slope == pytest.approx(2.0, abs=1e-9)
    assert intercept == pytest.approx(1.0, abs=1e-9)


# ─── Numeric-compute path — fixture-driven ───────────────────────────


def _fixture_scores(n_days=70, caffeine_sleep_coupling=True, protein_next_hrv=True):
    """Build a fake 70-day DailyScores dataset keyed by YYYY-MM-DD.

    Day index 0 is the most-recent day (today-ish); the compute path walks
    from i=0 back to i=window-1 using `today - (i+1)` days.

    Couples:
      caffeine_mg vs sleep_score (same day, negative)
      protein_total vs next-day hrv (positive)
    """
    from datetime import datetime, timedelta
    # Anchor "today" mid-window so next-day lookups resolve for every input day.
    today = datetime(2026, 5, 1)
    rows = {}
    for i in range(n_days):
        d = (today - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        caffeine = 50 + (i * 7) % 300  # 50..~350 mg
        protein = 100 + (i * 13) % 120  # 100..~220 g
        sleep_score = 95 - (caffeine / 10) if caffeine_sleep_coupling else 80  # strong negative coupling
        hrv_today = 45 + (i * 3) % 20
        rows[d] = {
            "date": d,
            "caffeine_total": caffeine,
            "protein_total": protein,
            "water_oz": 60 + (i % 40),
            "strain": 8 + (i % 7),
            "sleep_score": sleep_score,
            "sleep": {"total_min": 420 + (i % 60), "deep_min": 80, "rem_min": 90},
            "hrv": hrv_today,
            "recovery": 60 + (i % 30),
        }
    # Second pass: couple HRV on day d to the *previous* day's protein so the
    # next-day-lag pair (protein day N → HRV day N+1) registers a strong r.
    sorted_days = sorted(rows.keys())
    if protein_next_hrv:
        for i, d in enumerate(sorted_days):
            if i == 0:
                continue
            prev_protein = rows[sorted_days[i - 1]]["protein_total"]
            # Linear coupling: higher protein yesterday → higher HRV today.
            rows[d]["hrv"] = 30 + prev_protein * 0.12
    return rows


def test_numeric_compute_writes_expected_rows(monkeypatch):
    """Wire fake DynamoDB tables and assert write shapes + stat signs."""
    h = _load_module(monkeypatch)

    rows = _fixture_scores()
    writes: list[dict] = []

    fake_scores = MagicMock()
    fake_scores.get_item = lambda Key: {"Item": rows[Key["date"]]} if Key["date"] in rows else {}

    fake_corr = MagicMock()
    def _put(Item):
        writes.append(Item)
    fake_corr.put_item = lambda Item: _put(Item)

    def _get_table(env_var):
        if env_var == "DAILY_SCORES_TABLE":
            return fake_scores
        if env_var == "CORRELATIONS_TABLE":
            return fake_corr
        return MagicMock()

    monkeypatch.setattr(h, "get_table", _get_table)

    # Pin "now" to the same anchor the fixture used so the 60-day walk hits it.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    anchor = datetime(2026, 5, 1, tzinfo=ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(h, "local_now", lambda: anchor)

    result = h._compute_numeric_correlations()

    assert result["status"] == "numeric_correlations_computed"
    assert result["count"] >= 5, f"expected multiple pairs, got {result['count']}"

    # Every write should carry kind="numeric" and match the prefix convention.
    for item in writes:
        assert item["kind"] == "numeric"
        assert item["tag"].startswith("numeric:")
        assert isinstance(item["points"], list)
        assert len(item["points"]) == item["n"]
        assert item["insight"]
        assert item["window_days"] == 60

    # Find the caffeine → sleep_score row and confirm strongly negative r.
    caf_sleep = [i for i in writes if i["tag"] == "numeric:caffeine_mg" and i["metric"] == "sleep_score"]
    assert caf_sleep, "expected caffeine_mg → sleep_score pair to be written"
    assert caf_sleep[0]["r"] < -0.9, f"expected strong negative r, got {caf_sleep[0]['r']}"

    # Find the protein → next-day hrv row and confirm strongly positive r.
    pro_hrv = [i for i in writes if i["tag"] == "numeric:protein_total" and i["metric"] == "hrv"]
    assert pro_hrv, "expected protein_total → hrv pair to be written"
    assert pro_hrv[0]["lag_days"] == 1
    assert pro_hrv[0]["r"] > 0.9, f"expected strong positive r, got {pro_hrv[0]['r']}"


def test_numeric_compute_skips_pairs_below_min_n(monkeypatch):
    """Only ~5 days of data → nothing gets written."""
    h = _load_module(monkeypatch)

    rows = _fixture_scores(n_days=5)
    writes = []

    fake_scores = MagicMock()
    fake_scores.get_item = lambda Key: {"Item": rows[Key["date"]]} if Key["date"] in rows else {}
    fake_corr = MagicMock()
    fake_corr.put_item = lambda Item: writes.append(Item)

    def _get_table(env_var):
        if env_var == "DAILY_SCORES_TABLE":
            return fake_scores
        if env_var == "CORRELATIONS_TABLE":
            return fake_corr
        return MagicMock()
    monkeypatch.setattr(h, "get_table", _get_table)

    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(h, "local_now", lambda: datetime(2026, 5, 1, tzinfo=ZoneInfo("America/Los_Angeles")))

    result = h._compute_numeric_correlations()
    assert result["count"] == 0
    assert writes == []
