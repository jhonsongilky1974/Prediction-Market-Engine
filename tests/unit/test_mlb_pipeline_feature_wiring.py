"""Tests del wiring de `feature_snapshots` dentro de `run_mlb_pipeline`
(Paso 5b, Bloque 2). Sin red: conectores monkeypatcheados con payloads
mínimos pero con la forma real que `src/features/mlb_features.py` espera
(verificada leyendo `_extract_season_pitching_stat`/`_extract_handedness_splits`/
`compute_team_ops_season`), para que el valor calculado no sea trivialmente
None por un payload malformado.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.kalshi import KalshiConnector
from src.connectors.mlb import MlbConnector
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.pipelines.mlb_pipeline import run_mlb_pipeline


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _season_stat_payload(era="3.50", games_started=20):
    return {"stats": [{"splits": [{"stat": {"gamesStarted": games_started, "era": era, "whip": "1.20"}}]}]}


def _handedness_splits_payload():
    return {
        "stats": [
            {
                "splits": [
                    {"split": {"code": "vr"}, "stat": {"ops": ".720"}},
                    {"split": {"code": "vl"}, "stat": {"ops": ".680"}},
                ]
            }
        ]
    }


def _team_hitting_payload(ops=".750"):
    return {"stats": [{"splits": [{"stat": {"ops": ops}}]}]}


def _patch_kalshi_down(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi down"),
    )


def test_run_mlb_pipeline_persists_feature_snapshot_with_computed_values(
    monkeypatch, tmp_repository, tmp_history_repository, mlb_schedule_sample
):
    """mlb_schedule_sample trae probablePitcher en ambos lados (IDs
    696070/800048, ver tests/fixtures/mlb_schedule_sample.json) -- exactamente
    el caso que ejercita todas las llamadas nuevas del Bloque 2."""
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(mlb_schedule_sample)
    )
    monkeypatch.setattr(MlbConnector, "get_boxscore", lambda self, game_pk: _fail("no boxscore in test"))

    def fake_get_person_stats(self, person_id, group="pitching", stats_type="season"):
        if stats_type == "season":
            return _ok(_season_stat_payload())
        if stats_type == "gameLog":
            return _ok({"stats": [{"splits": []}]})  # sin starts previos -> pitcher_form_last5 queda None, no crashea
        return _fail("stats_type inesperado en test")

    monkeypatch.setattr(MlbConnector, "get_person_stats", fake_get_person_stats)
    monkeypatch.setattr(
        MlbConnector, "get_person_handedness_splits", lambda self, person_id, group="pitching": _ok(_handedness_splits_payload())
    )
    monkeypatch.setattr(
        MlbConnector, "get_injured_list_roster", lambda self, team_id: _ok({"roster": []})
    )
    monkeypatch.setattr(
        MlbConnector,
        "get_team_stats",
        lambda self, team_id, group="hitting", stats_type="season": _ok(_team_hitting_payload()),
    )
    _patch_kalshi_down(monkeypatch)

    result = run_mlb_pipeline(
        "2026-07-21",
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        fetch_boxscore=False,
        fetch_pitcher_stats=True,
    )

    assert len(result.records) == 1
    record = result.records[0]

    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    assert len(feature_snapshots) == 1
    snap = feature_snapshots[0]
    assert snap["feature_set_version"] == CURRENT_FEATURE_SET_VERSION

    features = json.loads(snap["features_json"])

    # pitcher_era_season: viene del season stat mockeado -> valor real, no None.
    assert features["pitcher_era_season"]["participant_a"] == 3.50
    assert features["pitcher_era_season"]["participant_b"] == 3.50

    # team_ops_season: viene del team_hitting_stat mockeado -> valor real.
    assert features["team_ops_season"]["participant_a"] == 0.750

    # Limitaciones deliberadas del Bloque 2 (documentadas, no bugs):
    # bullpen deshabilitado -> None; sin lineup confirmado -> handedness
    # ops en None pese a tener splits (falta opponent_dominant_hand);
    # sin key_player_ids -> il_flag en None.
    assert features["bullpen_era_recent"]["participant_a"] is None
    assert features["pitcher_vs_opponent_handedness_ops"]["participant_a"] is None
    assert features["il_flag_key_players"]["participant_a"] is None

    missing_features = json.loads(snap["missing_features_json"])
    assert isinstance(missing_features, list)


def test_run_mlb_pipeline_fetch_features_false_skips_feature_snapshot(
    monkeypatch, tmp_repository, tmp_history_repository, mlb_schedule_sample
):
    """`fetch_features=False` es la vía explícita para conservar el
    snapshot histórico de mercado (Paso 0c/0d) sin pagar el costo de
    features -- ambos siguen siendo independientes."""
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(mlb_schedule_sample)
    )
    _patch_kalshi_down(monkeypatch)

    result = run_mlb_pipeline(
        "2026-07-21",
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        fetch_boxscore=False,
        fetch_pitcher_stats=False,
        fetch_features=False,
    )

    assert len(result.records) == 1
    event_id = result.records[0].event_id
    assert tmp_history_repository.get_snapshots_for_event(event_id)  # snapshot de mercado sigue ocurriendo
    assert tmp_history_repository.get_feature_snapshots_for_event(event_id) == []  # pero sin features
