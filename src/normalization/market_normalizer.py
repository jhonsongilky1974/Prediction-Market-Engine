"""Normaliza mercados crudos de Kalshi al esquema único (`MarketData` +
timestamps). Ver reglas temporales y de precio en las instrucciones de
Fase 1 y en `src/connectors/kalshi.py`.

Nunca inventa valores: si un campo no está en el payload, queda en None y
se añade a `missing_fields` con el prefijo `market.`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.models.schemas import MarketData


def _parse_dollar_string(value: Any) -> Optional[float]:
    """Kalshi expresa precios como strings tipo "0.4000". No se reconstruyen
    a partir de otros campos: si falta o no es parseable, devuelve None."""
    if value is None or value == "":
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class KalshiMarketNormalization:
    def __init__(
        self,
        market: MarketData,
        start_time: Optional[datetime],
        market_close_time: Optional[datetime],
        expected_settlement_time: Optional[datetime],
        actual_settlement_time: Optional[datetime],
        ticker: Optional[str],
        event_ticker: Optional[str],
        status_raw: Optional[str],
        missing_fields: List[str],
    ):
        self.market = market
        self.start_time = start_time
        self.market_close_time = market_close_time
        self.expected_settlement_time = expected_settlement_time
        self.actual_settlement_time = actual_settlement_time
        self.ticker = ticker
        self.event_ticker = event_ticker
        self.status_raw = status_raw
        self.missing_fields = missing_fields


def normalize_kalshi_market(market_raw: Dict[str, Any]) -> KalshiMarketNormalization:
    missing: List[str] = []

    def req(raw_field: str, normalized_field: str) -> Any:
        """Lee `raw_field` del payload de Kalshi; si falta, registra el
        nombre del campo tal como aparece en el esquema normalizado
        (`normalized_field`), no el nombre crudo de la fuente."""
        val = market_raw.get(raw_field)
        if val is None or val == "":
            missing.append(normalized_field)
        return val

    yes_bid = _parse_dollar_string(req("yes_bid_dollars", "market.yes_bid"))
    yes_ask = _parse_dollar_string(req("yes_ask_dollars", "market.yes_ask"))
    no_bid = _parse_dollar_string(req("no_bid_dollars", "market.no_bid"))
    no_ask = _parse_dollar_string(req("no_ask_dollars", "market.no_ask"))
    last_price = _parse_dollar_string(req("last_price_dollars", "market.last_price"))

    spread_yes = round(yes_ask - yes_bid, 4) if yes_ask is not None and yes_bid is not None else None
    spread_no = round(no_ask - no_bid, 4) if no_ask is not None and no_bid is not None else None

    volume = _parse_dollar_string(market_raw.get("volume_fp"))
    volume_24h = _parse_dollar_string(market_raw.get("volume_24h_fp"))
    open_interest = _parse_dollar_string(market_raw.get("open_interest_fp"))
    liquidity = _parse_dollar_string(market_raw.get("liquidity_dollars"))

    # No hay campo de fee en el payload de Kalshi observado (ver kalshi.py).
    # Se deja NULL explícitamente hasta verificar la fórmula real de fees.
    exchange_fee = None
    fee_type = market_raw.get("fee_type")
    if fee_type is None:
        missing.append("market.fee_type")

    # MARKET_PRICE_EXECUTABLE: cada ticker de Kalshi ya representa una
    # posición YES concreta (ej. "equipo X gana"), así que el precio
    # ejecutable por defecto para abrir esa posición YES es YES_ASK, según
    # la regla "para comprar YES -> YES_ASK" de las instrucciones de Fase 1.
    market_price_executable = yes_ask

    market = MarketData(
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        last_price=last_price,
        spread_yes=spread_yes,
        spread_no=spread_no,
        volume=volume,
        volume_24h=volume_24h,
        open_interest=open_interest,
        liquidity=liquidity,
        exchange_fee=exchange_fee,
        fee_type=fee_type,
        market_price_executable=market_price_executable,
    )

    start_time = _parse_iso_timestamp(req("occurrence_datetime", "start_time"))
    market_close_time = _parse_iso_timestamp(req("close_time", "market_close_time"))
    expected_settlement_time = _parse_iso_timestamp(req("expected_expiration_time", "expected_settlement_time"))

    # ACTUAL_SETTLEMENT_TIME: el payload de /markets no trae un timestamp de
    # liquidación real distinto de expiration_time. Se deja NULL hasta que
    # se implemente una fuente de evidencia de liquidación explícita.
    actual_settlement_time = None
    missing.append("actual_settlement_time")

    return KalshiMarketNormalization(
        market=market,
        start_time=start_time,
        market_close_time=market_close_time,
        expected_settlement_time=expected_settlement_time,
        actual_settlement_time=actual_settlement_time,
        ticker=market_raw.get("ticker"),
        event_ticker=market_raw.get("event_ticker"),
        status_raw=market_raw.get("status"),
        missing_fields=missing,
    )
