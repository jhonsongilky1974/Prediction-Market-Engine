"""Market matching: dado un evento normalizado (MLB/tenis) y la lista de
eventos de Kalshi de la serie correspondiente, encuentra el evento de Kalshi
que representa el mismo partido/juego y selecciona, dentro de él, el
mercado (ticker) cuyo lado YES corresponde a `participant_a`.

Reutiliza `event_matcher` para la decisión de "es el mismo evento" —
market matching no vuelve a implementar su propia heurística de nombres.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE, EVENT_TIME_MATCH_TOLERANCE_MINUTES
from src.matching.event_matcher import MatchResult, match_event, name_similarity
from src.normalization.market_normalizer import normalize_kalshi_market
from src.quality.validators import validate_schema_sanity

logger = logging.getLogger(__name__)

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
    markets = kalshi_event.get("markets") or []
    if not markets:
        return None
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
        best.selected_market, best.market_selection_warning = _select_market(
            best.kalshi_event, source_participant_a
        )

    return best


def _no_candidates_result() -> MatchResult:
    from src.models.schemas import MatchMethod

    return MatchResult(0.0, MatchMethod.NO_MATCH, ["no hay eventos de Kalshi candidatos"], needs_review=True)


def _select_market(
    kalshi_event: Dict[str, Any], participant_a: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    markets = kalshi_event.get("markets") or []
    if not markets:
        return None, "el evento de Kalshi no tiene mercados anidados"
    if not participant_a:
        return markets[0], "participant_a ausente; se tomó el primer mercado por defecto"

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
    return best_market, warning


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
    missing.extend(market_norm.missing_fields)
    if match.market_selection_warning:
        record.data_quality.match_warnings.append(match.market_selection_warning)
