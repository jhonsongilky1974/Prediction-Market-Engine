"""Tests de `src.api.robinhood_mapper`. Ver `ROBINHOOD_KALSHI_MAPPER_SPEC.md`.

Sin red real: `KalshiConnector.get_all_events_for_sport` se
monkeypatchea -- este archivo prueba únicamente la lógica de mapeo
(symbol de Robinhood -> ticker de Kalshi verificado), no vuelve a probar
`find_best_kalshi_event`/`match_event` (ya probados en
`tests/unit/test_market_matcher.py`/`test_event_matcher.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.api.robinhood_mapper import (
    MappingError,
    _derive_opponent_code,
    _parse_symbol,
    _series_prefix_and_sport,
    map_robinhood_symbol_to_kalshi_ticker,
)
from src.connectors.base_client import FetchResult
from src.models.schemas import Sport


def _ok(events):
    return FetchResult(ok=True, status_code=200, data={"events": events}, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


class _StubKalshiConnector:
    """Sustituye a `KalshiConnector` real -- devuelve `result` fijo sin red,
    y registra con qué `sport_key` se llamó (para verificar que el
    mapeador consulta la serie correcta)."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def get_all_events_for_sport(self, sport_key, status="open"):
        self.calls.append((sport_key, status))
        return self._result

    @staticmethod
    def extract_events(data):
        from src.connectors.kalshi import KalshiConnector

        return KalshiConnector.extract_events(data)


_MLB_EVENT_NO_TIME = {
    "event_ticker": "KXMLBGAME-26AUG01LAADET",
    "title": "LA Angels vs Detroit",
    "markets": [
        {"ticker": "KXMLBGAME-26AUG01LAADET-LAA", "yes_sub_title": "LA Angels", "occurrence_datetime": "2026-08-01T19:00:00Z"},
        {"ticker": "KXMLBGAME-26AUG01LAADET-DET", "yes_sub_title": "Detroit", "occurrence_datetime": "2026-08-01T19:00:00Z"},
    ],
}

_MLB_EVENT_WITH_TIME = {
    "event_ticker": "KXMLBGAME-26AUG011507STLTOR",
    "title": "St Louis vs Toronto",
    "markets": [
        {"ticker": "KXMLBGAME-26AUG011507STLTOR-STL", "yes_sub_title": "St Louis", "occurrence_datetime": "2026-08-01T15:07:00Z"},
        {"ticker": "KXMLBGAME-26AUG011507STLTOR-TOR", "yes_sub_title": "Toronto", "occurrence_datetime": "2026-08-01T15:07:00Z"},
    ],
}

_WTA_EVENT = {
    "event_ticker": "KXWTAMATCH-26AUG02PEGEAL",
    "title": "Pegula vs Eala",
    "markets": [
        {"ticker": "KXWTAMATCH-26AUG02PEGEAL-PEG", "yes_sub_title": "Pegula", "occurrence_datetime": "2026-08-02T18:00:00Z"},
        {"ticker": "KXWTAMATCH-26AUG02PEGEAL-EAL", "yes_sub_title": "Eala", "occurrence_datetime": "2026-08-02T18:00:00Z"},
    ],
}


# ---------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------


def test_parse_symbol_splits_three_segments():
    assert _parse_symbol("MLBGAME-26AUG03WSHPHI-WSH") == ("MLBGAME", "26AUG03WSHPHI", "WSH")


@pytest.mark.parametrize("symbol", ["MLBGAME-26AUG03WSHPHI", "A-B-C-D", "onlyoneseg", "MLBGAME--WSH", "-26AUG03WSHPHI-WSH"])
def test_parse_symbol_rejects_malformed_input(symbol):
    with pytest.raises(MappingError) as exc_info:
        _parse_symbol(symbol)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "prefix,expected_series,expected_sport,expected_sport_key",
    [
        ("MLBGAME", "KXMLBGAME", Sport.MLB, "MLB"),
        ("KXMLBGAME", "KXMLBGAME", Sport.MLB, "MLB"),
        ("KXWTAMATCH", "KXWTAMATCH", Sport.TENNIS, "WTA"),
        ("ATPMATCH", "KXATPMATCH", Sport.TENNIS, "ATP"),
    ],
)
def test_series_prefix_and_sport(prefix, expected_series, expected_sport, expected_sport_key):
    series, sport, sport_key = _series_prefix_and_sport(prefix, symbol="x")
    assert series == expected_series
    assert sport == expected_sport
    assert sport_key == expected_sport_key


