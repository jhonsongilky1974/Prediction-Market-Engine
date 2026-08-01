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

REENCUADRE DE D-3 (investigación posterior al cierre del roadmap, ver
CONTINUITY.md §0.18): D-3 se redactó originalmente asumiendo que Kalshi
"expondría" el fee como un campo por-mercado algún día. Investigación
directa (payloads reales en `data/raw/kalshi/*.json`, código de
`src/connectors/kalshi.py`) confirma que ese campo nunca existió y no es
así como Kalshi cobra: publica una FÓRMULA pública basada en el precio
(`kalshi.com/docs/kalshi-fee-schedule.pdf`), no un campo por-mercado.
Dos fuentes secundarias (búsqueda web, no la fuente primaria -- el PDF
oficial devolvió HTTP 429 en 3 intentos) coinciden en la estructura
(`taker_fee ≈ 0.07 × precio × (1-precio)` por contrato, `maker_fee ≈ 25%`
del taker) pero difieren en el redondeo exacto -- insuficiente para
codificarla con la misma certeza que el resto de este proyecto exige
(Corrección C: "no inventar costes"). `_estimate_kalshi_taker_fee()`
(abajo) es el punto de enganche preparado para cuando esa verificación
se complete -- hoy devuelve `None` siempre, sin excepción, hasta que se
confirme contra la fuente primaria.

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


def _estimate_kalshi_taker_fee(price: Optional[float]) -> Optional[float]:
    """PUNTO DE ENGANCHE preparado para D-3 (ver docstring del módulo,
    "REENCUADRE DE D-3", y CONTINUITY.md §0.18) -- NO IMPLEMENTAR el
    cuerpo de esta función con una fórmula de fuente secundaria.

    Devuelve SIEMPRE None hasta que la fórmula pública de fees de Kalshi
    (`kalshi.com/docs/kalshi-fee-schedule.pdf`) se verifique directamente
    contra la fuente primaria -- 3 intentos de `WebFetch` devolvieron
    HTTP 429 (límite de tasa del servidor, no un bloqueo permanente).
    Dos fuentes secundarias, NO citables como evidencia verificada,
    sugieren una estructura `taker_fee ~= 0.07 * price * (1 - price)`
    por contrato (simétrica, máximo en price=0.50) con `maker_fee` ~=
    25% de esa cifra -- pero difieren en la regla de redondeo exacta, y
    ninguna es la fuente primaria. Implementar esto con esa incertidumbre
    violaría Corrección C ("no inventar costes").

    Cuando la verificación se complete: reemplazar el `return None` por
    la fórmula confirmada, actualizar el docstring citando la fuente
    primaria verificada, y solo entonces cambiar
    `estimate_payoff()`/`PayoffEstimate.net_ev_status` para permitir
    `COMPUTED`. Ningún otro cambio de este archivo debería ser
    necesario -- ese es el propósito de este punto de enganche."""
    return None


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
    incondicionalmente. entry_price/spread se propagan desde el registro
    cuando existen; entry_fee usa el campo real del registro si existe,
    si no el punto de enganche de D-3 (hoy siempre None); ningún campo
    de costo se fabrica."""
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

    # entry_fee: prioriza un campo real del propio registro si algún día
    # existe (Kalshi no lo expone hoy -- ver market_normalizer.py, Fase
    # 1/2); si no, intenta el punto de enganche de D-3 (hoy siempre
    # None). Ninguna de las dos fuentes fabrica un valor.
    entry_fee = record.market.exchange_fee
    if entry_fee is None:
        entry_fee = _estimate_kalshi_taker_fee(entry_price) if platform == "KALSHI" else None

    return PayoffEstimate(
        opportunity_id=opportunity_id,
        side=side,
        platform=platform,
        entry_price=entry_price,
        payout=payout,
        loss=loss,
        entry_fee=entry_fee,
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
