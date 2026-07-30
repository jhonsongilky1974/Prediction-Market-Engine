"""Tests de PayoffEstimate (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§3 -- invariantes: COMPUTED exige ev_to_settlement + cost_evidence_refs;
UNKNOWN exige ambos EV en None; timestamps tz-aware.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.payoff.schemas import NetEvStatus, PayoffEstimate
from tests.unit.fase3_factories import NOW, assert_round_trip, make_payoff_estimate


def test_construction_with_unknown_status_is_valid():
    payoff = make_payoff_estimate()
    assert payoff.net_ev_status == NetEvStatus.UNKNOWN
    assert payoff.ev_to_settlement is None


def test_computed_without_ev_to_settlement_raises():
    with pytest.raises(ValidationError, match="ev_to_settlement"):
        make_payoff_estimate(
            net_ev_status=NetEvStatus.COMPUTED,
            ev_to_settlement=None,
            cost_evidence_refs=["market.exchange_fee"],
        )


def test_computed_without_cost_evidence_refs_raises():
    with pytest.raises(ValidationError, match="cost_evidence_refs"):
        make_payoff_estimate(
            net_ev_status=NetEvStatus.COMPUTED,
            ev_to_settlement=0.05,
            cost_evidence_refs=[],
        )


def test_computed_with_full_evidence_is_valid():
    payoff = make_payoff_estimate(
        net_ev_status=NetEvStatus.COMPUTED,
        ev_to_settlement=0.05,
        cost_evidence_refs=["market.exchange_fee"],
    )
    assert payoff.net_ev_status == NetEvStatus.COMPUTED


def test_unknown_with_ev_populated_raises():
    with pytest.raises(ValidationError, match="net_ev_status=UNKNOWN"):
        make_payoff_estimate(net_ev_status=NetEvStatus.UNKNOWN, ev_to_settlement=0.05)


def test_naive_computed_at_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_payoff_estimate(computed_at=datetime(2026, 7, 30, 12, 0, 0))


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        PayoffEstimate(
            opportunity_id="opp-1",
            side="YES",
            platform="KALSHI",
            net_ev_status=NetEvStatus.UNKNOWN,
            computed_at=NOW,
            unexpected_field="x",
        )


def test_round_trip_serialization():
    assert_round_trip(make_payoff_estimate())
    assert_round_trip(
        make_payoff_estimate(
            net_ev_status=NetEvStatus.COMPUTED,
            ev_to_settlement=0.05,
            cost_evidence_refs=["market.exchange_fee"],
        )
    )
