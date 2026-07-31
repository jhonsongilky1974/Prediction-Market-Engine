"""Tests de compute_analysis_health() (Fase 3, Paso 3.7). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.7, y CONTRACTS_FASE3.md §5 (invariante
rectificado durante este paso, ver CONTINUITY.md §0.14) -- test de
arquitectura que confirma que soft_score.py NUNCA importa src/health/,
mientras que hard_rules.py sí puede, exclusivamente vía el contrato
(schemas.py), nunca la lógica de cómputo (analysis_health.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.health.analysis_health import compute_analysis_health
from src.models.schemas import DataQuality, NormalizedRecord, Sport
from src.uncertainty.quality_score import QualityScoreOutput
from tests.unit.fase3_factories import make_evidence_item

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    base = dict(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
    )
    base.update(overrides)
    return NormalizedRecord(**base)


def _quality_output(**overrides) -> QualityScoreOutput:
    base = dict(
        confidence=0.7,
        confidence_method="HEURISTIC_V1",
        confidence_config_version="quality_score_v1",
        components={"data_completeness": 0.8, "bookmaker_dispersion": 0.6},
        weights={},
    )
    base.update(overrides)
    return QualityScoreOutput(**base)


# ---------------------------------------------------------------------
# completeness_signal / consistency_signal -- escalado [0,1] -> [0,100]
# ---------------------------------------------------------------------


def test_completeness_and_consistency_signals_scaled_to_percent():
    health = compute_analysis_health("opp-1", _record(), _quality_output(), [], now=NOW)
    assert health.completeness_signal == pytest.approx(80.0)
    assert health.consistency_signal == pytest.approx(60.0)


def test_signals_are_none_when_components_absent():
    quality_output = _quality_output(components={})
    health = compute_analysis_health("opp-1", _record(), quality_output, [], now=NOW)
    assert health.completeness_signal is None
    assert health.consistency_signal is None


# ---------------------------------------------------------------------
# evidence_density
# ---------------------------------------------------------------------


def test_evidence_density_counts_evidence_items():
    items = [make_evidence_item(), make_evidence_item(fact="Otro hecho")]
    health = compute_analysis_health("opp-1", _record(), _quality_output(), items, now=NOW)
    assert health.evidence_density == 2


def test_evidence_density_zero_when_no_items():
    health = compute_analysis_health("opp-1", _record(), _quality_output(), [], now=NOW)
    assert health.evidence_density == 0


# ---------------------------------------------------------------------
# staleness_seconds -- del timestamp de fuente más viejo
# ---------------------------------------------------------------------


def test_staleness_seconds_computed_from_oldest_source_timestamp():
    record = _record(
        data_quality=DataQuality(
            source_timestamps={
                "mlb_stats_api": NOW - timedelta(seconds=300),
                "kalshi": NOW - timedelta(seconds=120),
            }
        )
    )
    health = compute_analysis_health("opp-1", record, _quality_output(), [], now=NOW)
    assert health.staleness_seconds == pytest.approx(300.0)


def test_staleness_seconds_none_when_no_source_timestamps():
    record = _record(data_quality=DataQuality(source_timestamps={}))
    health = compute_analysis_health("opp-1", record, _quality_output(), [], now=NOW)
    assert health.staleness_seconds is None


# ---------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------


def test_warning_when_staleness_not_computable():
    record = _record(data_quality=DataQuality(source_timestamps={}))
    health = compute_analysis_health("opp-1", record, _quality_output(), [], now=NOW)
    assert any("staleness" in w for w in health.warnings)


def test_warning_when_no_evidence():
    health = compute_analysis_health("opp-1", _record(), _quality_output(), [], now=NOW)
    assert any("evidencia" in w for w in health.warnings)


def test_no_warnings_when_everything_available():
    record = _record(data_quality=DataQuality(source_timestamps={"mlb_stats_api": NOW - timedelta(seconds=10)}))
    health = compute_analysis_health("opp-1", record, _quality_output(), [make_evidence_item()], now=NOW)
    assert health.warnings == []


# ---------------------------------------------------------------------
# Pureza y now naive
# ---------------------------------------------------------------------


def test_same_input_produces_same_output():
    health_a = compute_analysis_health("opp-1", _record(), _quality_output(), [], now=NOW)
    health_b = compute_analysis_health("opp-1", _record(), _quality_output(), [], now=NOW)
    assert health_a == health_b


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        compute_analysis_health(
            "opp-1", _record(), _quality_output(), [], now=datetime(2026, 7, 30, 12, 0, 0)
        )


# ---------------------------------------------------------------------
# Regla de dependencia RECTIFICADA (Principio 5, CONTRACTS_FASE3.md §5):
# soft_score.py NUNCA importa src/health/; hard_rules.py puede, solo el
# contrato (schemas.py), nunca la lógica de cómputo (analysis_health.py)
# ---------------------------------------------------------------------


def _imported_modules(file_path: str) -> set:
    import ast

    tree = ast.parse(open(file_path, encoding="utf-8").read())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_soft_score_never_imports_health_module():
    import src.policy.soft_score as soft_score_module

    imported = _imported_modules(soft_score_module.__file__)
    forbidden = {"src.health.analysis_health", "src.health.schemas"}
    assert not (imported & forbidden), imported & forbidden


def test_hard_rules_imports_only_health_schema_never_analysis_health_logic():
    import src.policy.hard_rules as hard_rules_module

    imported = _imported_modules(hard_rules_module.__file__)
    assert "src.health.schemas" in imported  # ya usado por temporarily_stale_data, Paso 3.4.3
    assert "src.health.analysis_health" not in imported


def test_decision_never_imports_analysis_health_computation_logic():
    """decide() (Paso 3.4.5) recibe un AnalysisHealth ya calculado como
    parámetro -- nunca debe importar la función de cómputo, solo el
    contrato (a través de hard_rules.py)."""
    import src.policy.decision as decision_module

    imported = _imported_modules(decision_module.__file__)
    assert "src.health.analysis_health" not in imported
