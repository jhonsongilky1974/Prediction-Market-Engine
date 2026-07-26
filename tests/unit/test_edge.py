"""Tests de `src/signals/edge.py` (Paso 8). Reutiliza los 6 escenarios
obligatorios de PLAN_PHASE2.md §7 -- ver `tests/unit/test_market_pricing.py`
para la parte de `P_market_YES`/`P_market_NO`; aquí se prueban las
aserciones exactas de `EDGE_YES`/`EDGE_NO` sobre esos mismos escenarios,
tal como quedó reservado explícitamente para el Paso 8.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.signals.edge import compute_edge_no, compute_edge_yes

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


# =========================================================================
# Los 6 escenarios obligatorios de §7 -- aserciones exactas de EDGE_YES/EDGE_NO
# =========================================================================


def test_scenario_1_edge_yes_exact():
    """P_model_YES=0.60, yes_ask=0.55 -> EDGE_YES=0.05 exacto."""
    record = _record(market=MarketData(yes_ask=0.55))
    output = _trained_output(0.60)
    assert compute_edge_yes(output, record) == pytest.approx(0.05)


def test_scenario_2_edge_no_exact_and_never_crosses_sides():
    """Mismo registro, no_ask=0.42 -> P_model_NO=0.40, EDGE_NO=-0.02
    exacto -- y explícitamente EDGE_NO != P_model_YES - no_ask."""
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _trained_output(0.60)

    edge_no = compute_edge_no(output, record)

    assert edge_no == pytest.approx(-0.02)
    wrong_crossed_value = 0.60 - 0.42  # P_model_YES - no_ask, el error que NUNCA debe ocurrir
    assert edge_no != pytest.approx(wrong_crossed_value)


def test_scenario_3_yes_ask_plus_no_ask_over_one_both_computed_independently():
    """yes_ask+no_ask>1 -- ambos EDGE se calculan sin error y sin
    reescalar los precios."""
    record = _record(market=MarketData(yes_ask=0.60, no_ask=0.55))
    output = _trained_output(0.70)

    edge_yes = compute_edge_yes(output, record)
    edge_no = compute_edge_no(output, record)

    assert edge_yes == pytest.approx(0.70 - 0.60)
    assert edge_no == pytest.approx((1 - 0.70) - 0.55)


def test_scenario_4_needs_review_blocks_both_edges():
    """NEEDS_REVIEW=True -> EDGE_YES=None, EDGE_NO=None -- ningún dato de
    mercado se usa, aunque P_model_YES exista."""
    record = _record(
        market=MarketData(yes_ask=0.55, no_ask=0.42),
        data_quality=DataQuality(needs_review=True),
    )
    output = _trained_output(0.60)

    assert compute_edge_yes(output, record) is None
    assert compute_edge_no(output, record) is None


def test_scenario_5_missing_ask_on_one_side_only_gates_that_side():
    """yes_ask=None, no_ask=0.40 presente -> EDGE_YES=None pero EDGE_NO
    calculable si P_model_YES existe."""
    record = _record(market=MarketData(yes_ask=None, no_ask=0.40))
    output = _trained_output(0.60)

    assert compute_edge_yes(output, record) is None
    assert compute_edge_no(output, record) == pytest.approx((1 - 0.60) - 0.40)


def test_scenario_6_out_of_range_price_never_used_never_clamped():
    """yes_ask=1.15 -> EDGE_YES=None (precio inválido, nunca clampado a 1.0)."""
    record = _record(market=MarketData(yes_ask=1.15))
    output = _trained_output(0.60)

    assert compute_edge_yes(output, record) is None


# =========================================================================
# Casos adicionales: model_status, determinismo
# =========================================================================


def test_model_not_trained_yields_none_edge_on_both_sides():
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _not_trained_output()

    assert compute_edge_yes(output, record) is None
    assert compute_edge_no(output, record) is None


def test_edge_is_deterministic_same_inputs_same_output():
    """Mismo PModelOutput + mismo NormalizedRecord -> exactamente el mismo
    resultado, cualquier número de veces (reproducibilidad para
    backtesting, confirmado explícitamente antes de implementar)."""
    record = _record(market=MarketData(yes_ask=0.55, no_ask=0.42))
    output = _trained_output(0.60)

    results_yes = {compute_edge_yes(output, record) for _ in range(50)}
    results_no = {compute_edge_no(output, record) for _ in range(50)}

    assert len(results_yes) == 1
    assert len(results_no) == 1


# =========================================================================
# Integración (sin red): cadena real normalize_mlb_game -> predict_mlb_elo
# -> compute_edge_yes/no, con las funciones REALES de Pasos 2/6, no
# reimplementadas ni mockeadas.
# =========================================================================


def test_integration_real_normalization_and_elo_inference_feed_edge_honestly():
    """Sin artefacto Elo entrenado (loaded_artifact=None, estado real de
    data/engine.db hoy) -> MODEL_NOT_TRAINED honesto -> EDGE None en
    cascada, sin fallar."""
    from src.models.mlb_elo import predict_mlb_elo
    from src.normalization.mlb_normalizer import normalize_mlb_game

    game_raw = {
        "gamePk": 999999,
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "gameDate": "2026-07-27T22:40:00Z",
        "teams": {
            "away": {"team": {"id": 1, "name": "Away Team"}, "leagueRecord": {"wins": 10, "losses": 5}},
            "home": {"team": {"id": 2, "name": "Home Team"}, "leagueRecord": {"wins": 8, "losses": 7}},
        },
        "venue": {"name": "Test Park"},
    }
    record, _missing = normalize_mlb_game(game_raw)
    record.market = MarketData(yes_ask=0.55, no_ask=0.42)

    output = predict_mlb_elo(record, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert compute_edge_yes(output, record) is None
    assert compute_edge_no(output, record) is None


def test_integration_real_elo_training_feeds_edge_with_a_real_number(tmp_path):
    """Con un artefacto Elo real (entrenado con un histórico sintético
    mínimo vía HistoryRepository, funciones reales de Paso 6, no
    mockeadas) -> EDGE_YES/EDGE_NO son números concretos, calculados con
    la fórmula real de §7 sobre una probabilidad real del modelo."""
    from datetime import timedelta

    from src.models.mlb_elo import predict_mlb_elo, train_mlb_elo_model
    from src.normalization.mlb_normalizer import normalize_mlb_game
    from src.storage.history_repository import HistoryRepository

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 4, 1, tzinfo=timezone.utc)
    for i in range(10):
        game_record = NormalizedRecord(
            sport=Sport.MLB,
            event_id=f"mlb_{i}",
            participant_a="Away",
            participant_b="Home",
            start_time=t0 + timedelta(days=i),
        )
        game_record.model_inputs.context = {"away_team_id": 1, "home_team_id": 2}
        hist.save_event_snapshot(game_record, source="test", captured_at=t0 + timedelta(days=i))
        hist.save_event_result(
            event_id=f"mlb_{i}",
            sport="MLB",
            result="PARTICIPANT_A_WON",
            source="test",
            recorded_at=t0 + timedelta(days=i, hours=3),
        )

    status, artifact, _ = train_mlb_elo_model(hist, models_dir=tmp_path / "models", min_games=10)
    assert status == ModelStatus.TRAINED

    game_raw = {
        "gamePk": 999999,
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "gameDate": "2026-07-27T22:40:00Z",
        "teams": {
            "away": {"team": {"id": 1, "name": "Away Team"}, "leagueRecord": {"wins": 10, "losses": 5}},
            "home": {"team": {"id": 2, "name": "Home Team"}, "leagueRecord": {"wins": 8, "losses": 7}},
        },
        "venue": {"name": "Test Park"},
    }
    record, _missing = normalize_mlb_game(game_raw)
    record.market = MarketData(yes_ask=0.55, no_ask=0.42)

    output = predict_mlb_elo(record, loaded_artifact=artifact)
    assert output.model_status == ModelStatus.TRAINED

    edge_yes = compute_edge_yes(output, record)
    edge_no = compute_edge_no(output, record)

    assert edge_yes == pytest.approx(output.p_model_yes - 0.55)
    assert edge_no == pytest.approx((1 - output.p_model_yes) - 0.42)
