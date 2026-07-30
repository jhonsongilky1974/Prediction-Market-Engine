"""Contrato de EvaluationRecord (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§14 y EVALUATION_LEARNING_SPEC.md §1.

Archivo nuevo dentro del paquete `src/evaluation/` ya existente de Fase 2
(`reports.py`, sin cambios) -- corrección aplicada antes de implementar
este paso, ver FASE3_EXECUTION_PLAN.md, Paso 3.0. La lógica que produce
`EvaluationRecord` en las 5 dimensiones vive en
`src/evaluation/learning.py` (Paso 3.8, no implementado todavía); este
módulo define únicamente el contrato de datos.

`EvaluationScope` formaliza como enum cerrado las 5 dimensiones del
Principio 15 (CONTRACTS_FASE3.md §14 las describía como comentario sobre
un campo `str` libre) -- mismo criterio ya usado en todo el proyecto para
vocabularios cerrados (`SignalType`, `Side`, `ModelStatus`...), en vez de
un string sin validar.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import model_validator

from src.models.schemas import Sport, StrictModel


class EvaluationScope(str, Enum):
    MODEL_PERFORMANCE = "model_performance"
    DECISION_PERFORMANCE = "decision_performance"
    FINANCIAL_PERFORMANCE = "financial_performance"
    OPERATIONAL_PERFORMANCE = "operational_performance"
    LEARNING_PERFORMANCE = "learning_performance"


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


class EvaluationRecord(StrictModel):
    record_id: str
    scope: EvaluationScope
    sport: Optional[Sport] = None
    market_type: Optional[str] = None
    model_version: Optional[str] = None
    calibration_version: Optional[str] = None
    policy_version: Optional[str] = None
    metric_name: str
    metric_value: Optional[float] = None
    sample_size: int
    confidence_interval_low: Optional[float] = None
    confidence_interval_high: Optional[float] = None
    computed_at: datetime
    evaluation_window_start: datetime
    evaluation_window_end: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "EvaluationRecord":
        if not self.metric_name.strip():
            raise ValueError("metric_name no puede estar vacío")
        if self.sample_size < 0:
            raise ValueError(f"sample_size no puede ser negativo: {self.sample_size}")
        if self.sample_size == 0 and self.metric_value is not None:
            raise ValueError(
                "sample_size=0 exige metric_value=None -- nunca se fabrica un valor "
                "sin muestras (mismo principio no negociable de Fase 1/2)"
            )
        if (
            self.confidence_interval_low is not None
            and self.confidence_interval_high is not None
            and self.confidence_interval_low > self.confidence_interval_high
        ):
            raise ValueError(
                "confidence_interval_low no puede ser mayor que confidence_interval_high"
            )

        _require_utc_aware(self.computed_at, "computed_at")
        _require_utc_aware(self.evaluation_window_start, "evaluation_window_start")
        _require_utc_aware(self.evaluation_window_end, "evaluation_window_end")
        if self.evaluation_window_start > self.evaluation_window_end:
            raise ValueError("evaluation_window_start no puede ser posterior a evaluation_window_end")
        return self
