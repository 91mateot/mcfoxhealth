"""Unit tests for nutrition_service.save_meal behavior around barcode sourcing.

Barcode-sourced meals (OpenFoodFacts lookup) should:
  1. Stamp validated_at + validated_source='openfoodfacts' at save time, so the
     UI's "Validated ✓" chip renders immediately without waiting for async
     audit.
  2. NOT fire the fire-and-forget Lambda validator invoke — the data is
     already canonical per-serving, and the USDA per-100g path can regress
     accurate numbers.

Non-barcode sources (llm, known_foods) should keep the existing behavior:
no validated_* stamps at save, validator invoke fires.
"""
import sys
from unittest.mock import MagicMock

import pytest


def _load_module(monkeypatch):
    """Stub boto3 and import shared.nutrition_service fresh."""
    import boto3
    monkeypatch.setattr(boto3, "client", lambda name, **kw: MagicMock())
    for mod_name in [m for m in list(sys.modules) if m == "shared" or m.startswith("shared.")]:
        sys.modules.pop(mod_name, None)
    import shared.nutrition_service as ns
    return ns


def _wire_fakes(monkeypatch, ns, invoke_calls, put_calls):
    """Point get_table/put_item/query_items at in-memory fakes and capture
    every lambda_client.invoke call."""
    fake_table = MagicMock()
    fake_lambda = MagicMock()

    def fake_invoke(**kwargs):
        invoke_calls.append(kwargs)
        return {}

    fake_lambda.invoke = fake_invoke

    monkeypatch.setattr(ns, "get_table", lambda _env: fake_table)
    monkeypatch.setattr(ns, "put_item", lambda _t, item: put_calls.append(item))
    monkeypatch.setattr(ns, "query_items", lambda *_a, **_k: [])
    monkeypatch.setattr(ns, "lambda_client", fake_lambda)
    # Ensure the validator-invoke code path is enabled (only fires when this
    # env var is truthy; real deploy sets it, tests must mimic).
    monkeypatch.setattr(ns, "NUTRITION_FUNCTION_NAME", "test-NutritionFunction")
    return fake_table, fake_lambda


def test_barcode_source_stamps_validated_and_skips_validator(monkeypatch):
    ns = _load_module(monkeypatch)
    invoke_calls: list = []
    put_calls: list = []
    _wire_fakes(monkeypatch, ns, invoke_calls, put_calls)

    result = ns.save_meal({
        "name": "Kirkland PB Protein Bar",
        "cal": 190, "p": 21, "c": 22, "f": 7,
        "tag": "snack",
        "source": "barcode",
    }, date="2026-04-28")

    # The meal row is in put_calls; filter out water companions.
    meal_rows = [p for p in put_calls if p.get("meal_id", "").startswith("meal_")]
    assert len(meal_rows) == 1
    row = meal_rows[0]
    assert row["source"] == "barcode"
    # Barcode meals are pre-validated — no async audit needed.
    assert row["validated_source"] == "openfoodfacts"
    assert row["validated_at"], "expected validated_at stamp"

    # Validator Lambda must NOT have been invoked.
    assert invoke_calls == [], f"validator should be skipped; got {invoke_calls}"

    # save_meal returns the saved item in result["meal"].
    assert result["meal"]["source"] == "barcode"


def test_llm_source_fires_validator_and_omits_validated_stamp(monkeypatch):
    ns = _load_module(monkeypatch)
    invoke_calls: list = []
    put_calls: list = []
    _wire_fakes(monkeypatch, ns, invoke_calls, put_calls)

    ns.save_meal({
        "name": "grilled chicken bowl",
        "cal": 450, "p": 40, "c": 30, "f": 15,
        "tag": "lunch",
        "source": "llm",
    }, date="2026-04-28")

    meal_rows = [p for p in put_calls if p.get("meal_id", "").startswith("meal_")]
    row = meal_rows[0]
    assert row["source"] == "llm"
    # No at-save validation for LLM-sourced — that's the async path's job.
    assert "validated_source" not in row
    assert "validated_at" not in row

    # Validator Lambda SHOULD have been invoked for LLM source.
    assert len(invoke_calls) == 1
    call = invoke_calls[0]
    assert call["FunctionName"] == "test-NutritionFunction"
    assert call["InvocationType"] == "Event"


