"""Contratos de dominio de Trading Advisory -- Tramo 5B (Position
Management Advisory). Todos `frozen=True`, Decimal-safe (mismas reglas
de `src.positions.money`: precios en centavos enteros exactos, nunca
`float`). Ningún campo de este módulo se llama `ENTER`/`WATCH`/`PASS` --
ver `src.advisory.enums.PositionManagementAction` para el vocabulario de
dominio usado en su lugar.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import ConfigDict, model_validator

from src.advisory.enums import (
    ComparisonOperator,
    FinalExitType,
    InvalidationConditionCode,
    OrderConflictCode,
    PositionManagementAction,
    Tp1RecoveryKind,
)
from src.advisory.event_identity import EventIdentity
from src.models.schemas import Sport, StrictModel
from src.positions.enums import Achievability, FeeStatus, OrderAction, OrderStatus, PositionStatus
from src.positions.money import require_exact_cents, require_non_negative
from src.signals.signal_schema import Side

# Tramo 5B no importa `src.payoff`/`src.policy`/`src.orchestration` ni
# ningún módulo deportivo: la ausencia de `ev_net_strength`/calibración
# (ver precheck de Tramo 5A) NO bloquea nada de lo que este módulo
# calcula (exposición, conflictos de orden, TP1, runner, stop,
# invalidación estructural) -- ver `src.advisory.__init__`.


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


# ---------------------------------------------------------------------
# Exposición (F.H del precheck) -- lectura agregada de Position Management
# ---------------------------------------------------------------------


class OrderSummaryView(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    action: OrderAction
    status: OrderStatus
    requested_qty: int
    confirmed_filled_qty: int
    planned_target_price_cents: Decimal

    @model_validator(mode="after")
    def _validate_invariants(self) -> "OrderSummaryView":
        require_exact_cents(self.planned_target_price_cents, "planned_target_price_cents")
        return self


class PositionExposureLine(StrictModel):
    """Exposición de UNA Position, gross/conservadora (Tramo 5B, decisión
    aprobada): `base_capital_at_risk_cents` es el remanente ya
    confirmado por fills (`Position.capital_remaining_computed`,
    `src.positions.schemas`); `buy_reserved_cents` es SOLO la porción
    pendiente (no confirmada) de una Order BUY no-terminal -- una Order
    SELL no-terminal NUNCA aporta a `buy_reserved_cents` (regla
    explícita). Nunca negativo por construcción."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    side: Side
    status: PositionStatus
    open_contracts: int
    base_capital_at_risk_cents: Decimal
    buy_reserved_cents: Decimal
    capital_committed_cents: Decimal
    contracts_reserved_by_sell_orders: int
    runner_contracts: Optional[int] = None
    blocked_by_unknown_order: bool
    pending_order: Optional[OrderSummaryView] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionExposureLine":
        require_non_negative(self.base_capital_at_risk_cents, "base_capital_at_risk_cents")
        require_non_negative(self.buy_reserved_cents, "buy_reserved_cents")
        require_non_negative(self.capital_committed_cents, "capital_committed_cents")
        if self.capital_committed_cents != self.base_capital_at_risk_cents + self.buy_reserved_cents:
            raise ValueError(
                "capital_committed_cents debe ser exactamente "
                "base_capital_at_risk_cents + buy_reserved_cents"
            )
        if self.contracts_reserved_by_sell_orders < 0:
            raise ValueError("contracts_reserved_by_sell_orders no puede ser negativo")
        if self.open_contracts < 0:
            raise ValueError("open_contracts no puede ser negativo")
        if self.contracts_reserved_by_sell_orders > self.open_contracts:
            # Estructuralmente no debería ocurrir (create_order/apply_fill en
            # src.positions ya garantizan requested_qty<=open_contracts al
            # crear una SELL, y ambos decrecen en lockstep con cada fill) --
            # pero si por cualquier motivo el dato de entrada resultara
            # incoherente, esto debe fallar explícito, nunca aceptarse en
            # silencio (auditoría de Tramo 5B).
            raise ValueError(
                f"contracts_reserved_by_sell_orders={self.contracts_reserved_by_sell_orders} excede "
                f"open_contracts={self.open_contracts} -- estado incoherente, nunca se acepta en silencio"
            )
        return self


