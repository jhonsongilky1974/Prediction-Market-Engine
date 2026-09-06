"""Tests de Phase 6 -- Tramo 5B: `src.advisory.exposure`. Cubre la tabla
OrderAction × OrderStatus -> efecto en capital comprometido/contratos
disponibles aprobada en el precheck de Tramo 5, y la fórmula de
exposición agregada (gross/conservadora, simétrica por lado)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.advisory.exposure import compute_exposure_snapshot, compute_position_exposure_line
from src.positions.enums import OrderAction, OrderStatus
from src.positions.schemas import Order
from tests.unit.advisory_factories import make_event_identity
from tests.unit.positions_factories import make_order, make_position

TERMINAL_STATUSES = (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)
NON_TERMINAL_STATUSES = (
    OrderStatus.PLANNED,
    OrderStatus.SUBMITTED,
    OrderStatus.PENDING,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.UNKNOWN,
)


def _order_for_status(status: OrderStatus, action: OrderAction) -> Order:
    confirmed = 3 if status == OrderStatus.PARTIALLY_FILLED else (10 if status == OrderStatus.FILLED else 0)
    return make_order(status=status, action=action, requested_qty=10, confirmed_filled_qty=confirmed, planned_target_price_cents=Decimal(60))


@pytest.mark.parametrize("status", NON_TERMINAL_STATUSES)
def test_buy_non_terminal_reserves_only_pending_qty(status):
    order = _order_for_status(status, OrderAction.BUY)
    position = make_position(open_contracts=3, capital_invested_cents=Decimal(150), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    outstanding = order.requested_qty - order.confirmed_filled_qty
    assert line.buy_reserved_cents == outstanding * order.planned_target_price_cents
    assert line.contracts_reserved_by_sell_orders == 0
    assert line.capital_committed_cents == line.base_capital_at_risk_cents + line.buy_reserved_cents


@pytest.mark.parametrize("status", NON_TERMINAL_STATUSES)
def test_sell_non_terminal_never_reserves_capital_but_reserves_contracts(status):
    order = _order_for_status(status, OrderAction.SELL)
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    outstanding = order.requested_qty - order.confirmed_filled_qty
    assert line.buy_reserved_cents == Decimal(0)
    assert line.contracts_reserved_by_sell_orders == outstanding
    assert line.capital_committed_cents == line.base_capital_at_risk_cents


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
@pytest.mark.parametrize("action", [OrderAction.BUY, OrderAction.SELL])
def test_terminal_orders_never_reserve(status, action):
    confirmed = 10 if status == OrderStatus.FILLED else 0
    order = make_order(status=status, action=action, requested_qty=10, confirmed_filled_qty=confirmed, planned_target_price_cents=Decimal(60))
    position = make_position(open_contracts=5, capital_invested_cents=Decimal(200), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    assert line.buy_reserved_cents == Decimal(0)
    assert line.contracts_reserved_by_sell_orders == 0
    assert line.capital_committed_cents == line.base_capital_at_risk_cents
    assert line.pending_order is None


def test_unknown_buy_is_conservative_worst_case_reserves_capital():
    order = _order_for_status(OrderStatus.UNKNOWN, OrderAction.BUY)
    position = make_position(open_contracts=0, capital_invested_cents=Decimal(0), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    assert line.buy_reserved_cents > 0
    assert line.blocked_by_unknown_order is False  # el flag real viene de Position, no de este cálculo


def test_unknown_sell_is_conservative_worst_case_does_not_shrink_exposure():
    order = _order_for_status(OrderStatus.UNKNOWN, OrderAction.SELL)
    position = make_position(open_contracts=10, capital_invested_cents=Decimal(500), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    # Peor caso: la venta pudo no haberse ejecutado -- no se reduce el capital comprometido.
    assert line.capital_committed_cents == line.base_capital_at_risk_cents
    assert line.contracts_reserved_by_sell_orders == order.requested_qty - order.confirmed_filled_qty


def test_capital_recovered_greater_than_invested_clamps_to_zero():
    position = make_position(
        open_contracts=0, capital_invested_cents=Decimal(100), capital_recovered_cents=Decimal(150)
    )
    line = compute_position_exposure_line(position, [])
    assert line.base_capital_at_risk_cents == Decimal(0)
    assert line.capital_committed_cents == Decimal(0)


def test_confirmed_fills_are_not_double_counted():
    """La porción YA confirmada de un fill vive en capital_invested_cents
    (Position); buy_reserved solo debe contar la porción PENDIENTE de la
    Order no-terminal, nunca la ya confirmada."""
    order = make_order(
        status=OrderStatus.PARTIALLY_FILLED,
        action=OrderAction.BUY,
        requested_qty=10,
        confirmed_filled_qty=4,
        planned_target_price_cents=Decimal(60),
    )
    # 4 contratos YA confirmados a 60c = 240, ya reflejados en Position.
    position = make_position(open_contracts=4, capital_invested_cents=Decimal(240), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [order])
    outstanding = 10 - 4
    assert line.buy_reserved_cents == outstanding * Decimal(60)
    assert line.capital_committed_cents == Decimal(240) + outstanding * Decimal(60)


def test_no_pending_order_never_reserves():
    position = make_position(open_contracts=5, capital_invested_cents=Decimal(250), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [])
    assert line.buy_reserved_cents == Decimal(0)
    assert line.contracts_reserved_by_sell_orders == 0
    assert line.capital_committed_cents == line.base_capital_at_risk_cents


def test_exposure_never_negative():
    position = make_position(open_contracts=0, capital_invested_cents=Decimal(0), capital_recovered_cents=Decimal(0))
    line = compute_position_exposure_line(position, [])
    assert line.base_capital_at_risk_cents >= 0
    assert line.buy_reserved_cents >= 0
    assert line.capital_committed_cents >= 0


# ---------------------------------------------------------------------
# Snapshot agregado -- simetría entre lados
# ---------------------------------------------------------------------


def test_snapshot_symmetric_across_sides():
    identity = make_event_identity()
    pos_a = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=5, capital_invested_cents=Decimal(300), capital_recovered_cents=Decimal(0),
    )
    pos_b = make_position(
        position_id="pos-b", kalshi_ticker=identity.kalshi_ticker_side_b, side=identity.side_b,
        open_contracts=5, capital_invested_cents=Decimal(300), capital_recovered_cents=Decimal(0),
    )
    snapshot = compute_exposure_snapshot(
        event_identity=identity, positions=[pos_a, pos_b], orders_by_position_id={}, as_of=pos_a.created_at
    )
    assert snapshot.exposure_side_a_cents == snapshot.exposure_side_b_cents == Decimal(300)
    assert snapshot.net_event_exposure_cents == Decimal(0)
    assert snapshot.capital_at_risk_total_cents == Decimal(600)


def test_snapshot_inverting_sides_mirrors_result():
    identity = make_event_identity()
    identity_swapped = make_event_identity(
        side_a=identity.side_b,
        side_b=identity.side_a,
        kalshi_ticker_side_a=identity.kalshi_ticker_side_b,
        kalshi_ticker_side_b=identity.kalshi_ticker_side_a,
        participant_a_canonical=identity.participant_b_canonical,
        participant_b_canonical=identity.participant_a_canonical,
        participant_a_display=identity.participant_b_display,
        participant_b_display=identity.participant_a_display,
    )
    pos_a = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=5, capital_invested_cents=Decimal(300), capital_recovered_cents=Decimal(0),
    )
    pos_b = make_position(
        position_id="pos-b", kalshi_ticker=identity.kalshi_ticker_side_b, side=identity.side_b,
        open_contracts=2, capital_invested_cents=Decimal(120), capital_recovered_cents=Decimal(0),
    )
    original = compute_exposure_snapshot(
        event_identity=identity, positions=[pos_a, pos_b], orders_by_position_id={}, as_of=pos_a.created_at
    )
    swapped = compute_exposure_snapshot(
        event_identity=identity_swapped, positions=[pos_a, pos_b], orders_by_position_id={}, as_of=pos_a.created_at
    )
    assert original.exposure_side_a_cents == swapped.exposure_side_b_cents
    assert original.exposure_side_b_cents == swapped.exposure_side_a_cents
    assert original.net_event_exposure_cents == -swapped.net_event_exposure_cents
    assert original.capital_at_risk_total_cents == swapped.capital_at_risk_total_cents


def test_snapshot_has_blocked_unknown_order_propagates():
    identity = make_event_identity()
    pos = make_position(
        kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a, blocked_by_unknown_order=True
    )
    snapshot = compute_exposure_snapshot(
        event_identity=identity, positions=[pos], orders_by_position_id={}, as_of=pos.created_at
    )
    assert snapshot.has_blocked_unknown_order is True


def test_snapshot_rejects_inconsistent_net_exposure_arithmetic():
    """Invariante de `PositionExposureSnapshot`: `net_event_exposure_cents`
    debe ser exactamente `exposure_side_a_cents - exposure_side_b_cents`
    -- nunca se acepta un valor inconsistente en silencio."""
    from pydantic import ValidationError

    from src.advisory.schemas import PositionExposureSnapshot

    identity = make_event_identity()
    with pytest.raises(ValidationError):
        PositionExposureSnapshot(
            event_identity=identity,
            as_of=identity.scheduled_start_time,
            positions=[],
            exposure_side_a_cents=Decimal(0),
            exposure_side_b_cents=Decimal(0),
            net_event_exposure_cents=Decimal(1),  # inconsistente a propósito
            capital_at_risk_total_cents=Decimal(0),
            capital_recovered_total_cents=Decimal(0),
            runner_contracts_side_a=0,
            runner_contracts_side_b=0,
            has_blocked_unknown_order=False,
        )


def test_position_exposure_line_rejects_sell_reservation_exceeding_open_contracts():
    """Auditoría: una SELL no puede reservar más contratos de los que
    hay abiertos -- esto es estructuralmente inalcanzable a través de
    `compute_position_exposure_line` (ver `create_order`/`apply_fill` en
    `src.positions`), pero el contrato en sí debe fallar explícito si
    algún día un dato de entrada incoherente lo produjera, nunca
    aceptarlo en silencio."""
    from pydantic import ValidationError

    from src.advisory.schemas import PositionExposureLine
    from src.positions.enums import PositionStatus

    with pytest.raises(ValidationError):
        PositionExposureLine(
            position_id="pos-x",
            side=make_event_identity().side_a,
            status=PositionStatus.OPEN,
            open_contracts=3,
            base_capital_at_risk_cents=Decimal(0),
            buy_reserved_cents=Decimal(0),
            capital_committed_cents=Decimal(0),
            contracts_reserved_by_sell_orders=5,  # excede open_contracts=3
            blocked_by_unknown_order=False,
        )
