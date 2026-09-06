"""Cálculo de exposición agregada -- Tramo 5B. Funciones puras: sin I/O,
sin SQLite (los datos ya vienen leídos por el llamador vía
`PositionsRepository`). Implementa literalmente la fórmula y la tabla
`OrderAction × OrderStatus` aprobadas en el precheck de Tramo 5:

    base_capital_at_risk(p) = max(0, capital_invested_cents - capital_recovered_cents)
    buy_reserved(p) = (requested_qty - confirmed_filled_qty) * planned_target_price_cents
                      SI existe una Order BUY no-terminal para p, SINO 0
    capital_committed(p) = base_capital_at_risk(p) + buy_reserved(p)

Una Order SELL no-terminal NUNCA aporta a `buy_reserved` -- solo reserva
`contracts_reserved_by_sell_orders` (disponibilidad de contratos, no
capital). Fills confirmados ya están en `Position.capital_invested_cents`/
`capital_recovered_cents` -- nunca se re-suman aquí. Exposición
GROSS/CONSERVADORA: documentado explícitamente, no se descuenta por
probabilidad de fill parcial.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Sequence

from src.advisory.event_identity import EventIdentity
from src.advisory.order_conflicts import find_pending_order
from src.advisory.schemas import OrderSummaryView, PositionExposureLine, PositionExposureSnapshot
from src.positions.enums import OrderAction
from src.positions.schemas import Order, Position


def _order_summary(order: Order) -> OrderSummaryView:
    return OrderSummaryView(
        order_id=order.order_id,
        action=order.action,
        status=order.status,
        requested_qty=order.requested_qty,
        confirmed_filled_qty=order.confirmed_filled_qty,
        planned_target_price_cents=order.planned_target_price_cents,
    )


def compute_position_exposure_line(position: Position, orders: Sequence[Order]) -> PositionExposureLine:
    base_capital_at_risk = position.capital_remaining_computed
    pending = find_pending_order(orders)

    buy_reserved = Decimal(0)
    contracts_reserved_by_sell = 0
    pending_view = None

    if pending is not None:
        pending_view = _order_summary(pending)
        outstanding_qty = pending.requested_qty - pending.confirmed_filled_qty
        if pending.action == OrderAction.BUY:
            buy_reserved = outstanding_qty * pending.planned_target_price_cents
        else:
            contracts_reserved_by_sell = outstanding_qty

    return PositionExposureLine(
        position_id=position.position_id,
        side=position.side,
        status=position.status,
        open_contracts=position.open_contracts,
        base_capital_at_risk_cents=base_capital_at_risk,
        buy_reserved_cents=buy_reserved,
        capital_committed_cents=base_capital_at_risk + buy_reserved,
        contracts_reserved_by_sell_orders=contracts_reserved_by_sell,
        runner_contracts=position.runner_contracts,
        blocked_by_unknown_order=position.blocked_by_unknown_order,
        pending_order=pending_view,
    )


def compute_exposure_snapshot(
    *,
    event_identity: EventIdentity,
    positions: Sequence[Position],
    orders_by_position_id: Dict[str, List[Order]],
    as_of: datetime,
) -> PositionExposureSnapshot:
    lines = [
        compute_position_exposure_line(p, orders_by_position_id.get(p.position_id, []))
        for p in positions
    ]

    exposure_a = Decimal(0)
    exposure_b = Decimal(0)
    capital_at_risk_total = Decimal(0)
    capital_recovered_total = Decimal(0)
    runners_a = 0
    runners_b = 0
    has_blocked = False

    for line, position in zip(lines, positions):
        capital_at_risk_total += position.capital_invested_cents - position.capital_recovered_cents \
            if position.capital_invested_cents > position.capital_recovered_cents else Decimal(0)
        capital_recovered_total += position.capital_recovered_cents
        if line.side == event_identity.side_a:
            exposure_a += line.capital_committed_cents
            runners_a += line.runner_contracts or 0
        else:
            exposure_b += line.capital_committed_cents
            runners_b += line.runner_contracts or 0
        if line.blocked_by_unknown_order:
            has_blocked = True

    return PositionExposureSnapshot(
        event_identity=event_identity,
        as_of=as_of,
        positions=lines,
        exposure_side_a_cents=exposure_a,
        exposure_side_b_cents=exposure_b,
        net_event_exposure_cents=exposure_a - exposure_b,
        capital_at_risk_total_cents=capital_at_risk_total,
        capital_recovered_total_cents=capital_recovered_total,
        runner_contracts_side_a=runners_a,
        runner_contracts_side_b=runners_b,
        has_blocked_unknown_order=has_blocked,
    )
