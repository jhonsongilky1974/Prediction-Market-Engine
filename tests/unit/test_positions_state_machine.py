"""Tests de src/positions/state_machine.py."""
from __future__ import annotations

import pytest

from src.positions.enums import OrderStatus, PositionStatus
from src.positions.exceptions import InvalidStateTransitionError
from src.positions.state_machine import (
    ORDER_NON_TERMINAL_STATUSES,
    ORDER_TERMINAL_STATUSES,
    validate_order_transition,
    validate_position_transition,
)


def test_order_unknown_is_non_terminal():
    assert OrderStatus.UNKNOWN in ORDER_NON_TERMINAL_STATUSES
    assert OrderStatus.UNKNOWN not in ORDER_TERMINAL_STATUSES


@pytest.mark.parametrize(
    "src,dst",
    [
        (OrderStatus.PLANNED, OrderStatus.SUBMITTED),
        (OrderStatus.SUBMITTED, OrderStatus.PENDING),
        (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PENDING, OrderStatus.FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELED),
        (OrderStatus.PENDING, OrderStatus.UNKNOWN),
        (OrderStatus.UNKNOWN, OrderStatus.FILLED),
        (OrderStatus.UNKNOWN, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.UNKNOWN, OrderStatus.CANCELED),
        (OrderStatus.UNKNOWN, OrderStatus.REJECTED),
        # Captura 100% manual (Tramo 1): un fill puede llegar directo
        # desde PLANNED/SUBMITTED sin pasar antes por PENDING.
        (OrderStatus.PLANNED, OrderStatus.FILLED),
        (OrderStatus.PLANNED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.FILLED),
    ],
)
def test_order_valid_transitions(src, dst):
    validate_order_transition(src, dst)  # no debe lanzar


@pytest.mark.parametrize(
    "src,dst",
    [
        (OrderStatus.FILLED, OrderStatus.PLANNED),
        (OrderStatus.CANCELED, OrderStatus.SUBMITTED),
        (OrderStatus.REJECTED, OrderStatus.PENDING),
        (OrderStatus.PLANNED, OrderStatus.PENDING),  # salto no permitido
        (OrderStatus.PLANNED, OrderStatus.REJECTED),  # sin pasar por SUBMITTED/PENDING
    ],
)
def test_order_invalid_transitions_rejected(src, dst):
    with pytest.raises(InvalidStateTransitionError):
        validate_order_transition(src, dst)


def test_order_terminal_statuses_have_no_outgoing_transitions():
    for status in ORDER_TERMINAL_STATUSES:
        for candidate in OrderStatus:
            with pytest.raises(InvalidStateTransitionError):
                validate_order_transition(status, candidate)


@pytest.mark.parametrize(
    "src,dst",
    [
        (PositionStatus.NEW, PositionStatus.OPEN),
        (PositionStatus.OPEN, PositionStatus.RECOVERY_IN_PROGRESS),
        (PositionStatus.OPEN, PositionStatus.CAPITAL_RECOVERED),
        (PositionStatus.RECOVERY_IN_PROGRESS, PositionStatus.RECOVERY_IN_PROGRESS),
        (PositionStatus.RECOVERY_IN_PROGRESS, PositionStatus.CAPITAL_RECOVERED),
        (PositionStatus.CAPITAL_RECOVERED, PositionStatus.RECOVERY_IN_PROGRESS),  # reversión F3
        (PositionStatus.CAPITAL_RECOVERED, PositionStatus.CLOSED),
        (PositionStatus.OPEN, PositionStatus.SETTLED_WIN),
        (PositionStatus.OPEN, PositionStatus.SETTLED_LOSS),
    ],
)
def test_position_valid_transitions(src, dst):
    validate_position_transition(src, dst)


def test_position_same_status_is_always_allowed():
    for status in PositionStatus:
        validate_position_transition(status, status)


@pytest.mark.parametrize(
    "src,dst",
    [
        (PositionStatus.CLOSED, PositionStatus.OPEN),
        (PositionStatus.SETTLED_WIN, PositionStatus.CAPITAL_RECOVERED),
        (PositionStatus.NEW, PositionStatus.CAPITAL_RECOVERED),
    ],
)
def test_position_invalid_transitions_rejected(src, dst):
    with pytest.raises(InvalidStateTransitionError):
        validate_position_transition(src, dst)
