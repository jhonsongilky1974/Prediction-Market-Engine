"""Infraestructura + modelo baseline de tenis (Paso 11). Ver
PLAN_PHASE2.md §6 y el Design Proposal explícitamente aprobado antes de
esta implementación.

Mismo patrón estructural que `mlb_baseline.py` (Pasos 5a/5b/9): dataset
builder -> vectorización -> training pipeline -> inference contract, con
dos diferencias deliberadas, ambas decisiones explícitas del Design
Proposal (Ambigüedad C/D):

  - **Persistencia INDEPENDIENTE**, propia de este módulo (JSON + joblib
    hermano, mismo patrón de archivos que `registry.py` pero sin
    importarlo ni modificarlo -- `registry.py` está acoplado a
    `MlbTrainedArtifact` específicamente). Ambos conviven sin colisión en
    el mismo `DATA_MODELS_DIR`: se distinguen por prefijo de archivo
    (`mlb_baseline_*` vs `tennis_baseline_*`).
  - **Umbral mínimo de entrenamiento propio** (`DEFAULT_MIN_TRAINING_SAMPLES_TENNIS
    = 30`), derivado de la misma heurística de ingeniería del plan
    ("10-20 observaciones por dimensión de feature", §5) aplicada a las 2
    dimensiones reales de tenis, no las ~26 de MLB -- explícitamente
    PROVISIONAL, revisable con evidencia, igual que el umbral de MLB.

ADVERTENCIA DE INTERPRETACIÓN DE LA ETIQUETA (mismo principio que
`mlb_baseline.py`): el modelo entrena y predice nativamente
`P(participant_a gana)`, tal como lo registra `event_results`. NO existe
ninguna conversión a "lado YES de un contrato de Kalshi concreto" (mismo
hueco ya documentado como Ambigüedad #2 del Paso 4).

Doble bloqueo esperado (PLAN_PHASE2.md §6): con SofaScore bloqueado y
poco histórico propio, es previsible que `model_status` permanezca en
`INSUFFICIENT_HISTORY` durante mucho tiempo -- resultado honesto, no un
fallo (§14, criterio 4).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.features.tennis_features import TennisFeatureInputs, compute_tennis_features
from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import NormalizedRecord
from src.storage.history_repository import HistoryRepository

# Heurística de ingeniería (Design Proposal Paso 11, Ambigüedad D): misma
# regla de "10-20 observaciones por dimensión" del plan (§5), aplicada a
# las 2 dimensiones de tenis (rest_days + tournament_round_context) en
# vez de las ~26 de MLB. PROVISIONAL, revisable con evidencia real.
DEFAULT_MIN_TRAINING_SAMPLES_TENNIS = 30

# Mismo valor y mismo rol que en mlb_baseline.py -- no es una decisión
# específica de tenis, se reutiliza la convención genérica de split.
DEFAULT_VALIDATION_FRACTION = 0.2

_VALID_RESULTS = {"PARTICIPANT_A_WON": 1, "PARTICIPANT_B_WON": 0}

# ---------------------------------------------------------------------
# Vectorización: dict de features (Paso 11) -> vector numérico fijo.
# ---------------------------------------------------------------------


def _vectorize_features(features: Dict[str, Any], round_categories: List[str]) -> Dict[str, float]:
    """Traduce el dict devuelto por `compute_tennis_features` a un dict
    PLANO `{columna: valor}`. `rest_days` por lado es escalar directo
    (NaN si falta). `tournament_round_context` es categórico de
    vocabulario ABIERTO (no acotado a 2 valores como `home_away` en MLB)
    -- se codifica manualmente como una bandera 0.0/1.0 por cada categoría
    YA OBSERVADA en el conjunto de entrenamiento (`round_categories`,
    descubierto en `train_tennis_baseline_model`, nunca una lista fija
    inventada). Una ronda desconocida o `None` produce una fila
    completamente en 0.0 para estas columnas -- nunca se fabrica una
    categoría."""
    row: Dict[str, float] = {}

    rest_days = features.get("rest_days") or {}
    for side in ("participant_a", "participant_b"):
        value = rest_days.get(side)
        row[f"rest_days.{side}"] = (
            float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")
        )

    round_value = features.get("tournament_round_context")
    for category in round_categories:
        row[f"tournament_round.{category}"] = 1.0 if round_value == category else 0.0

    return row


# ---------------------------------------------------------------------
# 1. Dataset builder
# ---------------------------------------------------------------------


@dataclass
class TennisTrainingSample:
    event_id: str
    feature_set_version: str
    features: Dict[str, Any]
    label: int  # 1 = participant_a ganó, 0 = participant_b ganó
    data_cutoff_timestamp: datetime
    result_recorded_at: datetime


@dataclass
class TennisTrainingDataset:
    samples: List[TennisTrainingSample] = field(default_factory=list)
    feature_set_version: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.samples)


def build_tennis_training_dataset(history_repository: HistoryRepository) -> TennisTrainingDataset:
    """Construye el dataset de entrenamiento de tenis desde
    `HistoryRepository` (`feature_snapshots` + `event_results`), NUNCA
    desde `normalized_records`. Mismo corte temporal no negociable que
    `build_mlb_training_dataset` (Paso 5b): una fila de features solo se
    etiqueta con un resultado si ese resultado se registró DESPUÉS de que
    las features fueran calculadas."""
    warnings: List[str] = []

    feature_rows = history_repository.get_all_feature_snapshots()
    result_rows = history_repository.get_all_event_results()

    latest_result_by_event: Dict[str, Dict[str, Any]] = {}
    for row in result_rows:
        event_id = row["event_id"]
        existing = latest_result_by_event.get(event_id)
        if existing is None or row["recorded_at"] > existing["recorded_at"]:
            latest_result_by_event[event_id] = row

    samples: List[TennisTrainingSample] = []
    excluded_wrong_sport = 0
    excluded_wrong_version = 0
    excluded_no_result = 0
    excluded_leakage = 0
    excluded_non_binary_result = 0

    for row in feature_rows:
        event_id = row["event_id"]

        # feature_snapshots no tiene columna `sport` propia -- se reutiliza
        # el prefijo ya establecido por tennis_normalizer.py
        # ("espn_tennis_{tour}_{id}"), mismo patrón que "mlb_" en MLB.
        if not event_id.startswith("espn_tennis_"):
            excluded_wrong_sport += 1
            continue

        if row["feature_set_version"] != CURRENT_FEATURE_SET_VERSION:
            excluded_wrong_version += 1
            continue

        result = latest_result_by_event.get(event_id)
        if result is None:
            excluded_no_result += 1
            continue

        computed_at = datetime.fromisoformat(row["computed_at"])
        recorded_at = datetime.fromisoformat(result["recorded_at"])
        if not (computed_at < recorded_at):
            excluded_leakage += 1
            continue

        result_value = result["result"]
        if result_value not in _VALID_RESULTS:
            excluded_non_binary_result += 1
            continue

        features = json.loads(row["features_json"])
        samples.append(
            TennisTrainingSample(
                event_id=event_id,
                feature_set_version=row["feature_set_version"],
                features=features,
                label=_VALID_RESULTS[result_value],
                data_cutoff_timestamp=computed_at,
                result_recorded_at=recorded_at,
            )
        )

    if excluded_wrong_sport:
        warnings.append(f"{excluded_wrong_sport} feature_snapshots excluidos: event_id no tiene prefijo 'espn_tennis_'")
    if excluded_wrong_version:
        warnings.append(
            f"{excluded_wrong_version} feature_snapshots excluidos: feature_set_version distinto de "
            f"{CURRENT_FEATURE_SET_VERSION!r}"
        )
    if excluded_no_result:
        warnings.append(f"{excluded_no_result} feature_snapshots excluidos: sin event_result todavía")
    if excluded_leakage:
        warnings.append(
            f"{excluded_leakage} feature_snapshots excluidos: el resultado se registró antes o al mismo "
            f"tiempo que las features (leakage temporal, nunca se etiqueta con esa fila)"
        )
    if excluded_non_binary_result:
        warnings.append(
            f"{excluded_non_binary_result} feature_snapshots excluidos: resultado no es "
            f"PARTICIPANT_A_WON/PARTICIPANT_B_WON (CANCELLED/POSTPONED/NO_CONTEST no son etiqueta binaria válida)"
        )

    feature_set_version = CURRENT_FEATURE_SET_VERSION if samples else None
    return TennisTrainingDataset(samples=samples, feature_set_version=feature_set_version, warnings=warnings)


def split_dataset_temporally(
    dataset: TennisTrainingDataset, validation_fraction: float = DEFAULT_VALIDATION_FRACTION
) -> Tuple[TennisTrainingDataset, TennisTrainingDataset]:
    """Split temporal simple train/validation -- NUNCA aleatorio, misma
    semántica exacta que `mlb_baseline.split_dataset_temporally` (Paso
    5b), duplicada aquí (no importada) para no acoplar `tennis_baseline.py`
    a `mlb_baseline.py`. La validación es siempre la porción cronológicamente
    MÁS RECIENTE."""
    ordered = sorted(dataset.samples, key=lambda s: (s.data_cutoff_timestamp, s.event_id))
    n_validation = round(len(ordered) * validation_fraction)
    n_validation = max(1, min(n_validation, len(ordered) - 1)) if len(ordered) > 1 else 0

    train_samples = ordered[: len(ordered) - n_validation]
    validation_samples = ordered[len(ordered) - n_validation :]

    train = TennisTrainingDataset(
        samples=train_samples, feature_set_version=dataset.feature_set_version, warnings=[]
    )
    validation = TennisTrainingDataset(
        samples=validation_samples, feature_set_version=dataset.feature_set_version, warnings=[]
    )
    return train, validation


# ---------------------------------------------------------------------
# 2. Persistencia INDEPENDIENTE (Ambigüedad C) -- no reutiliza ni
#    modifica src/models/registry.py.
# ---------------------------------------------------------------------


@dataclass
class TennisTrainedArtifact:
    model_version: str
    sport: str
    algorithm: str
    trained_at: datetime
    feature_set_version: str
    n_training_samples: int
    feature_columns: List[str]
    round_categories: List[str]
    file_path: Path
    n_train_samples: int = 0
    n_validation_samples: int = 0
    validation_fraction: float = 0.0
    accuracy: Optional[float] = None
    log_loss: Optional[float] = None
    brier_score: Optional[float] = None


def _tennis_metadata_path(models_dir: Path, model_version: str) -> Path:
    return models_dir / f"{model_version}.metadata.json"


def _save_tennis_artifact_metadata(artifact: TennisTrainedArtifact, models_dir: Path = DATA_MODELS_DIR) -> Path:
    """Persiste la metadata del artefacto YA serializado por
    `train_tennis_baseline_model` -- mismo patrón de archivos hermanos
    (.joblib + .metadata.json) que `registry.py`, pero como función propia
    de este módulo, nunca importando/modificando `registry.py`."""
    models_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_version": artifact.model_version,
        "sport": artifact.sport,
        "algorithm": artifact.algorithm,
        "trained_at": artifact.trained_at.isoformat(),
        "feature_set_version": artifact.feature_set_version,
        "n_training_samples": artifact.n_training_samples,
        "feature_columns": artifact.feature_columns,
        "round_categories": artifact.round_categories,
        "file_path": str(artifact.file_path),
        "n_train_samples": artifact.n_train_samples,
        "n_validation_samples": artifact.n_validation_samples,
        "validation_fraction": artifact.validation_fraction,
        "accuracy": artifact.accuracy,
        "log_loss": artifact.log_loss,
        "brier_score": artifact.brier_score,
    }
    path = _tennis_metadata_path(models_dir, artifact.model_version)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


def load_latest_tennis_artifact(models_dir: Path = DATA_MODELS_DIR) -> Optional[Tuple[Any, TennisTrainedArtifact]]:
    """Devuelve `(pipeline_sklearn_cargado, TennisTrainedArtifact)` del
    artefacto de tenis más reciente por `trained_at`, o `None` si no hay
    ninguno todavía. Filtra por prefijo `tennis_baseline_*` -- convive sin
    colisión con los artefactos MLB (`mlb_baseline_*`) en el mismo
    `DATA_MODELS_DIR`. Nunca lanza si el directorio no existe o está vacío."""
    if not models_dir.exists():
        return None

    latest_data: Optional[dict] = None
    latest_trained_at: Optional[datetime] = None
    for meta_path in sorted(models_dir.glob("tennis_baseline_*.metadata.json")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        trained_at = datetime.fromisoformat(data["trained_at"])
        if latest_trained_at is None or trained_at > latest_trained_at:
            latest_trained_at = trained_at
            latest_data = data

    if latest_data is None:
        return None

    import joblib

    model = joblib.load(latest_data["file_path"])
    artifact = TennisTrainedArtifact(
        model_version=latest_data["model_version"],
        sport=latest_data["sport"],
        algorithm=latest_data["algorithm"],
        trained_at=latest_trained_at,
        feature_set_version=latest_data["feature_set_version"],
        n_training_samples=latest_data["n_training_samples"],
        feature_columns=latest_data["feature_columns"],
        round_categories=latest_data.get("round_categories", []),
        file_path=Path(latest_data["file_path"]),
        n_train_samples=latest_data.get("n_train_samples", 0),
        n_validation_samples=latest_data.get("n_validation_samples", 0),
        validation_fraction=latest_data.get("validation_fraction", 0.0),
        accuracy=latest_data.get("accuracy"),
        log_loss=latest_data.get("log_loss"),
        brier_score=latest_data.get("brier_score"),
    )
    return model, artifact


# ---------------------------------------------------------------------
# 3. Training pipeline
# ---------------------------------------------------------------------


def train_tennis_baseline_model(
    history_repository: HistoryRepository,
    models_dir: Path = DATA_MODELS_DIR,
    min_samples: int = DEFAULT_MIN_TRAINING_SAMPLES_TENNIS,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    now: Optional[datetime] = None,
) -> Tuple[ModelStatus, Optional[TennisTrainedArtifact], List[str]]:
    """Training pipeline del baseline de tenis: SABE entrenar (regresión
    logística, `class_weight="balanced"`, mismo algoritmo que MLB) apenas
    exista histórico etiquetado suficiente. Nunca entrena con una muestra
    insuficiente -- devuelve `INSUFFICIENT_HISTORY` honestamente. Las
    categorías de `tournament_round_context` se descubren ÚNICAMENTE del
    split de TRAIN (nunca de validación), consistente con el principio de
    no usar validación para ninguna decisión de entrenamiento."""
    dataset = build_tennis_training_dataset(history_repository)
    warnings = list(dataset.warnings)

    if dataset.size < min_samples:
        warnings.append(
            f"dataset con {dataset.size} muestra(s) etiquetada(s), por debajo del umbral mínimo "
            f"({min_samples}) -- no se entrena ningún modelo (PLAN_PHASE2.md §6, Paso 11)."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    train_dataset, validation_dataset = split_dataset_temporally(dataset, validation_fraction=validation_fraction)

    round_categories = sorted(
        {
            s.features.get("tournament_round_context")
            for s in train_dataset.samples
            if s.features.get("tournament_round_context") is not None
        }
    )
    feature_columns = ["rest_days.participant_a", "rest_days.participant_b"] + [
        f"tournament_round.{category}" for category in round_categories
    ]

    import joblib
    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    def _to_matrix(samples: List[TennisTrainingSample]):
        return np.array(
            [
                [_vectorize_features(s.features, round_categories).get(col, float("nan")) for col in feature_columns]
                for s in samples
            ]
        )

    X_train = _to_matrix(train_dataset.samples)
    y_train = np.array([s.label for s in train_dataset.samples])
    X_val = _to_matrix(validation_dataset.samples)
    y_val = np.array([s.label for s in validation_dataset.samples])

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("logreg", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )
    pipeline.fit(X_train, y_train)

    val_proba = pipeline.predict_proba(X_val)[:, 1]
    val_pred = (val_proba >= 0.5).astype(int)

    accuracy = float(accuracy_score(y_val, val_pred))
    brier = float(brier_score_loss(y_val, val_proba))
    try:
        logloss = float(log_loss(y_val, val_proba, labels=[0, 1]))
    except ValueError as exc:
        logloss = None
        warnings.append(f"log_loss no pudo calcularse sobre la validación: {exc}")

    now = now or datetime.now(timezone.utc)
    model_version = f"tennis_baseline_logreg_v1_{now:%Y%m%dT%H%M%SZ}"
    models_dir.mkdir(parents=True, exist_ok=True)
    file_path = models_dir / f"{model_version}.joblib"
    joblib.dump(pipeline, file_path)

    artifact = TennisTrainedArtifact(
        model_version=model_version,
        sport="TENNIS",
        algorithm="logistic_regression_v1",
        trained_at=now,
        feature_set_version=dataset.feature_set_version or CURRENT_FEATURE_SET_VERSION,
        n_training_samples=dataset.size,
        feature_columns=feature_columns,
        round_categories=round_categories,
        file_path=file_path,
        n_train_samples=train_dataset.size,
        n_validation_samples=validation_dataset.size,
        validation_fraction=validation_fraction,
        accuracy=accuracy,
        log_loss=logloss,
        brier_score=brier,
    )

    _save_tennis_artifact_metadata(artifact, models_dir)

    return ModelStatus.TRAINED, artifact, warnings


# ---------------------------------------------------------------------
# 4. Inference contract -- funciona y es testeable incluso sin modelo
#    entrenado (`loaded_artifact=None`). Núcleo de inferencia único,
#    compartido por `predict_tennis_baseline` (en vivo) y
#    `predict_tennis_baseline_from_features` (histórico), mismo patrón
#    ya establecido para MLB (Paso 9).
# ---------------------------------------------------------------------


def _predict_proba_from_vectorized_features(
    model: Any, features: Dict[str, Any], feature_columns: List[str], round_categories: List[str]
) -> float:
    row = _vectorize_features(features, round_categories)
    X = [[row.get(col, float("nan")) for col in feature_columns]]
    return float(model.predict_proba(X)[0][1])


def predict_tennis_baseline(
    record: NormalizedRecord,
    inputs: TennisFeatureInputs,
    data_cutoff_timestamp: datetime,
    loaded_artifact: Optional[Tuple[Any, TennisTrainedArtifact]],
) -> PModelOutput:
    """Contrato de inferencia del baseline de tenis. `loaded_artifact=None`
    es un estado perfectamente válido -- `model_status=MODEL_NOT_TRAINED`,
    `p_model_yes=None`, nunca se fabrica una probabilidad."""
    features, missing, feature_warnings = compute_tennis_features(record, inputs, data_cutoff_timestamp)
    prediction_timestamp = datetime.now(timezone.utc)

    if loaded_artifact is None:
        return PModelOutput(
            p_model_yes=None,
            model_version=None,
            model_status=ModelStatus.MODEL_NOT_TRAINED,
            feature_set_version=CURRENT_FEATURE_SET_VERSION,
            prediction_timestamp=prediction_timestamp,
            data_cutoff_timestamp=data_cutoff_timestamp,
            missing_features=missing,
            warnings=feature_warnings,
        )

    model, artifact = loaded_artifact
    p_participant_a_win = _predict_proba_from_vectorized_features(
        model, features, artifact.feature_columns, artifact.round_categories
    )

    return PModelOutput(
        p_model_yes=p_participant_a_win,
        model_version=artifact.model_version,
        model_status=ModelStatus.TRAINED,
        feature_set_version=artifact.feature_set_version,
        prediction_timestamp=prediction_timestamp,
        data_cutoff_timestamp=data_cutoff_timestamp,
        missing_features=missing,
        warnings=feature_warnings,
    )


def predict_tennis_baseline_from_features(
    features: Dict[str, Any],
    loaded_artifact: Optional[Tuple[Any, TennisTrainedArtifact]],
) -> Optional[float]:
    """Wrapper delgado para inferencia histórica/backtesting -- mismo
    núcleo único de `predict_tennis_baseline`, sin duplicar lógica.
    Disponible desde ya para que un futuro uso de `src/backtesting/`
    sobre tenis (Design Proposal Paso 11, Ambigüedad F, diferido) no
    necesite ninguna extensión adicional a este módulo."""
    if loaded_artifact is None:
        return None
    model, artifact = loaded_artifact
    return _predict_proba_from_vectorized_features(model, features, artifact.feature_columns, artifact.round_categories)
