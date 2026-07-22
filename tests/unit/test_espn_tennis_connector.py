from src.connectors.espn_tennis import EspnTennisConnector
from src.normalization.tennis_normalizer import normalize_espn_tennis_match


def test_extract_matches_filters_out_doubles_by_default(espn_atp_scoreboard_with_doubles_sample):
    """Regresión: el scoreboard de ESPN mezcla singles y dobles en la misma
    respuesta. Un competitor de dobles tiene `type: "team"` + `roster`
    (2 atletas), no la clave `athlete` que espera el resto del pipeline.
    Sin filtrar, `normalize_espn_tennis_match` producía un registro con
    participant_a/participant_b en None (dato basura silencioso) en vez de
    descartar el partido de dobles antes de normalizar."""
    matches = EspnTennisConnector.extract_matches(espn_atp_scoreboard_with_doubles_sample)
    assert len(matches) == 1
    assert matches[0]["grouping_name"] == "Men's Singles"


def test_extract_matches_can_include_doubles_when_requested(espn_atp_scoreboard_with_doubles_sample):
    matches = EspnTennisConnector.extract_matches(espn_atp_scoreboard_with_doubles_sample, singles_only=False)
    grouping_names = {m["grouping_name"] for m in matches}
    assert grouping_names == {"Men's Singles", "Men's Doubles"}


def test_normalized_singles_only_matches_never_have_null_participants_from_doubles_leak(
    espn_atp_scoreboard_with_doubles_sample,
):
    matches = EspnTennisConnector.extract_matches(espn_atp_scoreboard_with_doubles_sample)
    for match in matches:
        record, missing = normalize_espn_tennis_match(match, "ATP")
        assert record.participant_a is not None
        assert record.participant_b is not None
