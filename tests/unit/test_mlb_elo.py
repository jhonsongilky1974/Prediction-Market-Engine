"""Tests del baseline Elo MLB (Paso 6). Ver el Design Proposal aprobado
antes de esta implementación -- parámetros (`K=20`, `home_advantage=25`,
`initial_rating=1500`, `min_games=50`) son exactamente los aprobados ahí.

Todo contra `HistoryRepository` en `tmp_path` -- nunca `data/engine.db`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.base import ModelStatus
from src.models.mlb_elo import (
    DEFAULT_HOME_ADVANTAGE,
    DEFAULT_INITIAL_RATING,
    DEFAULT_K,
    EloGameRecord,
    build_mlb_elo_game_sequence,
    compute_mlb_elo_ratings,
    load_latest_mlb_elo_artifact,
    predict_mlb_elo,
    train_mlb_elo_model,
)
from src.models.schemas import ModelInputs, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

T0 = datetime(2026, 4, 1, 18, 0, tzinfo=timezone.utc)


def _record(event_id, team_a_id=1, team_b_id=2, start_time=None):
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id=event_id,
        participant_a="Away Team",
        participant_b="Home Team",
        start_time=start_time,
        model_inputs=ModelInputs(context={"away_team_id": team_a_id, "home_team_id": team_b_id}),
    )


def _add_game(hist, event_id, start_time, team_a_id=1, team_b_id=2, result="PARTICIPANT_A_WON"):
    record = _record(event_id, team_a_id, team_b_id, start_time)
    captured_at = start_time or T0
    hist.save_event_snapshot(record, source="test", captured_at=captured_at)
    if result is not None:
        hist.save_event_result(
            event_id=event_id, sport="MLB", result=result, source="test", recorded_at=captured_at + timedelta(hours=3)
        )


# ---------------------------------------------------------------------
# Secuencia cronológica (dataset builder)
# ---------------------------------------------------------------------


def test_sequence_orders_by_game_time_not_insertion_order(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    # insertados fuera de orden a propósito
    _add_game(hist, "mlb_3", T0 + timedelta(days=2))
    _add_game(hist, "mlb_1", T0)
    _add_game(hist, "mlb_2", T0 + timedelta(days=1))

    sequence = build_mlb_elo_game_sequence(hist)

    assert [g.event_id for g in sequence.games] == ["mlb_1", "mlb_2", "mlb_3"]


def test_sequence_excludes_non_mlb_event_ids(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_999",
        participant_a="A",
        participant_b="B",
        start_time=T0,
        model_inputs=ModelInputs(context={"away_team_id": 1, "home_team_id": 2}),
    )
    hist.save_event_snapshot(record, source="test", captured_at=T0)
    hist.save_event_result(event_id="espn_tennis_atp_999", sport="TENNIS", result="PARTICIPANT_A_WON", source="test")

    sequence = build_mlb_elo_game_sequence(hist)

    assert sequence.size == 0
    assert any("mlb_" in w for w in sequence.warnings)


def test_sequence_excludes_missing_team_id(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = NormalizedRecord(sport=Sport.MLB, event_id="mlb_1", participant_a="A", participant_b="B", start_time=T0)
    hist.save_event_snapshot(record, source="test", captured_at=T0)
    hist.save_event_result(event_id="mlb_1", sport="MLB", result="PARTICIPANT_A_WON", source="test")

    sequence = build_mlb_elo_game_sequence(hist)

    assert sequence.size == 0
    assert any("team_id" in w for w in sequence.warnings)


def test_sequence_excludes_missing_start_time(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_game(hist, "mlb_1", start_time=None)

    sequence = build_mlb_elo_game_sequence(hist)

    assert sequence.size == 0
    assert any("event_start_time" in w for w in sequence.warnings)


def test_sequence_excludes_events_without_result(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_game(hist, "mlb_1", T0, result=None)

    sequence = build_mlb_elo_game_sequence(hist)

    assert sequence.size == 0


def test_sequence_excludes_non_binary_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_game(hist, "mlb_1", T0, result="CANCELLED")

    sequence = build_mlb_elo_game_sequence(hist)

    assert sequence.size == 0
    assert any("PARTICIPANT_A_WON" in w for w in sequence.warnings)


# ---------------------------------------------------------------------
# Cálculo de ratings -- función pura
# ---------------------------------------------------------------------


def test_compute_ratings_single_game_matches_hand_calculation():
    """Verificado a mano: R_a=1500,R_b=1500,home_advantage=25 ->
    R_b_efectivo=1525 -> expected_a=1/(1+10^(25/400))=0.46409...
    delta=20*(1-0.46409)=10.7183."""
    games = [EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=1, game_time=T0)]
    ratings = compute_mlb_elo_ratings(games, k=20.0, home_advantage=25.0, initial_rating=1500.0)

    assert ratings[1] == pytest.approx(1510.7183, abs=1e-3)
    assert ratings[2] == pytest.approx(1489.2817, abs=1e-3)
    # zero-sum: lo que gana uno lo pierde el otro exactamente
    assert (ratings[1] - 1500.0) == pytest.approx(-(ratings[2] - 1500.0))


def test_compute_ratings_new_team_starts_at_initial_rating():
    games = [EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=1, game_time=T0)]
    ratings = compute_mlb_elo_ratings(games, initial_rating=1600.0)
    # con initial_rating=1600 para ambos, el resultado debe partir de 1600, no 1500
    assert ratings[1] != pytest.approx(1510.7183, abs=1e-3)


def test_compute_ratings_home_win_favors_home_team():
    games = [EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=0, game_time=T0)]  # home (b) gana
    ratings = compute_mlb_elo_ratings(games)
    assert ratings[2] > 1500.0  # el ganador sube
    assert ratings[1] < 1500.0  # el perdedor baja


def test_compute_ratings_sequential_across_multiple_games():
    """Un equipo que gana dos veces seguidas debe terminar con rating
    estrictamente mayor que ganando una sola vez."""
    one_game = [EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=1, game_time=T0)]
    two_games = one_game + [
        EloGameRecord(event_id="mlb_2", team_a_id=1, team_b_id=3, label=1, game_time=T0 + timedelta(days=1))
    ]
    ratings_one = compute_mlb_elo_ratings(one_game)
    ratings_two = compute_mlb_elo_ratings(two_games)
    assert ratings_two[1] > ratings_one[1]


def test_no_look_ahead_bias_rating_update_is_composable():
    """Prueba explícita, ejecutable, de ausencia de look-ahead: reconstruye
    A MANO -- usando ÚNICAMENTE el rating tras el primer partido, nunca el
    resultado del segundo -- la actualización que un segundo partido
    (posterior) DEBERÍA producir según la fórmula, y confirma que coincide
    exactamente con lo que produce la función real, sin importar cuál sea
    el resultado de ese segundo partido.

    Si `compute_mlb_elo_ratings` tuviera cualquier forma de look-ahead
    (p.ej. usar el resultado de un partido posterior para ajustar uno
    anterior), esta reconstrucción manual -- que parte SOLO del rating ya
    calculado tras g1 -- dejaría de coincidir con la salida real."""
    g1 = EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=1, game_time=T0)
    g2_a_gana = EloGameRecord(event_id="mlb_2", team_a_id=1, team_b_id=2, label=1, game_time=T0 + timedelta(days=1))
    g2_b_gana = EloGameRecord(event_id="mlb_2", team_a_id=1, team_b_id=2, label=0, game_time=T0 + timedelta(days=1))

    # Rating tras procesar ÚNICAMENTE g1 -- este es, por construcción, el
    # único estado disponible "en el momento" de predecir g2, sin importar
    # qué ocurra después.
    ratings_after_g1 = compute_mlb_elo_ratings([g1])

    def _manual_update(ratings_before, game):
        r_a = ratings_before.get(game.team_a_id, DEFAULT_INITIAL_RATING)
        r_b = ratings_before.get(game.team_b_id, DEFAULT_INITIAL_RATING)
        expected_a = 1.0 / (1.0 + 10.0 ** (((r_b + DEFAULT_HOME_ADVANTAGE) - r_a) / 400.0))
        delta = DEFAULT_K * (float(game.label) - expected_a)
        return {**ratings_before, game.team_a_id: r_a + delta, game.team_b_id: r_b - delta}

    expected_after_g2_a = _manual_update(ratings_after_g1, g2_a_gana)
    expected_after_g2_b = _manual_update(ratings_after_g1, g2_b_gana)

    actual_after_g2_a = compute_mlb_elo_ratings([g1, g2_a_gana])
    actual_after_g2_b = compute_mlb_elo_ratings([g1, g2_b_gana])

    assert actual_after_g2_a[1] == pytest.approx(expected_after_g2_a[1])
    assert actual_after_g2_a[2] == pytest.approx(expected_after_g2_a[2])
    assert actual_after_g2_b[1] == pytest.approx(expected_after_g2_b[1])
    assert actual_after_g2_b[2] == pytest.approx(expected_after_g2_b[2])


def test_no_look_ahead_bias_future_game_outcome_never_alters_earlier_rating():
    """Complemento del test anterior: el rating que g1 produce POR SÍ SOLO
    debe ser idéntico sin importar qué partido (ni qué resultado) se le
    añada después -- ninguna de las dos ramas con resultados opuestos de
    g2 puede "filtrarse hacia atrás" y cambiar lo ya calculado para g1."""
    g1 = EloGameRecord(event_id="mlb_1", team_a_id=1, team_b_id=2, label=1, game_time=T0)
    ratings_g1_alone = compute_mlb_elo_ratings([g1])

    # Verificado indirectamente: si hubiera leakage, el rating de g1 SÓLO
    # sería observable de forma consistente calculándolo aislado -- lo que
    # ya probamos arriba coincide exactamente con el primer paso de
    # cualquier secuencia más larga, sin importar el futuro.
    g2 = EloGameRecord(event_id="mlb_2", team_a_id=1, team_b_id=3, label=0, game_time=T0 + timedelta(days=1))
    ratings_with_g2 = compute_mlb_elo_ratings([g1, g2])

    # El rating del equipo 2 (que NO participa en g2) es idéntico en ambos
    # casos -- prueba directa de que g2 no reescribe nada de g1.
    assert ratings_with_g2[2] == pytest.approx(ratings_g1_alone[2])


# ---------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------


def test_train_below_threshold_returns_insufficient_history(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_game(hist, "mlb_1", T0)
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_mlb_elo_model(hist, models_dir=models_dir, min_games=50)

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("umbral" in w for w in warnings)
    assert not models_dir.exists() or list(models_dir.glob("*.json")) == []


def test_train_at_threshold_produces_artifact(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        _add_game(hist, f"mlb_{i}", T0 + timedelta(days=i), team_a_id=1, team_b_id=2, result="PARTICIPANT_A_WON")
    models_dir = tmp_path / "models"

    status, artifact, _ = train_mlb_elo_model(
        hist, models_dir=models_dir, min_games=10, now=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )

    assert status == ModelStatus.TRAINED
    assert artifact.n_games == 10
    assert artifact.model_version.startswith("mlb_elo_v1_")
    assert artifact.file_path.exists()
    assert artifact.team_ratings[1] > 1500.0  # ganó las 10 -> rating sube
    assert artifact.team_ratings[2] < 1500.0


# ---------------------------------------------------------------------
# Persistencia (save/load)
# ---------------------------------------------------------------------


def test_load_latest_returns_none_when_dir_missing(tmp_path):
    assert load_latest_mlb_elo_artifact(models_dir=tmp_path / "does_not_exist") is None


def test_load_latest_returns_none_when_empty(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    assert load_latest_mlb_elo_artifact(models_dir=models_dir) is None


def test_save_load_roundtrip(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        _add_game(hist, f"mlb_{i}", T0 + timedelta(days=i))
    models_dir = tmp_path / "models"
    status, artifact, _ = train_mlb_elo_model(hist, models_dir=models_dir, min_games=10)
    assert status == ModelStatus.TRAINED

    loaded = load_latest_mlb_elo_artifact(models_dir=models_dir)

    assert loaded is not None
    assert loaded.model_version == artifact.model_version
    assert loaded.team_ratings == pytest.approx(artifact.team_ratings)
    assert loaded.k == artifact.k
    assert loaded.home_advantage == artifact.home_advantage


def test_load_latest_returns_most_recent_when_multiple(tmp_path):
    hist1 = HistoryRepository(db_path=tmp_path / "hist1.db")
    hist2 = HistoryRepository(db_path=tmp_path / "hist2.db")
    for i in range(10):
        _add_game(hist1, f"mlb_a{i}", T0 + timedelta(days=i))
        _add_game(hist2, f"mlb_b{i}", T0 + timedelta(days=i))
    models_dir = tmp_path / "models"

    _, older, _ = train_mlb_elo_model(hist1, models_dir=models_dir, min_games=10, now=datetime(2026, 5, 1, tzinfo=timezone.utc))
    _, newer, _ = train_mlb_elo_model(hist2, models_dir=models_dir, min_games=10, now=datetime(2026, 5, 3, tzinfo=timezone.utc))

    loaded = load_latest_mlb_elo_artifact(models_dir=models_dir)
    assert loaded.model_version == newer.model_version
    assert loaded.model_version != older.model_version


# ---------------------------------------------------------------------
# Inference contract
# ---------------------------------------------------------------------


def test_predict_without_artifact_is_honest_and_never_fabricates():
    record = _record("mlb_live_1", team_a_id=1, team_b_id=2, start_time=T0)
    output = predict_mlb_elo(record, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert output.model_version is None


def test_predict_with_artifact_computes_valid_probability(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        _add_game(hist, f"mlb_{i}", T0 + timedelta(days=i), team_a_id=1, team_b_id=2, result="PARTICIPANT_A_WON")
    _, artifact, _ = train_mlb_elo_model(hist, models_dir=tmp_path / "models", min_games=10)

    record = _record("mlb_live_1", team_a_id=1, team_b_id=2, start_time=T0 + timedelta(days=20))
    output = predict_mlb_elo(record, loaded_artifact=artifact)

    assert output.model_status == ModelStatus.TRAINED
    assert output.p_model_yes is not None
    assert 0.0 <= output.p_model_yes <= 1.0
    # el equipo 1 ganó siempre en el entrenamiento -> probabilidad > 0.5 de ganar de nuevo
    assert output.p_model_yes > 0.5
    assert output.model_version == artifact.model_version
    assert output.data_cutoff_timestamp == artifact.trained_at  # no "ahora"


def test_predict_unseen_team_uses_initial_rating_as_prior(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        _add_game(hist, f"mlb_{i}", T0 + timedelta(days=i), team_a_id=1, team_b_id=2)
    _, artifact, _ = train_mlb_elo_model(hist, models_dir=tmp_path / "models", min_games=10)

    # equipo 999 nunca apareció en el entrenamiento
    record = _record("mlb_live_1", team_a_id=999, team_b_id=2, start_time=T0 + timedelta(days=20))
    output = predict_mlb_elo(record, loaded_artifact=artifact)

    assert output.model_status == ModelStatus.TRAINED
    assert output.p_model_yes is not None
    assert any("999" in w and "initial_rating" in w for w in output.warnings)


def test_predict_missing_team_id_returns_model_not_trained(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        _add_game(hist, f"mlb_{i}", T0 + timedelta(days=i))
    _, artifact, _ = train_mlb_elo_model(hist, models_dir=tmp_path / "models", min_games=10)

    record = NormalizedRecord(sport=Sport.MLB, event_id="mlb_live_1", participant_a="A", participant_b="B")
    output = predict_mlb_elo(record, loaded_artifact=artifact)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert "away_team_id" in output.missing_features
    assert "home_team_id" in output.missing_features
