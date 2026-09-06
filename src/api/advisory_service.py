"""Orquestación HTTP de Trading Advisory -- Tramo 5B. Traduce entre los
contratos de transporte (`src.api.advisory_schemas`) y el dominio puro
(`src.advisory.*`). Lee `PositionsRepository` -- NUNCA llama
`create_position`/`create_order`/`apply_fill`/`update_order_status`
(cero efectos financieros, ver `AdvisoryApiError` y el router). Cero
llamadas a Robinhood, cero automatización, cero persistencia del
resultado (Tramo 5B es completamente stateless).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import ValidationError

from src.advisory.config import AdvisoryConfig, DEFAULT_ADVISORY_CONFIG
from src.advisory.event_identity import (
    EventIdentity,
    EventIdentityMismatchError,
    validate_event_identity_consistency,
)
from src.advisory.exposure import compute_exposure_snapshot
from src.advisory.position_advisory_engine import (
    PositionData,
    PositionEvaluationInput,
    build_position_management_advisory_result,
)
from src.advisory.schemas import (
    FinalExitAdvice,
    InvalidationCondition,
    OrderConflict,
    PositionExposureLine,
    PositionExposureSnapshot,
    PositionManagementAdvice,
    PositionManagementAdvisoryResult,
    StopAdvice,
    TP1Advice,
)
from src.api.advisory_schemas import (
    AdvisoryPositionsEvaluateRequest,
    EventIdentityRequest,
    EventIdentityResponse,
    FinalExitAdviceResponse,
    InvalidationConditionResponse,
    OrderConflictResponse,
    OrderSummaryResponse,
    PositionExposureLineResponse,
    PositionExposureSnapshotResponse,
    PositionManagementAdviceResponse,
    PositionManagementAdvisoryResponse,
    StopAdviceResponse,
    TP1AdviceResponse,
)
from src.positions.positions_repository import PositionsRepository
from src.positions.schemas import Fee


class AdvisoryApiError(Exception):
    """Error honesto de Trading Advisory -- mismo patrón que
    `PositionsApiError` (`src.api.positions_service`)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event_identity_from_request(request: EventIdentityRequest) -> EventIdentity:
    try:
        return EventIdentity(
            event_id=request.event_id,
            sport=request.sport,
            kalshi_ticker_side_a=request.kalshi_ticker_side_a,
            kalshi_ticker_side_b=request.kalshi_ticker_side_b,
            side_a=request.side_a,
            side_b=request.side_b,
            participant_a_canonical=request.participant_a_canonical,
            participant_b_canonical=request.participant_b_canonical,
            participant_a_display=request.participant_a_display,
            participant_b_display=request.participant_b_display,
            scheduled_start_time=request.scheduled_start_time,
            market_profile=request.market_profile,
        )
    except ValidationError as exc:
        raise AdvisoryApiError(400, f"event_identity inválida: {exc}") from exc


def _event_identity_to_response(identity: EventIdentity) -> EventIdentityResponse:
    return EventIdentityResponse(
        event_id=identity.event_id,
        sport=identity.sport,
        kalshi_ticker_side_a=identity.kalshi_ticker_side_a,
        kalshi_ticker_side_b=identity.kalshi_ticker_side_b,
        side_a=identity.side_a,
        side_b=identity.side_b,
        participant_a_canonical=identity.participant_a_canonical,
        participant_b_canonical=identity.participant_b_canonical,
        participant_a_display=identity.participant_a_display,
        participant_b_display=identity.participant_b_display,
        scheduled_start_time=identity.scheduled_start_time,
        market_profile=identity.market_profile,
    )


def _order_summary_to_response(view) -> Optional[OrderSummaryResponse]:
    if view is None:
        return None
    return OrderSummaryResponse(
        order_id=view.order_id,
        action=view.action,
        status=view.status,
        requested_qty=view.requested_qty,
        confirmed_filled_qty=view.confirmed_filled_qty,
        planned_target_price_cents=int(view.planned_target_price_cents),
    )


def _exposure_line_to_response(line: PositionExposureLine) -> PositionExposureLineResponse:
    return PositionExposureLineResponse(
        position_id=line.position_id,
        side=line.side,
        status=line.status,
        open_contracts=line.open_contracts,
        base_capital_at_risk_cents=str(line.base_capital_at_risk_cents),
        buy_reserved_cents=str(line.buy_reserved_cents),
        capital_committed_cents=str(line.capital_committed_cents),
        contracts_reserved_by_sell_orders=line.contracts_reserved_by_sell_orders,
        runner_contracts=line.runner_contracts,
        blocked_by_unknown_order=line.blocked_by_unknown_order,
        pending_order=_order_summary_to_response(line.pending_order),
    )


