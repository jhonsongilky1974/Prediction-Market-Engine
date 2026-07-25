"""Infraestructura + modelo(s) baseline MLB (Paso 5a/5b). Ver
PLAN_PHASE2.md §5.

Cuatro piezas, en el orden en que se usan:
  1. Dataset builder (`build_mlb_training_dataset`) -- lee `feature_snapshots`
     + `event_results` de `HistoryRepository`, NUNCA de `normalized_records`.
  2. Vectorización (`_vectorize_features` / `MLB_FEATURE_COLUMNS`) --
     traduce el dict de features (Paso 2) a un vector numérico fijo.
  3. Training pipeline (`train_mlb_baseline_model`) -- código que SABE
     entrenar (regresión logística, scikit-learn), gated por un umbral
     mínimo de muestras etiquetadas; nunca entrena por debajo del umbral.
  4. Inference contract (`predict_mlb_baseline`) -- funciona y es
     testeable incluso sin ningún modelo entrenado.

ADVERTENCIA DE INTERPRETACIÓN DE LA ETIQUETA (ver docstring completo en
`src/models/base.py`): el modelo entrena y predice nativamente
`P(participant_a gana)`, tal como lo registra `event_results`
(`PARTICIPANT_A_WON`/`PARTICIPANT_B_WON`). NO existe ninguna conversión a
"lado YES de un contrato de Kalshi concreto" -- ese mapeo no está
respaldado hoy por ningún campo estructurado (mismo hueco ya documentado
como Ambigüedad #2 del Paso 4) y queda deliberadamente fuera de este
módulo, reservado para una futura capa de integración con mercados.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.features.mlb_features import MlbFeatureInputs, compute_mlb_features
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import NormalizedRecord
from src.storage.history_repository import HistoryRepository

# Heurística de ingeniería de PLAN_PHASE2.md §5 (~300-500 eventos
# etiquetados), no un umbral de decisión de apuesta. Revisable con
# evidencia, no congelado.
DEFAULT_MIN_TRAINING_SAMPLES = 300

_VALID_RESULTS = {"PARTICIPANT_A_WON": 1, "PARTICIPANT_B_WON": 0}

# ---------------------------------------------------------------------
# Vectorización: dict de features (Paso 2) -> vector numérico fijo.
# ---------------------------------------------------------------------

# Features side-aware escalares simples (una columna por lado).
_PER_SIDE_SCALAR_FEATURES = [
    "pitcher_era_season",
    "pitcher_whip_season",
    "pitcher_k_pct",
    "pitcher_bb_pct",
    "pitcher_ip_season",
    "pitcher_vs_opponent_handedness_ops",
    "bullpen_era_recent",
    "team_ops_season",
    "team_record_pct",
]

# Features side-aware booleanas (True/False/None -> 1.0/0.0/NaN).
_PER_SIDE_BOOL_FEATURES = ["il_flag_key_players"]

# pitcher_form_last5 es side-aware pero anidada: {"era":..., "whip":...}.
_FORM_LAST5_SUBFIELDS = ["era", "whip"]


def _vectorize_features(features: Dict[str, Any]) -> Dict[str, float]:
    """Traduce el dict devuelto por `compute_mlb_features` a un dict PLANO
    `{columna: valor}`, con `NaN` explícito donde falte el dato (nunca
    0/False salvo que sea el valor real -- mismo principio de Fase 1/2 de
    no fabricar datos faltantes). La imputación real ocurre después, en el
    `Pipeline` de scikit-learn (`SimpleImputer`), nunca aquí."""
    row: Dict[str, float] = {}

    for name in _PER_SIDE_SCALAR_FEATURES:
        value = features.get(name)
        for side in ("participant_a", "participant_b"):
            v = value.get(side) if isinstance(value, dict) else None
            row[f"{name}.{side}"] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")

    for name in _PER_SIDE_BOOL_FEATURES:
        value = features.get(name)
        for side in ("participant_a", "participant_b"):
            v = value.get(side) if isinstance(value, dict) else None
            row[f"{name}.{side}"] = float(v) if isinstance(v, bool) else float("nan")

    form = features.get("pitcher_form_last5")
    for side in ("participant_a", "participant_b"):
        side_form = form.get(side) if isinstance(form, dict) else None
        for sub in _FORM_LAST5_SUBFIELDS:
            v = side_form.get(sub) if isinstance(side_form, dict) else None
            row[f"pitcher_form_last5.{side}.{sub}"] = float(v) if isinstance(v, (int, float)) else float("nan")

    home_away = features.get("home_away")
    for side in ("participant_a", "participant_b"):
        v = home_away.get(side) if isinstance(home_away, dict) else None
        row[f"home_away.{side}"] = 1.0 if v == "home" else (0.0 if v == "away" else float("nan"))

    return row


# Orden de columnas derivado del propio vectorizador (nunca se declara dos
# veces la misma lista) -- determinista, siempre en sincronía.
MLB_FEATURE_COLUMNS: List[str] = sorted(_vectorize_features({}).keys())


# ---------------------------------------------------------------------
# 1. Dataset builder
# ---------------------------------------------------------------------


@dataclass
class MlbTrainingSample:
    event_id: str
    feature_set_version: str
    features: Dict[str, Any]
    label: int  # 1 = participant_a ganó, 0 = participant_b ganó
    data_cutoff_timestamp: datetime
    result_recorded_at: datetime


@dataclass
class MlbTrainingDataset:
    samples: List[MlbTrainingSample] = field(default_factory=list)
    feature_set_version: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.samples)


def build_mlb_training_dataset(history_repository: HistoryRepository) -> MlbTrainingDataset:
    """Construye el dataset de entrenamiento MLB desde `HistoryRepository`
    (`feature_snapshots` + `event_results`), NUNCA desde
    `normalized_records`. Respeta el corte temporal no negociable de
    Fase 2 (PLAN_PHASE2.md §10/§11 punto 3): una fila de features solo se
    etiqueta con un resultado si ese resultado se registró DESPUÉS de que
    las features fueran calculadas -- nunca al revés. El resultado más
    reciente registrado para un `event_id` es el que se usa si hay más de
    uno (append-only, puede haber correcciones)."""
    warnings: List[str] = []

    feature_rows = history_repository.get_all_feature_snapshots()
    result_rows = history_repository.get_all_event_results()

    latest_result_by_event: Dict[str, Dict[str, Any]] = {}
    for row in result_rows:
        event_id = row["event_id"]
        existing = latest_result_by_event.get(event_id)
        if existing is None or row["recorded_at"] > existing["recorded_at"]:
            latest_result_by_event[event_id] = row

    samples: List[MlbTrainingSample] = []
    feature_set_versions_seen = set()
    excluded_wrong_sport = 0
    excluded_wrong_version = 0
    excluded_no_result = 0
    excluded_leakage = 0
    excluded_non_binary_result = 0

    for row in feature_rows:
        event_id = row["event_id"]

        # feature_snapshots no tiene columna `sport` propia -- se reutiliza
        # el prefijo ya establecido por mlb_normalizer.py (`mlb_{game_pk}`)
        # en vez de inventar una convención nueva.
        if not event_id.startswith("mlb_"):
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
        feature_set_versions_seen.add(row["feature_set_version"])
        samples.append(
            MlbTrainingSample(
                event_id=event_id,
                feature_set_version=row["feature_set_version"],
                features=features,
                label=_VALID_RESULTS[result_value],
                data_cutoff_timestamp=computed_at,
                result_recorded_at=recorded_at,
            )
        )

    if excluded_wrong_sport:
        warnings.append(f"{excluded_wrong_sport} feature_snapshots excluidos: event_id no tiene prefijo 'mlb_'")
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
    return MlbTrainingDataset(samples=samples, feature_set_version=feature_set_version, warnings=warnings)


# ---------------------------------------------------------------------
# 3. Training pipeline
# ---------------------------------------------------------------------


@dataclass
class MlbTrainedArtifact:
    model_version: str
    sport: str
    algorithm: str
    trained_at: datetime
    feature_set_version: str
    n_training_samples: int
    feature_columns: List[str]
    file_path: Path


def train_mlb_baseline_model(
    history_repository: HistoryRepository,
    models_dir: Path = DATA_MODELS_DIR,
    min_samples: int = DEFAULT_MIN_TRAINING_SAMPLES,
    now: Optional[datetime] = None,
) -> Tuple[ModelStatus, Optional[MlbTrainedArtifact], List[str]]:
    """Training pipeline (Paso 5a/5b): SABE entrenar un baseline MLB
    (regresión logística) apenas exista histórico etiquetado suficiente.
    Nunca entrena con una muestra insuficiente -- devuelve
    `INSUFFICIENT_HISTORY` de forma honesta, sin fabricar ningún modelo
    (PLAN_PHASE2.md §5-B). scikit-learn solo se importa si el dataset ya
    alcanzó el umbral -- una corrida por debajo del umbral no toca la
    librería de ML en absoluto."""
    dataset = build_mlb_training_dataset(history_repository)
    warnings = list(dataset.warnings)

    if dataset.size < min_samples:
        warnings.append(
            f"dataset con {dataset.size} muestra(s) etiquetada(s), por debajo del umbral mínimo "
            f"({min_samples}) -- no se entrena ningún modelo (PLAN_PHASE2.md §5-B)."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    import joblib
    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.array(
        [[_vectorize_features(s.features).get(col, float("nan")) for col in MLB_FEATURE_COLUMNS] for s in dataset.samples]
    )
    y = np.array([s.label for s in dataset.samples])

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("logreg", LogisticRegression(max_iter=1000)),
        ]
    )
    pipeline.fit(X, y)

    now = now or datetime.now(timezone.utc)
    model_version = f"mlb_baseline_logreg_v1_{now:%Y%m%dT%H%M%SZ}"
    models_dir.mkdir(parents=True, exist_ok=True)
    file_path = models_dir / f"{model_version}.joblib"
    joblib.dump(pipeline, file_path)

    artifact = MlbTrainedArtifact(
        model_version=model_version,
        sport="MLB",
        algorithm="logistic_regression_v1",
        trained_at=now,
        feature_set_version=dataset.feature_set_version or CURRENT_FEATURE_SET_VERSION,
        n_training_samples=dataset.size,
        feature_columns=list(MLB_FEATURE_COLUMNS),
        file_path=file_path,
    )

    # Import diferido (no a nivel de módulo) para evitar un ciclo:
    # src.models.registry importa MlbTrainedArtifact de este módulo.
    from src.models.registry import save_artifact_metadata

    save_artifact_metadata(artifact, models_dir)

    return ModelStatus.TRAINED, artifact, warnings


# ---------------------------------------------------------------------
# 4. Inference contract -- funciona y es testeable incluso sin modelo
#    entrenado (`loaded_artifact=None`).
# ---------------------------------------------------------------------


def predict_mlb_baseline(
    record: NormalizedRecord,
    inputs: MlbFeatureInputs,
    data_cutoff_timestamp: datetime,
    loaded_artifact: Optional[Tuple[Any, MlbTrainedArtifact]],
) -> PModelOutput:
    """Contrato de inferencia (Paso 5a). Reutiliza `compute_mlb_features`
    (Paso 2) directamente sobre datos EN VIVO del evento -- a diferencia
    del dataset builder, NO lee `feature_snapshots` aquí (eso es solo
    histórico, para entrenar). `loaded_artifact=None` es un estado
    perfectamente válido: significa que no hay ningún artefacto
    registrado todavía, sea porque nunca se entrenó o porque el último
    intento fue `INSUFFICIENT_HISTORY` -- en ambos casos, `model_status`
    de inferencia es `MODEL_NOT_TRAINED` y `p_model_yes=None`, nunca se
    fabrica una probabilidad."""
    features, missing, feature_warnings = compute_mlb_features(record, inputs, data_cutoff_timestamp)
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
    row = _vectorize_features(features)
    X = [[row.get(col, float("nan")) for col in artifact.feature_columns]]
    p_participant_a_win = float(model.predict_proba(X)[0][1])

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
