"""Tests de src/positions/capital_recovery.py -- lógica pura de capital
recovery (Fase 6, Tramo 1, sección B del alcance autorizado). Incluye
los casos matemáticos obligatorios de la auditoría (Kirkin, segunda
entrada, partial fills múltiples, fees KNOWN/ESTIMATED/UNKNOWN)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.positions.capital_recovery import (
    aggregate_fee_status,
    compute_capital_metrics,
    compute_recovery_plan,
    is_capital_recovery_confirmed,
    weighted_average_price_cents,
)
from src.positions.enums import Achievability, FeeStatus, OrderAction
from src.positions.schemas import Fee
from tests.unit.positions_factories import make_fill


def _buy(qty: int, price: int, fee_status=FeeStatus.KNOWN, fee_cents=Decimal(0), fill_id=None):
    return make_fill(
        fill_id=fill_id or f"buy-{price}-{qty}",
        action=OrderAction.BUY,
        qty=qty,
        price_cents=Decimal(price),
        fee=Fee(status=fee_status, cents=None if fee_status == FeeStatus.UNKNOWN else fee_cents),
    )


def _sell(qty: int, price: int, fee_status=FeeStatus.KNOWN, fee_cents=Decimal(0), fill_id=None):
    return make_fill(
        fill_id=fill_id or f"sell-{price}-{qty}",
        action=OrderAction.SELL,
        qty=qty,
        price_cents=Decimal(price),
        fee=Fee(status=fee_status, cents=None if fee_status == FeeStatus.UNKNOWN else fee_cents),
    )


# ---------------------------------------------------------------------
# weighted_average_price_cents -- helper compartido (auditoría de
# sobreingeniería: reemplaza el cálculo duplicado que existía tanto en
# compute_capital_metrics como en PositionsRepository.apply_fill)
# ---------------------------------------------------------------------


def test_weighted_average_price_cents_empty_is_none():
    assert weighted_average_price_cents([]) is None


def test_weighted_average_price_cents_single_fill():
    assert weighted_average_price_cents([_buy(19, 50)]) == Decimal(50)


def test_weighted_average_price_cents_multiple_fills_rounds_half_up():
    fills = [_buy(10, 44), _buy(10, 25, fill_id="buy-25-10-b")]
    # (10*44 + 10*25) / 20 = 34.5 -> ROUND_HALF_UP -> 35
    assert weighted_average_price_cents(fills) == Decimal(35)


# ---------------------------------------------------------------------
# aggregate_fee_status -- peor-caso
# ---------------------------------------------------------------------


def test_aggregate_fee_status_empty_is_known():
    assert aggregate_fee_status([]) == FeeStatus.KNOWN


def test_aggregate_fee_status_worst_of():
    assert aggregate_fee_status([FeeStatus.KNOWN, FeeStatus.KNOWN]) == FeeStatus.KNOWN
    assert aggregate_fee_status([FeeStatus.KNOWN, FeeStatus.ESTIMATED]) == FeeStatus.ESTIMATED
    assert aggregate_fee_status([FeeStatus.ESTIMATED, FeeStatus.UNKNOWN]) == FeeStatus.UNKNOWN
    assert aggregate_fee_status([FeeStatus.KNOWN, FeeStatus.UNKNOWN, FeeStatus.ESTIMATED]) == FeeStatus.UNKNOWN


# ---------------------------------------------------------------------
# Caso 1 (obligatorio) -- Kirkin: 19 contratos BUY @50c, venta ~63c
# ---------------------------------------------------------------------


def test_case_kirkin_capital_metrics():
    fills = [_buy(19, 50, fee_status=FeeStatus.ESTIMATED, fee_cents=Decimal(0))]
    metrics = compute_capital_metrics(fills)
    assert metrics.open_contracts == 19
    assert metrics.total_capital_at_risk_cents == Decimal(950)
    assert metrics.total_capital_at_risk_fee_status == FeeStatus.ESTIMATED
    assert metrics.capital_remaining_cents == Decimal(950)
    assert metrics.avg_entry_price_cents == Decimal(50)


def test_case_kirkin_recovery_plan_minimum_qty_and_runner():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.ESTIMATED,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)),
    )
    # ceil(950/63) == 16 -- vender 15 (como hizo el trader real) deja
    # 945c, 5c corto de 950c: la regla estricta v1 (sin tolerancia,
    # decisión 2) exige 16, no 15.
    assert result.contracts_to_sell == 16
    assert result.contracts_remaining_after == 3  # runner
    assert result.net_proceeds_cents == Decimal(1008)
    assert result.achievability == Achievability.FULLY_RECOVERABLE
    assert result.provisional is True  # fee ESTIMATED


def test_case_kirkin_selling_only_15_would_not_fully_recover():
    # Verificación directa de por qué 15 no basta bajo la regla estricta.
    net_15 = 15 * Decimal(63)
    assert net_15 == Decimal(945)
    assert net_15 < Decimal(950)


# ---------------------------------------------------------------------
# Caso 2 (obligatorio) -- segunda entrada: 10 BUY@44c + 10 BUY@25c
# ---------------------------------------------------------------------


def test_case_second_entry_capital_is_exact_sum_not_avg_times_qty():
    fills = [_buy(10, 44), _buy(10, 25, fill_id="buy-25-10-b")]
    metrics = compute_capital_metrics(fills)
    assert metrics.open_contracts == 20
    assert metrics.total_capital_at_risk_cents == Decimal(690)  # 440 + 250, suma exacta
    assert metrics.avg_entry_price_cents == Decimal(35)  # 690/20=34.5 -> ROUND_HALF_UP -> 35, SOLO display

    # Regla del Caso B (Design Proposal): recomputar capital como
    # avg*qty produce drift -- exactamente lo que este módulo evita.
    drifted = metrics.avg_entry_price_cents * metrics.open_contracts
    assert drifted != metrics.total_capital_at_risk_cents
    assert drifted == Decimal(700)  # 35*20=700 != 690: prueba del drift evitado


# ---------------------------------------------------------------------
# Caso 3/4 (obligatorios) -- partial fill de venta, y múltiples partial
# fills de venta a precios distintos
# ---------------------------------------------------------------------


def test_case_multiple_partial_sells_at_different_prices():
    fills = [
        _buy(19, 50, fee_status=FeeStatus.ESTIMATED),
        _sell(6, 63, fill_id="sell-63-6"),
        _sell(5, 66, fill_id="sell-66-5"),
        _sell(3, 69, fill_id="sell-69-3"),
    ]
    metrics = compute_capital_metrics(fills)
    assert metrics.open_contracts == 19 - 14
    assert metrics.total_buy_qty == 19
    assert metrics.total_sell_qty == 14
    assert metrics.realized_net_proceeds_cents == Decimal(6 * 63 + 5 * 66 + 3 * 69)  # 915, suma exacta
    assert metrics.capital_remaining_cents == Decimal(950 - 915)  # 35, aun no recuperado
    assert metrics.avg_exit_price_cents == Decimal(65)  # 915/14=65.357... -> ROUND_HALF_UP -> 65


def test_case_capital_metrics_total_buy_sell_qty_with_no_fills():
    metrics = compute_capital_metrics([])
    assert metrics.total_buy_qty == 0
    assert metrics.total_sell_qty == 0
    assert metrics.open_contracts == 0


# ---------------------------------------------------------------------
# Caso 5 (obligatorio) -- recuperación mediante múltiples ventas
# parciales hasta completar
# ---------------------------------------------------------------------


def test_case_recovery_completes_across_multiple_partial_sells():
    fills = [
        _buy(19, 50),
        _sell(6, 63, fill_id="sell-63-6"),
        _sell(5, 66, fill_id="sell-66-5"),
        _sell(3, 69, fill_id="sell-69-3"),
        _sell(1, 69, fill_id="sell-69-1-more"),
    ]
    metrics = compute_capital_metrics(fills)
    assert metrics.realized_net_proceeds_cents == Decimal(984)  # 915 + 69
    assert metrics.capital_remaining_cents == Decimal(0)  # clamped a 0, no negativo
    assert metrics.open_contracts == 4


# ---------------------------------------------------------------------
# Caso 6/7/8 (obligatorios) -- fees KNOWN / ESTIMATED / UNKNOWN
# ---------------------------------------------------------------------


def test_case_fees_known_plan_is_not_provisional():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal("2")),
    )
    assert result.provisional is False
    # net_per_contract = 63 - 2 = 61; k = ceil(950/61) = 16
    assert result.contracts_to_sell == 16


def test_case_fees_estimated_plan_is_provisional():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)),
    )
    assert result.provisional is True


def test_case_fees_unknown_plan_uses_zero_but_marks_provisional():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.UNKNOWN, cents=None),
    )
    assert result.provisional is True
    # Mismo resultado numérico que fee=0 ESTIMATED (decisión: usar 0
    # provisionalmente), pero SIEMPRE marcado provisional -- nunca
    # declarado como si fuera KNOWN.
    assert result.contracts_to_sell == 16


def test_case_capital_remaining_fee_status_alone_forces_provisional():
    # Aun con una fee_assumption KNOWN para la venta futura, si el
    # capital remanente en sí depende de fees pasados no confirmados,
    # el plan completo sigue siendo provisional.
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.ESTIMATED,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    assert result.provisional is True


# ---------------------------------------------------------------------
# Caso 9 (obligatorio) -- nunca declarar CAPITAL_RECOVERED definitivo
# con fee relevante desconocido
# ---------------------------------------------------------------------


def test_is_capital_recovery_confirmed_requires_both_sides_known():
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=True,
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_fee_status=FeeStatus.KNOWN,
    ) is True
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=True,
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_fee_status=FeeStatus.ESTIMATED,
    ) is False
    # Fee de ENTRADA sin confirmar también invalida la confirmación,
    # aunque toda la salida ya sea KNOWN -- el capital objetivo mismo
    # está en duda.
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=True,
        capital_invested_fee_status=FeeStatus.ESTIMATED,
        capital_recovered_fee_status=FeeStatus.KNOWN,
    ) is False
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=True,
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_fee_status=FeeStatus.UNKNOWN,
    ) is False
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=False,
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_fee_status=FeeStatus.KNOWN,
    ) is False


# ---------------------------------------------------------------------
# Caso 15/16 (obligatorios) -- nunca open_contracts negativo, nunca
# recomendar vender más de lo abierto
# ---------------------------------------------------------------------


def test_open_contracts_never_negative_raises():
    fills = [_buy(5, 50), _sell(6, 63)]  # vender más de lo comprado
    with pytest.raises(ValueError, match="open_contracts negativo"):
        compute_capital_metrics(fills)


def test_recovery_plan_never_recommends_more_than_open_contracts():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(10_000),  # capital enorme, inalcanzable
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=19,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    assert result.contracts_to_sell == 19  # clamped, nunca > open_contracts
    assert result.achievability == Achievability.RECOVERABLE_SELLING_ALL
    assert result.contracts_remaining_after == 0


def test_recovery_plan_not_recoverable_when_fee_consumes_price():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(950),
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=19,
        planned_target_price_cents=Decimal(10),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(10)),  # fee >= precio
    )
    assert result.achievability == Achievability.NOT_RECOVERABLE_AT_THIS_PRICE
    assert result.contracts_to_sell == 0


# ---------------------------------------------------------------------
# Caso 17 (obligatorio) -- capital ya recuperado -> recovery_qty == 0
# ---------------------------------------------------------------------


def test_recovery_plan_zero_when_already_recovered():
    result = compute_recovery_plan(
        capital_remaining_cents=Decimal(0),
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=4,
        planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    assert result.contracts_to_sell == 0
    assert result.achievability == Achievability.ALREADY_RECOVERED
    assert result.contracts_remaining_after == 4
