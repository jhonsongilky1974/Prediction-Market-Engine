"""Tests de ExplanationOutput (Fase 3, Paso 3.6). Ver CONTRACTS_FASE3.md
§17 -- adición contractual correctiva, misma exigencia de pruebas que
los 16 contratos originales del Paso 3.0 (invariantes, extra="forbid",
timestamps tz-aware, round-trip completo).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.explainability.schemas import ExplanationOutput
from tests.unit.fase3_factories import NOW, assert_round_trip, make_explanation_output


def test_construction_with_valid_values_is_valid():
    explanation = make_explanation_output()
    assert explanation.opportunity_id == "opp-1"
    assert explanation.evaluation_id == "oe-1"


def test_empty_headline_raises():
    with pytest.raises(ValidationError, match="headline"):
        make_explanation_output(headline="   ")


def test_empty_reasons_explained_raises():
    with pytest.raises(ValidationError, match="reasons_explained"):
        make_explanation_output(reasons_explained=[])


def test_naive_generated_at_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_explanation_output(generated_at=datetime(2026, 7, 30, 12, 0, 0))


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        ExplanationOutput(
            opportunity_id="opp-1",
            evaluation_id="oe-1",
            headline="ENTER",
            reasons_explained=["x"],
            generated_at=NOW,
            unexpected_field="z",
        )


def test_evidence_and_disclaimers_can_be_empty():
    explanation = make_explanation_output(evidence_for=[], evidence_against=[], disclaimers=[])
    assert explanation.evidence_for == []
    assert explanation.evidence_against == []
    assert explanation.disclaimers == []


def test_round_trip_serialization():
    assert_round_trip(make_explanation_output())
    assert_round_trip(
        make_explanation_output(
            disclaimers=["Probabilidad del modelo sin calibrar (calibration_version=None)."],
            evidence_against=["Divergencia significativa"],
        )
    )
