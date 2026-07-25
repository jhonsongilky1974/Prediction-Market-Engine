"""Tests de cobertura y lock a nivel de entry point (`scripts/run_e2e.py`,
Paso 0d, subfase de preparación de automatización). Sin red: todos los
conectores externos se monkeypatchean con fixtures sintéticas construidas
con el mismo schema ya verificado contra las fixtures reales de Fase 1.

Verifica:
  - modo `sample` (default) sigue acotado a 1 juego MLB / 5 partidos de
    tenis, exactamente igual que antes de esta subfase (compatibilidad
    hacia atrás explícitamente pedida);
  - modo `historical` procesa TODOS los juegos/partidos disponibles en la
    fecha ya seleccionada (cobertura ampliada, Paso 0d);
  - una segunda invocación mientras el lock ya está sostenido sale limpia,
    SIN instanciar Repository/HistoryRepository ni ejecutar ningún pipeline.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

import scripts.run_e2e as run_e2e_module
from scripts.pipeline_lock import single_instance_lock
from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.mlb import MlbConnector
from src.connectors.sofascore import SofascoreConnector


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _mlb_game(game_pk, away, home):
    return {
        "gamePk": game_pk,
        "gameType": "R",
        "season": "2026",
        "gameDate": "2026-07-21T22:40:00Z",
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "teams": {
            "away": {"team": {"id": 1, "name": away}, "leagueRecord": {"wins": 1, "losses": 1, "pct": ".500"}},
            "home": {"team": {"id": 2, "name": home}, "leagueRecord": {"wins": 1, "losses": 1, "pct": ".500"}},
        },
        "venue": {"id": 1, "name": "Test Park"},
    }


def _mlb_schedule(n_games):
    games = [_mlb_game(900000 + i, f"Away {i}", f"Home {i}") for i in range(n_games)]
    return {"dates": [{"games": games}]}


def _tennis_competition(comp_id, p_a, p_b):
    return {
        "id": comp_id,
        "date": "2026-07-21T12:30Z",
        "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}},
        "competitors": [
            {"homeAway": "home", "athlete": {"displayName": p_a}},
            {"homeAway": "away", "athlete": {"displayName": p_b}},
        ],
    }


def _tennis_scoreboard(n_matches):
    comps = [_tennis_competition(str(1000 + i), f"Player {2 * i}", f"Player {2 * i + 1}") for i in range(n_matches)]
    return {
        "events": [
            {
                "id": "999-2026",
                "name": "Test Open",
                "groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": comps}],
            }
        ]
    }


def _patch_no_network_dependencies(monkeypatch, mlb_games, tennis_matches):
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(_mlb_schedule(mlb_games))
    )
    monkeypatch.setattr(MlbConnector, "get_boxscore", lambda self, game_pk: _fail("no boxscore in test"))
    monkeypatch.setattr(
        MlbConnector,
        "get_person_stats",
        lambda self, person_id, group="pitching", stats_type="season": _fail("no stats in test"),
    )
    monkeypatch.setattr(
        EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(_tennis_scoreboard(tennis_matches))
    )
    monkeypatch.setattr(SofascoreConnector, "search", lambda self, query: _fail("sofascore blocked in test"))
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi down in test"),
    )


def _patch_tmp_storage(monkeypatch, tmp_path):
    from src.storage.history_repository import HistoryRepository
    from src.storage.repository import Repository

    captured = {}

    def fake_repository():
        repo = Repository(db_path=tmp_path / "test.db", raw_dir=tmp_path / "raw")
        captured["repository"] = repo
        return repo

    def fake_history_repository():
        hist = HistoryRepository(db_path=tmp_path / "history.db")
        captured["history_repository"] = hist
        return hist

    monkeypatch.setattr(run_e2e_module, "Repository", fake_repository)
    monkeypatch.setattr(run_e2e_module, "HistoryRepository", fake_history_repository)
    return captured


def test_sample_mode_stays_bounded_to_one_mlb_game_and_five_tennis_matches(monkeypatch, tmp_path):
    """Regresión de compatibilidad: el modo por defecto (sin --mode) sigue
    comportándose exactamente como antes de esta subfase, aunque la fuente
    tenga más eventos disponibles ese día (3 juegos MLB, 8 partidos ATP)."""
    _patch_no_network_dependencies(monkeypatch, mlb_games=3, tennis_matches=8)
    captured = _patch_tmp_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(run_e2e_module, "LOCK_PATH", tmp_path / "run_e2e.lock")
    monkeypatch.setattr(sys, "argv", ["run_e2e.py"])  # sin --mode -> "sample"

    exit_code = run_e2e_module.main()

    assert exit_code == 0
    repo = captured["repository"]
    assert len(repo.get_normalized_records(sport="MLB")) == 1
    assert len(repo.get_normalized_records(sport="TENNIS")) == 5


def test_historical_mode_captures_all_available_mlb_games_and_tennis_matches(monkeypatch, tmp_path):
    _patch_no_network_dependencies(monkeypatch, mlb_games=3, tennis_matches=8)
    captured = _patch_tmp_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(run_e2e_module, "LOCK_PATH", tmp_path / "run_e2e.lock")
    monkeypatch.setattr(sys, "argv", ["run_e2e.py", "--mode", "historical"])

    exit_code = run_e2e_module.main()

    assert exit_code == 0
    repo = captured["repository"]
    mlb_count = len(repo.get_normalized_records(sport="MLB"))
    tennis_count = len(repo.get_normalized_records(sport="TENNIS"))
    assert mlb_count == 3
    assert tennis_count == 8

    # Cobertura histórica: exactamente un event_snapshot por cada record
    # efectivamente persistido -- mismo invariante ya probado a nivel de
    # pipeline individual en test_pipeline_history_wiring.py, ahora
    # confirmado también en modo batch a través del entry point real.
    hist = captured["history_repository"]
    conn = sqlite3.connect(hist.db_path)
    snapshot_count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]
    conn.close()
    assert snapshot_count == mlb_count + tennis_count == 11


def test_second_invocation_exits_cleanly_without_touching_storage_while_lock_held(monkeypatch, tmp_path):
    """Con el lock ya sostenido externamente (simulando una corrida previa
    todavía en curso), una segunda invocación de main() debe salir con
    EXIT_ALREADY_RUNNING SIN instanciar Repository/HistoryRepository ni
    ejecutar ningún pipeline -- se hace que esos constructores fallen
    ruidosamente si llegaran a invocarse, para probarlo sin ambigüedad."""
    lock_path = tmp_path / "run_e2e.lock"
    monkeypatch.setattr(run_e2e_module, "LOCK_PATH", lock_path)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("Repository/HistoryRepository NO debían instanciarse con el lock activo")

    monkeypatch.setattr(run_e2e_module, "Repository", _must_not_be_called)
    monkeypatch.setattr(run_e2e_module, "HistoryRepository", _must_not_be_called)
    monkeypatch.setattr(sys, "argv", ["run_e2e.py"])

    with single_instance_lock(lock_path):
        exit_code = run_e2e_module.main()

    assert exit_code == run_e2e_module.EXIT_ALREADY_RUNNING
