"""Factories de ejemplo mínimo válido para los 14 contratos nuevos de
Fase 3 (Paso 3.0). Mismo patrón `_kwargs(**overrides)` ya usado en
`tests/unit/test_signal_schema.py` (Fase 2): cada `make_*` construye una
instancia válida con overrides superficiales de nivel superior. No es un
módulo de tests en sí (sin funciones `test_*`) -- lo importan los 7
archivos de test de este paso, y quedará disponible para los pasos
siguientes (3.1 en adelante) sin duplicar esta construcción.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.calibration.schemas import CalibrationOutput
from src.evaluation.schemas import EvaluationRecord, EvaluationScope
from src.evidence.schemas import EvidenceDirection, EvidenceItem
from src.health.schemas import AnalysisHealth
from src.models.base import ModelStatus
from src.models.schemas import Sport
from src.opportunity.schemas import (
    Opportunity,
    OpportunityEvaluation,
    compute_opportunity_id,
    compute_selection_id,
)
from src.payoff.schemas import NetEvStatus, PayoffEstimate
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
from src.signals.signal_schema import Side, SignalInputs, SignalType

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def assert_round_trip(instance) -> None:
    """Round-trip completo pedido por el usuario para Paso 3.0: dict y
    JSON, en ambos sentidos, igualdad exacta con el objeto original."""
    model_cls = type(instance)

    dumped = instance.model_dump()
    from_dict = model_cls.model_validate(dumped)
    assert from_dict == instance, f"round-trip dict falló para {model_cls.__name__}"

    dumped_json = instance.model_dump_json()
    from_json = model_cls.model_validate_json(dumped_json)
    assert from_json == instance, f"round-trip json falló para {model_cls.__name__}"


def make_signal_inputs(**overrides):
    """Reutiliza el contrato de Fase 2 tal cual -- no es un contrato
    nuevo de este paso, pero varios contratos nuevos lo embeben."""
    base = dict(
        event_id="evt-1",
        sport=Sport.MLB,
        side=Side.YES,
        model_status=ModelStatus.TRAINED,
        p_model=0.6,
        market_price=0.5,
        edge=0.1,
        ev_bruto=0.05,
        ev_neto=None,
        confidence=0.7,
        confidence_method="HEURISTIC_V1",
        generated_at=NOW,
    )
    base.update(overrides)
    return SignalInputs(**base)


def make_calibration_output(**overrides) -> CalibrationOutput:
    base = dict(
        p_model_raw=0.6,
        p_model_calibrated=None,
        model_version="mlb_baseline_v1",
        calibration_version=None,
        calibration_method=None,
        calibrated_at=None,
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )
    base.update(overrides)
    return CalibrationOutput(**base)


def make_payoff_estimate(**overrides) -> PayoffEstimate:
    base = dict(
        opportunity_id="opp-1",
        side=Side.YES,
        platform="KALSHI",
        entry_price=0.55,
        payout=1.0,
        loss=0.55,
        entry_fee=None,
        estimated_exit_fee=None,
        spread=0.02,
        slippage_estimate=None,
        ev_to_settlement=None,
        ev_to_planned_exit=None,
        breakeven_probability=0.55,
        max_acceptable_entry_price=None,
        net_ev_status=NetEvStatus.UNKNOWN,
        cost_evidence_refs=[],
        computed_at=NOW,
    )
    base.update(overrides)
    return PayoffEstimate(**base)


def make_confidence_profile(**overrides) -> ConfidenceProfile:
    base = dict(
        opportunity_id="opp-1",
        data_quality=70.0,
        model_reliability=None,
        market_quality=60.0,
        operational_safety=90.0,
        operational_risk=10.0,
        aggregate_confidence=None,
        quality_score_component_ref="quality_score_v1",
        computed_at=NOW,
    )
    base.update(overrides)
    return ConfidenceProfile(**base)


def make_analysis_health(**overrides) -> AnalysisHealth:
    base = dict(
        opportunity_id="opp-1",
        completeness_signal=80.0,
        consistency_signal=90.0,
        evidence_density=3,
        staleness_seconds=120.0,
        warnings=[],
        computed_at=NOW,
    )
    base.update(overrides)
    return AnalysisHealth(**base)


def make_evidence_item(**overrides) -> EvidenceItem:
    base = dict(
        opportunity_id="opp-1",
        fact="Pitcher probable confirmado",
        direction=EvidenceDirection.FOR,
        source_field="model_inputs.lineup_or_pitcher",
        source_timestamp=NOW,
        strength=0.8,
        generated_at=NOW,
    )
    base.update(overrides)
    return EvidenceItem(**base)


def make_eligibility_result(**overrides) -> EligibilityResult:
    base = dict(
        opportunity_id="opp-1",
        is_eligible=True,
        ineligibility_reasons=[],
        evaluated_at=NOW,
    )
    base.update(overrides)
    return EligibilityResult(**base)


def make_hard_rule_result(**overrides) -> HardRuleResult:
    base = dict(
        rule_id="unsafe_matching",
        category=HardRuleCategory.BLOCK,
        triggered=False,
        detail=None,
        evaluated_at=NOW,
    )
    base.update(overrides)
    return HardRuleResult(**base)


def make_soft_score_component(**overrides) -> SoftScoreComponent:
    base = dict(
        component_name="edge_strength",
        value=65.0,
        weight=0.2,
        is_critical_minimum=False,
        minimum_required=None,
        passed_minimum=None,
    )
    base.update(overrides)
    return SoftScoreComponent(**base)


def make_signal_reason(**overrides) -> SignalReason:
    base = dict(
        code=SignalReasonCode.ELIGIBLE_AND_SCORED,
        detail="score global 65 >= umbral 60",
        source_component="soft_score",
    )
    base.update(overrides)
    return SignalReason(**base)


def make_policy_decision(**overrides) -> PolicyDecision:
    base = dict(
        opportunity_id="opp-1",
        side=Side.YES,
        signal_type=SignalType.PASS,
        disposition=AbstentionDisposition.NO_VALUE,
        reasons=[make_signal_reason()],
        hard_rule_results=[],
        soft_score_components=[],
        aggregate_soft_score=None,
        policy_version="1.0.0",
        policy_manifest_hash="abc123",
        decided_at=NOW,
    )
    base.update(overrides)
    return PolicyDecision(**base)


def make_policy_manifest(**overrides) -> PolicyManifest:
    base = dict(
        policy_version="1.0.0",
        sport=Sport.MLB,
        hard_block_rules=["unsafe_matching"],
        hard_hold_rules=["unresolved_side_mapping"],
        soft_score_weights={"edge_strength": 0.2},
        critical_minimums={"ev_neto_strength": 0.0},
        hard_rule_parameters={},
        enter_global_threshold=70.0,
        watch_global_threshold=40.0,
        manifest_hash="abc123",
        created_at=NOW,
        promoted_at=None,
        promotion_gate_report_ref=None,
    )
    base.update(overrides)
    return PolicyManifest(**base)


def make_opportunity(**overrides) -> Opportunity:
    market_id = overrides.pop("market_id", "KXMLBGAME-1")
    side = overrides.get("side", Side.YES)
    selection_id = compute_selection_id(market_id, side) if market_id is not None else "evt-1:YES"
    event_id = overrides.get("event_id", "evt-1")
    base = dict(
        opportunity_id=compute_opportunity_id(event_id, selection_id),
        event_id=event_id,
        market_id=market_id,
        selection_id=selection_id,
        side=side,
        sport=Sport.MLB,
        first_seen_at=NOW,
        last_evaluated_at=NOW,
        state_version=1,
        previous_signal_id=None,
    )
    base.update(overrides)
    return Opportunity(**base)


def make_opportunity_evaluation(**overrides) -> OpportunityEvaluation:
    base = dict(
        evaluation_id="oe-1",
        opportunity_id="opp-1",
        state_version=1,
        signal_inputs=make_signal_inputs(),
        calibration_output=make_calibration_output(),
        payoff_estimate=make_payoff_estimate(),
        confidence_profile=make_confidence_profile(),
        analysis_health=make_analysis_health(),
        evidence_items=[make_evidence_item()],
        policy_decision=make_policy_decision(),
        decision_timestamp=NOW,
        data_cutoff_timestamp=NOW,
        market_snapshot_timestamp=NOW,
        model_version="mlb_baseline_v1",
        calibration_version=None,
        policy_version="1.0.0",
        feature_schema_version="mlb_features_v1",
    )
    base.update(overrides)
    return OpportunityEvaluation(**base)


def make_evaluation_record(**overrides) -> EvaluationRecord:
    base = dict(
        record_id="rec-1",
        scope=EvaluationScope.MODEL_PERFORMANCE,
        sport=Sport.MLB,
        market_type="moneyline",
        model_version="mlb_baseline_v1",
        calibration_version=None,
        policy_version="1.0.0",
        metric_name="brier_score",
        metric_value=0.21,
        sample_size=42,
        confidence_interval_low=0.18,
        confidence_interval_high=0.24,
        computed_at=NOW,
        evaluation_window_start=NOW,
        evaluation_window_end=NOW,
    )
    base.update(overrides)
    return EvaluationRecord(**base)
