"""Orquestación HTTP de Phase 6 -- Tramo 2. Traduce entre los contratos
de transporte (`src.api.positions_schemas`) y el núcleo de dominio ya
auditado en Tramo 1 (`src.positions.*`). Nunca escribe SQL directamente
-- toda persistencia pasa por `PositionsRepository`. Ningún cálculo de
capital recovery vive aquí: sigue exclusivamente en
`src.positions.capital_recovery` (función pura, ya auditada).

Cero llamadas a Robinhood, cero automatización de navegador, cero
ejecución de órdenes reales -- esta capa únicamente crea/lee/registra
estado que el usuario ya observó o decidió manualmente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from pydantic import ValidationError

from src.positions import capital_recovery
from src.positions.enums import FeeStatus, OrderStatus, PositionStatus
from src.positions.exceptions import (
    IdempotencyConflictError,
    InvalidStateTransitionError,
    InvariantViolationError,
    NonTerminalOrderExistsError,
    OptimisticLockError,
)
from src.positions.positions_repository import PositionsRepository
from src.positions.schemas import Order, OrderFill, Position

from src.api.positions_schemas import (
    ComputePlanRequest,
    CreateOrderRequest,
    CreatePositionRequest,
    FeeView,
    FillRegistrationResponse,
    OrderResponse,
    PositionEventResponse,
    PositionPlanResponse,
    PositionResponse,
    RegisterFillRequest,
    UpdateOrderRequest,
)

logger = logging.getLogger(__name__)


class PositionsApiError(Exception):
    """Error honesto de la capa Position Management -- `status_code`
    decide la respuesta HTTP en `src/api/positions_router.py`, `detail`
    es el mensaje real (nunca genérico), mismo patrón que
    `ResolverError`/`MappingError` (Fase 5)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _position_to_response(position: Position, *, repository: PositionsRepository) -> PositionResponse:
    fills = repository.get_fills_for_position(position.position_id)
    metrics = capital_recovery.compute_capital_metrics(fills)
    return PositionResponse(
        position_id=position.position_id,
        kalshi_ticker=position.kalshi_ticker,
        sport=position.sport,
        side=position.side,
        source=position.source,
        linked_opportunity_id=position.linked_opportunity_id,
        status=position.status,
        blocked_by_unknown_order=position.blocked_by_unknown_order,
        open_contracts=position.open_contracts,
        total_buy_qty=metrics.total_buy_qty,
        total_sell_qty=metrics.total_sell_qty,
        total_capital_at_risk_cents=str(position.capital_invested_cents),
        total_capital_at_risk_fee_status=position.capital_invested_fee_status,
        realized_net_proceeds_cents=str(position.capital_recovered_cents),
        realized_net_proceeds_fee_status=position.capital_recovered_fee_status,
        capital_remaining_cents=str(position.capital_remaining_computed),
        runner_contracts=position.runner_contracts,
        version=position.version,
        created_at=position.created_at,
        updated_at=position.updated_at,
    )


def _order_to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        order_id=order.order_id,
        position_id=order.position_id,
        intent_id=order.intent_id,
        action=order.action,
        requested_qty=order.requested_qty,
        planned_target_price_cents=int(order.planned_target_price_cents),
        order_price_cents=int(order.order_price_cents) if order.order_price_cents is not None else None,
        status=order.status,
        confirmed_filled_qty=order.confirmed_filled_qty,
        avg_fill_price_cents=int(order.avg_fill_price_cents) if order.avg_fill_price_cents is not None else None,
        replaces_order_id=order.replaces_order_id,
        version=order.version,
        created_at=order.created_at,
        last_updated_at=order.last_updated_at,
    )


def _provisional_reason(position: Position, plan) -> str:
    reasons: List[str] = []
    if plan.fee_assumption.status != FeeStatus.KNOWN:
        reasons.append(f"fee de la venta propuesta es {plan.fee_assumption.status.value}, no KNOWN")
    if position.capital_invested_fee_status != FeeStatus.KNOWN:
        reasons.append(f"fee de entrada de la posición es {position.capital_invested_fee_status.value}, no KNOWN")
    if position.capital_recovered_fee_status != FeeStatus.KNOWN:
        reasons.append(f"fee de salidas previas de la posición es {position.capital_recovered_fee_status.value}, no KNOWN")
    return "; ".join(reasons) if reasons else "capital remanente o fee dependen de datos no confirmados"


# ---------------------------------------------------------------------
# POST /positions
# ---------------------------------------------------------------------


