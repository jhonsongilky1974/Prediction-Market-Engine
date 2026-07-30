"""Tests de los 7 contratos de src/policy/schemas.py (Fase 3, Paso 3.0):
ConfidenceProfile, EligibilityResult, HardRuleResult, SoftScoreComponent,
SignalReason, PolicyDecision, PolicyManifest. Ver CONTRACTS_FASE3.md
§4, §7-11, §15 y POLICY_ENGINE_SPEC.md.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.policy.schemas import (
    AbstentionDisposition,
    ConfidenceProfile,
    EligibilityResult,
    HardRuleCategory,
    HardRuleResult,
    PolicyDecision,
    PolicyManifest,
    SignalReason,
    SignalReasonCode,
    SoftScoreComponent,
)
from src.signals.signal_schema import Side, SignalType
from tests.unit.fase3_factories import (
    NOW,
    assert_round_trip,
    make_confidence_profile,
    make_eligibility_result,
    make_hard_rule_result,
    make_policy_decision,
    make_policy_manifest,
    make_signal_reason,
    make_soft_score_component,
)

# ---------------------------------------------------------------------
# ConfidenceProfile
# ---------------------------------------------------------------------


def test_confidence_profile_valid():
    profile = make_confidence_profile()
    assert profile.operational_safety + profile.operational_risk == 100.0


def test_confidence_profile_safety_risk_mismatch_raises():
    with pytest.raises(ValidationError, match="operational_safety \\+ operational_risk"):
        make_confidence_profile(operational_safety=90.0, operational_risk=20.0)


@pytest.mark.parametrize(
    "field_name",
    ["data_quality", "model_reliability", "market_quality", "operational_safety", "operational_risk"],
)
def test_confidence_profile_out_of_range_raises(field_name):
    overrides = {field_name: 150.0}
    if field_name in ("operational_safety", "operational_risk"):
        # evita disparar el invariante de complemento antes que el de rango
        overrides["operational_safety"] = 150.0 if field_name == "operational_safety" else 90.0
        overrides["operational_risk"] = 150.0 if field_name == "operational_risk" else 10.0
    with pytest.raises(ValidationError, match=r"fuera de \[0,100\]"):
        make_confidence_profile(**overrides)


def test_confidence_profile_round_trip():
    assert_round_trip(make_confidence_profile())
    assert_round_trip(make_confidence_profile(operational_safety=None, operational_risk=None))


# ---------------------------------------------------------------------
# EligibilityResult
# ---------------------------------------------------------------------


def test_eligibility_result_eligible_valid():
    result = make_eligibility_result()
    assert result.is_eligible is True


def test_eligibility_result_eligible_with_reasons_raises():
    with pytest.raises(ValidationError, match="is_eligible=True"):
        make_eligibility_result(is_eligible=True, ineligibility_reasons=["x"])


def test_eligibility_result_ineligible_without_reasons_raises():
    with pytest.raises(ValidationError, match="is_eligible=False"):
        make_eligibility_result(is_eligible=False, ineligibility_reasons=[])


def test_eligibility_result_ineligible_with_reasons_valid():
    result = make_eligibility_result(is_eligible=False, ineligibility_reasons=["missing event_id"])
    assert result.ineligibility_reasons == ["missing event_id"]


def test_eligibility_result_round_trip():
    assert_round_trip(make_eligibility_result())
    assert_round_trip(make_eligibility_result(is_eligible=False, ineligibility_reasons=["x"]))


# ---------------------------------------------------------------------
# HardRuleResult
# ---------------------------------------------------------------------


def test_hard_rule_result_valid():
    result = make_hard_rule_result()
    assert result.category == HardRuleCategory.BLOCK


def test_hard_rule_result_categories_are_exactly_two():
    assert {member.value for member in HardRuleCategory} == {
        "HARD_BLOCK_PASS",
        "HARD_HOLD_WATCH",
    }


def test_hard_rule_result_empty_rule_id_raises():
    with pytest.raises(ValidationError, match="rule_id"):
        make_hard_rule_result(rule_id="  ")


def test_hard_rule_result_round_trip():
    assert_round_trip(make_hard_rule_result())
    assert_round_trip(make_hard_rule_result(category=HardRuleCategory.HOLD, triggered=True))


# ---------------------------------------------------------------------
# SoftScoreComponent
# ---------------------------------------------------------------------


def test_soft_score_component_valid():
    component = make_soft_score_component()
    assert component.is_critical_minimum is False


def test_soft_score_component_value_none_with_passed_minimum_raises():
    with pytest.raises(ValidationError, match="passed_minimum"):
        make_soft_score_component(value=None, passed_minimum=True)


def test_soft_score_component_critical_without_minimum_required_raises():
    with pytest.raises(ValidationError, match="minimum_required"):
        make_soft_score_component(is_critical_minimum=True, minimum_required=None)


def test_soft_score_component_critical_with_minimum_required_valid():
    component = make_soft_score_component(
        is_critical_minimum=True, minimum_required=50.0, value=70.0, passed_minimum=True
    )
    assert component.passed_minimum is True


def test_soft_score_component_negative_weight_raises():
    with pytest.raises(ValidationError, match="weight"):
        make_soft_score_component(weight=-0.1)


def test_soft_score_component_round_trip():
    assert_round_trip(make_soft_score_component())
    assert_round_trip(
        make_soft_score_component(is_critical_minimum=True, minimum_required=50.0, value=None)
    )


# ---------------------------------------------------------------------
# SignalReason
# ---------------------------------------------------------------------


def test_signal_reason_valid():
    reason = make_signal_reason()
    assert reason.code == SignalReasonCode.ELIGIBLE_AND_SCORED


def test_signal_reason_empty_detail_raises():
    with pytest.raises(ValidationError, match="detail"):
        make_signal_reason(detail="")


def test_signal_reason_round_trip():
    assert_round_trip(make_signal_reason())


# ---------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------


def test_policy_decision_pass_requires_disposition():
    with pytest.raises(ValidationError, match="disposition"):
        make_policy_decision(signal_type=SignalType.PASS, disposition=None)


@pytest.mark.parametrize("signal_type", [SignalType.ENTER, SignalType.WATCH])
def test_policy_decision_enter_watch_forbid_disposition(signal_type):
    with pytest.raises(ValidationError, match="disposition"):
        make_policy_decision(
            signal_type=signal_type,
            disposition=AbstentionDisposition.NO_VALUE,
            hard_rule_results=[],
            soft_score_components=[],
        )


def test_policy_decision_empty_reasons_raises():
    with pytest.raises(ValidationError, match="reasons"):
        make_policy_decision(reasons=[])


def test_policy_decision_enter_with_active_block_raises():
    blocked_rule = make_hard_rule_result(category=HardRuleCategory.BLOCK, triggered=True)
    with pytest.raises(ValidationError, match="BLOCK"):
        make_policy_decision(
            signal_type=SignalType.ENTER,
            disposition=None,
            hard_rule_results=[blocked_rule],
            soft_score_components=[],
        )


def test_policy_decision_enter_with_unmet_critical_minimum_raises():
    unmet_component = make_soft_score_component(
        is_critical_minimum=True, minimum_required=50.0, value=30.0, passed_minimum=False
    )
    with pytest.raises(ValidationError, match="Principio 9"):
        make_policy_decision(
            signal_type=SignalType.ENTER,
            disposition=None,
            hard_rule_results=[],
            soft_score_components=[unmet_component],
        )


def test_policy_decision_enter_with_all_minimums_met_is_valid():
    met_component = make_soft_score_component(
        is_critical_minimum=True, minimum_required=50.0, value=70.0, passed_minimum=True
    )
    decision = make_policy_decision(
        signal_type=SignalType.ENTER,
        disposition=None,
        hard_rule_results=[],
        soft_score_components=[met_component],
        aggregate_soft_score=75.0,
    )
    assert decision.signal_type == SignalType.ENTER


def test_policy_decision_naive_decided_at_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_policy_decision(decided_at=datetime(2026, 7, 30, 12, 0, 0))


def test_policy_decision_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        PolicyDecision(
            opportunity_id="opp-1",
            side=Side.YES,
            signal_type=SignalType.PASS,
            disposition=AbstentionDisposition.NO_VALUE,
            reasons=[make_signal_reason()],
            policy_version="1.0.0",
            policy_manifest_hash="abc",
            decided_at=NOW,
            unexpected_field="x",
        )


def test_policy_decision_round_trip():
    assert_round_trip(make_policy_decision())


# ---------------------------------------------------------------------
# PolicyManifest
# ---------------------------------------------------------------------


def test_policy_manifest_valid():
    manifest = make_policy_manifest()
    assert manifest.enter_global_threshold >= manifest.watch_global_threshold


def test_policy_manifest_enter_below_watch_raises():
    with pytest.raises(ValidationError, match="enter_global_threshold"):
        make_policy_manifest(enter_global_threshold=30.0, watch_global_threshold=40.0)


def test_policy_manifest_naive_created_at_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_policy_manifest(created_at=datetime(2026, 7, 30, 12, 0, 0))


def test_policy_manifest_round_trip():
    assert_round_trip(make_policy_manifest())
