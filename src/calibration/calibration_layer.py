"""Calibration Layer (Fase 3, Paso 3.1). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.1, y MODEL_PIPELINE_SPEC.md §3.

`calibrate()` es la última capa de la arquitectura jerárquica de
P_model (Principio 11): produce `CalibrationOutput` (Paso 3.0,
`src/calibration/schemas.py`, sin cambios) a partir de un `PModelOutput`
(Fase 2, `src/models/base.py`, sin cambios) y, opcionalmente, un
`Calibrator` ya entrenado.

Ningún `Calibrator` real (Platt scaling / isotonic regression) se
entrena en este paso ni en el alcance de Fase 3 -- depende de histórico
real (DECISIÓN PENDIENTE D-1, `PLAN_MASTER_FASE3.md` §8), fuera de
alcance. `Calibrator` se define aquí únicamente como una interfaz
mínima (`Protocol`): si en el futuro existe una implementación real que
la satisfaga, `calibrate()` ya sabe aplicarla sin que este archivo
vuelva a tocarse -- pero hoy, en la práctica, todo llamador real del
proyecto pasa `calibrator=None` (no existe ninguna instancia concreta en
el repositorio), por lo que el resultado observable hoy es siempre
`p_model_calibrated=None`/`calibration_version=None`. Ese es un estado
honesto y esperado (mismo principio que `ModelStatus.MODEL_NOT_TRAINED`
en Fase 2: ausencia de calibración no es un error).

Función 100% pura y determinista: sin I/O, sin red, sin estado mutable
-- mismo `PModelOutput` + mismo `calibrator` + mismo `now` producen
siempre el mismo `CalibrationOutput` (mismo estándar que
`src/signals/edge.py`/`expected_value.py`, Fase 2). El reloj se recibe
como parámetro inyectable (`now: Optional[datetime] = None`), mismo
patrón que `compute_quality_score` (`src/uncertainty/quality_score.py`,
Fase 2) -- nunca se llama `datetime.now()` sin poder sobreescribirlo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from src.calibration.schemas import CalibrationOutput
from src.models.base import PModelOutput


class Calibrator(Protocol):
    """Interfaz mínima que cualquier calibrador real (Paso posterior,
    fuera de alcance de Fase 3) deberá satisfacer. Sin implementación
    concreta en este repositorio todavía."""

    calibration_version: str
    calibration_method: str

    def calibrate(self, p_raw: float) -> float: ...


def calibrate(
    model_output: PModelOutput,
    calibrator: Optional[Calibrator] = None,
    now: Optional[datetime] = None,
) -> CalibrationOutput:
    """Produce CalibrationOutput a partir de PModelOutput.

    `p_model_raw` siempre es una copia exacta de `model_output.p_model_yes`
    -- nunca se recalcula ni se redondea. `p_model_calibrated` solo se
    puebla cuando existen SIMULTÁNEAMENTE un `calibrator` y un
    `p_model_raw` no nulo; en cualquier otro caso (sin calibrador, o
    modelo no entrenado -- `model_output.p_model_yes is None`) el
    resultado es `p_model_calibrated=None`/`calibration_version=None`,
    sin excepción y sin valor fabricado.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    p_model_raw = model_output.p_model_yes

    if calibrator is not None and p_model_raw is not None:
        p_model_calibrated = calibrator.calibrate(p_model_raw)
        calibration_version = calibrator.calibration_version
        calibration_method = calibrator.calibration_method
        calibrated_at = now
    else:
        p_model_calibrated = None
        calibration_version = None
        calibration_method = None
        calibrated_at = None

    return CalibrationOutput(
        p_model_raw=p_model_raw,
        p_model_calibrated=p_model_calibrated,
        model_version=model_output.model_version,
        calibration_version=calibration_version,
        calibration_method=calibration_method,
        calibrated_at=calibrated_at,
        prediction_timestamp=model_output.prediction_timestamp,
        data_cutoff_timestamp=model_output.data_cutoff_timestamp,
    )
