"""Tests de `src.api.analysis_service.analyze_ticker` (Fase 5). Ver
`HTTP_SERVICE_SPEC.md`.

`resolve_ticker` (ya probado en `test_event_resolver.py`) se
monkeypatchea -- este archivo prueba únicamente que `analyze_ticker`
compone `AnalyzeResponse` correctamente a partir de una
`OpportunityEvaluation` real (`run_decision_pipeline`, Fase 4, sin
mockear -- se ejecuta de verdad contra `tmp_path`, nunca
`data/engine.db`)."""
from __future__ import annotations

from datetime import datetime, timezone

import src.api.analysis_service as analysis_service_module
from src.api.event_resolver import ResolvedEvent
from src.features.mlb_features import MlbFeatureInputs
from src.models.schemas import MarketData, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
MARKET_CAPTURE_TS = datetime(2026, 8, 1, 11, 59, 30, tzinfo=timezone.utc)


def _record():
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_test_1",
        market_id="KXMLBGAME-TEST-A",
        participant_a="Team A",
        participant_b="Team B",
        market=MarketData(yes_bid=0.40, yes_ask=0.45, no_bid=0.55, no_ask=0.60),
    )


def _patch_resolver(monkeypatch, record):
    resolved = ResolvedEvent(
        record=record,
        feature_inputs=MlbFeatureInputs(),
        feature_cutoff=NOW,
        sport=Sport.MLB,
        market_capture_ts=MARKET_CAPTURE_TS,
        enrichment_mode="full",
    )
    monkeypatch.setattr(analysis_service_module, "resolve_ticker", lambda ticker, repository, history_repository: resolved)


def test_analyze_ticker_composes_response_from_real_orchestrator(monkeypatch, tmp_path):
    _patch_resolver(monkeypatch, _record())
    repo = Repository(db_path=tmp_path / "hist.db")
    hist_repo = HistoryRepository(db_path=tmp_path / "hist.db")

    response = analysis_service_module.analyze_ticker(
        "KXMLBGAME-TEST-A", repository=repo, history_repository=hist_repo
    )

    assert response.ticker == "KXMLBGAME-TEST-A"
    assert response.event_id == "mlb_test_1"
    assert response.sport == "MLB"
    assert response.participant_a == "Team A"
    # MODEL_NOT_TRAINED en producción hoy -- honesto, no fabricado.
    assert response.p_model is None
    assert response.model_version is None
    assert response.p_market == 0.45  # yes_ask
    assert response.p_consensus_no_vig is None
    assert response.p_consensus_no_vig_unavailable_reason is not None
    assert response.net_ev_status == "UNKNOWN"  # D-3 sin resolver
    assert response.recommendation in ("ENTER", "WATCH", "PASS")
    assert len(response.recommendation_reasons) > 0
    assert response.policy_version
    assert response.freshness.market_timestamp == MARKET_CAPTURE_TS
    assert response.freshness.data_freshness_seconds >= 0
    assert response.freshness.analysis_timestamp >= MARKET_CAPTURE_TS
    assert response.enrichment_mode == "full"
    assert response.processing_time_ms >= 0


def test_analyze_ticker_most_influential_variables_sorted_by_strength_desc(monkeypatch, tmp_path):
    _patch_resolver(monkeypatch, _record())
    repo = Repository(db_path=tmp_path / "hist.db")
    hist_repo = HistoryRepository(db_path=tmp_path / "hist.db")

    response = analysis_service_module.analyze_ticker(
        "KXMLBGAME-TEST-A", repository=repo, history_repository=hist_repo
    )

    strengths = [v.strength for v in response.most_influential_variables if v.strength is not None]
    assert strengths == sorted(strengths, reverse=True)


def test_analyze_ticker_persists_real_opportunity_evaluation(monkeypatch, tmp_path):
    """Efecto secundario documentado (HTTP_SERVICE_SPEC.md §0): /analyze
    persiste igual que la corrida horaria real, no es de solo lectura."""
    _patch_resolver(monkeypatch, _record())
    repo = Repository(db_path=tmp_path / "hist.db")
    hist_repo = HistoryRepository(db_path=tmp_path / "hist.db")

    analysis_service_module.analyze_ticker("KXMLBGAME-TEST-A", repository=repo, history_repository=hist_repo)

    from src.opportunity.opportunity_repository import OpportunityRepository

    opp_repo = OpportunityRepository(db_path=repo.db_path)
    evaluation = opp_repo.get_latest_evaluation("opp:mlb_test_1:KXMLBGAME-TEST-A:YES")
    assert evaluation is not None