class PositionExposureSnapshot(StrictModel):
    """Snapshot agregado de solo lectura, GROSS/CONSERVADOR (documentado
    explícitamente, decisión de Tramo 5): no descuenta por probabilidad
    de fill parcial de una Order BUY pendiente, se autocorrige cuando esa
    Order pasa a un estado terminal. Ambos lados del evento se
    contabilizan simétricamente -- la misma fórmula, sin excepción, para
    `side_a` y `side_b`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_identity: EventIdentity
    as_of: datetime
    positions: List[PositionExposureLine]

    exposure_side_a_cents: Decimal
    exposure_side_b_cents: Decimal
    net_event_exposure_cents: Decimal
    capital_at_risk_total_cents: Decimal
    capital_recovered_total_cents: Decimal
    runner_contracts_side_a: int
    runner_contracts_side_b: int
    has_blocked_unknown_order: bool

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionExposureSnapshot":
        _require_utc_aware(self.as_of, "as_of")
        require_non_negative(self.exposure_side_a_cents, "exposure_side_a_cents")
        require_non_negative(self.exposure_side_b_cents, "exposure_side_b_cents")
        require_non_negative(self.capital_at_risk_total_cents, "capital_at_risk_total_cents")
        require_non_negative(self.capital_recovered_total_cents, "capital_recovered_total_cents")
        if self.net_event_exposure_cents != self.exposure_side_a_cents - self.exposure_side_b_cents:
            raise ValueError(
                "net_event_exposure_cents debe ser exactamente "
                "exposure_side_a_cents - exposure_side_b_cents"
            )
        valid_sides = {self.event_identity.side_a, self.event_identity.side_b}
        for line in self.positions:
            if line.side not in valid_sides:
                raise ValueError(
                    f"PositionExposureLine.side={line.side.value} fuera de "
                    f"{sorted(s.value for s in valid_sides)} -- error de integridad, nunca se descarta en silencio"
                )
        return self


# ---------------------------------------------------------------------
# TP1 / recuperación de capital (reutiliza literalmente capital_recovery)
# ---------------------------------------------------------------------


class TP1Advice(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recovery_kind: Tp1RecoveryKind
    contracts_to_sell: Optional[int] = None
    evaluated_price_cents: Optional[Decimal] = None
    gross_proceeds_cents: Optional[Decimal] = None
    expected_fees_cents: Optional[Decimal] = None
    net_proceeds_cents: Optional[Decimal] = None
    capital_recovery_runner_contracts: Optional[int] = None
    """Remanente PROYECTADO tras vender `contracts_to_sell` -- NUNCA el
    mismo campo que `Position.runner_contracts` (que solo existe tras
    `CAPITAL_RECOVERED` confirmado por fills reales, ver
    `src.positions.schemas.Position`)."""
    achievability: Optional[Achievability] = None
    requires_recalculation: bool
    missing_data: List[str] = []

    @model_validator(mode="after")
    def _validate_invariants(self) -> "TP1Advice":
        if self.recovery_kind == Tp1RecoveryKind.UNAVAILABLE:
            if self.contracts_to_sell is not None:
                raise ValueError("contracts_to_sell debe ser None cuando recovery_kind=UNAVAILABLE")
            if not self.missing_data:
                raise ValueError("missing_data es obligatorio cuando recovery_kind=UNAVAILABLE")
            if not self.requires_recalculation:
                raise ValueError("requires_recalculation debe ser True cuando recovery_kind=UNAVAILABLE")
        else:
            if self.contracts_to_sell is None:
                raise ValueError(f"contracts_to_sell es obligatorio cuando recovery_kind={self.recovery_kind.value}")
            if self.missing_data:
                raise ValueError("missing_data debe estar vacío salvo recovery_kind=UNAVAILABLE")
        if self.recovery_kind == Tp1RecoveryKind.EXACT and self.requires_recalculation:
            raise ValueError("requires_recalculation debe ser False cuando recovery_kind=EXACT")
        if self.recovery_kind == Tp1RecoveryKind.CONSERVATIVE_ESTIMATE and not self.requires_recalculation:
            raise ValueError("requires_recalculation debe ser True cuando recovery_kind=CONSERVATIVE_ESTIMATE")
        if self.contracts_to_sell is not None and self.contracts_to_sell < 0:
            raise ValueError("contracts_to_sell no puede ser negativo")
        return self


# ---------------------------------------------------------------------
# Salida final / stop / invalidación -- informativos, nunca ejecutables
# ---------------------------------------------------------------------


class FinalExitAdvice(StrictModel):
    """Puramente informativo: qué proceeds tendría liquidar el 100% de
    `open_contracts` al precio evaluado -- NUNCA se ejecuta, NUNCA se
    prepara como Order automáticamente."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    price_cents: Decimal
    exit_type: FinalExitType
    contracts: int
    gross_proceeds_cents: Decimal

    @model_validator(mode="after")
    def _validate_invariants(self) -> "FinalExitAdvice":
        require_exact_cents(self.price_cents, "price_cents")
        require_non_negative(self.gross_proceeds_cents, "gross_proceeds_cents")
        if self.contracts < 0:
            raise ValueError("contracts no puede ser negativo")
        return self


