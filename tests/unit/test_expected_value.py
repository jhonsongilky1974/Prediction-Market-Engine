"""Tests de `src/signals/expected_value.py` (Paso 8)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.signals.expected_value import (
    compute_ev_no_bruto,
    compute_ev_no_neto,
    compute_ev_yes_bruto,
    compute_ev_yes_neto,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        **overrides,
    )


def _trained_output(p_model_yes: float) -> PModelOutput:
    return PModelOutput(
        p_model_yes=p_model_yes,
        model_version="test_v1",
        model_status=ModelStatus.TRAINED,
        feature_set_version="test",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )


def _not_trained_output() -> PModelOutput:
    return PModelOutput(
        p_model_yes=None,
        model_version=None,
        model_status=ModelStatus.MODEL_NOT_TRAINED,
        feature_set_version="test",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )


def test_ev_yes_bruto_matches_formula_exactly():
    record = _record(market=MarketData(yes_ask=0.55))
    output = _trained_output(0.60)

    expected = 0.60 * (1 - 0.55) - (1 - 0.60) * 0.55
    assert compute_ev_yes_bruto(output, record) == pytest.approx(expected)


def test_ev_no_bruto_matches_formula_exactly_and_independent_of_yes():
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _trained_output(0.60)

    p_model_no = 1 - 0.60
    expected = p_model_no * (1 - 0.42) - (1 - p_model_no) * 0.42
    assert compute_ev_no_bruto(output, record) == pytest.approx(expected)


def test_ev_bruto_none_when_model_not_trained():
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _not_trained_output()

    assert compute_ev_yes_bruto(output, record) is None
    assert compute_ev_no_bruto(output, record) is None


def test_ev_bruto_none_when_needs_review():
    record = _record(
        market=MarketData(yes_ask=0.55, no_ask=0.42),
        data_quality=DataQuality(needs_review=True),
    )
    output = _trained_output(0.60)

    assert compute_ev_yes_bruto(output, record) is None
    assert compute_ev_no_bruto(output, record) is None


def test_ev_neto_is_none_while_exchange_fee_is_none():
    """exchange_fee es None en la práctica siempre hoy (Kalshi no lo
    expone) -> EV_neto debe ser None, sin excepción, sin fabricar una
    fórmula de fee no especificada por el plan."""
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42, exchange_fee=None))
    output = _trained_output(0.60)
    ev_yes_bruto = compute_ev_yes_bruto(output, record)
    ev_no_bruto = compute_ev_no_bruto(output, record)

    assert compute_ev_yes_neto(output, record, ev_yes_bruto) is None
    assert compute_ev_no_neto(output, record, ev_no_bruto) is None


def test_ev_neto_none_when_bruto_is_none_even_if_fee_present():
    record = _record(market=MarketData(yes_ask=None, exchange_fee=0.01))
    output = _trained_output(0.60)

    assert compute_ev_yes_neto(output, record, ev_yes_bruto=None) is None


def test_ev_is_deterministic_same_inputs_same_output():
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _trained_output(0.60)

    results = {compute_ev_yes_bruto(output, record) for _ in range(50)}
    assert len(results) == 1
