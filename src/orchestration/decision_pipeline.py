"""Orquestador: captura -> Policy Engine -> `OpportunityRepository`
(Fase 4, Paso 4.1). Ver `ORCHESTRATOR_SPEC.md` para el diseño completo
aprobado -- este módulo implementa exactamente §3-§7 de ese documento.

Composición pura de código ya cerrado de Fase 2/3 (`market_pricing.py`,
`edge.py`, `expected_value.py`, `quality_score.py`, `calibration_layer.py`,
`payoff_model.py`, `evidence_engine.py`, `analysis_health.py`,
`decision.py`, `opportunity_repository.py`) -- ninguna regla de negocio
nueva vive aquí. Nunca importa `mlb_baseline`/`tennis_baseline`/
`registry` directamente (extensibilidad, `ORCHESTRATOR_SPEC.md` §2.3) --
recibe un `SportAdapter` ya construido por la capa de composición
(`scripts/run_e2e.py`).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.calibration.calibration_layer import calibrate
from src.evidence.evidence_engine import collect_evidence
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.health.analysis_health import compute_analysis_health
from src.models.schemas import NormalizedRecord, Sport
from src.observability.step_timer import log_step
from src.opportunity.opportunity_repository import OpportunityRepository
from src.opportunity.schemas import (
    Opportunity,
    OpportunityEvaluation,
    compute_opportunity_id,
    compute_selection_id,
)
from src.orchestration.confidence_profile_builder import build_confidence_profile
from src.orchestration.signal_builder import build_signal_inputs
from src.orchestration.sport_adapter import SportAdapter
from src.payoff.payoff_model import estimate_payoff
from src.policy.decision import decide
from src.policy.schemas import PolicyManifest
from src.signals.signal_schema import Side
from src.storage.history_repository import HistoryRepository
from src.uncertainty.quality_score import compute_quality_score

logger = logging.getLogger(__name__)

_BOTH_SIDES = (Side.YES, Side.NO)


@dataclass
class DecisionPipelineSummary:
    sport: Sport
    records_evaluated: int = 0
    skipped_no_market_id: int = 0
    opportunities_created: int = 0
    evaluations_created: int = 0
    signal_type_counts: Dict[str, int] = field(default_factory=dict)
    # (event_id, "pre-side" | side.value, repr(exc)) -- aislamiento de
    # fallos, ORCHESTRATOR_SPEC.md §5. No aborta el resto del lote.
    skipped_errors: List[Tuple[str, str, str]] = field(default_factory=list)
    exchange_fee_populated_unexpectedly: int = 0


@dataclass
class _RecordContext:
    """Objetos compartidos entre ambos lados de un mismo registro --
    calculados UNA VEZ por registro (pasos 1-3 de §4.2), no una vez por
    lado, para no invocar `predict_fn` (recomputa features) dos veces."""

    model_output: Any
    quality_score_output: Any
    calibration_output: Any


def _build_record_context(
    record: NormalizedRecord,
    feature_inputs: Optional[Any],
    data_cutoff_timestamp: Optional[datetime],
    adapter: SportAdapter,
    loaded_artifact: Optional[Tuple[Any, Any]],
    now: datetime,
) -> _RecordContext:
    logger.info("-> _build_record_context event_id=%r", record.event_id)
    fn_started = time.monotonic()
    with log_step(logger, "_build_record_context.predict_fn", event_id=record.event_id):
        model_output = adapter.predict_fn(record, feature_inputs, data_cutoff_timestamp, loaded_artifact)
    with log_step(logger, "_build_record_context.compute_quality_score", event_id=record.event_id):
        quality_score_output = compute_quality_score(record, consensus=None, now=now)
    # Calibración real (CALIBRATION_SPEC.md §4.3): `load_calibrator_fn` es
    # opcional -- `None` (MLB hoy, sin calibrador) preserva exactamente el
    # comportamiento anterior (calibrator=None). Nunca se invoca si no hay
    # model_version (modelo no entrenado) -- no hay nada que emparejar.
    calibrator = None
    if adapter.load_calibrator_fn is not None and model_output.model_version is not None:
        with log_step(logger, "_build_record_context.load_calibrator_fn", model_version=model_output.model_version):
            calibrator = adapter.load_calibrator_fn(model_output.model_version)
    with log_step(logger, "_build_record_context.calibrate", event_id=record.event_id):
        calibration_output = calibrate(model_output, calibrator=calibrator, now=now)
    logger.info(
        "<- _build_record_context OK event_id=%r elapsed_ms=%.1f",
        record.event_id, (time.monotonic() - fn_started) * 1000,
    )
    return _RecordContext(model_output, quality_score_output, calibration_output)


def evaluate_opportunity(
    record: NormalizedRecord,
    context: _RecordContext,
    side: Side,
    data_cutoff_timestamp: datetime,
    history_repository: HistoryRepository,
    opportunity_repository: OpportunityRepository,
    policy_manifest: PolicyManifest,
    now: datetime,
) -> Tuple[str, bool]:
    """Evalúa y persiste UNA `Opportunity`/`OpportunityEvaluation` para
    `(record, side)`. Devuelve `(signal_type, exchange_fee_populated_unexpectedly)`.
    `record.market_id` debe ser no-`None` (verificado por el llamador,
    `run_decision_pipeline`) -- sin mercado emparejado no hay nada que
    evaluar (`ORCHESTRATOR_SPEC.md` §4.2)."""
    fn_started = time.monotonic()
    selection_id = compute_selection_id(record.market_id, side)
    opportunity_id = compute_opportunity_id(record.event_id, selection_id)
    logger.info("-> evaluate_opportunity opportunity_id=%r side=%r", opportunity_id, side.value)

    with log_step(logger, "evaluate_opportunity.build_confidence_profile", opportunity_id=opportunity_id):
        confidence_profile = build_confidence_profile(context.quality_score_output, opportunity_id, now)
    with log_step(logger, "evaluate_opportunity.build_signal_inputs", opportunity_id=opportunity_id):
        signal_inputs, exchange_fee_populated_unexpectedly = build_signal_inputs(
            record, context.model_output, context.quality_score_output, side, now, context.calibration_output
        )
    with log_step(logger, "evaluate_opportunity.estimate_payoff", opportunity_id=opportunity_id):
        payoff_estimate = estimate_payoff(record, side, opportunity_id, platform="KALSHI", now=now)
    with log_step(logger, "evaluate_opportunity.collect_evidence", opportunity_id=opportunity_id):
        evidence_items = collect_evidence(
            opportunity_id, record, context.calibration_output, confidence_profile, now=now
        )
    with log_step(logger, "evaluate_opportunity.compute_analysis_health", opportunity_id=opportunity_id):
        analysis_health = compute_analysis_health(
            opportunity_id, record, context.quality_score_output, evidence_items, now=now
        )
    with log_step(logger, "evaluate_opportunity.decide", opportunity_id=opportunity_id):
        policy_decision = decide(
            opportunity_id=opportunity_id,
            record=record,
            signal_inputs=signal_inputs,
            payoff_estimate=payoff_estimate,
            confidence_profile=confidence_profile,
            analysis_health=analysis_health,
            data_cutoff_timestamp=data_cutoff_timestamp,
            history_repository=history_repository,
            policy_manifest=policy_manifest,
            now=now,
        )  # nunca lanza -- ORCHESTRATOR_SPEC.md §1.6

    # previous_signal_id encadena al evaluation_id de la OpportunityEvaluation
    # anterior (CONTRACTS_FASE3.md §12: "id de la OpportunityEvaluation
    # anterior, encadenamiento cronológico") -- NUNCA al opportunity_id
    # (identidad estable, no cambia entre versiones, encadenar contra eso
    # no aportaría información). Se consulta ANTES de construir la nueva
    # Opportunity para poder usarlo.
    with log_step(logger, "evaluate_opportunity.get_latest_opportunity", opportunity_id=opportunity_id):
        previous_opportunity = opportunity_repository.get_latest_opportunity(opportunity_id)
    with log_step(logger, "evaluate_opportunity.get_latest_evaluation", opportunity_id=opportunity_id):
        previous_evaluation = opportunity_repository.get_latest_evaluation(opportunity_id)

    opportunity_state_version = previous_opportunity.state_version + 1 if previous_opportunity is not None else 1
    opportunity = Opportunity(
        opportunity_id=opportunity_id,
        event_id=record.event_id,
        market_id=record.market_id,
        selection_id=selection_id,
        side=side,
        sport=record.sport,
        first_seen_at=previous_opportunity.first_seen_at if previous_opportunity is not None else now,
        last_evaluated_at=now,
        state_version=opportunity_state_version,
        previous_signal_id=(previous_evaluation.evaluation_id if previous_evaluation is not None else None),
    )
    with log_step(logger, "evaluate_opportunity.save_opportunity", opportunity_id=opportunity_id):
        opportunity_repository.save_opportunity(opportunity)

    evaluation_state_version = (
        previous_evaluation.state_version + 1 if previous_evaluation is not None else 1
    )
    evaluation = OpportunityEvaluation(
        evaluation_id=f"eval:{opportunity_id}:{evaluation_state_version}",
        opportunity_id=opportunity_id,
        state_version=evaluation_state_version,
        signal_inputs=signal_inputs,
        calibration_output=context.calibration_output,
        payoff_estimate=payoff_estimate,
        confidence_profile=confidence_profile,
        analysis_health=analysis_health,
        evidence_items=evidence_items,
        policy_decision=policy_decision,
        decision_timestamp=now,
        data_cutoff_timestamp=data_cutoff_timestamp,
        market_snapshot_timestamp=now,
        model_version=context.model_output.model_version,
        calibration_version=context.calibration_output.calibration_version,
        policy_version=policy_manifest.policy_version,
        feature_schema_version=CURRENT_FEATURE_SET_VERSION,
    )
    with log_step(logger, "evaluate_opportunity.save_opportunity_evaluation", opportunity_id=opportunity_id):
        opportunity_repository.save_opportunity_evaluation(evaluation)

    logger.info(
        "<- evaluate_opportunity OK opportunity_id=%r side=%r elapsed_ms=%.1f",
        opportunity_id, side.value, (time.monotonic() - fn_started) * 1000,
    )
    return policy_decision.signal_type.value, exchange_fee_populated_unexpectedly


def run_decision_pipeline(
    records: List[NormalizedRecord],
    feature_inputs_list: List[Optional[Any]],
    feature_cutoffs: List[Optional[datetime]],
    sport: Sport,
    adapter: SportAdapter,
    history_repository: HistoryRepository,
    opportunity_repository: OpportunityRepository,
    policy_manifest: PolicyManifest,
    now: Optional[datetime] = None,
) -> DecisionPipelineSummary:
    """Punto de entrada por lote (una corrida, un deporte) -- aislamiento
    de fallos por registro y por lado, `ORCHESTRATOR_SPEC.md` §5. Un
    registro/lado problemático se registra en `summary.skipped_errors` y
    NO detiene el resto del lote (a diferencia de los bucles de
    `mlb_pipeline.py`/`tennis_pipeline.py`, que sí abortan ante una
    excepción no capturada -- decisión de diseño deliberada, no una
    corrección de ese código, que queda sin tocar)."""
    pipeline_started = time.monotonic()
    logger.info("-> run_decision_pipeline sport=%r records=%d", sport.value, len(records))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    summary = DecisionPipelineSummary(sport=sport)
    with log_step(logger, "run_decision_pipeline.load_artifact_fn", sport=sport.value):
        loaded_artifact = adapter.load_artifact_fn()

    for record_index, (record, feature_inputs, data_cutoff_timestamp) in enumerate(
        zip(records, feature_inputs_list, feature_cutoffs)
    ):
        record_label = f"{record_index + 1}/{len(records)}"
        logger.info("-> run_decision_pipeline.record_loop record=%s event_id=%r", record_label, record.event_id)
        summary.records_evaluated += 1

        if record.market_id is None:
            summary.skipped_no_market_id += 1
            logger.info("<- run_decision_pipeline.record_loop record=%s SKIPPED (sin market_id)", record_label)
            continue

        try:
            context = _build_record_context(
                record, feature_inputs, data_cutoff_timestamp, adapter, loaded_artifact, now
            )
        except Exception as exc:  # noqa: BLE001 -- aislamiento deliberado, ver docstring
            summary.skipped_errors.append((record.event_id, "pre-side", repr(exc)))
            logger.info("<- run_decision_pipeline.record_loop record=%s FAILED error=%r", record_label, exc)
            continue

        for side in _BOTH_SIDES:
            try:
                signal_type, exchange_fee_unexpected = evaluate_opportunity(
                    record=record,
                    context=context,
                    side=side,
                    data_cutoff_timestamp=data_cutoff_timestamp or now,
                    history_repository=history_repository,
                    opportunity_repository=opportunity_repository,
                    policy_manifest=policy_manifest,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001 -- aislamiento deliberado, ver docstring
                summary.skipped_errors.append((record.event_id, side.value, repr(exc)))
                continue

            summary.opportunities_created += 1
            summary.evaluations_created += 1
            summary.signal_type_counts[signal_type] = summary.signal_type_counts.get(signal_type, 0) + 1
            if exchange_fee_unexpected:
                summary.exchange_fee_populated_unexpectedly += 1
        logger.info("<- run_decision_pipeline.record_loop record=%s OK", record_label)

    logger.info(
        "<- run_decision_pipeline OK sport=%r records=%d opportunities_created=%d elapsed_ms=%.1f",
        sport.value, len(records), summary.opportunities_created, (time.monotonic() - pipeline_started) * 1000,
    )
    return summary
