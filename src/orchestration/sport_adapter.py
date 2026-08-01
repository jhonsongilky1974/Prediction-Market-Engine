"""`SportAdapter` (Fase 4, Paso 4.1). Ver `ORCHESTRATOR_SPEC.md` §2.3.

Formaliza las dos únicas piezas realmente específicas por deporte que el
orquestador necesita -- `predict_fn`/`load_artifact_fn` -- para que
`decision_pipeline.py` nunca importe `mlb_baseline`/`tennis_baseline`/
`registry` directamente. Incorporar un deporte nuevo en el futuro solo
requiere construir un `SportAdapter` nuevo en la capa de composición
(`scripts/run_e2e.py`), sin tocar ninguna línea de
`src/orchestration/decision_pipeline.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Tuple

from src.calibration.calibration_layer import Calibrator
from src.models.base import PModelOutput
from src.models.schemas import NormalizedRecord, Sport

PredictFn = Callable[[NormalizedRecord, Any, datetime, Optional[Tuple[Any, Any]]], PModelOutput]
LoadArtifactFn = Callable[[], Optional[Tuple[Any, Any]]]
# Calibración real (ver CALIBRATION_SPEC.md §4.3): recibe el
# `model_version` del artefacto base ya cargado -- un calibrador solo
# debe aplicarse al `model_version` exacto contra el que se ajustó.
LoadCalibratorFn = Callable[[str], Optional[Calibrator]]


@dataclass(frozen=True)
class SportAdapter:
    sport: Sport
    predict_fn: PredictFn
    load_artifact_fn: LoadArtifactFn
    # Aditivo, opcional -- `None` (default) preserva el comportamiento
    # actual (calibrator=None) para cualquier deporte sin calibrador real
    # todavía (MLB hoy).
    load_calibrator_fn: Optional[LoadCalibratorFn] = None
