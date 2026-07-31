"""Tests de fail-safe de decide() (Fase 3, Paso 3.4.5). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.5, y POLICY_ENGINE_SPEC.md §6
(Principio 20) -- excepción forzada en cada etapa de la orquestación ->
PolicyDecision(PASS, INVALID_ANALYSIS), nunca propagación.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import src.policy.decision as decision_module
from src.models.schemas import DataQuality, EventStatus, MarketData, ModelInputs, NormalizedRecord, Sport
from src.payoff.schemas import NetEvStatus
from src.policy.decision import decide
from src.policy.hard_rules import HARD_BLOCK_RULE_IDS
from src.policy.schemas import AbstentionDisposition, PolicyManifest
from src.signals.signal_schema import Side, SignalType
from src.storage.history_repository import HistoryRepository
from tests.unit.fase3_factories import (
    NOW,
    make_analysis_health,
    make_confidence_profile,
    make_payoff_estimate,
    make_policy_manifest,
    make_signal_inputs,
)

_PERFECT_CONFIDENCE = dict(
    data_quality=90.0, model_reliability=90.0, market_quality=90.0, operational_safety=90.0, operational_risk=10.0
)


def _clean_record(**overrides) -> NormalizedRecord:
    base = dict(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        status=EventStatus.SCHEDULED,
        start_time=NOW + timedelta(hours=10),
        market=MarketData(yes_ask=0.55, no_ask=0.42, volume=5000.0),
        data_quality=DataQuality(match_confidence=0.95, missing_fields=[], validation_errors=[]),
        model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}),
    )
    base.update(overrides)
    return NormalizedRecord(**base)


def _permissive_manifest(**overrides) -> PolicyManifest:
    base = dict(
        hard_block_rules=list(HARD_BLOCK_RULE_IDS),
        hard_hold_rules=[],
        enter_global_threshold=60.0,
        watch_global_threshold=40.0,
        soft_score_weights={},
        critical_minimums={},
        hard_rule_parameters={},
    )
    base.update(overrides)
    return make_policy_manifest(**base)


def _decide_kwargs(tmp_path):
    return dict(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(
            net_ev_status=NetEvStatus.COMPUTED, ev_to_settlement=0.15, ev_to_planned_exit=0.15,
            cost_evidence_refs=["fixture"], side=Side.YES,
        ),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=HistoryRepository(db_path=tmp_path / "history.db"),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )


def _assert_fail_safe(decision):
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.INVALID_ANALYSIS
    assert len(decision.hard_rule_results) == 1
    assert decision.hard_rule_results[0].rule_id == "non_recoverable_inconsistency"
    assert decision.hard_rule_results[0].triggered is True
    assert decision.soft_score_components == []
    assert decision.aggregate_soft_score is None


# ---------------------------------------------------------------------
# Excepción forzada en cada etapa -- nunca propaga
# ---------------------------------------------------------------------


def test_fail_safe_on_eligibility_exception(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise RuntimeError("eligibility boom")

    monkeypatch.setattr(decision_module, "check_eligibility", _boom)
    decision = decide(**_decide_kwargs(tmp_path))
    _assert_fail_safe(decision)
    assert "eligibility boom" in decision.hard_rule_results[0].detail


def test_fail_safe_on_hard_block_exception(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise RuntimeError("hard block boom")

    monkeypatch.setattr(decision_module, "evaluate_hard_block_rules", _boom)
    decision = decide(**_decide_kwargs(tmp_path))
    _assert_fail_safe(decision)
    assert "hard block boom" in decision.hard_rule_results[0].detail


def test_fail_safe_on_hard_hold_exception(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise RuntimeError("hard hold boom")

    monkeypatch.setattr(decision_module, "evaluate_hard_hold_rules", _boom)
    decision = decide(**_decide_kwargs(tmp_path))
    _assert_fail_safe(decision)
    assert "hard hold boom" in decision.hard_rule_results[0].detail


def test_fail_safe_on_soft_score_exception(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise RuntimeError("soft score boom")

    monkeypatch.setattr(decision_module, "compute_soft_score_components", _boom)
    decision = decide(**_decide_kwargs(tmp_path))
    _assert_fail_safe(decision)
    assert "soft score boom" in decision.hard_rule_results[0].detail


def test_fail_safe_on_history_repository_exception(monkeypatch, tmp_path):
    """El caso real más probable de excepción no controlada: un error de
    HistoryRepository (p.ej. base de datos bloqueada) durante
    known_result."""
    kwargs = _decide_kwargs(tmp_path)

    class _BoomRepository:
        def get_results_for_event(self, event_id):
            raise RuntimeError("db locked")

    kwargs["history_repository"] = _BoomRepository()
    decision = decide(**kwargs)
    _assert_fail_safe(decision)
    assert "db locked" in decision.hard_rule_results[0].detail


# ---------------------------------------------------------------------
# Manifiesto inválido -- rechazado antes de ejecutarse (defensa en
# profundidad dentro de decide(), además de manifest.py)
# ---------------------------------------------------------------------


def test_fail_safe_on_invalid_manifest_passed_directly(tmp_path):
    """Un PolicyManifest que nunca pasó por save_policy_manifest()/
    load_policy_manifest() (que ya validan) -- decide() lo re-valida
    internamente y, al fallar, cae en el mismo camino fail-safe."""
    invalid_manifest = PolicyManifest.model_construct(
        **{**_permissive_manifest().model_dump(), "hard_block_rules": ["fake_rule_id"]}
    )
    kwargs = _decide_kwargs(tmp_path)
    kwargs["policy_manifest"] = invalid_manifest
    decision = decide(**kwargs)
    _assert_fail_safe(decision)
    assert "hard_block_rules" in decision.hard_rule_results[0].detail


# ---------------------------------------------------------------------
# El propio decide() (frontera pública) nunca lanza, pase lo que pase
# ---------------------------------------------------------------------


def test_decide_never_raises_even_with_completely_broken_dependencies(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise KeyError("totally unexpected")

    monkeypatch.setattr(decision_module, "check_eligibility", _boom)
    try:
        decision = decide(**_decide_kwargs(tmp_path))
    except Exception as exc:  # pragma: no cover -- este test falla si decide() propaga
        pytest.fail(f"decide() propagó una excepción en vez de devolver PolicyDecision: {exc!r}")
    _assert_fail_safe(decision)
