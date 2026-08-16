"""Contratos HTTP de Phase 6 -- Tramo 2 (API read/register/prepare sobre
el núcleo de Position Management ya auditado en Tramo 1). Capa de
PRESENTACIÓN únicamente -- ningún cálculo financiero vive aquí; todo
campo se lee o se traduce literalmente desde/hacia
`src.positions.schemas`/`src.positions.capital_recovery`.

Representación monetaria HTTP (regla fija, ver auditoría Tramo 2):

- Precios por contrato (`*_price_cents`, `price_cents`) -- SIEMPRE
  centavos enteros exactos (`int`). El dominio ya los valida como tal
  (`money.require_exact_cents`, ver `src.positions.schemas`), así que
  `int` es seguro y sin ambigüedad.
- Montos que pueden incorporar una fee (`fee.cents`, y cualquier total
  derivado que sume/reste una fee: `capital_invested_cents`,
  `capital_recovered_cents`, `capital_remaining_cents`,
  `gross_proceeds_cents`, `expected_fees_cents`, `net_proceeds_cents`)
  -- SIEMPRE string decimal exacto (p.ej. `"6.93"`), porque una fee
  puede tener fracción de centavo y el tipo de un campo en la API nunca
  debe cambiar de int a string según los datos de una respuesta
  concreta.
- Cantidades de contratos (`open_contracts`, `requested_qty`,
  `contracts_to_sell`, `total_buy_qty`, etc.) -- `int`, sin ambigüedad.

Nunca se usa `float` para ningún campo monetario ni de fee.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.schemas import Sport
from src.positions.enums import (
    Achievability,
    FeeStatus,
    OrderAction,
    OrderEventReason,
    OrderStatus,
    PositionEventTrigger,
    PositionSource,
    PositionStatus,
)
from src.positions.schemas import Fee
from src.signals.signal_schema import Side


def _parse_exact_decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name}={value!r} no es un decimal exacto válido") from exc


class FeeInput(BaseModel):
    """`cents` es un string decimal exacto (permite fracción de
    centavo). Obligatorio salvo `status=UNKNOWN`, en cuyo caso debe
    omitirse -- mismo invariante que `src.positions.schemas.Fee`
    (reforzado aquí solo como validación de formato, la regla real vive
    en `Fee`)."""

    model_config = ConfigDict(extra="forbid")

    status: FeeStatus
    cents: Optional[str] = None

    def to_domain(self) -> Fee:
        return Fee(
            status=self.status,
            cents=_parse_exact_decimal(self.cents, "fee.cents") if self.cents is not None else None,
        )


class FeeView(BaseModel):
    status: FeeStatus
    cents: Optional[str] = None

    @staticmethod
    def from_domain(fee: Fee) -> "FeeView":
        return FeeView(status=fee.status, cents=str(fee.cents) if fee.cents is not None else None)


# ---------------------------------------------------------------------
# POST /positions
# ---------------------------------------------------------------------


class CreatePositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kalshi_ticker: str = Field(..., min_length=1)
    sport: Sport
    side: Side
    source: PositionSource
    linked_opportunity_id: Optional[str] = None
    """Obligatorio si `source=MODEL_OPPORTUNITY`, prohibido si
    `source=MANUAL` -- invariante real (F6) validado por
    `src.positions.schemas.Position`, no duplicado aquí; una violación
    se traduce a 400."""


class PositionResponse(BaseModel):
    position_id: str
    kalshi_ticker: str
    sport: Sport
    side: Side
    source: PositionSource
    linked_opportunity_id: Optional[str] = None

    status: PositionStatus
    blocked_by_unknown_order: bool

    open_contracts: int
    total_buy_qty: int
    total_sell_qty: int

    total_capital_at_risk_cents: str
    total_capital_at_risk_fee_status: FeeStatus
    realized_net_proceeds_cents: str
    realized_net_proceeds_fee_status: FeeStatus
    capital_remaining_cents: str

    runner_contracts: Optional[int] = None
    version: int
    created_at: datetime
    updated_at: datetime


class PositionListResponse(BaseModel):
    positions: List[PositionResponse]


# ---------------------------------------------------------------------
# POST /positions/{id}/fills
# ---------------------------------------------------------------------


class RegisterFillRequest(BaseModel):
    """Registra MANUALMENTE un fill que el usuario ya observó/ejecutó en
    Robinhood -- nunca ejecuta nada. `fill_id` es la idempotency key:
    reenviar el mismo `fill_id` con el mismo payload es un no-op seguro;
    reenviarlo con un payload distinto es un 409 explícito."""

    model_config = ConfigDict(extra="forbid")

    fill_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    action: OrderAction
    qty: int = Field(..., gt=0)
    actual_fill_price_cents: int = Field(..., ge=0)
    fee: FeeInput
    filled_at: datetime
    is_confirmed: bool = True
    expected_order_version: int = Field(..., ge=1)
    """Optimistic locking: versión de la Order (no de la Position) que
    el llamador cree vigente -- coincide con el parámetro real de
    `PositionsRepository.apply_fill`. La Position se recalcula de forma
    derivada dentro de la misma transacción atómica (`BEGIN IMMEDIATE`),
    protegida por exclusividad de escritura, no por una versión de
    Position provista por el llamador -- ver nota de auditoría en el
    informe de entrega de Tramo 2."""


class OrderResponse(BaseModel):
    order_id: str
    position_id: str
    intent_id: str
    action: OrderAction
    requested_qty: int
    planned_target_price_cents: int
    order_price_cents: Optional[int] = None
    status: OrderStatus
    confirmed_filled_qty: int
    avg_fill_price_cents: Optional[int] = None
    replaces_order_id: Optional[str] = None
    version: int
    created_at: datetime
    last_updated_at: datetime


class FillRegistrationResponse(BaseModel):
    fill_id: str
    order: OrderResponse
    position: PositionResponse


# ---------------------------------------------------------------------
# POST /positions/{id}/plan
# ---------------------------------------------------------------------


class ComputePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(..., min_length=1)
    planned_target_price_cents: int = Field(..., ge=0)
    fee_assumption: FeeInput
    observed_market_price_cents: Optional[int] = None
    """Puramente informativo -- NUNCA se usa como `planned_target_price_cents`
    implícitamente (F7). Debe pasarse explícitamente si se quiere que la
    respuesta lo incluya como referencia."""


class PositionPlanResponse(BaseModel):
    plan_id: str
    position_id: str
    computed_at: datetime

    capital_remaining_cents: str
    """Capital remanente usado como base del cálculo (snapshot fijo en
    el momento de calcular el plan)."""
    contracts_to_sell: int
    """Cantidad mínima de contratos a vender para cubrir
    `capital_remaining_cents` al precio propuesto -- "recovery quantity
    requerida"."""
    gross_proceeds_cents: str
    expected_fees_cents: str
    net_proceeds_cents: str
    """"Projected proceeds"."""
    contracts_remaining_after: int
    """"Projected runner": contratos que quedarían abiertos tras
    ejecutar `contracts_to_sell`."""
    achievability: Achievability

    provisional: bool
    provisional_reason: Optional[str] = None
    """Explicación humana de por qué `provisional=True` (fees no
    confirmados en la venta propuesta y/o en fills previos de la
    posición) -- `None` cuando `provisional=False`."""

    fee_assumption: FeeView
    observed_market_price_cents: Optional[int] = None


# ---------------------------------------------------------------------
# POST /positions/{id}/orders  y  PATCH .../orders/{order_id}
# ---------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    """Crea únicamente una orden en estado PLANNED ("prepared" -- nunca
    se somete al broker desde aquí). No ejecuta nada."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(..., min_length=1)
    intent_id: str = Field(..., min_length=1)
    action: OrderAction
    requested_qty: int = Field(..., gt=0)
    planned_target_price_cents: int = Field(..., ge=0)


class UpdateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=1)
    new_status: OrderStatus
    reason: OrderEventReason
    reason_detail: Optional[str] = None
    occurred_at: Optional[datetime] = None


class OrderListResponse(BaseModel):
    orders: List[OrderResponse]


# ---------------------------------------------------------------------
# GET /positions/{id}/events
# ---------------------------------------------------------------------


class PositionEventResponse(BaseModel):
    event_id: str
    position_id: str
    from_status: Optional[PositionStatus] = None
    to_status: PositionStatus
    trigger: PositionEventTrigger
    trigger_detail: Optional[str] = None
    occurred_at: datetime
    recorded_at: datetime


class PositionEventListResponse(BaseModel):
    events: List[PositionEventResponse]