def _exposure_snapshot_to_response(snapshot: PositionExposureSnapshot) -> PositionExposureSnapshotResponse:
    return PositionExposureSnapshotResponse(
        event_identity=_event_identity_to_response(snapshot.event_identity),
        as_of=snapshot.as_of,
        positions=[_exposure_line_to_response(p) for p in snapshot.positions],
        exposure_side_a_cents=str(snapshot.exposure_side_a_cents),
        exposure_side_b_cents=str(snapshot.exposure_side_b_cents),
        net_event_exposure_cents=str(snapshot.net_event_exposure_cents),
        capital_at_risk_total_cents=str(snapshot.capital_at_risk_total_cents),
        capital_recovered_total_cents=str(snapshot.capital_recovered_total_cents),
        runner_contracts_side_a=snapshot.runner_contracts_side_a,
        runner_contracts_side_b=snapshot.runner_contracts_side_b,
        has_blocked_unknown_order=snapshot.has_blocked_unknown_order,
    )


def _tp1_to_response(tp1: TP1Advice) -> TP1AdviceResponse:
    return TP1AdviceResponse(
        recovery_kind=tp1.recovery_kind,
        contracts_to_sell=tp1.contracts_to_sell,
        evaluated_price_cents=(int(tp1.evaluated_price_cents) if tp1.evaluated_price_cents is not None else None),
        gross_proceeds_cents=(str(tp1.gross_proceeds_cents) if tp1.gross_proceeds_cents is not None else None),
        expected_fees_cents=(str(tp1.expected_fees_cents) if tp1.expected_fees_cents is not None else None),
        net_proceeds_cents=(str(tp1.net_proceeds_cents) if tp1.net_proceeds_cents is not None else None),
        capital_recovery_runner_contracts=tp1.capital_recovery_runner_contracts,
        achievability=tp1.achievability,
        requires_recalculation=tp1.requires_recalculation,
        missing_data=list(tp1.missing_data),
    )


def _final_exit_to_response(final_exit: Optional[FinalExitAdvice]) -> Optional[FinalExitAdviceResponse]:
    if final_exit is None:
        return None
    return FinalExitAdviceResponse(
        price_cents=int(final_exit.price_cents),
        exit_type=final_exit.exit_type,
        contracts=final_exit.contracts,
        gross_proceeds_cents=str(final_exit.gross_proceeds_cents),
    )


def _stop_to_response(stop: Optional[StopAdvice]) -> Optional[StopAdviceResponse]:
    if stop is None:
        return None
    return StopAdviceResponse(
        stop_price_cents=int(stop.stop_price_cents),
        based_on_avg_entry_price_cents=int(stop.based_on_avg_entry_price_cents),
        max_adverse_move_cents=int(stop.max_adverse_move_cents),
    )


def _invalidation_to_response(conditions: List[InvalidationCondition]) -> List[InvalidationConditionResponse]:
    return [
        InvalidationConditionResponse(
            condition_code=c.condition_code,
            evidence_id=c.evidence_id,
            sport=c.sport,
            subject=c.subject,
            operator=c.operator,
            expected_value=c.expected_value,
            human_explanation=c.human_explanation,
        )
        for c in conditions
    ]


def _order_conflicts_to_response(conflicts: List[OrderConflict]) -> List[OrderConflictResponse]:
    return [OrderConflictResponse(code=c.code, detail=c.detail, order_id=c.order_id) for c in conflicts]


def _advice_to_response(advice: PositionManagementAdvice) -> PositionManagementAdviceResponse:
    return PositionManagementAdviceResponse(
        position_id=advice.position_id,
        side=advice.side,
        status=advice.status,
        management_action=advice.management_action,
        current_price_cents=(int(advice.current_price_cents) if advice.current_price_cents is not None else None),
        average_entry_price_cents=(
            int(advice.average_entry_price_cents) if advice.average_entry_price_cents is not None else None
        ),
        capital_at_risk_cents=str(advice.capital_at_risk_cents),
        capital_at_risk_fee_status=advice.capital_at_risk_fee_status,
        tp1=_tp1_to_response(advice.tp1),
        capital_recovery_runner_contracts=advice.capital_recovery_runner_contracts,
        strategic_runner_contracts_projected=advice.strategic_runner_contracts_projected,
        strategic_runner_contracts_confirmed=advice.strategic_runner_contracts_confirmed,
        final_exit=_final_exit_to_response(advice.final_exit),
        stop=_stop_to_response(advice.stop),
        invalidation=_invalidation_to_response(advice.invalidation),
        order_conflicts=_order_conflicts_to_response(advice.order_conflicts),
        warnings=list(advice.warnings),
        missing_data=list(advice.missing_data),
        generated_at=advice.generated_at,
        expires_at=advice.expires_at,
    )


