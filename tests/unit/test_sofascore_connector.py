from src.connectors.sofascore import SofascoreConnector


def _search_payload(*entries):
    return {"results": [{"type": t, "entity": {"id": i, "name": n}} for (t, i, n) in entries]}


def test_find_player_exact_name_match():
    payload = _search_payload(("player", 42, "Daniel Merida"))
    assert SofascoreConnector.find_player_or_team_id(payload, "Daniel Merida", "player") == 42


def test_find_player_never_returns_id_for_unrelated_homonym():
    """Regresión: antes se devolvía el primer resultado de tipo 'player'
    SIN comprobar el nombre. Un homónimo/apellido compartido no debe
    adjuntarse como si fuera el jugador correcto."""
    payload = _search_payload(("player", 99, "Bryan Shelton"))
    assert SofascoreConnector.find_player_or_team_id(payload, "Ben Shelton", "player") is None


def test_find_player_picks_best_scoring_result_among_several():
    payload = _search_payload(
        ("player", 1, "Bryan Shelton"),
        ("player", 2, "Ben Shelton"),
        ("team", 3, "Ben Shelton"),
    )
    assert SofascoreConnector.find_player_or_team_id(payload, "Ben Shelton", "player") == 2


def test_find_player_ignores_wrong_entity_type():
    payload = _search_payload(("team", 7, "Daniel Merida"))
    assert SofascoreConnector.find_player_or_team_id(payload, "Daniel Merida", "player") is None


def test_find_player_no_results_returns_none():
    assert SofascoreConnector.find_player_or_team_id({"results": []}, "Daniel Merida", "player") is None
    assert SofascoreConnector.find_player_or_team_id(None, "Daniel Merida", "player") is None
