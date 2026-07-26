"""Tests unitarios de los métodos nuevos de `MlbConnector` (Paso 5b,
Bloque 1 -- ver PLAN_PHASE2.md §1.1). Sin red: se monkeypatchea
`BaseHttpClient.get_json` para capturar exactamente la URL/params
construidos, sin verificar contra la API real (eso es integración).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.connectors.base_client import BaseHttpClient, FetchResult
from src.connectors.mlb import MlbConnector


def _capture_get_json(monkeypatch):
    calls = []

    def fake_get_json(self, url, params=None, endpoint_label=None, extra_headers=None):
        calls.append({"url": url, "params": params, "endpoint_label": endpoint_label})
        return FetchResult(ok=True, status_code=200, data={}, error=None, url=url, capture_ts=datetime.now(timezone.utc))

    monkeypatch.setattr(BaseHttpClient, "get_json", fake_get_json)
    return calls


def test_get_person_handedness_splits_builds_correct_request(monkeypatch):
    calls = _capture_get_json(monkeypatch)
    mlb = MlbConnector()

    mlb.get_person_handedness_splits(12345)

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/people/12345/stats")
    assert calls[0]["params"] == {"stats": "statSplits", "sitCodes": "vr,vl", "group": "pitching"}


def test_get_injured_list_roster_builds_correct_request(monkeypatch):
    calls = _capture_get_json(monkeypatch)
    mlb = MlbConnector()

    mlb.get_injured_list_roster(114)

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/teams/114/roster")
    assert calls[0]["params"] == {"rosterType": "injuredList"}


def test_get_team_stats_builds_correct_request(monkeypatch):
    calls = _capture_get_json(monkeypatch)
    mlb = MlbConnector()

    mlb.get_team_stats(114)

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/teams/114/stats")
    assert calls[0]["params"] == {"stats": "season", "group": "hitting"}


def test_get_team_stats_respects_custom_group_and_stats_type(monkeypatch):
    calls = _capture_get_json(monkeypatch)
    mlb = MlbConnector()

    mlb.get_team_stats(114, group="pitching", stats_type="season")

    assert calls[0]["params"] == {"stats": "season", "group": "pitching"}


def test_existing_get_roster_and_get_person_stats_are_unaffected(monkeypatch):
    """Regresión: los métodos nuevos son aditivos -- get_roster y
    get_person_stats (Fase 1/Paso 2) deben seguir construyendo exactamente
    la misma request que antes."""
    calls = _capture_get_json(monkeypatch)
    mlb = MlbConnector()

    mlb.get_roster(114)
    mlb.get_person_stats(12345, group="pitching", stats_type="gameLog")

    assert calls[0]["params"] is None
    assert calls[0]["url"].endswith("/api/v1/teams/114/roster")
    assert calls[1]["params"] == {"stats": "gameLog", "group": "pitching"}
    assert calls[1]["url"].endswith("/api/v1/people/12345/stats")
