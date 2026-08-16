"""Representación monetaria segura para Phase 6 (Position Management).

Regla no-negociable (decisión de precisión monetaria, ver CONTINUITY.md
cuando se documente el cierre de Tramo 1): prohibido usar `float` para
dinero, precios financieros, fees, proceeds, cost basis o capital
recovery en `src.positions`. `Decimal` es el tipo canónico en todo el
módulo -- nunca `float`.

Dos granularidades conviven, ambas en centavos:

- Precios (fill price, requested price, planned target price, order
  price, observed market price): la granularidad REAL es exactamente 1
  centavo -- Kalshi cotiza contratos en centavos enteros (1-99).
  `require_exact_cents()` rechaza cualquier valor con fracción de
  centavo en estos campos.
- Fees: pueden requerir fracción de centavo -- la fórmula pública de
  Kalshi (no verificada todavía, ver `src/payoff/payoff_model.py`,
  `_estimate_kalshi_taker_fee` siempre retorna `None` por esa razón) es
  `0.07 * price * (1-price)`, no necesariamente un entero de centavos.
  Se conservan como `Decimal` de precisión completa, sin cuantizar.

`round_half_up_cents()` es EXCLUSIVAMENTE para campos derivados de solo
DISPLAY (p.ej. `avg_fill_price_cents` mostrado al usuario). Ningún valor
redondeado con esta función debe alimentar un cálculo posterior de
capital recovery -- ver `src/positions/capital_recovery.py`.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTS_QUANTUM = Decimal("1")


class MoneyPrecisionError(ValueError):
    """Un campo de precio recibió un valor con fracción de centavo, o un
    monto monetario es negativo donde el contrato no lo permite."""


def require_exact_cents(value: Decimal, field_name: str) -> Decimal:
    """Valida que `value` (expresado en centavos) sea un entero exacto --
    sin fracción de centavo. Usar en precios (fill/requested/planned/
    order/observed), NUNCA en fees (que sí pueden tener fracción de
    centavo)."""
    if not isinstance(value, Decimal):
        raise MoneyPrecisionError(
            f"{field_name}={value!r} debe ser Decimal, recibido {type(value).__name__} "
            "(prohibido usar float para dinero)"
        )
    if value != value.to_integral_value():
        raise MoneyPrecisionError(
            f"{field_name}={value} debe ser un número entero de centavos "
            "(la granularidad real de un precio de contrato es 1 centavo)"
        )
    return value


def require_non_negative(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise MoneyPrecisionError(
            f"{field_name}={value!r} debe ser Decimal, recibido {type(value).__name__} "
            "(prohibido usar float para dinero)"
        )
    if value < 0:
        raise MoneyPrecisionError(f"{field_name}={value} no puede ser negativo")
    return value


def round_half_up_cents(value: Decimal) -> Decimal:
    """SOLO para campos de display (p.ej. avg_fill_price_cents). El
    resultado nunca debe usarse como input de un cálculo de capital
    recovery -- ver docstring del módulo."""
    return value.quantize(CENTS_QUANTUM, rounding=ROUND_HALF_UP)
