"""Tests del Paso 4 -- de-vig intra-bookmaker (src/pricing/no_vig.py)."""
from __future__ import annotations

import pytest

from src.pricing.no_vig import devig_bookmaker


def test_devig_sums_to_exactly_one_within_rounding_tolerance():
    result = devig_bookmaker(decimal_odds_yes=1.80, decimal_odds_no=2.10)
    assert result.p_no_vig_yes is not None
    assert result.p_no_vig_no is not None
    assert result.p_no_vig_yes + result.p_no_vig_no == pytest.approx(1.0, abs=1e-9)


def test_devig_known_values():
    # p_raw_yes = 1/1.80 = 0.5556, p_raw_no = 1/2.10 = 0.4762
    # overround = 1.0317, p_no_vig_yes = 0.5385, p_no_vig_no = 0.4615
    result = devig_bookmaker(decimal_odds_yes=1.80, decimal_odds_no=2.10)
    assert result.p_no_vig_yes == pytest.approx(0.53850, abs=1e-4)
    assert result.p_no_vig_no == pytest.approx(0.46150, abs=1e-4)
    assert result.overround == pytest.approx(1.03175, abs=1e-4)


def test_devig_none_when_yes_odds_missing():
    result = devig_bookmaker(decimal_odds_yes=None, decimal_odds_no=2.10)
    assert result.p_no_vig_yes is None
    assert result.p_no_vig_no is None
    assert result.overround is None


def test_devig_none_when_no_odds_missing():
    result = devig_bookmaker(decimal_odds_yes=1.80, decimal_odds_no=None)
    assert result.p_no_vig_yes is None
    assert result.p_no_vig_no is None


def test_devig_none_when_odds_zero():
    result = devig_bookmaker(decimal_odds_yes=0.0, decimal_odds_no=2.10)
    assert result.p_no_vig_yes is None


def test_devig_none_when_odds_negative():
    result = devig_bookmaker(decimal_odds_yes=1.80, decimal_odds_no=-1.5)
    assert result.p_no_vig_no is None
    assert result.p_no_vig_yes is None


def test_devig_never_mixes_across_bookmakers_by_construction():
    """Cada llamada opera sobre un único par de cuotas -- no existe ningún
    parámetro ni estado compartido entre bookmakers en este módulo."""
    result_a = devig_bookmaker(decimal_odds_yes=1.50, decimal_odds_no=3.00)
    result_b = devig_bookmaker(decimal_odds_yes=1.90, decimal_odds_no=1.95)
    assert result_a.overround != result_b.overround
