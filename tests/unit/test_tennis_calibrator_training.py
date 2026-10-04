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
from src.models.base import ModelStatus
from src.models.tennis_baseline import (
    TRAINING_DATASET_SPEC_VERSION,
    load_latest_tennis_artifact,
    train_tennis_baseline_model,
)
from src.storage.history_repository import HistoryRepository
from tests.unit.tennis_preevent_factories import add_preevent_sample, promote_artifacts_for_test

# Mínimos relajados SOLO para probar la mecánica con pocos eventos: el
# modelo base resultante es REJECTED_CANDIDATE por política y solo se carga
# vía un registro en memoria que lo promueve (`promote_artifacts_for_test`).
BASE_KWARGS = dict(min_samples=10, min_partition_events=3)


def _populate_separable_dataset(hist, n=40, t0=None):
    """`n` eventos INTERCALADOS cronológicamente entre las dos clases
    (pre-evento, un snapshot por evento): la cola de validación debe tener
    AMBAS clases, requisito real de `train_tennis_calibrator`
    (GroupKFold necesita >=2 clases)."""
    t0 = t0 or datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(n):
        if i % 2 == 0:
            add_preevent_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(days=i), "PARTICIPANT_A_WON", rest_a=8.0, rest_b=1.0)
        else:
            add_preevent_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(days=i), "PARTICIPANT_B_WON", rest_a=1.0, rest_b=8.0)


def _train_base(hist, models_dir, **kwargs):
    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir, **{**BASE_KWARGS, **kwargs})
    registry = promote_artifacts_for_test(models_dir) if status == ModelStatus.TRAINED else None
    return status, artifact, warnings, registry


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

    base_status, base_artifact, _, registry = _train_base(hist, models_dir)
    assert base_status == ModelStatus.TRAINED

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=registry)

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

    base_status, base_artifact, _, registry = _train_base(hist, models_dir)
    assert base_status == ModelStatus.TRAINED
    train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=registry)

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
    base_status, _, _, registry = _train_base(hist, models_dir, min_partition_events=2)
    assert base_status == ModelStatus.TRAINED

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=registry)

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

    base_status, base_artifact, _, registry = _train_base(hist, models_dir)
    assert base_status == ModelStatus.TRAINED
    assert len(base_artifact.validation_event_ids) == base_artifact.n_validation_events

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=registry)
    assert status == ModelStatus.TRAINED
    assert any("validation_event_ids persistido" in w for w in warnings)


def test_calibrator_refuses_base_model_not_allowed_by_registry(tmp_path):
    """Fail-closed: sin entrada ALLOWED en el registro, el calibrador no
    entrena sobre ningún modelo base (el registro por defecto del repo
    tampoco lista modelos nuevos)."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    _populate_separable_dataset(hist, n=40)
    base_status, _, _, _ = _train_base(hist, models_dir)  # entrenado pero NO promovido
    assert base_status == ModelStatus.TRAINED

    status, artifact, _ = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5)

    assert status == ModelStatus.MODEL_NOT_TRAINED
    assert artifact is None


def test_calibrator_refuses_base_model_with_legacy_dataset_spec(tmp_path):
    import json

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    _populate_separable_dataset(hist, n=40)
    base_status, base_artifact, _, _ = _train_base(hist, models_dir)
    assert base_status == ModelStatus.TRAINED
    meta_path = models_dir / f"{base_artifact.model_version}.metadata.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["training_dataset_spec_version"] = "legacy_v1"
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    registry = promote_artifacts_for_test(models_dir)  # ALLOWED, con SHA real

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=registry)

    assert status == ModelStatus.MODEL_NOT_TRAINED
    assert artifact is None
    assert any(TRAINING_DATASET_SPEC_VERSION in w for w in warnings)
