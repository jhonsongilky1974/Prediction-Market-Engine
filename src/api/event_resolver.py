"""Resuelve un ticker de MERCADO de Kalshi a un `NormalizedRecord` real,
en vivo (Fase 5). Ver `HTTP_SERVICE_SPEC.md` §0/§2.

Cero lógica de matching/normalización nueva: reutiliza
`KalshiConnector`, `run_mlb_pipeline`/`run_tennis_pipeline` (Fase 1/2)
TAL CUAL. Este módulo solo decide QUÉ fecha/tour consultar (derivado
del propio ticker, ya en vivo) y CUÁL de los registros resultantes es
el pedido.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import KALSHI_SPORT_SERIES
from src.connectors.kalshi import KalshiConnector
from src.matching.market_matcher import local_date_from_kalshi_ticker
from src.models.schemas import NormalizedRecord, Sport
from src.observability.step_timer import log_step
from src.pipelines.mlb_pipeline import run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

logger = logging.getLogger(__name__)

_SERIES_TO_SPORT: Dict[str, Tuple[Sport, Optional[str]]] = {
    "KXMLBGAME": (Sport.MLB, None),
    "KXATPMATCH": (Sport.TENNIS, "atp"),
    "KXWTAMATCH": (Sport.TENNIS, "wta"),
}
assert set(_SERIES_TO_SPORT) == set(KALSHI_SPORT_SERIES.values())


class ResolverError(Exception):
    """Error honesto de resolución -- `status_code` decide la respuesta
    HTTP en `src/api/main.py`, `detail` es el mensaje real (nunca
    genérico) que se le devuelve al cliente."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ResolvedEvent:
    record: NormalizedRecord
    feature_inputs: Optional[Any]
    feature_cutoff: Optional[datetime]
    sport: Sport
    market_capture_ts: datetime
    """`capture_ts` del fetch en vivo de Kalshi usado para localizar
    este ticker -- fuente real de `Freshness.market_timestamp`."""
    enrichment_mode: str
    """"full" o "reduced" -- tenis desactiva el enriquecimiento SofaScore
    (`enrich_sofascore=False`, parámetro YA EXISTENTE de
    `run_tennis_pipeline`, ninguna lógica nueva) únicamente en la vía en
    vivo de `/analyze`, para mantener la latencia razonable (medido:
    >5min con enriquecimiento completo contra el volumen real de un día
    de ATP). La captura programada (LaunchAgent horario) no se toca,
    sigue enriqueciendo completo. MLB no tiene un lever equivalente
    -- siempre "full"."""


def _sport_and_tour_for_ticker(ticker: str) -> Tuple[Sport, Optional[str], str]:
    for series_prefix, (sport, tour) in _SERIES_TO_SPORT.items():
        if ticker.startswith(f"{series_prefix}-"):
            sport_key = "MLB" if sport == Sport.MLB else tour.upper()
            return sport, tour, sport_key
    raise ResolverError(
        400,
        f"ticker {ticker!r} no pertenece a ninguna serie de Kalshi soportada "
        f"({', '.join(KALSHI_SPORT_SERIES.values())}).",
    )


