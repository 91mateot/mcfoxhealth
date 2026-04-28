"""Unit tests for shared.lift_compute (Epley e1RM, PR detection, stalls).

Extra test confirms retroactive history ordering: a back-filled old session
correctly beats later sessions' PR flags when its numbers were higher."""
import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.lift_compute as lc
    return lc


def test_epley_e1rm(monkeypatch):
    lc = _load_module(monkeypatch)
    assert lc.epley_e1rm(0, 5) == 0.0
    assert lc.epley_e1rm(100, 0) == 0.0
    assert lc.epley_e1rm(225, 1) == 225.0
    assert lc.epley_e1rm(205, 5) == pytest.approx(239.2, abs=0.1)
    assert lc.epley_e1rm(315, 3) == pytest.approx(346.5, abs=0.1)


def test_session_top_e1rm_skips_warmups(monkeypatch):
    lc = _load_module(monkeypatch)
    row = {
        "sets": [
            {"reps": 10, "weight": 95, "warmup": True},
            {"reps": 5, "weight": 205},
            {"reps": 3, "weight": 225},
        ]
    }
    assert lc.session_top_e1rm(row) == pytest.approx(247.5, abs=0.1)


def test_detect_prs_strict_greater_than(monkeypatch):
    lc = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-01", "top_weight": 200, "working_volume": 1000,
         "sets": [{"reps": 5, "weight": 200}]},
        {"date": "2026-04-08", "top_weight": 200, "working_volume": 1000,
         "sets": [{"reps": 5, "weight": 200}]},
        {"date": "2026-04-15", "top_weight": 205, "working_volume": 1025,
         "sets": [{"reps": 5, "weight": 205}]},
    ]
    flags = lc.detect_prs(history)
    assert flags["2026-04-01"] == {"weight": True, "e1rm": True, "volume": True}
    assert flags["2026-04-08"] == {"weight": False, "e1rm": False, "volume": False}
    assert flags["2026-04-15"] == {"weight": True, "e1rm": True, "volume": True}


def test_detect_prs_retroactive_old_session_demotes_newer(monkeypatch):
    """Backfill scenario: Mateo annotates an older session that beats a newer
    one. After re-sorting history ascending-by-date, the old session should
    be a PR and the newer one should lose its flag."""
    lc = _load_module(monkeypatch)
    # History, as passed to detect_prs: must already be sorted ascending by date.
    history = [
        # Backfilled — heavy 215 session from earlier in the month.
        {"date": "2026-04-01", "top_weight": 215, "working_volume": 1075,
         "sets": [{"reps": 5, "weight": 215}]},
        # Logged first last week at 205 — was the PR before backfill.
        {"date": "2026-04-15", "top_weight": 205, "working_volume": 1025,
         "sets": [{"reps": 5, "weight": 205}]},
    ]
    flags = lc.detect_prs(history)
    # Old backfilled 215 is the true PR.
    assert flags["2026-04-01"] == {"weight": True, "e1rm": True, "volume": True}
    # Newer 205 was lower than the 215 that came before it chronologically.
    assert flags["2026-04-15"] == {"weight": False, "e1rm": False, "volume": False}


def test_detect_stall_exactly_three_sessions_flat(monkeypatch):
    lc = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 10},
    ]
    stall = lc.detect_stall(history)
    assert stall is not None
    assert stall["weight"] == 140
    assert stall["sessions"] == 3


def test_detect_stall_rejects_progression(monkeypatch):
    lc = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 145, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 145, "top_reps_at_top_weight": 10},
    ]
    assert lc.detect_stall(history) is None


def test_detect_stall_needs_minimum_sessions(monkeypatch):
    lc = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 10},
    ]
    assert lc.detect_stall(history) is None


def test_detect_stall_rejects_wide_rep_range(monkeypatch):
    lc = _load_module(monkeypatch)
    history = [
        {"date": "2026-04-08", "top_weight": 140, "top_reps_at_top_weight": 10},
        {"date": "2026-04-15", "top_weight": 140, "top_reps_at_top_weight": 5},
        {"date": "2026-04-22", "top_weight": 140, "top_reps_at_top_weight": 12},
    ]
    assert lc.detect_stall(history) is None