def test_label_photo_source_stamps_validated_and_skips_validator(monkeypatch):
    ns = _load_module(monkeypatch)
    invoke_calls: list = []
    put_calls: list = []
    _wire_fakes(monkeypatch, ns, invoke_calls, put_calls)

    result = ns.save_meal({
        "name": "Clif Bar — Chocolate Chip",
        "cal": 250, "p": 10, "c": 44, "f": 5,
        "tag": "snack",
        "source": "label_photo",
    }, date="2026-04-28")

    meal_rows = [p for p in put_calls if p.get("meal_id", "").startswith("meal_")]
    assert len(meal_rows) == 1
    row = meal_rows[0]
    assert row["source"] == "label_photo"
    # Label-photo rows are pre-validated against the actual nutrition panel.
    assert row["validated_source"] == "bedrock_vision"
    assert row["validated_at"], "expected validated_at stamp"

    # Validator Lambda must NOT have been invoked — the panel read is the audit.
    assert invoke_calls == [], f"validator should be skipped; got {invoke_calls}"
    assert result["meal"]["source"] == "label_photo"


def test_known_foods_source_fires_validator(monkeypatch):
    """known_foods rows are fast-path matches — the validator still runs to
    cross-check against USDA / LLM audit. Behavior is same as llm source."""
    ns = _load_module(monkeypatch)
    invoke_calls: list = []
    put_calls: list = []
    _wire_fakes(monkeypatch, ns, invoke_calls, put_calls)

    ns.save_meal({
        "name": "Oikos Vanilla Protein Shake",
        "cal": 170, "p": 30, "c": 8, "f": 3.5,
        "tag": "breakfast",
        "source": "known_foods",
    }, date="2026-04-28")

    meal_rows = [p for p in put_calls if p.get("meal_id", "").startswith("meal_")]
    row = meal_rows[0]
    assert row["source"] == "known_foods"
    assert "validated_source" not in row
    assert len(invoke_calls) == 1


# ── _fetch_usda_nutrients: serving-size correctness ────────────────────────


def _patch_usda_response(monkeypatch, ns, payload):
    """Stub urllib.request.urlopen to return `payload` as a USDA JSON body."""
    import io
    import json

    class FakeResp:
        status = 200
        def __init__(self, body): self._body = body
        def read(self): return self._body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=None):
        return FakeResp(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(ns.urllib.request, "urlopen", fake_urlopen)


def test_usda_returns_label_nutrients_per_serving(monkeypatch):
    """Branded foods with labelNutrients (per-serving panel values) should be
    returned directly — these match what's on the nutrition label."""
    ns = _load_module(monkeypatch)
    _patch_usda_response(monkeypatch, ns, {
        "foods": [{
            "description": "KIRKLAND SIGNATURE, PROTEIN BAR",
            "score": 900.0,
            "labelNutrients": {
                "calories": {"value": 190},
                "protein": {"value": 21},
                "carbohydrates": {"value": 22},
                "fat": {"value": 7},
            },
            # foodNutrients is per-100g for branded foods too — must be ignored.
            "foodNutrients": [
                {"nutrientName": "Energy", "value": 380},
                {"nutrientName": "Protein", "value": 42},
                {"nutrientName": "Carbohydrate, by difference", "value": 44},
                {"nutrientName": "Total lipid (fat)", "value": 14},
            ],
        }],
    })
    result = ns._fetch_usda_nutrients("kirkland protein bar", "fake-key")
    assert result is not None
    assert result["cal"] == 190
    assert result["p"] == 21
    assert result["c"] == 22
    assert result["f"] == 7


def test_usda_skips_foods_without_label_nutrients(monkeypatch):
    """SR Legacy / Foundation / FNDDS entries report per-100g only and lack
    labelNutrients. Returning those values as a meal total corrupts the row,
    so the validator must skip them entirely."""
    ns = _load_module(monkeypatch)
    _patch_usda_response(monkeypatch, ns, {
        "foods": [{
            "description": "Chicken, broilers or fryers, breast, cooked, roasted",
            "score": 900.0,
            # No labelNutrients (typical for SR Legacy / Foundation / FNDDS).
            "foodNutrients": [
                {"nutrientName": "Energy", "value": 165},
                {"nutrientName": "Protein", "value": 31},
                {"nutrientName": "Carbohydrate, by difference", "value": 0},
                {"nutrientName": "Total lipid (fat)", "value": 3.6},
            ],
        }],
    })
    assert ns._fetch_usda_nutrients("chicken breast", "fake-key") is None


def test_usda_skips_low_score_matches(monkeypatch):
    """Below _USDA_MIN_SCORE the match is too weak to trust — skip."""
    ns = _load_module(monkeypatch)
    _patch_usda_response(monkeypatch, ns, {
        "foods": [{
            "description": "Some loosely-matched food",
            "score": 100.0,
            "labelNutrients": {"calories": {"value": 100}},
        }],
    })
    assert ns._fetch_usda_nutrients("something", "fake-key") is None
