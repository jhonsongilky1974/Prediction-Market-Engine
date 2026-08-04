"""Mapeador Robinhood -> Kalshi. Ver `ROBINHOOD_KALSHI_MAPPER_SPEC.md` para
la evidencia real (DevTools, en vivo) que motiva este diseño.

Traduce el `symbol` de un contrato de Robinhood Prediction Markets
(campo real observado en `GET .../marketdata/event/contract/quotes/v1/`,
ej. `"MLBGAME-26AUG03WSHPHI-WSH"` o `"KXWTAMATCH-26AUG02PEGEAL-PEG"`) al
ticker de MERCADO real y vivo de Kalshi, para alimentar
`resolve_ticker()`/`analyze_ticker()` (Fase 5, `src/api/event_resolver.py`
y `src/api/analysis_service.py`) sin duplicar ninguna lógica de esos
módulos ni del pipeline de análisis.

Evidencia real (verificada en DevTools contra las APIs de Robinhood en
vivo, dos deportes, 2026-08-03):
  - Tenis (Pegula vs Eala, WTA): `symbol == "KXWTAMATCH-26AUG02PEGEAL-PEG"`
    -- coincide LITERAL, byte a byte, con el ticker real de Kalshi.
  - MLB (Washington vs Philadelphia): `symbol == "MLBGAME-26AUG03WSHPHI-WSH"`
    -- mismo formato pero SIN el prefijo `KX`, y sin el segmento de hora
    que Kalshi a veces inserta entre fecha y equipos para desambiguar
    doubleheaders (ejemplo real ya documentado en `CONTINUITY.md`:
    `KXMLBGAME-26AUG011507STLTOR-STL`).

Por eso NUNCA se confía ciegamente en el candidato derivado del `symbol`
-- se verifica contra los mercados abiertos y en vivo de Kalshi
(`KalshiConnector.get_all_events_for_sport`, ya existente) con tres
estrategias, probadas en orden, decisión explícita del usuario:

  1. EXACT: el candidato (symbol con `KX` al frente si no lo trae ya)
     coincide ticker a ticker con un mercado Kalshi realmente abierto.
  2. SUBSTRING: el candidato no coincide exacto -- se busca un ticker
     Kalshi abierto cuyo segmento central empiece con la fecha del
     candidato y termine con su bloque de equipos/jugadores (tolera el
     segmento de hora opcional de Kalshi sin necesidad de adivinar su
     valor). Rápida, determinista, sin matching difuso.
  3. EVENT_MATCHER: último recurso, delega en
     `src.matching.market_matcher.find_best_kalshi_event` (Fase 1, sin
     modificar) usando como nombres de participantes los códigos de 3
     letras derivados del propio `symbol` (Robinhood no expone nombres
     completos de equipos/jugadores en ninguna respuesta JSON -- ver
     spec). Por eso esta estrategia puede rendir peor que 1/2:
     `name_similarity` compara tokens/prefijos de texto, y un código como
     "WSH" no es un prefijo textual de "Washington"; es una limitación
     documentada, no un defecto a resolver aquí.

Sin match confidente en ninguna estrategia -> `MappingError` honesto
(mismo principio que `ResolverError`), nunca se fabrica un ticker. Cada
intento (éxito o fallo) se registra en el logger de este módulo para que
la estrategia efectivamente usada sea siempre auditable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT, KALSHI_SPORT_SERIES
from src.connectors.kalshi import KalshiConnector
from src.matching.market_matcher import _TICKER_DATE_SEGMENT_LENGTH as _DATE_SEGMENT_LENGTH
from src.matching.market_matcher import find_best_kalshi_event
from src.models.schemas import Sport
from src.storage.repository import Repository

logger = logging.getLogger(__name__)

_SERIES_TO_SPORT_KEY: Dict[str, str] = {
    "KXMLBGAME": "MLB",
    "KXATPMATCH": "ATP",
    "KXWTAMATCH": "WTA",
}
assert set(_SERIES_TO_SPORT_KEY) == set(KALSHI_SPORT_SERIES.values()), (
    "_SERIES_TO_SPORT_KEY (este módulo) debe cubrir exactamente las mismas series que "
    "KALSHI_SPORT_SERIES (config/settings.py) y _SERIES_TO_SPORT (src/api/event_resolver.py) -- "
    "las tres son fuentes independientes del mismo mapeo serie->deporte; una serie nueva en Kalshi "
    "requiere actualizar las tres o el mapeador Robinhood queda silenciosamente desincronizado."
)

# `_DATE_SEGMENT_LENGTH` reutiliza literalmente la constante de
# `market_matcher.py` (auditoría: ver CONTINUITY.md) -- antes había dos
# definiciones independientes del mismo valor (`YYMMMDD`, 7 caracteres)
# en dos módulos, sin ninguna garantía de que se mantuvieran sincronizadas.


class MappingError(Exception):
    """Error honesto de mapeo Robinhood -> Kalshi -- análogo a
    `ResolverError` de `event_resolver.py`. `status_code`/`detail` quedan
    listos para traducirse a HTTP si en el futuro se expone un endpoint."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class MappingResult:
    kalshi_ticker: str
    """Ticker de mercado Kalshi real y verificado en vivo -- lista para
    pasar directamente a `resolve_ticker()`/`analyze_ticker()`."""
    strategy: str
    """`"exact"` | `"substring"` | `"event_matcher"` -- qué estrategia
    encontró el match, para auditoría (ver también el log emitido)."""
    candidate: str
    """El ticker candidato construido a partir del `symbol` de Robinhood,
    antes de verificar contra Kalshi en vivo -- se conserva aunque la
    estrategia final haya sido substring/event_matcher."""
    sport: Sport
    sport_key: str


