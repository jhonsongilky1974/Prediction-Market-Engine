"""Pricing de mercado side-aware (Fase 2, Paso 3).

Implementa únicamente `P_market_YES` / `P_market_NO` tal como los define
PLAN_PHASE2.md §7 -- las dos únicas funciones con pseudocódigo explícito
en el plan (`market_price_yes` / `market_price_no`).

DECISIÓN DE ARQUITECTURA (fijada explícitamente por el usuario tras la
revisión contractual del Paso 3, que identificó una ambigüedad real entre
§3/§12-Paso8 y §12/§13-Paso3 respecto a dónde vive EDGE_YES/EDGE_NO):
este módulo **no calcula EDGE**. `PLAN_PHASE2.md` §3 asigna
`EDGE_YES`/`EDGE_NO` a `src/signals/edge.py` (Paso 8), y el plan nunca
definió pseudocódigo de una función de EDGE -- solo la fórmula
matemática (§7). Introducir esa lógica aquí duplicaría responsabilidad
entre dos módulos y contradiría la tabla de arquitectura de §3. En
consecuencia, los "6 tests obligatorios" de §7 se dividen: este módulo
prueba únicamente el comportamiento de `P_market_YES`/`P_market_NO` bajo
esos 6 escenarios (ver `tests/unit/test_market_pricing.py`); las
aserciones sobre valores exactos de `EDGE_YES`/`EDGE_NO` quedan
reservadas para el Paso 8, que reutilizará estas mismas funciones como
entrada.

Reglas no negociables (§7):
  - `NEEDS_REVIEW=True` -> ambos lados `None`, sin excepción.
  - Precio fuera de `[0.0, 1.0]` -> `None`, nunca se clampa.
  - Ask faltante (`None`) en un lado no afecta al otro lado -- gates
    completamente independientes por lado.
  - Ningún lado se reconstruye a partir del otro (nunca `1 - precio`).
  - `LAST_PRICE` nunca se usa como precio ejecutable de ningún lado.

Cómputo puro: sin llamadas de red ni persistencia en este módulo (a
diferencia del Paso 2, el plan no menciona persistencia para el Paso 3).
"""
from __future__ import annotations

from typing import Optional

from src.models.schemas import NormalizedRecord


def market_price_yes(record: NormalizedRecord) -> Optional[float]:
    """P_market_YES = YES_ASK, o None si no es usable (§7).

    None cuando: needs_review=True, yes_ask es None, o yes_ask está
    fuera de [0.0, 1.0]. El precio nunca se clampa a un valor válido.
    """
    if record.data_quality.needs_review:
        return None
    yes_ask = record.market.yes_ask
    if yes_ask is None or not (0.0 <= yes_ask <= 1.0):
        return None
    return yes_ask


def market_price_no(record: NormalizedRecord) -> Optional[float]:
    """P_market_NO = NO_ASK, o None si no es usable (§7).

    None cuando: needs_review=True, no_ask es None, o no_ask está
    fuera de [0.0, 1.0]. El precio nunca se clampa a un valor válido.
    Independiente de `market_price_yes`: nunca se deriva como
    `1 - market_price_yes(record)`.
    """
    if record.data_quality.needs_review:
        return None
    no_ask = record.market.no_ask
    if no_ask is None or not (0.0 <= no_ask <= 1.0):
        return None
    return no_ask