def create_position(request: CreatePositionRequest, *, repository: PositionsRepository) -> PositionResponse:
    now = _utcnow()
    try:
        position = Position(
            position_id=_new_id("pos"),
            source=request.source,
            linked_opportunity_id=request.linked_opportunity_id,
            kalshi_ticker=request.kalshi_ticker,
            sport=request.sport,
            side=request.side,
            status=PositionStatus.OPEN,
            blocked_by_unknown_order=False,
            open_contracts=0,
            capital_invested_cents=Decimal(0),
            capital_invested_fee_status=FeeStatus.KNOWN,
            capital_recovered_cents=Decimal(0),
            capital_recovered_fee_status=FeeStatus.KNOWN,
            runner_contracts=None,
            version=1,
            created_at=now,
            updated_at=now,
        )
    except ValidationError as exc:
        # F6 (linked_opportunity_id obligatorio/prohibido según source) y
        # el resto de invariantes de Position se validan aquí -- no se
        # duplica la regla, solo se traduce el rechazo a 400.
        raise PositionsApiError(400, f"request inválido: {exc}") from exc

    try:
        created = repository.create_position(position)
    except IdempotencyConflictError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvariantViolationError as exc:
        raise PositionsApiError(400, str(exc)) from exc

    return _position_to_response(created, repository=repository)


# ---------------------------------------------------------------------
# GET /positions/{id}  y  GET /positions
# ---------------------------------------------------------------------


def get_position(position_id: str, *, repository: PositionsRepository) -> PositionResponse:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")
    return _position_to_response(position, repository=repository)


def list_positions(status_filter: str, *, repository: PositionsRepository) -> List[PositionResponse]:
    if status_filter == "open":
        positions = repository.list_open_positions()
    elif status_filter == "all":
        positions = repository.list_all_positions()
    else:
        raise PositionsApiError(400, f"status={status_filter!r} inválido -- use 'open' o 'all'")
    return [_position_to_response(p, repository=repository) for p in positions]


# ---------------------------------------------------------------------
# POST /positions/{id}/fills
# ---------------------------------------------------------------------


def register_fill(
    position_id: str, request: RegisterFillRequest, *, repository: PositionsRepository
) -> FillRegistrationResponse:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")
    order = repository.get_order(request.order_id)
    if order is None:
        raise PositionsApiError(404, f"order_id={request.order_id!r} no existe")
    if order.position_id != position_id:
        raise PositionsApiError(
            400, f"order_id={request.order_id!r} no pertenece a position_id={position_id!r}"
        )

    try:
        fee = request.fee.to_domain()
        fill = OrderFill(
            fill_id=request.fill_id,
            order_id=request.order_id,
            position_id=position_id,
            action=request.action,
            qty=request.qty,
            price_cents=Decimal(request.actual_fill_price_cents),
            fee=fee,
            filled_at=request.filled_at,
            is_confirmed=request.is_confirmed,
            recorded_at=_utcnow(),
        )
    except ValidationError as exc:
        raise PositionsApiError(400, f"fill inválido: {exc}") from exc

    try:
        updated_order, updated_position = repository.apply_fill(
            fill, expected_order_version=request.expected_order_version
        )
    except OptimisticLockError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvariantViolationError as exc:
        raise PositionsApiError(400, str(exc)) from exc

    return FillRegistrationResponse(
        fill_id=request.fill_id,
        order=_order_to_response(updated_order),
        position=_position_to_response(updated_position, repository=repository),
    )


# ---------------------------------------------------------------------
# POST /positions/{id}/plan -- advisory únicamente, nunca crea una orden
# ---------------------------------------------------------------------


