"""Tests de `src/uncertainty/quality_score.py` (Paso 7). Ver el Design
Proposal aprobado explícitamente antes de esta implementación -- fórmulas,
normalización y pesos (`data_completeness=0.18, match_confidence_gap=0.22,
missing_critical=0.18, bookmaker_dispersion=0.15, sample_size=0.10,
market_liquidity=0.07, freshness=0.10`) son exactamente los aprobados ahí.

Todo sintético -- ninguna dependencia de `data/engine.db`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.pricing.odds_consensus import ConsensusNoVigResult
from src.uncertainty.quality_score import (
    CONFIDENCE_METHOD,
    DEFAULT_WEIGHTS,
    compute_quality_score,
)


def _record(
    data_completeness_score=1.0,
    match_confidence=1.0,
    missing_fields=None,
    market=None,
    source_timestamps=None,
):
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_1",
        participant_a="Away",
        participant_b="Home",
        market=market or MarketData(),
        data_quality=DataQuality(
            data_completeness_score=data_completeness_score,
            match_confidence=match_confidence,
            missing_fields=missing_fields or [],
            source_timestamps=source_timestamps or {},
        ),
    )


def _consensus(bookmaker_count=5, dispersion=0.0):
    return ConsensusNoVigResult(
        p_consensus_no_vig_yes=0.5,
        p_consensus_no_vig_no=0.5,
        bookmaker_count=bookmaker_count,
        per_bookmaker_timestamps={},
        freshness=None,
        dispersion=dispersion,
        event_match_confidence=1.0,
    )


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# Componentes individuales
# ---------------------------------------------------------------------


def test_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_data_completeness_reused_directly():
    record = _record(data_completeness_score=0.42)
    result = compute_quality_score(record, now=NOW)
    assert result.components["data_completeness"] == 0.42


def test_data_completeness_none_when_unavailable():
    record = _record(data_completeness_score=None)
    result = compute_quality_score(record, now=NOW)
    assert result.components["data_completeness"] is None


def test_match_confidence_gap_at_threshold_is_zero():
    record = _record(match_confidence=EVENT_NAME_MATCH_MIN_CONFIDENCE)
    result = compute_quality_score(record, now=NOW)
    assert result.components["match_confidence_gap"] == pytest.approx(0.0)


def test_match_confidence_gap_at_perfect_confidence_is_one():
    record = _record(match_confidence=1.0)
    result = compute_quality_score(record, now=NOW)
    assert result.components["match_confidence_gap"] == pytest.approx(1.0)


def test_match_confidence_gap_below_threshold_clips_to_zero():
    record = _record(match_confidence=0.0)
    result = compute_quality_score(record, now=NOW)
    assert result.components["match_confidence_gap"] == 0.0


def test_match_confidence_gap_none_when_unavailable():
    record = _record(match_confidence=None)
    result = compute_quality_score(record, now=NOW)
    assert result.components["match_confidence_gap"] is None


def test_missing_critical_all_core_fields_present():
    record = _record(missing_fields=[])
    result = compute_quality_score(record, now=NOW)
    assert result.components["missing_critical"] == 1.0


def test_missing_critical_all_core_fields_missing():
    from src.quality.completeness import CORE_FIELDS

    record = _record(missing_fields=list(CORE_FIELDS))
    result = compute_quality_score(record, now=NOW)
    assert result.components["missing_critical"] == 0.0


def test_missing_critical_never_none():
    """missing_fields siempre existe (lista vacía por defecto) -- este
    componente nunca es None."""
    record = _record(missing_fields=[])
    result = compute_quality_score(record, now=NOW)
    assert result.components["missing_critical"] is not None


def test_bookmaker_dispersion_zero_is_full_confidence():
    result = compute_quality_score(_record(), consensus=_consensus(dispersion=0.0), now=NOW)
    assert result.components["bookmaker_dispersion"] == pytest.approx(1.0)


def test_bookmaker_dispersion_at_cutoff_is_zero():
    result = compute_quality_score(_record(), consensus=_consensus(dispersion=0.10), now=NOW)
    assert result.components["bookmaker_dispersion"] == pytest.approx(0.0)


def test_bookmaker_dispersion_none_when_consensus_missing():
    result = compute_quality_score(_record(), consensus=None, now=NOW)
    assert result.components["bookmaker_dispersion"] is None


def test_sample_size_saturates_at_target():
    result = compute_quality_score(_record(), consensus=_consensus(bookmaker_count=10), now=NOW)
    assert result.components["sample_size"] == pytest.approx(1.0)


def test_sample_size_none_when_zero_bookmakers():
    result = compute_quality_score(_record(), consensus=_consensus(bookmaker_count=0), now=NOW)
    assert result.components["sample_size"] is None


def test_market_liquidity_uses_volume_first():
    record = _record(market=MarketData(volume=50000.0, open_interest=999999.0))
    result = compute_quality_score(record, now=NOW)
    assert result.components["market_liquidity"] == pytest.approx(1.0)


def test_market_liquidity_falls_back_to_open_interest():
    record = _record(market=MarketData(volume=None, open_interest=25000.0))
    result = compute_quality_score(record, now=NOW)
    assert result.components["market_liquidity"] == pytest.approx(0.5)


def test_market_liquidity_none_when_both_missing():
    record = _record(market=MarketData(volume=None, open_interest=None))
    result = compute_quality_score(record, now=NOW)
    assert result.components["market_liquidity"] is None


def test_market_liquidity_never_uses_liquidity_field():
    """Hallazgo del Design Proposal: `liquidity` es inutilizable (siempre
    0 en los datos reales observados) -- nunca se usa como base."""
    record = _record(market=MarketData(volume=None, open_interest=None, liquidity=999999.0))
    result = compute_quality_score(record, now=NOW)
    assert result.components["market_liquidity"] is None


def test_freshness_zero_age_is_full_confidence():
    record = _record(source_timestamps={"mlb": NOW})
    result = compute_quality_score(record, now=NOW)
    assert result.components["freshness"] == pytest.approx(1.0)


def test_freshness_at_one_hour_is_zero():
    record = _record(source_timestamps={"mlb": NOW - timedelta(hours=1)})
    result = compute_quality_score(record, now=NOW)
    assert result.components["freshness"] == pytest.approx(0.0)


def test_freshness_uses_oldest_timestamp():
    record = _record(source_timestamps={"mlb": NOW, "kalshi": NOW - timedelta(minutes=30)})
    result = compute_quality_score(record, now=NOW)
    assert result.components["freshness"] == pytest.approx(0.5)


def test_freshness_none_when_no_timestamps():
    record = _record(source_timestamps={})
    result = compute_quality_score(record, now=NOW)
    assert result.components["freshness"] is None


# ---------------------------------------------------------------------
# Agregación
# ---------------------------------------------------------------------


def test_confidence_method_always_heuristic_v1():
    result = compute_quality_score(_record(), now=NOW)
    assert result.confidence_method == CONFIDENCE_METHOD == "HEURISTIC_V1"


def test_all_components_perfect_yields_confidence_one():
    record = _record(
        data_completeness_score=1.0,
        match_confidence=1.0,
        missing_fields=[],
        market=MarketData(volume=100000.0),
        source_timestamps={"mlb": NOW},
    )
    result = compute_quality_score(record, consensus=_consensus(bookmaker_count=10, dispersion=0.0), now=NOW)
    assert result.confidence == pytest.approx(1.0)
    assert set(result.weights.keys()) == set(DEFAULT_WEIGHTS.keys())


def test_named_case_low_completeness_yields_low_confidence():
    """Caso nombrado explícitamente por PLAN_PHASE2.md §13: "P_model=0.64
    con baja completeness ⇒ confidence bajo"."""
    from src.quality.completeness import CORE_FIELDS

    record = _record(
        data_completeness_score=0.30,
        match_confidence=0.75,
        missing_fields=list(CORE_FIELDS[:4]),
        market=MarketData(volume=None, open_interest=None),
        source_timestamps={"mlb": NOW - timedelta(minutes=50)},
    )
    result = compute_quality_score(record, consensus=_consensus(bookmaker_count=2, dispersion=0.08), now=NOW)

    assert result.confidence is not None
    assert result.confidence < 0.5  # "confidence bajo"


