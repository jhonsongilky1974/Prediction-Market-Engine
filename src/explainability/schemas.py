"""Contrato de explicación (Fase 3, Paso 3.6). Ver CONTRACTS_FASE3.md §17
y EVIDENCE_EXPLAINABILITY_SPEC.md §2.

ADICIÓN CONTRACTUAL CORRECTIVA (aprobada explícitamente por el usuario
antes de crear este archivo, ver CONTINUITY.md §0.13): `ExplanationOutput`
se esbozó en `EVIDENCE_EXPLAINABILITY_SPEC.md` §2 durante la auditoría
original, pero nunca se incluyó en la lista cerrada de 16 contratos de
`CONTRACTS_FASE3.md` ni se scaffoldeó en el Paso 3.0 (`src/explainability/`
no existía). Se crea aquí, ahora, como 17ª entrada de esa lista -- mismo
patrón `StrictModel` que los otros 16, no una decisión de diseño nueva:
el Principio 6/14 (Evidence Engine y Explainability Engine separados)
siempre exigió que este contrato existiera en algún lugar.

Este módulo define únicamente el contrato de datos. La función que lo
produce vive en `src/explainability/explainability_engine.py` (Paso
3.6, no implementado todavía en el momento de escribir este archivo).
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import Field, model_validator

from src.models.schemas import StrictModel


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


class ExplanationOutput(StrictModel):
    """Ver CONTRACTS_FASE3.md §17 para el detalle campo por campo."""

    opportunity_id: str
    evaluation_id: str
    headline: str
    reasons_explained: List[str] = Field(default_factory=list)
    evidence_for: List[str] = Field(default_factory=list)
    evidence_against: List[str] = Field(default_factory=list)
    disclaimers: List[str] = Field(default_factory=list)
    generated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "ExplanationOutput":
        if not self.headline.strip():
            raise ValueError("headline no puede estar vacío -- ninguna explicación se fabrica sin contenido")
        if not self.reasons_explained:
            raise ValueError(
                "reasons_explained no puede estar vacío -- toda explicación debe trazar al menos "
                "un SignalReason real (mismo invariante que PolicyDecision.reasons, Paso 3.0)"
            )
        _require_utc_aware(self.generated_at, "generated_at")
        return self
