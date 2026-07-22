from datetime import datetime, timedelta, timezone

from src.models.schemas import MarketData, NormalizedRecord, Sport
from src.quality.validators import (
    find_duplicate_markets,
    validate_bid_ask_consistency,
    validate_participants,
    validate_price_ranges,
    validate_staleness,
    validate_timestamps,
)


def test_validate_price_ranges_flags_out_of_bounds():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1", market=MarketData(yes_bid=1.5))
    errors = validate_price_ranges(r)
    assert any("fuera de rango" in e for e in errors)


def test_validate_price_ranges_ok_within_bounds():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1", market=MarketData(yes_bid=0.4, yes_ask=0.45))
    assert validate_price_ranges(r) == []


def test_validate_bid_ask_consistency_detects_inverted():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1", market=MarketData(yes_bid=0.7, yes_ask=0.5))
    errors = validate_bid_ask_consistency(r)
    assert any("yes_ask" in e and "yes_bid" in e for e in errors)


def test_validate_timestamps_close_before_start():
    t = datetime(2026, 7, 21, tzinfo=timezone.utc)
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1", start_time=t, market_close_time=t - timedelta(hours=1))
    errors = validate_timestamps(r)
    assert any("anterior a start_time" in e for e in errors)


def test_validate_participants_empty():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    errors = validate_participants(r)
    assert "participant_a vacío" in errors
    assert "participant_b vacío" in errors


def test_validate_participants_identical():
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1", participant_a="X", participant_b="X")
    errors = validate_participants(r)
    assert any("idénticos" in e for e in errors)


def test_validate_staleness_flags_old_source_capture():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    r.data_quality.source_timestamps = {"mlb": now - timedelta(hours=3)}
    errors = validate_staleness(r, now=now)
    assert any("antigüedad" in e for e in errors)


def test_validate_staleness_uses_oldest_source_not_last_updated():
    """Regresión: el pipeline estampa `last_updated` justo antes de validar
    (siempre "ahora"), así que comparar contra ese campo nunca detecta nada
    en producción. El check real debe mirar `source_timestamps` (cuándo se
    capturó cada fuente cruda), no `last_updated`."""
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    r.data_quality.last_updated = now  # como hace el pipeline real: "ahora"
    r.data_quality.source_timestamps = {"mlb": now - timedelta(hours=3)}
    errors = validate_staleness(r, now=now)
    assert any("antigüedad" in e for e in errors)


def test_validate_staleness_no_source_timestamps_no_error():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    assert validate_staleness(r, now=now) == []


def test_validate_staleness_fresh_data_no_error():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    r = NormalizedRecord(sport=Sport.MLB, event_id="e1")
    r.data_quality.source_timestamps = {"mlb": now - timedelta(minutes=1)}
    assert validate_staleness(r, now=now) == []


def test_find_duplicate_markets():
    r1 = NormalizedRecord(sport=Sport.MLB, event_id="e1", market_id="M1")
    r2 = NormalizedRecord(sport=Sport.MLB, event_id="e2", market_id="M1")
    errors = find_duplicate_markets([r1, r2])
    assert any("M1" in e for e in errors)


def test_annotate_duplicate_markets_writes_into_affected_records_only():
    """Regresión: `find_duplicate_markets` existía pero ningún pipeline lo
    invocaba nunca -- 'mercados duplicados' (criterio de aceptación
    explícito de Fase 1) no se detectaba en producción."""
    from src.quality.validators import annotate_duplicate_markets

    r1 = NormalizedRecord(sport=Sport.MLB, event_id="e1", market_id="M1")
    r2 = NormalizedRecord(sport=Sport.MLB, event_id="e2", market_id="M1")
    r3 = NormalizedRecord(sport=Sport.MLB, event_id="e3", market_id="M2")

    annotate_duplicate_markets([r1, r2, r3])

    assert any("duplicado" in e for e in r1.data_quality.validation_errors)
    assert any("duplicado" in e for e in r2.data_quality.validation_errors)
    assert r3.data_quality.validation_errors == []


def test_annotate_duplicate_markets_no_duplicates_no_errors():
    from src.quality.validators import annotate_duplicate_markets

    r1 = NormalizedRecord(sport=Sport.MLB, event_id="e1", market_id="M1")
    r2 = NormalizedRecord(sport=Sport.MLB, event_id="e2", market_id="M2")
    annotate_duplicate_markets([r1, r2])
    assert r1.data_quality.validation_errors == []
    assert r2.data_quality.validation_errors == []
