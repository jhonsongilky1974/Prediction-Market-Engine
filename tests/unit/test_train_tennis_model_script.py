"""Tests de `scripts/train_tennis_model.py` (Fase 4, Paso 4.3). Mismo
patrón exacto que `test_train_mlb_model_script.py` (Fase 2, Paso 5b,
Bloque 5) -- `HistoryRepository` monkeypatcheada a `tmp_path`, nunca
toca `data/engine.db`; `--models-dir` explícito apuntando a `tmp_path`.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import scripts.train_tennis_model as train_script
from src.storage.history_repository import HistoryRepository
from tests.unit.tennis_preevent_factories import add_preevent_sample as _add_sample


def _patch_history_repository(monkeypatch, tmp_path, db_name="hist.db"):
    hist = HistoryRepository(db_path=tmp_path / db_name)
    monkeypatch.setattr(train_script, "HistoryRepository", lambda: hist)
    return hist


def test_script_reports_insufficient_history_honestly(monkeypatch, tmp_path):
    hist = _patch_history_repository(monkeypatch, tmp_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="PARTICIPANT_A_WON")
    models_dir = tmp_path / "models"
    monkeypatch.setattr(
        sys, "argv", ["train_tennis_model.py", "--min-samples", "30", "--models-dir", str(models_dir)]
    )

    exit_code = train_script.main()

    assert exit_code == 0
    assert not models_dir.exists() or not any(models_dir.iterdir())


def test_script_trains_and_reports_metrics_when_threshold_reached(monkeypatch, tmp_path, capsys):
    hist = _patch_history_repository(monkeypatch, tmp_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(160):  # política real: >=150 eventos y particiones >=30 (96/32/32)
        a_wins = i % 2 == 0
        _add_sample(
            hist, f"espn_tennis_atp_{i:03d}", t0 + timedelta(days=i),
            result="PARTICIPANT_A_WON" if a_wins else "PARTICIPANT_B_WON",
            rest_a=8.0 if a_wins else 1.0, rest_b=1.0 if a_wins else 8.0,
            round_context="Final" if a_wins else "Qualifying 1st Round",
        )
    models_dir = tmp_path / "models"
    monkeypatch.setattr(
        sys, "argv", ["train_tennis_model.py", "--models-dir", str(models_dir)]
    )

    exit_code = train_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "model_status: TRAINED" in captured.out
    assert "model_version: tennis_baseline_logreg_v1_" in captured.out
    assert "precision (validation):" in captured.out
    assert "ece (validation, modelo SIN calibrar):" in captured.out
    assert "calibration_version: None" in captured.out
    assert "artifact_sha256:" in captured.out
    assert "candidate_status: PROMOTION_ELIGIBLE" in captured.out  # elegible NO es activo: requiere registro explícito

    # Regresión: el artefacto debe quedar en `models_dir` (tmp_path) --
    # nunca en DATA_MODELS_DIR de producción.
    written_files = list(models_dir.glob("tennis_baseline_logreg_v1_*"))
    assert len(written_files) == 2  # .joblib + .metadata.json
