"""Conector Kalshi (API pública, read-only, sin autenticación para market data).

Series soportadas en Fase 1: KXMLBGAME, KXATPMATCH, KXWTAMATCH.

Payload real verificado (2026-07): los campos de precio llegan como strings
con sufijo `_dollars` (ej. `yes_ask_dollars`) y los de tamaño/volumen con
sufijo `_fp` (ej. `volume_fp`). No existe un campo `fee_type` ni de fee en el
payload actual — por eso EXCHANGE_FEE/FEE_TYPE quedan NULL (ver market_normalizer).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from config.settings import KALSHI_BASE_URL, KALSHI_POLICY, KALSHI_SPORT_SERIES
from src.connectors.base_client import BaseHttpClient, FetchResult

logger = logging.getLogger(__name__)


class KalshiConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = KALSHI_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("kalshi", KALSHI_POLICY, repository)

    def get_events(
        self,
        series_ticker: str,
        status: str = "open",
        with_nested_markets: bool = True,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> FetchResult:
        params: Dict[str, Any] = {
            "series_ticker": series_ticker,
            "status": status,
            "with_nested_markets": str(with_nested_markets).lower(),
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor
        return self._client.get_json(
            f"{self.base_url}/events", params=params, endpoint_label=f"events_{series_ticker}"
        )

    def get_markets(
        self,
        series_ticker: str,
        status: str = "open",
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> FetchResult:
        params: Dict[str, Any] = {"series_ticker": series_ticker, "status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._client.get_json(
            f"{self.base_url}/markets", params=params, endpoint_label=f"markets_{series_ticker}"
        )

    def get_events_for_sport(self, sport_key: str, status: str = "open") -> FetchResult:
        """`sport_key` en {"MLB", "ATP", "WTA"} -> series ticker correspondiente.
        Una sola página (hasta `limit` eventos, por defecto 200). Para el uso
        real del pipeline preferir `get_all_events_for_sport`, que sigue el
        cursor de paginación."""
        series_ticker = KALSHI_SPORT_SERIES[sport_key]
        return self.get_events(series_ticker, status=status)

    def get_all_events_for_sport(
        self, sport_key: str, status: str = "open", max_pages: int = 10
    ) -> FetchResult:
        """Sigue el `cursor` de paginación de Kalshi hasta agotar resultados
        o alcanzar `max_pages` (nunca un loop agresivo/sin límite).

        Antes solo se pedía la primera página (`limit=200`, sin seguir
        `cursor`): con una serie que tenga más de 200 eventos abiertos a la
        vez (torneos grandes de tenis con muchos partidos programados con
        días de antelación es un caso real observado), el matching operaba
        en silencio sobre un subconjunto incompleto, sin ningún error ni
        aviso. Devuelve un `FetchResult` sintético cuyo `data["events"]` es
        la unión de todas las páginas obtenidas con éxito. Si una página a
        mitad de la paginación falla, se conservan las páginas ya
        obtenidas (no se descartan) pero `ok=False` y `error` documentan
        que la lista quedó incompleta -- nunca se finge que está completa.
        """
        fetch_started = time.monotonic()
        logger.info("-> get_all_events_for_sport sport_key=%r status=%r max_pages=%d", sport_key, status, max_pages)
        series_ticker = KALSHI_SPORT_SERIES[sport_key]
        all_events: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        last_result: Optional[FetchResult] = None

        for page in range(max_pages):
            page_started = time.monotonic()
            result = self.get_events(series_ticker, status=status, cursor=cursor)
            logger.info(
                "get_all_events_for_sport: page=%d/%d ok=%r elapsed_ms=%.1f",
                page + 1, max_pages, result.ok, (time.monotonic() - page_started) * 1000,
            )
            last_result = result
            if not result.ok:
                logger.info(
                    "<- get_all_events_for_sport FAILED sport_key=%r page=%d elapsed_ms=%.1f",
                    sport_key, page + 1, (time.monotonic() - fetch_started) * 1000,
                )
                return FetchResult(
                    ok=False,
                    status_code=result.status_code,
                    data={"events": all_events},
                    error=f"paginacion_incompleta: {result.error}",
                    url=result.url,
                    capture_ts=result.capture_ts,
                )
            events = self.extract_events(result.data)
            all_events.extend(events)
            cursor = (result.data or {}).get("cursor")
            if not cursor or not events:
                break

        logger.info(
            "<- get_all_events_for_sport OK sport_key=%r total_events=%d elapsed_ms=%.1f",
            sport_key, len(all_events), (time.monotonic() - fetch_started) * 1000,
        )
        return FetchResult(
            ok=True,
            status_code=last_result.status_code if last_result else None,
            data={"events": all_events},
            error=None,
            url=last_result.url if last_result else "",
            capture_ts=last_result.capture_ts if last_result else None,  # type: ignore[arg-type]
        )

    @staticmethod
    def extract_events(events_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(events_payload, dict):
            return []
        return events_payload.get("events", []) or []
