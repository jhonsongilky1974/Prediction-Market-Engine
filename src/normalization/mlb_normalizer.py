"""Normaliza un juego de la MLB Stats API (`schedule` + opcionalmente
`boxscore`/roster/lesiones) al esquema único `NormalizedRecord`.

Nunca inventa valores. Cualquier dato no presente en las respuestas
provistas se deja en None y se añade a `missing_fields`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.models.schemas import EventStatus, ModelInputs, NormalizedRecord, Sport

_STATUS_MAP = {
    "Preview": EventStatus.SCHEDULED,
    "Live": EventStatus.LIVE,
    "Final": EventStatus.FINAL,
    "Postponed": EventStatus.POSTPONED,
    "Cancelled": EventStatus.CANCELLED,
}


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _map_status(abstract_state: Optional[str], detailed_state: Optional[str]) -> EventStatus:
    if detailed_state in _STATUS_MAP:
        return _STATUS_MAP[detailed_state]
    if abstract_state in _STATUS_MAP:
        return _STATUS_MAP[abstract_state]
    return EventStatus.UNKNOWN


def normalize_mlb_game(
    game_raw: Dict[str, Any],
    boxscore_raw: Optional[Dict[str, Any]] = None,
    probable_pitcher_stats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[NormalizedRecord, List[str]]:
    missing: List[str] = []

    def req(path: List[str], container: Dict[str, Any]) -> Any:
        cur: Any = container
        for key in path:
            if not isinstance(cur, dict) or key not in cur or cur[key] is None:
                missing.append("mlb." + ".".join(path))
                return None
            cur = cur[key]
        return cur

    game_pk = game_raw.get("gamePk")
    if game_pk is None:
        missing.append("mlb.gamePk")

    away_team = req(["teams", "away", "team", "name"], game_raw)
    home_team = req(["teams", "home", "team", "name"], game_raw)

    status_block = game_raw.get("status", {}) or {}
    abstract_state = status_block.get("abstractGameState")
    detailed_state = status_block.get("detailedState")
    if abstract_state is None:
        missing.append("mlb.status.abstractGameState")
    status = _map_status(abstract_state, detailed_state)

    start_time = _parse_iso_timestamp(req(["gameDate"], game_raw))

    away_pitcher = (game_raw.get("teams", {}) or {}).get("away", {}).get("probablePitcher")
    home_pitcher = (game_raw.get("teams", {}) or {}).get("home", {}).get("probablePitcher")
    if away_pitcher is None:
        missing.append("mlb.teams.away.probablePitcher")
    if home_pitcher is None:
        missing.append("mlb.teams.home.probablePitcher")

    lineup_or_pitcher: Dict[str, Any] = {
        "away_probable_pitcher": away_pitcher,
        "home_probable_pitcher": home_pitcher,
    }

    batting_orders = None
    if boxscore_raw is not None:
        away_bo = (boxscore_raw.get("teams", {}) or {}).get("away", {}).get("battingOrder")
        home_bo = (boxscore_raw.get("teams", {}) or {}).get("home", {}).get("battingOrder")
        if away_bo or home_bo:
            batting_orders = {"away": away_bo, "home": home_bo}
        else:
            missing.append("mlb.boxscore.battingOrder")
    else:
        missing.append("mlb.boxscore")
    lineup_or_pitcher["batting_order"] = batting_orders

    stats = None
    if probable_pitcher_stats:
        stats = {"probable_pitchers": probable_pitcher_stats}
    else:
        missing.append("mlb.probable_pitcher_stats")

    context = {
        # req() ya maneja el caso "venue" ausente (registra mlb.venue.name
        # en `missing` y devuelve None); el guard `if "venue" in game_raw`
        # que había aquí antes era redundante y, peor, se saltaba ese
        # registro cuando la clave faltaba por completo -- el valor seguía
        # siendo None (correcto) pero quedaba sin marcar como MISSING.
        "venue": req(["venue", "name"], game_raw),
        "game_type": game_raw.get("gameType"),
        "season": game_raw.get("season"),
        "away_league_record": req(["teams", "away", "leagueRecord"], game_raw),
        "home_league_record": req(["teams", "home", "leagueRecord"], game_raw),
        "away_team_id": (game_raw.get("teams", {}) or {}).get("away", {}).get("team", {}).get("id"),
        "home_team_id": (game_raw.get("teams", {}) or {}).get("home", {}).get("team", {}).get("id"),
    }

    record = NormalizedRecord(
        sport=Sport.MLB,
        event_id=f"mlb_{game_pk}",
        source_event_ids={"mlb": str(game_pk)} if game_pk is not None else {},
        start_time=start_time,
        status=status,
        participant_a=away_team,
        participant_b=home_team,
        model_inputs=ModelInputs(
            stats=stats,
            form=None,
            matchup_h2h=None,
            lineup_or_pitcher=lineup_or_pitcher,
            injuries=None,
            context=context,
        ),
    )
    missing.append("mlb.form")
    missing.append("mlb.matchup_h2h")
    missing.append("mlb.injuries")

    return record, missing
