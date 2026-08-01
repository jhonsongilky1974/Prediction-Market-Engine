"""Tests de `build_confidence_profile` (Fase 4, Paso 4.1). Ver
`ORCHESTRATOR_SPEC.md` §9.2 -- mapeo `PROVISIONAL_V1`, cubre la tabla
completa (cada campo, incluida la redistribución cuando un componente
de origen falta) y el invariante `operational_safety + operational_risk
== 100`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.orchestration.confidence_profile_builder import build_confidence_profile
from src.uncertainty.quality_score import QualityScoreOutput

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _quality_score(**components_override) -> QualityScoreOutput:
    components = {
        "data_completeness": 0.9,
        "match_confidence_gap": 0.5,
        "missing_critical": 0.7,
        "bookmaker_dispersion": 0.6,
        "sample_size": 0.4,
        "market_liquidity": 0.2,
        "freshness": 0.8,
    }
    components.update(components_override)
    return QualityScoreOutput(
        confidence=0.65,
        confidence_method="HEURISTIC_V1",
        confidence_config_version="quality_score_v1",
        components=components,
    )


def test_data_quality_reuses_data_completeness_component_rescaled_to_percent():
    profile = build_confidence_profile(_quality_score(data_completeness=0.9), "opp-1", NOW)
    assert profile.data_quality == 90.0


def test_market_quality_averages_the_three_market_components_rescaled():
    # (0.6 + 0.4 + 0.2) / 3 = 0.4 -> 40.0
    profile = build_confidence_profile(
        _quality_score(bookmaker_dispersion=0.6, sample_size=0.4, market_liquidity=0.2), "opp-1", NOW
    )
    assert profile.market_quality == 40.0


def test_market_quality_redistributes_when_one_component_missing():
    # solo bookmaker_dispersion/sample_size disponibles -> promedio de esos 2
    profile = build_confidence_profile(
        _quality_score(bookmaker_dispersion=0.8, sample_size=0.4, market_liquidity=None), "opp-1", NOW
    )
    assert profile.market_quality == pytest.approx(60.0)  # (0.8+0.4)/2 * 100


def test_market_quality_none_when_all_three_components_missing():
    profile = build_confidence_profile(
        _quality_score(bookmaker_dispersion=None, sample_size=None, market_liquidity=None), "opp-1", NOW
    )
    assert profile.market_quality is None


def test_operational_safety_and_risk_sum_to_100_invariant():
    profile = build_confidence_profile(_quality_score(freshness=0.8), "opp-1", NOW)
    assert profile.operational_safety == 80.0
    assert profile.operational_risk == 20.0
    assert profile.operational_safety + profile.operational_risk == 100.0


def test_operational_safety_and_risk_both_none_when_freshness_missing():
    profile = build_confidence_profile(_quality_score(freshness=None), "opp-1", NOW)
    assert profile.operational_safety is None
    assert profile.operational_risk is None


def test_model_reliability_always_none_no_evaluation_history_exists():
    """Regla 3 -- cero EvaluationRecord existen todavía (Coverage
    Gate/auditoría de labels de Fase 4, sin ejecutar). Nunca se fabrica."""
    profile = build_confidence_profile(_quality_score(), "opp-1", NOW)
    assert profile.model_reliability is None


def test_aggregate_confidence_reuses_quality_score_confidence_rescaled():
    profile = build_confidence_profile(_quality_score(), "opp-1", NOW)
    assert profile.aggregate_confidence == 65.0


def test_quality_score_component_ref_traces_to_confidence_config_version():
    profile = build_confidence_profile(_quality_score(), "opp-1", NOW)
    assert profile.quality_score_component_ref == "quality_score_v1"


def test_opportunity_id_and_computed_at_propagate():
    profile = build_confidence_profile(_quality_score(), "opp-42", NOW)
    assert profile.opportunity_id == "opp-42"
    assert profile.computed_at == NOW
