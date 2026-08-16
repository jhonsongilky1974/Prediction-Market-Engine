"""Enums cerrados de Phase 6 (Position Management). Decisión de diseño
(J.2 del Design Proposal): taxonomía de `trigger`/`reason` en los eventos
de auditoría es un enum cerrado, con un valor `OTHER` de escape -- nunca
un string libre como taxonomía primaria.
"""
from __future__ import annotations

from enum import Enum


class FeeStatus(str, Enum):
    """KNOWN: fee confirmada, monto exacto conocido. ESTIMATED: sin
    confirmar, se usa un monto provisional (p.ej. 0 mientras la fórmula
    pública de Kalshi sigue sin verificar). UNKNOWN: ni siquiera hay una
    estimación disponible. fee=0 NUNCA se trata como KNOWN salvo que de
    verdad se haya confirmado que la fee real es 0."""

    KNOWN = "KNOWN"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class PositionSource(str, Enum):
    """MODEL_OPPORTUNITY: la posición nace de una señal ENTER del motor
    (`src.opportunity.schemas.Opportunity`). MANUAL: el usuario registra
    una posición sin señal previa -- Position Management nunca inventa
    retroactivamente una señal deportiva."""

    MODEL_OPPORTUNITY = "MODEL_OPPORTUNITY"
    MANUAL = "MANUAL"


class OrderSourceOfTruth(str, Enum):
    """MANUAL_ENTRY: único valor admitido en Tramo 1 -- el usuario
    registra explícitamente lo que ya ejecutó en Robinhood.
    EXTENSION_OBSERVED: reservado para una fase futura de captura pasiva
    (NO implementada, NO habilitada -- ver alcance autorizado)."""

    MANUAL_ENTRY = "MANUAL_ENTRY"
    EXTENSION_OBSERVED = "EXTENSION_OBSERVED"


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Aprendizajes operativos incorporados directamente: distinguir
    PLANNED/SUBMITTED/PENDING/PARTIALLY_FILLED/FILLED/CANCELED/REJECTED/
    UNKNOWN. UNKNOWN es NO terminal y bloqueante -- ver
    `src.positions.state_machine`."""

    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class PositionStatus(str, Enum):
    """CAPITAL_RECOVERED puede alcanzarse numéricamente con
    capital_recovered_fee_status != KNOWN -- en ese caso es reversible
    (puede volver a RECOVERY_IN_PROGRESS si un fee real resulta mayor al
    asumido). Ver `capital_recovery.is_capital_recovery_confirmed`.

    RESERVED_FOR_FUTURE_TRANSITION (auditoría posterior al Tramo 1):
    CLOSED/SETTLED_WIN/SETTLED_LOSS existen en la máquina de estados
    (`state_machine.POSITION_TRANSITIONS`) y en el validador de
    `runner_contracts` para que el CONTRATO de datos sea coherente de
    cara a una fase futura de cierre/liquidación -- pero NINGÚN método
    de `PositionsRepository` en el Tramo 1 los produce. `apply_fill` (el
    único código que muta `Position.status`) solo puede asignar
    OPEN/RECOVERY_IN_PROGRESS/CAPITAL_RECOVERED -- ver
    `test_position_terminal_settlement_states_unreachable_in_tramo1`.
    NEW tampoco se persiste nunca (create_position exige status==OPEN
    directamente). No implementar `close_position`/`settle_position` sin
    una nueva propuesta de diseño aprobada explícitamente."""

    NEW = "NEW"
    OPEN = "OPEN"
    RECOVERY_IN_PROGRESS = "RECOVERY_IN_PROGRESS"
    CAPITAL_RECOVERED = "CAPITAL_RECOVERED"
    CLOSED = "CLOSED"
    SETTLED_WIN = "SETTLED_WIN"
    SETTLED_LOSS = "SETTLED_LOSS"


class Achievability(str, Enum):
    ALREADY_RECOVERED = "ALREADY_RECOVERED"
    FULLY_RECOVERABLE = "FULLY_RECOVERABLE"
    RECOVERABLE_SELLING_ALL = "RECOVERABLE_SELLING_ALL"
    NOT_RECOVERABLE_AT_THIS_PRICE = "NOT_RECOVERABLE_AT_THIS_PRICE"


class OrderEventReason(str, Enum):
    ORDER_CREATED = "ORDER_CREATED"
    STATUS_TRANSITION = "STATUS_TRANSITION"
    FILL_RECORDED = "FILL_RECORDED"
    MANUAL_RECONCILIATION = "MANUAL_RECONCILIATION"
    CANCEL_REPLACE = "CANCEL_REPLACE"
    OTHER = "OTHER"


class PositionEventTrigger(str, Enum):
    """Taxonomía cerrada de lo que `PositionsRepository` realmente
    produce en el Tramo 1 (auditoría posterior: se retiraron
    PLAN_ACCEPTED/FEE_RESOLVED/MANUAL_RECONCILIATION/SETTLEMENT --
    ningún método los emitía, eran generalización prematura sin caso de
    uso real todavía). Ampliar este enum cuando exista un trigger de
    negocio concreto que lo necesite, no antes."""

    POSITION_OPENED = "POSITION_OPENED"
    FILL_APPLIED = "FILL_APPLIED"
    OTHER = "OTHER"
