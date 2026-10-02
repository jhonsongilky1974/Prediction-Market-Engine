"""Orquestador puro de Position Management Advisory -- Tramo 5B. Sin
I/O, sin SQLite, sin reloj propio (`generated_at` es inyectado por el
llamador, mismo patrón que `src.positions.capital_recovery`). Combina
`exposure.py`/`exit_planning.py`/`invalidation.py`/`order_conflicts.py`
-- ninguno de ellos duplicado aquí, solo orquestados.

Regla de alcance (Tramo 5B, no negociable): este módulo NUNCA decide
`side` "ganador" ni compara ambos lados entre sí para preferir uno --
cada `Position` (en cualquiera de los dos lados) recibe exactamente el
mismo tratamiento, de forma independiente. Invertir qué lado es
`side_a`/`side_b` en `EventIdentity` produce resultados espejo
idénticos (test de simetría obligatorio, ver
`tests/unit/test_position_advisory_engine.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from pydantic import ConfigDict

from src.advisory.config import AdvisoryConfig
from src.advisory.enums import FinalExitType, PositionManagementAction, Tp1RecoveryKind
from src.advisory.event_identity import EventIdentity
from src.advisory.exit_planning import build_tp1_advice
from src.advisory.exposure import compute_exposure_snapshot
from src.advisory.invalidation import build_invalidation_conditions, build_stop_advice
from src.advisory.order_conflicts import detect_order_conflicts, find_pending_order
from src.advisory.schemas import (
    FinalExitAdvice,
    PositionManagementAdvice,
    PositionManagementAdvisoryResult,
)
from src.models.schemas import StrictModel
from src.positions import capital_recovery
from src.positions.enums import Achievability
from src.positions.schemas import Fee, Order, OrderFill, Position


class PositionEvaluationInput(StrictModel):
    """Input opcional por Position -- ausencia de target/fee nunca
    bloquea el resto de la asesoría (exposición, conflictos, stop,
    invalidación siguen calculándose)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    target_exit_price_cents: Optional[Decimal] = None
    fee_assumption: Optional[Fee] = None


@dataclass(frozen=True)
class PositionData:
    """Agrupa lo ya leído de `PositionsRepository` para UNA Position --
    ensamblado por el llamador (`src.api.advisory_service`), nunca por
    este módulo (que permanece puro, sin I/O)."""

    position: Position
    orders: Sequence[Order]
    fills: Sequence[OrderFill]


def _current_price_for_side(event_identity: EventIdentity, side, current_price_side_a_cents: Decimal, current_price_side_b_cents: Decimal) -> Decimal:
    return current_price_side_a_cents if side == event_identity.side_a else current_price_side_b_cents


def _determine_management_action(
    *, order_conflicts_count: int, tp1_recovery_kind: Tp1RecoveryKind, tp1_achievability: Optional[Achievability]
) -> PositionManagementAction:
    if order_conflicts_count > 0:
        return PositionManagementAction.MANAGE_ATTENTION_REQUIRED
    if tp1_recovery_kind != Tp1RecoveryKind.UNAVAILABLE and tp1_achievability in (
        Achievability.FULLY_RECOVERABLE,
        Achievability.RECOVERABLE_SELLING_ALL,
    ):
        return PositionManagementAction.MANAGE_ACTION_AVAILABLE
    return PositionManagementAction.HOLD_NO_ACTION_NEEDED


