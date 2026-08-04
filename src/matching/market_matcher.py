"""Market matching: dado un evento normalizado (MLB/tenis) y la lista de
eventos de Kalshi de la serie correspondiente, encuentra el evento de Kalshi
que representa el mismo partido/juego y selecciona, dentro de él, el
mercado (ticker) cuyo lado YES corresponde a `participant_a`.

Reutiliza `event_matcher` para la decisión de "es el mismo evento" —
market matching no vuelve a implementar su propia heurística de nombres.

Extensión aditiva (Fase 3, resolución de D-2 -- ver CONTINUITY.md): la
confianza de esa selección de lado YES (antes calculada y descartada,
solo usada para decidir si emitir una advertencia de texto) ahora se
expone también como número en `KalshiEventMatch.market_selection_confidence`
y se persiste en `NormalizedRecord.data_quality.side_selection_confidence`
vía `apply_kalshi_match`. Ningún comportamiento de selección/matching
existente cambia -- mismo mercado se sigue seleccionando exactamente
igual que antes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE, EVENT_TIME_MATCH_TOLERANCE_MINUTES
from src.matching.event_matcher import MatchResult, match_event, name_similarity
from src.normalization.market_normalizer import normalize_kalshi_market
from src.quality.validators import validate_schema_sanity

logger = logging.getLogger(__name__)

_TICKER_DATE_SEGMENT_LENGTH = 7
"""Longitud fija del segmento de fecha embebido en el ticker de Kalshi,
forma `YYMMMDD` (ej. `26AUG03`) -- mismo formato ya documentado y usado
en `src/api/robinhood_mapper.py`."""

_TICKER_TIME_SEGMENT_LENGTH = 4
"""Longitud del segmento de hora `HHMM` opcional que Kalshi inserta entre
la fecha y los equipos/jugadores para desambiguar partidos del mismo día
entre los mismos participantes (doubleheaders) -- ver
`src/api/robinhood_mapper.py` para la evidencia real que documentó este
formato."""

_TICKER_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
"""Mapa explícito (no `datetime.strptime("%b")`, dependiente del locale
del sistema) -- el segmento de fecha del ticker siempre usa abreviaturas
de mes en inglés, ej. "AUG", independientemente del locale de la
máquina que ejecuta el motor."""

_TICKER_TIMEZONE = ZoneInfo("America/New_York")
"""Hora local embebida en los tickers de Kalshi (MLB/tenis) -- verificado
contra evidencia real (ver `_start_time_from_ticker`): la hora "1840" del
ticker `KXMLBGAME-26AUG031840WSHPHI-WSH` coincide, convertida desde
`America/New_York`, con el `start_time` real de MLB Stats API
(2026-08-03T22:40:00Z) para las 8 partidos MLB abiertos verificados en
vivo el 2026-08-03. `zoneinfo` resuelve el offset EDT/EST correcto según
la fecha real -- la temporada de MLB (marzo-noviembre) cae casi en su
totalidad dentro del horario de verano de EE.UU."""


def _parse_ticker_date_segment(date_segment: str) -> Optional[Tuple[int, int, int]]:
    """`(year, month, day)` -- ej. `"26AUG03"` -> `(2026, 8, 3)`. `None` si
    `date_segment` no tiene la forma `YYMMMDD` esperada o no es una fecha
    real (ej. día 32). Extraído como función propia (compartida por
    `_start_time_from_ticker` y `local_date_from_kalshi_ticker`) para no
    duplicar el parseo del segmento de fecha en dos sitios."""
    if len(date_segment) != _TICKER_DATE_SEGMENT_LENGTH:
        return None
    month = _TICKER_MONTH_ABBR.get(date_segment[2:5].upper())
    if month is None:
        return None
    try:
        year = 2000 + int(date_segment[0:2])
        day = int(date_segment[5:7])
        datetime(year, month, day)  # valida que sea un día real del mes/año
    except ValueError:
        return None
    return year, month, day


def local_date_from_kalshi_ticker(ticker: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """`(year, month, day)` de la fecha LOCAL (huso horario embebido en el
    propio ticker -- ver `_start_time_from_ticker`) del partido
    representado por `ticker`, ej. `"KXMLBGAME-26AUG031840WSHPHI-WSH"` ->
    `(2026, 8, 3)`. A diferencia del resto de funciones de este módulo,
    es pública: `src/api/event_resolver.py` la necesita para decidir qué
    día consultarle a MLB Stats API/ESPN -- ver `_start_time_from_ticker`
    para la causa raíz real de por qué `occurrence_datetime` no sirve
    para esto (mismo problema, mismo fix: el ticker es la fuente
    confiable, `occurrence_datetime` un valor de liquidación esperada,
    no de inicio real). `None` si el ticker no trae el segmento de fecha
    esperado."""
    if not ticker:
        return None
    parts = ticker.split("-")
    if len(parts) != 3:
        return None
    _, middle, _side = parts
    if len(middle) < _TICKER_DATE_SEGMENT_LENGTH:
        return None
    return _parse_ticker_date_segment(middle[:_TICKER_DATE_SEGMENT_LENGTH])


def _start_time_from_ticker(ticker: Optional[str]) -> Optional[datetime]:
    """Deriva el start_time real del partido a partir del segmento de
    fecha+hora embebido en el propio ticker de mercado de Kalshi (ej.
    `KXMLBGAME-26AUG031840WSHPHI-WSH` -> 2026-08-03 18:40 hora del este
    de EE.UU. -> 2026-08-03T22:40:00Z).

    **Por qué existe esta función** (causa raíz real, verificada, no
    especulada): el campo `occurrence_datetime` de un mercado de Kalshi
    documenta oficialmente "The recorded datetime when the underlying
    event occurred, if available" (docs.kalshi.com/api-reference/market/
    get-market.md) -- es decir, se puebla DESPUÉS de que el evento ya
    ocurrió. Verificado contra la API real de Kalshi en vivo (2026-08-03):
    para TODO mercado MLB/ATP/WTA todavía abierto (el partido no ha
    ocurrido), `occurrence_datetime` es literalmente idéntico a
    `expected_expiration_time` ("Time when this market is expected to
    expire") -- un valor provisional de LIQUIDACIÓN esperada, no de
    INICIO real. Para MLB esto se tradujo en una diferencia constante de
    180 minutos (duración típica asumida de un partido) frente al
    `start_time` real de MLB Stats API, en el 100% (8/8) de los partidos
    abiertos verificados -- suficiente para exceder
    `EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["MLB"]` (90min) siempre,
    bloqueando la confirmación del match pese a que el nombre del
    candidato correcto ya se había identificado.

    Ningún campo estructurado de la API de Kalshi (evento o mercado)
    documenta la hora de inicio programada (verificado contra el schema
    real de `GET /events`/`GET /markets/{ticker}`) -- el propio ticker
    (verificado, no asumido: coincide exacto con `start_time` de MLB
    Stats API en los 8/8 casos reales probados) es la fuente estructurada
    más confiable disponible.

    Devuelve `None` si el ticker no trae forma esperada o no incluye el
    segmento de hora (ej. tickers de tenis reales observados hoy -- ver
    `CONTINUITY.md` -- que no lo embeben) -- el llamador cae de vuelta a
    `occurrence_datetime`, mismo comportamiento que antes de este fix.
    """
    if not ticker:
        return None
    parts = ticker.split("-")
    if len(parts) != 3:
        return None
    _, middle, _side = parts
    if len(middle) < _TICKER_DATE_SEGMENT_LENGTH + _TICKER_TIME_SEGMENT_LENGTH:
        return None

    date_segment = middle[:_TICKER_DATE_SEGMENT_LENGTH]
    time_segment = middle[
        _TICKER_DATE_SEGMENT_LENGTH : _TICKER_DATE_SEGMENT_LENGTH + _TICKER_TIME_SEGMENT_LENGTH
    ]
    if not time_segment.isdigit():
        return None

    ymd = _parse_ticker_date_segment(date_segment)
    if ymd is None:
        return None
    year, month, day = ymd
    try:
        hour, minute = int(time_segment[0:2]), int(time_segment[2:4])
        naive_local = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    return naive_local.replace(tzinfo=_TICKER_TIMEZONE).astimezone(timezone.utc)

# Claves top-level que el payload de un mercado de Kalshi debe traer según
# el schema real observado (ver src/connectors/kalshi.py). Sirve para
# detectar cambios de schema de la API no documentada -- antes
# `validate_schema_sanity` existía pero ningún llamador la invocaba nunca.
KALSHI_MARKET_EXPECTED_KEYS = [
    "ticker",
    "event_ticker",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "no_bid_dollars",
    "no_ask_dollars",
    "occurrence_datetime",
    "close_time",
    "expected_expiration_time",
]

# Campos del esquema normalizado que dependen del mercado de Kalshi
# seleccionado. Cuando el match NO es confidente (ver MatchResult.is_confident)
# estos se dejan sin poblar y se registran aquí como MISSING explícito, en
# vez de arriesgarse a adjuntar precios de un mercado probablemente
# equivocado (ver `apply_kalshi_match`).
MARKET_DEPENDENT_FIELDS = [
    "market.yes_bid",
    "market.yes_ask",
    "market.no_bid",
    "market.no_ask",
    "market_close_time",
    "expected_settlement_time",
]


@dataclass
class KalshiEventMatch:
    kalshi_event: Optional[Dict[str, Any]]
    match_result: MatchResult
    selected_market: Optional[Dict[str, Any]] = None
    market_selection_warning: Optional[str] = None
    market_selection_confidence: Optional[float] = None
    """Similitud [0,1] entre participant_a y el yes_sub_title del mercado
    seleccionado (mismo best_score que ya calculaba _select_market, ahora
    expuesto en vez de descartado -- ver DataQuality.side_selection_confidence,
    resolución de D-2). None si no se pudo puntuar (sin mercados, o
    participant_a ausente)."""


def _kalshi_event_participants(kalshi_event: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Deriva (participant_a, participant_b) del título del evento de Kalshi,
    ej. "Merida vs Jacquet" o "Kansas City vs Detroit"."""
    title = kalshi_event.get("title") or ""
    if " vs " in title:
        a, b = title.split(" vs ", 1)
        return a.strip(), b.strip()
    markets = kalshi_event.get("markets") or []
    if len(markets) >= 2:
        return markets[0].get("yes_sub_title"), markets[1].get("yes_sub_title")
    if len(markets) == 1:
        return markets[0].get("yes_sub_title"), markets[0].get("no_sub_title")
    return None, None


def _kalshi_event_start_time(kalshi_event: Dict[str, Any]) -> Optional[datetime]:
    """Fuente primaria: el segmento de hora embebido en el propio ticker
    (`_start_time_from_ticker`) -- ver su docstring para la causa raíz
    real de por qué `occurrence_datetime` no es confiable como start_time
    mientras el evento no ha ocurrido todavía. Fallback a
    `occurrence_datetime` únicamente cuando el ticker no trae segmento de
    hora parseable (mismo comportamiento que antes de ese fix)."""
    markets = kalshi_event.get("markets") or []
    if not markets:
        return None

    from_ticker = _start_time_from_ticker(markets[0].get("ticker"))
    if from_ticker is not None:
        return from_ticker

    raw = markets[0].get("occurrence_datetime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def find_best_kalshi_event(
    source_participant_a: Optional[str],
    source_participant_b: Optional[str],
    source_start_time: Optional[datetime],
    kalshi_events: List[Dict[str, Any]],
    tolerance_minutes: int = EVENT_TIME_MATCH_TOLERANCE_MINUTES,
    min_confidence: float = EVENT_NAME_MATCH_MIN_CONFIDENCE,
) -> KalshiEventMatch:
    best: Optional[KalshiEventMatch] = None

    for kalshi_event in kalshi_events:
        # Un único evento de Kalshi con forma inesperada (schema-drift, campo
        # no-dict, etc.) no debe tumbar el matching de TODO el lote: se
        # descarta ese candidato puntual y se sigue con el resto.
        try:
            target_a, target_b = _kalshi_event_participants(kalshi_event)
            target_start = _kalshi_event_start_time(kalshi_event)

            result = match_event(
                source_participant_a,
                source_participant_b,
                source_start_time,
                target_a,
                target_b,
                target_start,
                tolerance_minutes=tolerance_minutes,
                min_confidence=min_confidence,
            )
        except (AttributeError, TypeError, KeyError) as exc:
            logger.warning("candidato de Kalshi con forma inesperada, se descarta: %s", exc)
            continue

        if best is None or result.confidence > best.match_result.confidence:
            best = KalshiEventMatch(kalshi_event=kalshi_event, match_result=result)

    if best is None:
        return KalshiEventMatch(kalshi_event=None, match_result=_no_candidates_result())

    if best.kalshi_event is not None:
        best.selected_market, best.market_selection_warning, best.market_selection_confidence = _select_market(
            best.kalshi_event, source_participant_a
        )

    return best


def _no_candidates_result() -> MatchResult:
    from src.models.schemas import MatchMethod

    return MatchResult(0.0, MatchMethod.NO_MATCH, ["no hay eventos de Kalshi candidatos"], needs_review=True)


def _select_market(
    kalshi_event: Dict[str, Any], participant_a: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[float]]:
    """Devuelve (mercado_seleccionado, advertencia_o_None, confianza_o_None).
    `confianza` es la similitud [0,1] entre `participant_a` y el
    `yes_sub_title` del mercado elegido -- None en los dos casos en que no
    hay una puntuación real que reportar (sin mercados; o participant_a
    ausente, caso en que se toma markets[0] a ciegas, sin comparar nada).
    Resolución de D-2 (ver CONTINUITY.md): antes este score se calculaba y
    se descartaba, ahora se expone vía DataQuality.side_selection_confidence
    (apply_kalshi_match)."""
    markets = kalshi_event.get("markets") or []
    if not markets:
        return None, "el evento de Kalshi no tiene mercados anidados", None
    if not participant_a:
        return markets[0], "participant_a ausente; se tomó el primer mercado por defecto", None

    best_market = None
    best_score = -1.0
    for market in markets:
        score = name_similarity(participant_a, market.get("yes_sub_title"))
        if score > best_score:
            best_score = score
            best_market = market

    warning = None
    if best_score < 0.72:
        warning = f"selección de mercado por lado YES incierta (similitud {best_score:.2f})"
    return best_market, warning, best_score


def apply_kalshi_match(record: Any, match: KalshiEventMatch, missing: List[str]) -> None:
    """Aplica el resultado de `find_best_kalshi_event` a un `NormalizedRecord`.

    Regla central (ver MatchResult.is_confident): los datos de mercado
    (bid/ask/timestamps/market_id) SOLO se adjuntan al registro cuando el
    match es confidente (EXACT_NAME_TIME/FUZZY_NAME_TIME). Si el mejor
    candidato disponible es NEEDS_REVIEW o NO_MATCH, el registro NUNCA lleva
    precios de ese mercado -- quedan NULL + MISSING, y el ticker candidato
    queda solo como texto en `match_warnings`, para que un humano pueda
    revisarlo sin que un consumidor downstream confunda un "mejor intento"
    con un match confirmado. Antes de este fix, CUALQUIER candidato (incluso
    con confidence=0.05) se adjuntaba al registro como si fuera real.
    """
    record.data_quality.match_confidence = match.match_result.confidence
    record.data_quality.match_method = match.match_result.method
    record.data_quality.match_warnings = list(match.match_result.warnings)
    record.data_quality.needs_review = match.match_result.needs_review

    if match.selected_market is None:
        missing.append("market_id")
        record.data_quality.match_warnings.append("sin mercado de Kalshi seleccionable")
        return

    if not match.match_result.is_confident:
        candidate_ticker = match.selected_market.get("ticker")
        record.data_quality.match_warnings.append(
            f"mejor candidato Kalshi NO confirmado (confidence={match.match_result.confidence:.2f}, "
            f"method={match.match_result.method.value}): ticker={candidate_ticker!r} -- "
            "no se adjuntan datos de mercado, requiere revisión humana"
        )
        missing.append("market_id")
        missing.extend(MARKET_DEPENDENT_FIELDS)
        return

    schema_warnings = validate_schema_sanity(match.selected_market, KALSHI_MARKET_EXPECTED_KEYS, "kalshi_market")
    if schema_warnings:
        record.data_quality.validation_errors.extend(schema_warnings)

    market_norm = normalize_kalshi_market(match.selected_market)
    record.market = market_norm.market
    record.market_id = market_norm.ticker
    record.source_market_id = market_norm.ticker
    record.source_event_ids["kalshi"] = market_norm.event_ticker or ""
    record.market_close_time = market_norm.market_close_time
    record.expected_settlement_time = market_norm.expected_settlement_time
    record.actual_settlement_time = market_norm.actual_settlement_time
    record.data_quality.side_selection_confidence = match.market_selection_confidence
    missing.extend(market_norm.missing_fields)
    if match.market_selection_warning:
        record.data_quality.match_warnings.append(match.market_selection_warning)
