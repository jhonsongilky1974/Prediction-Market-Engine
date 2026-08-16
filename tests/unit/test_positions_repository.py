"""Tests de PositionsRepository (Fase 6, Tramo 1). TODOS los tests usan
`db_path=tmp_path / "test.db"`, NUNCA la ruta de producción
(`data/engine.db`) -- mismo patrón que
`tests/unit/test_opportunity_repository.py`. Casos obligatorios del
alcance autorizado (E): 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18
(1/2/6/7/8 ya cubiertos en test_positions_capital_recovery.py como
lógica pura)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.positions.capital_recovery import is_capital_recovery_confirmed
from src.positions.enums import (
    FeeStatus,
    OrderAction,
    OrderEventReason,
    OrderStatus,
    PositionSource,
    PositionStatus,
)
from src.positions.exceptions import (
    IdempotencyConflictError,
    InvariantViolationError,
    NonTerminalOrderExistsError,
    OptimisticLockError,
)
from src.positions.positions_repository import PositionsRepository
from src.positions.schemas import Fee
from tests.unit.positions_factories import NOW, make_fee, make_fill, make_order, make_position


def _repo(tmp_path) -> PositionsRepository:
    return PositionsRepository(db_path=tmp_path / "test.db")


def _t(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


# ---------------------------------------------------------------------
# create_position / get_position
# ---------------------------------------------------------------------


def test_create_and_get_position(tmp_path):
    repo = _repo(tmp_path)
    pos = make_position(position_id="pos-1")
    repo.create_position(pos)
    fetched = repo.get_position("pos-1")
    assert fetched == pos


def test_get_position_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_position("does-not-exist") is None


def test_create_position_duplicate_id_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    with pytest.raises(IdempotencyConflictError, match="ya existe"):
        repo.create_position(make_position(position_id="pos-1"))


def test_create_position_records_position_opened_event(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    events = repo.get_position_events("pos-1")
    assert len(events) == 1
    assert events[0].from_status is None
    assert events[0].to_status == PositionStatus.OPEN


# ---------------------------------------------------------------------
# create_order + idempotencia (Test obligatorio #10) + F5 (Caso C)
# ---------------------------------------------------------------------


def test_create_and_get_order(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    order = make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-1")
    repo.create_order(order)
    assert repo.get_order("ord-1") == order


def test_create_order_idempotent_same_intent_is_noop(tmp_path):
    """Test obligatorio #10: idempotency key repetida no crea duplicado."""
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    order = make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-shared")
    first = repo.create_order(order)
    retry = repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-shared"))
    assert first == retry
    assert len(repo.get_orders_for_position("pos-1")) == 1


def test_create_order_same_intent_different_data_raises_conflict(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-shared", requested_qty=10))
    with pytest.raises(IdempotencyConflictError):
        repo.create_order(make_order(order_id="ord-2", position_id="pos-1", intent_id="intent-shared", requested_qty=99))


def test_create_order_rejected_while_non_terminal_order_exists(tmp_path):
    """F5: no se puede crear una segunda Order mientras la primera no
    esté en un estado terminal."""
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-1"))
    with pytest.raises(NonTerminalOrderExistsError):
        repo.create_order(make_order(order_id="ord-2", position_id="pos-1", intent_id="intent-2"))


def test_has_non_terminal_order(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    assert repo.has_non_terminal_order("pos-1") is False
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="intent-1"))
    assert repo.has_non_terminal_order("pos-1") is True


# ---------------------------------------------------------------------
# apply_fill -- flujo básico + recomputo de Order/Position
# ---------------------------------------------------------------------


def test_apply_fill_full_buy_updates_order_and_position(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-buy", position_id="pos-1", intent_id="i-buy", action=OrderAction.BUY, requested_qty=19))

    fill = make_fill(
        fill_id="fill-buy-1", order_id="ord-buy", position_id="pos-1", action=OrderAction.BUY,
        qty=19, price_cents=Decimal(50), fee=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)),
        filled_at=_t(1), recorded_at=_t(1),
    )
    order, position = repo.apply_fill(fill, expected_order_version=1)

    assert order.status == OrderStatus.FILLED
    assert order.confirmed_filled_qty == 19
    assert order.avg_fill_price_cents == Decimal(50)
    assert order.version == 2

    assert position.open_contracts == 19
    assert position.capital_invested_cents == Decimal(950)
    assert position.capital_invested_fee_status == FeeStatus.ESTIMATED
    assert position.status == PositionStatus.OPEN  # nada vendido todavia
    assert position.version == 2


