"""Tests de OpportunityRepository (Fase 3, Paso 3.5). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.5 -- TODOS los tests usan
`db_path=tmp_path / "test.db"`, NUNCA la ruta de producción
(`data/engine.db`). Casos: inserción simple, determinismo de
opportunity_id, encadenamiento de state_version/previous_signal_id,
rechazo de UPDATE/DELETE crudo, foreign_keys=ON.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from src.opportunity.opportunity_repository import OpportunityRepository
from src.opportunity.schemas import compute_opportunity_id, compute_selection_id
from src.signals.signal_schema import Side
from tests.unit.fase3_factories import NOW, make_opportunity, make_opportunity_evaluation


def _repo(tmp_path) -> OpportunityRepository:
    return OpportunityRepository(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------
# Inserción simple + round-trip
# ---------------------------------------------------------------------


def test_save_and_get_latest_opportunity(tmp_path):
    repo = _repo(tmp_path)
    opportunity = make_opportunity()
    repo.save_opportunity(opportunity)
    fetched = repo.get_latest_opportunity(opportunity.opportunity_id)
    assert fetched == opportunity


def test_save_and_get_latest_evaluation(tmp_path):
    repo = _repo(tmp_path)
    evaluation = make_opportunity_evaluation()
    repo.save_opportunity_evaluation(evaluation)
    fetched = repo.get_latest_evaluation(evaluation.opportunity_id)
    assert fetched == evaluation


def test_get_latest_returns_none_when_nothing_saved(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_latest_opportunity("opp-does-not-exist") is None
    assert repo.get_latest_evaluation("opp-does-not-exist") is None


# ---------------------------------------------------------------------
# opportunity_id determinístico -- reconstruible sin tabla de lookup
# ---------------------------------------------------------------------


def test_opportunity_id_is_deterministic_across_saves(tmp_path):
    repo = _repo(tmp_path)
    selection_id = compute_selection_id("KXMLBGAME-1", Side.YES)
    expected_id = compute_opportunity_id("evt-1", selection_id)

    opp_a = make_opportunity(event_id="evt-1", market_id="KXMLBGAME-1", side=Side.YES)
    opp_b = make_opportunity(event_id="evt-1", market_id="KXMLBGAME-1", side=Side.YES)
    assert opp_a.opportunity_id == opp_b.opportunity_id == expected_id

    repo.save_opportunity(opp_a)
    fetched = repo.get_latest_opportunity(expected_id)
    assert fetched.opportunity_id == expected_id


# ---------------------------------------------------------------------
# Encadenamiento: state_version + previous_signal_id
# ---------------------------------------------------------------------


def test_second_opportunity_state_increments_version_and_chains(tmp_path):
    repo = _repo(tmp_path)
    v1 = make_opportunity(state_version=1, previous_signal_id=None)
    repo.save_opportunity(v1)

    v2 = make_opportunity(
        state_version=2, previous_signal_id="oe-1", last_evaluated_at=NOW + timedelta(hours=1)
    )
    repo.save_opportunity(v2)

    latest = repo.get_latest_opportunity(v1.opportunity_id)
    assert latest.state_version == 2
    assert latest.previous_signal_id == "oe-1"

    history = repo.get_opportunity_history(v1.opportunity_id)
    assert [o.state_version for o in history] == [1, 2]
    assert history[0] == v1
    assert history[1] == v2


def test_first_opportunity_never_overwritten_by_second(tmp_path):
    """La primera fila sigue existiendo intacta tras insertar la
    segunda -- nunca se sobrescribe."""
    repo = _repo(tmp_path)
    v1 = make_opportunity(state_version=1, previous_signal_id=None)
    repo.save_opportunity(v1)
    v2 = make_opportunity(state_version=2, previous_signal_id="oe-1")
    repo.save_opportunity(v2)

    history = repo.get_opportunity_history(v1.opportunity_id)
    assert history[0] == v1  # exactamente igual a como se guardó


def test_opportunity_state_version_gap_rejected(tmp_path):
    repo = _repo(tmp_path)
    jump = make_opportunity(state_version=3, previous_signal_id="oe-2")
    with pytest.raises(ValueError, match="state_version=3.*se esperaba 1"):
        repo.save_opportunity(jump)


def test_opportunity_state_version_duplicate_rejected(tmp_path):
    repo = _repo(tmp_path)
    v1 = make_opportunity(state_version=1, previous_signal_id=None)
    repo.save_opportunity(v1)
    duplicate = make_opportunity(state_version=1, previous_signal_id=None)
    with pytest.raises(ValueError, match="se esperaba 2"):
        repo.save_opportunity(duplicate)


def test_opportunity_previous_signal_id_required_after_first_version(tmp_path):
    repo = _repo(tmp_path)
    v1 = make_opportunity(state_version=1, previous_signal_id=None)
    repo.save_opportunity(v1)
    v2_missing_link = make_opportunity(state_version=2, previous_signal_id=None)
    with pytest.raises(ValueError, match="previous_signal_id no puede ser None"):
        repo.save_opportunity(v2_missing_link)


def test_second_evaluation_increments_state_version(tmp_path):
    repo = _repo(tmp_path)
    e1 = make_opportunity_evaluation(evaluation_id="oe-1", state_version=1)
    repo.save_opportunity_evaluation(e1)
    e2 = make_opportunity_evaluation(evaluation_id="oe-2", state_version=2)
    repo.save_opportunity_evaluation(e2)

    latest = repo.get_latest_evaluation(e1.opportunity_id)
    assert latest.evaluation_id == "oe-2"
    assert latest.state_version == 2

    all_evaluations = repo.get_evaluations_for_opportunity(e1.opportunity_id)
    assert [e.evaluation_id for e in all_evaluations] == ["oe-1", "oe-2"]


def test_evaluation_state_version_gap_rejected(tmp_path):
    repo = _repo(tmp_path)
    jump = make_opportunity_evaluation(evaluation_id="oe-3", state_version=3)
    with pytest.raises(ValueError, match="state_version=3.*se esperaba 1"):
        repo.save_opportunity_evaluation(jump)


# ---------------------------------------------------------------------
# Append-only reforzado a nivel de motor (SQL crudo, fuera de la clase)
# ---------------------------------------------------------------------


def test_raw_update_on_opportunities_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.save_opportunity(make_opportunity())
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE opportunities SET state_version = 99")
    conn.close()


def test_raw_delete_on_opportunities_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.save_opportunity(make_opportunity())
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM opportunities")
    conn.close()


def test_raw_update_on_opportunity_evaluations_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.save_opportunity_evaluation(make_opportunity_evaluation())
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE opportunity_evaluations SET state_version = 99")
    conn.close()


def test_raw_delete_on_opportunity_evaluations_rejected(tmp_path):
    repo = _repo(tmp_path)
    repo.save_opportunity_evaluation(make_opportunity_evaluation())
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM opportunity_evaluations")
    conn.close()


# ---------------------------------------------------------------------
# PRAGMA foreign_keys = ON por conexión
# ---------------------------------------------------------------------


def test_foreign_keys_pragma_is_on(tmp_path):
    repo = _repo(tmp_path)
    with repo._connect() as conn:  # inspección directa, mismo patrón que HistoryRepository
        (value,) = conn.execute("PRAGMA foreign_keys").fetchone()
    assert value == 1


# ---------------------------------------------------------------------
# Cero cambios a repository.py/history_repository.py de Fase 1/2
# ---------------------------------------------------------------------


def test_does_not_import_repository_or_history_repository():
    import ast

    import src.opportunity.opportunity_repository as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden = {"src.storage.repository", "src.storage.history_repository"}
    assert not (imported_modules & forbidden)
