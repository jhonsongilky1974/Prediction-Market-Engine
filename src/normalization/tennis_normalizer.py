"""Normaliza un partido de tenis (ESPN scoreboard como fuente base de
evento/calendario; SofaScore como fuente enriquecida de ranking/forma/
estadísticas de saque-resto cuando esté disponible) al esquema único.

Nunca inventa valores: cualquier variable de `TENNIS_VARIABLES` sin datos
reales queda en None y se registra en `missing_fields`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.models.schemas import EventStatus, NormalizedRecord, Sport, TennisVariables

_ESPN_STATE_MAP = {
    "pre": EventStatus.SCHEDULED,
    "in": EventStatus.LIVE,
    "post": EventStatus.FINAL,
}


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _map_status(espn_match: Dict[str, Any]) -> EventStatus:
    state = ((espn_match.get("status") or {}).get("type") or {}).get("state")
    return _ESPN_STATE_MAP.get(state, EventStatus.UNKNOWN)


def normalize_espn_tennis_match(
    espn_match: Dict[str, Any],
    tour: str,
) -> Tuple[NormalizedRecord, List[str]]:
    """`espn_match` es un elemento ya aplanado por
    `EspnTennisConnector.extract_matches` -- que preserva el `competition`
    crudo completo vía `dict(competition)`, así que `id`/`round` de cada
    competidor y de la competencia ya están disponibles aquí sin ningún
    cambio al conector. `tour` en {"ATP","WTA"}."""
    missing: List[str] = []

    match_id = espn_match.get("id")
    if match_id is None:
        missing.append("espn_tennis.id")

    names: List[Optional[str]] = [None, None]
    espn_ids: List[Optional[str]] = [None, None]
    for competitor in espn_match.get("competitors", []) or []:
        athlete = competitor.get("athlete", {}) or {}
        idx = 0 if competitor.get("homeAway") == "home" else 1
        names[idx] = athlete.get("displayName")
        espn_ids[idx] = competitor.get("id")
    participant_a, participant_b = names
    participant_a_espn_id, participant_b_espn_id = espn_ids
    if participant_a is None:
        missing.append("espn_tennis.competitors.home")
    if participant_b is None:
        missing.append("espn_tennis.competitors.away")

    start_time = _parse_iso_timestamp(espn_match.get("date"))
    if start_time is None:
        missing.append("espn_tennis.date")

    status = _map_status(espn_match)
    if status == EventStatus.UNKNOWN:
        missing.append("espn_tennis.status")

    tournament_name = espn_match.get("tournament_name")
    if tournament_name is None:
        missing.append("espn_tennis.tournament_name")

    # Paso 11: ronda del torneo (p.ej. "Qualifying 1st Round", "Final"),
    # verificada contra la API real de ESPN antes de implementar esto --
    # NUNCA inferida por heurística de texto del nombre del torneo (eso
    # está explícitamente prohibido, PLAN_PHASE2.md §16).
    tournament_round = ((espn_match.get("round") or {}).get("displayName"))
    if tournament_round is None:
        missing.append("espn_tennis.round")

    tennis_vars = TennisVariables()
    for field in TennisVariables.model_fields:
        missing.append(f"tennis_variables.{field}")

    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id=f"espn_tennis_{tour.lower()}_{match_id}",
        source_event_ids={"espn_tennis": str(match_id)} if match_id is not None else {},
        start_time=start_time,
        status=status,
        participant_a=participant_a,
        participant_b=participant_b,
        tennis_variables=tennis_vars,
    )
    # Paso 11: identidad estable (espn_id) y ronda del torneo, mismo rol
    # que away_team_id/home_team_id en MLB -- permite emparejar al mismo
    # jugador entre partidos distintos sin depender de texto de nombre.
    record.model_inputs.context = {
        "tournament_name": tournament_name,
        "tour": tour,
        "participant_a_espn_id": participant_a_espn_id,
        "participant_b_espn_id": participant_b_espn_id,
        "tournament_round": tournament_round,
    }
    return record, missing


def enrich_with_sofascore_stats(
    record: NormalizedRecord,
    ranking_a: Optional[int] = None,
    ranking_b: Optional[int] = None,
    surface: Optional[str] = None,
    last_5: Optional[Dict[str, Any]] = None,
    last_10: Optional[Dict[str, Any]] = None,
    h2h: Optional[Dict[str, Any]] = None,
    statistics_items: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Rellena `record.tennis_variables` in-place con datos reales de
    SofaScore cuando están disponibles. Devuelve la lista de campos que
    siguen faltando (para restar de `missing_fields` en el pipeline)."""
    filled: List[str] = []
    tv = record.tennis_variables
    if tv is None:
        return filled

    if ranking_a is not None:
        tv.ranking_a = ranking_a
        filled.append("tennis_variables.ranking_a")
    if ranking_b is not None:
        tv.ranking_b = ranking_b
        filled.append("tennis_variables.ranking_b")
    if surface is not None:
        tv.surface = surface
        filled.append("tennis_variables.surface")
    if last_5 is not None:
        tv.last_5 = last_5
        filled.append("tennis_variables.last_5")
    if last_10 is not None:
        tv.last_10 = last_10
        filled.append("tennis_variables.last_10")
    if h2h is not None:
        tv.h2h = h2h
        filled.append("tennis_variables.h2h")

    if statistics_items:
        stat_map = {item.get("name"): item for item in statistics_items if isinstance(item, dict)}

        def take(name: str) -> Optional[Dict[str, Any]]:
            item = stat_map.get(name)
            if not item:
                return None
            return {"home": item.get("home"), "away": item.get("away")}

        mapping = {
            "aces": "aces",
            "double_faults": "doubleFaults",
            "first_serve_pct": "firstServeAccuracy",
            "first_serve_points_won": "firstServePointsAccuracy",
            "second_serve_points_won": "secondServePointsAccuracy",
            "service_games_held": "serviceGamesWon",
            "break_points_saved": "breakPointsSaved",
            "break_points_converted": "breakPointsScored",
        }
        for field, stat_name in mapping.items():
            value = take(stat_name)
            if value is not None:
                setattr(tv, field, value)
                filled.append(f"tennis_variables.{field}")

    return filled
