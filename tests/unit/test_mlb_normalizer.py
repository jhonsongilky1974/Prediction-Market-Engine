from src.models.schemas import EventStatus
from src.normalization.mlb_normalizer import normalize_mlb_game


def test_normalize_mlb_game_basic_fields(mlb_schedule_sample):
    game = mlb_schedule_sample["dates"][0]["games"][0]
    record, missing = normalize_mlb_game(game)
    assert record.participant_a == "Minnesota Twins"
    assert record.participant_b == "Cleveland Guardians"
    assert record.status == EventStatus.SCHEDULED
    assert record.event_id == "mlb_824409"
    assert record.source_event_ids == {"mlb": "824409"}


def test_normalize_mlb_game_missing_boxscore(mlb_schedule_sample):
    game = mlb_schedule_sample["dates"][0]["games"][0]
    _, missing = normalize_mlb_game(game)
    assert "mlb.boxscore" in missing
    assert "mlb.injuries" in missing


def test_normalize_mlb_game_with_boxscore_fills_batting_order(mlb_schedule_sample, mlb_boxscore_sample):
    game = mlb_schedule_sample["dates"][0]["games"][0]
    record, missing = normalize_mlb_game(game, boxscore_raw=mlb_boxscore_sample)
    assert record.model_inputs.lineup_or_pitcher["batting_order"] is not None
    assert "mlb.boxscore" not in missing


def test_normalize_mlb_game_probable_pitchers(mlb_schedule_sample):
    game = mlb_schedule_sample["dates"][0]["games"][0]
    record, _ = normalize_mlb_game(game)
    lineup = record.model_inputs.lineup_or_pitcher
    assert lineup["away_probable_pitcher"]["fullName"] == "Kendry Rojas"
    assert lineup["home_probable_pitcher"]["fullName"] == "Parker Messick"


def test_never_invents_missing_gamepk():
    record, missing = normalize_mlb_game({})
    assert record.participant_a is None
    assert record.participant_b is None
    assert "mlb.gamePk" in missing


def test_missing_venue_key_is_tracked_in_missing_fields(mlb_schedule_sample):
    """Regresión: un guard redundante (`if "venue" in game_raw else None`)
    se saltaba el registro de `req()` cuando la clave "venue" faltaba por
    completo, dejando el valor en None (correcto) pero SIN aparecer en
    `missing_fields` (incorrecto: el dato ausente quedaba sin rastro)."""
    game = dict(mlb_schedule_sample["dates"][0]["games"][0])
    del game["venue"]
    record, missing = normalize_mlb_game(game)
    assert record.model_inputs.context["venue"] is None
    assert "mlb.venue.name" in missing
