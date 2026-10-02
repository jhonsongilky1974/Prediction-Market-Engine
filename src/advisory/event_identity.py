"""Identidad canónica de evento -- Tramo 5B. `event_id` (canónico, de
Market Analysis) es la identidad primaria; ticker/side/deporte/
participantes/market_profile se validan cruzados contra ella y contra
cada `Position` involucrada -- un prefijo de ticker por sí solo NUNCA
define el evento (decisión explícita, ver precheck de Tramo 5).

`market_profile` se define como el prefijo de serie Kalshi
(`config.settings.KALSHI_SPORT_SERIES`, ya canónico y reutilizado tal
cual -- no se inventa una taxonomía nueva). Los nombres de participantes
(`participant_a_display`/`participant_b_display`) son SOLO una
validación secundaria informativa -- nunca la clave primaria de
identidad.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from pydantic import ConfigDict, model_validator

from config.settings import KALSHI_SPORT_SERIES
from src.models.schemas import Sport, StrictModel
from src.positions.schemas import Position
from src.signals.signal_schema import Side

_SERIES_PREFIX_TO_SPORT: dict[str, Sport] = {
    "KXMLBGAME": Sport.MLB,
    "KXATPMATCH": Sport.TENNIS,
    "KXWTAMATCH": Sport.TENNIS,
}
assert set(_SERIES_PREFIX_TO_SPORT) == set(KALSHI_SPORT_SERIES.values()), (
    "_SERIES_PREFIX_TO_SPORT (este módulo) debe cubrir exactamente las mismas series que "
    "KALSHI_SPORT_SERIES (config/settings.py) -- una serie nueva en Kalshi requiere actualizar "
    "ambas o la identidad de evento de Advisory queda silenciosamente desincronizada."
)


class EventIdentityMismatchError(Exception):
    """Contradicción de integridad entre `EventIdentity` declarada y una
    `Position` real -- fail-closed explícito, nunca se descarta la
    Position en silencio."""


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def derive_market_profile(kalshi_ticker: str) -> str:
    """Prefijo de serie Kalshi (antes del primer `-`), p.ej.
    `KXMLBGAME-26AUG03WSHPHI-WSH` -> `KXMLBGAME`."""
    return kalshi_ticker.split("-")[0]


class EventIdentity(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    sport: Sport
    kalshi_ticker_side_a: str
    kalshi_ticker_side_b: str
    side_a: Side
    side_b: Side
    participant_a_canonical: Optional[str] = None
    participant_b_canonical: Optional[str] = None
    participant_a_display: Optional[str] = None
    participant_b_display: Optional[str] = None
    scheduled_start_time: datetime
    market_profile: str

    @model_validator(mode="after")
    def _validate_invariants(self) -> "EventIdentity":
        if not self.event_id.strip():
            raise ValueError("event_id no puede estar vacío")
        _require_utc_aware(self.scheduled_start_time, "scheduled_start_time")
        if self.side_a == self.side_b:
            raise ValueError(f"side_a y side_b no pueden ser el mismo lado: {self.side_a.value}")
        if self.kalshi_ticker_side_a == self.kalshi_ticker_side_b:
            raise ValueError("kalshi_ticker_side_a y kalshi_ticker_side_b no pueden ser idénticos")

        expected_sport = _SERIES_PREFIX_TO_SPORT.get(self.market_profile)
        if expected_sport is None:
            raise ValueError(
                f"market_profile={self.market_profile!r} no es una serie Kalshi soportada: "
                f"{sorted(_SERIES_PREFIX_TO_SPORT)}"
            )
        if expected_sport != self.sport:
            raise ValueError(
                f"market_profile={self.market_profile!r} corresponde a sport={expected_sport.value}, "
                f"pero se declaró sport={self.sport.value} -- contradicción de identidad"
            )
        for ticker, label in (
            (self.kalshi_ticker_side_a, "kalshi_ticker_side_a"),
            (self.kalshi_ticker_side_b, "kalshi_ticker_side_b"),
        ):
            if derive_market_profile(ticker) != self.market_profile:
                raise ValueError(
                    f"{label}={ticker!r} no comparte el prefijo de serie declarado en "
                    f"market_profile={self.market_profile!r}"
                )
        return self

    @property
    def ticker_by_side(self) -> dict:
        return {self.side_a: self.kalshi_ticker_side_a, self.side_b: self.kalshi_ticker_side_b}


def validate_event_identity_consistency(
    identity: EventIdentity, positions: Sequence[Position], *, now: Optional[datetime] = None
) -> None:
    """Fail-closed: cualquier `Position` cuyo `kalshi_ticker`/`sport` no
    encaje EXACTAMENTE con la identidad declarada produce
    `EventIdentityMismatchError` -- nunca se descarta esa Position en
    silencio ni se continúa el cálculo con datos contradictorios."""
    valid_tickers = {identity.kalshi_ticker_side_a, identity.kalshi_ticker_side_b}
    for position in positions:
        if position.kalshi_ticker not in valid_tickers:
            raise EventIdentityMismatchError(
                f"Position {position.position_id!r} tiene kalshi_ticker={position.kalshi_ticker!r}, "
                f"que no pertenece a event_id={identity.event_id!r} "
                f"(tickers esperados: {sorted(valid_tickers)})"
            )
        if position.sport != identity.sport:
            raise EventIdentityMismatchError(
                f"Position {position.position_id!r} tiene sport={position.sport.value}, "
                f"contradice sport={identity.sport.value} declarado para event_id={identity.event_id!r}"
            )
