"""Tests de src/positions/money.py -- precisión monetaria (Fase 6,
decisión: prohibido float en dinero/precios/fees/proceeds/cost basis)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.positions.money import (
    MoneyPrecisionError,
    require_exact_cents,
    require_non_negative,
    round_half_up_cents,
)


def test_require_exact_cents_accepts_integral_decimal():
    assert require_exact_cents(Decimal("50"), "price") == Decimal("50")


def test_require_exact_cents_rejects_fractional_cents():
    with pytest.raises(MoneyPrecisionError, match="entero de centavos"):
        require_exact_cents(Decimal("50.5"), "price")


def test_require_exact_cents_rejects_float():
    with pytest.raises(MoneyPrecisionError, match="debe ser Decimal"):
        require_exact_cents(50.0, "price")  # type: ignore[arg-type]


def test_require_non_negative_rejects_negative():
    with pytest.raises(MoneyPrecisionError, match="no puede ser negativo"):
        require_non_negative(Decimal("-1"), "capital")


def test_require_non_negative_rejects_float():
    with pytest.raises(MoneyPrecisionError, match="debe ser Decimal"):
        require_non_negative(1.5, "capital")  # type: ignore[arg-type]


def test_round_half_up_cents_rounds_up_at_half():
    assert round_half_up_cents(Decimal("62.5")) == Decimal("63")


def test_round_half_up_cents_never_used_for_fees_allows_fractional_input():
    # round_half_up_cents en sí no rechaza fracción de centavo -- eso es
    # exactamente lo que la vuelve segura para display de un fee
    # fraccionario, pero prohibida para alimentar capital recovery
    # (regla documentada en el módulo, verificada a nivel de
    # capital_recovery.py -- ver test_positions_capital_recovery.py).
    assert round_half_up_cents(Decimal("6.926")) == Decimal("7")
