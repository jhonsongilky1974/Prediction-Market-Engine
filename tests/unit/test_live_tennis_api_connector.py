"""Tests del conector Live Tennis API (sin red, con fixture).

Cubre el mismo contrato que `test_odds_api.py` (key desde env, NOT_CONFIGURED
sin tocar la red) más la extracción defensiva del estado de partido en vivo y
la lógica tri-valuada del flag de break point.
"""
import pytest

from src.connectors.live_tennis_api import (
    BREAK_POINT_NO,
    BREAK_POINT_UNDEF,
    BREAK_POINT_YES,
    LiveTennisApiConnector,
)


# --- Configuración de key (mismo contrato que odds_api) ----------------------

def test_not_configured_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("LIVE_TENNIS_API_KEY", raising=False)
    assert LiveTennisApiConnector().is_configured() is False


def test_configured_when_env_var_present(monkeypatch):
    monkeypatch.setenv("LIVE_TENNIS_API_KEY", "fake-key-for-test")
    assert LiveTennisApiConnector().is_configured() is True


def test_get_live_matches_returns_not_configured_without_network_call(monkeypatch):
    monkeypatch.delenv("LIVE_TENNIS_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no debería llamar a la red sin API key")

    connector = LiveTennisApiConnector()
    monkeypatch.setattr(connector._client, "get_json", fail_if_called)

    result = connector.get_live_matches()
    assert result.ok is False
    assert result.error == "NOT_CONFIGURED"


def test_get_live_matches_sends_api_key_header(monkeypatch):
    monkeypatch.setenv("LIVE_TENNIS_API_KEY", "secret-123")
    connector = LiveTennisApiConnector()

    captured = {}

    def fake_get_json(url, params=None, endpoint_label=None, extra_headers=None):
        captured["url"] = url
        captured["headers"] = extra_headers
        return object()

    monkeypatch.setattr(connector._client, "get_json", fake_get_json)
    connector.get_live_matches()

    assert captured["url"].endswith("/live")
    assert captured["headers"] == {"X-API-Key": "secret-123"}


# --- Extracción defensiva ----------------------------------------------------

def test_extract_matches_returns_data_list(livetennisapi_live_sample):
    matches = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)
    assert len(matches) == 6
    assert matches[0]["id"] == "lt_1001"


@pytest.mark.parametrize("payload", [None, {}, {"data": None}, {"data": "x"}, 42])
def test_extract_matches_tolerates_bad_payload(payload):
    assert LiveTennisApiConnector.extract_matches(payload) == []


def test_extract_participant_names(livetennisapi_live_sample):
    match = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)[0]
    assert LiveTennisApiConnector.extract_participant_names(match) == [
        "Carlos Alcaraz",
        "Jannik Sinner",
    ]


def test_extract_participant_names_missing_returns_none():
    assert LiveTennisApiConnector.extract_participant_names({}) == [None, None]


def test_extract_status_variants(livetennisapi_live_sample):
    matches = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)
    by_id = {m["id"]: m for m in matches}
    assert LiveTennisApiConnector.extract_status(by_id["lt_1001"]) == "live"
    assert LiveTennisApiConnector.extract_status(by_id["lt_1005"]) == "retired"
    assert LiveTennisApiConnector.extract_status(by_id["lt_1006"]) == "walkover"


def test_extract_server(livetennisapi_live_sample):
    matches = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)
    by_id = {m["id"]: m for m in matches}
    assert LiveTennisApiConnector.extract_server(by_id["lt_1001"]) == 1
    assert LiveTennisApiConnector.extract_server(by_id["lt_1002"]) == 2
    # server null -> None
    assert LiveTennisApiConnector.extract_server(by_id["lt_1004"]) is None


# --- Flag de break point (tri-valuado) --------------------------------------

def test_break_point_yes_returner_at_40():
    # servidor p1 en 30, restador p2 en 40 -> break point
    score = {"server": 1, "points": {"p1": "30", "p2": "40"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_YES


def test_break_point_yes_returner_advantage():
    score = {"server": 2, "points": {"p1": "AD", "p2": "40"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_YES


def test_break_point_no_at_deuce():
    score = {"server": 2, "points": {"p1": "40", "p2": "40"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_NO


def test_break_point_no_server_advantage():
    # el sacador con ventaja no es break point
    score = {"server": 1, "points": {"p1": "AD", "p2": "40"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_NO


def test_break_point_suppressed_in_tiebreak():
    score = {"server": 1, "points": {"p1": "5", "p2": "6"}, "tiebreak": True}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_NO


def test_break_point_suppressed_on_numeric_points_without_flag():
    # aunque falte el flag `tiebreak`, points fuera del scoring estándar se
    # tratan como no-break-point (no se inventa un Yes)
    score = {"server": 1, "points": {"p1": "5", "p2": "6"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_NO


def test_break_point_undef_when_server_unknown():
    score = {"server": None, "points": {"p1": "AD", "p2": "40"}}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_UNDEF


def test_break_point_undef_when_score_not_dict():
    assert LiveTennisApiConnector.break_point_flag(None) == BREAK_POINT_UNDEF


def test_break_point_no_when_points_missing():
    score = {"server": 1}
    assert LiveTennisApiConnector.break_point_flag(score) == BREAK_POINT_NO


# --- Vista compacta match_state ---------------------------------------------

def test_match_state_shape(livetennisapi_live_sample):
    matches = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)
    by_id = {m["id"]: m for m in matches}

    state = LiveTennisApiConnector.match_state(by_id["lt_1001"])
    assert state == {
        "id": "lt_1001",
        "status": "live",
        "participant_a": "Carlos Alcaraz",
        "participant_b": "Jannik Sinner",
        "server": 1,
        "break_point": BREAK_POINT_YES,
        "sets": {"p1": 1, "p2": 1},
        "games": {"p1": 4, "p2": 5},
        "points": {"p1": "30", "p2": "40"},
    }


def test_match_state_walkover_has_no_break_point(livetennisapi_live_sample):
    matches = LiveTennisApiConnector.extract_matches(livetennisapi_live_sample)
    by_id = {m["id"]: m for m in matches}
    state = LiveTennisApiConnector.match_state(by_id["lt_1006"])
    assert state["status"] == "walkover"
    # score vacío -> servidor desconocido -> UNDEF
    assert state["break_point"] == BREAK_POINT_UNDEF
    assert state["server"] is None
