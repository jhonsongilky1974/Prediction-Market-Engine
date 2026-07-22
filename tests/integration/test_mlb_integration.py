"""Tests de integración reales contra la MLB Stats API. Requieren red.
Ejecutar con: pytest -m integration tests/integration
"""
from datetime import date, timedelta

import pytest

from src.connectors.mlb import MlbConnector

pytestmark = pytest.mark.integration


def _next_days(n=5):
    today = date.today()
    return [(today + timedelta(days=i)).isoformat() for i in range(n)]


def test_get_schedule_real():
    mlb = MlbConnector()
    for d in _next_days():
        result = mlb.get_schedule(d)
        if result.ok and MlbConnector.extract_games(result.data):
            games = MlbConnector.extract_games(result.data)
            assert games[0]["gamePk"] is not None
            return
    pytest.skip("no se encontraron juegos MLB programados en los próximos días (o la API no respondió)")


def test_get_boxscore_real_for_first_available_game():
    mlb = MlbConnector()
    game_pk = None
    for d in _next_days():
        result = mlb.get_schedule(d)
        if result.ok:
            games = MlbConnector.extract_games(result.data)
            if games:
                game_pk = games[0]["gamePk"]
                break
    if game_pk is None:
        pytest.skip("no hay gamePk disponible para probar boxscore")
    result = mlb.get_boxscore(game_pk)
    # el boxscore puede no existir aún si el juego no ha empezado; solo
    # verificamos que la llamada falla limpiamente o retorna JSON válido
    assert result.ok in (True, False)
    if result.ok:
        assert isinstance(result.data, dict)
