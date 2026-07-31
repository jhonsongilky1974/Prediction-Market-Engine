"""Payoff Model (Fase 3, Paso 3.2). Ver FASE3_EXECUTION_PLAN.md, Paso
3.2, y CONTRACTS_FASE3.md §3 (Corrección C).

`estimate_payoff()` produce `PayoffEstimate` (Paso 3.0,
`src/payoff/schemas.py`, sin cambios) a partir de un `NormalizedRecord` +
`Side` (Fase 2, sin cambios) -- reutiliza literalmente
`market_price_yes`/`market_price_no` (`src/pricing/market_pricing.py`,
Fase 2) para `entry_price`, sin reimplementar ese cálculo.

DECISIÓN DE ALCANCE (no una desviación silenciosa -- ver
`PLAN_MASTER_FASE3.md` §8, DECISIÓN PENDIENTE D-3): este módulo **nunca**
produce `net_ev_status=COMPUTED`. La fórmula exacta de incorporación de
`exchange_fee`/`estimated_exit_fee`/`spread`/`slippage` a un EV neto real
está deliberadamente sin especificar -- Kalshi no expone esos campos con
evidencia real hoy (mismo estado ya documentado en Fase 2 para
`compute_ev_yes_neto`/`compute_ev_no_neto`,
`src/signals/expected_value.py`), y no se inventa aquí. Por eso
`estimate_payoff()` no recibe ninguna probabilidad de modelo como
parámetro: aunque la recibiera, no habría una fórmula aprobada para
combinarla con los costos. Cuando D-3 se resuelva, este archivo se
actualizará explícitamente para ese caso -- no antes.

`entry_fee`/`spread` sí se propagan (nunca se descartan) cuando el
propio `NormalizedRecord` los trae poblados, porque propagar un valor
observado no es lo mismo que inventar una fórmula de incorporación.

Función 100% pura: sin I/O, sin red, `now` inyectable (mismo patrón que
`calibration_layer.py`, Paso 3.1).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.models.schemas import NormalizedRecord
from src.payoff.schemas import NetEvStatus, PayoffEstimate
from src.pricing.market_pricing import market_price_no, market_price_yes
from src.signals.signal_schema import Side

_KNOWN_BINARY_PAYOUT_PLATFORMS = {"KALSHI"}
"""Plataformas cuyo contrato binario estándar liquida en {0, 1} -- hecho
estructural de la plataforma, no un dato observado por evento. Ninguna
otra plataforma asume payout=1.0 sin evidencia."""


def estimate_payoff(
    record: NormalizedRecord,
    side: Side,
    opportunity_id: str,
    platform: str = "KALSHI",
    now: Optional[datetime] = None,
) -> PayoffEstimate:
    """net_ev_status es SIEMPRE NetEvStatus.UNKNOWN en este paso (ver
    DECISIÓN PENDIENTE D-3 en el docstring del módulo) -- ev_to_settlement/
    ev_to_planned_exit/max_acceptable_entry_price permanecen None
    incondicionalmente. entry_price/entry_fee/spread se propagan desde el
    registro cuando existen; ningún campo de costo se fabrica."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    if side == Side.YES:
        entry_price = market_price_yes(record)
        spread = record.market.spread_yes
    else:
        entry_price = market_price_no(record)
        spread = record.market.spread_no

    payout = 1.0 if platform in _KNOWN_BINARY_PAYOUT_PLATFORMS else None
    loss = entry_price if entry_price is not None else None
    breakeven_probability = entry_price if (payout == 1.0 and entry_price is not None) else None

    return PayoffEstimate(
        opportunity_id=opportunity_id,
        side=side,
        platform=platform,
        entry_price=entry_price,
        payout=payout,
        loss=loss,
        entry_fee=record.market.exchange_fee,
        estimated_exit_fee=None,
        spread=spread,
        slippage_estimate=None,
        ev_to_settlement=None,
        ev_to_planned_exit=None,
        breakeven_probability=breakeven_probability,
        max_acceptable_entry_price=None,
        net_ev_status=NetEvStatus.UNKNOWN,
        cost_evidence_refs=[],
        computed_at=now,
    )
