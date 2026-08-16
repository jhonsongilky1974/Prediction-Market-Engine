"""Máquinas de estado de Order y Position (Phase 6, Tramo 1). Ver Design
Proposal aprobado, sección E ("State machines definitivas").

`UNKNOWN` (Order) es NO terminal y bloqueante: mientras exista una Order
en UNKNOWN para una Position, no se permite crear una Order nueva para
esa misma Position (F5, `PositionsRepository.create_order`) hasta
reconciliación manual explícita.

`CAPITAL_RECOVERED` (Position) puede alcanzarse con fees no confirmados
(F3) -- es reversible a RECOVERY_IN_PROGRESS si un fee real hace que
`capital_remaining_cents` vuelva a ser positivo. Por eso
`CAPITAL_RECOVERED -> RECOVERY_IN_PROGRESS` es una transición válida, a
diferencia del resto de estados terminales.
"""
from __future__ import annotations

from typing import Dict, FrozenSet

from src.positions.enums import OrderStatus, PositionStatus
from src.positions.exceptions import InvalidStateTransitionError

ORDER_TERMINAL_STATUSES: FrozenSet[OrderStatus] = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}
)
# UNKNOWN se considera no-terminal a propósito: es bloqueante, no un
# estado de reposo válido -- ver docstring del módulo.
ORDER_NON_TERMINAL_STATUSES: FrozenSet[OrderStatus] = (
    frozenset(OrderStatus) - ORDER_TERMINAL_STATUSES
)

ORDER_TRANSITIONS: Dict[OrderStatus, FrozenSet[OrderStatus]] = {
    # PARTIALLY_FILLED/FILLED alcanzables directamente desde PLANNED y
    # SUBMITTED (no solo desde PENDING): Tramo 1 es 100% captura manual
    # -- el usuario puede registrar un fill ya confirmado sin haber
    # modelado antes cada paso intermedio SUBMITTED/PENDING del broker.
    OrderStatus.PLANNED: frozenset(
        {
            OrderStatus.SUBMITTED,
            OrderStatus.CANCELED,
            OrderStatus.UNKNOWN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        }
    ),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.PENDING,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.UNKNOWN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        }
    ),
    OrderStatus.PENDING: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,  # otro fill parcial adicional
            OrderStatus.FILLED,
            OrderStatus.CANCELED,  # cancela el remanente, qty ya confirmada persiste
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.UNKNOWN: frozenset(
        {
            OrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


def validate_order_transition(from_status: OrderStatus, to_status: OrderStatus) -> None:
    allowed = ORDER_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidStateTransitionError(
            f"Order: transición inválida {from_status.value} -> {to_status.value} "
            f"(permitidas desde {from_status.value}: {sorted(s.value for s in allowed)})"
        )


POSITION_TERMINAL_STATUSES: FrozenSet[PositionStatus] = frozenset(
    {PositionStatus.CLOSED, PositionStatus.SETTLED_WIN, PositionStatus.SETTLED_LOSS}
)

POSITION_TRANSITIONS: Dict[PositionStatus, FrozenSet[PositionStatus]] = {
    PositionStatus.NEW: frozenset({PositionStatus.OPEN}),
    PositionStatus.OPEN: frozenset(
        {
            PositionStatus.RECOVERY_IN_PROGRESS,
            PositionStatus.CAPITAL_RECOVERED,
            PositionStatus.SETTLED_WIN,
            PositionStatus.SETTLED_LOSS,
        }
    ),
    PositionStatus.RECOVERY_IN_PROGRESS: frozenset(
        {
            PositionStatus.RECOVERY_IN_PROGRESS,  # otra venta parcial (decisión 6)
            PositionStatus.CAPITAL_RECOVERED,
            PositionStatus.SETTLED_WIN,
            PositionStatus.SETTLED_LOSS,
        }
    ),
    PositionStatus.CAPITAL_RECOVERED: frozenset(
        {
            PositionStatus.RECOVERY_IN_PROGRESS,  # reversión F3 (fee real > estimado)
            PositionStatus.CLOSED,
            PositionStatus.SETTLED_WIN,
            PositionStatus.SETTLED_LOSS,
        }
    ),
    PositionStatus.CLOSED: frozenset(),
    PositionStatus.SETTLED_WIN: frozenset(),
    PositionStatus.SETTLED_LOSS: frozenset(),
}


def validate_position_transition(from_status: PositionStatus, to_status: PositionStatus) -> None:
    if from_status == to_status:
        # Recompute sin cambio real de estado (p.ej. otro fill que no
        # altera la fase de la posición) -- no es una "transición" per
        # se, se permite sin más.
        return
    allowed = POSITION_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidStateTransitionError(
            f"Position: transición inválida {from_status.value} -> {to_status.value} "
            f"(permitidas desde {from_status.value}: {sorted(s.value for s in allowed)})"
        )
