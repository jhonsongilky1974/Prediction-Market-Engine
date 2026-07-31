"""Tests de las 6 reglas HARD_HOLD_WATCH (Fase 3, Paso 3.4.3). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.3, y POLICY_ENGINE_SPEC.md §2.2 -- un
test por regla, más el test explícito de unresolved_side_mapping como
constante (DECISIÓN PENDIENTE D-2).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.schemas import DataQuality, MarketData, ModelInputs, NormalizedRecord, Sport
from src.policy.hard_rules import (
    HARD_HOLD_RULE_IDS,
    check_pending_lineup,
    check_recoverable_missing_information,
    check_temporarily_insufficient_liquidity,
    check_temporarily_stale_data,
    check_unconfirmed_pitcher,
    check_unresolved_side_mapping,
    evaluate_hard_hold_rules,
)
from src.policy.schemas import HardRuleCategory
from tests.unit.fase3_factories import make_analysis_health

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    base = dict(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
    )
    base.update(overrides)
    return NormalizedRecord(**base)


# ---------------------------------------------------------------------
# Catálogo cerrado
# ---------------------------------------------------------------------


def test_catalog_has_exactly_six_rule_ids():
    assert len(HARD_HOLD_RULE_IDS) == 6
    assert len(set(HARD_HOLD_RULE_IDS)) == 6
    assert set(HARD_HOLD_RULE_IDS) == {
        "pending_lineup",
        "unconfirmed_pitcher",
        "temporarily_stale_data",
        "temporarily_insufficient_liquidity",
        "recoverable_missing_information",
        "unresolved_side_mapping",
    }


def test_evaluator_returns_six_results_all_hold_category():
    record = _record()
    results = evaluate_hard_hold_rules(record, make_analysis_health(), now=NOW)
    assert len(results) == 6
    for result in results:
        assert result.category == HardRuleCategory.HOLD
    assert {r.rule_id for r in results} == set(HARD_HOLD_RULE_IDS)


# ---------------------------------------------------------------------
# pending_lineup
# ---------------------------------------------------------------------


def test_pending_lineup_triggers_when_missing_and_within_window():
    record = _record(
        model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=NOW + timedelta(hours=1)
    )
    result = check_pending_lineup(record, NOW)
    assert result.triggered is True


def test_pending_lineup_does_not_trigger_when_present():
    record = _record(
        model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}),
        start_time=NOW + timedelta(hours=1),
    )
    result = check_pending_lineup(record, NOW)
    assert result.triggered is False


def test_pending_lineup_does_not_trigger_when_far_in_future():
    record = _record(
        model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=NOW + timedelta(hours=10)
    )
    result = check_pending_lineup(record, NOW)
    assert result.triggered is False


def test_pending_lineup_does_not_trigger_without_start_time():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=None)
    result = check_pending_lineup(record, NOW)
    assert result.triggered is False


def test_pending_lineup_respects_custom_threshold():
    record = _record(
        model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=NOW + timedelta(hours=5)
    )
    assert check_pending_lineup(record, NOW, hours_threshold=3.0).triggered is False
    assert check_pending_lineup(record, NOW, hours_threshold=6.0).triggered is True


# ---------------------------------------------------------------------
# unconfirmed_pitcher
# ---------------------------------------------------------------------


def test_unconfirmed_pitcher_triggers_for_mlb_when_missing():
    record = _record(sport=Sport.MLB, model_inputs=ModelInputs(lineup_or_pitcher=None))
    result = check_unconfirmed_pitcher(record, NOW)
    assert result.triggered is True


def test_unconfirmed_pitcher_does_not_trigger_for_mlb_when_present():
    record = _record(sport=Sport.MLB, model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane"}))
    result = check_unconfirmed_pitcher(record, NOW)
    assert result.triggered is False


def test_unconfirmed_pitcher_does_not_trigger_for_tennis():
    record = _record(sport=Sport.TENNIS, model_inputs=ModelInputs(lineup_or_pitcher=None))
    result = check_unconfirmed_pitcher(record, NOW)
    assert result.triggered is False


def test_unconfirmed_pitcher_not_time_gated():
    """A diferencia de pending_lineup, dispara sin importar la
    proximidad del evento (o incluso sin start_time)."""
    record = _record(sport=Sport.MLB, model_inputs=ModelInputs(lineup_or_pitcher=None), start_time=None)
    result = check_unconfirmed_pitcher(record, NOW)
    assert result.triggered is True


# ---------------------------------------------------------------------
# temporarily_stale_data
# ---------------------------------------------------------------------


def test_temporarily_stale_data_triggers_above_threshold():
    analysis_health = make_analysis_health(staleness_seconds=4000.0)
    result = check_temporarily_stale_data(analysis_health, NOW)
    assert result.triggered is True


def test_temporarily_stale_data_does_not_trigger_below_threshold():
    analysis_health = make_analysis_health(staleness_seconds=100.0)
    result = check_temporarily_stale_data(analysis_health, NOW)
    assert result.triggered is False


def test_temporarily_stale_data_does_not_trigger_when_none():
    analysis_health = make_analysis_health(staleness_seconds=None)
    result = check_temporarily_stale_data(analysis_health, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# temporarily_insufficient_liquidity
# ---------------------------------------------------------------------


def test_temporarily_insufficient_liquidity_triggers_below_minimum():
    record = _record(market=MarketData(volume=50.0))
    result = check_temporarily_insufficient_liquidity(record, NOW)
    assert result.triggered is True


def test_temporarily_insufficient_liquidity_does_not_trigger_above_minimum():
    record = _record(market=MarketData(volume=5000.0))
    result = check_temporarily_insufficient_liquidity(record, NOW)
    assert result.triggered is False


def test_temporarily_insufficient_liquidity_falls_back_to_open_interest():
    record = _record(market=MarketData(volume=None, open_interest=50.0))
    result = check_temporarily_insufficient_liquidity(record, NOW)
    assert result.triggered is True


def test_temporarily_insufficient_liquidity_does_not_trigger_when_no_data():
    record = _record(market=MarketData(volume=None, open_interest=None))
    result = check_temporarily_insufficient_liquidity(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# recoverable_missing_information
# ---------------------------------------------------------------------


def test_recoverable_missing_information_triggers_on_non_core_field():
    record = _record(data_quality=DataQuality(missing_fields=["mlb.injuries"]))
    result = check_recoverable_missing_information(record, NOW)
    assert result.triggered is True


def test_recoverable_missing_information_does_not_trigger_on_core_field_only():
    record = _record(data_quality=DataQuality(missing_fields=["participant_a"]))
    result = check_recoverable_missing_information(record, NOW)
    assert result.triggered is False


def test_recoverable_missing_information_does_not_trigger_when_empty():
    record = _record(data_quality=DataQuality(missing_fields=[]))
    result = check_recoverable_missing_information(record, NOW)
    assert result.triggered is False


# ---------------------------------------------------------------------
# unresolved_side_mapping -- SIEMPRE triggered=True (D-2 sin resolver)
# ---------------------------------------------------------------------


def test_unresolved_side_mapping_always_triggered():
    """DECISIÓN PENDIENTE D-2 (PLAN_MASTER_FASE3.md §5 Hallazgo #2, §8):
    el mapeo participante<->YES de un contrato Kalshi concreto sigue sin
    resolver. Mientras eso no cambie mediante una decisión explícita del
    usuario, esta regla debe disparar SIEMPRE -- si este test empieza a
    fallar porque alguien "corrigió" la función para que deje de
    disparar sin pasar por esa decisión, eso es una regresión que debe
    bloquear el paso, no un mejor comportamiento."""
    result = check_unresolved_side_mapping(NOW)
    assert result.triggered is True
    assert result.category == HardRuleCategory.HOLD


@pytest.mark.parametrize(
    "now",
    [NOW, NOW + timedelta(days=365), NOW - timedelta(days=365)],
)
def test_unresolved_side_mapping_triggered_regardless_of_time(now):
    assert check_unresolved_side_mapping(now).triggered is True


# ---------------------------------------------------------------------
# Pureza y validación de now
# ---------------------------------------------------------------------


def test_evaluator_same_input_produces_same_output():
    record = _record(market=MarketData(volume=5000.0))
    analysis_health = make_analysis_health()
    results_a = evaluate_hard_hold_rules(record, analysis_health, now=NOW)
    results_b = evaluate_hard_hold_rules(record, analysis_health, now=NOW)
    assert results_a == results_b


def test_evaluator_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        evaluate_hard_hold_rules(
            _record(), make_analysis_health(), now=datetime(2026, 7, 30, 12, 0, 0)
        )
