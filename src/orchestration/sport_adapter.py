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

from src.models.base import PModelOutput
from src.models.schemas import NormalizedRecord, Sport

PredictFn = Callable[[NormalizedRecord, Any, datetime, Optional[Tuple[Any, Any]]], PModelOutput]
LoadArtifactFn = Callable[[], Optional[Tuple[Any, Any]]]


@dataclass(frozen=True)
class SportAdapter:
    sport: Sport
    predict_fn: PredictFn
    load_artifact_fn: LoadArtifactFn
