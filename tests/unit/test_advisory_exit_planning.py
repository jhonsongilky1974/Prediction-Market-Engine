"""Tests de Phase 6 -- Tramo 5B: `src.advisory.exit_planning`. TP1
reutiliza LITERALMENTE `src.positions.capital_recovery.compute_recovery_plan`
-- estos tests verifican que los números coinciden exactamente con una
llamada directa a esa función, y que el etiquetado
EXACT/CONSERVATIVE_ESTIMATE/UNAVAILABLE sigue la regla de fees aprobada."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.advisory.enums import Tp1RecoveryKind
from src.advisory.exit_planning import build_tp1_advice, derive_conservative_fee_from_history
from src.positions import capital_recovery
from src.positions.enums import Achievability, FeeStatus
from tests.unit.positions_factories import make_fee, make_fill, make_position


def test_no_target_price_is_unavailable():
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=None, fee_assumption=None)
    assert advice.recovery_kind == Tp1RecoveryKind.UNAVAILABLE
    assert advice.contracts_to_sell is None
    assert advice.requires_recalculation is True
    assert advice.missing_data


def test_known_fee_and_known_capital_is_exact_and_matches_compute_recovery_plan():
    position = make_position(
        open_contracts=10,
        capital_invested_cents=Decimal(500),
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_cents=Decimal(0),
        capital_recovered_fee_status=FeeStatus.KNOWN,
    )
    fee = make_fee(status=FeeStatus.KNOWN, cents=Decimal("1"))
    advice = build_tp1_advice(
        position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee
    )
    assert advice.recovery_kind == Tp1RecoveryKind.EXACT
    assert advice.requires_recalculation is False
    assert not advice.missing_data

    expected = capital_recovery.compute_recovery_plan(
        capital_remaining_cents=position.capital_remaining_computed,
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=position.open_contracts,
        planned_target_price_cents=Decimal(60),
        fee_assumption=fee,
    )
    assert advice.contracts_to_sell == expected.contracts_to_sell
    assert advice.gross_proceeds_cents == expected.gross_proceeds_cents
    assert advice.net_proceeds_cents == expected.net_proceeds_cents
    assert advice.capital_recovery_runner_contracts == expected.contracts_remaining_after
    assert advice.achievability == expected.achievability


def test_estimated_fee_is_conservative_and_provisional():
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500))
    fee = make_fee(status=FeeStatus.ESTIMATED, cents=Decimal("2"))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee)
    assert advice.recovery_kind == Tp1RecoveryKind.CONSERVATIVE_ESTIMATE
    assert advice.requires_recalculation is True
    assert advice.contracts_to_sell is not None


def test_unknown_fee_without_history_is_unavailable_with_missing_data():
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500))
    fee = make_fee(status=FeeStatus.UNKNOWN, cents=None)
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee)
    assert advice.recovery_kind == Tp1RecoveryKind.UNAVAILABLE
    assert advice.contracts_to_sell is None
    assert any("fee" in m.lower() for m in advice.missing_data)


def test_omitted_fee_assumption_defaults_to_unknown_never_known():
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=None)
    assert advice.recovery_kind == Tp1RecoveryKind.UNAVAILABLE


def test_unknown_fee_with_historical_known_fill_derives_conservative_estimate():
    from src.positions.enums import OrderAction

    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500))
    historical_fill = make_fill(
        action=OrderAction.BUY, qty=5, price_cents=Decimal(50), fee=make_fee(status=FeeStatus.KNOWN, cents=Decimal("3"))
    )
    advice = build_tp1_advice(
        position=position, fills=[historical_fill], target_exit_price_cents=Decimal(60), fee_assumption=None
    )
    assert advice.recovery_kind == Tp1RecoveryKind.CONSERVATIVE_ESTIMATE
    assert advice.requires_recalculation is True
    assert advice.contracts_to_sell is not None


def test_derive_conservative_fee_uses_worst_observed_known_fee_per_contract():
    fills = [
        make_fill(fill_id="f1", qty=2, fee=make_fee(status=FeeStatus.KNOWN, cents=Decimal("2"))),  # 1.0/contract
        make_fill(fill_id="f2", qty=1, fee=make_fee(status=FeeStatus.KNOWN, cents=Decimal("5"))),  # 5.0/contract
        make_fill(fill_id="f3", qty=1, fee=make_fee(status=FeeStatus.ESTIMATED, cents=Decimal("100"))),  # ignorado (no KNOWN)
    ]
    fee = derive_conservative_fee_from_history(fills)
    assert fee is not None
    assert fee.status == FeeStatus.ESTIMATED
    assert fee.cents == Decimal("5")


def test_derive_conservative_fee_none_without_any_known_fill():
    fills = [make_fill(fee=make_fee(status=FeeStatus.UNKNOWN, cents=None))]
    assert derive_conservative_fee_from_history(fills) is None


def test_capital_already_recovered_reflected_as_achievability():
    position = make_position(
        open_contracts=5, capital_invested_cents=Decimal(100), capital_recovered_cents=Decimal(200)
    )
    fee = make_fee(status=FeeStatus.KNOWN, cents=Decimal(0))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee)
    assert advice.achievability == Achievability.ALREADY_RECOVERED
    assert advice.contracts_to_sell == 0


def test_capital_recovery_runner_contracts_distinct_from_contracts_to_sell():
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(100))
    fee = make_fee(status=FeeStatus.KNOWN, cents=Decimal(0))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee)
    assert advice.capital_recovery_runner_contracts == position.open_contracts - advice.contracts_to_sell


def test_non_known_capital_remaining_fee_status_prevents_exact_even_with_known_sell_fee():
    position = make_position(
        open_contracts=10,
        capital_invested_cents=Decimal(500),
        capital_invested_fee_status=FeeStatus.ESTIMATED,
    )
    fee = make_fee(status=FeeStatus.KNOWN, cents=Decimal("1"))
    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=Decimal(60), fee_assumption=fee)
    assert advice.recovery_kind == Tp1RecoveryKind.CONSERVATIVE_ESTIMATE


# ---------------------------------------------------------------------
# Recovery equivalence -- auditoría: build_tp1_advice nunca diverge
# numéricamente de una llamada directa a compute_recovery_plan con los
# MISMOS inputs, barrido sobre capital/contratos/precio/fee, incluidos
# los 4 casos límite de Achievability.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "capital_invested,open_contracts,target_price,fee_cents",
    [
        (Decimal(500), 10, Decimal(60), Decimal("0")),
        (Decimal(500), 10, Decimal(60), Decimal("1")),
        (Decimal(1), 10, Decimal(60), Decimal("0")),  # ALREADY_RECOVERED (capital trivial)
        (Decimal(10_000), 5, Decimal(60), Decimal("0")),  # RECOVERABLE_SELLING_ALL
        (Decimal(500), 10, Decimal(1), Decimal("1")),  # NOT_RECOVERABLE_AT_THIS_PRICE (fee >= precio)
        (Decimal(97), 1, Decimal(99), Decimal("0")),  # límite: 1 solo contrato disponible
        (Decimal(0), 10, Decimal(60), Decimal("0")),  # capital ya en 0
    ],
)
def test_build_tp1_advice_matches_compute_recovery_plan_exactly(capital_invested, open_contracts, target_price, fee_cents):
    position = make_position(
        open_contracts=open_contracts,
        capital_invested_cents=capital_invested,
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_cents=Decimal(0),
        capital_recovered_fee_status=FeeStatus.KNOWN,
    )
    fee = make_fee(status=FeeStatus.KNOWN, cents=fee_cents)

    advice = build_tp1_advice(position=position, fills=[], target_exit_price_cents=target_price, fee_assumption=fee)

    direct = capital_recovery.compute_recovery_plan(
        capital_remaining_cents=position.capital_remaining_computed,
        capital_remaining_fee_status=FeeStatus.KNOWN,
        open_contracts=open_contracts,
        planned_target_price_cents=target_price,
        fee_assumption=fee,
    )

    assert advice.contracts_to_sell == direct.contracts_to_sell
    assert advice.gross_proceeds_cents == direct.gross_proceeds_cents
    assert advice.expected_fees_cents == direct.expected_fees_cents
    assert advice.net_proceeds_cents == direct.net_proceeds_cents
    assert advice.capital_recovery_runner_contracts == direct.contracts_remaining_after
    assert advice.achievability == direct.achievability
    # contracts_to_sell nunca excede lo disponible (test obligatorio #16
    # ya cubierto en capital_recovery, reconfirmado aquí a través de la
    # capa de Advisory).
    assert advice.contracts_to_sell <= open_contracts
