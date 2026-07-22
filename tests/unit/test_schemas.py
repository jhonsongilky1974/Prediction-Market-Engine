from src.models.schemas import EventStatus, NormalizedRecord, Sport


def test_normalized_record_defaults_are_null():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    assert r.status == EventStatus.UNKNOWN
    assert r.participant_a is None
    assert r.participant_b is None
    assert r.market.yes_bid is None
    assert r.market.market_price_executable is None
    assert r.tennis_variables is None


def test_model_output_stays_null_by_default():
    r = NormalizedRecord(sport=Sport.TENNIS, event_id="e2")
    mo = r.model_output
    assert mo.model_probability is None
    assert mo.confidence is None
    assert mo.uncertainty is None
    assert mo.edge is None
    assert mo.expected_value is None
    assert mo.signal is None


def test_data_quality_defaults():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e3")
    assert r.data_quality.missing_fields == []
    assert r.data_quality.needs_review is False
    assert r.data_quality.match_confidence is None


def test_extra_fields_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NormalizedRecord(sport=Sport.MLB, event_id="e4", not_a_real_field=True)
