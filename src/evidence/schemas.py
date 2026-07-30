"""Contrato de evidencia (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md §6 y
EVIDENCE_EXPLAINABILITY_SPEC.md §1.

`EvidenceItem` es el hecho estructurado producido por el Evidence Engine
(`src/evidence/evidence_engine.py`, Paso 3.3, no implementado todavía).
Este módulo define únicamente el contrato de datos.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import model_validator

from src.models.schemas import StrictModel


class EvidenceDirection(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    NEUTRAL = "NEUTRAL"


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


class EvidenceItem(StrictModel):
    """Ver CONTRACTS_FASE3.md §6 para el detalle campo por campo."""

    opportunity_id: str
    fact: str
    direction: EvidenceDirection
    source_field: str
    source_timestamp: Optional[datetime] = None
    strength: Optional[float] = None
    generated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "EvidenceItem":
        if not self.fact.strip():
            raise ValueError("fact no puede estar vacío -- ningún hecho se fabrica sin contenido")
        if not self.source_field.strip():
            raise ValueError("source_field no puede estar vacío -- todo hecho debe ser trazable")
        if self.strength is not None and not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength fuera de [0,1]: {self.strength}")
        _require_utc_aware(self.source_timestamp, "source_timestamp")
        _require_utc_aware(self.generated_at, "generated_at")
        return self
