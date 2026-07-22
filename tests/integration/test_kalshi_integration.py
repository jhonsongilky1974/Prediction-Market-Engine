"""Tests de integración reales contra Kalshi. Requieren red."""
import pytest

from src.connectors.kalshi import KalshiConnector

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("sport_key", ["MLB", "ATP", "WTA"])
def test_get_events_real(sport_key):
    kalshi = KalshiConnector()
    result = kalshi.get_events_for_sport(sport_key)
    if not result.ok:
        pytest.skip(f"Kalshi no respondió para {sport_key}: {result.error}")
    events = KalshiConnector.extract_events(result.data)
    assert isinstance(events, list)


def test_market_payload_has_real_bid_ask_fields():
    kalshi = KalshiConnector()
    result = kalshi.get_events_for_sport("MLB")
    if not result.ok:
        pytest.skip(f"Kalshi no respondió: {result.error}")
    events = KalshiConnector.extract_events(result.data)
    if not events:
        pytest.skip("no hay eventos MLB abiertos en Kalshi ahora mismo")
    markets = events[0].get("markets") or []
    if not markets:
        pytest.skip("evento sin mercados anidados")
    market = markets[0]
    for field in ("yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars"):
        assert field in market
