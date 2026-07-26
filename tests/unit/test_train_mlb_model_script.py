"""Tests de `scripts/train_mlb_model.py` (Paso 5b, Bloque 5). Sin red:
`HistoryRepository` se monkeypatchea a una instancia `tmp_path` -- nunca
toca `data/engine.db`.
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
    monkeypatch.setattr(sys, "argv", ["train_mlb_model.py", "--min-samples", "300"])

    exit_code = train_script.main()

    assert exit_code == 0


def test_script_trains_and_reports_metrics_when_threshold_reached(monkeypatch, tmp_path, capsys):
    hist = _patch_history_repository(monkeypatch, tmp_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"mlb_{i}", t0 + timedelta(minutes=i), result=result)
    monkeypatch.setattr(sys, "argv", ["train_mlb_model.py", "--min-samples", "10"])

    exit_code = train_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "model_status: TRAINED" in captured.out
    assert "model_version: mlb_baseline_logreg_v1_" in captured.out
    assert "accuracy (validation):" in captured.out
