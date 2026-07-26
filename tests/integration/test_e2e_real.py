"""Versión pytest (pass/fail) del test end-to-end real. Para el reporte
legible por humanos usar `python scripts/run_e2e.py` (ver README).
"""
from datetime import date, datetime, timedelta

import pytest

from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.mlb import MlbConnector
from src.pipelines.mlb_pipeline import run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline

pytestmark = pytest.mark.integration


def _next_mlb_date_with_games():
    mlb = MlbConnector()
    for i in range(10):
        d = (date.today() + timedelta(days=i)).isoformat()
        result = mlb.get_schedule(d)
        if result.ok and MlbConnector.extract_games(result.data):
            return d
    return None


def _next_tennis_date_with_matches(tour="atp"):
    espn = EspnTennisConnector()
    for i in range(10):
        d = (date.today() + timedelta(days=i)).strftime("%Y%m%d")
        result = espn.get_scoreboard(tour, d)
        if result.ok and EspnTennisConnector.extract_matches(result.data):
            return d
    return None


def test_mlb_pipeline_end_to_end_real(tmp_repository):
    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.sport.value == "MLB"
    assert record.participant_a is not None
    assert record.participant_b is not None
    # nunca se inventan campos: missing_fields siempre debe ser una lista (posiblemente no vacía)
    assert isinstance(record.data_quality.missing_fields, list)
    assert record.data_quality.data_completeness_score is not None


def test_tennis_pipeline_end_to_end_real(tmp_repository):
    tennis_date = _next_tennis_date_with_matches("atp")
    if tennis_date is None:
        pytest.skip("no hay partidos ATP próximos disponibles vía ESPN")
    result = run_tennis_pipeline("ATP", tennis_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.sport.value == "TENNIS"
    assert record.tennis_variables is not None
    assert isinstance(record.data_quality.missing_fields, list)


def test_mlb_pipeline_history_wiring_reaches_history_repository_real(tmp_repository, tmp_history_repository):
    """Paso 0c, prueba controlada real (E): confirma que el wiring del
    pipeline MLB alcanza `HistoryRepository` de verdad, contra la API real,
    escribiendo únicamente en bases temporales (`tmp_path`) -- nunca en
    `data/engine.db`. No fabrica histórico pasado: `captured_at` es el
    instante real de esta ejecución.

    Paso 5b, Bloque 2: además confirma que el wiring de `feature_snapshots`
    (fetch_features=True por defecto cuando hay history_repository) también
    alcanza la API real -- sin exigir valores no-None (el próximo juego
    puede no tener probable pitcher confirmado todavía), solo que el
    snapshot de features se haya creado."""
    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1
    record = result.records[0]
    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    captured_at = datetime.fromisoformat(snapshots[0]["captured_at"])
    assert captured_at.tzinfo is not None

    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    assert len(feature_snapshots) == 1


def test_tennis_pipeline_history_wiring_reaches_history_repository_real(tmp_repository, tmp_history_repository):
    """Paso 0c, prueba controlada real (E), equivalente para tenis. Ver
    docstring de la prueba MLB hermana arriba."""
    tennis_date = _next_tennis_date_with_matches("atp")
    if tennis_date is None:
        pytest.skip("no hay partidos ATP próximos disponibles vía ESPN")
    result = run_tennis_pipeline(
        "ATP", tennis_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1
    record = result.records[0]
    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    captured_at = datetime.fromisoformat(snapshots[0]["captured_at"])
    assert captured_at.tzinfo is not None


def test_quality_score_computes_on_real_mlb_pipeline_output(tmp_repository):
    """Paso 7, prueba controlada real (E): confirma que
    `compute_quality_score` no falla y produce una salida válida sobre un
    `NormalizedRecord` real de la API (sin `consensus`, ya que
    `ODDS_API_KEY` no está configurada en este entorno -- ver Paso 4)."""
    from src.uncertainty.quality_score import compute_quality_score

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    score = compute_quality_score(record, consensus=None)

    assert score.confidence_method == "HEURISTIC_V1"
    assert score.components["missing_critical"] is not None  # siempre calculable
    if score.confidence is not None:
        assert 0.0 <= score.confidence <= 1.0


def test_mlb_elo_inference_works_on_real_pipeline_output(tmp_repository):
    """Paso 6, prueba controlada real (E): confirma que `predict_mlb_elo`
    no falla sobre un `NormalizedRecord` real de la API. Sin artefacto
    entrenado todavía en este entorno (`loaded_artifact=None`) ->
    `MODEL_NOT_TRAINED` honesto, nunca una probabilidad fabricada."""
    from src.models.base import ModelStatus
    from src.models.mlb_elo import predict_mlb_elo

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    output = predict_mlb_elo(record, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None


def test_backtest_dataset_builds_honestly_on_real_mlb_pipeline_output_without_results(
    tmp_repository, tmp_history_repository
):
    """Paso 9, prueba controlada real (E): confirma que
    `build_backtest_dataset` no falla contra un `HistoryRepository`
    alimentado por una corrida real del pipeline MLB. Sin `event_results`
    reales sincronizados en este entorno, el dataset debe reportar
    honestamente 0 filas (excluidas por "sin event_result todavía"), nunca
    fabricar una etiqueta."""
    from src.backtesting.dataset import build_backtest_dataset

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1

    dataset = build_backtest_dataset(tmp_history_repository)

    assert dataset.size == 0
    assert any("sin event_result" in w for w in dataset.warnings)


def test_edge_and_ev_compute_honestly_on_real_mlb_pipeline_output(tmp_repository):
    """Paso 8, prueba controlada real (E): confirma que
    `compute_edge_yes`/`compute_edge_no`/`compute_ev_yes_bruto`/
    `compute_ev_no_bruto` no fallan sobre un `NormalizedRecord` real de la
    API. Sin modelo entrenado en este entorno -> EDGE/EV = None en
    cascada, honesto, nunca fabricado."""
    from src.models.mlb_elo import predict_mlb_elo
    from src.signals.edge import compute_edge_no, compute_edge_yes
    from src.signals.expected_value import compute_ev_no_bruto, compute_ev_yes_bruto

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    model_output = predict_mlb_elo(record, loaded_artifact=None)

    assert compute_edge_yes(model_output, record) is None
    assert compute_edge_no(model_output, record) is None
    assert compute_ev_yes_bruto(model_output, record) is None
    assert compute_ev_no_bruto(model_output, record) is None
