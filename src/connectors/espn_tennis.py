"""Conector ESPN Tennis (fuente complementaria/fallback, pública, sin key).

Endpoint validado:
  GET site.api.espn.com/apis/site/v2/sports/tennis/{atp|wta}/scoreboard?dates=YYYYMMDD

Schema real verificado (2026-07-21):
  {"events": [{"id", "date", "name" (torneo), "groupings": [{"competitions": [
      {"id", "date", "status": {"type": {"name","state","completed"}},
       "competitors": [{"athlete": {"displayName", ...}, "homeAway", "winner"}]}
  ]}]}]}

No se asume cobertura completa: puede haber torneos ausentes, o el evento no
tener aún competidores confirmados.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import ESPN_TENNIS_BASE_URL, ESPN_TENNIS_POLICY
from src.connectors.base_client import BaseHttpClient, FetchResult

_VALID_TOURS = ("atp", "wta")


class EspnTennisConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = ESPN_TENNIS_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("espn_tennis", ESPN_TENNIS_POLICY, repository)

    def get_scoreboard(self, tour: str, date: str) -> FetchResult:
        """`tour` en {"atp","wta"}; `date` en formato YYYYMMDD."""
        tour = tour.lower()
        if tour not in _VALID_TOURS:
            raise ValueError(f"tour debe ser uno de {_VALID_TOURS}, recibido: {tour}")
        return self._client.get_json(
            f"{self.base_url}/{tour}/scoreboard",
            params={"dates": date},
            endpoint_label=f"scoreboard_{tour}_{date}",
        )

    @staticmethod
    def extract_matches(payload: Optional[Dict[str, Any]], singles_only: bool = True) -> List[Dict[str, Any]]:
        """Aplana events[].groupings[].competitions[] a una lista de partidos,
        cada uno con el nombre del torneo adjunto.

        `singles_only=True` (por defecto) descarta agrupaciones de dobles
        ("Men's Doubles"/"Women's Doubles"/"Mixed Doubles"). Kalshi
        (KXATPMATCH/KXWTAMATCH) solo cubre partidos individuales, y el
        `competitor` de un partido de dobles tiene una forma distinta —
        `type: "team"` con un `roster` de 2 atletas en vez de un `athlete`
        único. Sin este filtro, `normalize_espn_tennis_match` no encuentra
        la clave `athlete` esperada y produce silenciosamente un registro
        con `participant_a`/`participant_b` en None (dato basura, no un
        error visible) en vez de ser descartado antes de normalizar."""
        if not isinstance(payload, dict):
            return []
        matches: List[Dict[str, Any]] = []
        for event in payload.get("events", []) or []:
            tournament_name = event.get("name")
            for grouping in event.get("groupings", []) or []:
                grouping_name = (grouping.get("grouping") or {}).get("displayName") or ""
                if singles_only and "singles" not in grouping_name.lower():
                    continue
                for competition in grouping.get("competitions", []) or []:
                    match = dict(competition)
                    match["tournament_name"] = tournament_name
                    match["grouping_name"] = grouping_name
                    matches.append(match)
        return matches

    @staticmethod
    def extract_participant_names(match: Dict[str, Any]) -> List[Optional[str]]:
        names: List[Optional[str]] = [None, None]
        for competitor in match.get("competitors", []) or []:
            athlete = competitor.get("athlete", {}) or {}
            idx = 0 if competitor.get("homeAway") == "home" else 1
            names[idx] = athlete.get("displayName")
        return names
