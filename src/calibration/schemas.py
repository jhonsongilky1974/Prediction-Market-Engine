"""Contrato de calibración (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§1-2 y MODEL_PIPELINE_SPEC.md §3-4.

`CalibrationOutput` es la resolución del Principio 12 (conservar
p_model_raw/p_model_calibrated/model_version/calibration_version) por
composición sobre `PModelOutput` (Fase 2, `src/models/base.py`, sin
cambios) -- no reemplaza ni colisiona con `NormalizedRecord.model_output`
(schemas.py, Fase 1, vestigial, permanece siempre None -- ver
PLAN_MASTER_FASE3.md §5, Hallazgo de Contrato #1).

Este módulo define únicamente el contrato de datos y sus invariantes.
Ninguna función de calibración vive aquí -- eso es
`src/calibration/calibration_layer.py` (Paso 3.1, no implementado
todavía).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import model_validator

from src.models.schemas import StrictModel


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def _require_unit_interval(value: Optional[float], field_name: str) -> None:
    if value is None:
        return
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{field_name} fuera de [0,1]: {value}")


class CalibrationOutput(StrictModel):
    """Ver CONTRACTS_FASE3.md §2 para el detalle campo por campo."""

    p_model_raw: Optional[float] = None
    p_model_calibrated: Optional[float] = None
    model_version: str
    calibration_version: Optional[str] = None
    calibration_method: Optional[str] = None
    calibrated_at: Optional[datetime] = None
    prediction_timestamp: datetime
    data_cutoff_timestamp: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "CalibrationOutput":
        _require_unit_interval(self.p_model_raw, "p_model_raw")
        _require_unit_interval(self.p_model_calibrated, "p_model_calibrated")
        _require_utc_aware(self.prediction_timestamp, "prediction_timestamp")
        _require_utc_aware(self.data_cutoff_timestamp, "data_cutoff_timestamp")
        _require_utc_aware(self.calibrated_at, "calibrated_at")

        if self.p_model_calibrated is not None and self.calibration_version is None:
            raise ValueError(
                "p_model_calibrated no puede existir sin calibration_version "
                "(CONTRACTS_FASE3.md §2, invariante 1)"
            )
        if self.p_model_raw is None and self.p_model_calibrated is not None:
            raise ValueError(
                "p_model_calibrated debe ser None cuando p_model_raw es None "
                "(CONTRACTS_FASE3.md §2, invariante 2)"
            )
        return self
