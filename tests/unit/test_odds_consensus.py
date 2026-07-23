"""Tests del Paso 4 -- consenso no-vig en dos pasos + gate de matching
(src/pricing/odds_consensus.py).

`bookmaker_odds` se construye siempre ya etiquetado YES/NO en estos
tests (fixtures sintéticos) -- por decisión de arquitectura (Opción A),
este módulo nunca deriva esa etiqueta desde nombres de participante
reales, así que no hay forma de testear esa extracción aquí (queda
delegada a una capa de integración futura, ver docstring de
`odds_consensus.py`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.schemas import NormalizedRecord, SourceStatus, Sport
from src.pricing.odds_consensus import LabeledBookmakerOdds, compute_consensus_no_vig

NOW = datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    defaults = dict(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
    )
    defaults.update(overrides)
    return NormalizedRecord(**defaults)


def _bm(name, decimal_odds_yes, decimal_odds_no, last_update=None):
    return LabeledBookmakerOdds(
        bookmaker=name,
        decimal_odds_yes=decimal_odds_yes,
        decimal_odds_no=decimal_odds_no,
        last_update=last_update,
    )


def _matching_call(bookmaker_odds, odds_api_key_configured=True, record=None):
    return compute_consensus_no_vig(
        odds_api_key_configured=odds_api_key_configured,
        source_participant_a="Minnesota Twins",
        source_participant_b="Cleveland Guardians",
        source_start_time=None,
        target_record=record or _record(),
        bookmaker_odds=bookmaker_odds,
        as_of=NOW,
    )


# =========================================================================
# Tests obligatorios de §13 (Paso 4)
# =========================================================================

def test_odds_api_not_configured_degrades_clean_to_none():
    result = _matching_call(bookmaker_odds=[], odds_api_key_configured=False)
    assert result.p_consensus_no_vig_yes is None
    assert result.p_consensus_no_vig_no is None
    assert result.bookmaker_count == 0
    assert result.source_quality == SourceStatus.NOT_CONFIGURED
    assert result.event_match_confidence is None


def test_median_aggregation_robust_to_outlier():
    bookmakers = [
        _bm("book_a", 1.80, 2.10),
        _bm("book_b", 1.83, 2.05),
        _bm("book_c", 5.00, 1.20),  # outlier claramente desviado
    ]
    result = _matching_call(bookmakers)
    assert result.bookmaker_count == 3
    # Mediana de [0.5385 (a), 0.5283 (b), 0.1935 (c, outlier)] = 0.5283 (book_b) --
    # no se ve arrastrada hacia el outlier como lo haría un promedio (~0.420).
    assert result.p_consensus_no_vig_yes == pytest.approx(0.5283, abs=0.001)
    average_would_be = (0.5385 + 0.5283 + 0.1935) / 3
    assert abs(result.p_consensus_no_vig_yes - average_would_be) > 0.05


def test_event_matching_needs_review_excludes_all_bookmakers_named_regression():
    mismatched_record = _record(participant_a="Completely Different Team", participant_b="Another Unrelated Club")
    bookmakers = [_bm("book_a", 1.80, 2.10), _bm("book_b", 1.83, 2.05)]
    result = _matching_call(bookmakers, record=mismatched_record)
    assert result.bookmaker_count == 0
    assert result.p_consensus_no_vig_yes is None
    assert result.p_consensus_no_vig_no is None
    assert set(result.exclusion_reasons.keys()) == {"book_a", "book_b"}
    assert all("event_match_failed" in reason for reason in result.exclusion_reasons.values())
    assert result.source_quality == SourceStatus.FAILED


# =========================================================================
# Casos adversariales adicionales
# =========================================================================

def test_individual_bookmaker_excluded_for_invalid_odds_others_still_included():
    bookmakers = [
        _bm("book_a", 1.80, 2.10),
        _bm("book_bad", None, 2.00),
        _bm("book_c", 1.83, 2.05),
    ]
    result = _matching_call(bookmakers)
    assert result.bookmaker_count == 2
    assert result.exclusion_reasons == {"book_bad": "invalid_or_missing_odds"}
    assert result.p_consensus_no_vig_yes is not None


def test_source_quality_ok_at_three_or_more():
    bookmakers = [_bm(f"book_{i}", 1.80, 2.10) for i in range(3)]
    result = _matching_call(bookmakers)
    assert result.source_quality == SourceStatus.OK


def test_source_quality_partial_at_one_or_two():
    bookmakers = [_bm("book_a", 1.80, 2.10)]
    result = _matching_call(bookmakers)
    assert result.source_quality == SourceStatus.PARTIAL


def test_source_quality_failed_at_zero_when_configured():
    bookmakers = [_bm("book_bad", None, None)]
    result = _matching_call(bookmakers)
    assert result.bookmaker_count == 0
    assert result.source_quality == SourceStatus.FAILED


def test_dispersion_none_with_fewer_than_two_bookmakers():
    result = _matching_call([_bm("book_a", 1.80, 2.10)])
    assert result.dispersion is None


def test_dispersion_computed_with_two_or_more_bookmakers():
    bookmakers = [_bm("book_a", 1.80, 2.10), _bm("book_b", 1.90, 2.00)]
    result = _matching_call(bookmakers)
    assert result.dispersion is not None
    assert result.dispersion >= 0.0


def test_per_bookmaker_timestamps_includes_excluded_bookmakers_too():
    ts = NOW - timedelta(minutes=5)
    bookmakers = [_bm("book_a", 1.80, 2.10, ts), _bm("book_bad", None, None, ts)]
    result = _matching_call(bookmakers)
    assert set(result.per_bookmaker_timestamps.keys()) == {"book_a", "book_bad"}


def test_freshness_uses_oldest_included_timestamp_only():
    older = NOW - timedelta(minutes=30)
    newer = NOW - timedelta(minutes=5)
    bookmakers = [
        _bm("book_a", 1.80, 2.10, newer),
        _bm("book_bad", None, None, older),  # excluido: no debe afectar freshness
    ]
    result = _matching_call(bookmakers)
    assert result.freshness == pytest.approx(300.0)  # 5 minutos en segundos


def test_freshness_none_when_no_included_bookmaker_has_timestamp():
    bookmakers = [_bm("book_a", 1.80, 2.10, last_update=None)]
    result = _matching_call(bookmakers)
    assert result.freshness is None


def test_as_of_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        compute_consensus_no_vig(
            odds_api_key_configured=True,
            source_participant_a="Minnesota Twins",
            source_participant_b="Cleveland Guardians",
            source_start_time=None,
            target_record=_record(),
            bookmaker_odds=[],
            as_of=datetime(2026, 7, 23, 18, 0),  # naive
        )


def test_event_match_confidence_populated_even_when_no_bookmakers_pass():
    result = _matching_call([])
    assert result.event_match_confidence is not None


def test_does_not_mutate_input_bookmaker_list_or_record():
    record = _record()
    bookmakers = [_bm("book_a", 1.80, 2.10)]
    _matching_call(bookmakers, record=record)
    assert record.participant_a == "Minnesota Twins"
    assert bookmakers[0].decimal_odds_yes == 1.80


def test_yes_and_no_never_cross_contaminate_in_aggregation():
    bookmakers = [_bm("book_a", 1.50, 3.00), _bm("book_b", 1.55, 2.90)]
    result = _matching_call(bookmakers)
    assert result.p_consensus_no_vig_yes != result.p_consensus_no_vig_no
    assert result.p_consensus_no_vig_yes > 0.5
    assert result.p_consensus_no_vig_no < 0.5
