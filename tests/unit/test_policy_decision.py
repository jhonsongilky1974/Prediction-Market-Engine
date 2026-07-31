"""Tests de decide() (Fase 3, Paso 3.4.5). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.4.5, y POLICY_ENGINE_SPEC.md §1.1 -- orquestación completa de las
4 etapas, más el fuzz test de no-ENTER-con-bloqueo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.schemas import (
    DataQuality,
    EventStatus,
    MarketData,
    MatchMethod,
    ModelInputs,
    NormalizedRecord,
    Sport,
)
from src.payoff.schemas import NetEvStatus
from src.policy.decision import decide
from src.policy.hard_rules import HARD_BLOCK_RULE_IDS, HARD_HOLD_RULE_IDS
from src.policy.schemas import AbstentionDisposition, HardRuleCategory
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
_COMPUTED_PAYOFF = dict(
    net_ev_status=NetEvStatus.COMPUTED, ev_to_settlement=0.15, ev_to_planned_exit=0.15, cost_evidence_refs=["fixture"]
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
        data_quality=DataQuality(
            match_method=MatchMethod.SOURCE_ID, match_confidence=0.95, missing_fields=[], validation_errors=[]
        ),
        model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}),
    )
    base.update(overrides)
    return NormalizedRecord(**base)


def _permissive_manifest(**overrides) -> "PolicyManifest":  # noqa: F821 -- forward ref en docstring
    """hard_hold_rules vacío a propósito: aísla la etapa Soft Score de
    unresolved_side_mapping (que siempre dispara, D-2) para poder probar
    la ruta ENTER/WATCH/PASS del score de forma independiente."""
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


def _full_catalog_manifest(**overrides) -> "PolicyManifest":  # noqa: F821
    """Manifiesto realista: TODAS las reglas del catálogo activas,
    incluida unresolved_side_mapping -- el escenario real del proyecto
    hoy."""
    base = dict(
        hard_block_rules=list(HARD_BLOCK_RULE_IDS),
        hard_hold_rules=list(HARD_HOLD_RULE_IDS),
        enter_global_threshold=60.0,
        watch_global_threshold=40.0,
        soft_score_weights={},
        critical_minimums={},
        hard_rule_parameters={},
    )
    base.update(overrides)
    return make_policy_manifest(**base)


def _tmp_history(tmp_path) -> HistoryRepository:
    return HistoryRepository(db_path=tmp_path / "history.db")


# ---------------------------------------------------------------------
# Etapa 4 (Soft Score) -- ruta ENTER, aislada de Hard Hold
# ---------------------------------------------------------------------


def test_enter_when_everything_perfect_and_hold_rules_not_active(tmp_path):
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(staleness_seconds=100.0),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    assert decision.signal_type == SignalType.ENTER
    assert decision.disposition is None
    assert decision.aggregate_soft_score is not None and decision.aggregate_soft_score >= 60.0


def test_watch_forced_by_unresolved_side_mapping_even_when_everything_else_perfect(tmp_path):
    """El escenario real del proyecto hoy: con TODAS las reglas del
    catálogo activas (incluida unresolved_side_mapping, D-2 sin
    resolver), ningún ENTER es posible aunque todo lo demás sea
    perfecto -- verificado a nivel de orquestación completa."""
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(staleness_seconds=100.0),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_full_catalog_manifest(),
        now=NOW,
    )
    assert decision.signal_type == SignalType.WATCH
    assert any(r.source_component == "unresolved_side_mapping" for r in decision.reasons)
    assert decision.soft_score_components == []  # nunca se llega a Soft Score


# ---------------------------------------------------------------------
# Etapa 2 (Hard Block) -> PASS/POLICY_REJECTED
# ---------------------------------------------------------------------


def test_pass_policy_rejected_on_hard_block(tmp_path):
    record = _clean_record(data_quality=DataQuality(match_confidence=0.30))  # unsafe_matching
    decision = decide(
        opportunity_id="opp-1",
        record=record,
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.POLICY_REJECTED
    assert any(r.rule_id == "unsafe_matching" and r.triggered for r in decision.hard_rule_results)
    assert decision.soft_score_components == []


def test_inactive_hard_block_rule_does_not_block(tmp_path):
    """Un rule_id triggered=True pero NO activado en el manifiesto no
    debe bloquear -- se evalúa (transparencia/auditoría) pero no cuenta
    para la decisión."""
    record = _clean_record(data_quality=DataQuality(match_confidence=0.30))
    manifest = _permissive_manifest(hard_block_rules=[])  # ningún BLOCK activo
    decision = decide(
        opportunity_id="opp-1",
        record=record,
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=manifest,
        now=NOW,
    )
    # unsafe_matching se evalúa internamente (triggered=True), pero al no
    # estar activo en el manifiesto ni bloquea ni aparece en el
    # hard_rule_results persistido -- PolicyDecision (Paso 3.0) exige que
    # ningún ENTER coexista con un BLOCK triggered=True en su propia
    # lista, así que solo las reglas ACTIVAS quedan en el resultado final
    # (encontrado como bug real durante este paso, corregido en
    # decision.py sin tocar el contrato de Paso 3.0 -- ver CONTINUITY.md
    # §0.11).
    assert not any(r.rule_id == "unsafe_matching" for r in decision.hard_rule_results)
    assert decision.signal_type == SignalType.ENTER


# ---------------------------------------------------------------------
# Etapa 3 (Hard Hold) -> WATCH
# ---------------------------------------------------------------------


def test_watch_on_hard_hold_pending_lineup(tmp_path):
    record = _clean_record(model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=NOW + timedelta(hours=1))
    manifest = _permissive_manifest(hard_hold_rules=["pending_lineup"])
    decision = decide(
        opportunity_id="opp-1",
        record=record,
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=manifest,
        now=NOW,
    )
    assert decision.signal_type == SignalType.WATCH
    assert decision.disposition is None
    assert any(r.source_component == "pending_lineup" for r in decision.reasons)


# ---------------------------------------------------------------------
# Etapa 4 -- mínimo crítico incumplido (ev_neto_strength, caso real hoy)
# ---------------------------------------------------------------------


def test_watch_when_ev_neto_unknown_but_confidence_high_enough_for_watch_floor(tmp_path):
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(side=Side.YES),  # default: net_ev_status=UNKNOWN
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    assert decision.signal_type == SignalType.WATCH
    ev_component = next(c for c in decision.soft_score_components if c.component_name == "ev_neto_strength")
    assert ev_component.value is None
    assert ev_component.passed_minimum is None


def test_pass_insufficient_evidence_when_critical_missing_and_below_watch_floor(tmp_path):
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.0, side=Side.YES),
        payoff_estimate=make_payoff_estimate(side=Side.YES),  # UNKNOWN
        confidence_profile=make_confidence_profile(
            data_quality=30.0, model_reliability=30.0, market_quality=30.0, operational_safety=30.0, operational_risk=70.0
        ),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(watch_global_threshold=99.0, enter_global_threshold=99.0),
        now=NOW,
    )
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.INSUFFICIENT_EVIDENCE


def test_pass_no_value_when_all_critical_pass_but_aggregate_below_watch(tmp_path):
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=-0.30, side=Side.YES),
        payoff_estimate=make_payoff_estimate(
            net_ev_status=NetEvStatus.COMPUTED, ev_to_settlement=0.02, ev_to_planned_exit=0.02,
            cost_evidence_refs=["fixture"], side=Side.YES,
        ),
        confidence_profile=make_confidence_profile(
            data_quality=40.0, model_reliability=60.0, market_quality=60.0, operational_safety=60.0, operational_risk=40.0
        ),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(watch_global_threshold=50.0, enter_global_threshold=60.0),
        now=NOW,
    )
    critical_failures = [c for c in decision.soft_score_components if c.is_critical_minimum and c.passed_minimum is not True]
    assert critical_failures == []  # todos los críticos pasaron su mínimo
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.NO_VALUE


# ---------------------------------------------------------------------
# Etapa 1 (Eligibility) -> PASS/INVALID_ANALYSIS
# ---------------------------------------------------------------------


def test_pass_invalid_analysis_when_ineligible(tmp_path):
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.INVALID_ANALYSIS
    assert decision.hard_rule_results == []


# ---------------------------------------------------------------------
# Fail-safe: sport mismatch entre manifiesto y record
# ---------------------------------------------------------------------


def test_pass_invalid_analysis_on_sport_mismatch(tmp_path):
    manifest = _permissive_manifest(sport=Sport.TENNIS)
    decision = decide(
        opportunity_id="opp-1",
        record=_clean_record(sport=Sport.MLB),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES, sport=Sport.MLB),
        payoff_estimate=make_payoff_estimate(side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=manifest,
        now=NOW,
    )
    assert decision.signal_type == SignalType.PASS
    assert decision.disposition == AbstentionDisposition.INVALID_ANALYSIS
    assert decision.hard_rule_results[0].rule_id == "non_recoverable_inconsistency"


# ---------------------------------------------------------------------
# Fuzz test: ningún ENTER coexiste con un HardRuleResult BLOCK activo
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "record_overrides",
    [
        {},  # limpio
        {"data_quality": DataQuality(match_confidence=0.30)},  # unsafe_matching
        {"status": EventStatus.CANCELLED},  # invalid_event
        {"market": MarketData()},  # invalid_or_closed_market
        {"data_quality": DataQuality(validation_errors=["participant_a vacío"])},  # corrupted_critical_data
    ],
)
@pytest.mark.parametrize(
    "confidence_overrides",
    [_PERFECT_CONFIDENCE, dict(data_quality=10.0, model_reliability=10.0, market_quality=10.0, operational_safety=10.0, operational_risk=90.0)],
)
def test_fuzz_no_enter_coexists_with_active_block(tmp_path, record_overrides, confidence_overrides):
    record = _clean_record(**record_overrides)
    decision = decide(
        opportunity_id="opp-1",
        record=record,
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**confidence_overrides),
        analysis_health=make_analysis_health(),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    active_blocks_triggered = any(
        r.category == HardRuleCategory.BLOCK and r.triggered for r in decision.hard_rule_results
    )
    if active_blocks_triggered:
        assert decision.signal_type != SignalType.ENTER


# ---------------------------------------------------------------------
# Pureza
# ---------------------------------------------------------------------


def test_same_input_produces_same_decision(tmp_path):
    kwargs = dict(
        opportunity_id="opp-1",
        record=_clean_record(),
        signal_inputs=make_signal_inputs(event_id="mlb_824409", edge=0.15, side=Side.YES),
        payoff_estimate=make_payoff_estimate(**_COMPUTED_PAYOFF, side=Side.YES),
        confidence_profile=make_confidence_profile(**_PERFECT_CONFIDENCE),
        analysis_health=make_analysis_health(staleness_seconds=100.0),
        data_cutoff_timestamp=NOW,
        history_repository=_tmp_history(tmp_path),
        policy_manifest=_permissive_manifest(),
        now=NOW,
    )
    decision_a = decide(**kwargs)
    decision_b = decide(**kwargs)
    assert decision_a == decision_b
