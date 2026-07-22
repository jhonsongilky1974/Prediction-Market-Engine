from src.normalization.market_normalizer import normalize_kalshi_market


def test_normalize_kalshi_market_preserves_raw_bid_ask(kalshi_mlb_market_sample):
    norm = normalize_kalshi_market(kalshi_mlb_market_sample)
    assert norm.market.yes_bid == 0.35
    assert norm.market.yes_ask == 0.40
    assert norm.market.no_bid == 0.60
    assert norm.market.no_ask == 0.68
    # nunca reconstruido como 1 - yes_bid (que daría 0.65, no 0.68)
    assert norm.market.no_ask != round(1 - norm.market.yes_bid, 4)


def test_spread_calculation(kalshi_mlb_market_sample):
    norm = normalize_kalshi_market(kalshi_mlb_market_sample)
    assert norm.market.spread_yes == 0.05
    assert norm.market.spread_no == 0.08


def test_market_price_executable_is_yes_ask(kalshi_mlb_market_sample):
    norm = normalize_kalshi_market(kalshi_mlb_market_sample)
    assert norm.market.market_price_executable == norm.market.yes_ask


def test_timestamps_mapped_correctly(kalshi_mlb_market_sample):
    norm = normalize_kalshi_market(kalshi_mlb_market_sample)
    assert norm.start_time.isoformat() == "2026-07-24T01:40:00+00:00"
    assert norm.market_close_time.isoformat() == "2026-07-26T22:40:00+00:00"
    assert norm.expected_settlement_time.isoformat() == "2026-07-24T01:40:00+00:00"
    assert norm.actual_settlement_time is None
    assert "actual_settlement_time" in norm.missing_fields


def test_exchange_fee_stays_null_when_absent(kalshi_mlb_market_sample):
    norm = normalize_kalshi_market(kalshi_mlb_market_sample)
    assert norm.market.exchange_fee is None
    assert "market.fee_type" in norm.missing_fields


def test_missing_price_field_not_invented():
    raw = {"ticker": "X", "event_ticker": "Y"}
    norm = normalize_kalshi_market(raw)
    assert norm.market.yes_bid is None
    assert norm.market.spread_yes is None
    assert "market.yes_bid" in norm.missing_fields
