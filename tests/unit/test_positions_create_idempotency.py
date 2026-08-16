"""Tests obligatorios de idempotencia real de `POST /positions`
(auditoría posterior a Tramo 3): `Position.create_intent_id`, `UNIQUE`
en SQLite, verificado en el repositorio y en la API end-to-end,
incluida concurrencia real con threads."""
from __future__ import annotations

import sqlite3
import threading
from decimal import Decimal

import pytest

from src.positions.enums import PositionSource
from src.positions.exceptions import IdempotencyConflictError, InvariantViolationError
from src.positions.positions_repository import PositionsRepository
from tests.unit.positions_factories import make_position


def _repo(tmp_path) -> PositionsRepository:
    return PositionsRepository(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------
# 1. create Position con key nueva -> crea una
# ---------------------------------------------------------------------


def test_1_new_intent_key_creates_position(tmp_path):
    repo = _repo(tmp_path)
    created = repo.create_position(make_position(position_id="pos-1", create_intent_id="intent-new"))
    assert created.create_intent_id == "intent-new"
    assert repo.get_position("pos-1") == created


# ---------------------------------------------------------------------
# 2. misma key + mismo payload -> misma Position, una sola fila
# ---------------------------------------------------------------------


def test_2_same_key_same_payload_returns_same_position_no_duplicate_row(tmp_path):
    repo = _repo(tmp_path)
    first = repo.create_position(make_position(position_id="pos-1", create_intent_id="intent-x"))
    # Segundo intento: distinto position_id "propuesto" (simula un
    # cliente que reintenta y genera un position_id nuevo del lado
    # cliente, pero envía la MISMA idempotency key) -- debe devolver la
    # Position YA creada, con su position_id ORIGINAL, sin crear una fila
    # nueva.
    second = repo.create_position(
        make_position(position_id="pos-1-DIFFERENT-PROPOSED-ID", create_intent_id="intent-x")
    )
    assert second == first
    assert second.position_id == "pos-1"  # el ID original, no el "propuesto" en el reintento

    conn = sqlite3.connect(repo.db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM positions WHERE create_intent_id = 'intent-x'").fetchone()
    conn.close()
    assert count == 1

    # Tampoco se duplica el PositionEvent de apertura.
    events = repo.get_position_events("pos-1")
    assert len(events) == 1


# ---------------------------------------------------------------------
# 3. misma key + payload lógico diferente -> 409 (IdempotencyConflictError)
# ---------------------------------------------------------------------


def test_3_same_key_different_payload_raises_conflict(tmp_path):
    repo = _repo(tmp_path)
    repo.create_position(
        make_position(position_id="pos-1", create_intent_id="intent-y", kalshi_ticker="KXMLBGAME-A", side="YES")
    )
    with pytest.raises(IdempotencyConflictError, match="ya fue usado con datos"):
        repo.create_position(
            make_position(position_id="pos-2", create_intent_id="intent-y", kalshi_ticker="KXMLBGAME-A", side="NO")
        )
    # Ningún efecto secundario del intento en conflicto.
    assert repo.get_position("pos-2") is None
    conn = sqlite3.connect(repo.db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM positions WHERE create_intent_id = 'intent-y'").fetchone()
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------
# 4. requests concurrentes con la misma key -> exactamente una Position
# ---------------------------------------------------------------------


def test_4_concurrent_requests_same_key_create_exactly_one_position(tmp_path):
    repo = _repo(tmp_path)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker(position_id: str):
        try:
            barrier.wait(timeout=5)  # maximiza la chance de colisión real
            position = make_position(position_id=position_id, create_intent_id="intent-concurrent")
            results.append(repo.create_position(position))
        except Exception as exc:  # noqa: BLE001 -- se captura para inspección, no se traga
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("pos-thread-1",))
    t2 = threading.Thread(target=worker, args=("pos-thread-2",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"ningún thread debería fallar con payload idéntico: {errors}"
    assert len(results) == 2
    # Ambos threads deben haber recibido la MISMA Position (mismo
    # position_id real, sin importar cuál "propuso" originalmente).
    assert results[0].position_id == results[1].position_id

    conn = sqlite3.connect(repo.db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM positions WHERE create_intent_id = 'intent-concurrent'").fetchone()
    conn.close()
    assert count == 1  # exactamente una fila, pese a la carrera real


# ---------------------------------------------------------------------
# 5. fallo transaccional no deja idempotencia huérfana
# ---------------------------------------------------------------------


def test_5_failed_attempt_leaves_no_orphaned_intent_key(tmp_path):
    """Un intento con datos internamente inconsistentes (open_contracts
    != 0) falla ANTES de tocar la tabla -- la key nunca queda "consumida"
    apuntando a una fila inexistente/incompleta. Un reintento posterior
    con la MISMA key y datos válidos crea la Position con normalidad."""
    repo = _repo(tmp_path)
    bad_position = make_position(position_id="pos-1", create_intent_id="intent-retry", open_contracts=1)
    with pytest.raises(InvariantViolationError):
        repo.create_position(bad_position)

    conn = sqlite3.connect(repo.db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM positions WHERE create_intent_id = 'intent-retry'").fetchone()
    conn.close()
    assert count == 0  # la key NUNCA quedó consumida

    good_position = make_position(position_id="pos-1", create_intent_id="intent-retry", open_contracts=0)
    created = repo.create_position(good_position)
    assert created.position_id == "pos-1"


def test_5b_conflicting_intent_leaves_no_partial_row(tmp_path):
    """El caso 3 (conflicto) tampoco deja ningún rastro parcial -- el
    chequeo de conflicto ocurre ANTES de cualquier INSERT."""
    repo = _repo(tmp_path)
    repo.create_position(make_position(position_id="pos-1", create_intent_id="intent-z", kalshi_ticker="K-A"))
    with pytest.raises(IdempotencyConflictError):
        repo.create_position(make_position(position_id="pos-2", create_intent_id="intent-z", kalshi_ticker="K-B"))

    all_rows = repo.list_all_positions()
    assert len(all_rows) == 1
    assert all_rows[0].position_id == "pos-1"


# ---------------------------------------------------------------------
# 6. keys distintas permiten dos Positions legítimas aunque ticker/side
# coincidan -- NUNCA ticker+side como idempotencia global
# ---------------------------------------------------------------------


def test_6_different_keys_allow_two_legitimate_positions_same_ticker_side(tmp_path):
    repo = _repo(tmp_path)
    first = repo.create_position(
        make_position(position_id="pos-1", create_intent_id="intent-first", kalshi_ticker="KXMLBGAME-SAME", side="YES")
    )
    second = repo.create_position(
        make_position(position_id="pos-2", create_intent_id="intent-second", kalshi_ticker="KXMLBGAME-SAME", side="YES")
    )
    assert first.position_id != second.position_id
    assert first.kalshi_ticker == second.kalshi_ticker == "KXMLBGAME-SAME"
    assert first.side == second.side == "YES"
    assert len(repo.list_all_positions()) == 2
