"""Regresión: `get_events_for_sport` solo pedía una página (hasta `limit`
eventos) e ignoraba el `cursor` de paginación de Kalshi. Con una serie que
tenga más eventos abiertos que el límite, el matching operaba en silencio
sobre un subconjunto incompleto. `get_all_events_for_sport` debe seguir el
cursor hasta agotarlo (o hasta `max_pages`, para no hacer un loop agresivo).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.kalshi import KalshiConnector


def _page_result(events, cursor=None):
    return FetchResult(
        ok=True,
        status_code=200,
        data={"events": events, "cursor": cursor},
        error=None,
        url="x",
        capture_ts=datetime.now(timezone.utc),
    )


def test_get_all_events_follows_cursor_across_pages(monkeypatch):
    pages = [
        _page_result([{"event_ticker": "A"}, {"event_ticker": "B"}], cursor="cursor1"),
        _page_result([{"event_ticker": "C"}], cursor="cursor2"),
        _page_result([{"event_ticker": "D"}], cursor=None),
    ]
    calls = []

    def fake_get_events(self, series_ticker, status="open", with_nested_markets=True, limit=200, cursor=None):
        calls.append(cursor)
        return pages[len(calls) - 1]

    monkeypatch.setattr(KalshiConnector, "get_events", fake_get_events)
    kalshi = KalshiConnector()
    result = kalshi.get_all_events_for_sport("MLB")

    assert result.ok is True
    tickers = [e["event_ticker"] for e in result.data["events"]]
    assert tickers == ["A", "B", "C", "D"]
    assert calls == [None, "cursor1", "cursor2"]


def test_get_all_events_stops_at_max_pages_never_loops_forever(monkeypatch):
    def fake_get_events(self, series_ticker, status="open", with_nested_markets=True, limit=200, cursor=None):
        # cursor SIEMPRE presente -> sin el tope de max_pages esto sería un
        # loop infinito.
        return _page_result([{"event_ticker": "X"}], cursor="always-more")

    monkeypatch.setattr(KalshiConnector, "get_events", fake_get_events)
    kalshi = KalshiConnector()
    result = kalshi.get_all_events_for_sport("MLB", max_pages=3)

    assert result.ok is True
    assert len(result.data["events"]) == 3


def test_get_all_events_preserves_partial_results_on_mid_pagination_failure(monkeypatch):
    pages = [
        _page_result([{"event_ticker": "A"}], cursor="cursor1"),
        FetchResult(ok=False, status_code=500, data=None, error="http_500", url="x", capture_ts=datetime.now(timezone.utc)),
    ]
    calls = []

    def fake_get_events(self, series_ticker, status="open", with_nested_markets=True, limit=200, cursor=None):
        calls.append(cursor)
        return pages[len(calls) - 1]

    monkeypatch.setattr(KalshiConnector, "get_events", fake_get_events)
    kalshi = KalshiConnector()
    result = kalshi.get_all_events_for_sport("MLB")

    assert result.ok is False
    assert "paginacion_incompleta" in result.error
    # lo ya obtenido en páginas previas NO se descarta silenciosamente
    assert [e["event_ticker"] for e in result.data["events"]] == ["A"]


def test_get_all_events_single_page_when_no_cursor(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_events",
        lambda self, series_ticker, status="open", with_nested_markets=True, limit=200, cursor=None: _page_result(
            [{"event_ticker": "A"}, {"event_ticker": "B"}], cursor=None
        ),
    )
    kalshi = KalshiConnector()
    result = kalshi.get_all_events_for_sport("ATP")
    assert len(result.data["events"]) == 2
