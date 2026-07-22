"""Conector The Odds API.

Regla de seguridad: la API key se lee EXCLUSIVAMENTE desde la variable de
entorno `ODDS_API_KEY` (ver config.settings.get_odds_api_key). Nunca se
hardcodea, nunca se inventa. Si no está configurada, el conector expone
`is_configured() == False` y cualquier llamada devuelve un `FetchResult`
con `error="NOT_CONFIGURED"` sin tocar la red, para que el pipeline
continúe sin romperse.

Cuota: se registran los headers `x-requests-used`, `x-requests-remaining`,
`x-requests-last` de la última respuesta para evitar polling innecesario.

Fase 1 cubre `h2h`. La estructura deja espacio para `spreads`/`totals` en
una fase futura (parámetro `markets`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import ODDS_API_BASE_URL, ODDS_API_POLICY, get_odds_api_key
from src.connectors.base_client import BaseHttpClient, FetchResult

SUPPORTED_MARKETS_PHASE1 = ("h2h",)
FUTURE_MARKETS = ("spreads", "totals")

SPORT_KEYS = {
    "MLB": "baseball_mlb",
    "ATP": "tennis_atp",
    "WTA": "tennis_wta",
}


class OddsApiConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = ODDS_API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("odds_api", ODDS_API_POLICY, repository)
        self._api_key = get_odds_api_key()
        self.last_quota: Dict[str, Optional[str]] = {
            "x-requests-used": None,
            "x-requests-remaining": None,
            "x-requests-last": None,
        }

    def is_configured(self) -> bool:
        return self._api_key is not None

    def get_odds(
        self,
        sport_key: str,
        regions: str = "us",
        markets: str = "h2h",
        odds_format: str = "decimal",
    ) -> FetchResult:
        if not self.is_configured():
            return FetchResult(
                ok=False,
                status_code=None,
                data=None,
                error="NOT_CONFIGURED",
                url=f"{self.base_url}/sports/{sport_key}/odds",
                capture_ts=datetime.now(timezone.utc),
            )
        params = {
            "apiKey": self._api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
        }
        result = self._client.get_json(
            f"{self.base_url}/sports/{sport_key}/odds",
            params=params,
            endpoint_label=f"odds_{sport_key}_{markets}",
        )
        for key in self.last_quota:
            if key in result.headers:
                self.last_quota[key] = result.headers[key]
        return result

    @staticmethod
    def extract_h2h_prices(event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Devuelve `bookmaker_odds_raw`: lista de {bookmaker, last_update, outcomes}."""
        raw: List[Dict[str, Any]] = []
        for bookmaker in event.get("bookmakers", []) or []:
            h2h_market = next(
                (m for m in bookmaker.get("markets", []) or [] if m.get("key") == "h2h"), None
            )
            if h2h_market is None:
                continue
            raw.append(
                {
                    "bookmaker": bookmaker.get("key"),
                    "last_update": h2h_market.get("last_update"),
                    "outcomes": h2h_market.get("outcomes"),
                }
            )
        return raw
