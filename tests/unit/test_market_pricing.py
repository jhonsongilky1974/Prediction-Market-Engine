"""Tests del Paso 3 -- pricing de mercado side-aware (src/pricing/market_pricing.py).

Alcance deliberadamente limitado a `P_market_YES` / `P_market_NO`. Los 6
escenarios de PLAN_PHASE2.md §7 se prueban aquí únicamente en la parte que
corresponde a estas dos funciones -- ninguna aserción de `EDGE_YES` /
`EDGE_NO` aparece en este archivo, por decisión de arquitectura explícita
del usuario (ver docstring de `market_pricing.py`). Esas aserciones se
implementarán en el Paso 8 (`tests/unit/test_edge.py`), reutilizando estas
mismas funciones como entrada.
"""
from __future__ import annotations

import pytest

from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.pricing.market_pricing import market_price_no, market_price_yes


def _priced_record(**overrides) -> NormalizedRecord:
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        **overrides,
    )


# =========================================================================
# Los 6 escenarios obligatorios de §7 -- alcance P_market únicamente
# =========================================================================

def test_scenario_1_yes_side_returns_yes_ask():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    assert market_price_yes(record) == 0.55


def test_scenario_2_no_side_returns_no_ask():
    record = _priced_record(market=MarketData(no_ask=0.42))
    assert market_price_no(record) == 0.42


def test_scenario_3_yes_ask_plus_no_ask_over_one_both_still_computed_unscaled():
    record = _priced_record(market=MarketData(yes_ask=0.60, no_ask=0.55))
    assert market_price_yes(record) == 0.60
    assert market_price_no(record) == 0.55
    assert market_price_yes(record) + market_price_no(record) == pytest.approx(1.15)


def test_scenario_4_needs_review_blocks_both_sides_even_with_valid_asks():
    record = _priced_record(
        market=MarketData(yes_ask=0.55, no_ask=0.42),
        data_quality=DataQuality(needs_review=True),
    )
    assert market_price_yes(record) is None
    assert market_price_no(record) is None


def test_scenario_5_missing_ask_on_one_side_only_gates_that_side():
    record = _priced_record(market=MarketData(yes_ask=None, no_ask=0.40))
    assert market_price_yes(record) is None
    assert market_price_no(record) == 0.40


def test_scenario_6_out_of_range_price_returns_none_never_clamped():
    record = _priced_record(market=MarketData(yes_ask=1.15))
    assert market_price_yes(record) is None


# =========================================================================
# Casos adversariales adicionales
# =========================================================================

def test_out_of_range_negative_price_returns_none():
    record = _priced_record(market=MarketData(no_ask=-0.10))
    assert market_price_no(record) is None


def test_boundary_price_zero_is_valid_not_treated_as_missing():
    record = _priced_record(market=MarketData(yes_ask=0.0))
    assert market_price_yes(record) == 0.0


def test_boundary_price_one_is_valid():
    record = _priced_record(market=MarketData(no_ask=1.0))
    assert market_price_no(record) == 1.0


def test_no_side_is_never_reconstructed_from_yes_side():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.30))
    assert market_price_yes(record) == 0.55
    assert market_price_no(record) == 0.30
    assert market_price_no(record) != 1.0 - market_price_yes(record)


def test_last_price_never_used_as_executable_price():
    record = _priced_record(market=MarketData(yes_ask=None, no_ask=None, last_price=0.55))
    assert market_price_yes(record) is None
    assert market_price_no(record) is None


def test_both_asks_missing_returns_none_for_both():
    record = _priced_record(market=MarketData())
    assert market_price_yes(record) is None
    assert market_price_no(record) is None


def test_needs_review_false_by_default_does_not_block_valid_price():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    assert record.data_quality.needs_review is False
    assert market_price_yes(record) == 0.55


def test_market_price_yes_ignores_no_ask_value():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=None))
    assert market_price_yes(record) == 0.55


def test_market_price_no_ignores_yes_ask_value():
    record = _priced_record(market=MarketData(yes_ask=None, no_ask=0.42))
    assert market_price_no(record) == 0.42


def test_functions_do_not_mutate_input_record():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    market_price_yes(record)
    market_price_no(record)
    assert record.market.yes_ask == 0.55
    assert record.market.no_ask == 0.42
