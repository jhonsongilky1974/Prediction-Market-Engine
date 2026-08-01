"""Tests de `src.api.event_resolver` (Fase 5). Ver `HTTP_SERVICE_SPEC.md`.

Sin red real: `KalshiConnector.get_all_events_for_sport` y
`run_mlb_pipeline`/`run_tennis_pipeline` (ya probados exhaustivamente en
sus propios archivos de test) se monkeypatchean -- este archivo prueba
únicamente la lógica NUEVA de este paso (resolución de ticker -> fecha/
sport/registro), no vuelve a probar el pipeline ni el matcher.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.api import event_resolver as resolver_module
from src.api.event_resolver import ResolverError, _date_from_market, _find_market, _sport_and_tour_for_ticker, resolve_ticker
from src.connectors.base_client import FetchResult
from src.connectors.kalshi import KalshiConnector
from src.models.schemas import NormalizedRecord, Sport


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


_MLB_EVENT = {
    "event_ticker": "KXMLBGAME-26AUG01LAADET",
    "title": "LA Angels vs Detroit",
    "markets": [
        {"ticker": "KXMLBGAME-26AUG01LAADET-LAA", "yes_sub_title": "LA Angels", "occurrence_datetime": "2026-08-01T19:00:00Z"},
        {"ticker": "KXMLBGAME-26AUG01LAADET-DET", "yes_sub_title": "Detroit", "occurrence_datetime": "2026-08-01T19:00:00Z"},
    ],
}


# ---------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "ticker,expected_sport,expected_tour,expected_sport_key",
    [
        ("KXMLBGAME-26AUG01LAADET-LAA", Sport.MLB, None, "MLB"),
        ("KXATPMATCH-TEST-A", Sport.TENNIS, "atp", "ATP"),
        ("KXWTAMATCH-TEST-A", Sport.TENNIS, "wta", "WTA"),
    ],
)
def test_sport_and_tour_for_ticker(ticker, expected_sport, expected_tour, expected_sport_key):
    sport, tour, sport_key = _sport_and_tour_for_ticker(ticker)
    assert sport == expected_sport
    assert tour == expected_tour
    assert sport_key == expected_sport_key


def test_sport_and_tour_for_unsupported_series_raises_400():
    with pytest.raises(ResolverError) as exc_info:
        _sport_and_tour_for_ticker("KXNFLGAME-TEST-A")
    assert exc_info.value.status_code == 400


def test_find_market_locates_exact_ticker():
    event, market = _find_market("KXMLBGAME-26AUG01LAADET-LAA", [_MLB_EVENT])
    assert event is _MLB_EVENT
    assert market["ticker"] == "KXMLBGAME-26AUG01LAADET-LAA"


def test_find_market_rejects_event_ticker_with_400_and_lists_markets():
    with pytest.raises(ResolverError) as exc_info:
        _find_market("KXMLBGAME-26AUG01LAADET", [_MLB_EVENT])
    assert exc_info.value.status_code == 400
    assert "KXMLBGAME-26AUG01LAADET-LAA" in exc_info.value.detail


def test_find_market_not_found_raises_404():
    with pytest.raises(ResolverError) as exc_info:
        _find_market("KXMLBGAME-DOES-NOT-EXIST", [_MLB_EVENT])
    assert exc_info.value.status_code == 404


def test_date_from_market_mlb_format():
    assert _date_from_market({"occurrence_datetime": "2026-08-01T19:00:00Z"}, Sport.MLB) == "2026-08-01"


def test_date_from_market_tennis_format():
    assert _date_from_market({"occurrence_datetime": "2026-08-01T19:00:00Z"}, Sport.TENNIS) == "20260801"


def test_date_from_market_missing_occurrence_raises_502():
    with pytest.raises(ResolverError) as exc_info:
        _date_from_market({}, Sport.MLB)
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------
# resolve_ticker -- glue completo, KalshiConnector.get_all_events_for_sport
# monkeypatcheado a nivel de clase, run_mlb_pipeline/run_tennis_pipeline
# monkeypatcheados a nivel de módulo (ya probados en sus propios archivos).
# ---------------------------------------------------------------------


def _record(market_id, event_id="mlb_1"):
    return NormalizedRecord(sport=Sport.MLB, event_id=event_id, market_id=market_id, participant_a="A", participant_b="B")


class _FakeMlbPipelineResult:
    def __init__(self, records, feature_inputs_list=None, feature_cutoffs=None):
        self.records = records
        self.feature_inputs_list = feature_inputs_list or [None] * len(records)
        self.feature_cutoffs = feature_cutoffs or [None] * len(records)


def test_resolve_ticker_happy_path(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({"events": [_MLB_EVENT]}),
    )
    matched_record = _record("KXMLBGAME-26AUG01LAADET-LAA")
    calls = {}

    def fake_run_mlb_pipeline(date, repository=None, history_repository=None):
        calls["date"] = date
        return _FakeMlbPipelineResult([matched_record])

    monkeypatch.setattr(resolver_module, "run_mlb_pipeline", fake_run_mlb_pipeline)

    resolved = resolve_ticker("KXMLBGAME-26AUG01LAADET-LAA")

    assert resolved.record is matched_record
    assert resolved.sport == Sport.MLB
    assert calls["date"] == "2026-08-01"  # derivado del occurrence_datetime del mercado, no adivinado
    assert resolved.market_capture_ts is not None
    assert resolved.enrichment_mode == "full"  # MLB no tiene lever de reducción


_ATP_EVENT = {
    "event_ticker": "KXATPMATCH-26AUG01AAABBB",
    "title": "Player A vs Player B",
    "markets": [
        {"ticker": "KXATPMATCH-26AUG01AAABBB-AAA", "yes_sub_title": "Player A", "occurrence_datetime": "2026-08-01T17:00:00Z"},
    ],
}


def test_resolve_ticker_tennis_disables_sofascore_enrichment_for_latency(monkeypatch):
    """Aprobado explícitamente por el usuario: enrich_sofascore=False
    (parámetro YA EXISTENTE de run_tennis_pipeline) SOLO en la vía en
    vivo de /analyze, tras medir >5min con enriquecimiento completo
    contra el volumen real de un día de ATP (349 partidos)."""
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({"events": [_ATP_EVENT]}),
    )
    matched_record = _record("KXATPMATCH-26AUG01AAABBB-AAA", event_id="espn_tennis_atp_1")
    calls = {}

    def fake_run_tennis_pipeline(tour, date, repository=None, history_repository=None, enrich_sofascore=True):
        calls["enrich_sofascore"] = enrich_sofascore
        return _FakeMlbPipelineResult([matched_record])

    monkeypatch.setattr(resolver_module, "run_tennis_pipeline", fake_run_tennis_pipeline)

    resolved = resolve_ticker("KXATPMATCH-26AUG01AAABBB-AAA")

    assert calls["enrich_sofascore"] is False
    assert resolved.enrichment_mode == "reduced"


def test_resolve_ticker_kalshi_down_raises_502(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi 429"),
    )
    with pytest.raises(ResolverError) as exc_info:
        resolve_ticker("KXMLBGAME-26AUG01LAADET-LAA")
    assert exc_info.value.status_code == 502
    assert "kalshi 429" in exc_info.value.detail


def test_resolve_ticker_no_confident_match_raises_404(monkeypatch):
    """El ticker existe en Kalshi, pero ningún registro del pipeline de esa
    fecha quedó con ese market_id (matcher existente no confidente) --
    debe reportarse honestamente, nunca fabricar un match."""
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({"events": [_MLB_EVENT]}),
    )
    unrelated_record = _record(market_id=None)  # match no confidente -> market_id nunca se puebla

    def fake_run_mlb_pipeline(date, repository=None, history_repository=None):
        return _FakeMlbPipelineResult([unrelated_record])

    monkeypatch.setattr(resolver_module, "run_mlb_pipeline", fake_run_mlb_pipeline)

    with pytest.raises(ResolverError) as exc_info:
        resolve_ticker("KXMLBGAME-26AUG01LAADET-LAA")
    assert exc_info.value.status_code == 404