def test_apply_fill_qty_exceeding_requested_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-buy", position_id="pos-1", intent_id="i-buy", requested_qty=5))
    fill = make_fill(fill_id="f1", order_id="ord-buy", position_id="pos-1", qty=6)
    with pytest.raises(InvariantViolationError, match="excede lo pendiente"):
        repo.apply_fill(fill, expected_order_version=1)


# ---------------------------------------------------------------------
# Test obligatorio #3 -- partial fill de venta
# ---------------------------------------------------------------------


def _open_kirkin_position(repo, position_id="pos-1"):
    repo.create_position(make_position(position_id=position_id))
    repo.create_order(make_order(order_id="ord-buy", position_id=position_id, intent_id="i-buy", action=OrderAction.BUY, requested_qty=19))
    fill = make_fill(
        fill_id="fill-buy-1", order_id="ord-buy", position_id=position_id, action=OrderAction.BUY,
        qty=19, price_cents=Decimal(50), fee=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)),
        filled_at=_t(1), recorded_at=_t(1),
    )
    repo.apply_fill(fill, expected_order_version=1)


def test_case_partial_sell_fill(tmp_path):
    """Test obligatorio #3 (Caso C del Design Proposal): se intenta
    vender 15, solo se ejecutan 9."""
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=15, planned_target_price_cents=Decimal(63)))

    fill = make_fill(
        fill_id="fill-sell-1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL,
        qty=9, price_cents=Decimal(63), fee=make_fee(), filled_at=_t(2), recorded_at=_t(2),
    )
    order, position = repo.apply_fill(fill, expected_order_version=1)

    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.confirmed_filled_qty == 9
    # F12: open_contracts se recalcula con la qty CONFIRMADA (9), no con
    # requested_qty (15).
    assert position.open_contracts == 19 - 9
    assert position.status == PositionStatus.RECOVERY_IN_PROGRESS

    # Caso C: no se puede crear una orden nueva mientras la original
    # sigue PARTIALLY_FILLED (no terminal) -- evita doble-venta.
    with pytest.raises(NonTerminalOrderExistsError):
        repo.create_order(make_order(order_id="ord-sell-extra", position_id="pos-1", intent_id="i-sell-extra", action=OrderAction.SELL, requested_qty=6))


# ---------------------------------------------------------------------
# Test obligatorio #4/#5 -- múltiples partial fills a precios distintos,
# recuperación completada mediante varias ventas parciales
# ---------------------------------------------------------------------


def test_case_multiple_partial_sells_reach_capital_recovered(tmp_path):
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=15, planned_target_price_cents=Decimal(63)))

    def _sell(fill_id, qty, price, version):
        fill = make_fill(
            fill_id=fill_id, order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL,
            qty=qty, price_cents=Decimal(price), fee=make_fee(), filled_at=_t(version), recorded_at=_t(version),
        )
        return repo.apply_fill(fill, expected_order_version=version)

    order, position = _sell("s1", 6, 63, 1)
    assert position.status == PositionStatus.RECOVERY_IN_PROGRESS
    assert position.capital_recovered_cents == Decimal(6 * 63)

    order, position = _sell("s2", 5, 66, 2)
    assert position.capital_recovered_cents == Decimal(6 * 63 + 5 * 66)

    order, position = _sell("s3", 4, 69, 3)
    # 378 + 330 + 276 = 984 >= 950 -> recuperado
    assert position.capital_recovered_cents == Decimal(984)
    assert position.status == PositionStatus.CAPITAL_RECOVERED
    assert position.runner_contracts == 4  # 19 - 15
    assert order.status == OrderStatus.FILLED

    # Test obligatorio #17: una vez recuperado, el plan recomienda 0.
    plan = repo.compute_and_save_plan(
        plan_id="plan-1", position_id="pos-1", planned_target_price_cents=Decimal(50),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)), computed_at=_t(4),
    )
    assert plan.contracts_to_sell == 0


# ---------------------------------------------------------------------
# Test obligatorio #9 -- nunca declarar CAPITAL_RECOVERED definitivo con
# fee desconocido; reversión cuando el fee real es mayor
# ---------------------------------------------------------------------


