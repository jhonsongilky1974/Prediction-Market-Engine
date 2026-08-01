"""Tests de `run_results_sync` (Fase 4, Paso 4.0B -- D-4B). Sin red:
`MlbConnector.get_schedule`/`EspnTennisConnector.get_scoreboard`
monkeypatcheados, mismo patrón que `test_mlb_results_sync.py`/
`test_tennis_results_sync.py`. Todo contra `HistoryRepository` en
`tmp_path` -- nunca `data/engine.db`. No re-testea la lógica de mapeo de
resultados (ya cubierta en los dos archivos de arriba) -- solo que la
orquestación combina ambos deportes correctamente.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.mlb import MlbConnector
from src.storage.history_repository import HistoryRepository

from scripts.sync_results import run_results_sync


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _mlb_game(game_pk, detailed_state, away_winner=None, home_winner=None):
    teams = {"away": {"team": {"id": 1}}, "home": {"team": {"id": 2}}}
    if away_winner is not None:
        teams["away"]["isWinner"] = away_winner
    if home_winner is not None:
        teams["home"]["isWinner"] = home_winner
    return {"gamePk": game_pk, "status": {"detailedState": detailed_state}, "teams": teams}


def _mlb_schedule(games):
    return {"dates": [{"games": games}]}


def _patch_mlb_schedule(monkeypatch, games_by_date):
    def fake_get_schedule(self, d, hydrate_probable_pitcher=True):
        if d not in games_by_date:
            return _fail(f"no data for {d}")
        return _ok(_mlb_schedule(games_by_date[d]))

    monkeypatch.setattr(MlbConnector, "get_schedule", fake_get_schedule)


def _tennis_match(match_id, state, completed=True, home_winner=None, away_winner=None):
    competitors = [
        {"homeAway": "home", "athlete": {"displayName": "Home Player"}},
        {"homeAway": "away", "athlete": {"displayName": "Away Player"}},
    ]
    if home_winner is not None:
        competitors[0]["winner"] = home_winner
    if away_winner is not None:
        competitors[1]["winner"] = away_winner
    return {
        "id": match_id,
        "date": "2026-07-24T12:00Z",
        "status": {"type": {"name": "STATUS_FINAL" if state == "post" else "STATUS_SCHEDULED", "state": state, "completed": completed}},
        "competitors": competitors,
    }


def _tennis_scoreboard(matches):
    return {"events": [{"id": "1", "name": "Test Open", "groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": matches}]}]}


def _patch_tennis_scoreboard(monkeypatch, matches_by_date):
    def fake_get_scoreboard(self, tour, d):
        if d not in matches_by_date:
            return _fail(f"no data for {d}")
        return _ok(_tennis_scoreboard(matches_by_date[d]))

    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", fake_get_scoreboard)


def test_combines_mlb_and_tennis_into_a_single_summary(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_mlb_schedule(monkeypatch, {"2026-07-24": [_mlb_game(100, "Final", away_winner=True, home_winner=False)]})
    _patch_tennis_scoreboard(monkeypatch, {"20260724": [_tennis_match("200", "post", home_winner=True, away_winner=False)]})

    summary = run_results_sync(
        hist=hist,
        mlb=MlbConnector(),
        espn=EspnTennisConnector(),
        today=date(2026, 7, 24),
        mlb_lookback_days=1,
        tennis_lookback_days=1,
    )

    assert summary["mlb"].recorded == 1
    assert summary["tennis"].recorded == 1
    assert hist.get_results_for_event("mlb_100")[0]["result"] == "PARTICIPANT_A_WON"
    assert hist.get_results_for_event("espn_tennis_atp_200")[0]["result"] == "PARTICIPANT_A_WON"


def test_default_tour_is_atp_matching_production_capture(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_mlb_schedule(monkeypatch, {})
    _patch_tennis_scoreboard(monkeypatch, {"20260724": [_tennis_match("201", "post", home_winner=True, away_winner=False)]})

    summary = run_results_sync(
        hist=hist,
        mlb=MlbConnector(),
        espn=EspnTennisConnector(),
        today=date(2026, 7, 24),
        mlb_lookback_days=1,
        tennis_lookback_days=1,
    )

    assert summary["tennis"].tour == "ATP"
    assert hist.get_results_for_event("espn_tennis_atp_201")


def test_second_call_does_not_duplicate_already_recorded_results(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_mlb_schedule(monkeypatch, {"2026-07-24": [_mlb_game(101, "Final", away_winner=True, home_winner=False)]})
    _patch_tennis_scoreboard(monkeypatch, {"20260724": [_tennis_match("202", "post", home_winner=True, away_winner=False)]})
    kwargs = dict(
        hist=hist, mlb=MlbConnector(), espn=EspnTennisConnector(),
        today=date(2026, 7, 24), mlb_lookback_days=1, tennis_lookback_days=1,
    )

    first = run_results_sync(**kwargs)
    second = run_results_sync(**kwargs)

    assert first["mlb"].recorded == 1 and first["tennis"].recorded == 1
    assert second["mlb"].recorded == 0 and second["mlb"].already_recorded == 1
    assert second["tennis"].recorded == 0 and second["tennis"].already_recorded == 1
    assert len(hist.get_results_for_event("mlb_101")) == 1
    assert len(hist.get_results_for_event("espn_tennis_atp_202")) == 1


def test_mlb_fetch_error_does_not_block_tennis_sync(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_mlb_schedule(monkeypatch, {})  # toda fecha falla (no está en el dict)
    _patch_tennis_scoreboard(monkeypatch, {"20260724": [_tennis_match("203", "post", home_winner=True, away_winner=False)]})

    summary = run_results_sync(
        hist=hist,
        mlb=MlbConnector(),
        espn=EspnTennisConnector(),
        today=date(2026, 7, 24),
        mlb_lookback_days=1,
        tennis_lookback_days=1,
    )

    assert summary["mlb"].fetch_errors
    assert summary["tennis"].recorded == 1


def test_uses_independent_lookback_days_per_sport(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_mlb_schedule(monkeypatch, {"2026-07-23": [_mlb_game(102, "Final", away_winner=True, home_winner=False)]})
    _patch_tennis_scoreboard(monkeypatch, {})

    summary = run_results_sync(
        hist=hist,
        mlb=MlbConnector(),
        espn=EspnTennisConnector(),
        today=date(2026, 7, 24),
        mlb_lookback_days=2,
        tennis_lookback_days=1,
    )

    assert summary["mlb"].dates_scanned == ["2026-07-24", "2026-07-23"]
    assert summary["tennis"].dates_scanned == ["20260724"]
    assert summary["mlb"].recorded == 1
