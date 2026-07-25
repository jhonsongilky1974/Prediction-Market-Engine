"""Infraestructura de modelo (Paso 5a) -- contrato de salida común para
`P_model`, independiente del deporte o del algoritmo concreto. Ver
PLAN_PHASE2.md §5.

Separación obligatoria del plan: la infraestructura (este contrato, el
dataset builder, el training pipeline, el inference contract) se
construye y se prueba siempre, incluso sin ningún modelo entrenado. Un
modelo real solo existe cuando `model_status == TRAINED`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ModelStatus(str, Enum):
    """`MODEL_NOT_TRAINED`: la infraestructura existe pero no hay ningún
    artefacto entrenado persistido todavía (estado por defecto en
    inferencia mientras el registro esté vacío, sea porque nunca se
    intentó entrenar o porque el intento anterior no alcanzó el umbral).
    `INSUFFICIENT_HISTORY`: resultado explícito de UN INTENTO de
    entrenamiento (`train_mlb_baseline_model`) que construyó el dataset y
    no alcanzó el volumen mínimo -- no fabrica ningún modelo.
    `TRAINED`: existe un artefacto real, versionado y evaluable."""

    MODEL_NOT_TRAINED = "MODEL_NOT_TRAINED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    TRAINED = "TRAINED"


@dataclass
class PModelOutput:
    """Contrato de salida OBLIGATORIO para TODO modelo, entrenado o no
    (PLAN_PHASE2.md §5). Mientras `model_status != TRAINED`,
    `p_model_yes` es SIEMPRE `None` -- nunca se fabrica una probabilidad
    para aparentar que el modelo está operativo.

    ADVERTENCIA DE INTERPRETACIÓN (decisión arquitectónica explícita,
    misma lógica ya aprobada para la Ambigüedad #2 del Paso 4 -- ver
    `src/pricing/odds_consensus.py`): NO existe todavía ninguna capa que
    conecte el lado YES de un contrato de Kalshi concreto con
    `participant_a`/`participant_b` de un evento. Por eso, mientras esa
    capa de integración no exista, `p_model_yes` representa la
    probabilidad de la etiqueta NATIVA con la que se entrenó el modelo
    (para el baseline MLB: `P(participant_a gana)`, tal como la registra
    `event_results` -- ver `src/models/mlb_baseline.py`), y NO
    necesariamente la probabilidad del lado YES de un mercado específico.
    No se implementa aquí ninguna conversión automática participante->YES;
    esa traducción pertenece a una futura capa de integración con
    mercados, deliberadamente separada del pipeline de entrenamiento."""

    p_model_yes: Optional[float]
    model_version: Optional[str]
    model_status: ModelStatus
    feature_set_version: str
    prediction_timestamp: datetime
    data_cutoff_timestamp: datetime
    missing_features: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # confidence/uncertainty calibrados pertenecen al Paso 7
    # (confidence_method="HEURISTIC_V1", ver PLAN_PHASE2.md §9) -- ese
    # módulo no existe todavía, así que ambos quedan explícitamente None
    # aquí. Nunca se fabrica ni se infiere un valor placeholder.
    confidence: Optional[float] = None
    confidence_method: Optional[str] = None

    def __post_init__(self) -> None:
        if self.model_status != ModelStatus.TRAINED and self.p_model_yes is not None:
            raise ValueError(
                f"p_model_yes debe ser None mientras model_status != TRAINED "
                f"(recibido model_status={self.model_status}, p_model_yes={self.p_model_yes})"
            )
        if self.p_model_yes is not None and not (0.0 <= self.p_model_yes <= 1.0):
            raise ValueError(f"p_model_yes fuera de [0,1]: {self.p_model_yes}")
        for ts_name in ("prediction_timestamp", "data_cutoff_timestamp"):
            ts = getattr(self, ts_name)
            if ts.tzinfo is None or ts.utcoffset() is None:
                raise ValueError(f"{ts_name} debe ser tz-aware (UTC), recibido naive: {ts!r}")
