"""Prueba de integración del entry point real `scripts/run_e2e.py` (Paso
0d): confirma que `main()` construye y pasa `HistoryRepository` a AMBOS
pipelines (MLB y tenis) tal como quedó cableado.

No usa fixtures artificiales: ejecuta el script real contra las APIs
reales (mismo patrón que `tests/integration/test_e2e_real.py`). Lo único
que se parchea son los CONSTRUCTORES `Repository`/`HistoryRepository` que
usa el script, para que apunten a bases temporales -- así se verifica el
wiring real sin escribir absolutamente nada en `data/engine.db`.
"""
from __future__ import annotations

import sqlite3
import sys

import pytest

import scripts.run_e2e as run_e2e_module
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

pytestmark = pytest.mark.integration


def test_run_e2e_main_injects_history_repository_into_both_pipelines(monkeypatch, tmp_path):
    captured = {}

    def fake_repository():
        repo = Repository(db_path=tmp_path / "test.db", raw_dir=tmp_path / "raw")
        captured["repository"] = repo
        return repo

    def fake_history_repository():
        hist = HistoryRepository(db_path=tmp_path / "history.db")
        captured["history_repository"] = hist
        return hist

    monkeypatch.setattr(run_e2e_module, "Repository", fake_repository)
    monkeypatch.setattr(run_e2e_module, "HistoryRepository", fake_history_repository)
    # Paso 0d, subfase de lock: sin esto, main() tomaría el LOCK_PATH real
    # (data/.run_e2e.lock) -- se redirige a tmp_path por la misma razón que
    # Repository/HistoryRepository de arriba, para no tocar `data/` real.
    monkeypatch.setattr(run_e2e_module, "LOCK_PATH", tmp_path / "run_e2e.lock")
    monkeypatch.setattr(sys, "argv", ["run_e2e.py"])

    exit_code = run_e2e_module.main()

    assert exit_code == 0
    assert "history_repository" in captured  # main() sí construyó un HistoryRepository real

    hist = captured["history_repository"]
    repo = captured["repository"]

    conn = sqlite3.connect(hist.db_path)
    snapshot_count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]
    conn.close()

    normalized_count = len(repo.get_normalized_records())
    if normalized_count == 0:
        pytest.skip("no hubo eventos MLB/tenis disponibles vía las APIs en esta ejecución")

    # Un snapshot histórico por cada record efectivamente guardado en esta
    # corrida -- el mismo invariante verificado a nivel unitario en
    # test_pipeline_history_wiring.py, ahora confirmado a través del
    # entry point real, no solo de las funciones de pipeline directamente.
    assert snapshot_count == normalized_count
