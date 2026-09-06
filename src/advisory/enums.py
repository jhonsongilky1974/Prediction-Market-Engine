"""Enums cerrados de Trading Advisory -- Tramo 5B (Position Management
Advisory). Mismo principio que `src.positions.enums`: taxonomía cerrada,
con un valor `OTHER` de escape donde aplica -- nunca un string libre
como taxonomía primaria. Ningún valor de este módulo es
`ENTER`/`WATCH`/`PASS` -- Tramo 5B no expone esa taxonomía interna en
ningún JSON visible (decisión arquitectónica explícita del usuario).
"""
from __future__ import annotations

from enum import Enum


class Tp1RecoveryKind(str, Enum):
    """EXACT: capital_invested/capital_recovered/fee de la venta candidata
    son todos KNOWN -- la cantidad a vender es una recuperación exacta.
    CONSERVATIVE_ESTIMATE: al menos una fee involucrada no es KNOWN, pero
    existe una cota conservadora defendible (fee ESTIMATED explícita, o
    derivada empíricamente del historial KNOWN de fills de esta misma
    posición) -- el resultado es `provisional`/`requires_recalculation`.
    UNAVAILABLE: no hay target de salida, o hay una fee UNKNOWN sin
    ninguna cota conservadora derivable -- no se fabrica ninguna
    cantidad, `contracts_to_sell` es `None`."""

    EXACT = "EXACT"
    CONSERVATIVE_ESTIMATE = "CONSERVATIVE_ESTIMATE"
    UNAVAILABLE = "UNAVAILABLE"


class OrderConflictCode(str, Enum):
    NON_TERMINAL_ORDER_EXISTS = "NON_TERMINAL_ORDER_EXISTS"
    BLOCKED_BY_UNKNOWN_ORDER = "BLOCKED_BY_UNKNOWN_ORDER"
    SELL_ORDER_RESERVES_CONTRACTS = "SELL_ORDER_RESERVES_CONTRACTS"


class InvalidationConditionCode(str, Enum):
    PLAYER_RETIRED = "PLAYER_RETIRED"
    WEATHER_DELAY_EXCEEDS = "WEATHER_DELAY_EXCEEDS"
    SCORE_DIFFERENTIAL = "SCORE_DIFFERENTIAL"
    LINEUP_CHANGE = "LINEUP_CHANGE"
    DATA_STALE = "DATA_STALE"
    CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"
    OTHER = "OTHER"


class ComparisonOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    EXISTS = "EXISTS"


class PositionManagementAction(str, Enum):
    """Vocabulario de dominio para "puede mantenerse o debe gestionarse"
    -- deliberadamente NO es `SignalType` (`ENTER`/`WATCH`/`PASS`, ver
    `src.signals.signal_schema`); es un vocabulario nuevo e
    independiente, exclusivo de gestión de posiciones existentes."""

    HOLD_NO_ACTION_NEEDED = "HOLD_NO_ACTION_NEEDED"
    MANAGE_ACTION_AVAILABLE = "MANAGE_ACTION_AVAILABLE"
    MANAGE_ATTENTION_REQUIRED = "MANAGE_ATTENTION_REQUIRED"


class FinalExitType(str, Enum):
    LIMIT = "LIMIT"
    GTD = "GTD"
