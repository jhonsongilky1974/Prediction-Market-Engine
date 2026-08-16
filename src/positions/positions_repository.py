"""Persistencia SQLite de Phase 6 -- Tramo 1 (Position Management). Ver
Design Proposal aprobado, secciones C ("Recomendación final de
persistencia") y H ("Esquema SQLite definitivo").

Seis tablas nuevas, aditivas, en el MISMO archivo SQLite (`data/engine.db`)
que ya usan `Repository`/`HistoryRepository`/`OpportunityRepository` --
conviven sin alterar en absoluto ninguna tabla existente, mismo patrón
exacto de `CREATE TABLE IF NOT EXISTS` + `PRAGMA foreign_keys = ON` por
conexión:

- `positions`/`orders` -- MATERIALIZADAS, mutables, con `version` para
  optimistic locking (Option B aprobada: diverge deliberadamente del
  patrón insert-only de `opportunities`/`event_snapshots` -- ver
  justificación en el Design Proposal, sección C). Todo cambio de estado
  pasa exclusivamente por los métodos de esta clase: ningún otro código
  debe emitir `UPDATE positions`/`UPDATE orders` (F8).
- `order_fills`/`position_events`/`order_events`/`position_plans` --
  append-only, mismo patrón de trigger `RAISE(ABORT)` que
  `event_snapshots` (Fase 2) que rechaza UPDATE/DELETE incluso con SQL
  crudo fuera de esta clase (F9).

Concurrencia (decisión 1, Fase 6): optimistic locking (columna `version`,
`UPDATE ... WHERE version = ?`) es el mecanismo PRINCIPAL -- nunca
last-write-wins silencioso, un conflicto de versión siempre falla
explícito (`OptimisticLockError`). Las operaciones multi-write
(fill -> Order -> Position) además se ejecutan dentro de una transacción
SQLite `BEGIN IMMEDIATE` (`_connect_for_write`) que adquiere el lock de
escritura desde el inicio -- optimistic locking y atomicidad son DOS
defensas independientes, ninguna sustituye a la otra.

Idempotencia (requisito D del alcance autorizado): `orders.intent_id` y
`order_fills.fill_id` llevan `UNIQUE` a nivel de motor. `create_order`/
`apply_fill` verifican la existencia ANTES de insertar: una repetición
exacta de la misma intención lógica es un no-op idempotente (devuelve lo
ya existente); una reutilización de la misma clave con datos distintos
es una contradicción y lanza `IdempotencyConflictError` -- nunca se
fusiona ni se sobrescribe en silencio.

Dinero: todos los campos monetarios se persisten como TEXT (`str(Decimal)`)
-- nunca REAL/float -- para preservar precisión exacta a través del
round-trip SQLite (ver `src.positions.money`).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator, List, Optional

from config.settings import DB_PATH
from src.positions import capital_recovery
from src.positions.enums import (
    Achievability,
    FeeStatus,
    OrderAction,
    OrderEventReason,
    OrderSourceOfTruth,
    OrderStatus,
    PositionEventTrigger,
    PositionSource,
    PositionStatus,
)
from src.positions.exceptions import (
    IdempotencyConflictError,
    InvariantViolationError,
    NonTerminalOrderExistsError,
    OptimisticLockError,
)
from src.positions.schemas import Fee, Order, OrderEvent, OrderFill, Position, PositionEvent, PositionPlan
from src.positions.state_machine import (
    ORDER_NON_TERMINAL_STATUSES,
    validate_order_transition,
    validate_position_transition,
)

POSITIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    linked_opportunity_id TEXT,
    kalshi_ticker TEXT NOT NULL,
    sport TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    blocked_by_unknown_order INTEGER NOT NULL DEFAULT 0,
    open_contracts INTEGER NOT NULL,
    capital_invested_cents TEXT NOT NULL,
    capital_invested_fee_status TEXT NOT NULL,
    capital_recovered_cents TEXT NOT NULL,
    capital_recovered_fee_status TEXT NOT NULL,
    runner_contracts INTEGER,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    intent_id TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    requested_qty INTEGER NOT NULL,
    planned_target_price_cents TEXT NOT NULL,
    order_price_cents TEXT,
    status TEXT NOT NULL,
    confirmed_filled_qty INTEGER NOT NULL,
    avg_fill_price_cents TEXT,
    source_of_truth TEXT NOT NULL,
    replaces_order_id TEXT,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_position_status ON orders(position_id, status);

CREATE TABLE IF NOT EXISTS order_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    action TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price_cents TEXT NOT NULL,
    fee_status TEXT NOT NULL,
    fee_cents TEXT,
    filled_at TEXT NOT NULL,
    is_confirmed INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
);
CREATE INDEX IF NOT EXISTS idx_order_fills_position ON order_fills(position_id);
CREATE INDEX IF NOT EXISTS idx_order_fills_order ON order_fills(order_id);

CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    position_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_detail TEXT,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
);
CREATE INDEX IF NOT EXISTS idx_position_events_position ON position_events(position_id);

CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    reason_detail TEXT,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id);

CREATE TABLE IF NOT EXISTS position_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL UNIQUE,
    position_id TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    capital_remaining_at_computation_cents TEXT NOT NULL,
    planned_target_price_cents TEXT NOT NULL,
    fee_assumption_status TEXT NOT NULL,
    fee_assumption_cents TEXT,
    open_contracts_at_computation INTEGER NOT NULL,
    contracts_to_sell INTEGER NOT NULL,
    gross_proceeds_cents TEXT NOT NULL,
    expected_fees_cents TEXT NOT NULL,
    net_proceeds_cents TEXT NOT NULL,
    contracts_remaining_after INTEGER NOT NULL,
    achievability TEXT NOT NULL,
    provisional INTEGER NOT NULL,
    observed_market_price_cents TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
);
CREATE INDEX IF NOT EXISTS idx_position_plans_position ON position_plans(position_id);

-- Append-only reforzado a nivel de motor (F9), mismo patrón que
-- event_snapshots (Fase 2, src/storage/history_repository.py): rechaza
-- UPDATE/DELETE incluso con SQL crudo fuera de esta clase. positions/
-- orders NO llevan estos triggers -- son las únicas tablas mutables del
-- módulo (F9), su protección es optimistic locking (version), no
-- append-only.
CREATE TRIGGER IF NOT EXISTS trg_order_fills_no_update
BEFORE UPDATE ON order_fills
BEGIN
    SELECT RAISE(ABORT, 'order_fills es append-only: UPDATE no permitido');
END;
CREATE TRIGGER IF NOT EXISTS trg_order_fills_no_delete
BEFORE DELETE ON order_fills
BEGIN
    SELECT RAISE(ABORT, 'order_fills es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_position_events_no_update
BEFORE UPDATE ON position_events
BEGIN
    SELECT RAISE(ABORT, 'position_events es append-only: UPDATE no permitido');
END;
CREATE TRIGGER IF NOT EXISTS trg_position_events_no_delete
BEFORE DELETE ON position_events
BEGIN
    SELECT RAISE(ABORT, 'position_events es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_order_events_no_update
BEFORE UPDATE ON order_events
BEGIN
    SELECT RAISE(ABORT, 'order_events es append-only: UPDATE no permitido');
END;
CREATE TRIGGER IF NOT EXISTS trg_order_events_no_delete
BEFORE DELETE ON order_events
BEGIN
    SELECT RAISE(ABORT, 'order_events es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_position_plans_no_update
BEFORE UPDATE ON position_plans
BEGIN
    SELECT RAISE(ABORT, 'position_plans es append-only: UPDATE no permitido');
END;
CREATE TRIGGER IF NOT EXISTS trg_position_plans_no_delete
BEFORE DELETE ON position_plans
BEGIN
    SELECT RAISE(ABORT, 'position_plans es append-only: DELETE no permitido');
END;
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _dec(value: str) -> Decimal:
    return Decimal(value)


def _opt_dec(value: Optional[str]) -> Optional[Decimal]:
    return Decimal(value) if value is not None else None


class PositionsRepository:
    """Punto único de acceso a las 6 tablas de Phase 6. No reemplaza ni
    envuelve `Repository`/`HistoryRepository`/`OpportunityRepository` --
    es un componente hermano, aditivo, mismo `db_path` (default
    `DB_PATH`, inyectable para tests -- SIEMPRE `tmp_path` en tests,
    nunca la ruta de producción)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(POSITIONS_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Conexión de solo-lectura / escritura simple de una sola tabla.
        Mismo patrón que `OpportunityRepository._connect`."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _connect_for_write(self) -> Iterator[sqlite3.Connection]:
        """`BEGIN IMMEDIATE`: adquiere el lock de escritura desde el
        INICIO de la transacción, no de forma diferida en el primer
        INSERT/UPDATE -- necesario para que las operaciones multi-write
        (fill -> Order -> Position) sean verdaderamente atómicas frente
        a otro escritor concurrente, complementando (no sustituyendo) el
        optimistic locking por versión. Uso exclusivo de
        `create_position`/`create_order`/`apply_fill`/
        `update_order_status`/`save_position_plan`."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # positions (materializada, mutable, version)
    # ------------------------------------------------------------------

    def create_position(self, position: Position) -> Position:
        if position.version != 1:
            raise InvariantViolationError(
                f"create_position exige version==1, recibido {position.version}"
            )
        if position.status != PositionStatus.OPEN:
            raise InvariantViolationError(
                "create_position exige status==OPEN (Tramo 1 no usa NEW como estado "
                f"transitorio persistido); recibido {position.status.value}"
            )
        if position.open_contracts != 0:
            raise InvariantViolationError("create_position exige open_contracts==0 al abrir")

        with self._connect_for_write() as conn:
            existing = conn.execute(
                "SELECT position_id FROM positions WHERE position_id = ?", (position.position_id,)
            ).fetchone()
            if existing is not None:
                raise IdempotencyConflictError(
                    f"position_id={position.position_id!r} ya existe -- create_position no es "
                    "un upsert, usar get_position() para consultar el estado actual"
                )

            conn.execute(
                """
                INSERT INTO positions (
                    position_id, source, linked_opportunity_id, kalshi_ticker, sport, side,
                    status, blocked_by_unknown_order, open_contracts,
                    capital_invested_cents, capital_invested_fee_status,
                    capital_recovered_cents, capital_recovered_fee_status,
                    runner_contracts,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.position_id,
                    position.source.value,
                    position.linked_opportunity_id,
                    position.kalshi_ticker,
                    position.sport.value,
                    position.side.value,
                    position.status.value,
                    int(position.blocked_by_unknown_order),
                    position.open_contracts,
                    str(position.capital_invested_cents),
                    position.capital_invested_fee_status.value,
                    str(position.capital_recovered_cents),
                    position.capital_recovered_fee_status.value,
                    position.runner_contracts,
                    position.version,
                    _iso(position.created_at),
                    _iso(position.updated_at),
                ),
            )
            self._insert_position_event(
                conn,
                event_id=f"{position.position_id}:opened",
                position_id=position.position_id,
                from_status=None,
                to_status=position.status,
                trigger=PositionEventTrigger.POSITION_OPENED,
                trigger_detail=None,
                occurred_at=position.created_at,
            )
        return position

    def get_position(self, position_id: str) -> Optional[Position]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM positions WHERE position_id = ?", (position_id,)
            ).fetchone()
        return self._row_to_position(row) if row is not None else None

    def list_open_positions(self) -> List[Position]:
        terminal = tuple(s.value for s in (PositionStatus.CLOSED, PositionStatus.SETTLED_WIN, PositionStatus.SETTLED_LOSS))
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM positions WHERE status NOT IN ({','.join('?' * len(terminal))}) "
                "ORDER BY created_at ASC",
                terminal,
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def list_all_positions(self) -> List[Position]:
        """Sin filtro de status -- mismo patrón que `get_all_event_snapshots`
        (Fase 2). Añadido para Tramo 2 (`GET /positions?status=all`), lectura
        pura, no toca ningún invariante de escritura ya auditado."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM positions ORDER BY created_at ASC").fetchall()
        return [self._row_to_position(r) for r in rows]

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            position_id=row["position_id"],
            source=PositionSource(row["source"]),
            linked_opportunity_id=row["linked_opportunity_id"],
            kalshi_ticker=row["kalshi_ticker"],
            sport=row["sport"],
            side=row["side"],
            status=PositionStatus(row["status"]),
            blocked_by_unknown_order=bool(row["blocked_by_unknown_order"]),
            open_contracts=row["open_contracts"],
            capital_invested_cents=_dec(row["capital_invested_cents"]),
            capital_invested_fee_status=FeeStatus(row["capital_invested_fee_status"]),
            capital_recovered_cents=_dec(row["capital_recovered_cents"]),
            capital_recovered_fee_status=FeeStatus(row["capital_recovered_fee_status"]),
            runner_contracts=row["runner_contracts"],
            version=row["version"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    # ------------------------------------------------------------------
    # orders (materializada, mutable, version) + idempotencia (intent_id)
    # ------------------------------------------------------------------

    def create_order(self, order: Order) -> Order:
        if order.version != 1:
            raise InvariantViolationError(f"create_order exige version==1, recibido {order.version}")
        if order.status != OrderStatus.PLANNED:
            raise InvariantViolationError(
                f"create_order exige status==PLANNED, recibido {order.status.value}"
            )
        if order.confirmed_filled_qty != 0:
            raise InvariantViolationError("create_order exige confirmed_filled_qty==0")

        with self._connect_for_write() as conn:
            conn.row_factory = sqlite3.Row

            existing_by_intent = conn.execute(
                "SELECT * FROM orders WHERE intent_id = ?", (order.intent_id,)
            ).fetchone()
            if existing_by_intent is not None:
                existing_order = self._row_to_order(existing_by_intent)
                if (
                    existing_order.position_id == order.position_id
                    and existing_order.action == order.action
                    and existing_order.requested_qty == order.requested_qty
                    and existing_order.planned_target_price_cents == order.planned_target_price_cents
                ):
                    # Misma intención lógica -- no-op idempotente (evita
                    # doble orden por doble click / reintento de red).
                    return existing_order
                raise IdempotencyConflictError(
                    f"intent_id={order.intent_id!r} ya fue usado con datos distintos -- "
                    "posible colisión de idempotency key, no un reintento legítimo"
                )

            existing_by_id = conn.execute(
                "SELECT order_id FROM orders WHERE order_id = ?", (order.order_id,)
            ).fetchone()
            if existing_by_id is not None:
                raise IdempotencyConflictError(f"order_id={order.order_id!r} ya existe")

            if self._has_non_terminal_order(conn, order.position_id):
                raise NonTerminalOrderExistsError(
                    f"position_id={order.position_id!r} ya tiene una Order en estado no "
                    "terminal -- debe resolverse (reconciliar UNKNOWN o esperar estado "
                    "terminal) antes de crear otra (F5, idempotencia estructural)"
                )

            if order.action == OrderAction.SELL:
                # Añadido para Tramo 2: rechazar de entrada la PREPARACIÓN
                # de una orden SELL que ya es imposible de cumplir, sin
                # esperar al fill (apply_fill ya rechazaba el fill en sí,
                # pero permitía preparar una orden nunca ejecutable).
                position_row = conn.execute(
                    "SELECT open_contracts FROM positions WHERE position_id = ?", (order.position_id,)
                ).fetchone()
                if position_row is None:
                    raise InvariantViolationError(f"position_id={order.position_id!r} no existe")
                open_contracts = position_row[0]
                if order.requested_qty > open_contracts:
                    raise InvariantViolationError(
                        f"No se puede preparar una orden SELL por {order.requested_qty} contratos: "
                        f"la posición {order.position_id!r} solo tiene {open_contracts} abiertos"
                    )

            conn.execute(
                """
                INSERT INTO orders (
                    order_id, position_id, intent_id, action, requested_qty,
                    planned_target_price_cents, order_price_cents, status,
                    confirmed_filled_qty, avg_fill_price_cents, source_of_truth,
                    replaces_order_id, version, created_at, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.position_id,
                    order.intent_id,
                    order.action.value,
                    order.requested_qty,
                    str(order.planned_target_price_cents),
                    str(order.order_price_cents) if order.order_price_cents is not None else None,
                    order.status.value,
                    order.confirmed_filled_qty,
                    str(order.avg_fill_price_cents) if order.avg_fill_price_cents is not None else None,
                    order.source_of_truth.value,
                    order.replaces_order_id,
                    order.version,
                    _iso(order.created_at),
                    _iso(order.last_updated_at),
                ),
            )
            self._insert_order_event(
                conn,
                event_id=f"{order.order_id}:created",
                order_id=order.order_id,
                from_status=None,
                to_status=order.status,
                reason=OrderEventReason.ORDER_CREATED,
                reason_detail=None,
                occurred_at=order.created_at,
            )
        return order

    def _has_non_terminal_order(self, conn: sqlite3.Connection, position_id: str) -> bool:
        non_terminal = tuple(s.value for s in ORDER_NON_TERMINAL_STATUSES)
        query = (
            f"SELECT 1 FROM orders WHERE position_id = ? AND status IN "
            f"({','.join('?' * len(non_terminal))})"
        )
        params: tuple = (position_id, *non_terminal)
        return conn.execute(query, params).fetchone() is not None

    def has_non_terminal_order(self, position_id: str) -> bool:
        with self._connect() as conn:
            return self._has_non_terminal_order(conn, position_id)

    def get_order(self, order_id: str) -> Optional[Order]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return self._row_to_order(row) if row is not None else None

    def get_orders_for_position(self, position_id: str) -> List[Order]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM orders WHERE position_id = ? ORDER BY created_at ASC", (position_id,)
            ).fetchall()
        return [self._row_to_order(r) for r in rows]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> Order:
        return Order(
            order_id=row["order_id"],
            position_id=row["position_id"],
            intent_id=row["intent_id"],
            action=OrderAction(row["action"]),
            requested_qty=row["requested_qty"],
            planned_target_price_cents=_dec(row["planned_target_price_cents"]),
            order_price_cents=_opt_dec(row["order_price_cents"]),
            status=OrderStatus(row["status"]),
            confirmed_filled_qty=row["confirmed_filled_qty"],
            avg_fill_price_cents=_opt_dec(row["avg_fill_price_cents"]),
            source_of_truth=OrderSourceOfTruth(row["source_of_truth"]),
            replaces_order_id=row["replaces_order_id"],
            version=row["version"],
            created_at=_parse_dt(row["created_at"]),
            last_updated_at=_parse_dt(row["last_updated_at"]),
        )

    def update_order_status(
        self,
        order_id: str,
        *,
        expected_version: int,
        new_status: OrderStatus,
        reason: OrderEventReason,
        reason_detail: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> Order:
        """Transiciones administrativas que NO provienen de un fill
        (PLANNED->SUBMITTED->PENDING, cancelación, o reconciliación
        manual de UNKNOWN). Para fills, usar `apply_fill` (que también
        mueve el status del Order como efecto de un fill real)."""
        occurred_at = occurred_at or _utcnow()
        with self._connect_for_write() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is None:
                raise InvariantViolationError(f"order_id={order_id!r} no existe")
            current = self._row_to_order(row)
            if current.version != expected_version:
                raise OptimisticLockError(
                    f"Order {order_id!r}: version esperada={expected_version}, "
                    f"version almacenada={current.version} -- relectura requerida"
                )
            validate_order_transition(current.status, new_status)

            cursor = conn.execute(
                "UPDATE orders SET status = ?, version = version + 1, last_updated_at = ? "
                "WHERE order_id = ? AND version = ?",
                (new_status.value, _iso(occurred_at), order_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise OptimisticLockError(
                    f"Order {order_id!r}: conflicto de escritura concurrente detectado en UPDATE"
                )
            self._insert_order_event(
                conn,
                event_id=f"{order_id}:{expected_version + 1}",
                order_id=order_id,
                from_status=current.status,
                to_status=new_status,
                reason=reason,
                reason_detail=reason_detail,
                occurred_at=occurred_at,
            )

            self._recompute_blocked_flag(conn, current.position_id, occurred_at)

            updated_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return self._row_to_order(updated_row)

    def _recompute_blocked_flag(self, conn: sqlite3.Connection, position_id: str, occurred_at: datetime) -> None:
        still_blocked = self._has_non_terminal_order_in_status(conn, position_id, OrderStatus.UNKNOWN)
        pos_row = conn.execute(
            "SELECT blocked_by_unknown_order, version FROM positions WHERE position_id = ?", (position_id,)
        ).fetchone()
        if pos_row is None:
            return
        if bool(pos_row[0]) == still_blocked:
            return
        conn.execute(
            "UPDATE positions SET blocked_by_unknown_order = ?, version = version + 1, updated_at = ? "
            "WHERE position_id = ? AND version = ?",
            (int(still_blocked), _iso(occurred_at), position_id, pos_row[1]),
        )

    @staticmethod
    def _has_non_terminal_order_in_status(conn: sqlite3.Connection, position_id: str, status: OrderStatus) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM orders WHERE position_id = ? AND status = ?",
                (position_id, status.value),
            ).fetchone()
            is not None
        )

    # ------------------------------------------------------------------
    # order_fills (append-only) -- operación central: fill -> Order -> Position
    # ------------------------------------------------------------------

    def apply_fill(self, fill: OrderFill, *, expected_order_version: int) -> "tuple[Order, Position]":
        with self._connect_for_write() as conn:
            conn.row_factory = sqlite3.Row

            existing_fill = conn.execute(
                "SELECT * FROM order_fills WHERE fill_id = ?", (fill.fill_id,)
            ).fetchone()
            if existing_fill is not None:
                existing = self._row_to_fill(existing_fill)
                if (
                    existing.order_id == fill.order_id
                    and existing.position_id == fill.position_id
                    and existing.action == fill.action
                    and existing.qty == fill.qty
                    and existing.price_cents == fill.price_cents
                    and existing.fee.status == fill.fee.status
                    and existing.fee.cents == fill.fee.cents
                ):
                    # Mismo fill_id, misma intención lógica -- no-op
                    # idempotente (reintento tras timeout de red, etc.).
                    order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (fill.order_id,)).fetchone()
                    position_row = conn.execute(
                        "SELECT * FROM positions WHERE position_id = ?", (fill.position_id,)
                    ).fetchone()
                    return self._row_to_order(order_row), self._row_to_position(position_row)
                raise IdempotencyConflictError(
                    f"fill_id={fill.fill_id!r} ya fue registrado con datos distintos -- "
                    "posible colisión de idempotency key, no un reintento legítimo"
                )

            order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (fill.order_id,)).fetchone()
            if order_row is None:
                raise InvariantViolationError(f"order_id={fill.order_id!r} no existe")
            order = self._row_to_order(order_row)

            if order.version != expected_order_version:
                raise OptimisticLockError(
                    f"Order {fill.order_id!r}: version esperada={expected_order_version}, "
                    f"version almacenada={order.version} -- relectura requerida"
                )
            if order.status not in ORDER_NON_TERMINAL_STATUSES:
                raise InvariantViolationError(
                    f"Order {fill.order_id!r} está en estado terminal {order.status.value}, "
                    "no admite más fills"
                )
            if order.position_id != fill.position_id:
                raise InvariantViolationError("fill.position_id no coincide con order.position_id")
            if order.action != fill.action:
                raise InvariantViolationError("fill.action no coincide con order.action")

            new_confirmed_qty = order.confirmed_filled_qty + fill.qty
            if new_confirmed_qty > order.requested_qty:
                raise InvariantViolationError(
                    f"fill.qty={fill.qty} excede lo pendiente: confirmed={order.confirmed_filled_qty}, "
                    f"requested={order.requested_qty} (Order {fill.order_id!r})"
                )

            position_row = conn.execute(
                "SELECT * FROM positions WHERE position_id = ?", (fill.position_id,)
            ).fetchone()
            if position_row is None:
                raise InvariantViolationError(f"position_id={fill.position_id!r} no existe")
            position = self._row_to_position(position_row)

            if fill.action == OrderAction.SELL and fill.qty > position.open_contracts:
                raise InvariantViolationError(
                    f"No se puede vender {fill.qty} contratos: solo hay "
                    f"{position.open_contracts} abiertos en la posición {fill.position_id!r} "
                    "(nunca open_contracts negativo)"
                )

            self._insert_fill(conn, fill)

            # --- recomputar Order ---
            new_order_status = OrderStatus.FILLED if new_confirmed_qty == order.requested_qty else OrderStatus.PARTIALLY_FILLED
            validate_order_transition(order.status, new_order_status)

            all_order_fills = [self._row_to_fill(r) for r in conn.execute(
                "SELECT * FROM order_fills WHERE order_id = ?", (fill.order_id,)
            ).fetchall()]
            avg_fill_price = capital_recovery.weighted_average_price_cents(all_order_fills)

            cursor = conn.execute(
                "UPDATE orders SET confirmed_filled_qty = ?, status = ?, avg_fill_price_cents = ?, "
                "version = version + 1, last_updated_at = ? WHERE order_id = ? AND version = ?",
                (
                    new_confirmed_qty,
                    new_order_status.value,
                    str(avg_fill_price) if avg_fill_price is not None else None,
                    _iso(fill.recorded_at),
                    fill.order_id,
                    expected_order_version,
                ),
            )
            if cursor.rowcount != 1:
                raise OptimisticLockError(
                    f"Order {fill.order_id!r}: conflicto de escritura concurrente detectado en UPDATE"
                )
            self._insert_order_event(
                conn,
                event_id=f"{fill.fill_id}:order-event",
                order_id=fill.order_id,
                from_status=order.status,
                to_status=new_order_status,
                reason=OrderEventReason.FILL_RECORDED,
                reason_detail=None,
                occurred_at=fill.recorded_at,
            )

            # --- recomputar Position ---
            all_position_fills = [self._row_to_fill(r) for r in conn.execute(
                "SELECT * FROM order_fills WHERE position_id = ?", (fill.position_id,)
            ).fetchall()]
            metrics = capital_recovery.compute_capital_metrics(all_position_fills)

            if metrics.capital_remaining_cents <= 0:
                new_position_status = PositionStatus.CAPITAL_RECOVERED
                runner_contracts = metrics.open_contracts
            else:
                ever_sold = metrics.avg_exit_price_cents is not None
                if position.status == PositionStatus.CAPITAL_RECOVERED:
                    # Reversión F3: un fee real resultó mayor al estimado
                    # y el capital remanente vuelve a ser positivo.
                    new_position_status = PositionStatus.RECOVERY_IN_PROGRESS
                elif ever_sold:
                    new_position_status = PositionStatus.RECOVERY_IN_PROGRESS
                else:
                    new_position_status = PositionStatus.OPEN
                runner_contracts = None

            validate_position_transition(position.status, new_position_status)

            # NO se calcula/persiste un "realized P&L" en el Tramo 1 --
            # ver nota en schemas.py::Position. Las únicas cifras
            # honestas son capital_invested_cents (capital total en
            # riesgo), capital_recovered_cents (proceeds netos de lo
            # efectivamente vendido) y su status de fee -- ambas ya se
            # persisten a continuación tal cual las calculó
            # `compute_capital_metrics` (función pura, ver
            # capital_recovery.py).
            cursor = conn.execute(
                """
                UPDATE positions SET
                    open_contracts = ?, capital_invested_cents = ?, capital_invested_fee_status = ?,
                    capital_recovered_cents = ?, capital_recovered_fee_status = ?, runner_contracts = ?,
                    status = ?, version = version + 1, updated_at = ?
                WHERE position_id = ? AND version = ?
                """,
                (
                    metrics.open_contracts,
                    str(metrics.total_capital_at_risk_cents),
                    metrics.total_capital_at_risk_fee_status.value,
                    str(metrics.realized_net_proceeds_cents),
                    metrics.realized_net_proceeds_fee_status.value,
                    runner_contracts,
                    new_position_status.value,
                    _iso(fill.recorded_at),
                    fill.position_id,
                    position.version,
                ),
            )
            if cursor.rowcount != 1:
                raise OptimisticLockError(
                    f"Position {fill.position_id!r}: conflicto de escritura concurrente detectado en UPDATE"
                )
            if new_position_status != position.status:
                self._insert_position_event(
                    conn,
                    event_id=f"{fill.fill_id}:position-event",
                    position_id=fill.position_id,
                    from_status=position.status,
                    to_status=new_position_status,
                    trigger=PositionEventTrigger.FILL_APPLIED,
                    trigger_detail=None,
                    occurred_at=fill.recorded_at,
                )

            updated_order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (fill.order_id,)).fetchone()
            updated_position_row = conn.execute(
                "SELECT * FROM positions WHERE position_id = ?", (fill.position_id,)
            ).fetchone()

        return self._row_to_order(updated_order_row), self._row_to_position(updated_position_row)

    def _insert_fill(self, conn: sqlite3.Connection, fill: OrderFill) -> None:
        conn.execute(
            """
            INSERT INTO order_fills (
                fill_id, order_id, position_id, action, qty, price_cents,
                fee_status, fee_cents, filled_at, is_confirmed, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.fill_id,
                fill.order_id,
                fill.position_id,
                fill.action.value,
                fill.qty,
                str(fill.price_cents),
                fill.fee.status.value,
                str(fill.fee.cents) if fill.fee.cents is not None else None,
                _iso(fill.filled_at),
                int(fill.is_confirmed),
                _iso(fill.recorded_at),
            ),
        )

    def get_fills_for_position(self, position_id: str) -> List[OrderFill]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM order_fills WHERE position_id = ? ORDER BY recorded_at ASC, id ASC",
                (position_id,),
            ).fetchall()
        return [self._row_to_fill(r) for r in rows]

    def get_fills_for_order(self, order_id: str) -> List[OrderFill]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM order_fills WHERE order_id = ? ORDER BY recorded_at ASC, id ASC",
                (order_id,),
            ).fetchall()
        return [self._row_to_fill(r) for r in rows]

    @staticmethod
    def _row_to_fill(row: sqlite3.Row) -> OrderFill:
        fee = Fee(status=FeeStatus(row["fee_status"]), cents=_opt_dec(row["fee_cents"]))
        return OrderFill(
            fill_id=row["fill_id"],
            order_id=row["order_id"],
            position_id=row["position_id"],
            action=OrderAction(row["action"]),
            qty=row["qty"],
            price_cents=_dec(row["price_cents"]),
            fee=fee,
            filled_at=_parse_dt(row["filled_at"]),
            is_confirmed=bool(row["is_confirmed"]),
            recorded_at=_parse_dt(row["recorded_at"]),
        )

    # ------------------------------------------------------------------
    # position_events / order_events (append-only)
    # ------------------------------------------------------------------

    def _insert_position_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        position_id: str,
        from_status: Optional[PositionStatus],
        to_status: PositionStatus,
        trigger: PositionEventTrigger,
        trigger_detail: Optional[str],
        occurred_at: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO position_events (
                event_id, position_id, from_status, to_status, trigger_type,
                trigger_detail, occurred_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                position_id,
                from_status.value if from_status is not None else None,
                to_status.value,
                trigger.value,
                trigger_detail,
                _iso(occurred_at),
                _iso(_utcnow()),
            ),
        )

    def _insert_order_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        order_id: str,
        from_status: Optional[OrderStatus],
        to_status: OrderStatus,
        reason: OrderEventReason,
        reason_detail: Optional[str],
        occurred_at: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO order_events (
                event_id, order_id, from_status, to_status, reason,
                reason_detail, occurred_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                order_id,
                from_status.value if from_status is not None else None,
                to_status.value,
                reason.value,
                reason_detail,
                _iso(occurred_at),
                _iso(_utcnow()),
            ),
        )

    def get_position_events(self, position_id: str) -> List[PositionEvent]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM position_events WHERE position_id = ? ORDER BY id ASC", (position_id,)
            ).fetchall()
        return [
            PositionEvent(
                event_id=r["event_id"],
                position_id=r["position_id"],
                from_status=PositionStatus(r["from_status"]) if r["from_status"] is not None else None,
                to_status=PositionStatus(r["to_status"]),
                trigger=PositionEventTrigger(r["trigger_type"]),
                trigger_detail=r["trigger_detail"],
                occurred_at=_parse_dt(r["occurred_at"]),
                recorded_at=_parse_dt(r["recorded_at"]),
            )
            for r in rows
        ]

    def get_order_events(self, order_id: str) -> List[OrderEvent]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM order_events WHERE order_id = ? ORDER BY id ASC", (order_id,)
            ).fetchall()
        return [
            OrderEvent(
                event_id=r["event_id"],
                order_id=r["order_id"],
                from_status=OrderStatus(r["from_status"]) if r["from_status"] is not None else None,
                to_status=OrderStatus(r["to_status"]),
                reason=OrderEventReason(r["reason"]),
                reason_detail=r["reason_detail"],
                occurred_at=_parse_dt(r["occurred_at"]),
                recorded_at=_parse_dt(r["recorded_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # position_plans (append-only, advisory)
    # ------------------------------------------------------------------

    def save_position_plan(self, plan: PositionPlan) -> PositionPlan:
        with self._connect_for_write() as conn:
            existing = conn.execute(
                "SELECT plan_id FROM position_plans WHERE plan_id = ?", (plan.plan_id,)
            ).fetchone()
            if existing is not None:
                raise IdempotencyConflictError(f"plan_id={plan.plan_id!r} ya existe")
            conn.execute(
                """
                INSERT INTO position_plans (
                    plan_id, position_id, computed_at, capital_remaining_at_computation_cents,
                    planned_target_price_cents, fee_assumption_status, fee_assumption_cents,
                    open_contracts_at_computation, contracts_to_sell, gross_proceeds_cents,
                    expected_fees_cents, net_proceeds_cents, contracts_remaining_after,
                    achievability, provisional, observed_market_price_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.position_id,
                    _iso(plan.computed_at),
                    str(plan.capital_remaining_at_computation_cents),
                    str(plan.planned_target_price_cents),
                    plan.fee_assumption.status.value,
                    str(plan.fee_assumption.cents) if plan.fee_assumption.cents is not None else None,
                    plan.open_contracts_at_computation,
                    plan.contracts_to_sell,
                    str(plan.gross_proceeds_cents),
                    str(plan.expected_fees_cents),
                    str(plan.net_proceeds_cents),
                    plan.contracts_remaining_after,
                    plan.achievability.value,
                    int(plan.provisional),
                    str(plan.observed_market_price_cents) if plan.observed_market_price_cents is not None else None,
                ),
            )
        return plan

    def compute_and_save_plan(
        self,
        *,
        plan_id: str,
        position_id: str,
        planned_target_price_cents: Decimal,
        fee_assumption: Fee,
        observed_market_price_cents: Optional[Decimal] = None,
        computed_at: Optional[datetime] = None,
    ) -> PositionPlan:
        """Orquestación read -> pure math -> save: lee el estado actual
        de la Position, delega el cálculo a
        `capital_recovery.compute_recovery_plan` (función pura), y
        persiste el resultado como PositionPlan append-only. Nunca muta
        la Position ni ejecuta nada -- puramente advisory (F7, F10)."""
        computed_at = computed_at or _utcnow()
        position = self.get_position(position_id)
        if position is None:
            raise InvariantViolationError(f"position_id={position_id!r} no existe")

        capital_remaining = position.capital_invested_cents - position.capital_recovered_cents
        if capital_remaining < 0:
            capital_remaining = Decimal(0)

        result = capital_recovery.compute_recovery_plan(
            capital_remaining_cents=capital_remaining,
            capital_remaining_fee_status=capital_recovery.aggregate_fee_status(
                [position.capital_invested_fee_status, position.capital_recovered_fee_status]
            ),
            open_contracts=position.open_contracts,
            planned_target_price_cents=planned_target_price_cents,
            fee_assumption=fee_assumption,
        )

        plan = PositionPlan(
            plan_id=plan_id,
            position_id=position_id,
            computed_at=computed_at,
            capital_remaining_at_computation_cents=capital_remaining,
            planned_target_price_cents=planned_target_price_cents,
            fee_assumption=fee_assumption,
            open_contracts_at_computation=position.open_contracts,
            contracts_to_sell=result.contracts_to_sell,
            gross_proceeds_cents=result.gross_proceeds_cents,
            expected_fees_cents=result.expected_fees_cents,
            net_proceeds_cents=result.net_proceeds_cents,
            contracts_remaining_after=result.contracts_remaining_after,
            achievability=result.achievability,
            provisional=result.provisional,
            observed_market_price_cents=observed_market_price_cents,
        )
        return self.save_position_plan(plan)

    def get_position_plans(self, position_id: str) -> List[PositionPlan]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM position_plans WHERE position_id = ? ORDER BY id ASC", (position_id,)
            ).fetchall()
        return [
            PositionPlan(
                plan_id=r["plan_id"],
                position_id=r["position_id"],
                computed_at=_parse_dt(r["computed_at"]),
                capital_remaining_at_computation_cents=_dec(r["capital_remaining_at_computation_cents"]),
                planned_target_price_cents=_dec(r["planned_target_price_cents"]),
                fee_assumption=Fee(
                    status=FeeStatus(r["fee_assumption_status"]),
                    cents=_opt_dec(r["fee_assumption_cents"]),
                ),
                open_contracts_at_computation=r["open_contracts_at_computation"],
                contracts_to_sell=r["contracts_to_sell"],
                gross_proceeds_cents=_dec(r["gross_proceeds_cents"]),
                expected_fees_cents=_dec(r["expected_fees_cents"]),
                net_proceeds_cents=_dec(r["net_proceeds_cents"]),
                contracts_remaining_after=r["contracts_remaining_after"],
                achievability=Achievability(r["achievability"]),
                provisional=bool(r["provisional"]),
                observed_market_price_cents=_opt_dec(r["observed_market_price_cents"]),
            )
            for r in rows
        ]
