"""Compone `AnalyzeResponse` a partir de una `OpportunityEvaluation` real
(Fase 5). Ver `HTTP_SERVICE_SPEC.md` §2.

Reutiliza `run_decision_pipeline` (Fase 4, sin modificar) y
`SPORT_ADAPTERS`/`CONFIG_POLICY_DIR` importados literalmente de
`scripts.run_e2e` -- cero redeclaración de esa construcción. Persiste
en el MISMO `data/engine.db` que la corrida horaria real (mismo
tratamiento, mismo rastro de auditoría) -- no existe una variante de
solo lectura.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from scripts.run_e2e import CONFIG_POLICY_DIR, SPORT_ADAPTERS
from src.api.event_resolver import ResolverError, resolve_ticker
from src.api.schemas import AnalyzeResponse, Freshness, InfluentialVariable, UncertaintyBreakdown
from src.models.schemas import Sport
from src.opportunity.opportunity_repository import OpportunityRepository
from src.opportunity.schemas import compute_opportunity_id, compute_selection_id
from src.orchestration.decision_pipeline import run_decision_pipeline
from src.payoff.schemas import NetEvStatus
from src.policy.manifest import load_policy_manifest
from src.signals.signal_schema import Side
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

_POLICY_MANIFEST_FILENAME = {
    Sport.MLB: "mlb_v1.json",
    Sport.TENNIS: "tennis_v1.json",
}

_P_CONSENSUS_NO_VIG_UNAVAILABLE_REASON = (
    "no disponible: la capa que resuelve qué participante de The Odds API corresponde al lado YES "
    "de un ticker de Kalshi nunca se construyó (diferida deliberadamente en Fase 2, "
    "src/pricing/odds_consensus.py) -- ningún valor se fabrica."
)


def analyze_ticker(
    ticker: str,
    repository: Optional[Repository] = None,
    history_repository: Optional[HistoryRepository] = None,
) -> AnalyzeResponse:
    """`repository`/`history_repository` son inyectables (mismo patrón que
    `run_mlb_pipeline`/`run_tennis_pipeline`) -- `None` (uso real vía
    `src/api/main.py`) construye sobre `data/engine.db` de producción;
    los tests inyectan instancias sobre `tmp_path`, nunca tocan
    producción."""
    started_at_monotonic = time.monotonic()

    repo = repository or Repository()
    hist_repo = history_repository or HistoryRepository()
    opp_repo = OpportunityRepository(db_path=repo.db_path)

    resolved = resolve_ticker(ticker, repository=repo, history_repository=hist_repo)

    # `now` para el orquestador se captura AQUÍ, DESPUÉS del fetch en vivo
    # (`resolve_ticker`, que puede tardar decenas de segundos) -- nunca al
    # inicio del request. Bug real encontrado en pruebas manuales contra
    # APIs reales: `compute_analysis_health`/`staleness_seconds` compara
    # `now` contra `record.data_quality.source_timestamps`, que el
    # pipeline en vivo estampa DURANTE el fetch -- con un `now` capturado
    # antes del fetch, esos timestamps quedan en el FUTURO respecto a
    # `now`, produciendo `staleness_seconds` negativo (rechazado por el
    # validador de `AnalysisHealth`, correctamente).
    decision_now = datetime.now(timezone.utc)

    manifest = load_policy_manifest(CONFIG_POLICY_DIR / _POLICY_MANIFEST_FILENAME[resolved.sport])
    summary = run_decision_pipeline(
        records=[resolved.record],
        feature_inputs_list=[resolved.feature_inputs],
        feature_cutoffs=[resolved.feature_cutoff],
        sport=resolved.sport,
        adapter=SPORT_ADAPTERS[resolved.sport],
        history_repository=hist_repo,
        opportunity_repository=opp_repo,
        policy_manifest=manifest,
        now=decision_now,
    )
    if summary.skipped_errors:
        _event_id, _side, error_repr = summary.skipped_errors[0]
        raise ResolverError(502, f"el orquestador no pudo evaluar este evento: {error_repr}")

    selection_id = compute_selection_id(resolved.record.market_id, Side.YES)
    opportunity_id = compute_opportunity_id(resolved.record.event_id, selection_id)
    evaluation = opp_repo.get_latest_evaluation(opportunity_id)
    if evaluation is None:
        raise ResolverError(502, "el orquestador no persistió ninguna evaluación para este ticker -- inesperado, sin errores reportados.")

    net_ev_status: NetEvStatus = (
        evaluation.payoff_estimate.net_ev_status if evaluation.payoff_estimate is not None else NetEvStatus.UNKNOWN
    )

    most_influential = sorted(
        evaluation.evidence_items,
        key=lambda item: (item.strength is None, -(item.strength or 0.0)),
    )

    return AnalyzeResponse(
        ticker=ticker,
        event_id=resolved.record.event_id,
        sport=resolved.sport.value,
        participant_a=resolved.record.participant_a,
        participant_b=resolved.record.participant_b,
        p_model=evaluation.signal_inputs.p_model,
        p_market=evaluation.signal_inputs.market_price,
        p_consensus_no_vig=None,
        p_consensus_no_vig_unavailable_reason=_P_CONSENSUS_NO_VIG_UNAVAILABLE_REASON,
        edge=evaluation.signal_inputs.edge,
        ev_bruto=evaluation.signal_inputs.ev_bruto,
        ev_neto=evaluation.signal_inputs.ev_neto,
        net_ev_status=net_ev_status.value,
        recommendation=evaluation.policy_decision.signal_type.value,
        recommendation_reasons=[
            f"{reason.code.value}: {reason.detail}" for reason in evaluation.policy_decision.reasons
        ],
        uncertainty=UncertaintyBreakdown(
            data_quality=evaluation.confidence_profile.data_quality,
            model_reliability=evaluation.confidence_profile.model_reliability,
            market_quality=evaluation.confidence_profile.market_quality,
            operational_safety=evaluation.confidence_profile.operational_safety,
            operational_risk=evaluation.confidence_profile.operational_risk,
            aggregate_confidence=evaluation.confidence_profile.aggregate_confidence,
        ),
        most_influential_variables=[
            InfluentialVariable(
                fact=item.fact, direction=item.direction.value, source_field=item.source_field, strength=item.strength
            )
            for item in most_influential
        ],
        model_version=evaluation.model_version,
        calibration_version=evaluation.calibration_version,
        policy_version=evaluation.policy_version,
        feature_schema_version=evaluation.feature_schema_version,
        freshness=_build_freshness(resolved.market_capture_ts),
        enrichment_mode=resolved.enrichment_mode,
        processing_time_ms=(time.monotonic() - started_at_monotonic) * 1000,
    )


def _build_freshness(market_capture_ts: datetime) -> Freshness:
    """`analysis_timestamp` se captura aquí, al FINAL del procesamiento
    (justo antes de responder) -- garantiza por construcción
    `analysis_timestamp >= market_capture_ts` (el mercado se capturó en
    algún punto DURANTE el procesamiento, siempre antes de terminarlo),
    nunca un `data_freshness_seconds` negativo. Capturarlo al inicio del
    request (como en una versión anterior de este código) podía dar
    negativo, porque `market_capture_ts` se obtiene DESPUÉS del inicio
    del request (dentro de `resolve_ticker`)."""
    analysis_timestamp = datetime.now(timezone.utc)
    return Freshness(
        analysis_timestamp=analysis_timestamp,
        market_timestamp=market_capture_ts,
        data_freshness_seconds=(analysis_timestamp - market_capture_ts).total_seconds(),
    )
