from src.quality.completeness import compute_completeness_score, dedupe_missing_fields, subtract_filled_fields


def test_dedupe_missing_fields():
    assert dedupe_missing_fields(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_subtract_filled_fields():
    result = subtract_filled_fields(["a", "b", "c"], ["b"])
    assert result == ["a", "c"]


def test_compute_completeness_score_all_present():
    assert compute_completeness_score([], "MLB") == 1.0


def test_compute_completeness_score_partial():
    score = compute_completeness_score(["participant_a", "market.yes_bid"], "MLB")
    assert 0.0 < score < 1.0


def test_compute_completeness_score_never_negative_or_above_one():
    score = compute_completeness_score(
        ["start_time", "status", "participant_a", "participant_b", "market.yes_bid",
         "market.yes_ask", "market.no_bid", "market.no_ask", "market_close_time",
         "expected_settlement_time"] * 2,
        "MLB",
    )
    assert 0.0 <= score <= 1.0
