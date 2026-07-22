"""Conector de la MLB Stats API oficial (pública, sin key).

Endpoints validados (ver instrucciones de Fase 1):
  GET /api/v1/schedule?sportId=1&date=YYYY-MM-DD[&hydrate=probablePitcher]
  GET /api/v1/game/{gamePk}/boxscore
  GET /api/v1.1/game/{gamePk}/feed/live
  GET /api/v1/teams/{id}/roster
  GET /api/v1/people/{id}/stats
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import MLB_BASE_URL, MLB_POLICY
from src.connectors.base_client import BaseHttpClient, FetchResult


class MlbConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = MLB_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("mlb", MLB_POLICY, repository)

    def get_schedule(self, date: str, hydrate_probable_pitcher: bool = True) -> FetchResult:
        """`date` en formato YYYY-MM-DD."""
        params = {"sportId": 1, "date": date}
        if hydrate_probable_pitcher:
            params["hydrate"] = "probablePitcher,team"
        return self._client.get_json(
            f"{self.base_url}/api/v1/schedule", params=params, endpoint_label=f"schedule_{date}"
        )

    def get_boxscore(self, game_pk: int) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/api/v1/game/{game_pk}/boxscore",
            endpoint_label=f"boxscore_{game_pk}",
        )

    def get_live_feed(self, game_pk: int) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/api/v1.1/game/{game_pk}/feed/live",
            endpoint_label=f"feed_live_{game_pk}",
        )

    def get_roster(self, team_id: int) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/api/v1/teams/{team_id}/roster",
            endpoint_label=f"roster_{team_id}",
        )

    def get_person_stats(self, person_id: int, group: str = "pitching", stats_type: str = "season") -> FetchResult:
        params = {"stats": stats_type, "group": group}
        return self._client.get_json(
            f"{self.base_url}/api/v1/people/{person_id}/stats",
            params=params,
            endpoint_label=f"people_stats_{person_id}_{group}",
        )

    @staticmethod
    def extract_games(schedule_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        games: List[Dict[str, Any]] = []
        for date_entry in schedule_payload.get("dates", []) or []:
            games.extend(date_entry.get("games", []) or [])
        return games
