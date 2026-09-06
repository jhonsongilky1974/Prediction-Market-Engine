"""Tests de Phase 6 -- Tramo 5B: `src.advisory.event_identity`. Identidad
canónica de evento y validación cruzada fail-closed contra `Position`
real -- un prefijo de ticker por sí solo nunca define el evento."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.advisory.event_identity import (
    EventIdentityMismatchError,
    derive_market_profile,
    validate_event_identity_consistency,
)
from src.models.schemas import Sport
from tests.unit.advisory_factories import make_event_identity
from tests.unit.positions_factories import make_position


def test_derive_market_profile_is_ticker_prefix():
    assert derive_market_profile("KXMLBGAME-26AUG03WSHPHI-WSH") == "KXMLBGAME"
    assert derive_market_profile("KXATPMATCH-26AUG01GEASHA-GEA") == "KXATPMATCH"


def test_valid_identity_constructs():
    identity = make_event_identity()
    assert identity.sport == Sport.MLB
    assert identity.market_profile == "KXMLBGAME"


def test_side_a_and_side_b_must_differ():
    with pytest.raises(ValidationError):
        make_event_identity(side_b=make_event_identity().side_a)


def test_tickers_must_differ():
    with pytest.raises(ValidationError):
        identity = make_event_identity()
        make_event_identity(kalshi_ticker_side_b=identity.kalshi_ticker_side_a)


def test_market_profile_must_match_sport():
    with pytest.raises(ValidationError):
        make_event_identity(sport=Sport.TENNIS)  # market_profile sigue siendo KXMLBGAME


def test_market_profile_must_be_known_series():
    with pytest.raises(ValidationError):
        make_event_identity(market_profile="KXUNKNOWNSERIES")


def test_ticker_prefix_must_match_declared_market_profile():
    with pytest.raises(ValidationError):
        make_event_identity(kalshi_ticker_side_a="KXATPMATCH-26AUG01GEASHA-GEA")


def test_scheduled_start_time_must_be_tz_aware():
    from datetime import datetime

    with pytest.raises(ValidationError):
        make_event_identity(scheduled_start_time=datetime(2026, 8, 15, 12, 0, 0))


# ---------------------------------------------------------------------
# Validación cruzada fail-closed contra Position real
# ---------------------------------------------------------------------


def test_consistency_passes_when_ticker_and_sport_match():
    identity = make_event_identity()
    position = make_position(kalshi_ticker=identity.kalshi_ticker_side_a, sport=identity.sport, side=identity.side_a)
    validate_event_identity_consistency(identity, [position])  # no debe lanzar


def test_consistency_fails_on_unrelated_ticker():
    identity = make_event_identity()
    position = make_position(kalshi_ticker="KXMLBGAME-DISTINTO-XXX", sport=identity.sport)
    with pytest.raises(EventIdentityMismatchError):
        validate_event_identity_consistency(identity, [position])


def test_consistency_fails_on_sport_contradiction():
    identity = make_event_identity()
    position = make_position(kalshi_ticker=identity.kalshi_ticker_side_a, sport=Sport.TENNIS)
    with pytest.raises(EventIdentityMismatchError):
        validate_event_identity_consistency(identity, [position])


def test_consistency_never_silently_drops_mismatched_position():
    """Una contradicción debe fallar explícito -- nunca descartar la
    Position en silencio y continuar con las demás."""
    identity = make_event_identity()
    good = make_position(position_id="good", kalshi_ticker=identity.kalshi_ticker_side_a, sport=identity.sport)
    bad = make_position(position_id="bad", kalshi_ticker="KXMLBGAME-OTRO-YYY", sport=identity.sport)
    with pytest.raises(EventIdentityMismatchError):
        validate_event_identity_consistency(identity, [good, bad])
