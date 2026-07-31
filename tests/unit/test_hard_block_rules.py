"""Tests de las 7 reglas HARD_BLOCK_PASS (Fase 3, Paso 3.4.2). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.2, y POLICY_ENGINE_SPEC.md §2.1 -- un
test por regla que la dispara, uno por regla que no se dispara con datos
limpios, más el test de fuga temporal de known_result.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.schemas import (
    DataQuality,
    EventStatus,
    MarketData,
    MatchMethod,
    NormalizedRecord,
    Sport,
)
from src.policy.hard_rules import (
    HARD_BLOCK_RULE_IDS,
    check_corrupted_critical_data,
    check_incompatible_contract,
    check_invalid_event,
    check_invalid_or_closed_market,
    check_known_result,
    check_non_recoverable_inconsistency,
    check_unsafe_matching,
    evaluate_hard_block_rules,
)
from src.policy.schemas import HardRuleCategory
from src.storage.history_repository import HistoryRepository

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        **overrides,
    )


# ---------------------------------------------------------------------
# Catálogo cerrado
# ---------------------------------------------------------------------


def test_catalog_has_exactly_seven_rule_ids():
    assert len(HARD_BLOCK_RULE_IDS) == 7
    assert len(set(HARD_BLOCK_RULE_IDS)) == 7
    assert set(HARD_BLOCK_RULE_IDS) == {
        "unsafe_matching",
        "invalid_event",
        "invalid_or_closed_market",
        "incompatible_contract",
        "corrupted_critical_data",
        "known_result",
        "non_recoverable_inconsistency",
    }


def test_all_rule_results_carry_block_category(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    record = _record()
    results = evaluate_hard_block_rules(record, NOW, history_repository, now=NOW)
    assert len(results) == 6  # non_recoverable_inconsistency queda fuera del evaluador
    for result in results:
        assert result.category == HardRuleCategory.BLOCK
    assert {r.rule_id for r in results} == set(HARD_BLOCK_RULE_IDS) - {"non_recoverable_inconsistency"}


# ---------------------------------------------------------------------
# unsafe_matching
# ---------------------------------------------------------------------


def test_unsafe_matching_triggers_on_needs_review_method():
    record = _record(data_quality=DataQuality(match_method=MatchMethod.NEEDS_REVIEW))
    result = check_unsafe_matching(record, NOW)
    assert result.triggered is True


def test_unsafe_matching_triggers_on_no_match_method():
    record = _record(data_quality=DataQuality(match_method=MatchMethod.NO_MATCH))
    result = check_unsafe_matching(record, NOW)
    assert result.triggered is True


def test_unsafe_matching_triggers_on_low_confidence():
    record = _record(data_quality=DataQuality(match_confidence=0.50))
    result = check_unsafe_matching(record, NOW)
    assert result.triggered is True


def test_unsafe_matching_does_not_trigger_with_clean_data():
    record = _record(
        data_quality=DataQuality(match_method=MatchMethod.SOURCE_ID, match_confidence=0.95)
    )
    result = check_unsafe_matching(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# invalid_event
# ---------------------------------------------------------------------


def test_invalid_event_triggers_on_cancelled():
    record = _record(status=EventStatus.CANCELLED)
    result = check_invalid_event(record, NOW)
    assert result.triggered is True


def test_invalid_event_does_not_trigger_on_scheduled():
    record = _record(status=EventStatus.SCHEDULED)
    result = check_invalid_event(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# invalid_or_closed_market
# ---------------------------------------------------------------------


def test_invalid_or_closed_market_triggers_when_both_prices_missing():
    record = _record(market=MarketData())
    result = check_invalid_or_closed_market(record, NOW)
    assert result.triggered is True


def test_invalid_or_closed_market_triggers_when_already_settled():
    record = _record(market=MarketData(yes_ask=0.55), actual_settlement_time=NOW)
    result = check_invalid_or_closed_market(record, NOW)
    assert result.triggered is True


def test_invalid_or_closed_market_does_not_trigger_with_clean_data():
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    result = check_invalid_or_closed_market(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# incompatible_contract -- nunca dispara contra el esquema actual
# ---------------------------------------------------------------------


def test_incompatible_contract_never_triggers_today():
    result = check_incompatible_contract(_record(), NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# corrupted_critical_data
# ---------------------------------------------------------------------


def test_corrupted_critical_data_triggers_on_core_field_error():
    record = _record(data_quality=DataQuality(validation_errors=["participant_a vacío"]))
    result = check_corrupted_critical_data(record, NOW)
    assert result.triggered is True


def test_corrupted_critical_data_does_not_trigger_on_non_core_error():
    record = _record(data_quality=DataQuality(validation_errors=["mlb.injuries: dato inusual"]))
    result = check_corrupted_critical_data(record, NOW)
    assert result.triggered is False


def test_corrupted_critical_data_does_not_trigger_with_no_errors():
    record = _record(data_quality=DataQuality(validation_errors=[]))
    result = check_corrupted_critical_data(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# known_result + fuga temporal
# ---------------------------------------------------------------------


def test_known_result_does_not_trigger_with_no_results(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    result = check_known_result(_record(), NOW, history_repository, NOW)
    assert result.triggered is False


def test_known_result_triggers_when_recorded_before_cutoff(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    record = _record()
    history_repository.save_event_result(
        event_id=record.event_id,
        sport="MLB",
        result="participant_a",
        source="mlb_stats_api",
        recorded_at=NOW - timedelta(hours=1),
    )
    result = check_known_result(record, NOW, history_repository, NOW)
    assert result.triggered is True


def test_known_result_does_not_trigger_when_recorded_after_cutoff(tmp_path):
    """No es una fuga: un resultado registrado DESPUÉS del cutoff no era
    conocimiento público en ese instante, así que se ignora
    correctamente -- si esta regla lo disparara, SÍ sería la fuga."""
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    record = _record()
    history_repository.save_event_result(
        event_id=record.event_id,
        sport="MLB",
        result="participant_a",
        source="mlb_stats_api",
        recorded_at=NOW + timedelta(hours=1),
    )
    result = check_known_result(record, NOW, history_repository, NOW)
    assert result.triggered is False


def test_known_result_scoped_to_event_id(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    record = _record()
    history_repository.save_event_result(
        event_id="mlb_OTHER_EVENT",
        sport="MLB",
        result="participant_a",
        source="mlb_stats_api",
        recorded_at=NOW - timedelta(hours=1),
    )
    result = check_known_result(record, NOW, history_repository, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# non_recoverable_inconsistency
# ---------------------------------------------------------------------


def test_non_recoverable_inconsistency_triggers_with_exception():
    result = check_non_recoverable_inconsistency(ValueError("boom"), NOW)
    assert result.triggered is True
    assert "boom" in result.detail


def test_non_recoverable_inconsistency_does_not_trigger_without_exception():
    result = check_non_recoverable_inconsistency(None, NOW)
    assert result.triggered is False
    assert result.detail is None


# ---------------------------------------------------------------------
# Pureza y validación temporal del evaluador
# ---------------------------------------------------------------------


def test_evaluator_same_input_produces_same_output(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    record = _record(market=MarketData(yes_ask=0.55))
    results_a = evaluate_hard_block_rules(record, NOW, history_repository, now=NOW)
    results_b = evaluate_hard_block_rules(record, NOW, history_repository, now=NOW)
    assert results_a == results_b


def test_evaluator_naive_now_raises(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    with pytest.raises(ValueError, match="tz-aware"):
        evaluate_hard_block_rules(
            _record(), NOW, history_repository, now=datetime(2026, 7, 30, 12, 0, 0)
        )


def test_evaluator_naive_data_cutoff_raises(tmp_path):
    history_repository = HistoryRepository(db_path=tmp_path / "history.db")
    with pytest.raises(ValueError, match="tz-aware"):
        evaluate_hard_block_rules(
            _record(), datetime(2026, 7, 30, 12, 0, 0), history_repository, now=NOW
        )
