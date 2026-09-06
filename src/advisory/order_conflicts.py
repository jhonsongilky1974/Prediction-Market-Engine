"""Detección de conflictos de orden -- Tramo 5B. Función pura: sin I/O,
sin SQLite. Reutiliza `src.positions.state_machine.ORDER_NON_TERMINAL_STATUSES`
tal cual -- no redefine qué es "no terminal".

Invariante estructural ya existente en `PositionsRepository.create_order`
(`NonTerminalOrderExistsError`): como máximo UNA Order no-terminal por
Position en todo momento -- este módulo asume y documenta esa
invariante, no la reimplementa.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from src.advisory.enums import OrderConflictCode
from src.advisory.schemas import OrderConflict
from src.positions.enums import OrderAction
from src.positions.schemas import Order
from src.positions.state_machine import ORDER_NON_TERMINAL_STATUSES


def find_pending_order(orders: Sequence[Order]) -> Optional[Order]:
    """La única Order no-terminal de la posición, si existe -- a lo sumo
    una, por la invariante de `create_order`. Si por algún motivo
    hubiera más de una (estado incoherente, nunca debería ocurrir), se
    devuelve la más reciente y se documenta como advertencia en el
    llamador -- nunca se lanza aquí (función pura de lectura)."""
    pending = [o for o in orders if o.status in ORDER_NON_TERMINAL_STATUSES]
    if not pending:
        return None
    return max(pending, key=lambda o: o.created_at)


def detect_order_conflicts(*, blocked_by_unknown_order: bool, pending_order: Optional[Order]) -> List[OrderConflict]:
    """Códigos de conflicto -- nunca texto libre suelto. `blocked_by_unknown_order`
    viene directamente de `Position.blocked_by_unknown_order` (ya
    mantenido por `PositionsRepository._recompute_blocked_flag`, ver
    `src.positions.positions_repository`)."""
    conflicts: List[OrderConflict] = []

    if blocked_by_unknown_order:
        conflicts.append(
            OrderConflict(
                code=OrderConflictCode.BLOCKED_BY_UNKNOWN_ORDER,
                detail=(
                    "La posición tiene una Order en estado UNKNOWN -- bloqueante hasta "
                    "reconciliación manual explícita (ver src.positions.state_machine)."
                ),
                order_id=pending_order.order_id if pending_order is not None else None,
            )
        )

    if pending_order is not None:
        conflicts.append(
            OrderConflict(
                code=OrderConflictCode.NON_TERMINAL_ORDER_EXISTS,
                detail=(
                    f"Order {pending_order.order_id} en estado {pending_order.status.value} "
                    "impide crear una nueva orden en esta posición hasta que se resuelva."
                ),
                order_id=pending_order.order_id,
            )
        )
        if pending_order.action == OrderAction.SELL:
            conflicts.append(
                OrderConflict(
                    code=OrderConflictCode.SELL_ORDER_RESERVES_CONTRACTS,
                    detail=(
                        f"Order {pending_order.order_id} (SELL) reserva "
                        f"{pending_order.requested_qty - pending_order.confirmed_filled_qty} "
                        "contratos para esa salida -- no disponibles para una nueva orden hasta resolverse."
                    ),
                    order_id=pending_order.order_id,
                )
            )

    return conflicts
