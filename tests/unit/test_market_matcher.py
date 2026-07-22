from datetime import datetime, timedelta, timezone

from src.connectors.kalshi import KalshiConnector
from src.matching.market_matcher import apply_kalshi_match, find_best_kalshi_event
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