class StopAdvice(StrictModel):
    """Informativo únicamente -- ver `src.advisory.invalidation`. Nunca
    ejecuta un stop; `stop_price_cents` siempre clamped al dominio válido
    de un contrato Kalshi (`AdvisoryConfig.contract_price_min/max_cents`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stop_price_cents: Decimal
    based_on_avg_entry_price_cents: Decimal
    max_adverse_move_cents: Decimal

    @model_validator(mode="after")
    def _validate_invariants(self) -> "StopAdvice":
        require_exact_cents(self.stop_price_cents, "stop_price_cents")
        require_exact_cents(self.based_on_avg_entry_price_cents, "based_on_avg_entry_price_cents")
        return self


class InvalidationCondition(StrictModel):
    """Estructurada, NUNCA texto libre ejecutable -- `human_explanation`
    es informativo y no puede, por sí mismo, activar entrada, reentrada,
    stop ni salida (la lógica solo opera sobre `condition_code`/
    `subject`/`operator`/`expected_value`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition_code: InvalidationConditionCode
    evidence_id: Optional[str] = None
    sport: Sport
    subject: str
    operator: ComparisonOperator
    expected_value: Optional[str] = None
    human_explanation: str

    @model_validator(mode="after")
    def _validate_invariants(self) -> "InvalidationCondition":
        if not self.subject.strip():
            raise ValueError("subject no puede estar vacío")
        if not self.human_explanation.strip():
            raise ValueError("human_explanation no puede estar vacío")
        return self


class OrderConflict(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: OrderConflictCode
    detail: str
    order_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "OrderConflict":
        if not self.detail.strip():
            raise ValueError("detail no puede estar vacío")
        return self


# ---------------------------------------------------------------------
# PositionManagementAdvice -- una entrada por Position relevante
# ---------------------------------------------------------------------


class PositionManagementAdvice(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    side: Side
    status: PositionStatus
    management_action: PositionManagementAction

    current_price_cents: Optional[Decimal] = None
    average_entry_price_cents: Optional[Decimal] = None
    capital_at_risk_cents: Decimal
    capital_at_risk_fee_status: FeeStatus

    tp1: TP1Advice
    capital_recovery_runner_contracts: Optional[int] = None
    strategic_runner_contracts_projected: Optional[int] = None
    strategic_runner_contracts_confirmed: Optional[int] = None
    """Fijo en `None` en Tramo 5B -- solo se confirma tras fills reales
    en una fase futura (reanálisis dinámico, fuera de este alcance)."""

    final_exit: Optional[FinalExitAdvice] = None
    stop: Optional[StopAdvice] = None
    invalidation: List[InvalidationCondition] = []
    order_conflicts: List[OrderConflict] = []

    warnings: List[str] = []
    missing_data: List[str] = []

    generated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionManagementAdvice":
        _require_utc_aware(self.generated_at, "generated_at")
        _require_utc_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.generated_at:
            raise ValueError("expires_at debe ser posterior a generated_at")
        require_non_negative(self.capital_at_risk_cents, "capital_at_risk_cents")
        if self.current_price_cents is not None:
            require_exact_cents(self.current_price_cents, "current_price_cents")
        if self.average_entry_price_cents is not None:
            require_exact_cents(self.average_entry_price_cents, "average_entry_price_cents")
        if self.strategic_runner_contracts_confirmed is not None:
            raise ValueError(
                "strategic_runner_contracts_confirmed debe ser None en Tramo 5B "
                "(solo se confirma en una fase futura tras fills reales)"
            )
        return self


# ---------------------------------------------------------------------
# Resultado top-level
# ---------------------------------------------------------------------


class PositionManagementAdvisoryResult(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_identity: EventIdentity
    advices: List[PositionManagementAdvice]
    exposure: PositionExposureSnapshot
    warnings: List[str] = []
    generated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PositionManagementAdvisoryResult":
        _require_utc_aware(self.generated_at, "generated_at")
        _require_utc_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.generated_at:
            raise ValueError("expires_at debe ser posterior a generated_at")
        return self
