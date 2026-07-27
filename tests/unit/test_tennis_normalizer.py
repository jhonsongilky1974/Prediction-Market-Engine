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


# ---------------------------------------------------------------------
# Paso 11: espn_id por participante + ronda del torneo. `extract_matches`
# ya preserva el `competition` crudo completo (dict(competition)), así que
# se construye el match inline con la forma real verificada contra la API
# de ESPN -- el fixture compartido (Fase 1) no incluye estos campos y no
# se modifica para no afectar otros tests que dependen de él.
# ---------------------------------------------------------------------


def _match_with_ids_and_round(round_info=None):
    return {
        "id": "183021",
        "date": "2026-07-18T11:00Z",
        "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}},
        "competitors": [
            {"id": "11754", "homeAway": "home", "athlete": {"displayName": "Edas Butvilas"}},
            {"id": "3512", "homeAway": "away", "athlete": {"displayName": "Clement Tabur"}},
        ],
        "round": round_info,
        "tournament_name": "Millennium Estoril Open",
        "grouping_name": "Men's Singles",
    }


def test_normalize_captures_participant_espn_ids_and_tournament_round():
    match = _match_with_ids_and_round({"id": "11", "displayName": "Qualifying 1st Round"})
    record, missing = normalize_espn_tennis_match(match, "ATP")

    assert record.participant_a == "Edas Butvilas"  # home
    assert record.participant_b == "Clement Tabur"  # away
    assert record.model_inputs.context["participant_a_espn_id"] == "11754"
    assert record.model_inputs.context["participant_b_espn_id"] == "3512"
    assert record.model_inputs.context["tournament_round"] == "Qualifying 1st Round"
    assert "espn_tennis.round" not in missing


def test_normalize_reports_missing_round_when_absent_never_fabricates():
    match = _match_with_ids_and_round(None)
    record, missing = normalize_espn_tennis_match(match, "ATP")

    assert record.model_inputs.context["tournament_round"] is None
    assert "espn_tennis.round" in missing
