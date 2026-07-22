"""Conector SofaScore (API interna/no oficial, sin key).

Endpoints validados:
  GET /search/all?q={nombre}
  GET /team/{id}                  (SofaScore usa "team" también para jugadores individuales)
  GET /team/{id}/events/last/0
  GET /event/{event_id}/statistics

Precauciones obligatorias (API no documentada, ver instrucciones de Fase 1):
  - timeouts cortos y reintentos limitados (ver config.settings.SOFASCORE_POLICY)
  - backoff exponencial, nunca loops agresivos
  - rate limiting conservador (espaciado mínimo entre requests)
  - headers tipo navegador (algunos despliegues de SofaScore exigen
    Referer/Origin; se envían siempre, pero no garantizan 200 — el WAF
    puede bloquear por IP/datacenter independientemente de los headers)
  - manejo de cambios de schema: la extracción nunca asume que una clave
    anidada existe; devuelve None/[] y dependerá de quality.completeness
    marcar el campo como MISSING en vez de fallar

NOTA (verificado 2026-07-21): desde el entorno de ejecución de este agente,
SofaScore responde 403 Forbidden a *todas* las requests (con o sin headers
de navegador), consistente con un bloqueo Cloudflare por rango de IP de
datacenter. El conector queda implementado según especificación pero su
disponibilidad real debe revalidarse desde una IP residencial/oficina.
ESPN Tennis actúa como fallback (ver espn_tennis.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE, SOFASCORE_BASE_URL, SOFASCORE_POLICY
from src.connectors.base_client import BaseHttpClient, FetchResult
from src.matching.event_matcher import name_similarity

_BROWSER_HEADERS = {
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}


class SofascoreConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = SOFASCORE_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("sofascore", SOFASCORE_POLICY, repository)

    def search(self, query: str) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/search/all",
            params={"q": query},
            endpoint_label=f"search_{query}",
            extra_headers=_BROWSER_HEADERS,
        )

    def get_team(self, team_id: int) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/team/{team_id}",
            endpoint_label=f"team_{team_id}",
            extra_headers=_BROWSER_HEADERS,
        )

    def get_team_last_events(self, team_id: int, page: int = 0) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/team/{team_id}/events/last/{page}",
            endpoint_label=f"team_events_last_{team_id}_{page}",
            extra_headers=_BROWSER_HEADERS,
        )

    def get_event_statistics(self, event_id: int) -> FetchResult:
        return self._client.get_json(
            f"{self.base_url}/event/{event_id}/statistics",
            endpoint_label=f"event_statistics_{event_id}",
            extra_headers=_BROWSER_HEADERS,
        )

    # -----------------------------------------------------------------
    # Extracción defensiva (tolerante a cambios de schema)
    # -----------------------------------------------------------------
    @staticmethod
    def extract_search_results(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        return payload.get("results", []) or []

    @staticmethod
    def find_player_or_team_id(
        search_payload: Optional[Dict[str, Any]],
        name_query: str,
        entity_type: str = "player",
        min_similarity: float = EVENT_NAME_MATCH_MIN_CONFIDENCE,
    ) -> Optional[int]:
        """Devuelve el id del PRIMER resultado del tipo pedido cuyo nombre
        coincide razonablemente con `name_query` (ver `name_similarity`).

        Antes esto devolvía el primer resultado de `entity_type` SIN
        verificar el nombre en absoluto: `/search/all?q=<nombre>` puede
        devolver varios jugadores homónimos o parcialmente similares, y
        tomar el primero a ciegas podía adjuntar el ranking/stats de una
        persona real distinta al registro. Un resultado cuyo nombre no
        supera el umbral se descarta (se sigue buscando en los siguientes,
        no se fuerza)."""
        best_id: Optional[int] = None
        best_score = -1.0
        for result in SofascoreConnector.extract_search_results(search_payload):
            entity = result.get("entity", {}) if isinstance(result, dict) else {}
            if result.get("type") != entity_type or entity.get("id") is None:
                continue
            score = name_similarity(name_query, entity.get("name"))
            if score >= min_similarity and score > best_score:
                best_score = score
                best_id = entity.get("id")
        return best_id

    @staticmethod
    def extract_last_events(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        return payload.get("events", []) or []

    @staticmethod
    def extract_statistics_groups(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aplana `statistics[*].groups[*].statisticsItems[*]` a una lista de
        items {name, home, away}. Devuelve [] si el schema no coincide."""
        if not isinstance(payload, dict):
            return []
        items: List[Dict[str, Any]] = []
        for period_block in payload.get("statistics", []) or []:
            for group in period_block.get("groups", []) or []:
                for item in group.get("statisticsItems", []) or []:
                    items.append(item)
        return items
