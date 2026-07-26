"""Registro de artefactos de modelo entrenado (Paso 5a). Ver
PLAN_PHASE2.md §3: `model_version -> artefacto entrenado (o ausente)`.

Cada artefacto se guarda como dos archivos hermanos en `DATA_MODELS_DIR`:
  - `{model_version}.joblib`          el pipeline de scikit-learn serializado
  - `{model_version}.metadata.json`   metadata legible (sin necesitar joblib
                                        para inspeccionar qué existe)

No hay ningún artefacto todavía es un estado válido y esperado (Paso 5a
cierra honestamente con `model_status=MODEL_NOT_TRAINED`/
`INSUFFICIENT_HISTORY` mientras no haya histórico suficiente).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.models.mlb_baseline import MlbTrainedArtifact


def _metadata_path(models_dir: Path, model_version: str) -> Path:
    return models_dir / f"{model_version}.metadata.json"


def save_artifact_metadata(artifact: MlbTrainedArtifact, models_dir: Path = DATA_MODELS_DIR) -> Path:
    """Persiste la metadata del artefacto YA serializado por
    `train_mlb_baseline_model` (que ya escribió el `.joblib`). Separado en
    su propia función para que el registro (leer/listar modelos) no
    necesite saber nada de cómo se entrenó ni de scikit-learn."""
    models_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_version": artifact.model_version,
        "sport": artifact.sport,
        "algorithm": artifact.algorithm,
        "trained_at": artifact.trained_at.isoformat(),
        "feature_set_version": artifact.feature_set_version,
        "n_training_samples": artifact.n_training_samples,
        "feature_columns": artifact.feature_columns,
        "file_path": str(artifact.file_path),
        "n_train_samples": artifact.n_train_samples,
        "n_validation_samples": artifact.n_validation_samples,
        "validation_fraction": artifact.validation_fraction,
        "accuracy": artifact.accuracy,
        "log_loss": artifact.log_loss,
        "brier_score": artifact.brier_score,
    }
    path = _metadata_path(models_dir, artifact.model_version)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


def load_latest_mlb_artifact(models_dir: Path = DATA_MODELS_DIR) -> Optional[Tuple[Any, MlbTrainedArtifact]]:
    """Devuelve `(pipeline_sklearn_cargado, MlbTrainedArtifact)` del
    artefacto MLB más reciente por `trained_at`, o `None` si no hay
    ninguno todavía -- estado perfectamente válido
    (`model_status=MODEL_NOT_TRAINED` en inferencia). Nunca lanza si el
    directorio no existe o está vacío."""
    if not models_dir.exists():
        return None

    latest_data: Optional[dict] = None
    latest_trained_at: Optional[datetime] = None
    for meta_path in sorted(models_dir.glob("mlb_baseline_*.metadata.json")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        trained_at = datetime.fromisoformat(data["trained_at"])
        if latest_trained_at is None or trained_at > latest_trained_at:
            latest_trained_at = trained_at
            latest_data = data

    if latest_data is None:
        return None

    import joblib

    model = joblib.load(latest_data["file_path"])
    artifact = MlbTrainedArtifact(
        model_version=latest_data["model_version"],
        sport=latest_data["sport"],
        algorithm=latest_data["algorithm"],
        trained_at=latest_trained_at,
        feature_set_version=latest_data["feature_set_version"],
        n_training_samples=latest_data["n_training_samples"],
        feature_columns=latest_data["feature_columns"],
        file_path=Path(latest_data["file_path"]),
        # .get(...) con default: metadata de artefactos guardados ANTES del
        # Bloque 4 (Paso 5b) no tiene estos campos -- se cargan igual, sin
        # fabricar valores, simplemente ausentes (0/None).
        n_train_samples=latest_data.get("n_train_samples", 0),
        n_validation_samples=latest_data.get("n_validation_samples", 0),
        validation_fraction=latest_data.get("validation_fraction", 0.0),
        accuracy=latest_data.get("accuracy"),
        log_loss=latest_data.get("log_loss"),
        brier_score=latest_data.get("brier_score"),
    )
    return model, artifact
