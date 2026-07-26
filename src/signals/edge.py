"""EDGE_YES / EDGE_NO side-aware (Paso 8). Ver PLAN_PHASE2.md §7 y el
Design Proposal explícitamente aprobado antes de esta implementación.

Funciones 100% puras y deterministas: sin I/O, sin red, sin estado
mutable, sin dependencia del reloj -- el mismo `PModelOutput` y el mismo
`NormalizedRecord` producen siempre exactamente el mismo resultado
(reproducibilidad garantizada para testing y backtesting, confirmado
explícitamente antes de implementar).

Reutiliza `market_price_yes`/`market_price_no` de
`src/pricing/market_pricing.py` (Paso 3) SIN modificarlas -- tal como su
propio docstring ya anticipaba ("las aserciones sobre valores exactos de
EDGE_YES/EDGE_NO quedan reservadas para el Paso 8, que reutilizará estas
mismas funciones como entrada").

ADVERTENCIA DE INTERPRETACIÓN (mismo hueco ya documentado como
Ambigüedad #2 del Paso 4 / Ambigüedad C del Paso 5a-6, ver
`src/models/base.py`): `model_output.p_model_yes` representa hoy
`P(participant_a gana)`, no necesariamente el lado YES de un contrato de
Kalshi específico -- la capa de integración participante<->YES no existe
todavía. Este módulo NO intenta resolver ese mapeo: aplica la fórmula de
§7 literalmente, tomando `p_model_yes` tal cual llega. Mientras esa capa
no exista, `EDGE_YES`/`EDGE_NO` deben leerse como "edge contra la
etiqueta nativa del modelo", no garantizadamente contra el YES real de
un mercado de Kalshi.
"""
from __future__ import annotations

from typing import Optional

from src.models.base import PModelOutput
from src.models.schemas import NormalizedRecord
from src.pricing.market_pricing import market_price_no, market_price_yes


def compute_edge_yes(model_output: PModelOutput, record: NormalizedRecord) -> Optional[float]:
    """EDGE_YES = P_model_YES - YES_ASK (§7). `None` si `p_model_yes` no
    existe (`model_status != TRAINED`) o si `market_price_yes` no es
    usable (`NEEDS_REVIEW`, ask ausente, o fuera de [0,1] -- Paso 3)."""
    p_model_yes = model_output.p_model_yes
    if p_model_yes is None:
        return None
    yes_ask = market_price_yes(record)
    if yes_ask is None:
        return None
    return p_model_yes - yes_ask


def compute_edge_no(model_output: PModelOutput, record: NormalizedRecord) -> Optional[float]:
    """EDGE_NO = P_model_NO - NO_ASK = (1 - P_model_YES) - NO_ASK (§7).
    Independiente de `compute_edge_yes` -- nunca se compara P_model_YES
    directamente contra NO_ASK ni se deriva de EDGE_YES."""
    p_model_yes = model_output.p_model_yes
    if p_model_yes is None:
        return None
    no_ask = market_price_no(record)
    if no_ask is None:
        return None
    p_model_no = 1.0 - p_model_yes
    return p_model_no - no_ask
