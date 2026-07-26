"""EV bruto/neto side-aware (Paso 8). Ver PLAN_PHASE2.md §7 y el Design
Proposal explícitamente aprobado antes de esta implementación.

Mismas garantías que `src/signals/edge.py`: funciones 100% puras y
deterministas, sin I/O, sin dependencia del reloj. Reutiliza
`market_price_yes`/`market_price_no` (Paso 3) sin modificarlas. Misma
advertencia de interpretación de `p_model_yes` que en `edge.py` (ver ese
módulo) -- aplica igual aquí.
"""
from __future__ import annotations

from typing import Optional

from src.models.base import PModelOutput
from src.models.schemas import NormalizedRecord
from src.pricing.market_pricing import market_price_no, market_price_yes


def compute_ev_yes_bruto(model_output: PModelOutput, record: NormalizedRecord) -> Optional[float]:
    """EV_YES_bruto = P_model_YES*(1-YES_ASK) - (1-P_model_YES)*YES_ASK (§7)."""
    p_model_yes = model_output.p_model_yes
    if p_model_yes is None:
        return None
    yes_ask = market_price_yes(record)
    if yes_ask is None:
        return None
    return p_model_yes * (1.0 - yes_ask) - (1.0 - p_model_yes) * yes_ask


def compute_ev_no_bruto(model_output: PModelOutput, record: NormalizedRecord) -> Optional[float]:
    """EV_NO_bruto = P_model_NO*(1-NO_ASK) - (1-P_model_NO)*NO_ASK (§7).
    Independiente de `compute_ev_yes_bruto` -- su propia probabilidad,
    su propio precio."""
    p_model_yes = model_output.p_model_yes
    if p_model_yes is None:
        return None
    no_ask = market_price_no(record)
    if no_ask is None:
        return None
    p_model_no = 1.0 - p_model_yes
    return p_model_no * (1.0 - no_ask) - (1.0 - p_model_no) * no_ask


def compute_ev_yes_neto(
    model_output: PModelOutput, record: NormalizedRecord, ev_yes_bruto: Optional[float]
) -> Optional[float]:
    """EV_YES_neto permanece `None` mientras `exchange_fee` sea `None`
    en el esquema (§7) -- Kalshi no expone ese campo hoy. La fórmula
    exacta de incorporación del fee (¿resta plana? ¿porcentaje según
    `fee_type`?) NO está especificada por el plan y no se inventa aquí --
    queda deliberadamente diferida hasta que exista el dato real."""
    if record.market.exchange_fee is None or ev_yes_bruto is None:
        return None
    raise NotImplementedError(
        "EV_YES_neto: fórmula de incorporación de exchange_fee no especificada por el "
        "plan -- exchange_fee nunca está poblado en la práctica hoy; implementar cuando "
        "exista el dato real y una decisión explícita sobre la fórmula."
    )


def compute_ev_no_neto(
    model_output: PModelOutput, record: NormalizedRecord, ev_no_bruto: Optional[float]
) -> Optional[float]:
    """Ver `compute_ev_yes_neto` -- misma limitación deliberada."""
    if record.market.exchange_fee is None or ev_no_bruto is None:
        return None
    raise NotImplementedError(
        "EV_NO_neto: fórmula de incorporación de exchange_fee no especificada por el "
        "plan -- exchange_fee nunca está poblado en la práctica hoy; implementar cuando "
        "exista el dato real y una decisión explícita sobre la fórmula."
    )
