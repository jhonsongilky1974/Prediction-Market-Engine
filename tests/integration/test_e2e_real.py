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