def test_case_capital_recovered_provisional_and_reversible(tmp_path):
    repo = _repo(tmp_path)
    # Compra con fee ESTIMATED(0) -- capital_invested_fee_status queda
    # ESTIMATED, no KNOWN.
    _open_kirkin_position(repo)
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=19, planned_target_price_cents=Decimal(63)))

    fill = make_fill(
        fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL,
        qty=19, price_cents=Decimal(63), fee=make_fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
        filled_at=_t(2), recorded_at=_t(2),
    )
    _, position = repo.apply_fill(fill, expected_order_version=1)
    assert position.status == PositionStatus.CAPITAL_RECOVERED
    # Numéricamente recuperado, PERO el fee de ENTRADA sigue ESTIMATED:
    # nunca se declara definitivo.
    assert position.capital_invested_fee_status == FeeStatus.ESTIMATED
    assert is_capital_recovery_confirmed(
        status_is_capital_recovered=(position.status == PositionStatus.CAPITAL_RECOVERED),
        capital_invested_fee_status=position.capital_invested_fee_status,
        capital_recovered_fee_status=position.capital_recovered_fee_status,
    ) is False


def test_case_capital_recovered_reverses_when_real_fee_is_higher(tmp_path):
    """F3: reversión a RECOVERY_IN_PROGRESS si un fee real hace que el
    capital remanente vuelva a ser positivo -- aquí simulado con una
    compra adicional que reabre capital_remaining tras haber llegado a
    CAPITAL_RECOVERED (mismo mecanismo de recompute, cualquier fill que
    empuje capital_remaining > 0 de nuevo dispara la reversión)."""
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-buy", position_id="pos-1", intent_id="i-buy", action=OrderAction.BUY, requested_qty=10, planned_target_price_cents=Decimal(50)))
    repo.apply_fill(
        make_fill(fill_id="b1", order_id="ord-buy", position_id="pos-1", action=OrderAction.BUY, qty=10, price_cents=Decimal(50), fee=make_fee(), filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=10, planned_target_price_cents=Decimal(60)))
    _, position = repo.apply_fill(
        make_fill(fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL, qty=10, price_cents=Decimal(60), fee=make_fee(), filled_at=_t(2), recorded_at=_t(2)),
        expected_order_version=1,
    )
    assert position.status == PositionStatus.CAPITAL_RECOVERED  # 600 >= 500

    # Fill compensatorio de corrección (Test #18: nunca se edita el fill
    # histórico, se registra uno nuevo) que revela una fee de compra real
    # mayor a la asumida -- aquí modelado como un BUY adicional que
    # incrementa capital_invested por encima de lo ya recuperado.
    repo.create_order(make_order(order_id="ord-buy-2", position_id="pos-1", intent_id="i-buy-2", action=OrderAction.BUY, requested_qty=5, planned_target_price_cents=Decimal(50)))
    _, position = repo.apply_fill(
        make_fill(fill_id="b2", order_id="ord-buy-2", position_id="pos-1", action=OrderAction.BUY, qty=5, price_cents=Decimal(50), fee=make_fee(), filled_at=_t(3), recorded_at=_t(3)),
        expected_order_version=1,
    )
    assert position.capital_invested_cents == Decimal(750)  # 500 + 250
    assert position.capital_remaining_computed > 0
    assert position.status == PositionStatus.RECOVERY_IN_PROGRESS  # reversión


# ---------------------------------------------------------------------
# Test obligatorio #6/7/8 a nivel de repositorio -- ya cubiertos como
# lógica pura; aquí solo se confirma que compute_and_save_plan propaga
# fielmente el status de fee.
# ---------------------------------------------------------------------


def test_compute_and_save_plan_is_advisory_and_does_not_mutate_position(tmp_path):
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    before = repo.get_position("pos-1")
    plan = repo.compute_and_save_plan(
        plan_id="plan-1", position_id="pos-1", planned_target_price_cents=Decimal(63),
        fee_assumption=Fee(status=FeeStatus.ESTIMATED, cents=Decimal(0)), computed_at=_t(5),
    )
    after = repo.get_position("pos-1")
    assert before == after  # nunca muta la Position
    assert plan.contracts_to_sell == 16
    assert plan.provisional is True
    assert repo.get_position_plans("pos-1") == [plan]


