"""Tests de `train_tennis_calibrator`/`load_latest_tennis_calibrator`
(calibración real, ver `CALIBRATION_SPEC.md`). Mismo patrón de fixtures
que `tests/unit/test_tennis_baseline.py` (`HistoryRepository(tmp_path)`,
`_add_sample`)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.calibration.tennis_calibrator_training import (
    TennisCalibratorArtifact,
    load_latest_tennis_calibrator,
    train_tennis_calibrator,
)
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.base import ModelStatus
from src.models.schemas import NormalizedRecord, Sport
from src.models.tennis_baseline import load_latest_tennis_artifact, train_tennis_baseline_model
from src.storage.history_repository import HistoryRepository


def _record(event_id):
    return NormalizedRecord(sport=Sport.TENNIS, event_id=event_id, participant_a="Player A", participant_b="Player B")


def _synthetic_features(rest_a=5.0, rest_b=3.0, round_context="Qualifying 1st Round"):
    return {
        "rest_days": {"participant_a": rest_a, "participant_b": rest_b},
        "tournament_round_context": round_context,
    }


def _add_sample(hist, event_id, computed_at, result, recorded_at=None, rest_a=5.0, rest_b=3.0):
    snap_id = hist.save_event_snapshot(_record(event_id), source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=computed_at,
        features=_synthetic_features(rest_a, rest_b),
        computed_at=computed_at,
    )
    hist.save_event_result(
        event_id=event_id, sport="TENNIS", result=result, source="test", recorded_at=recorded_at or (computed_at + timedelta(hours=3))
    )


def _populate_separable_dataset(hist, n=40, t0=None):
    """`n` eventos INTERCALADOS cronológicamente entre las dos clases --
    a diferencia de `test_tennis_baseline.py` (que agrupa A antes de B),
    aquí se necesita que la cola de validación (el 20% más reciente)
    tenga AMBAS clases, requisito real de `train_tennis_calibrator`
    (GroupKFold necesita >=2 clases)."""
    t0 = t0 or datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(n):
        if i % 2 == 0:
            _add_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(minutes=i), "PARTICIPANT_A_WON", rest_a=8.0, rest_b=1.0)
        else:
            _add_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(minutes=i), "PARTICIPANT_B_WON", rest_a=1.0, rest_b=8.0)


def test_no_base_model_returns_model_not_trained(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir)

    assert status == ModelStatus.MODEL_NOT_TRAINED
    assert artifact is None
    assert any("nada que calibrar" in w for w in warnings)


def test_trains_platt_calibrator_against_real_base_model(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    _populate_separable_dataset(hist, n=40)

    base_status, base_artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir)
    assert base_status == ModelStatus.TRAINED

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5)

    assert status == ModelStatus.TRAINED
    assert isinstance(artifact, TennisCalibratorArtifact)
    assert artifact.base_model_version == base_artifact.model_version
    assert artifact.calibration_method == "PLATT_V1"
    assert artifact.n_calibration_events == base_artifact.n_validation_events
    assert artifact.n_calibration_samples == base_artifact.n_validation_samples
    assert artifact.raw_ece == base_artifact.ece
    assert artifact.raw_brier == base_artifact.brier_score
    assert artifact.calibrated_ece_oof is not None
    assert artifact.calibrated_brier_oof is not None
    assert artifact.artifact_sha256 != ""
    assert artifact.file_path.exists()


def test_load_latest_tennis_calibrator_matches_exact_base_model_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    _populate_separable_dataset(hist, n=40)

    base_status, base_artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir)
    assert base_status == ModelStatus.TRAINED
    train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5)

    calibrator = load_latest_tennis_calibrator(base_artifact.model_version, models_dir=models_dir)
    assert calibrator is not None
    assert calibrator.calibration_method == "PLATT_V1"

    mismatched = load_latest_tennis_calibrator("some_other_model_version_never_trained", models_dir=models_dir)
    assert mismatched is None


def test_load_latest_tennis_calibrator_returns_none_when_directory_empty(tmp_path):
    models_dir = tmp_path / "models"
    assert load_latest_tennis_calibrator("any_version", models_dir=models_dir) is None


def test_insufficient_validation_events_for_cv_folds_returns_insufficient_history(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    # Suficientes muestras para entrenar el modelo base (min_samples=10),
    # pero muy pocas para que la validación (20%) alcance cv_folds=5
    # eventos distintos.
    _populate_separable_dataset(hist, n=12)
    base_status, _, _ = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)
    assert base_status == ModelStatus.TRAINED

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5)

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("GroupKFold" in w or "evento" in w for w in warnings)


def test_resolved_validation_uses_persisted_validation_event_ids_when_present(tmp_path):
    """`validation_event_ids` (Fase 4, `CALIBRATION_SPEC.md` §4.4) debe
    usarse tal cual cuando el artefacto lo tiene -- no debe recomputar
    `split_dataset_temporally` en ese caso."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    _populate_separable_dataset(hist, n=40)

    base_status, base_artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir)
    assert base_status == ModelStatus.TRAINED
    assert len(base_artifact.validation_event_ids) == base_artifact.n_validation_events

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5)
    assert status == ModelStatus.TRAINED
    assert any("validation_event_ids persistido" in w for w in warnings)
