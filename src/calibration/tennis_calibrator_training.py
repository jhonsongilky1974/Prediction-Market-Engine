"""Entrenamiento + persistencia del calibrador Platt de tenis (Fase 4,
calibración real -- ver `CALIBRATION_SPEC.md`).

Persistencia INDEPENDIENTE, mismo patrón que
`src/models/tennis_baseline.py` (joblib + `.metadata.json` hermano,
distinguido por prefijo `tennis_calibrator_platt_v1_*` -- convive sin
colisión con `tennis_baseline_*` en el mismo `DATA_MODELS_DIR`).

Reutiliza literalmente `predict_tennis_baseline_from_features` (ya
existente, documentado para exactamente este uso: "inferencia
histórica/backtesting... sin duplicar lógica") para producir `p_raw`
sobre la validación -- cero reimplementación de la vectorización interna
de `tennis_baseline.py`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.backtesting.metrics import brier_score, ece as compute_ece
from src.calibration.platt_calibrator import PlattCalibrator, fit_platt_calibrator
from src.models.base import ModelStatus
from src.models.tennis_baseline import (
    build_tennis_training_dataset,
    load_latest_tennis_artifact,
    predict_tennis_baseline_from_features,
    split_dataset_temporally,
)
from src.storage.history_repository import HistoryRepository

# Estándar de la librería (sklearn usa cv=5 por defecto en sus propias
# funciones de validación cruzada) -- no un número elegido a medida,
# CALIBRATION_SPEC.md §2.
DEFAULT_CV_FOLDS = 5


@dataclass
class TennisCalibratorArtifact:
    calibrator_version: str
    calibration_method: str
    base_model_version: str
    trained_at: datetime
    n_calibration_samples: int
    n_calibration_events: int
    cv_folds: int
    file_path: Path
    raw_ece: Optional[float] = None
    raw_brier: Optional[float] = None
    calibrated_ece_oof: Optional[float] = None
    calibrated_brier_oof: Optional[float] = None
    artifact_sha256: str = ""


def _tennis_calibrator_metadata_path(models_dir: Path, calibrator_version: str) -> Path:
    return models_dir / f"{calibrator_version}.metadata.json"


def _save_tennis_calibrator_metadata(artifact: TennisCalibratorArtifact, models_dir: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "calibrator_version": artifact.calibrator_version,
        "calibration_method": artifact.calibration_method,
        "base_model_version": artifact.base_model_version,
        "trained_at": artifact.trained_at.isoformat(),
        "n_calibration_samples": artifact.n_calibration_samples,
        "n_calibration_events": artifact.n_calibration_events,
        "cv_folds": artifact.cv_folds,
        "file_path": str(artifact.file_path),
        "raw_ece": artifact.raw_ece,
        "raw_brier": artifact.raw_brier,
        "calibrated_ece_oof": artifact.calibrated_ece_oof,
        "calibrated_brier_oof": artifact.calibrated_brier_oof,
        "artifact_sha256": artifact.artifact_sha256,
    }
    path = _tennis_calibrator_metadata_path(models_dir, artifact.calibrator_version)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


def _resolve_validation_samples(
    history_repository: HistoryRepository, artifact: Any, warnings: List[str]
) -> Tuple[Optional[list], List[str]]:
    """Devuelve las muestras de validación seguras para calibrar (nunca
    vistas por el entrenamiento del modelo base), o `None` si no se
    pueden verificar como tales. `CALIBRATION_SPEC.md` §0.4/§4.4: usa
    `validation_event_ids` persistido si existe (reconstrucción exacta,
    a prueba de crecimiento futuro de la base de datos); si no existe
    (el artefacto ya entrenado hoy no lo tiene), recomputa el split y
    exige que los conteos coincidan exactamente con el `metadata.json`
    del modelo base antes de confiar en él."""
    dataset = build_tennis_training_dataset(history_repository)
    validation_event_ids = getattr(artifact, "validation_event_ids", None) or []

    if validation_event_ids:
        validation_samples = [s for s in dataset.samples if s.event_id in set(validation_event_ids)]
        warnings.append(
            "validación reconstruida desde validation_event_ids persistido en el artefacto "
            "(reconstrucción exacta, no depende de recomputar el split)."
        )
        return validation_samples, warnings

    train_dataset, validation_dataset = split_dataset_temporally(dataset)
    recomputed_train_events = len({s.event_id for s in train_dataset.samples})
    recomputed_validation_events = len({s.event_id for s in validation_dataset.samples})

    if (
        train_dataset.size != artifact.n_train_samples
        or validation_dataset.size != artifact.n_validation_samples
        or recomputed_train_events != artifact.n_train_events
        or recomputed_validation_events != artifact.n_validation_events
    ):
        warnings.append(
            "el artefacto base no tiene validation_event_ids persistido y recomputar el split "
            f"hoy da train={train_dataset.size}/{recomputed_train_events}ev, "
            f"validation={validation_dataset.size}/{recomputed_validation_events}ev, que NO coincide "
            f"con el metadata.json del modelo base (train={artifact.n_train_samples}/{artifact.n_train_events}ev, "
            f"validation={artifact.n_validation_samples}/{artifact.n_validation_events}ev) -- no se puede "
            "garantizar que la validación esté libre de fuga respecto al entrenamiento del modelo base. "
            "Calibración abortada, nada se fabrica."
        )
        return None, warnings

    warnings.append(
        "el artefacto base no tiene validation_event_ids persistido -- se recomputó el split y los "
        "conteos coinciden exactamente con el metadata.json del modelo base (evidencia de que no hay "
        "fuga, CALIBRATION_SPEC.md §0.4), pero no es una garantía matemática."
    )
    return validation_dataset.samples, warnings


def train_tennis_calibrator(
    history_repository: HistoryRepository,
    models_dir: Path = DATA_MODELS_DIR,
    cv_folds: int = DEFAULT_CV_FOLDS,
    now: Optional[datetime] = None,
) -> Tuple[ModelStatus, Optional[TennisCalibratorArtifact], List[str]]:
    """Ajusta y persiste un `PlattCalibrator` real contra el modelo base
    de tenis más reciente. Nunca fabrica un calibrador: si no hay modelo
    base, si la validación no se puede verificar como libre de fuga, o si
    no hay suficientes eventos/clases para `GroupKFold`, devuelve
    `INSUFFICIENT_HISTORY`/`MODEL_NOT_TRAINED` honestamente."""
    warnings: List[str] = []

    loaded = load_latest_tennis_artifact(models_dir=models_dir)
    if loaded is None:
        return ModelStatus.MODEL_NOT_TRAINED, None, [
            "no hay ningún modelo base de tenis entrenado -- nada que calibrar."
        ]
    model, base_artifact = loaded

    validation_samples, warnings = _resolve_validation_samples(history_repository, base_artifact, warnings)
    if validation_samples is None:
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    n_events = len({s.event_id for s in validation_samples})
    if n_events < cv_folds:
        warnings.append(
            f"validación con {n_events} evento(s) distinto(s), por debajo de cv_folds={cv_folds} -- "
            "no se puede hacer GroupKFold, calibración abortada."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    y = [s.label for s in validation_samples]
    if len(set(y)) < 2:
        warnings.append("la validación tiene una sola clase de resultado -- no se puede ajustar Platt scaling.")
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    p_raw = [
        predict_tennis_baseline_from_features(s.features, loaded) for s in validation_samples
    ]

    import numpy as np
    from sklearn.model_selection import GroupKFold

    p_raw_arr = np.array(p_raw, dtype=float)
    y_arr = np.array(y, dtype=int)
    event_ids_arr = np.array([s.event_id for s in validation_samples])

    oof = np.full(len(p_raw_arr), np.nan)
    gkf = GroupKFold(n_splits=cv_folds)
    for train_idx, test_idx in gkf.split(p_raw_arr.reshape(-1, 1), y_arr, groups=event_ids_arr):
        fold_calibrator = fit_platt_calibrator(
            p_raw_arr[train_idx], y_arr[train_idx], calibration_version="_oof_fold"
        )
        for i in test_idx:
            oof[i] = fold_calibrator.calibrate(float(p_raw_arr[i]))

    calibrated_ece_oof = compute_ece(list(y_arr), list(oof))
    calibrated_brier_oof = brier_score(list(y_arr), list(oof))

    now = now or datetime.now(timezone.utc)
    calibrator_version = f"tennis_calibrator_platt_v1_{now:%Y%m%dT%H%M%SZ}"
    final_calibrator = fit_platt_calibrator(p_raw_arr, y_arr, calibration_version=calibrator_version)

    import joblib

    models_dir.mkdir(parents=True, exist_ok=True)
    file_path = models_dir / f"{calibrator_version}.joblib"
    joblib.dump(final_calibrator, file_path)

    import hashlib

    artifact_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

    artifact = TennisCalibratorArtifact(
        calibrator_version=calibrator_version,
        calibration_method="PLATT_V1",
        base_model_version=base_artifact.model_version,
        trained_at=now,
        n_calibration_samples=len(validation_samples),
        n_calibration_events=n_events,
        cv_folds=cv_folds,
        file_path=file_path,
        raw_ece=base_artifact.ece,
        raw_brier=base_artifact.brier_score,
        calibrated_ece_oof=calibrated_ece_oof,
        calibrated_brier_oof=calibrated_brier_oof,
        artifact_sha256=artifact_sha256,
    )
    _save_tennis_calibrator_metadata(artifact, models_dir)

    return ModelStatus.TRAINED, artifact, warnings


def load_latest_tennis_calibrator(
    base_model_version: str, models_dir: Path = DATA_MODELS_DIR
) -> Optional[PlattCalibrator]:
    """Devuelve el calibrador de tenis más reciente CUYO `base_model_version`
    coincida exactamente con `base_model_version` -- nunca aplica un
    calibrador ajustado contra otra versión del modelo base
    (`CALIBRATION_SPEC.md` §4.1). `None` si no existe ninguno."""
    if not models_dir.exists():
        return None

    latest_data: Optional[dict] = None
    latest_trained_at: Optional[datetime] = None
    for meta_path in sorted(models_dir.glob("tennis_calibrator_platt_v1_*.metadata.json")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if data.get("base_model_version") != base_model_version:
            continue
        trained_at = datetime.fromisoformat(data["trained_at"])
        if latest_trained_at is None or trained_at > latest_trained_at:
            latest_trained_at = trained_at
            latest_data = data

    if latest_data is None:
        return None

    import joblib

    calibrator = joblib.load(latest_data["file_path"])
    return calibrator
