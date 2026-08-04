"""Tests de `src.api.main` (Fase 5) -- capa de transporte HTTP. Ver
`HTTP_SERVICE_SPEC.md` §1 y `ROBINHOOD_KALSHI_MAPPER_SPEC.md` §5.
`analyze_ticker`/`map_robinhood_symbol_to_kalshi_ticker` (ya probados en
`test_analysis_service.py`/`test_robinhood_mapper.py`) se monkeypatchean
-- este archivo prueba únicamente que los códigos HTTP/formas de
respuesta son correctos."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import src.api.main as main_module
from src.api.event_resolver import ResolverError
from src.api.robinhood_mapper import MappingError, MappingResult
from src.api.schemas import AnalyzeResponse, Freshness, UncertaintyBreakdown
from src.models.schemas import Sport

client = TestClient(main_module.app)

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _sample_response() -> AnalyzeResponse:
    return AnalyzeResponse(
        ticker="KXMLBGAME-TEST-A",
        event_id="mlb_test_1",
        sport="MLB",
        participant_a="Team A",
        participant_b="Team B",
        p_model=0.55,
        p_market=0.45,
        p_consensus_no_vig=None,
        p_consensus_no_vig_unavailable_reason="no disponible",
        edge=0.10,
        ev_bruto=0.05,
        ev_neto=None,
        net_ev_status="UNKNOWN",
        recommendation="WATCH",
        recommendation_reasons=["ELIGIBLE_AND_SCORED: por debajo del umbral global"],
        uncertainty=UncertaintyBreakdown(aggregate_confidence=60.0),
        most_influential_variables=[],
        model_version=None,
        calibration_version=None,
        policy_version="mlb_v1",
        feature_schema_version="phase2_registry_v1",
        freshness=Freshness(analysis_timestamp=NOW, market_timestamp=NOW, data_freshness_seconds=0.3),
        enrichment_mode="full",
        processing_time_ms=42.0,
    )


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_happy_path(monkeypatch):
    monkeypatch.setattr(main_module, "analyze_ticker", lambda ticker: _sample_response())

    response = client.get("/analyze/KXMLBGAME-TEST-A")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "KXMLBGAME-TEST-A"
    assert body["recommendation"] == "WATCH"
    assert body["p_consensus_no_vig"] is None
    assert "freshness" in body
    assert body["freshness"]["data_freshness_seconds"] == 0.3


def test_analyze_resolver_error_translates_to_matching_status_code(monkeypatch):
    def raise_resolver_error(ticker):
        raise ResolverError(404, f"ticker {ticker!r} no encontrado")

    monkeypatch.setattr(main_module, "analyze_ticker", raise_resolver_error)

    response = client.get("/analyze/KXMLBGAME-DOES-NOT-EXIST")

    assert response.status_code == 404
    assert "no encontrado" in response.json()["detail"]


def test_analyze_unexpected_exception_returns_502_not_a_fabricated_200(monkeypatch):
    def raise_unexpected(ticker):
        raise RuntimeError("fallo real de conector")

    monkeypatch.setattr(main_module, "analyze_ticker", raise_unexpected)

    response = client.get("/analyze/KXMLBGAME-TEST-A")

    assert response.status_code == 502
    assert "fallo real de conector" in response.json()["detail"]


def _sample_mapping_result() -> MappingResult:
    return MappingResult(
        kalshi_ticker="KXMLBGAME-26AUG03WSHPHI-WSH",
        strategy="exact",
        candidate="KXMLBGAME-26AUG03WSHPHI-WSH",
        sport=Sport.MLB,
        sport_key="MLB",
    )


def test_map_robinhood_happy_path(monkeypatch):
    calls = []

    def fake_map(symbol, robinhood_start_time=None, repository=None, kalshi_connector=None):
        calls.append((symbol, robinhood_start_time))
        return _sample_mapping_result()

    monkeypatch.setattr(main_module, "map_robinhood_symbol_to_kalshi_ticker", fake_map)

    response = client.post("/map/robinhood", json={"symbol": "MLBGAME-26AUG03WSHPHI-WSH"})

    assert response.status_code == 200
    body = response.json()
    assert body["kalshi_ticker"] == "KXMLBGAME-26AUG03WSHPHI-WSH"
    assert body["strategy"] == "exact"
    assert body["candidate"] == "KXMLBGAME-26AUG03WSHPHI-WSH"
    assert body["sport"] == "MLB"
    assert body["sport_key"] == "MLB"
    assert calls == [("MLBGAME-26AUG03WSHPHI-WSH", None)]


def test_map_robinhood_forwards_optional_game_start(monkeypatch):
    calls = []

    def fake_map(symbol, robinhood_start_time=None, repository=None, kalshi_connector=None):
        calls.append((symbol, robinhood_start_time))
        return _sample_mapping_result()

    monkeypatch.setattr(main_module, "map_robinhood_symbol_to_kalshi_ticker", fake_map)

    response = client.post(
        "/map/robinhood",
        json={"symbol": "MLBGAME-26AUG03WSHPHI-WSH", "game_start": "2026-08-03T19:00:00Z"},
    )

    assert response.status_code == 200
    assert calls[0][1] == datetime(2026, 8, 3, 19, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("status_code", [400, 404, 409, 502])
def test_map_robinhood_mapping_error_translates_to_matching_status_code(monkeypatch, status_code):
    def raise_mapping_error(symbol, robinhood_start_time=None, repository=None, kalshi_connector=None):
        raise MappingError(status_code, f"error real de mapeo para {symbol!r}")

    monkeypatch.setattr(main_module, "map_robinhood_symbol_to_kalshi_ticker", raise_mapping_error)

    response = client.post("/map/robinhood", json={"symbol": "MLBGAME-BAD"})

    assert response.status_code == status_code
    assert "error real de mapeo" in response.json()["detail"]


def test_map_robinhood_unexpected_exception_returns_502_not_a_fabricated_200(monkeypatch):
    def raise_unexpected(symbol, robinhood_start_time=None, repository=None, kalshi_connector=None):
        raise RuntimeError("fallo real de conector")

    monkeypatch.setattr(main_module, "map_robinhood_symbol_to_kalshi_ticker", raise_unexpected)

    response = client.post("/map/robinhood", json={"symbol": "MLBGAME-26AUG03WSHPHI-WSH"})

    assert response.status_code == 502
    assert "fallo real de conector" in response.json()["detail"]


def test_map_robinhood_missing_symbol_returns_422():
    response = client.post("/map/robinhood", json={})

    assert response.status_code == 422
