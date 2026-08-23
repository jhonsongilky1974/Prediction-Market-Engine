"""Contratos de dominio de Phase 6 -- Tramo 1 (Position Management). Ver
Design Proposal aprobado (sección D "Modelo definitivo") para el diseño
completo -- este módulo lo implementa literalmente.

Persistencia (Option B, aprobada en sección C del Design Proposal):
`Position`/`Order` son snapshots inmutables (`frozen=True`) de una fila
MUTABLE en SQLite -- el objeto Python nunca se muta in-place, cualquier
cambio de estado pasa por `PositionsRepository` y produce un snapshot
NUEVO. `OrderFill`/`PositionEvent`/`OrderEvent`/`PositionPlan` son
append-only tanto a nivel de contrato (frozen=True) como de motor SQLite
(triggers, ver `positions_repository.py`).

Todo campo monetario es `Decimal` -- nunca `float` (ver
`src.positions.money`). Precios (no fees) deben ser centavos enteros
exactos.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import ConfigDict, model_validator

from src.models.schemas import Sport, StrictModel
from src.positions.enums import (
    Achievability,
    FeeStatus,
    OrderAction,
    OrderEventReason,
    OrderSourceOfTruth,
    OrderStatus,
    PositionEventTrigger,
    PositionSource,
    PositionStatus,
)
from src.positions.money import require_exact_cents, require_non_negative
from src.signals.signal_schema import Side


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


# ---------------------------------------------------------------------
# Fee -- value object, nunca un campo suelto Optional[Decimal]
# ---------------------------------------------------------------------


class Fee(StrictModel):
    """Decisión de precisión de fees (Fase 6): `status` distingue
    KNOWN/ESTIMATED/UNKNOWN explícitamente. `cents` puede tener fracción
    de centavo (a diferencia de un precio) -- ver `src.positions.money`.
    Puede usarse provisionalmente 0 como estimación, pero SOLO marcado
    como ESTIMATED, nunca como si fuera KNOWN."""

    status: FeeStatus
    cents: Optional[Decimal] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Fee":
        if self.status == FeeStatus.UNKNOWN:
            if self.cents is not None:
                raise ValueError("Fee.cents debe ser None cuando status=UNKNOWN")
        else:
            if self.cents is None:
                raise ValueError(f"Fee.cents es obligatorio cuando status={self.status.value}")
            require_non_negative(self.cents, "Fee.cents")
        return self


# ---------------------------------------------------------------------
# Position -- materializada, mutable a nivel de fila SQLite, snapshot
# inmutable a nivel de objeto Python (Design Proposal, sección D)
#
# Deliberadamente NO expone un campo "realized_pnl" (auditoría posterior
# al Tramo 1): `capital_recovered_cents - capital_invested_cents` mezcla
# proceeds de SOLO los contratos ya vendidos contra el capital de TODOS
# los contratos comprados (incluidos los que siguen abiertos) -- no es
# P&L realizado en ningún sentido contable, y declararlo así habría sido
# engañoso mientras la posición conserve contratos abiertos. Las
# métricas honestas ya existen por separado y son las únicas expuestas:
# `capital_invested_cents` (capital total en riesgo),
# `capital_recovered_cents` (proceeds netos realmente cobrados),
# `capital_remaining_computed` (derivado, ver más abajo) y `status`
# (estado de recuperación de capital). Un P&L realizado correcto
# requeriría costeo FIFO/average-cost por contrato, explícitamente fuera
# de alcance del Tramo 1.
# ---------------------------------------------------------------------


class Position(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    create_intent_id: str
    """Idempotency key de la INTENCIÓN de creación (auditoría Tramo 3) --
    mismo patrón que `Order.intent_id`. `UNIQUE` a nivel de motor
    (positions_repository.py). Reenviar la misma key con el mismo
    payload lógico (kalshi_ticker/sport/side/source/linked_opportunity_id)
    es un no-op idempotente; con datos distintos es un conflicto
    explícito (409) -- ver `PositionsRepository.create_position`. NUNCA
    se usa ticker+side como idempotencia global: dos intenciones
    distintas (create_intent_id distintos) pueden crear legítimamente
    dos Position separadas para el mismo ticker/side."""
    source: PositionSource
    linked_opportunity_id: Optional[str] = None
    kalshi_ticker: str
    sport: Sport
    side: Side
    status: PositionStatus
    blocked_by_unknown_order: bool = False
    open_contracts: int
    capital_invested_cents: Decimal
    capital_invested_fee_status: FeeStatus
    capital_recovered_cents: Decimal
    capital_recovered_fee_status: FeeStatus
    runner_contracts: Optional[int] = None
    version: int
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Position":
        _require_utc_aware(self.created_at, "created_at")
        _require_utc_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at no puede ser anterior a created_at")
        if self.version < 1:
            raise ValueError(f"version debe ser >= 1: {self.version}")
        if self.open_contracts < 0:
            raise ValueError(f"open_contracts no puede ser negativo: {self.open_contracts}")

        # F6 (Design Proposal): linked_opportunity_id obligatorio/prohibido
        # según source -- Position Management nunca inventa retroactivamente
        # una señal deportiva.
        if self.source == PositionSource.MODEL_OPPORTUNITY and self.linked_opportunity_id is None:
            raise ValueError("linked_opportunity_id es obligatorio cuando source=MODEL_OPPORTUNITY")
        if self.source == PositionSource.MANUAL and self.linked_opportunity_id is not None:
            raise ValueError("linked_opportunity_id debe ser None cuando source=MANUAL")

        require_non_negative(self.capital_invested_cents, "capital_invested_cents")
        require_non_negative(self.capital_recovered_cents, "capital_recovered_cents")

        if self.runner_contracts is not None:
            if self.status not in (
                PositionStatus.CAPITAL_RECOVERED,
                PositionStatus.CLOSED,
                PositionStatus.SETTLED_WIN,
                PositionStatus.SETTLED_LOSS,
            ):
                raise ValueError(
                    "runner_contracts solo tiene sentido en status "
                    f"CAPITAL_RECOVERED/CLOSED/SETTLED_*, no en {self.status.value}"
                )
            if self.runner_contracts < 0 or self.runner_contracts > self.open_contracts:
                raise ValueError(
                    f"runner_contracts={self.runner_contracts} fuera de rango "
                    f"[0, open_contracts={self.open_contracts}]"
                )
        return self

    @property
    def capital_remaining_computed(self) -> Decimal:
        """Derivado, NO persistido como columna propia (Design Proposal,
        sección D: "capital_remaining: Money (derivado)"). Nunca negativo."""
        remaining = self.capital_invested_cents - self.capital_recovered_cents
        return remaining if remaining > 0 else Decimal(0)


# ---------------------------------------------------------------------
# Order -- materializada, mutable a nivel de fila SQLite
# ---------------------------------------------------------------------


class Order(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    position_id: str
    intent_id: str
    action: OrderAction
    requested_qty: int
    planned_target_price_cents: Decimal
    order_price_cents: Optional[Decimal] = None
    status: OrderStatus
    confirmed_filled_qty: int
    avg_fill_price_cents: Optional[Decimal] = None
    source_of_truth: OrderSourceOfTruth = OrderSourceOfTruth.MANUAL_ENTRY
    replaces_order_id: Optional[str] = None
    version: int
    created_at: datetime
    last_updated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Order":
        _require_utc_aware(self.created_at, "created_at")
        _require_utc_aware(self.last_updated_at, "last_updated_at")
        if self.last_updated_at < self.created_at:
            raise ValueError("last_updated_at no puede ser anterior a created_at")
        if self.version < 1:
            raise ValueError(f"version debe ser >= 1: {self.version}")
        if self.requested_qty <= 0:
            raise ValueError(f"requested_qty debe ser > 0: {self.requested_qty}")
        if self.confirmed_filled_qty < 0 or self.confirmed_filled_qty > self.requested_qty:
            raise ValueError(
                f"confirmed_filled_qty={self.confirmed_filled_qty} fuera de rango "
                f"[0, requested_qty={self.requested_qty}]"
            )
        require_exact_cents(self.planned_target_price_cents, "planned_target_price_cents")
        if self.order_price_cents is not None:
            require_exact_cents(self.order_price_cents, "order_price_cents")
        if self.avg_fill_price_cents is not None:
            require_non_negative(self.avg_fill_price_cents, "avg_fill_price_cents")

        # Alcance autorizado Tramo 1: captura de fills 100% manual --
        # EXTENSION_OBSERVED está reservado, no habilitado.
        if self.source_of_truth != OrderSourceOfTruth.MANUAL_ENTRY:
            raise ValueError(
                f"Tramo 1: source_of_truth solo admite MANUAL_ENTRY, recibido "
                f"{self.source_of_truth.value} (captura pasiva no implementada)"
            )

        # Coherencia status <-> confirmed_filled_qty.
        if self.status == OrderStatus.FILLED and self.confirmed_filled_qty != self.requested_qty:
            raise ValueError("status=FILLED exige confirmed_filled_qty == requested_qty")
        if (
            self.status in (OrderStatus.PLANNED, OrderStatus.SUBMITTED, OrderStatus.PENDING)
            and self.confirmed_filled_qty != 0
        ):
            raise ValueError(f"status={self.status.value} exige confirmed_filled_qty == 0")
        if self.status == OrderStatus.PARTIALLY_FILLED and not (
            0 < self.confirmed_filled_qty < self.requested_qty
        ):
            raise ValueError(
                "status=PARTIALLY_FILLED exige 0 < confirmed_filled_qty < requested_qty"
            )
        return self


# ---------------------------------------------------------------------
# OrderFill -- append-only, inmutable (F9)
# ---------------------------------------------------------------------


class OrderFill(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fill_id: str
    order_id: str
    position_id: str
    action: OrderAction
    qty: int
    price_cents: Decimal
    fee: Fee
    filled_at: datetime
    is_confirmed: bool
    recorded_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "OrderFill":
        _require_utc_aware(self.filled_at, "filled_at")
        _require_utc_aware(self.recorded_at, "recorded_at")
        if self.qty <= 0:
            raise ValueError(f"qty debe ser > 0: {self.qty}")
        require_exact_cents(self.price_cents, "price_cents")
        require_non_negative(self.price_cents, "price_cents")
        return self


# ---------------------------------------------------------------------
# PositionEvent / OrderEvent -- append-only, taxonomía cerrada + OTHER
# ---------------------------------------------------------------------


class PositionEvent(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    position_id: str
    from_status: Optional[PositionStatus] = None
    to_status: PositionStatus
    trigger: PositionEventTrigger
    trigger_detail: Optional[str] = None
    occurred_at: datetime
    recorded_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionEvent":
        _require_utc_aware(self.occurred_at, "occurred_at")
        _require_utc_aware(self.recorded_at, "recorded_at")
        if self.trigger == PositionEventTrigger.OTHER and not self.trigger_detail:
            raise ValueError("trigger_detail es obligatorio cuando trigger=OTHER")
        if self.trigger != PositionEventTrigger.OTHER and self.trigger_detail is not None:
            raise ValueError("trigger_detail solo se admite cuando trigger=OTHER")
        return self


class OrderEvent(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    order_id: str
    from_status: Optional[OrderStatus] = None
    to_status: OrderStatus
    reason: OrderEventReason
    reason_detail: Optional[str] = None
    occurred_at: datetime
    recorded_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "OrderEvent":
        _require_utc_aware(self.occurred_at, "occurred_at")
        _require_utc_aware(self.recorded_at, "recorded_at")
        if self.reason == OrderEventReason.OTHER and not self.reason_detail:
            raise ValueError("reason_detail es obligatorio cuando reason=OTHER")
        if self.reason != OrderEventReason.OTHER and self.reason_detail is not None:
            raise ValueError("reason_detail solo se admite cuando reason=OTHER")
        return self


# ---------------------------------------------------------------------
# PositionPlan -- append-only, advisory, NUNCA ejecutable (F7, F10)
# ---------------------------------------------------------------------


class PositionPlan(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    position_id: str
    computed_at: datetime
    capital_remaining_at_computation_cents: Decimal
    planned_target_price_cents: Decimal
    fee_assumption: Fee
    open_contracts_at_computation: int
    contracts_to_sell: int
    gross_proceeds_cents: Decimal
    expected_fees_cents: Decimal
    net_proceeds_cents: Decimal
    contracts_remaining_after: int
    achievability: Achievability
    provisional: bool
    observed_market_price_cents: Optional[Decimal] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionPlan":
        _require_utc_aware(self.computed_at, "computed_at")
        require_exact_cents(self.planned_target_price_cents, "planned_target_price_cents")
        if self.observed_market_price_cents is not None:
            # F7 (Design Proposal): observed_market_price es puramente
            # informativo -- este validator NO lo compara ni lo deriva
            # hacia planned_target_price_cents, solo valida su forma.
            require_exact_cents(self.observed_market_price_cents, "observed_market_price_cents")

        require_non_negative(self.capital_remaining_at_computation_cents, "capital_remaining_at_computation_cents")
        require_non_negative(self.gross_proceeds_cents, "gross_proceeds_cents")
        require_non_negative(self.expected_fees_cents, "expected_fees_cents")
        require_non_negative(self.net_proceeds_cents, "net_proceeds_cents")

        if self.open_contracts_at_computation < 0:
            raise ValueError("open_contracts_at_computation no puede ser negativo")
        if self.contracts_to_sell < 0 or self.contracts_to_sell > self.open_contracts_at_computation:
            raise ValueError(
                f"contracts_to_sell={self.contracts_to_sell} fuera de rango "
                f"[0, open_contracts_at_computation={self.open_contracts_at_computation}]"
            )
        if self.contracts_remaining_after != self.open_contracts_at_computation - self.contracts_to_sell:
            raise ValueError(
                "contracts_remaining_after debe ser exactamente "
                "open_contracts_at_computation - contracts_to_sell"
            )

        # Decisión de fees (Fase 6): mientras la recuperación dependa de
        # fees ESTIMATED o UNKNOWN, el resultado queda explícitamente
        # PROVISIONAL -- nunca se declara definitivo silenciosamente.
        if self.fee_assumption.status != FeeStatus.KNOWN and not self.provisional:
            raise ValueError(
                "provisional debe ser True cuando fee_assumption.status != KNOWN"
            )
        return self