def compute_plan(
    position_id: str, request: ComputePlanRequest, *, repository: PositionsRepository
) -> PositionPlanResponse:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")

    try:
        fee_assumption = request.fee_assumption.to_domain()
    except ValidationError as exc:
        raise PositionsApiError(400, f"fee_assumption inválida: {exc}") from exc

    try:
        plan = repository.compute_and_save_plan(
            plan_id=request.plan_id,
            position_id=position_id,
            planned_target_price_cents=Decimal(request.planned_target_price_cents),
            fee_assumption=fee_assumption,
            observed_market_price_cents=(
                Decimal(request.observed_market_price_cents)
                if request.observed_market_price_cents is not None
                else None
            ),
        )
    except IdempotencyConflictError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvariantViolationError as exc:
        raise PositionsApiError(400, str(exc)) from exc
    except ValidationError as exc:
        raise PositionsApiError(400, f"plan inválido: {exc}") from exc

    provisional_reason = _provisional_reason(position, plan) if plan.provisional else None

    return PositionPlanResponse(
        plan_id=plan.plan_id,
        position_id=plan.position_id,
        computed_at=plan.computed_at,
        capital_remaining_cents=str(plan.capital_remaining_at_computation_cents),
        contracts_to_sell=plan.contracts_to_sell,
        gross_proceeds_cents=str(plan.gross_proceeds_cents),
        expected_fees_cents=str(plan.expected_fees_cents),
        net_proceeds_cents=str(plan.net_proceeds_cents),
        contracts_remaining_after=plan.contracts_remaining_after,
        achievability=plan.achievability,
        provisional=plan.provisional,
        provisional_reason=provisional_reason,
        fee_assumption=FeeView.from_domain(plan.fee_assumption),
        observed_market_price_cents=(
            int(plan.observed_market_price_cents) if plan.observed_market_price_cents is not None else None
        ),
    )


# ---------------------------------------------------------------------
# POST /positions/{id}/orders -- crea únicamente PLANNED ("prepared")
# ---------------------------------------------------------------------


def create_order(
    position_id: str, request: CreateOrderRequest, *, repository: PositionsRepository
) -> OrderResponse:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")

    now = _utcnow()
    try:
        order = Order(
            order_id=request.order_id,
            position_id=position_id,
            intent_id=request.intent_id,
            action=request.action,
            requested_qty=request.requested_qty,
            planned_target_price_cents=Decimal(request.planned_target_price_cents),
            order_price_cents=None,
            status=OrderStatus.PLANNED,
            confirmed_filled_qty=0,
            avg_fill_price_cents=None,
            version=1,
            created_at=now,
            last_updated_at=now,
        )
    except ValidationError as exc:
        raise PositionsApiError(400, f"request inválido: {exc}") from exc

    try:
        created = repository.create_order(order)
    except IdempotencyConflictError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except NonTerminalOrderExistsError as exc:
        # "No permitir intención incompatible con estado UNKNOWN/reservado."
        raise PositionsApiError(409, str(exc)) from exc
    except InvariantViolationError as exc:
        # "No permitir preparar SELL qty mayor que open_contracts."
        raise PositionsApiError(400, str(exc)) from exc

    return _order_to_response(created)


# ---------------------------------------------------------------------
# PATCH /positions/{id}/orders/{order_id} -- reconciliación MANUAL
# ---------------------------------------------------------------------


def update_order(
    position_id: str, order_id: str, request: UpdateOrderRequest, *, repository: PositionsRepository
) -> OrderResponse:
    order = repository.get_order(order_id)
    if order is None:
        raise PositionsApiError(404, f"order_id={order_id!r} no existe")
    if order.position_id != position_id:
        raise PositionsApiError(404, f"order_id={order_id!r} no pertenece a position_id={position_id!r}")

    try:
        updated = repository.update_order_status(
            order_id,
            expected_version=request.expected_version,
            new_status=request.new_status,
            reason=request.reason,
            reason_detail=request.reason_detail,
            occurred_at=request.occurred_at or _utcnow(),
        )
    except OptimisticLockError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise PositionsApiError(409, str(exc)) from exc
    except InvariantViolationError as exc:
        raise PositionsApiError(400, str(exc)) from exc

    return _order_to_response(updated)


# ---------------------------------------------------------------------
# GET /positions/{id}/orders
# ---------------------------------------------------------------------


def list_orders(position_id: str, *, repository: PositionsRepository) -> List[OrderResponse]:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")
    return [_order_to_response(o) for o in repository.get_orders_for_position(position_id)]


# ---------------------------------------------------------------------
# GET /positions/{id}/events
# ---------------------------------------------------------------------


def list_events(position_id: str, *, repository: PositionsRepository) -> List[PositionEventResponse]:
    position = repository.get_position(position_id)
    if position is None:
        raise PositionsApiError(404, f"position_id={position_id!r} no existe")
    return [
        PositionEventResponse(
            event_id=e.event_id,
            position_id=e.position_id,
            from_status=e.from_status,
            to_status=e.to_status,
            trigger=e.trigger,
            trigger_detail=e.trigger_detail,
            occurred_at=e.occurred_at,
            recorded_at=e.recorded_at,
        )
        for e in repository.get_position_events(position_id)
    ]