def test_series_prefix_and_sport_rejects_unsupported_series():
    with pytest.raises(MappingError) as exc_info:
        _series_prefix_and_sport("NFLGAME", symbol="NFLGAME-x-Y")
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "teams_part,side,expected",
    [
        ("WSHPHI", "WSH", "PHI"),
        ("WSHPHI", "PHI", "WSH"),
        ("PEGEAL", "PEG", "EAL"),
        ("ABCDEF", "ZZZ", None),
        ("", "WSH", None),
    ],
)
def test_derive_opponent_code(teams_part, side, expected):
    assert _derive_opponent_code(teams_part, side) == expected


# ---------------------------------------------------------------------
# map_robinhood_symbol_to_kalshi_ticker -- estrategia 1: EXACT
# ---------------------------------------------------------------------


def test_exact_match_tennis_symbol_already_has_kx_prefix():
    stub = _StubKalshiConnector(_ok([_WTA_EVENT]))
    result = map_robinhood_symbol_to_kalshi_ticker("KXWTAMATCH-26AUG02PEGEAL-PEG", kalshi_connector=stub)
    assert result.strategy == "exact"
    assert result.kalshi_ticker == "KXWTAMATCH-26AUG02PEGEAL-PEG"
    assert result.sport == Sport.TENNIS
    assert stub.calls == [("WTA", "open")]


def test_exact_match_mlb_symbol_without_kx_prefix():
    stub = _StubKalshiConnector(_ok([_MLB_EVENT_NO_TIME]))
    result = map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01LAADET-LAA", kalshi_connector=stub)
    assert result.strategy == "exact"
    assert result.kalshi_ticker == "KXMLBGAME-26AUG01LAADET-LAA"
    assert result.sport == Sport.MLB
    assert stub.calls == [("MLB", "open")]


# ---------------------------------------------------------------------
# estrategia 2: SUBSTRING (ticker Kalshi real con segmento de hora que
# Robinhood no expone)
# ---------------------------------------------------------------------


def test_substring_match_when_kalshi_ticker_has_time_segment():
    stub = _StubKalshiConnector(_ok([_MLB_EVENT_WITH_TIME]))
    result = map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01STLTOR-STL", kalshi_connector=stub)
    assert result.strategy == "substring"
    assert result.kalshi_ticker == "KXMLBGAME-26AUG011507STLTOR-STL"
    assert result.candidate == "KXMLBGAME-26AUG01STLTOR-STL"


def test_substring_match_ambiguous_raises_409():
    doubleheader_game_2 = {
        "event_ticker": "KXMLBGAME-26AUG012207STLTOR",
        "title": "St Louis vs Toronto (game 2)",
        "markets": [
            {"ticker": "KXMLBGAME-26AUG012207STLTOR-STL", "yes_sub_title": "St Louis", "occurrence_datetime": "2026-08-01T22:07:00Z"},
        ],
    }
    stub = _StubKalshiConnector(_ok([_MLB_EVENT_WITH_TIME, doubleheader_game_2]))
    with pytest.raises(MappingError) as exc_info:
        map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01STLTOR-STL", kalshi_connector=stub)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------
# estrategia 3: EVENT_MATCHER (último recurso)
# ---------------------------------------------------------------------


