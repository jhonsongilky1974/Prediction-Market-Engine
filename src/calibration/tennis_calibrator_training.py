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

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.backtesting.metrics import brier_score, ece as compute_ece
from src.calibration.platt_calibrator import PlattCalibrator, fit_platt_calibrator
from src.models.base import ModelStatus
from src.models.model_registry_policy import (
    ModelRegistryPolicy,
    load_model_registry,
    read_bytes_once,
    resolve_declared_path,
    resolve_in_dir,
    sha256_hex,
)
from src.models.tennis_baseline import (
    CANDIDATE_REJECTED,
    TRAINING_DATASET_SPEC_VERSION,
    build_tennis_training_dataset,
    load_latest_tennis_artifact,
    predict_tennis_baseline_from_features,
    split_dataset_temporally,
)
from src.storage.history_repository import HistoryRepository

logger = logging.getLogger(__name__)

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
    registry: Optional[ModelRegistryPolicy] = None,
) -> Tuple[ModelStatus, Optional[TennisCalibratorArtifact], List[str]]:
    """Ajusta y persiste un `PlattCalibrator` real contra el modelo base
    de tenis más reciente. Nunca fabrica un calibrador: si no hay modelo
    base, si la validación no se puede verificar como libre de fuga, o si
    no hay suficientes eventos/clases para `GroupKFold`, devuelve
    `INSUFFICIENT_HISTORY`/`MODEL_NOT_TRAINED` honestamente."""
    warnings: List[str] = []

    loaded = load_latest_tennis_artifact(models_dir=models_dir, registry=registry)
    if loaded is None:
        return ModelStatus.MODEL_NOT_TRAINED, None, [
            "no hay ningún modelo base de tenis ACTIVABLE (entrenado y permitido en config/model_registry.json) "
            "-- nada que calibrar."
        ]
    model, base_artifact = loaded

    # CONTINUITY.md §0.38: nunca se calibra un modelo base entrenado sin la
    # spec pre-evento v2 (el modelo original con fuga temporal quedó
    # INVALID; su validación contaminada no sirve para calibrar).
    if getattr(base_artifact, "training_dataset_spec_version", None) != TRAINING_DATASET_SPEC_VERSION:
        return ModelStatus.MODEL_NOT_TRAINED, None, [
            f"el modelo base {base_artifact.model_version!r} no fue entrenado con la spec "
            f"{TRAINING_DATASET_SPEC_VERSION!r} (dataset pre-evento, un snapshot por evento) -- "
            "calibración rechazada, nada se fabrica."
        ]

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


_CALIBRATOR_REQUIRED_METADATA_KEYS = (
    "calibrator_version", "base_model_version", "trained_at", "artifact_sha256", "file_path"
)


