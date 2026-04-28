"""Unit tests for the lift compute helpers (Epley e1RM, PR detection, stalls).

Loads functions/compute/handler.py as a distinct module (`compute_handler`)
via importlib so it doesn't collide with other function handlers when pytest
runs the full suite."""
import importlib.util
import os
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(ROOT, "functions", "compute", "handler.py")
    spec = importlib.util.spec_from_file_location("compute_handler", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_epley_e1rm(monkeypatch):
    h = _load_module(monkeypatch)
    # Base cases
    assert h._epley_e1rm(0, 5) == 0.0
    assert h._epley_e1rm(100, 0) == 0.0
    assert h._epley_e1rm(225, 1) == 225.0  # Single = no adjustment.
    # 205 x 5 → 205 * (1 + 5/30) = 205 * 1.1667 = 239.2
    assert h._epley_e1rm(205, 5) == pytest.approx(239.2, abs=0.1)
    # 315 x 3 → 315 * 1.1 = 346.5
    assert h._epley_e1rm(315, 3) == pytest.approx(346.5, abs=0.1)


def test_session_top_e1rm_skips_warmups(monkeypatch):
    h = _load_module(monkeypatch)
    row = {
        "sets": [
            {"reps": 10, "weight": 95, "warmup": True},   # ignored
            {"reps": 5, "weight": 205},                    # e1rm 239.2
            {"reps": 3, "weight": 225},                    # e1rm 247.5 → top
        ]
    }
    assert h._session_top_e1rm(row) == pytest.approx(247.5, abs=0.1)


def test_detect_prs_strict_greater_than(monkeypatch):
    h = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-01", "top_weight": 200, "working_volume": 1000,
         "sets": [{"reps": 5, "weight": 200}]},
        # Same weight, different day — NOT a PR.
        {"date": "2026-04-08", "top_weight": 200, "working_volume": 1000,
         "sets": [{"reps": 5, "weight": 200}]},
        # Weight goes up.
        {"date": "2026-04-15", "top_weight": 205, "working_volume": 1025,
         "sets": [{"reps": 5, "weight": 205}]},
    ]
    flags = h._detect_prs(history)
    assert flags["2026-04-01"] == {"weight": True, "e1rm": True, "volume": True}  # First → all PRs
    assert flags["2026-04-08"] == {"weight": False, "e1rm": False, "volume": False}
    assert flags["2026-04-15"] == {"weight": True, "e1rm": True, "volume": True}


def test_detect_stall_exactly_three_sessions_flat(monkeypatch):
    h = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 10},
    ]
    stall = h._detect_stall(history)
    assert stall is not None
    assert stall["weight"] == 140
    assert stall["sessions"] == 3


def test_detect_stall_rejects_progression(monkeypatch):
    h = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 145, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 145, "top_reps_at_top_weight": 10},
    ]
    # Weight went up in tail, not a stall.
    assert h._detect_stall(history) is None


def test_detect_stall_needs_minimum_sessions(monkeypatch):
    h = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 10},
    ]
    assert h._detect_stall(history) is None


def test_detect_stall_rejects_wide_rep_range(monkeypatch):
    h = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 5},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 12},
    ]
    # Rep spread is 12-5 = 7 > 2, so different rep schemes — not a pure stall.
    assert h._detect_stall(history) is None