def _find_market(ticker: str, kalshi_events: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Devuelve `(kalshi_event, market)` cuyo `market["ticker"] == ticker`.
    Si el ticker coincide con un `event_ticker` (agrupa varios mercados,
    no representa un solo lado YES) se rechaza explícitamente en vez de
    adivinar cuál mercado se quiso decir."""
    for event in kalshi_events:
        for market in event.get("markets") or []:
            if market.get("ticker") == ticker:
                return event, market

    for event in kalshi_events:
        if event.get("event_ticker") == ticker:
            available = [m.get("ticker") for m in (event.get("markets") or [])]
            raise ResolverError(
                400,
                f"{ticker!r} es un event_ticker de Kalshi (agrupa varios mercados), no un ticker de "
                f"mercado -- /analyze necesita el ticker de un mercado concreto (un lado YES). "
                f"Mercados de este evento: {available}.",
            )

    raise ResolverError(
        404,
        f"ticker {ticker!r} no encontrado entre los eventos ACTUALMENTE ABIERTOS de Kalshi para esa "
        "serie -- puede haber cerrado, liquidado, o no existir.",
    )


def _date_from_market(market: Dict[str, Any], sport: Sport) -> str:
    """Fuente primaria: el segmento de fecha embebido en el propio
    `ticker` (`local_date_from_kalshi_ticker`, `src/matching/market_matcher.py`)
    -- ver su docstring / la de `_start_time_from_ticker` para la causa
    raíz real de por qué `occurrence_datetime` NO es la fecha del
    partido mientras este no ha ocurrido todavía (queda igual a
    `expected_expiration_time`, una liquidación esperada, no un inicio
    real -- verificado contra la API real de Kalshi). Fallback a
    `occurrence_datetime` únicamente cuando el ticker no trae segmento
    de fecha parseable (mismo comportamiento que antes de ese fix)."""
    ymd = local_date_from_kalshi_ticker(market.get("ticker"))
    if ymd is not None:
        year, month, day = ymd
        return f"{year:04d}-{month:02d}-{day:02d}" if sport == Sport.MLB else f"{year:04d}{month:02d}{day:02d}"

    raw = market.get("occurrence_datetime")
    if not raw:
        raise ResolverError(502, "el mercado de Kalshi encontrado no trae occurrence_datetime -- no se puede derivar la fecha del evento real.")
    try:
        occurrence = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResolverError(502, f"occurrence_datetime de Kalshi con formato inesperado: {raw!r} ({exc}).") from None

    return occurrence.strftime("%Y-%m-%d") if sport == Sport.MLB else occurrence.strftime("%Y%m%d")


def resolve_ticker(
    ticker: str,
    repository: Optional[Repository] = None,
    history_repository: Optional[HistoryRepository] = None,
    kalshi_connector: Optional[KalshiConnector] = None,
) -> ResolvedEvent:
    logger.info("-> resolve_ticker ticker=%r", ticker)
    resolve_started = time.monotonic()
    sport, tour, sport_key = _sport_and_tour_for_ticker(ticker)

    kalshi = kalshi_connector or KalshiConnector(repository=repository)
    with log_step(logger, "resolve_ticker.kalshi_get_all_events_for_sport", sport_key=sport_key):
        events_result = kalshi.get_all_events_for_sport(sport_key, status="open")
    if not events_result.ok:
        raise ResolverError(502, f"fallo al obtener eventos de Kalshi para {sport_key}: {events_result.error}")

    kalshi_events = KalshiConnector.extract_events(events_result.data)
    logger.info("resolve_ticker: kalshi_events count=%d", len(kalshi_events))

    with log_step(logger, "resolve_ticker._find_market", ticker=ticker, candidates=len(kalshi_events)):
        kalshi_event, market = _find_market(ticker, kalshi_events)

    with log_step(logger, "resolve_ticker._date_from_market", ticker=ticker):
        date = _date_from_market(market, sport)

    if sport == Sport.MLB:
        with log_step(logger, "resolve_ticker.run_mlb_pipeline", date=date):
            pipeline_result = run_mlb_pipeline(date, repository=repository, history_repository=history_repository)
        enrichment_mode = "full"
    else:
        with log_step(logger, "resolve_ticker.run_tennis_pipeline", tour=tour, date=date):
            pipeline_result = run_tennis_pipeline(
                tour, date, repository=repository, history_repository=history_repository, enrich_sofascore=False
            )
        enrichment_mode = "reduced"
    logger.info("resolve_ticker: pipeline_result records=%d", len(pipeline_result.records))

    for index, record in enumerate(pipeline_result.records):
        if record.market_id == ticker:
            feature_inputs = pipeline_result.feature_inputs_list[index] if pipeline_result.feature_inputs_list else None
            feature_cutoff = pipeline_result.feature_cutoffs[index] if pipeline_result.feature_cutoffs else None
            logger.info(
                "<- resolve_ticker OK ticker=%r elapsed_ms=%.1f",
                ticker,
                (time.monotonic() - resolve_started) * 1000,
            )
            return ResolvedEvent(
                record=record,
                feature_inputs=feature_inputs,
                feature_cutoff=feature_cutoff,
                sport=sport,
                market_capture_ts=events_result.capture_ts,
                enrichment_mode=enrichment_mode,
            )

    raise ResolverError(
        404,
        f"ticker {ticker!r} existe en Kalshi (evento {kalshi_event.get('title')!r}), pero el motor no "
        "encontró un match confidente contra los datos de MLB/tenis de esa fecha -- ver "
        "match_warnings del pipeline para el detalle (umbral de confianza no alcanzado).",
    )