def test_missing_component_redistributes_weight_exactly():
    """dispersion no disponible (consensus=None) -- el peso de
    bookmaker_dispersion Y sample_size se redistribuye entre el resto
    (ambos dependen de `consensus`). data_completeness=0.5, resto=1.0."""
    record = _record(
        data_completeness_score=0.5,
        match_confidence=1.0,
        missing_fields=[],
        market=MarketData(volume=100000.0),
        source_timestamps={"mlb": NOW},
    )
    result = compute_quality_score(record, consensus=None, now=NOW)

    remaining_weight = (
        DEFAULT_WEIGHTS["data_completeness"]
        + DEFAULT_WEIGHTS["match_confidence_gap"]
        + DEFAULT_WEIGHTS["missing_critical"]
        + DEFAULT_WEIGHTS["market_liquidity"]
        + DEFAULT_WEIGHTS["freshness"]
    )
    weighted_sum = (
        DEFAULT_WEIGHTS["data_completeness"] * 0.5
        + DEFAULT_WEIGHTS["match_confidence_gap"] * 1.0
        + DEFAULT_WEIGHTS["missing_critical"] * 1.0
        + DEFAULT_WEIGHTS["market_liquidity"] * 1.0
        + DEFAULT_WEIGHTS["freshness"] * 1.0
    )
    expected_confidence = weighted_sum / remaining_weight

    assert result.confidence == pytest.approx(expected_confidence)
    assert "bookmaker_dispersion" not in result.weights
    assert "sample_size" not in result.weights
    assert result.components["bookmaker_dispersion"] is None
    assert result.components["sample_size"] is None
    # weights de salida son los REDISTRIBUIDOS de este cálculo, no los estáticos
    assert result.weights["data_completeness"] == pytest.approx(
        DEFAULT_WEIGHTS["data_completeness"] / remaining_weight
    )
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_confidence_is_none_when_total_weight_is_zero():
    """Caso degenerado (§9: nunca se fabrica un valor): si la
    configuración de pesos asigna 0 a TODOS los componentes -- incluido
    `missing_critical`, el único que en la práctica siempre está
    disponible -- no hay ningún peso sobre el que promediar, y
    `confidence` es `None` explícitamente en vez de inventarse un 0.0."""
    zero_weights = {name: 0.0 for name in DEFAULT_WEIGHTS}
    result = compute_quality_score(_record(), consensus=_consensus(), now=NOW, weights=zero_weights)

    assert result.confidence is None
    assert result.weights == {}