def _parse_symbol(symbol: str) -> tuple[str, str, str]:
    parts = symbol.split("-")
    if len(parts) != 3:
        raise MappingError(
            400,
            f"symbol de Robinhood con forma inesperada (se esperaban 3 segmentos separados por '-', "
            f"ej. 'MLBGAME-26AUG03WSHPHI-WSH'): {symbol!r}",
        )
    prefix, middle, side = parts
    if not prefix or not middle or not side:
        raise MappingError(400, f"symbol de Robinhood con algún segmento vacío: {symbol!r}")
    return prefix, middle, side


def _series_prefix_and_sport(prefix: str, symbol: str) -> tuple[str, Sport, str]:
    series_prefix = prefix if prefix.startswith("KX") else f"KX{prefix}"
    sport_key = _SERIES_TO_SPORT_KEY.get(series_prefix)
    if sport_key is None:
        raise MappingError(
            400,
            f"prefijo de serie {series_prefix!r} (derivado de symbol={symbol!r}) no es una de las series "
            f"Kalshi soportadas por este motor: {sorted(_SERIES_TO_SPORT_KEY)}.",
        )
    sport = Sport.MLB if sport_key == "MLB" else Sport.TENNIS
    return series_prefix, sport, sport_key


def _iter_markets(kalshi_events: List[Dict[str, Any]]):
    for event in kalshi_events:
        for market in event.get("markets") or []:
            yield event, market


def _exact_match(candidate: str, kalshi_events: List[Dict[str, Any]]) -> Optional[str]:
    for _, market in _iter_markets(kalshi_events):
        if market.get("ticker") == candidate:
            return candidate
    return None


def _substring_match(
    date_part: str, teams_part: str, side: str, kalshi_events: List[Dict[str, Any]]
) -> Optional[str]:
    matches: List[str] = []
    for _, market in _iter_markets(kalshi_events):
        ticker = market.get("ticker") or ""
        t_parts = ticker.split("-")
        if len(t_parts) != 3:
            continue
        _, t_middle, t_side = t_parts
        if t_side != side:
            continue
        if t_middle.startswith(date_part) and t_middle.endswith(teams_part):
            matches.append(ticker)

    if not matches:
        return None
    if len(matches) > 1:
        raise MappingError(
            409,
            f"ambiguo: {len(matches)} tickers Kalshi coinciden por subcadena para fecha={date_part!r} "
            f"equipos={teams_part!r} lado={side!r}: {matches} -- no se puede elegir sin fabricar un resultado.",
        )
    return matches[0]


def _derive_opponent_code(teams_part: str, side: str) -> Optional[str]:
    if teams_part.startswith(side):
        opponent = teams_part[len(side):]
    elif teams_part.endswith(side):
        opponent = teams_part[: -len(side)]
    else:
        return None
    return opponent or None


