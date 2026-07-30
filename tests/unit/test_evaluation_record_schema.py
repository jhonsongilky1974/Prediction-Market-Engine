"""Tests de EvaluationRecord (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§14 y EVALUATION_LEARNING_SPEC.md §1.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.evaluation.schemas import EvaluationRecord, EvaluationScope
from tests.unit.fase3_factories import NOW, assert_round_trip, make_evaluation_record


def test_construction_with_valid_values_is_valid():
    record = make_evaluation_record()
    assert record.scope == EvaluationScope.MODEL_PERFORMANCE


def test_scope_has_exactly_5_dimensions():
    assert {member.value for member in EvaluationScope} == {
        "model_performance",
        "decision_performance",
        "financial_performance",
        "operational_performance",
        "learning_performance",
    }


def test_empty_metric_name_raises():
    with pytest.raises(ValidationError, match="metric_name"):
        make_evaluation_record(metric_name="  ")


def test_negative_sample_size_raises():
    with pytest.raises(ValidationError, match="sample_size"):
        make_evaluation_record(sample_size=-1)


def test_zero_sample_size_with_metric_value_raises():
    """Nunca se fabrica un valor sin muestras -- mismo principio no
    negociable de Fase 1/2, formalizado aquí a nivel de contrato."""
    with pytest.raises(ValidationError, match="sample_size=0"):
        make_evaluation_record(sample_size=0, metric_value=0.21)


def test_zero_sample_size_without_metric_value_is_valid():
    record = make_evaluation_record(sample_size=0, metric_value=None)
    assert record.metric_value is None


def test_confidence_interval_inverted_raises():
    with pytest.raises(ValidationError, match="confidence_interval"):
        make_evaluation_record(confidence_interval_low=0.5, confidence_interval_high=0.1)


def test_evaluation_window_inverted_raises():
    with pytest.raises(ValidationError, match="evaluation_window"):
        make_evaluation_record(
            evaluation_window_start=NOW, evaluation_window_end=NOW - timedelta(days=1)
        )


@pytest.mark.parametrize(
    "field_name", ["computed_at", "evaluation_window_start", "evaluation_window_end"]
)
def test_naive_timestamp_raises(field_name):
    with pytest.raises(ValidationError, match="tz-aware"):
        make_evaluation_record(**{field_name: datetime(2026, 7, 30, 12, 0, 0)})


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        EvaluationRecord(
            record_id="rec-1",
            scope=EvaluationScope.MODEL_PERFORMANCE,
            metric_name="brier_score",
            sample_size=0,
            computed_at=NOW,
            evaluation_window_start=NOW,
            evaluation_window_end=NOW,
            unexpected_field="x",
        )


def test_round_trip_serialization():
    assert_round_trip(make_evaluation_record())
    assert_round_trip(make_evaluation_record(sample_size=0, metric_value=None))
