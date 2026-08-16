"""Factories de ejemplo mínimo válido para Phase 6 -- Tramo 1 (Position
Management). Mismo patrón `_kwargs(**overrides)` que
`tests/unit/fase3_factories.py` (Fase 3): cada `make_*` construye una
instancia válida con overrides superficiales de nivel superior. No es un
módulo de tests en sí (sin funciones `test_*`) -- lo importan todos los
archivos `test_positions_*.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.models.schemas import Sport
from src.positions.enums import (
    FeeStatus,
    OrderAction,
    OrderSourceOfTruth,
    OrderStatus,
    PositionSource,
    PositionStatus,
)
from src.positions.schemas import Fee, Order, OrderFill, Position
from src.signals.signal_schema import Side

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def make_fee(**overrides) -> Fee:
    base = dict(status=FeeStatus.KNOWN, cents=Decimal(0))
    base.update(overrides)
    return Fee(**base)


def make_position(**overrides) -> Position:
    base = dict(
        position_id="pos-1",
        source=PositionSource.MANUAL,
        linked_opportunity_id=None,
        kalshi_ticker="KXMLBGAME-1",
        sport=Sport.MLB,
        side=Side.YES,
        status=PositionStatus.OPEN,
        blocked_by_unknown_order=False,
        open_contracts=0,
        capital_invested_cents=Decimal(0),
        capital_invested_fee_status=FeeStatus.KNOWN,
        capital_recovered_cents=Decimal(0),
        capital_recovered_fee_status=FeeStatus.KNOWN,
        runner_contracts=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return Position(**base)


def make_order(**overrides) -> Order:
    base = dict(
        order_id="ord-1",
        position_id="pos-1",
        intent_id="intent-1",
        action=OrderAction.BUY,
        requested_qty=10,
        planned_target_price_cents=Decimal(50),
        order_price_cents=None,
        status=OrderStatus.PLANNED,
        confirmed_filled_qty=0,
        avg_fill_price_cents=None,
        source_of_truth=OrderSourceOfTruth.MANUAL_ENTRY,
        replaces_order_id=None,
        version=1,
        created_at=NOW,
        last_updated_at=NOW,
    )
    base.update(overrides)
    return Order(**base)


def make_fill(**overrides) -> OrderFill:
    base = dict(
        fill_id="fill-1",
        order_id="ord-1",
        position_id="pos-1",
        action=OrderAction.BUY,
        qty=1,
        price_cents=Decimal(50),
        fee=make_fee(),
        filled_at=NOW,
        is_confirmed=True,
        recorded_at=NOW,
    )
    base.update(overrides)
    return OrderFill(**base)
