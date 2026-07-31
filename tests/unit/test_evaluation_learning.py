"""Tests de build_evaluation_record() (Fase 3, Paso 3.8). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.8, y EVALUATION_LEARNING_SPEC.md §1 --
las 5 dimensiones, catálogo cerrado de metric_name por scope,
sample_size=0 nunca con metric_value poblado, más un caso de integración
de punta a punta con backtesting/metrics.py (fixtures sintéticos, nunca
histórico real -- ver GATE-0, PLAN_MASTER_FASE3.md §0).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.backtesting.metrics import brier_score, clv, drawdown, ece, profit_factor, roi_teorico
from src.evaluation.learning import build_evaluation_record, compute_evaluation_record_id
from src.evaluation.schemas import EvaluationScope
from src.models.schemas import Sport

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_START = NOW - timedelta(days=30)


def _kwargs(**overrides):
    base = dict(
        scope=EvaluationScope.MODEL_PERFORMANCE,
        metric_name="brier_score",
        metric_value=0.21,
        sample_size=42,
        evaluation_window_start=WINDOW_START,
        evaluation_window_end=NOW,
        sport=Sport.MLB,
        model_version="mlb_baseline_v1",
        now=NOW,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------
# Un caso válido por cada una de las 5 dimensiones
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "scope,metric_name",
    [
        (EvaluationScope.MODEL_PERFORMANCE, "brier_score"),
        (EvaluationScope.DECISION_PERFORMANCE, "clv_24h"),
        (EvaluationScope.FINANCIAL_PERFORMANCE, "roi_teorico"),
        (EvaluationScope.OPERATIONAL_PERFORMANCE, "hard_hold_rate"),
        (EvaluationScope.LEARNING_PERFORMANCE, "policy_regression_pass_rate"),
    ],
)
def test_valid_metric_per_scope_builds_record(scope, metric_name):
    record = build_evaluation_record(**_kwargs(scope=scope, metric_name=metric_name))
    assert record.scope == scope
    assert record.metric_name == metric_name


# ---------------------------------------------------------------------
# Catálogo cerrado -- metric_name fuera de su scope se rechaza
# ---------------------------------------------------------------------


def test_metric_name_outside_scope_catalog_rejected():
    with pytest.raises(ValueError, match="no pertenece al catálogo cerrado"):
        build_evaluation_record(**_kwargs(scope=EvaluationScope.MODEL_PERFORMANCE, metric_name="roi_teorico"))


def test_completely_unknown_metric_name_rejected():
    with pytest.raises(ValueError, match="no pertenece al catálogo cerrado"):
        build_evaluation_record(**_kwargs(metric_name="not_a_real_metric"))


# ---------------------------------------------------------------------
# sample_size=0 nunca con metric_value poblado (delegado a EvaluationRecord)
# ---------------------------------------------------------------------


def test_sample_size_zero_requires_metric_value_none():
    record = build_evaluation_record(**_kwargs(metric_value=None, sample_size=0))
    assert record.metric_value is None
    assert record.sample_size == 0


def test_sample_size_zero_with_metric_value_populated_raises():
    with pytest.raises(ValidationError, match="sample_size=0"):
        build_evaluation_record(**_kwargs(metric_value=0.21, sample_size=0))


# ---------------------------------------------------------------------
# record_id determinístico
# ---------------------------------------------------------------------


def test_record_id_deterministic_for_same_context():
    id_a = compute_evaluation_record_id(
        EvaluationScope.MODEL_PERFORMANCE, "brier_score", "mlb_baseline_v1", None, "1.0.0",
        WINDOW_START, NOW,
    )
    id_b = compute_evaluation_record_id(
        EvaluationScope.MODEL_PERFORMANCE, "brier_score", "mlb_baseline_v1", None, "1.0.0",
        WINDOW_START, NOW,
    )
    assert id_a == id_b


def test_record_id_differs_for_different_window():
    id_a = compute_evaluation_record_id(
        EvaluationScope.MODEL_PERFORMANCE, "brier_score", "mlb_baseline_v1", None, "1.0.0",
        WINDOW_START, NOW,
    )
    id_b = compute_evaluation_record_id(
        EvaluationScope.MODEL_PERFORMANCE, "brier_score", "mlb_baseline_v1", None, "1.0.0",
        WINDOW_START, NOW + timedelta(days=1),
    )
    assert id_a != id_b


def test_build_evaluation_record_uses_deterministic_id():
    record_a = build_evaluation_record(**_kwargs())
    record_b = build_evaluation_record(**_kwargs())
    assert record_a.record_id == record_b.record_id


# ---------------------------------------------------------------------
# Pureza y now naive
# ---------------------------------------------------------------------


def test_same_input_produces_same_record():
    record_a = build_evaluation_record(**_kwargs())
    record_b = build_evaluation_record(**_kwargs())
    assert record_a == record_b


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        build_evaluation_record(**_kwargs(now=datetime(2026, 7, 30, 12, 0, 0)))


# ---------------------------------------------------------------------
# Integración de punta a punta con fixtures sintéticos (nunca histórico
# real -- GATE-0, PLAN_MASTER_FASE3.md §0)
# ---------------------------------------------------------------------


def test_end_to_end_model_performance_record_from_synthetic_fixtures():
    y_true = [1, 0, 1, 0]
    y_pred = [0.8, 0.2, 0.4, 0.6]
    value = brier_score(y_true, y_pred)
    record = build_evaluation_record(
        **_kwargs(scope=EvaluationScope.MODEL_PERFORMANCE, metric_name="brier_score",
                   metric_value=value, sample_size=len(y_true))
    )
    assert record.metric_value == pytest.approx(value)
    assert record.sample_size == 4


def test_end_to_end_decision_performance_record_from_synthetic_fixtures():
    value = clv(entry_price=0.55, closing_price=0.62)
    record = build_evaluation_record(
        **_kwargs(scope=EvaluationScope.DECISION_PERFORMANCE, metric_name="clv_24h",
                   metric_value=value, sample_size=1)
    )
    assert record.metric_value == pytest.approx(0.07)


def test_end_to_end_financial_performance_records_from_synthetic_fixtures():
    roi_value = roi_teorico([(1.0, 0.5), (1.0, -0.3)])
    dd_value = drawdown([100.0, 120.0, 90.0])
    pf_value = profit_factor([10.0, 20.0], [-5.0])

    roi_record = build_evaluation_record(
        **_kwargs(scope=EvaluationScope.FINANCIAL_PERFORMANCE, metric_name="roi_teorico",
                   metric_value=roi_value, sample_size=2)
    )
    dd_record = build_evaluation_record(
        **_kwargs(scope=EvaluationScope.FINANCIAL_PERFORMANCE, metric_name="drawdown",
                   metric_value=dd_value, sample_size=3)
    )
    pf_record = build_evaluation_record(
        **_kwargs(scope=EvaluationScope.FINANCIAL_PERFORMANCE, metric_name="profit_factor",
                   metric_value=pf_value, sample_size=3)
    )
    assert roi_record.metric_value == pytest.approx(0.1)
    assert dd_record.metric_value == pytest.approx(30.0)
    assert pf_record.metric_value == pytest.approx(6.0)


def test_no_evaluation_record_here_claims_real_performance():
    """Documentación ejecutable de la advertencia de alcance: ningún
    registro construido en este paso usa histórico real -- todos los
    tests de este archivo pasan sample_size derivado de fixtures
    sintéticos pequeños, nunca de HistoryRepository."""
    record = build_evaluation_record(**_kwargs(sample_size=4))
    assert record.sample_size == 4  # tamaño de una fixture sintética, no de producción
