"""Tests de AnalysisHealth (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md §5.
Nota: el invariante "nunca usado como input del Soft Score" (Principio 5)
se prueba a nivel de arquitectura en el Paso 3.7, no aquí -- este archivo
solo prueba el contrato de datos en sí.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.health.schemas import AnalysisHealth
from tests.unit.fase3_factories import NOW, assert_round_trip, make_analysis_health


def test_construction_with_valid_values_is_valid():
    health = make_analysis_health()
    assert health.completeness_signal == 80.0


def test_all_optional_fields_can_be_none():
    health = make_analysis_health(
        completeness_signal=None,
        consistency_signal=None,
        evidence_density=None,
        staleness_seconds=None,
    )
    assert health.completeness_signal is None


@pytest.mark.parametrize("field_name", ["completeness_signal", "consistency_signal"])
def test_out_of_range_percent_raises(field_name):
    with pytest.raises(ValidationError, match=r"fuera de \[0,100\]"):
        make_analysis_health(**{field_name: 150.0})


def test_negative_evidence_density_raises():
    with pytest.raises(ValidationError, match="evidence_density"):
        make_analysis_health(evidence_density=-1)


def test_negative_staleness_raises():
    with pytest.raises(ValidationError, match="staleness_seconds"):
        make_analysis_health(staleness_seconds=-1.0)


def test_naive_computed_at_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_analysis_health(computed_at=datetime(2026, 7, 30, 12, 0, 0))


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        AnalysisHealth(opportunity_id="opp-1", computed_at=NOW, unexpected_field="x")


def test_round_trip_serialization():
    assert_round_trip(make_analysis_health())
    assert_round_trip(make_analysis_health(warnings=["stale data"]))