def _result_to_response(result: PositionManagementAdvisoryResult) -> PositionManagementAdvisoryResponse:
    return PositionManagementAdvisoryResponse(
        event_identity=_event_identity_to_response(result.event_identity),
        advices=[_advice_to_response(a) for a in result.advices],
        exposure=_exposure_snapshot_to_response(result.exposure),
        warnings=list(result.warnings),
        generated_at=result.generated_at,
        expires_at=result.expires_at,
    )


def _fetch_positions_and_validate(
    identity: EventIdentity, *, repository: PositionsRepository
):
    positions = repository.list_positions_for_tickers(
        [identity.kalshi_ticker_side_a, identity.kalshi_ticker_side_b]
    )
    try:
        validate_event_identity_consistency(identity, positions)
    except EventIdentityMismatchError as exc:
        raise AdvisoryApiError(409, str(exc)) from exc
    return positions


# ---------------------------------------------------------------------
# POST /advisory/positions/evaluate
# ---------------------------------------------------------------------


def evaluate_positions(
    request: AdvisoryPositionsEvaluateRequest,
    *,
    repository: PositionsRepository,
    config: AdvisoryConfig = DEFAULT_ADVISORY_CONFIG,
    now: Optional[datetime] = None,
) -> PositionManagementAdvisoryResponse:
    now = now or _utcnow()
    identity = _event_identity_from_request(request.event_identity)

    if request.prices_timestamp.tzinfo is None or request.prices_timestamp.utcoffset() is None:
        raise AdvisoryApiError(400, "prices_timestamp debe ser tz-aware (UTC)")
    staleness_seconds = (now - request.prices_timestamp).total_seconds()
    if staleness_seconds > config.max_allowed_staleness_seconds or staleness_seconds < 0:
        raise AdvisoryApiError(
            422,
            f"prices_timestamp obsoleto o inválido: antigüedad={staleness_seconds:.1f}s, "
            f"máximo permitido={config.max_allowed_staleness_seconds}s",
        )

    positions = _fetch_positions_and_validate(identity, repository=repository)

    evaluation_inputs: Dict[str, PositionEvaluationInput] = {}
    for target in request.position_targets:
        try:
            fee_domain: Optional[Fee] = target.fee_assumption.to_domain() if target.fee_assumption is not None else None
            evaluation_inputs[target.position_id] = PositionEvaluationInput(
                position_id=target.position_id,
                target_exit_price_cents=(
                    Decimal(target.target_exit_price_cents) if target.target_exit_price_cents is not None else None
                ),
                fee_assumption=fee_domain,
            )
        except ValidationError as exc:
            raise AdvisoryApiError(400, f"position_targets[{target.position_id}] inválido: {exc}") from exc

    positions_data = [
        PositionData(
            position=position,
            orders=repository.get_orders_for_position(position.position_id),
            fills=repository.get_fills_for_position(position.position_id),
        )
        for position in positions
    ]

    result = build_position_management_advisory_result(
        event_identity=identity,
        positions_data=positions_data,
        current_price_side_a_cents=Decimal(request.current_price_side_a_cents),
        current_price_side_b_cents=Decimal(request.current_price_side_b_cents),
        evaluation_inputs_by_position_id=evaluation_inputs,
        config=config,
        generated_at=now,
    )

    # Auditoría: los datos de precio pueden vencer DURANTE el cálculo (lecturas
    # a SQLite, construcción de la respuesta) -- se re-verifica la staleness
    # contra el reloj REAL al final (no el `now` inyectado al principio, que
    # solo sirve para `generated_at`), antes de devolver nada al llamador --
    # fail-closed también para el caso "se venció a mitad de camino".
    final_staleness_seconds = (_utcnow() - request.prices_timestamp).total_seconds()
    if final_staleness_seconds > config.max_allowed_staleness_seconds:
        raise AdvisoryApiError(
            422,
            f"prices_timestamp venció durante el cálculo: antigüedad final={final_staleness_seconds:.1f}s, "
            f"máximo permitido={config.max_allowed_staleness_seconds}s",
        )

    return _result_to_response(result)


# ---------------------------------------------------------------------
# GET /positions/exposure
# ---------------------------------------------------------------------


def get_exposure(
    request: EventIdentityRequest,
    *,
    repository: PositionsRepository,
    now: Optional[datetime] = None,
) -> PositionExposureSnapshotResponse:
    now = now or _utcnow()
    identity = _event_identity_from_request(request)
    positions = _fetch_positions_and_validate(identity, repository=repository)

    orders_by_position_id = {p.position_id: repository.get_orders_for_position(p.position_id) for p in positions}
    snapshot = compute_exposure_snapshot(
        event_identity=identity,
        positions=positions,
        orders_by_position_id=orders_by_position_id,
        as_of=now,
    )
    return _exposure_snapshot_to_response(snapshot)