def _resolve_tennis_calibrator(
    base_model_version: str, models_dir: Path, policy: ModelRegistryPolicy
) -> Tuple[Optional[PlattCalibrator], str]:
    """`(calibrador | None, motivo)`. FAIL-CLOSED (CONTINUITY.md §0.38): ante
    cualquier duda sobre el artefacto seleccionado no se carga ningún
    calibrador, y NUNCA hay fallback hacia otro (ni más antiguo, ni no
    registrado). Los candidatos salen EXCLUSIVAMENTE del registro: ningún
    archivo no registrado, antiguo o ajeno del directorio se lee ni puede
    bloquear a un candidato válido. Se exige, en orden:
    1. modelo base `ALLOWED` en el registro con SHA-256 verificado sobre los
       bytes leídos (y metadata legible, coherente y no `REJECTED_CANDIDATE`);
    2. un calibrador `ALLOWED` en el registro atado a ese modelo base
       (`base_model_version` de la entrada); si hay varios, el de mayor
       `calibrator_version` (el nombre lleva el timestamp de entrenamiento);
    3. el metadato del calibrador coincide con la entrada: SHA-256 igual a
       `metadata_sha256`, y `calibrator_version`, `base_model_version`
       (== modelo base solicitado == entrada) y `artifact_sha256` coherentes;
    4. el `.joblib` del calibrador tiene el SHA-256 de la entrada.
    Cada archivo se lee UNA sola vez y se verifica/deserializa el MISMO
    contenido en memoria (sin ventana TOCTOU). Los artefactos se localizan
    por `metadata.file_path` (contrato previo) validado con
    `resolve_declared_path`: solo archivos regulares DENTRO de `models_dir`
    (sin traversal ni symlinks). Los metadatos se localizan por el nombre
    `<versión>.metadata.json`, con la versión tomada del registro."""
    # 1. modelo base
    base_meta_path = resolve_in_dir(models_dir, f"{base_model_version}.metadata.json")
    if base_meta_path is None:
        return None, f"nombre de modelo base no seguro: {base_model_version!r}"
    base_meta_bytes = read_bytes_once(base_meta_path)
    if base_meta_bytes is None:
        return None, f"metadata del modelo base {base_model_version!r} ausente o ilegible"
    try:
        base_meta = json.loads(base_meta_bytes.decode("utf-8"))
        base_declared_version = base_meta["model_version"]
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"metadata del modelo base {base_model_version!r} ausente o ilegible ({exc!r})"
    if base_declared_version != base_model_version:
        return None, f"metadata del modelo base inconsistente: declara {base_declared_version!r}"
    base_file_path = resolve_declared_path(models_dir, base_meta.get("file_path"))
    if base_file_path is None:
        return None, (
            f"file_path del modelo base {base_model_version!r} no válido, ausente o fuera de {models_dir}: "
            f"{base_meta.get('file_path')!r}"
        )
    activable, reason = policy.check_bytes(base_model_version, read_bytes_once(base_file_path))
    if not activable:
        return None, f"modelo base {base_model_version!r} no activable: {reason}"
    if base_meta.get("candidate_status") == CANDIDATE_REJECTED:
        return None, f"modelo base {base_model_version!r} es {CANDIDATE_REJECTED}"

    # 2. candidato: solo entradas del registro
    candidates = policy.allowed_calibrators_for_base(base_model_version)
    if not candidates:
        return None, f"el registro no declara ningún calibrador ALLOWED atado al modelo base {base_model_version!r}"
    entry = max(candidates, key=lambda e: e.model_version)
    calibrator_version = entry.model_version
    if not entry.metadata_sha256:
        return None, f"entrada del calibrador {calibrator_version!r} sin metadata_sha256 -- integridad del metadato no verificable"

    # 3. metadato (leído una vez; el hash se calcula sobre esos bytes y se parsean esos mismos bytes)
    meta_path = resolve_in_dir(models_dir, f"{calibrator_version}.metadata.json")
    if meta_path is None:
        return None, f"nombre de calibrador no seguro en el registro: {calibrator_version!r}"
    meta_bytes = read_bytes_once(meta_path)
    if meta_bytes is None:
        return None, f"metadato del calibrador {calibrator_version!r} ausente o ilegible"
    if sha256_hex(meta_bytes) != entry.metadata_sha256:
        return None, f"SHA-256 del metadato del calibrador {calibrator_version!r} no coincide con el registro (metadato alterado)"
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
        missing = [k for k in _CALIBRATOR_REQUIRED_METADATA_KEYS if not meta.get(k)]
        if missing:
            return None, f"metadato del calibrador {calibrator_version!r} incompleto (faltan {missing})"
        datetime.fromisoformat(meta["trained_at"])
    except (ValueError, TypeError, AttributeError) as exc:
        return None, f"metadato del calibrador {calibrator_version!r} ilegible ({exc!r})"
    if meta["calibrator_version"] != calibrator_version:
        return None, f"metadato inconsistente: declara calibrator_version={meta['calibrator_version']!r}"
    if not (meta["base_model_version"] == entry.base_model_version == base_model_version):
        return None, (
            f"vínculo calibrador-modelo inconsistente: metadato={meta['base_model_version']!r}, "
            f"registro={entry.base_model_version!r}, solicitado={base_model_version!r}"
        )

    # 4. artefacto del calibrador, localizado por `file_path` del metadato (ya autenticado por
    # `metadata_sha256`) y validado dentro de `models_dir`; una sola lectura, se verifica y se
    # deserializa ese mismo contenido
    file_path = resolve_declared_path(models_dir, meta["file_path"])
    if file_path is None:
        return None, (
            f"file_path del calibrador {calibrator_version!r} no válido, ausente o fuera de {models_dir}: "
            f"{meta['file_path']!r}"
        )
    payload = read_bytes_once(file_path)
    if payload is None:
        return None, f"archivo del calibrador {calibrator_version!r} ausente o ilegible"
    activable, reason = policy.check_bytes(calibrator_version, payload)
    if not activable:
        return None, f"calibrador {calibrator_version!r} no activable: {reason}"
    if sha256_hex(payload) != meta["artifact_sha256"]:
        return None, f"artifact_sha256 del metadato del calibrador {calibrator_version!r} no coincide con el archivo"

    import joblib

    try:
        calibrator = joblib.load(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001 -- fail-closed: cualquier fallo de carga rechaza
        return None, f"el calibrador {calibrator_version!r} no pudo cargarse ({exc!r})"
    return calibrator, f"calibrador {calibrator_version!r} cargado (ALLOWED, SHA-256 verificado)"


def load_latest_tennis_calibrator(
    base_model_version: str,
    models_dir: Path = DATA_MODELS_DIR,
    registry: Optional[ModelRegistryPolicy] = None,
) -> Optional[PlattCalibrator]:
    """Devuelve el calibrador de tenis más reciente CUYO `base_model_version`
    coincida exactamente con `base_model_version` -- nunca aplica un
    calibrador ajustado contra otra versión del modelo base
    (`CALIBRATION_SPEC.md` §4.1) -- y SOLO si pasa la política fail-closed
    del registro de modelos (`config/model_registry.json`, `registry=None`
    -> lo carga): modelo base y calibrador `ALLOWED` con SHA-256 verificado,
    la entrada del calibrador atada al modelo base (`base_model_version`) y
    con `metadata_sha256` que protege la integridad de su metadato. En
    cualquier otro caso devuelve `None` y registra el motivo en el log
    (nunca lanza, nunca hace fallback hacia otro calibrador). Es la función que debe usar
    `SportAdapter.load_calibrator_fn` (se invoca con `model_version` como
    único argumento): cableada así, el pipeline nunca aplica un calibrador
    no verificado."""
    if not models_dir.exists():
        logger.warning("calibrador de tenis RECHAZADO para %s: el directorio de modelos no existe", base_model_version)
        return None
    policy = registry if registry is not None else load_model_registry()
    try:
        calibrator, reason = _resolve_tennis_calibrator(base_model_version, models_dir, policy)
    except Exception as exc:  # noqa: BLE001 -- fail-closed ante cualquier error inesperado
        logger.error("calibrador de tenis RECHAZADO para %s: error inesperado %r", base_model_version, exc)
        return None
    if calibrator is None:
        logger.warning("calibrador de tenis RECHAZADO para %s: %s", base_model_version, reason)
    else:
        logger.info("calibrador de tenis para %s: %s", base_model_version, reason)
    return calibrator
