"""Esquema de señal (Paso 12). Ver PLAN_PHASE2.md §12 y el Design
Proposal explícitamente aprobado antes de esta implementación (decisiones
A1/B2/C2/D3, ver auditoría previa a este commit).

Este módulo define ÚNICAMENTE tipos: el vocabulario `SignalType`
(ENTER/WATCH/PASS) y el contenedor `SignalInputs` con los datos que una
futura función de umbral necesitaría leer. Deliberadamente NO define
ninguna función que decida `SignalType` a partir de esos inputs -- esa
lógica de clasificación (reglas, ML, o híbrida) queda fuera de este
archivo, en un módulo futuro separado, tal como PLAN_PHASE2.md §16 exige
explícitamente ("no debe construirse todavía").

`SignalInputs` es por lado (`Side.YES` / `Side.NO`), nunca por evento --
mismo invariante ya establecido en el Paso 8 (`src/signals/edge.py`,
`src/signals/expected_value.py`): EDGE_YES/EDGE_NO y EV por lado son
independientes y nunca se cruzan. Un evento completo se describe con dos
instancias de `SignalInputs`, correlacionadas por `event_id`.

`SignalInputs` es `frozen=True`: refuerza al nivel del tipo la misma
garantía de pureza que ya declaran por escrito `edge.py`/`expected_value.py`
("100% puras y deterministas") -- una vez construido, no puede mutarse.

Acoplamiento deliberadamente mínimo (Ambigüedad D, decisión D3): se
reutiliza `ModelStatus` (`src.models.base`) y `Sport` (`src.models.schemas`)
-- ambos enums estables sin lógica, ya importados por `edge.py`/
`expected_value.py`/`evaluation/reports.py` -- pero NO se embeben
`PModelOutput`, `QualityScoreOutput` ni `NormalizedRecord` completos como
campos; todos los valores derivados (p_model, market_price, edge, ev,
confidence) viajan como primitivos ya extraídos, igual que ya hace
`QualityScoreOutput` con sus propios campos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from src.models.base import ModelStatus
from src.models.schemas import Sport


class Side(str, Enum):
    """Lado de un contrato binario. Vocabulario nuevo y autocontenido --
    no existe hoy un enum equivalente en el proyecto."""

    YES = "YES"
    NO = "NO"


class SignalType(str, Enum):
    """Tipos de señal pedidos explícitamente por PLAN_PHASE2.md §12.
    Ninguna función en este módulo (ni en ningún otro todavía) calcula
    este valor -- sin lógica de umbral, tal como exige el plan."""

    ENTER = "ENTER"
    WATCH = "WATCH"
    PASS = "PASS"


@dataclass(frozen=True)
class SignalInputs:
    """Inputs de un lado de un evento para una futura decisión de señal.
    Puramente datos: ningún método calcula edge/EV/confidence -- todos
    llegan ya calculados por el llamador (`src/signals/edge.py`,
    `src/signals/expected_value.py`, `src/uncertainty/quality_score.py`).
    `__post_init__` solo valida invariantes ya establecidos en el
    proyecto (timestamps tz-aware, rangos [0,1]), nunca decide nada."""

    event_id: str
    sport: Sport
    side: Side
    model_status: ModelStatus
    p_model: Optional[float]
    market_price: Optional[float]
    edge: Optional[float]
    ev_bruto: Optional[float]
    ev_neto: Optional[float]
    confidence: Optional[float]
    confidence_method: Optional[str]
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError(
                f"generated_at debe ser tz-aware (UTC), recibido naive: {self.generated_at!r}"
            )
        for field_name in ("p_model", "market_price", "confidence"):
            value = getattr(self, field_name)
            if value is not None and not (0.0 <= value <= 1.0):
                raise ValueError(f"{field_name} fuera de [0,1]: {value}")
