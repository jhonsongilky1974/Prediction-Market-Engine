"""Tests de check_eligibility() (Fase 3, Paso 3.4.1). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.1, y POLICY_ENGINE_SPEC.md §1.1,
etapa [1] -- un caso por campo obligatorio ausente, más el caso feliz.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.schemas import Sport
from src.policy.eligibility import check_eligibility
from src.signals.signal_schema import Side

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _kwargs(**overrides):
    base = dict(
        opportunity_id="opp-1",
        event_id="evt-1",
        sport=Sport.MLB,
        side=Side.YES,
        generated_at=NOW,
        now=NOW,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------
# Caso feliz
# ---------------------------------------------------------------------


def test_all_fields_present_is_eligible():
    result = check_eligibility(**_kwargs())
    assert result.is_eligible is True
    assert result.ineligibility_reasons == []
    assert result.opportunity_id == "opp-1"
    assert result.evaluated_at == NOW


# ---------------------------------------------------------------------
# Un caso por campo obligatorio ausente
# ---------------------------------------------------------------------


def test_missing_event_id_is_not_eligible():
    result = check_eligibility(**_kwargs(event_id=None))
    assert result.is_eligible is False
    assert any("event_id" in r for r in result.ineligibility_reasons)


def test_empty_event_id_is_not_eligible():
    result = check_eligibility(**_kwargs(event_id="   "))
    assert result.is_eligible is False
    assert any("event_id" in r for r in result.ineligibility_reasons)


def test_missing_sport_is_not_eligible():
    result = check_eligibility(**_kwargs(sport=None))
    assert result.is_eligible is False
    assert any("sport" in r for r in result.ineligibility_reasons)


def test_missing_side_is_not_eligible():
    result = check_eligibility(**_kwargs(side=None))
    assert result.is_eligible is False
    assert any("side" in r for r in result.ineligibility_reasons)


def test_missing_generated_at_is_not_eligible():
    result = check_eligibility(**_kwargs(generated_at=None))
    assert result.is_eligible is False
    assert any("generated_at" in r for r in result.ineligibility_reasons)


# ---------------------------------------------------------------------
# Múltiples campos ausentes a la vez -- todos los motivos reportados
# ---------------------------------------------------------------------


def test_all_fields_missing_reports_all_four_reasons():
    result = check_eligibility(**_kwargs(event_id=None, sport=None, side=None, generated_at=None))
    assert result.is_eligible is False
    assert len(result.ineligibility_reasons) == 4


# ---------------------------------------------------------------------
# No evalúa calidad de datos -- solo estructura
# ---------------------------------------------------------------------


def test_does_not_import_hard_rules_or_soft_score_or_decision():
    """Inspecciona únicamente las sentencias import (AST), no el texto
    completo del archivo -- el docstring del módulo menciona esos
    nombres en prosa explicando qué NO hace, lo cual no debe contar
    como una importación real."""
    import ast

    import src.policy.eligibility as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = {
        "src.policy.hard_rules",
        "src.policy.soft_score",
        "src.policy.decision",
        "src.policy.manifest",
        "src.policy.validation",
    }
    assert not (imported_modules & forbidden), imported_modules & forbidden


# ---------------------------------------------------------------------
# Pureza y validación de now
# ---------------------------------------------------------------------


def test_same_input_produces_same_output():
    result_a = check_eligibility(**_kwargs())
    result_b = check_eligibility(**_kwargs())
    assert result_a == result_b


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        check_eligibility(**_kwargs(now=datetime(2026, 7, 30, 12, 0, 0)))
