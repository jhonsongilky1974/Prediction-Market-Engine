"""Tests de Phase 6 -- Tramo 5B: `src.advisory.order_conflicts`."""
from __future__ import annotations

from src.advisory.enums import OrderConflictCode
from src.advisory.order_conflicts import detect_order_conflicts, find_pending_order
from src.positions.enums import OrderAction, OrderStatus
from tests.unit.positions_factories import make_order


def test_find_pending_order_none_when_empty():
    assert find_pending_order([]) is None


def test_find_pending_order_ignores_terminal():
    order = make_order(status=OrderStatus.FILLED, confirmed_filled_qty=10)
    assert find_pending_order([order]) is None


def test_find_pending_order_returns_non_terminal():
    order = make_order(status=OrderStatus.PLANNED)
    assert find_pending_order([order]) is order


def test_no_conflicts_when_no_pending_order_and_not_blocked():
    conflicts = detect_order_conflicts(blocked_by_unknown_order=False, pending_order=None)
    assert conflicts == []


def test_pending_buy_order_produces_non_terminal_conflict_only():
    order = make_order(status=OrderStatus.PLANNED, action=OrderAction.BUY)
    conflicts = detect_order_conflicts(blocked_by_unknown_order=False, pending_order=order)
    codes = {c.code for c in conflicts}
    assert codes == {OrderConflictCode.NON_TERMINAL_ORDER_EXISTS}


def test_pending_sell_order_also_flags_contract_reservation():
    order = make_order(status=OrderStatus.PLANNED, action=OrderAction.SELL, requested_qty=5)
    conflicts = detect_order_conflicts(blocked_by_unknown_order=False, pending_order=order)
    codes = {c.code for c in conflicts}
    assert codes == {OrderConflictCode.NON_TERMINAL_ORDER_EXISTS, OrderConflictCode.SELL_ORDER_RESERVES_CONTRACTS}


def test_blocked_by_unknown_order_flag_produces_dedicated_conflict():
    order = make_order(status=OrderStatus.UNKNOWN)
    conflicts = detect_order_conflicts(blocked_by_unknown_order=True, pending_order=order)
    codes = {c.code for c in conflicts}
    assert OrderConflictCode.BLOCKED_BY_UNKNOWN_ORDER in codes
    assert OrderConflictCode.NON_TERMINAL_ORDER_EXISTS in codes


def test_conflicts_never_empty_detail():
    order = make_order(status=OrderStatus.PLANNED, action=OrderAction.SELL)
    conflicts = detect_order_conflicts(blocked_by_unknown_order=True, pending_order=order)
    for c in conflicts:
        assert c.detail.strip()