def build_position_management_advice(
    *,
    data: PositionData,
    event_identity: EventIdentity,
    current_price_side_a_cents: Decimal,
    current_price_side_b_cents: Decimal,
    evaluation_input: Optional[PositionEvaluationInput],
    config: AdvisoryConfig,
    generated_at: datetime,
) -> PositionManagementAdvice:
    position = data.position
    metrics = capital_recovery.compute_capital_metrics(data.fills)
    capital_fee_status = capital_recovery.aggregate_fee_status(
        [position.capital_invested_fee_status, position.capital_recovered_fee_status]
    )

    target_price = evaluation_input.target_exit_price_cents if evaluation_input is not None else None
    fee_assumption = evaluation_input.fee_assumption if evaluation_input is not None else None

    tp1 = build_tp1_advice(
        position=position, fills=data.fills, target_exit_price_cents=target_price, fee_assumption=fee_assumption
    )

    pending_order = find_pending_order(data.orders)
    order_conflicts = detect_order_conflicts(
        blocked_by_unknown_order=position.blocked_by_unknown_order, pending_order=pending_order
    )

    stop = build_stop_advice(average_entry_price_cents=metrics.avg_entry_price_cents, config=config)
    invalidation = build_invalidation_conditions(sport=position.sport)

    final_exit: Optional[FinalExitAdvice] = None
    if target_price is not None and position.open_contracts > 0:
        final_exit = FinalExitAdvice(
            price_cents=target_price,
            exit_type=FinalExitType.LIMIT,
            contracts=position.open_contracts,
            gross_proceeds_cents=Decimal(position.open_contracts) * target_price,
        )

    current_price = _current_price_for_side(
        event_identity, position.side, current_price_side_a_cents, current_price_side_b_cents
    )

    management_action = _determine_management_action(
        order_conflicts_count=len(order_conflicts),
        tp1_recovery_kind=tp1.recovery_kind,
        tp1_achievability=tp1.achievability,
    )

    warnings: List[str] = []
    missing_data: List[str] = list(tp1.missing_data)
    if pending_order is not None and target_price is not None:
        warnings.append(
            f"Existe una Order no-terminal ({pending_order.order_id}) -- no se puede crear una nueva "
            "orden de salida hasta que se resuelva, aunque el cálculo de TP1 se muestre informativamente."
        )

    expires_at = generated_at + timedelta(seconds=config.max_allowed_staleness_seconds)

    return PositionManagementAdvice(
        position_id=position.position_id,
        side=position.side,
        status=position.status,
        management_action=management_action,
        current_price_cents=current_price,
        average_entry_price_cents=metrics.avg_entry_price_cents,
        capital_at_risk_cents=position.capital_remaining_computed,
        capital_at_risk_fee_status=capital_fee_status,
        tp1=tp1,
        capital_recovery_runner_contracts=tp1.capital_recovery_runner_contracts,
        strategic_runner_contracts_projected=tp1.capital_recovery_runner_contracts,
        strategic_runner_contracts_confirmed=None,
        final_exit=final_exit,
        stop=stop,
        invalidation=invalidation,
        order_conflicts=order_conflicts,
        warnings=warnings,
        missing_data=missing_data,
        generated_at=generated_at,
        expires_at=expires_at,
    )


def build_position_management_advisory_result(
    *,
    event_identity: EventIdentity,
    positions_data: Sequence[PositionData],
    current_price_side_a_cents: Decimal,
    current_price_side_b_cents: Decimal,
    evaluation_inputs_by_position_id: Dict[str, PositionEvaluationInput],
    config: AdvisoryConfig,
    generated_at: datetime,
) -> PositionManagementAdvisoryResult:
    advices = [
        build_position_management_advice(
            data=data,
            event_identity=event_identity,
            current_price_side_a_cents=current_price_side_a_cents,
            current_price_side_b_cents=current_price_side_b_cents,
            evaluation_input=evaluation_inputs_by_position_id.get(data.position.position_id),
            config=config,
            generated_at=generated_at,
        )
        for data in positions_data
    ]

    exposure = compute_exposure_snapshot(
        event_identity=event_identity,
        positions=[d.position for d in positions_data],
        orders_by_position_id={d.position.position_id: list(d.orders) for d in positions_data},
        as_of=generated_at,
    )

    warnings: List[str] = []
    if exposure.has_blocked_unknown_order:
        warnings.append(
            "Al menos una posición de este evento está bloqueada por una Order en estado UNKNOWN -- "
            "requiere reconciliación manual antes de continuar gestionándola."
        )

    expires_at = generated_at + timedelta(seconds=config.max_allowed_staleness_seconds)

    return PositionManagementAdvisoryResult(
        event_identity=event_identity,
        advices=advices,
        exposure=exposure,
        warnings=warnings,
        generated_at=generated_at,
        expires_at=expires_at,
    )
