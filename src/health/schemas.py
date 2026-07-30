"""Contrato de Analysis Health (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§5 y PLAN_MASTER_FASE3.md Principio 5.

`AnalysisHealth` es EXCLUSIVAMENTE informativo -- ningún componente de
este contrato puede usarse como insumo del Soft Score
(`src/policy/soft_score.py`, Paso 3.4.4). Ese invariante se verifica con
un test de arquitectura en el Paso 3.7, no en este módulo (que solo
define el dato).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field, model_validator

from src.models.schemas import StrictModel


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


class AnalysisHealth(StrictModel):
    """Ver CONTRACTS_FASE3.md §5 para el detalle campo por campo."""

    opportunity_id: str
    completeness_signal: Optional[float] = None
    consistency_signal: Optional[float] = None
    evidence_density: Optional[int] = None
    staleness_seconds: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    computed_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "AnalysisHealth":
        _require_percent_range(self.completeness_signal, "completeness_signal")
        _require_percent_range(self.consistency_signal, "consistency_signal")
        if self.evidence_density is not None and self.evidence_density < 0:
            raise ValueError(f"evidence_density no puede ser negativo: {self.evidence_density}")
        if self.staleness_seconds is not None and self.staleness_seconds < 0:
            raise ValueError(f"staleness_seconds no puede ser negativo: {self.staleness_seconds}")
        _require_utc_aware(self.computed_at, "computed_at")
        return self