# ---------------------------------------------------------------------
# Test obligatorio #11 -- optimistic locking
# ---------------------------------------------------------------------


def test_optimistic_lock_stale_version_on_apply_fill_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1", requested_qty=10))
    fill1 = make_fill(fill_id="f1", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(1), recorded_at=_t(1))
    repo.apply_fill(fill1, expected_order_version=1)  # ord-1 ahora version=2

    fill2 = make_fill(fill_id="f2", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(2), recorded_at=_t(2))
    with pytest.raises(OptimisticLockError):
        repo.apply_fill(fill2, expected_order_version=1)  # version stale (debería ser 2)

    # Nada se escribió a medias: el segundo fill nunca quedó registrado.
    assert repo.get_fills_for_order("ord-1") == [fill1]
    order = repo.get_order("ord-1")
    assert order.confirmed_filled_qty == 5  # sin cambios


def test_optimistic_lock_correct_version_succeeds(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1", requested_qty=10))
    fill1 = make_fill(fill_id="f1", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(1), recorded_at=_t(1))
    order, _ = repo.apply_fill(fill1, expected_order_version=1)
    assert order.version == 2

    fill2 = make_fill(fill_id="f2", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(2), recorded_at=_t(2))
    order2, _ = repo.apply_fill(fill2, expected_order_version=2)  # version correcta
    assert order2.confirmed_filled_qty == 10
    assert order2.status == OrderStatus.FILLED


def test_optimistic_lock_on_update_order_status(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1"))
    with pytest.raises(OptimisticLockError):
        repo.update_order_status(
            "ord-1", expected_version=99, new_status=OrderStatus.SUBMITTED, reason=OrderEventReason.STATUS_TRANSITION
        )
    updated = repo.update_order_status(
        "ord-1", expected_version=1, new_status=OrderStatus.SUBMITTED, reason=OrderEventReason.STATUS_TRANSITION
    )
    assert updated.status == OrderStatus.SUBMITTED
    assert updated.version == 2


# ---------------------------------------------------------------------
# Test obligatorio #12 -- cancel/replace sin alterar fills históricos
# ---------------------------------------------------------------------


def test_case_cancel_replace_preserves_historical_fills(tmp_path):
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=15, planned_target_price_cents=Decimal(63)))
    repo.apply_fill(
        make_fill(fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL, qty=9, price_cents=Decimal(63), fee=make_fee(), filled_at=_t(2), recorded_at=_t(2)),
        expected_order_version=1,
    )
    order_before_cancel = repo.get_order("ord-sell")
    assert order_before_cancel.status == OrderStatus.PARTIALLY_FILLED
    assert order_before_cancel.confirmed_filled_qty == 9

    canceled = repo.update_order_status(
        "ord-sell", expected_version=order_before_cancel.version, new_status=OrderStatus.CANCELED,
        reason=OrderEventReason.CANCEL_REPLACE, occurred_at=_t(3),
    )
    assert canceled.status == OrderStatus.CANCELED
    assert canceled.confirmed_filled_qty == 9  # los fills confirmados NUNCA se pierden/resetean

    fills_after_cancel = repo.get_fills_for_order("ord-sell")
    assert len(fills_after_cancel) == 1
    assert fills_after_cancel[0].qty == 9  # fill histórico intacto

    replacement = make_order(
        order_id="ord-sell-2", position_id="pos-1", intent_id="i-sell-2", action=OrderAction.SELL,
        requested_qty=6, planned_target_price_cents=Decimal(66), replaces_order_id="ord-sell",
    )
    created = repo.create_order(replacement)
    assert created.replaces_order_id == "ord-sell"
    # El fill original sigue exactamente igual tras crear el reemplazo.
    assert repo.get_fills_for_order("ord-sell") == fills_after_cancel


# ---------------------------------------------------------------------
# Test obligatorio #13 -- reinicio/reapertura de DB conserva estado
# ---------------------------------------------------------------------