def map_robinhood_symbol_to_kalshi_ticker(
    robinhood_symbol: str,
    robinhood_start_time: Optional[datetime] = None,
    repository: Optional[Repository] = None,
    kalshi_connector: Optional[KalshiConnector] = None,
) -> MappingResult:
    """Traduce `robinhood_symbol` (campo `symbol` de
    `.../event/contract/quotes/v1/`) al ticker de mercado Kalshi real,
    verificado en vivo. `robinhood_start_time` es opcional -- solo se usa
    en la estrategia 3 (event_matcher), como señal adicional de
    proximidad temporal; su ausencia no bloquea las estrategias 1/2.

    Lanza `MappingError` (400/404/409/502) si no hay match confidente --
    nunca devuelve un ticker sin verificar contra Kalshi en vivo.
    """
    prefix, middle, side = _parse_symbol(robinhood_symbol)
    series_prefix, sport, sport_key = _series_prefix_and_sport(prefix, robinhood_symbol)
    candidate = f"{series_prefix}-{middle}-{side}"

    logger.info(
        "mapeo robinhood->kalshi iniciado: symbol=%s candidato=%s sport_key=%s",
        robinhood_symbol, candidate, sport_key,
    )

    kalshi = kalshi_connector or KalshiConnector(repository=repository)
    events_result = kalshi.get_all_events_for_sport(sport_key, status="open")
    if not events_result.ok:
        raise MappingError(
            502, f"fallo al obtener eventos de Kalshi para {sport_key}: {events_result.error}"
        )
    kalshi_events = KalshiConnector.extract_events(events_result.data)

    # Estrategia 1: EXACT
    exact_ticker = _exact_match(candidate, kalshi_events)
    if exact_ticker:
        logger.info(
            "mapeo robinhood->kalshi RESUELTO: symbol=%s estrategia=exact ticker=%s",
            robinhood_symbol, exact_ticker,
        )
        return MappingResult(exact_ticker, "exact", candidate, sport, sport_key)
    logger.info(
        "mapeo robinhood->kalshi: estrategia=exact SIN match para candidato=%s -- probando substring",
        candidate,
    )

    # Estrategia 2: SUBSTRING
    if len(middle) > _DATE_SEGMENT_LENGTH:
        date_part, teams_part = middle[:_DATE_SEGMENT_LENGTH], middle[_DATE_SEGMENT_LENGTH:]
        substring_ticker = _substring_match(date_part, teams_part, side, kalshi_events)
        if substring_ticker:
            logger.info(
                "mapeo robinhood->kalshi RESUELTO: symbol=%s estrategia=substring ticker=%s",
                robinhood_symbol, substring_ticker,
            )
            return MappingResult(substring_ticker, "substring", candidate, sport, sport_key)
        logger.info(
            "mapeo robinhood->kalshi: estrategia=substring SIN match para fecha=%s equipos=%s -- "
            "probando event_matcher",
            date_part, teams_part,
        )
    else:
        teams_part = ""
        logger.info(
            "mapeo robinhood->kalshi: estrategia=substring omitida (symbol=%s sin segmento de "
            "equipos/jugadores parseable tras la fecha) -- probando event_matcher",
            robinhood_symbol,
        )

    # Estrategia 3: EVENT_MATCHER (último recurso)
    opponent = _derive_opponent_code(teams_part, side) if teams_part else None
    if opponent:
        # Regresión real encontrada en auditoría (ver CONTINUITY.md): esta
        # llamada omitía `tolerance_minutes`, cayendo en el default
        # genérico de `find_best_kalshi_event` (90min, el valor de MLB) --
        # para tenis debía ser 240min (`EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT`,
        # ya usado correctamente en `tennis_pipeline.py`). Sin este fix,
        # esta estrategia (último recurso) podía rechazar por tiempo un
        # partido de tenis genuino con hasta 240min de desfase legítimo
        # (horario "por orden de salida a pista", ver config/settings.py).
        match = find_best_kalshi_event(
            side, opponent, robinhood_start_time, kalshi_events,
            tolerance_minutes=EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT[sport.value],
        )
        selected_ticker = (match.selected_market or {}).get("ticker") if match.selected_market else None
        if match.match_result.is_confident and selected_ticker:
            logger.info(
                "mapeo robinhood->kalshi RESUELTO: symbol=%s estrategia=event_matcher ticker=%s "
                "confidence=%.4f method=%s",
                robinhood_symbol, selected_ticker, match.match_result.confidence, match.match_result.method.value,
            )
            return MappingResult(selected_ticker, "event_matcher", candidate, sport, sport_key)
        logger.info(
            "mapeo robinhood->kalshi: estrategia=event_matcher SIN match confidente (lado=%s oponente=%s "
            "confidence=%.4f method=%s warnings=%s)",
            side, opponent, match.match_result.confidence, match.match_result.method.value, match.match_result.warnings,
        )
    else:
        logger.info(
            "mapeo robinhood->kalshi: estrategia=event_matcher omitida (no se pudo derivar el código del "
            "oponente a partir de symbol=%s)",
            robinhood_symbol,
        )

    logger.warning(
        "mapeo robinhood->kalshi FALLIDO tras 3 estrategias: symbol=%s candidato=%s sport_key=%s",
        robinhood_symbol, candidate, sport_key,
    )
    raise MappingError(
        404,
        f"no se encontró un ticker Kalshi confidente para symbol={robinhood_symbol!r} "
        f"(candidato={candidate!r}) tras probar exact/substring/event_matcher -- ver logs para el detalle "
        "de cada intento.",
    )
