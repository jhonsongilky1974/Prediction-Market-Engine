"""Tests del registro de artefactos de modelo (Paso 5a). Ver
src/models/registry.py -- `model_version -> artefacto entrenado (o ausente)`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models.mlb_baseline import train_mlb_baseline_model
from src.models.registry import load_latest_mlb_artifact
from src.storage.history_repository import HistoryRepository
from tests.unit.test_mlb_baseline import _add_sample


def test_load_latest_mlb_artifact_returns_none_when_dir_missing(tmp_path):
    assert load_latest_mlb_artifact(models_dir=tmp_path / "does_not_exist") is None


def test_load_latest_mlb_artifact_returns_none_when_empty(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    assert load_latest_mlb_artifact(models_dir=models_dir) is None


def _train_tiny_model(hist_db_path, models_dir, now):
    hist = HistoryRepository(db_path=hist_db_path)
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _add_sample(hist, f"mlb_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON", era_a=2.5, era_b=5.0)
    for i in range(5):
        _add_sample(hist, f"mlb_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", era_a=5.0, era_b=2.5)
    return train_mlb_baseline_model(hist, models_dir=models_dir, min_samples=10, now=now)


def test_save_and_load_artifact_roundtrip(tmp_path):
    models_dir = tmp_path / "models"
    status, artifact, _ = _train_tiny_model(
        tmp_path / "hist.db", models_dir, now=datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
    )

    loaded = load_latest_mlb_artifact(models_dir=models_dir)

    assert loaded is not None
    model, loaded_artifact = loaded
    assert loaded_artifact.model_version == artifact.model_version
    assert loaded_artifact.feature_set_version == artifact.feature_set_version
    assert loaded_artifact.n_training_samples == artifact.n_training_samples
    assert loaded_artifact.feature_columns == artifact.feature_columns
    assert hasattr(model, "predict_proba")


def test_load_latest_returns_most_recent_when_multiple(tmp_path):
    models_dir = tmp_path / "models"
    _, older, _ = _train_tiny_model(
        tmp_path / "hist1.db", models_dir, now=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    )
    _, newer, _ = _train_tiny_model(
        tmp_path / "hist2.db", models_dir, now=datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
    )
    assert older.model_version != newer.model_version

    loaded = load_latest_mlb_artifact(models_dir=models_dir)

    assert loaded is not None
    _, loaded_artifact = loaded
    assert loaded_artifact.model_version == newer.model_version