def test_missing_critical_is_the_only_component_never_none_in_practice():
    """`missing_critical` es calculable siempre que `missing_fields`
    exista (por defecto lista vacía) -- documentado como el único
    componente que en la práctica garantiza que `confidence` nunca sea
    `None` bajo los pesos por defecto."""
    record = _record(
        data_completeness_score=None,
        match_confidence=None,
        missing_fields=[],
        market=MarketData(volume=None, open_interest=None),
        source_timestamps={},
    )
    result = compute_quality_score(record, consensus=None, now=NOW)

    assert result.components["missing_critical"] is not None
    assert result.confidence is not None


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        compute_quality_score(_record(), now=datetime(2026, 7, 26, 12, 0))


def test_custom_weights_are_respected():
    custom = {
        "data_completeness": 1.0,
        "match_confidence_gap": 0.0,
        "missing_critical": 0.0,
        "bookmaker_dispersion": 0.0,
        "sample_size": 0.0,
        "market_liquidity": 0.0,
        "freshness": 0.0,
    }
    record = _record(data_completeness_score=0.3, match_confidence=1.0)
    result = compute_quality_score(record, now=NOW, weights=custom)
    assert result.confidence == pytest.approx(0.3)


# ---------------------------------------------------------------------
# Integración cruzada de módulos (sintética, sin red): Fase 1
# (normalize_mlb_game) + Paso 4 (compute_consensus_no_vig) + Paso 7
# (compute_quality_score), cada uno con su función REAL, no reimplementada
# ni mockeada -- solo los datos de entrada son sintéticos.
# ---------------------------------------------------------------------


def test_integration_real_normalization_and_consensus_feed_quality_score():
    from src.normalization.mlb_normalizer import normalize_mlb_game
    from src.pricing.odds_consensus import LabeledBookmakerOdds, compute_consensus_no_vig
    from src.quality.completeness import compute_completeness_score, dedupe_missing_fields

    start = datetime(2026, 7, 26, 22, 40, tzinfo=timezone.utc)
    game_raw = {
        "gamePk": 999999,
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "gameDate": start.isoformat().replace("+00:00", "Z"),
        "teams": {
            "away": {"team": {"id": 1, "name": "Away Team"}, "leagueRecord": {"wins": 10, "losses": 5}},
            "home": {"team": {"id": 2, "name": "Home Team"}, "leagueRecord": {"wins": 8, "losses": 7}},
        },
        "venue": {"name": "Test Park"},
    }
    record, missing = normalize_mlb_game(game_raw)
    record.data_quality.missing_fields = dedupe_missing_fields(missing)
    record.data_quality.data_completeness_score = compute_completeness_score(
        record.data_quality.missing_fields, "MLB"
    )
    record.data_quality.match_confidence = 0.95
    record.data_quality.source_timestamps = {"mlb": NOW}
    record.market = MarketData(volume=30000.0)

    bookmaker_odds = [
        LabeledBookmakerOdds(bookmaker="book_a", decimal_odds_yes=1.90, decimal_odds_no=2.05, last_update=NOW),
        LabeledBookmakerOdds(bookmaker="book_b", decimal_odds_yes=1.95, decimal_odds_no=2.00, last_update=NOW),
        LabeledBookmakerOdds(bookmaker="book_c", decimal_odds_yes=1.88, decimal_odds_no=2.08, last_update=NOW),
    ]
    consensus = compute_consensus_no_vig(
        odds_api_key_configured=True,
        source_participant_a="Away Team",
        source_participant_b="Home Team",
        source_start_time=start,
        target_record=record,
        bookmaker_odds=bookmaker_odds,
        as_of=NOW,
    )
    assert consensus.bookmaker_count == 3  # confirma que el consenso real sí se calculó, no NOT_CONFIGURED

    result = compute_quality_score(record, consensus=consensus, now=NOW)

    assert result.confidence is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence_method == "HEURISTIC_V1"
    assert result.components["bookmaker_dispersion"] is not None
    assert result.components["sample_size"] == pytest.approx(3 / 5)
    assert result.components["data_completeness"] == record.data_quality.data_completeness_score
