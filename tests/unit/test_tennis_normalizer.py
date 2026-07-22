from src.connectors.espn_tennis import EspnTennisConnector
from src.models.schemas import EventStatus
from src.normalization.tennis_normalizer import enrich_with_sofascore_stats, normalize_espn_tennis_match


def _first_match(espn_atp_scoreboard_sample):
    matches = EspnTennisConnector.extract_matches(espn_atp_scoreboard_sample)
    return matches[0]


def test_normalize_espn_tennis_match(espn_atp_scoreboard_sample):
    match = _first_match(espn_atp_scoreboard_sample)
    record, missing = normalize_espn_tennis_match(match, "ATP")
    assert record.participant_a == "Daniel Merida"
    assert record.participant_b == "Kyrian Jacquet"
    assert record.status == EventStatus.SCHEDULED
    assert record.tennis_variables is not None
    assert record.tennis_variables.ranking_a is None
    assert any(f.startswith("tennis_variables.") for f in missing)


def test_enrich_with_sofascore_fills_and_reports(espn_atp_scoreboard_sample):
    match = _first_match(espn_atp_scoreboard_sample)
    record, _ = normalize_espn_tennis_match(match, "ATP")
    filled = enrich_with_sofascore_stats(record, ranking_a=12, ranking_b=45, surface="Clay")
    assert record.tennis_variables.ranking_a == 12
    assert record.tennis_variables.ranking_b == 45
    assert record.tennis_variables.surface == "Clay"
    assert "tennis_variables.ranking_a" in filled
    # variables no provistas siguen en None
    assert record.tennis_variables.h2h is None


def test_enrich_maps_statistics_items(espn_atp_scoreboard_sample):
    match = _first_match(espn_atp_scoreboard_sample)
    record, _ = normalize_espn_tennis_match(match, "ATP")
    stats_items = [
        {"name": "aces", "home": "8", "away": "5"},
        {"name": "doubleFaults", "home": "2", "away": "3"},
    ]
    filled = enrich_with_sofascore_stats(record, statistics_items=stats_items)
    assert record.tennis_variables.aces == {"home": "8", "away": "5"}
    assert record.tennis_variables.double_faults == {"home": "2", "away": "3"}
    assert "tennis_variables.aces" in filled
