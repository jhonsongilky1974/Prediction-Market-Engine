"""Tests de src/positions/schemas.py -- invariantes de los contratos de
dominio de Phase 6 (Tramo 1)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.positions.enums import (
    Achievability,
    FeeStatus,
    OrderEventReason,
    OrderStatus,
    PositionEventTrigger,
    PositionSource,
    PositionStatus,
)
from src.positions.schemas import Fee, OrderEvent, OrderFill, PositionEvent, PositionPlan
from tests.unit.positions_factories import NOW, make_fee, make_fill, make_order, make_position


# ---------------------------------------------------------------------
# Fee
# ---------------------------------------------------------------------


def test_fee_known_requires_cents():
    with pytest.raises(ValidationError, match="cents es obligatorio"):
        Fee(status=FeeStatus.KNOWN, cents=None)


def test_fee_unknown_forbids_cents():
    with pytest.raises(ValidationError, match="debe ser None"):
        Fee(status=FeeStatus.UNKNOWN, cents=Decimal("5"))


def test_fee_estimated_zero_is_valid_and_distinct_from_known():
    estimated = Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0))
    known = Fee(status=FeeStatus.KNOWN, cents=Decimal(0))
    assert estimated.cents == known.cents == Decimal(0)
    assert estimated.status != known.status  # nunca se confunden aunque el monto coincida


def test_fee_round_trip():
    fee = make_fee(status=FeeStatus.ESTIMATED, cents=Decimal("6.93"))
    assert Fee.model_validate(fee.model_dump()) == fee
    assert Fee.model_validate_json(fee.model_dump_json()) == fee


# ---------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------


def test_position_model_opportunity_requires_linked_id():
    with pytest.raises(ValidationError, match="linked_opportunity_id es obligatorio"):
        make_position(source=PositionSource.MODEL_OPPORTUNITY, linked_opportunity_id=None)


def test_position_manual_forbids_linked_id():
    with pytest.raises(ValidationError, match="linked_opportunity_id debe ser None"):
        make_position(source=PositionSource.MANUAL, linked_opportunity_id="opp-1")


def test_position_model_opportunity_with_link_is_valid():
    pos = make_position(source=PositionSource.MODEL_OPPORTUNITY, linked_opportunity_id="opp-1")
    assert pos.linked_opportunity_id == "opp-1"


def test_position_negative_open_contracts_rejected():
    with pytest.raises(ValidationError, match="no puede ser negativo"):
        make_position(open_contracts=-1)


def test_position_runner_contracts_requires_terminal_ish_status():
    with pytest.raises(ValidationError, match="runner_contracts solo tiene sentido"):
        make_position(status=PositionStatus.OPEN, runner_contracts=3)


def test_position_runner_contracts_valid_in_capital_recovered():
    pos = make_position(status=PositionStatus.CAPITAL_RECOVERED, open_contracts=4, runner_contracts=4)
    assert pos.runner_contracts == 4


def test_position_runner_contracts_out_of_range_rejected():
    with pytest.raises(ValidationError, match="fuera de rango"):
        make_position(status=PositionStatus.CAPITAL_RECOVERED, open_contracts=4, runner_contracts=5)


def test_position_is_frozen():
    pos = make_position()
    with pytest.raises(ValidationError):
        pos.open_contracts = 5


def test_position_round_trip():
    pos = make_position(open_contracts=19, capital_invested_cents=Decimal("950"))
    assert type(pos).model_validate(pos.model_dump()) == pos
    assert type(pos).model_validate_json(pos.model_dump_json()) == pos


# ---------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------


def test_order_requested_qty_must_be_positive():
    with pytest.raises(ValidationError, match="requested_qty debe ser > 0"):
        make_order(requested_qty=0)


def test_order_planned_target_price_rejects_fractional_cents():
    with pytest.raises(ValidationError, match="entero de centavos"):
        make_order(planned_target_price_cents=Decimal("50.5"))


def test_order_extension_observed_rejected_in_tramo1():
    from src.positions.enums import OrderSourceOfTruth

    with pytest.raises(ValidationError, match="Tramo 1"):
        make_order(source_of_truth=OrderSourceOfTruth.EXTENSION_OBSERVED)


def test_order_filled_requires_full_confirmed_qty():
    with pytest.raises(ValidationError, match="FILLED exige"):
        make_order(status=OrderStatus.FILLED, requested_qty=10, confirmed_filled_qty=5)


def test_order_planned_requires_zero_confirmed_qty():
    with pytest.raises(ValidationError, match="exige confirmed_filled_qty == 0"):
        make_order(status=OrderStatus.PLANNED, confirmed_filled_qty=1)


def test_order_partially_filled_requires_strictly_between():
    with pytest.raises(ValidationError, match="PARTIALLY_FILLED exige"):
        make_order(status=OrderStatus.PARTIALLY_FILLED, requested_qty=10, confirmed_filled_qty=0)
    with pytest.raises(ValidationError, match="PARTIALLY_FILLED exige"):
        make_order(status=OrderStatus.PARTIALLY_FILLED, requested_qty=10, confirmed_filled_qty=10)


def test_order_partially_filled_valid_mid_range():
    order = make_order(status=OrderStatus.PARTIALLY_FILLED, requested_qty=10, confirmed_filled_qty=6)
    assert order.confirmed_filled_qty == 6


# ---------------------------------------------------------------------
# OrderFill
# ---------------------------------------------------------------------


def test_fill_qty_must_be_positive():
    with pytest.raises(ValidationError, match="qty debe ser > 0"):
        make_fill(qty=0)


def test_fill_price_rejects_fractional_cents():
    with pytest.raises(ValidationError, match="entero de centavos"):
        make_fill(price_cents=Decimal("50.25"))


def test_fill_is_frozen():
    fill = make_fill()
    with pytest.raises(ValidationError):
        fill.qty = 99


# ---------------------------------------------------------------------
# PositionEvent / OrderEvent -- taxonomía cerrada + OTHER
# ---------------------------------------------------------------------


def test_position_event_other_requires_detail():
    with pytest.raises(ValidationError, match="trigger_detail es obligatorio"):
        PositionEvent(
            event_id="e1",
            position_id="pos-1",
            from_status=None,
            to_status=PositionStatus.OPEN,
            trigger=PositionEventTrigger.OTHER,
            trigger_detail=None,
            occurred_at=NOW,
            recorded_at=NOW,
        )


def test_position_event_non_other_forbids_detail():
    with pytest.raises(ValidationError, match="solo se admite cuando trigger=OTHER"):
        PositionEvent(
            event_id="e1",
            position_id="pos-1",
            from_status=None,
            to_status=PositionStatus.OPEN,
            trigger=PositionEventTrigger.POSITION_OPENED,
            trigger_detail="no debería ir aquí",
            occurred_at=NOW,
            recorded_at=NOW,
        )


def test_order_event_other_requires_detail():
    with pytest.raises(ValidationError, match="reason_detail es obligatorio"):
        OrderEvent(
            event_id="e1",
            order_id="ord-1",
            from_status=None,
            to_status=OrderStatus.PLANNED,
            reason=OrderEventReason.OTHER,
            reason_detail=None,
            occurred_at=NOW,
            recorded_at=NOW,
        )


# ---------------------------------------------------------------------
# PositionPlan
# ---------------------------------------------------------------------


def _base_plan_kwargs(**overrides):
    base = dict(
        plan_id="plan-1",
        position_id="pos-1",
        computed_at=NOW,
        capital_remaining_at_computation_cents=Decimal("950"),
        planned_target_price_cents=Decimal("63"),
        fee_assumption=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)),
        open_contracts_at_computation=19,
        contracts_to_sell=16,
        gross_proceeds_cents=Decimal("1008"),
        expected_fees_cents=Decimal(0),
        net_proceeds_cents=Decimal("1008"),
        contracts_remaining_after=3,
        achievability=Achievability.FULLY_RECOVERABLE,
        provisional=True,
        observed_market_price_cents=None,
    )
    base.update(overrides)
    return base


def test_position_plan_valid():
    plan = PositionPlan(**_base_plan_kwargs())
    assert plan.contracts_to_sell == 16


def test_position_plan_contracts_to_sell_out_of_range_rejected():
    with pytest.raises(ValidationError, match="fuera de rango"):
        PositionPlan(**_base_plan_kwargs(contracts_to_sell=20))


def test_position_plan_remaining_after_must_match():
    with pytest.raises(ValidationError, match="contracts_remaining_after debe ser exactamente"):
        PositionPlan(**_base_plan_kwargs(contracts_remaining_after=99))


def test_position_plan_non_known_fee_requires_provisional_true():
    with pytest.raises(ValidationError, match="provisional debe ser True"):
        PositionPlan(**_base_plan_kwargs(fee_assumption=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)), provisional=False))


def test_position_plan_known_fee_allows_provisional_false():
    plan = PositionPlan(**_base_plan_kwargs(fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)), provisional=False))
    assert plan.provisional is False


def test_position_plan_round_trip():
    plan = PositionPlan(**_base_plan_kwargs())
    assert PositionPlan.model_validate(plan.model_dump()) == plan
    assert PositionPlan.model_validate_json(plan.model_dump_json()) == plan
