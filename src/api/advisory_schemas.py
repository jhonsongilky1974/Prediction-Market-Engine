"""Contratos HTTP de Trading Advisory -- Tramo 5B (Position Management
Advisory). Capa de PRESENTACIÓN únicamente -- ningún cálculo financiero
vive aquí; todo se lee o traduce literalmente desde/hacia
`src.advisory.schemas`/`src.advisory.event_identity`. Reutiliza
LITERALMENTE `FeeInput`/`FeeView` de `src.api.positions_schemas` -- no
se duplica el contrato de fee.

Misma regla de representación monetaria HTTP que Tramo 2
(`src.api.positions_schemas`): precios por contrato son `int` (centavos
enteros exactos); montos que pueden incorporar una fee son `str`
decimal exacto; cantidades de contratos son `int`. Nunca `float`.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.advisory.enums import (
    ComparisonOperator,
    FinalExitType,
    InvalidationConditionCode,
    OrderConflictCode,
    PositionManagementAction,
    Tp1RecoveryKind,
)
from src.api.positions_schemas import FeeInput, FeeView
from src.models.schemas import Sport
from src.positions.enums import Achievability, FeeStatus, OrderAction, OrderStatus, PositionStatus
from src.signals.signal_schema import Side


# ---------------------------------------------------------------------
# EventIdentity (wire)
# ---------------------------------------------------------------------


class EventIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    sport: Sport
    kalshi_ticker_side_a: str = Field(..., min_length=1)
    kalshi_ticker_side_b: str = Field(..., min_length=1)
    side_a: Side
    side_b: Side
    participant_a_canonical: Optional[str] = None
    participant_b_canonical: Optional[str] = None
    participant_a_display: Optional[str] = None
    participant_b_display: Optional[str] = None
    scheduled_start_time: datetime
    market_profile: str = Field(..., min_length=1)


class EventIdentityResponse(BaseModel):
    event_id: str
    sport: Sport
    kalshi_ticker_side_a: str
    kalshi_ticker_side_b: str
    side_a: Side
    side_b: Side
    participant_a_canonical: Optional[str] = None
    participant_b_canonical: Optional[str] = None
    participant_a_display: Optional[str] = None
    participant_b_display: Optional[str] = None
    scheduled_start_time: datetime
    market_profile: str


# ---------------------------------------------------------------------
# POST /advisory/positions/evaluate
# ---------------------------------------------------------------------


class PositionEvaluationTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: str = Field(..., min_length=1)
    target_exit_price_cents: Optional[int] = Field(default=None, ge=0)
    fee_assumption: Optional[FeeInput] = None


class AdvisoryPositionsEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_identity: EventIdentityRequest
    current_price_side_a_cents: int = Field(..., ge=0)
    current_price_side_b_cents: int = Field(..., ge=0)
    prices_timestamp: datetime
    position_targets: List[PositionEvaluationTargetRequest] = Field(default_factory=list)


class OrderSummaryResponse(BaseModel):
    order_id: str
    action: OrderAction
    status: OrderStatus
    requested_qty: int
    confirmed_filled_qty: int
    planned_target_price_cents: int


class PositionExposureLineResponse(BaseModel):
    position_id: str
    side: Side
    status: PositionStatus
    open_contracts: int
    base_capital_at_risk_cents: str
    buy_reserved_cents: str
    capital_committed_cents: str
    contracts_reserved_by_sell_orders: int
    runner_contracts: Optional[int] = None
    blocked_by_unknown_order: bool
    pending_order: Optional[OrderSummaryResponse] = None


class PositionExposureSnapshotResponse(BaseModel):
    event_identity: EventIdentityResponse
    as_of: datetime
    positions: List[PositionExposureLineResponse]
    exposure_side_a_cents: str
    exposure_side_b_cents: str
    net_event_exposure_cents: str
    capital_at_risk_total_cents: str
    capital_recovered_total_cents: str
    runner_contracts_side_a: int
    runner_contracts_side_b: int
    has_blocked_unknown_order: bool


class TP1AdviceResponse(BaseModel):
    recovery_kind: Tp1RecoveryKind
    contracts_to_sell: Optional[int] = None
    evaluated_price_cents: Optional[int] = None
    gross_proceeds_cents: Optional[str] = None
    expected_fees_cents: Optional[str] = None
    net_proceeds_cents: Optional[str] = None
    capital_recovery_runner_contracts: Optional[int] = None
    achievability: Optional[Achievability] = None
    requires_recalculation: bool
    missing_data: List[str] = Field(default_factory=list)


class FinalExitAdviceResponse(BaseModel):
    price_cents: int
    exit_type: FinalExitType
    contracts: int
    gross_proceeds_cents: str


class StopAdviceResponse(BaseModel):
    stop_price_cents: int
    based_on_avg_entry_price_cents: int
    max_adverse_move_cents: int


class InvalidationConditionResponse(BaseModel):
    condition_code: InvalidationConditionCode
    evidence_id: Optional[str] = None
    sport: Sport
    subject: str
    operator: ComparisonOperator
    expected_value: Optional[str] = None
    human_explanation: str


class OrderConflictResponse(BaseModel):
    code: OrderConflictCode
    detail: str
    order_id: Optional[str] = None


class PositionManagementAdviceResponse(BaseModel):
    position_id: str
    side: Side
    status: PositionStatus
    management_action: PositionManagementAction

    current_price_cents: Optional[int] = None
    average_entry_price_cents: Optional[int] = None
    capital_at_risk_cents: str
    capital_at_risk_fee_status: FeeStatus

    tp1: TP1AdviceResponse
    capital_recovery_runner_contracts: Optional[int] = None
    strategic_runner_contracts_projected: Optional[int] = None
    strategic_runner_contracts_confirmed: Optional[int] = None

    final_exit: Optional[FinalExitAdviceResponse] = None
    stop: Optional[StopAdviceResponse] = None
    invalidation: List[InvalidationConditionResponse] = Field(default_factory=list)
    order_conflicts: List[OrderConflictResponse] = Field(default_factory=list)

    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    generated_at: datetime
    expires_at: datetime


class PositionManagementAdvisoryResponse(BaseModel):
    event_identity: EventIdentityResponse
    advices: List[PositionManagementAdviceResponse]
    exposure: PositionExposureSnapshotResponse
    warnings: List[str] = Field(default_factory=list)
    generated_at: datetime
    expires_at: datetime


__all__ = [
    "FeeInput",
    "FeeView",
    "EventIdentityRequest",
    "EventIdentityResponse",
    "PositionEvaluationTargetRequest",
    "AdvisoryPositionsEvaluateRequest",
    "OrderSummaryResponse",
    "PositionExposureLineResponse",
    "PositionExposureSnapshotResponse",
    "TP1AdviceResponse",
    "FinalExitAdviceResponse",
    "StopAdviceResponse",
    "InvalidationConditionResponse",
    "OrderConflictResponse",
    "PositionManagementAdviceResponse",
    "PositionManagementAdvisoryResponse",
]
