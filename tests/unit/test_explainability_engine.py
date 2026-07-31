"""Tests de explain() (Fase 3, Paso 3.6). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.6, y EVIDENCE_EXPLAINABILITY_SPEC.md §2 -- casos ENTER/WATCH/PASS
con distintos disposition, disclaimers obligatorios, y el test de
arquitectura de imports (separación Principio 6).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.evidence.schemas import EvidenceDirection
from src.explainability.explainability_engine import explain
from src.policy.schemas import AbstentionDisposition, SignalReasonCode
from src.signals.signal_schema import SignalType
from tests.unit.fase3_factories import (
    NOW,
    make_evidence_item,
    make_policy_decision,
    make_signal_reason,
)

# ---------------------------------------------------------------------
# Trazabilidad: toda razón viene de PolicyDecision/EvidenceItem reales
# ---------------------------------------------------------------------


def test_reasons_explained_trace_every_signal_reason():
    reasons = [
        make_signal_reason(code=SignalReasonCode.SOFT_SCORE_BELOW_GLOBAL, detail="score bajo"),
        make_signal_reason(code=SignalReasonCode.CRITICAL_MINIMUM_NOT_MET, detail="ev_neto_strength falló"),
    ]
    policy_decision = make_policy_decision(reasons=reasons)
    explanation = explain(policy_decision, [], evaluation_id="oe-1", now=NOW)
    assert len(explanation.reasons_explained) == 2
    assert "score bajo" in explanation.reasons_explained[0]
    assert "ev_neto_strength falló" in explanation.reasons_explained[1]


def test_evidence_for_and_against_are_separated():
    evidence = [
        make_evidence_item(fact="Pitcher confirmado", direction=EvidenceDirection.FOR),
        make_evidence_item(fact="Confianza marginal", direction=EvidenceDirection.AGAINST),
    ]
    policy_decision = make_policy_decision()
    explanation = explain(policy_decision, evidence, evaluation_id="oe-1", now=NOW)
    assert explanation.evidence_for == ["Pitcher confirmado"]
    assert explanation.evidence_against == ["Confianza marginal"]


def test_neutral_evidence_excluded_from_both_lists():
    evidence = [make_evidence_item(fact="Dato neutral", direction=EvidenceDirection.NEUTRAL)]
    policy_decision = make_policy_decision()
    explanation = explain(policy_decision, evidence, evaluation_id="oe-1", now=NOW)
    assert explanation.evidence_for == []
    assert explanation.evidence_against == []


def test_opportunity_id_and_evaluation_id_propagated():
    policy_decision = make_policy_decision(opportunity_id="opp-42")
    explanation = explain(policy_decision, [], evaluation_id="oe-99", now=NOW)
    assert explanation.opportunity_id == "opp-42"
    assert explanation.evaluation_id == "oe-99"


# ---------------------------------------------------------------------
# Headline por signal_type/disposition/aggregate_soft_score
# ---------------------------------------------------------------------


def test_headline_includes_enter_and_score():
    policy_decision = make_policy_decision(
        signal_type=SignalType.ENTER, disposition=None, aggregate_soft_score=82.5
    )
    explanation = explain(policy_decision, [], evaluation_id="oe-1", now=NOW)
    assert "ENTER" in explanation.headline
    assert "82.5" in explanation.headline


def test_headline_includes_watch():
    policy_decision = make_policy_decision(signal_type=SignalType.WATCH, disposition=None)
    explanation = explain(policy_decision, [], evaluation_id="oe-1", now=NOW)
    assert "WATCH" in explanation.headline


def test_headline_includes_pass_disposition():
    policy_decision = make_policy_decision(
        signal_type=SignalType.PASS, disposition=AbstentionDisposition.INSUFFICIENT_EVIDENCE
    )
    explanation = explain(policy_decision, [], evaluation_id="oe-1", now=NOW)
    assert "PASS" in explanation.headline
    assert "INSUFFICIENT_EVIDENCE" in explanation.headline


# ---------------------------------------------------------------------
# Disclaimers obligatorios
# ---------------------------------------------------------------------


def test_disclaimer_present_when_calibration_version_none():
    policy_decision = make_policy_decision()
    explanation = explain(policy_decision, [], evaluation_id="oe-1", calibration_version=None, now=NOW)
    assert any("calibration_version=None" in d for d in explanation.disclaimers)


def test_no_calibration_disclaimer_when_version_present():
    policy_decision = make_policy_decision()
    explanation = explain(
        policy_decision, [], evaluation_id="oe-1", calibration_version="PLATT_V1",
        net_ev_status_is_unknown=False, now=NOW,
    )
    assert explanation.disclaimers == []


def test_disclaimer_present_when_net_ev_status_unknown():
    policy_decision = make_policy_decision()
    explanation = explain(
        policy_decision, [], evaluation_id="oe-1", calibration_version="PLATT_V1",
        net_ev_status_is_unknown=True, now=NOW,
    )
    assert any("net_ev_status=UNKNOWN" in d for d in explanation.disclaimers)


def test_both_disclaimers_when_both_missing():
    policy_decision = make_policy_decision()
    explanation = explain(
        policy_decision, [], evaluation_id="oe-1", calibration_version=None,
        net_ev_status_is_unknown=True, now=NOW,
    )
    assert len(explanation.disclaimers) == 2


# ---------------------------------------------------------------------
# Pureza y now naive
# ---------------------------------------------------------------------


def test_same_input_produces_same_output():
    policy_decision = make_policy_decision()
    evidence = [make_evidence_item()]
    explanation_a = explain(policy_decision, evidence, evaluation_id="oe-1", now=NOW)
    explanation_b = explain(policy_decision, evidence, evaluation_id="oe-1", now=NOW)
    assert explanation_a == explanation_b


def test_naive_now_raises():
    policy_decision = make_policy_decision()
    with pytest.raises(ValueError, match="tz-aware"):
        explain(policy_decision, [], evaluation_id="oe-1", now=datetime(2026, 7, 30, 12, 0, 0))


# ---------------------------------------------------------------------
# Regla de dependencia (Principio 6): separado de datos crudos
# ---------------------------------------------------------------------


def test_does_not_import_raw_data_or_evidence_engine_logic():
    """explainability_engine.py solo puede depender de policy/schemas.py
    y evidence/schemas.py (contratos ya calculados) -- nunca de
    models/schemas.py (datos crudos), uncertainty/quality_score.py, ni
    de evidence/evidence_engine.py (lógica de negocio del Evidence
    Engine, que ya corrió antes -- este módulo no debe volver a
    ejecutarla)."""
    import ast

    import src.explainability.explainability_engine as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = {
        "src.models.schemas",
        "src.uncertainty.quality_score",
        "src.evidence.evidence_engine",
        "src.policy.hard_rules",
        "src.policy.soft_score",
        "src.policy.decision",
    }
    assert not (imported_modules & forbidden), imported_modules & forbidden
    allowed = {"__future__", "datetime", "typing", "src.evidence.schemas", "src.explainability.schemas", "src.policy.schemas"}
    assert imported_modules <= allowed, imported_modules - allowed
