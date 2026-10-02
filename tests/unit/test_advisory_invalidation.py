"""Tests de Phase 6 -- Tramo 5B: `src.advisory.invalidation`. Stop
informativo (siempre clamped al dominio [1,99]) + invalidación
estructurada (nunca texto libre ejecutable)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.advisory.config import AdvisoryConfig
from src.advisory.enums import InvalidationConditionCode
from src.advisory.invalidation import build_invalidation_conditions, build_stop_advice
from src.models.schemas import Sport

CONFIG = AdvisoryConfig(max_adverse_move_cents=Decimal(10))


def test_stop_none_without_average_entry_price():
    assert build_stop_advice(average_entry_price_cents=None, config=CONFIG) is None


def test_stop_basic_calculation():
    stop = build_stop_advice(average_entry_price_cents=Decimal(50), config=CONFIG)
    assert stop.stop_price_cents == Decimal(40)
    assert stop.based_on_avg_entry_price_cents == Decimal(50)


@pytest.mark.parametrize("avg_entry", [Decimal(1), Decimal(5), Decimal(9)])
def test_stop_never_below_domain_minimum(avg_entry):
    stop = build_stop_advice(average_entry_price_cents=avg_entry, config=CONFIG)
    assert stop.stop_price_cents >= 1


@pytest.mark.parametrize("avg_entry", [Decimal(95), Decimal(99), Decimal(150)])
def test_stop_never_above_domain_maximum(avg_entry):
    stop = build_stop_advice(average_entry_price_cents=avg_entry, config=CONFIG)
    assert stop.stop_price_cents <= 99


@pytest.mark.parametrize("avg_entry", [Decimal(1), Decimal(10), Decimal(50), Decimal(99), Decimal(150)])
def test_stop_always_within_domain(avg_entry):
    stop = build_stop_advice(average_entry_price_cents=avg_entry, config=CONFIG)
    assert 1 <= stop.stop_price_cents <= 99


def test_invalidation_defaults_to_context_unavailable_without_evidence():
    conditions = build_invalidation_conditions(sport=Sport.MLB)
    assert len(conditions) == 1
    assert conditions[0].condition_code == InvalidationConditionCode.CONTEXT_UNAVAILABLE
    assert conditions[0].human_explanation.strip()


def test_invalidation_never_fabricates_condition_without_evidence_ref():
    conditions = build_invalidation_conditions(sport=Sport.TENNIS, evidence_refs=None)
    assert all(c.evidence_id is None for c in conditions)
    assert all(c.condition_code == InvalidationConditionCode.CONTEXT_UNAVAILABLE for c in conditions)
