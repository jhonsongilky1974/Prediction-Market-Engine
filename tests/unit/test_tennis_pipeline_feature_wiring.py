"""Tests del wiring de `feature_snapshots` dentro de `run_tennis_pipeline`
(Paso 11). Sin red: conectores monkeypatcheados con payloads que
preservan la forma real verificada contra la API de ESPN (`competitor.id`,
`round.displayName`, ver Design Proposal del Paso 11)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.sofascore import SofascoreConnector
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.schemas import NormalizedRecord, Sport
from src.pipelines.tennis_pipeline import run_tennis_pipeline


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _scoreboard(match_id, home_id, away_id, home_name, away_name, round_display, date_str):
    return {
        "events": [
            {
                "id": "evt1",
                "name": "Test Open",
                "groupings": [
                    {
                        "grouping": {"displayName": "Men's Singles"},
                        "competitions": [
                            {
                                "id": match_id,
                                "date": date_str,
                                "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}},
                                "competitors": [
                                    {"id": home_id, "homeAway": "home", "athlete": {"displayName": home_name}},
                                    {"id": away_id, "homeAway": "away", "athlete": {"displayName": away_name}},
                                ],
                                "round": {"id": "1", "displayName": round_display},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _patch_kalshi_down(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi down"),
    )


def _patch_sofascore_down(monkeypatch):
    monkeypatch.setattr(SofascoreConnector, "search", lambda self, query: _fail("sofascore down"))


def test_run_tennis_pipeline_persists_feature_snapshot_with_known_round(
    monkeypatch, tmp_repository, tmp_history_repository
):
    payload = _scoreboard("300", "111", "222", "Home Player", "Away Player", "Quarterfinal", "2026-07-26T11:00Z")
    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(payload))
    _patch_kalshi_down(monkeypatch)
    _patch_sofascore_down(monkeypatch)

    result = run_tennis_pipeline(
        "atp", "20260726", repository=tmp_repository, history_repository=tmp_history_repository, enrich_sofascore=False
    )

    assert len(result.records) == 1
    record = result.records[0]

    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    assert len(feature_snapshots) == 1
    snap = feature_snapshots[0]
    assert snap["feature_set_version"] == CURRENT_FEATURE_SET_VERSION

    features = json.loads(snap["features_json"])
    assert features["tournament_round_context"] == "Quarterfinal"
    # sin histórico previo del jugador -> rest_days honestamente None
    assert features["rest_days"]["participant_a"] is None
    assert features["rest_days"]["participant_b"] is None


def test_run_tennis_pipeline_computes_rest_days_from_own_prior_history(
    monkeypatch, tmp_repository, tmp_history_repository
):
    """Un partido previo del MISMO jugador (espn_id 111), ya persistido en
    HistoryRepository, debe producir un rest_days real -- no None -- en el
    siguiente partido de ese jugador. Emparejado por espn_id, nunca por
    nombre de texto."""
    prior_start = datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)
    prior_record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_prior",
        participant_a="Home Player",
        participant_b="Someone Else",
        start_time=prior_start,
    )
    prior_record.model_inputs.context = {
        "tournament_name": "Prior Open",
        "tour": "ATP",
        "participant_a_espn_id": "111",
        "participant_b_espn_id": "999",
        "tournament_round": "Final",
    }
    tmp_history_repository.save_event_snapshot(prior_record, source="test", captured_at=prior_start)

    payload = _scoreboard("301", "111", "222", "Home Player", "Away Player", "Semifinal", "2026-07-26T11:00Z")
    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(payload))
    _patch_kalshi_down(monkeypatch)
    _patch_sofascore_down(monkeypatch)

    result = run_tennis_pipeline(
        "atp", "20260726", repository=tmp_repository, history_repository=tmp_history_repository, enrich_sofascore=False
    )

    assert len(result.records) == 1
    record = result.records[0]
    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    features = json.loads(feature_snapshots[0]["features_json"])

    assert features["rest_days"]["participant_a"] == pytest.approx(6.0)
    assert features["rest_days"]["participant_b"] is None  # sin histórico de ese jugador (id 222)


def test_run_tennis_pipeline_fetch_features_false_skips_feature_snapshot(
    monkeypatch, tmp_repository, tmp_history_repository
):
    """`fetch_features=False` conserva el snapshot histórico de mercado
    (Paso 0c) sin pagar el costo de features -- ambos son independientes,
    mismo contrato que `run_mlb_pipeline`."""
    payload = _scoreboard("302", "111", "222", "Home Player", "Away Player", "Final", "2026-07-26T11:00Z")
    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(payload))
    _patch_kalshi_down(monkeypatch)

    result = run_tennis_pipeline(
        "atp",
        "20260726",
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        enrich_sofascore=False,
        fetch_features=False,
    )

    assert len(result.records) == 1
    event_id = result.records[0].event_id
    assert tmp_history_repository.get_snapshots_for_event(event_id)
    assert tmp_history_repository.get_feature_snapshots_for_event(event_id) == []
