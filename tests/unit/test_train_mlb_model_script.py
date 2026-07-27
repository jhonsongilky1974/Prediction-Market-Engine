"""Tests de `scripts/train_mlb_model.py` (Paso 5b, Bloque 5). Sin red:
`HistoryRepository` se monkeypatchea a una instancia `tmp_path` -- nunca
toca `data/engine.db`. `--models-dir` se pasa explícitamente apuntando a
`tmp_path` en todo test que efectivamente entrena (hallazgo de la
Validación Institucional de Fase 2: sin este aislamiento, cada corrida
de este archivo escribía un artefacto sintético real en `data/models/`
de producción, porque el script no exponía forma de redirigir ese
directorio). Aislamiento de test únicamente -- ninguna lógica de
`train_mlb_baseline_model`/predicción cambia.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import scripts.train_mlb_model as train_script
from src.storage.history_repository import HistoryRepository
from tests.unit.test_mlb_baseline import _add_sample


def _patch_history_repository(monkeypatch, tmp_path, db_name="hist.db"):
    hist = HistoryRepository(db_path=tmp_path / db_name)
    monkeypatch.setattr(train_script, "HistoryRepository", lambda: hist)
    return hist


def test_script_reports_insufficient_history_honestly(monkeypatch, tmp_path):
    hist = _patch_history_repository(monkeypatch, tmp_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result="PARTICIPANT_A_WON")
    models_dir = tmp_path / "models"
    monkeypatch.setattr(
        sys, "argv", ["train_mlb_model.py", "--min-samples", "300", "--models-dir", str(models_dir)]
    )

    exit_code = train_script.main()

    assert exit_code == 0
    assert not models_dir.exists() or not any(models_dir.iterdir())


def test_script_trains_and_reports_metrics_when_threshold_reached(monkeypatch, tmp_path, capsys):
    hist = _patch_history_repository(monkeypatch, tmp_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"mlb_{i}", t0 + timedelta(minutes=i), result=result)
    models_dir = tmp_path / "models"
    monkeypatch.setattr(
        sys, "argv", ["train_mlb_model.py", "--min-samples", "10", "--models-dir", str(models_dir)]
    )

    exit_code = train_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "model_status: TRAINED" in captured.out
    assert "model_version: mlb_baseline_logreg_v1_" in captured.out
    assert "accuracy (validation):" in captured.out

    # Regresión: el artefacto debe quedar en `models_dir` (tmp_path) --
    # nunca en DATA_MODELS_DIR de producción, aunque el script no lo
    # reciba explícitamente (hallazgo de la Validación Institucional).
    written_files = list(models_dir.glob("mlb_baseline_logreg_v1_*"))
    assert len(written_files) == 2  # .joblib + .metadata.json
