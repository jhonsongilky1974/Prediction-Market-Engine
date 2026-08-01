"""Contratos de Opportunity Lifecycle (Fase 3, Paso 3.0). Ver
CONTRACTS_FASE3.md §12-13 y PLAN_MASTER_FASE3.md Principio 10 /
Hallazgo de Contrato #3 (selection_id).

`compute_selection_id`/`compute_opportunity_id` son las dos funciones
determinísticas que resuelven la identidad estable de una oportunidad --
sin tabla de lookup, reconstruibles desde `(event_id, market_id, side)`.

`OpportunityEvaluation` es inmutable (`frozen=True`): representa una
evaluación puntual ya decidida -- una re-evaluación crea una NUEVA
instancia con `state_version` incrementado, nunca muta la anterior
(mismo principio que `event_snapshots`/`feature_snapshots`/
`event_results` append-only de Fase 2, `src/storage/history_repository.py`).
La persistencia real (tabla SQLite, triggers append-only) vive en
`src/opportunity/opportunity_repository.py` (Paso 3.5, no implementado
todavía) -- este módulo define únicamente el contrato de datos.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field, model_validator

from src.evidence.schemas import EvidenceItem
from src.calibration.schemas import CalibrationOutput
from src.health.schemas import AnalysisHealth
from src.models.schemas import Sport, StrictModel
from src.payoff.schemas import PayoffEstimate
from src.policy.schemas import ConfidenceProfile, PolicyDecision
from src.signals.signal_schema import Side, SignalInputs


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def compute_selection_id(market_id: str, side: Side) -> str:
    """selection_id determinístico -- Kalshi no expone un id de selección
    separado del contrato binario (Hallazgo de Contrato #3)."""
    return f"{market_id}:{side.value}"


def compute_opportunity_id(event_id: str, selection_id: str) -> str:
    """opportunity_id determinístico -- misma identidad para el mismo
    (event_id, selection_id) siempre, sin estado ni tabla de lookup."""
    return f"opp:{event_id}:{selection_id}"


# ---------------------------------------------------------------------
# Opportunity (CONTRACTS_FASE3.md §12)
# ---------------------------------------------------------------------


class Opportunity(StrictModel):
    opportunity_id: str
    event_id: str
    market_id: Optional[str] = None
    selection_id: str
    side: Side
    sport: Sport
    first_seen_at: datetime
    last_evaluated_at: datetime
    state_version: int
    previous_signal_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Opportunity":
        if self.state_version < 1:
            raise ValueError(f"state_version debe ser >= 1: {self.state_version}")

        # selection_id solo se verifica contra el formato determinístico
        # cuando market_id existe -- si aún no hay market_id (matching no
        # resuelto todavía, Fase 1), no se fabrica uno: el llamador es
        # responsable del valor de selection_id en ese caso.
        if self.market_id is not None:
            expected_selection_id = compute_selection_id(self.market_id, self.side)
            if self.selection_id != expected_selection_id:
                raise ValueError(
                    f"selection_id={self.selection_id!r} no coincide con el valor "
                    f"determinístico esperado {expected_selection_id!r} para "
                    f"market_id={self.market_id!r}, side={self.side.value}"
                )

        expected_opportunity_id = compute_opportunity_id(self.event_id, self.selection_id)
        if self.opportunity_id != expected_opportunity_id:
            raise ValueError(
                f"opportunity_id={self.opportunity_id!r} no coincide con el valor "
                f"determinístico esperado {expected_opportunity_id!r} para "
                f"event_id={self.event_id!r}, selection_id={self.selection_id!r}"
            )

        _require_utc_aware(self.first_seen_at, "first_seen_at")
        _require_utc_aware(self.last_evaluated_at, "last_evaluated_at")
        if self.last_evaluated_at < self.first_seen_at:
            raise ValueError("last_evaluated_at no puede ser anterior a first_seen_at")
        return self


# ---------------------------------------------------------------------
# OpportunityEvaluation (CONTRACTS_FASE3.md §13) -- inmutable
# ---------------------------------------------------------------------


class OpportunityEvaluation(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_id: str
    opportunity_id: str
    state_version: int
    signal_inputs: SignalInputs
    calibration_output: CalibrationOutput
    payoff_estimate: Optional[PayoffEstimate] = None
    confidence_profile: ConfidenceProfile
    analysis_health: AnalysisHealth
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    policy_decision: PolicyDecision
    decision_timestamp: datetime
    data_cutoff_timestamp: datetime
    market_snapshot_timestamp: Optional[datetime] = None
    # Fase 4, Paso 4.1: rectificado de `str` obligatorio a `Optional[str]`
    # -- mismo error de transcripción ya corregido una vez en
    # `CalibrationOutput.model_version` (Paso 3.1, CONTINUITY.md §0.3.1).
    # `PModelOutput.model_version` (src/models/base.py) es `Optional[str]`,
    # y en producción es siempre `None` (ningún modelo entrenado existe
    # todavía) -- este campo debe reflejar exactamente esa fuente.
    model_version: Optional[str] = None
    calibration_version: Optional[str] = None
    policy_version: str
    feature_schema_version: str

    @model_validator(mode="after")
    def _validate_invariants(self) -> "OpportunityEvaluation":
        if self.state_version < 1:
            raise ValueError(f"state_version debe ser >= 1: {self.state_version}")
        _require_utc_aware(self.decision_timestamp, "decision_timestamp")
        _require_utc_aware(self.data_cutoff_timestamp, "data_cutoff_timestamp")
        _require_utc_aware(self.market_snapshot_timestamp, "market_snapshot_timestamp")
        return self
