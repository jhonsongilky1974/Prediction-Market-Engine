"""Tests de EvidenceItem (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md §6."""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.evidence.schemas import EvidenceDirection, EvidenceItem
from tests.unit.fase3_factories import NOW, assert_round_trip, make_evidence_item


def test_construction_with_valid_values_is_valid():
    item = make_evidence_item()
    assert item.direction == EvidenceDirection.FOR


def test_empty_fact_raises():
    with pytest.raises(ValidationError, match="fact"):
        make_evidence_item(fact="   ")


def test_empty_source_field_raises():
    with pytest.raises(ValidationError, match="source_field"):
        make_evidence_item(source_field="")


def test_strength_out_of_range_raises():
    with pytest.raises(ValidationError, match=r"fuera de \[0,1\]"):
        make_evidence_item(strength=1.5)


@pytest.mark.parametrize("field_name", ["source_timestamp", "generated_at"])
def test_naive_timestamp_raises(field_name):
    with pytest.raises(ValidationError, match="tz-aware"):
        make_evidence_item(**{field_name: datetime(2026, 7, 30, 12, 0, 0)})


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        EvidenceItem(
            opportunity_id="opp-1",
            fact="x",
            direction=EvidenceDirection.NEUTRAL,
            source_field="y",
            generated_at=NOW,
            unexpected_field="z",
        )


def test_round_trip_serialization():
    assert_round_trip(make_evidence_item())
    assert_round_trip(make_evidence_item(direction=EvidenceDirection.AGAINST, strength=None))
