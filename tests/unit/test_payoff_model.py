"""Tests de estimate_payoff() (Fase 3, Paso 3.2). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.2, y CONTRACTS_FASE3.md §3.

Reutiliza el mismo patrón de fixtures que `tests/unit/test_market_pricing.py`
(Fase 2) -- incluidos varios de sus 6 escenarios obligatorios -- para
confirmar que, con los datos reales observados en Fase 2, net_ev_status
es SIEMPRE UNKNOWN (DECISIÓN PENDIENTE D-3, sin fórmula de fee
aprobada).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.payoff.payoff_model import estimate_payoff
from src.payoff.schemas import NetEvStatus
from src.signals.signal_schema import Side

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _priced_record(**overrides) -> NormalizedRecord:
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        **overrides,
    )


# ---------------------------------------------------------------------
# net_ev_status es SIEMPRE UNKNOWN (D-3 sin resolver) -- incluso con
# exchange_fee poblado
# ---------------------------------------------------------------------


def test_net_ev_status_is_unknown_with_no_fee_data():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.net_ev_status == NetEvStatus.UNKNOWN
    assert result.ev_to_settlement is None
    assert result.ev_to_planned_exit is None
    assert result.cost_evidence_refs == []


def test_net_ev_status_is_unknown_even_when_exchange_fee_is_populated():
    """Aunque exchange_fee exista, no hay fórmula aprobada (D-3) para
    incorporarlo -- estimate_payoff() no debe inventar una."""
    record = _priced_record(market=MarketData(yes_ask=0.55, exchange_fee=0.01))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.net_ev_status == NetEvStatus.UNKNOWN
    assert result.ev_to_settlement is None
    assert result.entry_fee == 0.01  # se propaga, pero no se usa para calcular EV


@pytest.mark.parametrize(
    "market",
    [
        MarketData(yes_ask=0.55, no_ask=0.42),
        MarketData(yes_ask=None, no_ask=0.40),
        MarketData(yes_ask=1.15),
        MarketData(),
        MarketData(yes_ask=0.0),
        MarketData(no_ask=1.0),
    ],
)
def test_net_ev_status_always_unknown_across_market_pricing_scenarios(market):
    """Recorre variantes de los 6 escenarios de test_market_pricing.py
    (Fase 2) -- en ningún caso net_ev_status puede ser COMPUTED."""
    record = _priced_record(market=market)
    result_yes = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    result_no = estimate_payoff(record, Side.NO, opportunity_id="opp-1", now=NOW)
    assert result_yes.net_ev_status == NetEvStatus.UNKNOWN
    assert result_no.net_ev_status == NetEvStatus.UNKNOWN


# ---------------------------------------------------------------------
# entry_price reutiliza market_price_yes/no literalmente
# ---------------------------------------------------------------------


def test_entry_price_yes_reuses_market_price_yes():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.entry_price == 0.55


def test_entry_price_no_reuses_market_price_no():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    result = estimate_payoff(record, Side.NO, opportunity_id="opp-1", now=NOW)
    assert result.entry_price == 0.42


def test_needs_review_blocks_entry_price_both_sides():
    record = _priced_record(
        market=MarketData(yes_ask=0.55, no_ask=0.42), data_quality=DataQuality(needs_review=True)
    )
    result_yes = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    result_no = estimate_payoff(record, Side.NO, opportunity_id="opp-1", now=NOW)
    assert result_yes.entry_price is None
    assert result_no.entry_price is None


def test_out_of_range_price_returns_none_entry_price_never_clamped():
    record = _priced_record(market=MarketData(yes_ask=1.15))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.entry_price is None


def test_sides_are_independent_no_never_derived_from_yes():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.30))
    result_yes = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    result_no = estimate_payoff(record, Side.NO, opportunity_id="opp-1", now=NOW)
    assert result_no.entry_price != 1.0 - result_yes.entry_price


# ---------------------------------------------------------------------
# payout / loss / breakeven_probability -- estructurales, no fabricados
# ---------------------------------------------------------------------


def test_kalshi_payout_is_one_and_breakeven_equals_entry_price():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", platform="KALSHI", now=NOW)
    assert result.payout == 1.0
    assert result.loss == 0.55
    assert result.breakeven_probability == 0.55


def test_unknown_platform_has_no_assumed_payout():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", platform="OTHER", now=NOW)
    assert result.payout is None
    assert result.breakeven_probability is None


def test_missing_entry_price_leaves_loss_and_breakeven_none():
    record = _priced_record(market=MarketData())
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.entry_price is None
    assert result.loss is None
    assert result.breakeven_probability is None


# ---------------------------------------------------------------------
# Campos de costo nunca fabricados
# ---------------------------------------------------------------------


def test_estimated_exit_fee_and_slippage_always_none():
    record = _priced_record(market=MarketData(yes_ask=0.55, exchange_fee=0.01))
    result = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result.estimated_exit_fee is None
    assert result.slippage_estimate is None
    assert result.max_acceptable_entry_price is None


def test_spread_is_propagated_side_aware():
    record = _priced_record(market=MarketData(spread_yes=0.02, spread_no=0.03))
    result_yes = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    result_no = estimate_payoff(record, Side.NO, opportunity_id="opp-1", now=NOW)
    assert result_yes.spread == 0.02
    assert result_no.spread == 0.03


def test_entry_fee_propagated_when_present_none_when_absent():
    record_with_fee = _priced_record(market=MarketData(exchange_fee=0.02))
    record_without_fee = _priced_record(market=MarketData())
    assert estimate_payoff(record_with_fee, Side.YES, opportunity_id="opp-1", now=NOW).entry_fee == 0.02
    assert estimate_payoff(record_without_fee, Side.YES, opportunity_id="opp-1", now=NOW).entry_fee is None


# ---------------------------------------------------------------------
# Pureza y validación de now
# ---------------------------------------------------------------------


def test_same_input_produces_same_output():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    result_a = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    result_b = estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert result_a == result_b


def test_naive_now_raises():
    record = _priced_record(market=MarketData(yes_ask=0.55))
    with pytest.raises(ValueError, match="tz-aware"):
        estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=datetime(2026, 7, 30, 12, 0, 0))


def test_function_does_not_mutate_input_record():
    record = _priced_record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    estimate_payoff(record, Side.YES, opportunity_id="opp-1", now=NOW)
    assert record.market.yes_ask == 0.55
    assert record.market.no_ask == 0.42
