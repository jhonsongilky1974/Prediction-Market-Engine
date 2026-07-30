"""Contratos del Policy Engine (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§4, §7-11, §15 y POLICY_ENGINE_SPEC.md.

Siete contratos en este archivo: `ConfidenceProfile`, `EligibilityResult`,
`HardRuleResult`+`HardRuleCategory`, `SoftScoreComponent`,
`SignalReason`+`SignalReasonCode`, `PolicyDecision`+
`AbstentionDisposition`, `PolicyManifest`. `ConfidenceProfile` se ubica
aquí (y no en `src/opportunity/`, donde `PLAN_MASTER_FASE3.md` §4 dejaba
la decisión abierta) porque es consumida directamente por
`src/policy/soft_score.py` (Paso 3.4.4).

Únicamente contratos de datos -- ninguna función de negocio. La lógica
(Hard Rules, Soft Score, decisión, validación de manifiesto) vive en
`hard_rules.py`/`soft_score.py`/`decision.py`/`manifest.py`/`validation.py`,
ninguno implementado todavía (Paso 3.4).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from src.models.schemas import Sport, StrictModel
from src.signals.signal_schema import Side, SignalType


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def _require_percent_range(value: Optional[float], field_name: str) -> None:
    if value is None:
        return
    if not (0.0 <= value <= 100.0):
        raise ValueError(f"{field_name} fuera de [0,100]: {value}")


# ---------------------------------------------------------------------
# ConfidenceProfile (CONTRACTS_FASE3.md §4)
# ---------------------------------------------------------------------


class ConfidenceProfile(StrictModel):
    opportunity_id: str
    data_quality: Optional[float] = None
    model_reliability: Optional[float] = None
    market_quality: Optional[float] = None
    operational_safety: Optional[float] = None
    operational_risk: Optional[float] = None
    aggregate_confidence: Optional[float] = None
    quality_score_component_ref: Optional[str] = None
    computed_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "ConfidenceProfile":
        for field_name in (
            "data_quality",
            "model_reliability",
            "market_quality",
            "operational_safety",
            "operational_risk",
            "aggregate_confidence",
        ):
            _require_percent_range(getattr(self, field_name), field_name)
        if self.operational_safety is not None and self.operational_risk is not None:
            total = self.operational_safety + self.operational_risk
            if abs(total - 100.0) > 1e-6:
                raise ValueError(
                    "operational_safety + operational_risk debe ser exactamente 100 "
                    f"(Corrección B): recibido {self.operational_safety} + "
                    f"{self.operational_risk} = {total}"
                )
        _require_utc_aware(self.computed_at, "computed_at")
        return self


# ---------------------------------------------------------------------
# EligibilityResult (CONTRACTS_FASE3.md §7)
# ---------------------------------------------------------------------


class EligibilityResult(StrictModel):
    opportunity_id: str
    is_eligible: bool
    ineligibility_reasons: List[str] = Field(default_factory=list)
    evaluated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "EligibilityResult":
        if self.is_eligible and self.ineligibility_reasons:
            raise ValueError("is_eligible=True no puede llevar ineligibility_reasons pobladas")
        if not self.is_eligible and not self.ineligibility_reasons:
            raise ValueError("is_eligible=False exige al menos un motivo en ineligibility_reasons")
        _require_utc_aware(self.evaluated_at, "evaluated_at")
        return self


# ---------------------------------------------------------------------
# HardRuleResult (CONTRACTS_FASE3.md §8)
# ---------------------------------------------------------------------


class HardRuleCategory(str, Enum):
    BLOCK = "HARD_BLOCK_PASS"
    HOLD = "HARD_HOLD_WATCH"


class HardRuleResult(StrictModel):
    rule_id: str
    category: HardRuleCategory
    triggered: bool
    detail: Optional[str] = None
    evaluated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "HardRuleResult":
        if not self.rule_id.strip():
            raise ValueError("rule_id no puede estar vacío")
        _require_utc_aware(self.evaluated_at, "evaluated_at")
        return self


# ---------------------------------------------------------------------
# SoftScoreComponent (CONTRACTS_FASE3.md §9)
# ---------------------------------------------------------------------


class SoftScoreComponent(StrictModel):
    component_name: str
    value: Optional[float] = None
    weight: float
    is_critical_minimum: bool
    minimum_required: Optional[float] = None
    passed_minimum: Optional[bool] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "SoftScoreComponent":
        _require_percent_range(self.value, "value")
        if self.weight < 0:
            raise ValueError(f"weight no puede ser negativo: {self.weight}")
        if self.value is None and self.passed_minimum is not None:
            raise ValueError("passed_minimum debe ser None cuando value es None")
        if self.is_critical_minimum and self.minimum_required is None:
            raise ValueError(
                "is_critical_minimum=True exige minimum_required declarado (Principio 9)"
            )
        return self


# ---------------------------------------------------------------------
# SignalReason (CONTRACTS_FASE3.md §10)
# ---------------------------------------------------------------------


class SignalReasonCode(str, Enum):
    HARD_BLOCK = "HARD_BLOCK"
    HARD_HOLD = "HARD_HOLD"
    SOFT_SCORE_BELOW_GLOBAL = "SOFT_SCORE_BELOW_GLOBAL"
    CRITICAL_MINIMUM_NOT_MET = "CRITICAL_MINIMUM_NOT_MET"
    ELIGIBLE_AND_SCORED = "ELIGIBLE_AND_SCORED"


class SignalReason(StrictModel):
    code: SignalReasonCode
    detail: str
    source_component: Optional[str] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "SignalReason":
        if not self.detail.strip():
            raise ValueError("detail no puede estar vacío")
        return self


# ---------------------------------------------------------------------
# PolicyDecision (CONTRACTS_FASE3.md §11)
# ---------------------------------------------------------------------


class AbstentionDisposition(str, Enum):
    NO_VALUE = "NO_VALUE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    POLICY_REJECTED = "POLICY_REJECTED"


class PolicyDecision(StrictModel):
    opportunity_id: str
    side: Side
    signal_type: SignalType
    disposition: Optional[AbstentionDisposition] = None
    reasons: List[SignalReason]
    hard_rule_results: List[HardRuleResult] = Field(default_factory=list)
    soft_score_components: List[SoftScoreComponent] = Field(default_factory=list)
    aggregate_soft_score: Optional[float] = None
    policy_version: str
    policy_manifest_hash: str
    decided_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PolicyDecision":
        if not self.reasons:
            raise ValueError("reasons nunca puede estar vacío (CONTRACTS_FASE3.md §11)")

        if self.signal_type == SignalType.PASS and self.disposition is None:
            raise ValueError("signal_type=PASS exige disposition no nulo (Corrección G)")
        if self.signal_type in (SignalType.ENTER, SignalType.WATCH) and self.disposition is not None:
            raise ValueError(
                f"signal_type={self.signal_type.value} no admite disposition (Corrección G)"
            )

        if self.signal_type == SignalType.ENTER:
            for rule in self.hard_rule_results:
                if rule.category == HardRuleCategory.BLOCK and rule.triggered:
                    raise ValueError(
                        "signal_type=ENTER no puede coexistir con un HardRuleResult "
                        f"BLOCK activo (rule_id={rule.rule_id})"
                    )
            for component in self.soft_score_components:
                if component.is_critical_minimum and component.passed_minimum is not True:
                    raise ValueError(
                        "signal_type=ENTER exige passed_minimum=True en todo componente "
                        f"crítico (component_name={component.component_name}, Principio 9)"
                    )

        _require_utc_aware(self.decided_at, "decided_at")
        return self


# ---------------------------------------------------------------------
# PolicyManifest (CONTRACTS_FASE3.md §15)
# ---------------------------------------------------------------------


class PolicyManifest(StrictModel):
    policy_version: str
    sport: Sport
    hard_block_rules: List[str] = Field(default_factory=list)
    hard_hold_rules: List[str] = Field(default_factory=list)
    soft_score_weights: Dict[str, float] = Field(default_factory=dict)
    critical_minimums: Dict[str, float] = Field(default_factory=dict)
    enter_global_threshold: float
    watch_global_threshold: float
    manifest_hash: str
    created_at: datetime
    promoted_at: Optional[datetime] = None
    promotion_gate_report_ref: Optional[str] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PolicyManifest":
        _require_percent_range(self.enter_global_threshold, "enter_global_threshold")
        _require_percent_range(self.watch_global_threshold, "watch_global_threshold")
        if self.enter_global_threshold < self.watch_global_threshold:
            raise ValueError(
                "enter_global_threshold debe ser >= watch_global_threshold "
                "(POLICY_ENGINE_SPEC.md §5.2)"
            )
        _require_utc_aware(self.created_at, "created_at")
        _require_utc_aware(self.promoted_at, "promoted_at")
        return self
