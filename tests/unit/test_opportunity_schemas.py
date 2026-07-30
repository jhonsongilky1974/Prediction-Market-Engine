"""Tests de Opportunity y OpportunityEvaluation (Fase 3, Paso 3.0). Ver
CONTRACTS_FASE3.md §12-13 y PLAN_MASTER_FASE3.md Principio 10 / Hallazgo
de Contrato #3.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.opportunity.schemas import (
    Opportunity,
    compute_opportunity_id,
    compute_selection_id,
)
from src.signals.signal_schema import Side
from tests.unit.fase3_factories import (
    NOW,
    assert_round_trip,
    make_opportunity,
    make_opportunity_evaluation,
)

# ---------------------------------------------------------------------
# compute_selection_id / compute_opportunity_id -- determinismo
# ---------------------------------------------------------------------


def test_compute_selection_id_is_deterministic():
    assert compute_selection_id("KXMLBGAME-1", Side.YES) == compute_selection_id(
        "KXMLBGAME-1", Side.YES
    )
    assert compute_selection_id("KXMLBGAME-1", Side.YES) != compute_selection_id(
        "KXMLBGAME-1", Side.NO
    )


def test_compute_opportunity_id_is_deterministic():
    sid = compute_selection_id("KXMLBGAME-1", Side.YES)
    assert compute_opportunity_id("evt-1", sid) == compute_opportunity_id("evt-1", sid)
    assert compute_opportunity_id("evt-1", sid) != compute_opportunity_id("evt-2", sid)


# ---------------------------------------------------------------------
# Opportunity
# ---------------------------------------------------------------------


def test_opportunity_valid():
    opp = make_opportunity()
    assert opp.state_version == 1


def test_opportunity_selection_id_mismatch_raises():
    with pytest.raises(ValidationError, match="selection_id"):
        make_opportunity(selection_id="not-the-real-selection-id")


def test_opportunity_opportunity_id_mismatch_raises():
    with pytest.raises(ValidationError, match="opportunity_id"):
        make_opportunity(opportunity_id="not-the-real-id")


def test_opportunity_without_market_id_does_not_fabricate_selection_id():
    """market_id ausente (matching de Fase 1 no resuelto todavía): el
    contrato no fabrica un market_id, exige que el llamador ya haya
    provisto selection_id/opportunity_id consistentes entre sí."""
    opp = make_opportunity(
        market_id=None,
        selection_id="evt-1:YES",
        opportunity_id=compute_opportunity_id("evt-1", "evt-1:YES"),
    )
    assert opp.market_id is None


def test_opportunity_state_version_below_one_raises():
    with pytest.raises(ValidationError, match="state_version"):
        make_opportunity(state_version=0)


def test_opportunity_last_evaluated_before_first_seen_raises():
    with pytest.raises(ValidationError, match="last_evaluated_at"):
        make_opportunity(last_evaluated_at=NOW - timedelta(hours=1), first_seen_at=NOW)


def test_opportunity_naive_timestamp_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_opportunity(first_seen_at=datetime(2026, 7, 30, 12, 0, 0))


def test_opportunity_extra_field_is_forbidden():
    sid = compute_selection_id("KXMLBGAME-1", Side.YES)
    with pytest.raises(ValidationError):
        Opportunity(
            opportunity_id=compute_opportunity_id("evt-1", sid),
            event_id="evt-1",
            market_id="KXMLBGAME-1",
            selection_id=sid,
            side=Side.YES,
            sport="MLB",
            first_seen_at=NOW,
            last_evaluated_at=NOW,
            state_version=1,
            unexpected_field="x",
        )


def test_opportunity_round_trip():
    assert_round_trip(make_opportunity())


# ---------------------------------------------------------------------
# OpportunityEvaluation -- inmutabilidad + composición
# ---------------------------------------------------------------------


def test_opportunity_evaluation_valid():
    evaluation = make_opportunity_evaluation()
    assert evaluation.state_version == 1
    assert evaluation.signal_inputs.event_id == "evt-1"


def test_opportunity_evaluation_is_frozen():
    evaluation = make_opportunity_evaluation()
    with pytest.raises(ValidationError):
        evaluation.state_version = 2  # type: ignore[misc]


def test_opportunity_evaluation_state_version_below_one_raises():
    with pytest.raises(ValidationError, match="state_version"):
        make_opportunity_evaluation(state_version=0)


def test_opportunity_evaluation_naive_decision_timestamp_raises():
    with pytest.raises(ValidationError, match="tz-aware"):
        make_opportunity_evaluation(decision_timestamp=datetime(2026, 7, 30, 12, 0, 0))


def test_opportunity_evaluation_payoff_estimate_can_be_none():
    evaluation = make_opportunity_evaluation(payoff_estimate=None)
    assert evaluation.payoff_estimate is None


def test_opportunity_evaluation_round_trip():
    """Cubre explícitamente la serialización del SignalInputs embebido
    (dataclass de Fase 2, no un BaseModel de pydantic) dentro de un
    contrato pydantic de Fase 3 -- el caso de composición más delicado
    de este paso."""
    assert_round_trip(make_opportunity_evaluation())