def test_case_restart_reopening_db_preserves_state(tmp_path):
    db_path = tmp_path / "restart.db"
    repo1 = PositionsRepository(db_path=db_path)
    repo1.create_position(make_position(position_id="pos-1"))
    repo1.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1", requested_qty=5))
    repo1.apply_fill(
        make_fill(fill_id="f1", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )

    repo2 = PositionsRepository(db_path=db_path)  # "reinicio": nueva instancia, mismo archivo
    assert repo2.get_position("pos-1") == repo1.get_position("pos-1")
    assert repo2.get_order("ord-1") == repo1.get_order("ord-1")
    assert repo2.get_fills_for_position("pos-1") == repo1.get_fills_for_position("pos-1")


# ---------------------------------------------------------------------
# Test obligatorio #14 -- dos posiciones simultáneas completamente
# aisladas
# ---------------------------------------------------------------------


def test_case_two_positions_are_isolated(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-a", kalshi_ticker="KXMLBGAME-A"))
    repo.create_position(make_position(position_id="pos-b", kalshi_ticker="KXMLBGAME-B"))

    repo.create_order(make_order(order_id="ord-a", position_id="pos-a", intent_id="i-a", requested_qty=10))
    repo.create_order(make_order(order_id="ord-b", position_id="pos-b", intent_id="i-b", requested_qty=20))

    repo.apply_fill(
        make_fill(fill_id="fa", order_id="ord-a", position_id="pos-a", qty=10, price_cents=Decimal(40), filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )
    repo.apply_fill(
        make_fill(fill_id="fb", order_id="ord-b", position_id="pos-b", qty=20, price_cents=Decimal(70), filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )

    pos_a = repo.get_position("pos-a")
    pos_b = repo.get_position("pos-b")
    assert pos_a.open_contracts == 10
    assert pos_a.capital_invested_cents == Decimal(400)
    assert pos_b.open_contracts == 20
    assert pos_b.capital_invested_cents == Decimal(1400)

    assert {f.fill_id for f in repo.get_fills_for_position("pos-a")} == {"fa"}
    assert {f.fill_id for f in repo.get_fills_for_position("pos-b")} == {"fb"}


# ---------------------------------------------------------------------
# Test obligatorio #15/#16 -- nunca open_contracts negativo / nunca
# vender más de lo abierto
# ---------------------------------------------------------------------


def test_case_sell_more_than_open_contracts_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-buy", position_id="pos-1", intent_id="i-buy", action=OrderAction.BUY, requested_qty=5))
    repo.apply_fill(
        make_fill(fill_id="b1", order_id="ord-buy", position_id="pos-1", action=OrderAction.BUY, qty=5, price_cents=Decimal(50), filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=6))
    with pytest.raises(InvariantViolationError, match="No se puede vender"):
        repo.apply_fill(
            make_fill(fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL, qty=6, price_cents=Decimal(60), filled_at=_t(2), recorded_at=_t(2)),
            expected_order_version=1,
        )
    # Estado intacto tras el rechazo.
    assert repo.get_position("pos-1").open_contracts == 5


# ---------------------------------------------------------------------
# Test obligatorio #18 -- reconciliación mediante nuevo evento/fill,
# nunca editando silenciosamente un fill histórico confirmado
# ---------------------------------------------------------------------


def test_case_raw_update_on_order_fills_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1", requested_qty=5))
    repo.apply_fill(
        make_fill(fill_id="f1", order_id="ord-1", position_id="pos-1", qty=5, filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE order_fills SET qty = 999 WHERE fill_id = 'f1'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM order_fills WHERE fill_id = 'f1'")
    conn.close()

    # La corrección legítima es un evento NUEVO -- p.ej. reconciliar
    # manualmente el estado de la Order agrega una fila nueva a
    # order_events, nunca reescribe el fill ya confirmado.
    order = repo.get_order("ord-1")
    assert order.status == OrderStatus.FILLED  # ya completo, nada que reconciliar
    events_before = repo.get_order_events("ord-1")
    fills_untouched = repo.get_fills_for_order("ord-1")
    assert fills_untouched[0].qty == 5  # sin cambios
    assert len(events_before) == 2  # ORDER_CREATED + FILL_RECORDED, ambos preexistentes intactos


def test_case_raw_update_on_position_events_and_order_events_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1"))
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE position_events SET to_status = 'CLOSED'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM position_events")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE order_events SET to_status = 'FILLED'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM order_events")
    conn.close()


def test_case_raw_update_on_position_plans_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.compute_and_save_plan(
        plan_id="plan-1", position_id="pos-1", planned_target_price_cents=Decimal(50),
        fee_assumption=Fee(status=FeeStatus.KNOWN, cents=Decimal(0)), computed_at=_t(1),
    )
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE position_plans SET contracts_to_sell = 999")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM position_plans")
    conn.close()


def test_case_reconciliation_of_unknown_order_uses_new_event(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1"))
    repo.create_order(make_order(order_id="ord-1", position_id="pos-1", intent_id="i-1"))
    order = repo.update_order_status(
        "ord-1", expected_version=1, new_status=OrderStatus.SUBMITTED, reason=OrderEventReason.STATUS_TRANSITION,
    )
    order = repo.update_order_status(
        "ord-1", expected_version=order.version, new_status=OrderStatus.UNKNOWN, reason=OrderEventReason.OTHER,
        reason_detail="conexión perdida tras enviar la orden",
    )
    assert order.status == OrderStatus.UNKNOWN
    assert repo.get_position("pos-1").blocked_by_unknown_order is True

    # Mientras esté UNKNOWN, no se puede crear otra orden (bloqueante).
    with pytest.raises(NonTerminalOrderExistsError):
        repo.create_order(make_order(order_id="ord-2", position_id="pos-1", intent_id="i-2"))

    reconciled = repo.update_order_status(
        "ord-1", expected_version=order.version, new_status=OrderStatus.CANCELED,
        reason=OrderEventReason.MANUAL_RECONCILIATION, reason_detail=None,
    )
    assert reconciled.status == OrderStatus.CANCELED
    assert repo.get_position("pos-1").blocked_by_unknown_order is False

    events = repo.get_order_events("ord-1")
    assert [e.to_status for e in events] == [
        OrderStatus.PLANNED, OrderStatus.SUBMITTED, OrderStatus.UNKNOWN, OrderStatus.CANCELED,
    ]
    # Reconciliación = evento nuevo, nunca reescritura de los anteriores.
    assert events[2].to_status == OrderStatus.UNKNOWN
    assert events[3].reason == OrderEventReason.MANUAL_RECONCILIATION


# ---------------------------------------------------------------------
# Auditoría posterior al Tramo 1 -- punto 2: realized_pnl_cents auditado
# y retirado por semántica engañosa (mezclaba proceeds de contratos
# vendidos contra capital de TODOS los contratos comprados, incluidos
# los que seguían abiertos). Estos tests demuestran que una posición
# parcialmente vendida expone únicamente las métricas honestas ya
# aprobadas (capital_invested_cents / capital_recovered_cents /
# capital_remaining_computed / status), y que el campo engañoso ya no
# existe en absoluto (no fue renombrado a otra cosa ambigua).
# ---------------------------------------------------------------------


def test_position_no_longer_exposes_realized_pnl_field(tmp_path):
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    position = repo.get_position("pos-1")
    assert not hasattr(position, "realized_pnl_cents")
    assert not hasattr(position, "realized_pnl_provisional")
    assert "realized_pnl_cents" not in position.model_dump()


def test_partial_sale_exposes_only_honest_capital_metrics_not_pnl(tmp_path):
    """Con 19 contratos @50c comprados y solo 6 vendidos @63c, la
    posición sigue con 13 contratos abiertos: `capital_invested_cents`
    (950) NUNCA debe compararse directamente contra
    `capital_recovered_cents` (378) como si fuera P&L -- eso mezclaría
    capital todavía en riesgo con proceeds de una venta parcial. Las
    métricas expuestas deben ser exactas y sin inventar un P&L."""
    repo = _repo(tmp_path)
    _open_kirkin_position(repo)
    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=6, planned_target_price_cents=Decimal(63)))
    _, position = repo.apply_fill(
        make_fill(fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL, qty=6, price_cents=Decimal(63), fee=make_fee(), filled_at=_t(2), recorded_at=_t(2)),
        expected_order_version=1,
    )
    assert position.open_contracts == 13  # 19 - 6, contratos siguen abiertos
    assert position.capital_invested_cents == Decimal(950)  # capital TOTAL, no solo lo vendido
    assert position.capital_recovered_cents == Decimal(378)  # 6*63, proceeds SOLO de lo vendido
    assert position.capital_remaining_computed == Decimal(950 - 378)  # 572, aún en riesgo
    assert position.status == PositionStatus.RECOVERY_IN_PROGRESS  # no un P&L, un estado de recuperación
    # Ningún atributo del modelo pretende ser "el P&L de esta posición".
    assert not hasattr(position, "realized_pnl_cents")


# ---------------------------------------------------------------------
# Auditoría posterior al Tramo 1 -- punto 3: CLOSED/SETTLED_WIN/
# SETTLED_LOSS son RESERVED_FOR_FUTURE_TRANSITION -- ningún método de
# PositionsRepository en el Tramo 1 los produce. `apply_fill` es el
# ÚNICO código que muta Position.status; sus dos únicas ramas asignan
# CAPITAL_RECOVERED o RECOVERY_IN_PROGRESS/OPEN (ver
# positions_repository.py). Este test recorre el ciclo completo
# (incluida la reversión F3) y confirma que el conjunto alcanzable es
# exactamente {OPEN, RECOVERY_IN_PROGRESS, CAPITAL_RECOVERED}.
# ---------------------------------------------------------------------


def test_position_terminal_settlement_states_unreachable_in_tramo1(tmp_path):
    repo = _repo(tmp_path)
    reachable_statuses = set()

    repo.create_position(make_position(position_id="pos-1"))
    reachable_statuses.add(repo.get_position("pos-1").status)  # OPEN al crear

    repo.create_order(make_order(order_id="ord-buy", position_id="pos-1", intent_id="i-buy", action=OrderAction.BUY, requested_qty=10, planned_target_price_cents=Decimal(50)))
    _, position = repo.apply_fill(
        make_fill(fill_id="b1", order_id="ord-buy", position_id="pos-1", action=OrderAction.BUY, qty=10, price_cents=Decimal(50), fee=make_fee(), filled_at=_t(1), recorded_at=_t(1)),
        expected_order_version=1,
    )
    reachable_statuses.add(position.status)  # OPEN (nada vendido aún)

    repo.create_order(make_order(order_id="ord-sell", position_id="pos-1", intent_id="i-sell", action=OrderAction.SELL, requested_qty=10, planned_target_price_cents=Decimal(60)))
    _, position = repo.apply_fill(
        make_fill(fill_id="s1", order_id="ord-sell", position_id="pos-1", action=OrderAction.SELL, qty=10, price_cents=Decimal(60), fee=make_fee(), filled_at=_t(2), recorded_at=_t(2)),
        expected_order_version=1,
    )
    reachable_statuses.add(position.status)  # CAPITAL_RECOVERED (600 >= 500)

    repo.create_order(make_order(order_id="ord-buy-2", position_id="pos-1", intent_id="i-buy-2", action=OrderAction.BUY, requested_qty=5, planned_target_price_cents=Decimal(50)))
    _, position = repo.apply_fill(
        make_fill(fill_id="b2", order_id="ord-buy-2", position_id="pos-1", action=OrderAction.BUY, qty=5, price_cents=Decimal(50), fee=make_fee(), filled_at=_t(3), recorded_at=_t(3)),
        expected_order_version=1,
    )
    reachable_statuses.add(position.status)  # RECOVERY_IN_PROGRESS (reversión F3)

    assert reachable_statuses == {
        PositionStatus.OPEN, PositionStatus.CAPITAL_RECOVERED, PositionStatus.RECOVERY_IN_PROGRESS,
    }
    assert PositionStatus.CLOSED not in reachable_statuses
    assert PositionStatus.SETTLED_WIN not in reachable_statuses
    assert PositionStatus.SETTLED_LOSS not in reachable_statuses
    assert PositionStatus.NEW not in reachable_statuses  # create_position exige status==OPEN directo


def test_list_open_positions_excludes_reserved_terminal_statuses(tmp_path):
    """`list_open_positions` debe seguir excluyendo correctamente
    CLOSED/SETTLED_* aunque ningún método público del Tramo 1 pueda
    producirlas -- se inserta una fila vía SQL crudo (bypass deliberado
    del repositorio, igual que los tests de trigger append-only) para
    validar la consulta de filtrado en sí misma, con independencia de
    que el estado sea alcanzable hoy."""
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-open"))
    repo.create_position(make_position(position_id="pos-closed"))

    conn = sqlite3.connect(repo.db_path)
    conn.execute("UPDATE positions SET status = 'CLOSED' WHERE position_id = 'pos-closed'")
    conn.commit()
    conn.close()

    open_ids = {p.position_id for p in repo.list_open_positions()}
    assert open_ids == {"pos-open"}
