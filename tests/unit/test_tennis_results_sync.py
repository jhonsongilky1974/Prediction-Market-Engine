"""Tests de `sync_tennis_event_results` (Paso 11, mismo patrón que
`test_mlb_results_sync.py`). Sin red: `EspnTennisConnector.get_scoreboard`
monkeypatcheado. Todo contra `HistoryRepository` en `tmp_path` -- nunca
`data/engine.db`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.pipelines.tennis_results_sync import default_lookback_dates, sync_tennis_event_results
from src.storage.history_repository import HistoryRepository


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _match(match_id, state, completed=True, home_winner=None, away_winner=None):
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


def _scoreboard(matches):
    return {"events": [{"id": "1", "name": "Test Open", "groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": matches}]}]}


def _patch_scoreboard(monkeypatch, matches_by_date):
    def fake_get_scoreboard(self, tour, d):
        if d not in matches_by_date:
            return _fail(f"no data for {d}")
        return _ok(_scoreboard(matches_by_date[d]))

    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", fake_get_scoreboard)


def test_default_lookback_dates_uses_yyyymmdd_format():
    dates = default_lookback_dates(today=date(2026, 7, 25), lookback_days=3)
    assert dates == ["20260725", "20260724", "20260723"]


def test_final_match_home_winner_maps_to_participant_a_won(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(monkeypatch, {"20260724": [_match("200", "post", home_winner=True, away_winner=False)]})

    summary = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])

    assert summary.recorded == 1
    results = hist.get_results_for_event("espn_tennis_atp_200")
    assert len(results) == 1
    assert results[0]["result"] == "PARTICIPANT_A_WON"


def test_final_match_away_winner_maps_to_participant_b_won(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(monkeypatch, {"20260724": [_match("201", "post", home_winner=False, away_winner=True)]})

    summary = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])

    assert summary.recorded == 1
    results = hist.get_results_for_event("espn_tennis_atp_201")
    assert results[0]["result"] == "PARTICIPANT_B_WON"


def test_final_match_with_ambiguous_winner_is_skipped_never_fabricated(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(
        monkeypatch,
        {
            "20260724": [
                _match("202", "post"),  # sin winner en absoluto
                _match("203", "post", home_winner=True, away_winner=True),  # ambos True -> ambiguo
            ]
        },
    )

    summary = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])

    assert summary.recorded == 0
    assert summary.skipped_ambiguous == 2
    assert hist.get_results_for_event("espn_tennis_atp_202") == []
    assert hist.get_results_for_event("espn_tennis_atp_203") == []


def test_undecided_match_is_not_recorded(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(monkeypatch, {"20260724": [_match("204", "pre", completed=False), _match("205", "in", completed=False)]})

    summary = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])

    assert summary.recorded == 0
    assert summary.not_yet_decided == 2
    assert hist.get_results_for_event("espn_tennis_atp_204") == []


def test_already_recorded_event_is_not_duplicated_on_second_sync(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(monkeypatch, {"20260724": [_match("206", "post", home_winner=True, away_winner=False)]})

    summary1 = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])
    summary2 = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260724"])

    assert summary1.recorded == 1
    assert summary2.recorded == 0
    assert summary2.already_recorded == 1
    assert len(hist.get_results_for_event("espn_tennis_atp_206")) == 1


def test_fetch_error_for_one_date_does_not_block_others(monkeypatch, tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _patch_scoreboard(monkeypatch, {"20260724": [_match("207", "post", home_winner=True, away_winner=False)]})

    summary = sync_tennis_event_results(EspnTennisConnector(), hist, "atp", ["20260723", "20260724"])

    assert summary.recorded == 1
    assert len(summary.fetch_errors) == 1
    assert "20260723" in summary.fetch_errors[0]