def test_event_matcher_fallback_used_when_exact_and_substring_fail():
    # yes_sub_title coincide exactamente con los códigos de 3 letras
    # (caso favorable, no representativo del texto real de Kalshi -- ver
    # limitación documentada en el docstring del módulo) para verificar
    # que la estrategia 3 queda correctamente cableada.
    event_with_matching_titles = {
        "event_ticker": "KXMLBGAME-26AUG05NYYBOS",
        "title": "NYY vs BOS",
        "markets": [
            {"ticker": "KXMLBGAME-26AUG05NYYBOS-NYY", "yes_sub_title": "NYY", "occurrence_datetime": "2026-08-05T23:00:00Z"},
            {"ticker": "KXMLBGAME-26AUG05NYYBOS-BOS", "yes_sub_title": "BOS", "occurrence_datetime": "2026-08-05T23:00:00Z"},
        ],
    }
    # symbol con fecha DISTINTA a la del evento Kalshi -> exact y
    # substring fallan ambos, solo event_matcher (que no exige igualdad
    # de fecha, solo tolerancia) puede resolverlo.
    stub = _StubKalshiConnector(_ok([event_with_matching_titles]))
    result = map_robinhood_symbol_to_kalshi_ticker(
        "MLBGAME-26AUG06NYYBOS-NYY",
        robinhood_start_time=datetime(2026, 8, 5, 23, 0, tzinfo=timezone.utc),
        kalshi_connector=stub,
    )
    assert result.strategy == "event_matcher"
    assert result.kalshi_ticker == "KXMLBGAME-26AUG05NYYBOS-NYY"


def test_event_matcher_uses_tennis_tolerance_not_generic_mlb_default():
    """Regresión real encontrada en auditoría (ver CONTINUITY.md): la
    llamada a find_best_kalshi_event en esta estrategia omitía
    tolerance_minutes -- caía al default genérico de la función (90min,
    el valor de MLB), nunca el de tenis (240min,
    EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT, ya usado correctamente
    en tennis_pipeline.py). Un desfase de 150min entre
    robinhood_start_time y occurrence_datetime -- legítimo en tenis
    ("orden de salida a pista", ver config/settings.py) -- solo se
    resuelve con la tolerancia correcta; con el bug (90min) esto habría
    dado NEEDS_REVIEW y terminado en 404."""
    event = {
        "event_ticker": "KXWTAMATCH-26AUG02PEGEAL",
        "title": "Pegula vs Eala",
        "markets": [
            {"ticker": "KXWTAMATCH-26AUG02PEGEAL-PEG", "yes_sub_title": "Pegula", "occurrence_datetime": "2026-08-02T18:00:00Z"},
            {"ticker": "KXWTAMATCH-26AUG02PEGEAL-EAL", "yes_sub_title": "Eala", "occurrence_datetime": "2026-08-02T18:00:00Z"},
        ],
    }
    stub = _StubKalshiConnector(_ok([event]))
    # symbol con fecha DISTINTA (03 en vez de 02) -> exact y substring
    # fallan, solo event_matcher puede resolverlo.
    result = map_robinhood_symbol_to_kalshi_ticker(
        "WTAMATCH-26AUG03PEGEAL-PEG",
        robinhood_start_time=datetime(2026, 8, 2, 20, 30, tzinfo=timezone.utc),  # +150min vs occurrence_datetime
        kalshi_connector=stub,
    )
    assert result.strategy == "event_matcher"
    assert result.kalshi_ticker == "KXWTAMATCH-26AUG02PEGEAL-PEG"


def test_all_strategies_fail_raises_404():
    stub = _StubKalshiConnector(_ok([_WTA_EVENT]))
    with pytest.raises(MappingError) as exc_info:
        map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01LAADET-LAA", kalshi_connector=stub)
    assert exc_info.value.status_code == 404


def test_no_opponent_derivable_skips_event_matcher_and_still_raises_404():
    stub = _StubKalshiConnector(_ok([]))
    with pytest.raises(MappingError) as exc_info:
        map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01ZZZ-LAA", kalshi_connector=stub)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------
# Fallo real de Kalshi (502) y symbol inválido (400) de punta a punta
# ---------------------------------------------------------------------


def test_kalshi_fetch_failure_raises_502():
    stub = _StubKalshiConnector(_fail("timeout"))
    with pytest.raises(MappingError) as exc_info:
        map_robinhood_symbol_to_kalshi_ticker("MLBGAME-26AUG01LAADET-LAA", kalshi_connector=stub)
    assert exc_info.value.status_code == 502


def test_unsupported_series_raises_400_before_any_kalshi_call():
    stub = _StubKalshiConnector(_ok([]))
    with pytest.raises(MappingError) as exc_info:
        map_robinhood_symbol_to_kalshi_ticker("NFLGAME-26AUG01KCLV-KC", kalshi_connector=stub)
    assert exc_info.value.status_code == 400
    assert stub.calls == []
