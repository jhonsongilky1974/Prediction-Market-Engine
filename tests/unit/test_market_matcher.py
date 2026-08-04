from datetime import datetime, timedelta, timezone

import pytest

from src.connectors.kalshi import KalshiConnector
from src.matching.market_matcher import (
    _kalshi_event_start_time,
    _start_time_from_ticker,
    apply_kalshi_match,
    find_best_kalshi_event,
    local_date_from_kalshi_ticker,
)
from src.models.schemas import MatchMethod, NormalizedRecord, Sport


def test_find_best_kalshi_event_matches_and_selects_market(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    result = find_best_kalshi_event(
        "Daniel Merida", "Kyrian Jacquet", start, events, tolerance_minutes=240
    )
    assert result.kalshi_event is not None
    assert result.match_result.method in (MatchMethod.EXACT_NAME_TIME, MatchMethod.FUZZY_NAME_TIME)
    assert result.selected_market["ticker"] == "KXATPMATCH-26JUL21MERJAC-MER"


def test_find_best_kalshi_event_selects_correct_side_when_swapped(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    # participant_a es Jacquet en la fuente -> el mercado seleccionado debe
    # seguir correspondiendo al lado YES de Jacquet, no al de Merida.
    result = find_best_kalshi_event("Kyrian Jacquet", "Daniel Merida", start, events, tolerance_minutes=240)
    assert result.selected_market["yes_sub_title"] != "Daniel Merida"


def test_find_best_kalshi_event_no_candidates_returns_no_match():
    result = find_best_kalshi_event("A", "B", None, [])
    assert result.kalshi_event is None
    assert result.match_result.method == MatchMethod.NO_MATCH
    assert result.match_result.needs_review is True


# --- Regresión: `find_best_kalshi_event` siempre devuelve el "mejor
# candidato disponible" aunque sea malísimo (para diagnóstico). El bug real
# estaba en los pipelines, que adjuntaban ese candidato al registro como si
# fuera un match confirmado sin comprobar la confianza. `apply_kalshi_match`
# es el punto único que ambos pipelines deben usar para esa decisión.

def test_apply_kalshi_match_needs_review_never_attaches_market_data(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    # nombres completamente ajenos al fixture -> el "mejor" candidato
    # disponible será de confianza muy baja / NEEDS_REVIEW.
    far_off_time = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc) + timedelta(days=30)
    match = find_best_kalshi_event(
        "Unrelated Player One", "Unrelated Player Two", far_off_time, events, tolerance_minutes=240
    )
    assert not match.match_result.is_confident

    record = NormalizedRecord(sport=Sport.TENNIS, event_id="e1")
    missing: list = []
    apply_kalshi_match(record, match, missing)

    assert record.market_id is None
    assert record.market.yes_bid is None
    assert record.market.yes_ask is None
    assert record.market_close_time is None
    assert record.expected_settlement_time is None
    assert "market_id" in missing
    assert "market.yes_bid" in missing
    assert record.data_quality.needs_review is True
    # el candidato descartado queda documentado, no oculto
    assert any("NO confirmado" in w for w in record.data_quality.match_warnings)


def test_apply_kalshi_match_confident_attaches_real_bid_ask(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    match = find_best_kalshi_event("Daniel Merida", "Kyrian Jacquet", start, events, tolerance_minutes=240)
    assert match.match_result.is_confident

    record = NormalizedRecord(sport=Sport.TENNIS, event_id="e2")
    missing: list = []
    apply_kalshi_match(record, match, missing)

    assert record.market_id == "KXATPMATCH-26JUL21MERJAC-MER"
    assert record.market.yes_bid == 0.69
    assert record.market.yes_ask == 0.7
    assert "market_id" not in missing


def test_apply_kalshi_match_flags_unexpected_kalshi_schema(kalshi_atp_events_sample):
    """Regresión: `validate_schema_sanity` existía pero no se invocaba desde
    ningún pipeline -- un cambio de schema de Kalshi (API no documentada,
    ver kalshi.py) no generaba ninguna señal de alerta."""
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    # simula un cambio de schema: desaparece el campo de precio yes_ask_dollars
    del events[0]["markets"][0]["yes_ask_dollars"]

    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    match = find_best_kalshi_event("Daniel Merida", "Kyrian Jacquet", start, events, tolerance_minutes=240)
    assert match.match_result.is_confident

    record = NormalizedRecord(sport=Sport.TENNIS, event_id="e3")
    missing: list = []
    apply_kalshi_match(record, match, missing)

    assert any("cambio de schema" in e and "yes_ask_dollars" in e for e in record.data_quality.validation_errors)


# --- Resolución de D-2 (Fase 3, ver CONTINUITY.md): la confianza de
# selección de lado YES, antes calculada y descartada dentro de
# _select_market, ahora se expone en KalshiEventMatch.market_selection_confidence
# y se persiste en DataQuality.side_selection_confidence. Extensión
# aditiva -- ningún test de arriba se modificó.


def test_find_best_kalshi_event_exposes_market_selection_confidence(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    result = find_best_kalshi_event(
        "Daniel Merida", "Kyrian Jacquet", start, events, tolerance_minutes=240
    )
    assert result.market_selection_confidence is not None
    assert 0.0 <= result.market_selection_confidence <= 1.0
    # nombre exacto (mismo texto que yes_sub_title) -> similitud máxima
    assert result.market_selection_confidence == pytest.approx(1.0)


def test_apply_kalshi_match_confident_populates_side_selection_confidence(kalshi_atp_events_sample):
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    match = find_best_kalshi_event("Daniel Merida", "Kyrian Jacquet", start, events, tolerance_minutes=240)

    record = NormalizedRecord(sport=Sport.TENNIS, event_id="e4")
    apply_kalshi_match(record, match, [])

    assert record.data_quality.side_selection_confidence == pytest.approx(1.0)


def test_apply_kalshi_match_needs_review_leaves_side_selection_confidence_none(kalshi_atp_events_sample):
    """Cuando el match de EVENTO no es confidente, no se adjunta ningún
    dato de mercado (regla ya existente) -- side_selection_confidence
    tampoco se puebla, coherente con que ningún otro campo dependiente
    del mercado se puebla en ese caso."""
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    far_off_time = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc) + timedelta(days=30)
    match = find_best_kalshi_event(
        "Unrelated Player One", "Unrelated Player Two", far_off_time, events, tolerance_minutes=240
    )

    record = NormalizedRecord(sport=Sport.TENNIS, event_id="e5")
    apply_kalshi_match(record, match, [])

    assert record.data_quality.side_selection_confidence is None


def test_market_selection_confidence_none_when_participant_a_missing(kalshi_atp_events_sample):
    """participant_a ausente -> _select_market toma markets[0] a ciegas,
    sin comparar nada -- no hay una puntuación real que reportar."""
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    result = find_best_kalshi_event(None, "Kyrian Jacquet", start, events, tolerance_minutes=240)
    if result.selected_market is not None:
        assert result.market_selection_confidence is None


# --- Regresión real (2026-08-03, ver CONTINUITY.md §0.31): `occurrence_datetime`
# de un mercado de Kalshi que TODAVÍA no ocurrió es un valor de LIQUIDACIÓN
# esperada (idéntico a `expected_expiration_time`, documentado así por Kalshi:
# "The recorded datetime when the underlying event occurred, IF AVAILABLE"),
# no el inicio real del partido. Verificado en vivo contra los 8 partidos MLB
# abiertos el 2026-08-03: los 8 tenían `occurrence_datetime` exactamente
# +180min (duración típica asumida de un partido) respecto al `start_time`
# real de MLB Stats API -- suficiente para exceder siempre
# EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["MLB"] (90min) y bloquear la
# confirmación del match pese a que el nombre coincidía exacto. Esto rompía
# /analyze para CUALQUIER ticker MLB recién resuelto (por el mapeador
# Robinhood o de cualquier otra forma) -- no solo para el flujo de Robinhood.


def test_start_time_from_ticker_matches_real_mlb_start_time():
    """`26AUG031840` -> 2026-08-03 18:40 hora del este de EE.UU. (EDT,
    UTC-4) -> 2026-08-03T22:40:00Z -- verificado idéntico al `start_time`
    real de MLB Stats API para este mismo partido (Washington @
    Philadelphia, 2026-08-03)."""
    assert _start_time_from_ticker("KXMLBGAME-26AUG031840WSHPHI-WSH") == datetime(
        2026, 8, 3, 22, 40, tzinfo=timezone.utc
    )


def test_start_time_from_ticker_crosses_midnight_utc_correctly():
    """`26AUG032140` (21:40 ET) -> 2026-08-04T01:40:00Z -- el mismo caso
    real que motivó este fix: el ticker "dice" 03AUG pero el partido
    cruza a las 01:40 UTC del día siguiente en horario UTC."""
    assert _start_time_from_ticker("KXMLBGAME-26AUG032140SDAZ-SD") == datetime(
        2026, 8, 4, 1, 40, tzinfo=timezone.utc
    )


def test_start_time_from_ticker_none_without_time_segment():
    """Tickers reales de tenis (KXATPMATCH/KXWTAMATCH) no embeben hora --
    el llamador debe caer de vuelta a `occurrence_datetime`, comportamiento
    sin cambios respecto a antes de este fix."""
    assert _start_time_from_ticker("KXATPMATCH-26AUG01ATMDRA-ATM") is None


@pytest.mark.parametrize("ticker", [None, "", "not-a-real-ticker", "KXMLBGAME-26AUG03-WSH-EXTRA"])
def test_start_time_from_ticker_none_for_malformed_input(ticker):
    assert _start_time_from_ticker(ticker) is None


def test_local_date_from_kalshi_ticker():
    assert local_date_from_kalshi_ticker("KXMLBGAME-26AUG031840WSHPHI-WSH") == (2026, 8, 3)


def test_local_date_from_kalshi_ticker_works_without_time_segment():
    """La fecha no depende del segmento de hora (opcional) -- solo del
    segmento de fecha, siempre presente."""
    assert local_date_from_kalshi_ticker("KXATPMATCH-26AUG01ATMDRA-ATM") == (2026, 8, 1)


@pytest.mark.parametrize("ticker", [None, "", "garbage", "KXMLBGAME-13FOO03WSHPHI-WSH"])
def test_local_date_from_kalshi_ticker_none_for_malformed_input(ticker):
    assert local_date_from_kalshi_ticker(ticker) is None


def test_kalshi_event_start_time_prefers_ticker_over_misleading_occurrence_datetime():
    """Caso real reproducido: `occurrence_datetime` "adelantado" +180min
    (valor de liquidación esperada) -- `_kalshi_event_start_time` debe
    devolver la hora derivada del ticker, no la de `occurrence_datetime`."""
    event = {
        "title": "Washington vs Philadelphia",
        "markets": [
            {
                "ticker": "KXMLBGAME-26AUG031840WSHPHI-WSH",
                "yes_sub_title": "Washington",
                "occurrence_datetime": "2026-08-04T01:40:00Z",
            }
        ],
    }
    assert _kalshi_event_start_time(event) == datetime(2026, 8, 3, 22, 40, tzinfo=timezone.utc)


def test_kalshi_event_start_time_falls_back_to_occurrence_datetime_without_ticker_time():
    """Sin segmento de hora en el ticker (ej. tenis), el comportamiento
    sigue siendo exactamente el de antes de este fix: se usa
    `occurrence_datetime` tal cual."""
    event = {
        "title": "Player A vs Player B",
        "markets": [
            {
                "ticker": "KXATPMATCH-26AUG01AAABBB-AAA",
                "yes_sub_title": "Player A",
                "occurrence_datetime": "2026-08-01T17:00:00Z",
            }
        ],
    }
    assert _kalshi_event_start_time(event) == datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc)


def test_find_best_kalshi_event_confident_despite_misleading_occurrence_datetime():
    """Regresión end-to-end del bug real (ver CONTINUITY.md §0.31): antes
    de este fix, esto daba NEEDS_REVIEW (diferencia temporal 180min >
    tolerancia 90min) pese a que el nombre del equipo coincide exacto --
    exactamente la causa raíz de que /analyze devolviera 404 justo
    después de que el mapeador Robinhood resolviera el ticker correcto."""
    events = [
        {
            "title": "Washington vs Philadelphia",
            "markets": [
                {
                    "ticker": "KXMLBGAME-26AUG031840WSHPHI-WSH",
                    "yes_sub_title": "Washington",
                    "occurrence_datetime": "2026-08-04T01:40:00Z",
                }
            ],
        }
    ]
    real_mlb_start_time = datetime(2026, 8, 3, 22, 40, tzinfo=timezone.utc)  # real, de MLB Stats API

    result = find_best_kalshi_event(
        "Washington Nationals", "Philadelphia Phillies", real_mlb_start_time, events, tolerance_minutes=90
    )

    assert result.match_result.method == MatchMethod.EXACT_NAME_TIME
    assert result.match_result.is_confident
    assert result.selected_market["ticker"] == "KXMLBGAME-26AUG031840WSHPHI-WSH"


def test_find_best_kalshi_event_skips_malformed_candidate_without_crashing(kalshi_atp_events_sample):
    """Un único evento de Kalshi con forma inesperada no debe tumbar el
    matching de todo el lote (schema-drift puntual en una API no
    documentada)."""
    events = KalshiConnector.extract_events(kalshi_atp_events_sample)
    malformed = {"title": "Broken Event", "markets": "not-a-list-of-dicts"}
    start = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)

    result = find_best_kalshi_event(
        "Daniel Merida", "Kyrian Jacquet", start, [malformed] + events, tolerance_minutes=240
    )

    assert result.kalshi_event is not None
    assert result.selected_market["ticker"] == "KXATPMATCH-26JUL21MERJAC-MER"
