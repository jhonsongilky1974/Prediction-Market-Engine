"""Tests de `sync_mlb_event_results` (Paso 5b, Bloque 3). Sin red:
`MlbConnector.get_schedule` monkeypatcheado. Todo contra `HistoryRepository`
en `tmp_path` -- nunca `data/engine.db`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.mlb import MlbConnector
from src.pipelines.mlb_results_sync import default_lookback_dates, sync_mlb_event_results
from src.storage.history_repository import HistoryRepository


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _game(game_pk, detailed_state, away_winner=None, home_winner=None):
    teams = {"away": {"team": {"id": 1}}, "home": {"team": {"id": 2}}}
    if away_winner is not None:
        teams["away"]["isWinner"] = away_winner
    if home_winner is not None:
        teams["home"]["isWinner"] = home_winner
    return {
        "gamePk": game_pk,
        "status": {"detailedState": detailed_state},
        "teams": teams,
    }


def _schedule(games):
    return {"dates": [{"games": games}]}


def _patch_schedule(monkeypatch, games_by_date):
    def fake_get_schedule(self, date, hydrate_probable_pitcher=True):
        if date not in games_by_date:
            return _fail(f"no data for {date}")
        return _ok(_schedule(games_by_date[date]))

    monkeypatch.setattr(MlbConnector, "get_schedule", fake_get_schedule)


def test_default_lookback_dates_is_today_plus_two_previous_days():
    from datetime import date

    dates = default_lookback_dates(today=date(2026, 7, 25), lookback_days=3)
    assert dates == ["2026-07-25", "2026-07-24", "2026-07-23"]


def test_final_game_away_winner_maps_to_participant_a_won(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(monkeypatch, {"2026-07-24": [_game(100, "Final", away_winner=True, home_winner=False)]})

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary.recorded == 1
    results = hist.get_results_for_event("mlb_100")
    assert len(results) == 1
    assert results[0]["result"] == "PARTICIPANT_A_WON"


def test_final_game_home_winner_maps_to_participant_b_won(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(monkeypatch, {"2026-07-24": [_game(101, "Final", away_winner=False, home_winner=True)]})

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary.recorded == 1
    results = hist.get_results_for_event("mlb_101")
    assert results[0]["result"] == "PARTICIPANT_B_WON"


def test_final_game_with_ambiguous_winner_is_skipped_never_fabricated(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(
        monkeypatch,
        {
            "2026-07-24": [
                _game(102, "Final"),  # sin isWinner en absoluto
                _game(103, "Final", away_winner=True, home_winner=True),  # ambos True -> ambiguo
            ]
        },
    )

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary.recorded == 0
    assert summary.skipped_ambiguous == 2
    assert hist.get_results_for_event("mlb_102") == []
    assert hist.get_results_for_event("mlb_103") == []


def test_postponed_and_cancelled_games_map_correctly(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(
        monkeypatch,
        {"2026-07-24": [_game(104, "Postponed"), _game(105, "Cancelled")]},
    )

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary.recorded == 2
    assert summary.postponed == 1
    assert summary.cancelled == 1
    assert hist.get_results_for_event("mlb_104")[0]["result"] == "POSTPONED"
    assert hist.get_results_for_event("mlb_105")[0]["result"] == "CANCELLED"


def test_undecided_game_is_not_recorded(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(monkeypatch, {"2026-07-24": [_game(106, "Preview"), _game(107, "Live")]})

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary.recorded == 0
    assert summary.not_yet_decided == 2
    assert hist.get_results_for_event("mlb_106") == []


def test_already_recorded_event_is_not_duplicated_on_second_sync(monkeypatch, tmp_path):
    """Idempotencia a nivel de llamador -- correr el sync dos veces sobre
    el mismo juego ya concluido no genera una segunda fila."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(monkeypatch, {"2026-07-24": [_game(108, "Final", away_winner=True, home_winner=False)]})

    summary1 = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])
    summary2 = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-24"])

    assert summary1.recorded == 1
    assert summary2.recorded == 0
    assert summary2.already_recorded == 1
    assert len(hist.get_results_for_event("mlb_108")) == 1  # una sola fila, no dos


def test_fetch_error_for_one_date_does_not_block_others(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_schedule(monkeypatch, {"2026-07-24": [_game(109, "Final", away_winner=True, home_winner=False)]})
    # "2026-07-23" no está en games_by_date -> _fail

    summary = sync_mlb_event_results(MlbConnector(), hist, ["2026-07-23", "2026-07-24"])

    assert summary.recorded == 1
    assert len(summary.fetch_errors) == 1
    assert "2026-07-23" in summary.fetch_errors[0]
