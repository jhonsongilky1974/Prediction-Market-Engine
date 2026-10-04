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

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DATA_MODELS_DIR
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.features.tennis_features import TennisFeatureInputs, compute_tennis_features
from src.models.base import ModelStatus, PModelOutput
from src.models.model_registry_policy import (
    ModelRegistryPolicy,
    load_model_registry,
    read_bytes_once,
    resolve_declared_path,
)
from src.models.preevent_snapshots import (
    MIN_SNAPSHOT_LEAD_MINUTES,
    PreeventViolation,
    preevent_violations,
    select_one_snapshot_per_event,
)
from src.models.schemas import NormalizedRecord
from src.storage.history_repository import HistoryRepository

logger = logging.getLogger(__name__)

# Heurística de ingeniería (Design Proposal Paso 11, Ambigüedad D): misma
# regla de "10-20 observaciones por dimensión" del plan (§5), aplicada a
# las 2 dimensiones de tenis (rest_days + tournament_round_context) en
# vez de las ~26 de MLB. PROVISIONAL, revisable con evidencia real.
DEFAULT_MIN_TRAINING_SAMPLES_TENNIS = 30

# Mismo valor y mismo rol que en mlb_baseline.py -- no es una decisión
# específica de tenis, se reutiliza la convención genérica de split.
DEFAULT_VALIDATION_FRACTION = 0.2

# --- Política de reentrenamiento v2 (CONTINUITY.md §0.38, decisión explícita) ---
# Spec del dataset: un snapshot PRE-EVENTO (>= MIN_SNAPSHOT_LEAD_MINUTES antes
# del inicio, status SCHEDULED) por evento -- ver `src.models.preevent_snapshots`.
TRAINING_DATASET_SPEC_VERSION = "v2_preevent_one_per_event"
# Mínimo de EVENTOS independientes y válidos (no filas) para entrenar.
MIN_EVENTS_FOR_RETRAIN = 150
# Mínimo de eventos por partición (train/validación/test). El test temporal
# exige >= 30 eventos (decisión explícita).
MIN_PARTITION_EVENTS = 30
DEFAULT_TRAIN_FRACTION = 0.6
CANDIDATE_PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
CANDIDATE_REJECTED = "REJECTED_CANDIDATE"
# Un artefacto NUNCA se activa por existir: solo si figura ALLOWED (con SHA
# verificado) en `config/model_registry.json` (`src.models.model_registry_policy`).

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
    event_start_time: Optional[datetime] = None
    snapshot_lead_minutes: Optional[float] = None
    feature_snapshot_id: Optional[int] = None
    snapshot_computed_at: Optional[datetime] = None


@dataclass
class TennisTrainingDataset:
    samples: List[TennisTrainingSample] = field(default_factory=list)
    feature_set_version: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    # Fase 4, Paso 4.2 (Coverage Gate) -- aditivo, mismo motivo y mismas
    # claves que MlbTrainingDataset.exclusions (src/models/mlb_baseline.py).
    exclusions: Dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.samples)


def _parse_iso(value: str) -> datetime:
    """`fromisoformat` de Python 3.9 no acepta el sufijo `Z`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_tennis_training_dataset(history_repository: HistoryRepository) -> TennisTrainingDataset:
    """Construye el dataset de entrenamiento de tenis (spec
    `v2_preevent_one_per_event`, CONTINUITY.md §0.38) desde
    `HistoryRepository` (`feature_snapshots` + `event_snapshots` +
    `event_results`), NUNCA desde `normalized_records`.

    Además del corte original (`computed_at < result.recorded_at`, que
    por sí solo NO impide usar snapshots posteriores al partido cuando el
    resultado se cargó en bloque), cada snapshot debe ser PRE-EVENTO:
    `computed_at`, `data_cutoff_timestamp` y `captured_at` estrictamente
    anteriores a `event_start_time`, con anticipación >=
    `MIN_SNAPSHOT_LEAD_MINUTES`, y `status == SCHEDULED`. Se conserva
    exactamente UN snapshot por evento (el válido más reciente), de modo
    que cada muestra es un evento independiente."""
    warnings: List[str] = []

    feature_rows = history_repository.get_all_feature_snapshots()
    result_rows = history_repository.get_all_event_results()

    latest_result_by_event: Dict[str, Dict[str, Any]] = {}
    for row in result_rows:
        event_id = row["event_id"]
        existing = latest_result_by_event.get(event_id)
        if existing is None or row["recorded_at"] > existing["recorded_at"]:
            latest_result_by_event[event_id] = row

    excluded_wrong_sport = 0
    excluded_wrong_version = 0
    excluded_no_result = 0
    excluded_leakage = 0
    excluded_non_binary_result = 0
    excluded_missing_context = 0
    excluded_missing_start_time = 0
    excluded_status_not_scheduled = 0
    excluded_not_before_start = 0
    excluded_insufficient_lead = 0
    excluded_negative_rest_days = 0

    pending: List[Tuple[Dict[str, Any], Dict[str, Any], datetime, datetime]] = []
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

        computed_at = _parse_iso(row["computed_at"])
        recorded_at = _parse_iso(result["recorded_at"])
        if not (computed_at < recorded_at):
            excluded_leakage += 1
            continue

        if result["result"] not in _VALID_RESULTS:
            excluded_non_binary_result += 1
            continue

        pending.append((row, result, computed_at, recorded_at))

    contexts = history_repository.get_event_snapshot_contexts([row["event_snapshot_id"] for row, _, _, _ in pending])

    valid: List[TennisTrainingSample] = []
    for row, result, computed_at, recorded_at in pending:
        context = contexts.get(row["event_snapshot_id"])
        if context is None:
            excluded_missing_context += 1
            continue

        start_raw = context["event_start_time"]
        event_start_time = _parse_iso(start_raw) if start_raw else None
        data_cutoff = _parse_iso(row["data_cutoff_timestamp"])
        violations = preevent_violations(
            event_start_time=event_start_time,
            status=context["event_status"],
            data_cutoff_timestamp=data_cutoff,
            computed_at=computed_at,
            captured_at=_parse_iso(context["captured_at"]),
            min_lead_minutes=MIN_SNAPSHOT_LEAD_MINUTES,
        )
        if violations:
            if PreeventViolation.MISSING_START_TIME in violations:
                excluded_missing_start_time += 1
            elif PreeventViolation.STATUS_NOT_SCHEDULED in violations:
                excluded_status_not_scheduled += 1
            elif violations == [PreeventViolation.INSUFFICIENT_LEAD]:
                excluded_insufficient_lead += 1
            else:
                excluded_not_before_start += 1
            continue

        features = json.loads(row["features_json"])
        rest_days = features.get("rest_days") or {}
        if any(isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0 for v in rest_days.values()):
            excluded_negative_rest_days += 1
            continue

        valid.append(
            TennisTrainingSample(
                event_id=row["event_id"],
                feature_set_version=row["feature_set_version"],
                features=features,
                label=_VALID_RESULTS[result["result"]],
                data_cutoff_timestamp=data_cutoff,
                result_recorded_at=recorded_at,
                event_start_time=event_start_time,
                snapshot_lead_minutes=(event_start_time - computed_at).total_seconds() / 60.0,
                snapshot_computed_at=computed_at,
                feature_snapshot_id=row.get("id"),
            )
        )

    chosen = select_one_snapshot_per_event(
        valid,
        event_id_of=lambda s_: s_.event_id,
        computed_at_of=lambda s_: s_.snapshot_computed_at,
        tie_break_of=lambda s_: (s_.feature_snapshot_id or 0),
    )
    superseded_same_event = len(valid) - len(chosen)
    samples = sorted(chosen.values(), key=lambda s_: (s_.event_start_time, s_.event_id))

    messages = (
        (excluded_wrong_sport, "{n} feature_snapshots excluidos: event_id no tiene prefijo 'espn_tennis_'"),
        (
            excluded_wrong_version,
            "{n} feature_snapshots excluidos: feature_set_version distinto de " + repr(CURRENT_FEATURE_SET_VERSION),
        ),
        (excluded_no_result, "{n} feature_snapshots excluidos: sin event_result todavía"),
        (
            excluded_leakage,
            "{n} feature_snapshots excluidos: el resultado se registró antes o al mismo tiempo que las features "
            "(leakage temporal, nunca se etiqueta con esa fila)",
        ),
        (
            excluded_non_binary_result,
            "{n} feature_snapshots excluidos: resultado no es PARTICIPANT_A_WON/PARTICIPANT_B_WON "
            "(CANCELLED/POSTPONED/NO_CONTEST no son etiqueta binaria válida)",
        ),
        (excluded_missing_context, "{n} feature_snapshots excluidos: sin event_snapshot asociado"),
        (excluded_missing_start_time, "{n} feature_snapshots excluidos: event_start_time ausente"),
        (
            excluded_status_not_scheduled,
            "{n} feature_snapshots excluidos: status distinto de SCHEDULED (partido ya LIVE/FINAL u otro estado)",
        ),
        (
            excluded_not_before_start,
            "{n} feature_snapshots excluidos: snapshot/corte/captura NO anterior a event_start_time "
            "(información posterior al comienzo)",
        ),
        (
            excluded_insufficient_lead,
            "{n} feature_snapshots excluidos: anticipación menor a " + str(MIN_SNAPSHOT_LEAD_MINUTES) + " minutos",
        ),
        (excluded_negative_rest_days, "{n} feature_snapshots excluidos: rest_days negativo (dato incompatible)"),
        (
            superseded_same_event,
            "{n} snapshots pre-evento válidos descartados: solo se conserva UN snapshot por evento (el más reciente)",
        ),
    )
    for count, text in messages:
        if count:
            warnings.append(text.format(n=count))

    feature_set_version = CURRENT_FEATURE_SET_VERSION if samples else None
    exclusions = {
        "wrong_sport": excluded_wrong_sport,
        "wrong_version": excluded_wrong_version,
        "no_result": excluded_no_result,
        "leakage": excluded_leakage,
        "non_binary_result": excluded_non_binary_result,
        "missing_event_context": excluded_missing_context,
        "missing_start_time": excluded_missing_start_time,
        "status_not_scheduled": excluded_status_not_scheduled,
        "not_before_event_start": excluded_not_before_start,
        "insufficient_lead": excluded_insufficient_lead,
        "negative_rest_days": excluded_negative_rest_days,
        "superseded_same_event": superseded_same_event,
    }
    return TennisTrainingDataset(
        samples=samples, feature_set_version=feature_set_version, warnings=warnings, exclusions=exclusions
    )


def split_dataset_temporally(
    dataset: TennisTrainingDataset, validation_fraction: float = DEFAULT_VALIDATION_FRACTION
) -> Tuple[TennisTrainingDataset, TennisTrainingDataset]:
    """Split temporal train/validation agrupado por `event_id` -- NUNCA
    aleatorio, misma semántica exacta que
    `mlb_baseline.split_dataset_temporally` (Paso 5b + corrección de
    fuga de datos del Paso 4.3, ver docstring hermano para el detalle
    completo del hallazgo), duplicada aquí (no importada) para no
    acoplar `tennis_baseline.py` a `mlb_baseline.py`. La validación es
    siempre la porción de EVENTOS (no de muestras individuales)
    cronológicamente MÁS RECIENTE -- ningún `event_id` puede aparecer en
    ambas particiones."""
    samples_by_event: Dict[str, List[TennisTrainingSample]] = {}
    for sample in dataset.samples:
        samples_by_event.setdefault(sample.event_id, []).append(sample)

    event_order = sorted(
        samples_by_event, key=lambda event_id: (min(s.data_cutoff_timestamp for s in samples_by_event[event_id]), event_id)
    )
    n_validation_events = round(len(event_order) * validation_fraction)
    n_validation_events = max(1, min(n_validation_events, len(event_order) - 1)) if len(event_order) > 1 else 0

    train_event_ids = set(event_order[: len(event_order) - n_validation_events])
    train_samples = [s for s in dataset.samples if s.event_id in train_event_ids]
    validation_samples = [s for s in dataset.samples if s.event_id not in train_event_ids]

    train = TennisTrainingDataset(
        samples=train_samples, feature_set_version=dataset.feature_set_version, warnings=[]
    )
    validation = TennisTrainingDataset(
        samples=validation_samples, feature_set_version=dataset.feature_set_version, warnings=[]
    )
    return train, validation


def split_events_temporally(
    dataset: TennisTrainingDataset,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
) -> Tuple[TennisTrainingDataset, TennisTrainingDataset, TennisTrainingDataset]:
    """Split ESTRICTAMENTE temporal en tres particiones disjuntas por
    `event_id` (train / validación / test), ordenadas por
    `event_start_time` ascendente (desempate por `event_id`) -- NUNCA
    aleatorio. train = eventos más antiguos, test = los más recientes. Cada
    evento aparece en exactamente una partición (el dataset v2 ya trae
    una muestra por evento). La fracción de test es el remanente
    `1 - train_fraction - validation_fraction`.

    Lanza `ValueError` si algún evento no tiene `event_start_time` (no se
    puede ordenar cronológicamente sin inventar un orden) o si alguna
    partición quedaría vacía."""
    if train_fraction <= 0 or validation_fraction <= 0 or train_fraction + validation_fraction >= 1:
        raise ValueError(
            f"fracciones inválidas: train={train_fraction}, validation={validation_fraction} "
            "(ambas deben ser > 0 y dejar un remanente > 0 para test)"
        )

    samples_by_event: Dict[str, List[TennisTrainingSample]] = {}
    for sample in dataset.samples:
        if sample.event_start_time is None:
            raise ValueError(f"event_id={sample.event_id!r} sin event_start_time: no se puede ordenar cronológicamente")
        samples_by_event.setdefault(sample.event_id, []).append(sample)

    event_order = sorted(
        samples_by_event, key=lambda event_id: (min(s.event_start_time for s in samples_by_event[event_id]), event_id)
    )
    n = len(event_order)
    n_train = round(n * train_fraction)
    n_validation = round(n * validation_fraction)
    n_test = n - n_train - n_validation
    if min(n_train, n_validation, n_test) < 1:
        raise ValueError(f"{n} evento(s) insuficientes para tres particiones no vacías (train/val/test)")

    train_ids = set(event_order[:n_train])
    validation_ids = set(event_order[n_train : n_train + n_validation])
    test_ids = set(event_order[n_train + n_validation :])

    def _subset(ids: set) -> TennisTrainingDataset:
        return TennisTrainingDataset(
            samples=[s for s in dataset.samples if s.event_id in ids],
            feature_set_version=dataset.feature_set_version,
            warnings=[],
        )

    return _subset(train_ids), _subset(validation_ids), _subset(test_ids)


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
    # Fase 4, Paso 4.3 -- aditivo (MODEL_TRAINING_SPEC.md §0.5.2-4).
    n_train_events: int = 0
    """Eventos distintos (no muestras) del lado `train` -- transparencia
    del split corregido por `event_id` (§0.5.1)."""
    n_validation_events: int = 0
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    ece: Optional[float] = None
    """Expected Calibration Error del modelo CRUDO (sin calibrar) sobre
    la validación -- reutiliza `src.backtesting.metrics.ece` (Fase 3,
    Paso 3.8), no una fórmula nueva."""
    reliability_diagram: Optional[List[Dict[str, float]]] = None
    """Curva de calibración cruda (`src.backtesting.metrics.calibration_curve`)
    serializada por bucket -- la evidencia más directa para decidir, en
    un paso futuro, si vale la pena calibrar en absoluto."""
    calibration_version: Optional[str] = None
    """Permanece `None` hasta que exista una implementación real de
    `Calibrator` (`src/calibration/calibration_layer.py`) -- estructura
    del contrato declarada por adelantado, no un valor fabricado."""
    calibration_method: Optional[str] = None
    artifact_sha256: str = ""
    """`sha256` del contenido binario del `.joblib` ya escrito -- mismo
    principio que `PolicyManifest.manifest_hash`, aplicado al contenido
    real del artefacto (detecta corrupción/reentrenamiento idéntico, no
    solo diferencia por timestamp)."""
    validation_event_ids: List[str] = field(default_factory=list)
    """`event_id` exactos del split de validación (hallazgo de
    `CALIBRATION_SPEC.md` §0.4/§4.4): permite a un paso futuro (p.ej.
    calibración) reconstruir la partición EXACTA usada para entrenar este
    artefacto sin depender de recomputar `split_dataset_temporally` contra
    un `HistoryRepository` que puede haber crecido desde entonces. Vacío
    para artefactos entrenados antes de este campo (Paso 4.3) -- nunca
    fabricado retroactivamente."""
    # --- Spec v2 (CONTINUITY.md §0.38): None en artefactos anteriores ---
    training_dataset_spec_version: Optional[str] = None
    min_snapshot_lead_minutes: Optional[int] = None
    train_event_ids: List[str] = field(default_factory=list)
    test_event_ids: List[str] = field(default_factory=list)
    n_test_events: int = 0
    test_brier: Optional[float] = None
    test_accuracy: Optional[float] = None
    test_log_loss: Optional[float] = None
    baseline_test_brier: Optional[float] = None
    baseline_test_log_loss: Optional[float] = None
    candidate_status: Optional[str] = None
    """`PROMOTION_ELIGIBLE` solo si el modelo supera la baseline simple
    (tasa base de TRAIN) en el test temporal fuera de muestra Y se entrenó
    con los mínimos de política; si no, `REJECTED_CANDIDATE` -- el
    artefacto se conserva como evidencia pero nunca es activable."""
    min_events_policy: Optional[int] = None
    min_partition_events_policy: Optional[int] = None


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
        "n_train_events": artifact.n_train_events,
        "n_validation_events": artifact.n_validation_events,
        "precision": artifact.precision,
        "recall": artifact.recall,
        "f1": artifact.f1,
        "ece": artifact.ece,
        "reliability_diagram": artifact.reliability_diagram,
        "calibration_version": artifact.calibration_version,
        "calibration_method": artifact.calibration_method,
        "artifact_sha256": artifact.artifact_sha256,
        "validation_event_ids": artifact.validation_event_ids,
        "training_dataset_spec_version": artifact.training_dataset_spec_version,
        "min_snapshot_lead_minutes": artifact.min_snapshot_lead_minutes,
        "train_event_ids": artifact.train_event_ids,
        "test_event_ids": artifact.test_event_ids,
        "n_test_events": artifact.n_test_events,
        "test_brier": artifact.test_brier,
        "test_accuracy": artifact.test_accuracy,
        "test_log_loss": artifact.test_log_loss,
        "baseline_test_brier": artifact.baseline_test_brier,
        "baseline_test_log_loss": artifact.baseline_test_log_loss,
        "candidate_status": artifact.candidate_status,
        "min_events_policy": artifact.min_events_policy,
        "min_partition_events_policy": artifact.min_partition_events_policy,
    }
    path = _tennis_metadata_path(models_dir, artifact.model_version)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


def load_latest_tennis_artifact(
    models_dir: Path = DATA_MODELS_DIR, registry: Optional[ModelRegistryPolicy] = None
) -> Optional[Tuple[Any, TennisTrainedArtifact]]:
    """Devuelve `(pipeline_sklearn_cargado, TennisTrainedArtifact)` del
    artefacto de tenis ACTIVABLE más reciente por `trained_at`, o `None` si
    no hay ninguno. Filtra por prefijo `tennis_baseline_*` -- convive sin
    colisión con los artefactos MLB (`mlb_baseline_*`) en el mismo
    `DATA_MODELS_DIR`. Nunca lanza si el directorio no existe, está vacío o
    un archivo de metadata es ilegible.

    CONTENCIÓN FAIL-CLOSED (CONTINUITY.md §0.38): solo es activable un
    artefacto con `status=ALLOWED` y SHA-256 verificado en el registro de
    modelos (`config/model_registry.json`, `registry=None` -> lo carga);
    uno desconocido, `INVALID`, `REJECTED_CANDIDATE` o con SHA distinto se
    rechaza (se registra en el log) sin moverlo ni borrarlo. Si ninguno
    es activable devuelve `None` -- mismo estado que `MODEL_NOT_TRAINED`,
    nunca se fabrica una probabilidad."""
    if not models_dir.exists():
        return None

    policy = registry if registry is not None else load_model_registry()

    latest_data: Optional[dict] = None
    latest_trained_at: Optional[datetime] = None
    latest_payload: Optional[bytes] = None
    for meta_path in sorted(models_dir.glob("tennis_baseline_*.metadata.json")):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            model_version = data["model_version"]
            trained_at = datetime.fromisoformat(data["trained_at"])
            data["file_path"]  # campo obligatorio de la metadata
        except (OSError, ValueError, KeyError) as exc:
            logger.error("metadata de modelo de tenis ilegible %s: %r -- se rechaza", meta_path, exc)
            continue

        # El artefacto se localiza por `metadata.file_path` (contrato previo),
        # validado por `resolve_declared_path` (archivo regular DENTRO de
        # `models_dir`, sin traversal ni symlinks) y se lee UNA sola vez: el
        # SHA-256 verificado y la deserialización posterior usan exactamente
        # estos bytes (sin ventana TOCTOU).
        artifact_path = resolve_declared_path(models_dir, data["file_path"])
        if artifact_path is None:
            logger.warning(
                "modelo de tenis %s RECHAZADO (no activable): file_path %r no válido, ausente o fuera de %s",
                model_version, data["file_path"], models_dir,
            )
            continue
        payload = read_bytes_once(artifact_path)
        activable, reason = policy.check_bytes(model_version, payload)
        if not activable:
            logger.warning("modelo de tenis %s RECHAZADO (no activable): %s", model_version, reason)
            continue
        if data.get("candidate_status") == CANDIDATE_REJECTED:
            logger.warning(
                "modelo de tenis %s RECHAZADO: candidate_status=%s (no superó la baseline fuera de muestra)",
                model_version,
                CANDIDATE_REJECTED,
            )
            continue

        if latest_trained_at is None or trained_at > latest_trained_at:
            latest_trained_at = trained_at
            latest_data = data
            latest_payload = payload

    if latest_data is None or latest_payload is None:
        return None

    import io

    import joblib

    model = joblib.load(io.BytesIO(latest_payload))
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
        # Hallazgo real (calibración, ver CALIBRATION_SPEC.md): estos
        # campos existen en TennisTrainedArtifact y ya se PERSISTEN desde
        # el Paso 4.3 (_save_tennis_artifact_metadata), pero nunca se
        # habían vuelto a CARGAR aquí -- .get(...) con default para
        # metadata anterior a su introducción, nunca fabricado.
        n_train_events=latest_data.get("n_train_events", 0),
        n_validation_events=latest_data.get("n_validation_events", 0),
        precision=latest_data.get("precision"),
        recall=latest_data.get("recall"),
        f1=latest_data.get("f1"),
        ece=latest_data.get("ece"),
        reliability_diagram=latest_data.get("reliability_diagram"),
        calibration_version=latest_data.get("calibration_version"),
        calibration_method=latest_data.get("calibration_method"),
        artifact_sha256=latest_data.get("artifact_sha256", ""),
        validation_event_ids=latest_data.get("validation_event_ids", []),
        training_dataset_spec_version=latest_data.get("training_dataset_spec_version"),
        min_snapshot_lead_minutes=latest_data.get("min_snapshot_lead_minutes"),
        train_event_ids=latest_data.get("train_event_ids", []),
        test_event_ids=latest_data.get("test_event_ids", []),
        n_test_events=latest_data.get("n_test_events", 0),
        test_brier=latest_data.get("test_brier"),
        test_accuracy=latest_data.get("test_accuracy"),
        test_log_loss=latest_data.get("test_log_loss"),
        baseline_test_brier=latest_data.get("baseline_test_brier"),
        baseline_test_log_loss=latest_data.get("baseline_test_log_loss"),
        candidate_status=latest_data.get("candidate_status"),
        min_events_policy=latest_data.get("min_events_policy"),
        min_partition_events_policy=latest_data.get("min_partition_events_policy"),
    )
    return model, artifact


# ---------------------------------------------------------------------
# 3. Training pipeline
# ---------------------------------------------------------------------


def train_tennis_baseline_model(
    history_repository: HistoryRepository,
    models_dir: Path = DATA_MODELS_DIR,
    min_samples: int = MIN_EVENTS_FOR_RETRAIN,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    min_partition_events: int = MIN_PARTITION_EVENTS,
    now: Optional[datetime] = None,
) -> Tuple[ModelStatus, Optional[TennisTrainedArtifact], List[str]]:
    """Training pipeline del baseline de tenis (spec v2, CONTINUITY.md
    §0.38): regresión logística (`class_weight="balanced"`, mismas
    features) sobre el dataset PRE-EVENTO de un snapshot por evento
    (`build_tennis_training_dataset`) con split ESTRICTAMENTE temporal en
    tres particiones disjuntas (`split_events_temporally`): ajuste solo
    con train, métricas de validación, y un único test temporal fuera de
    muestra contra una baseline simple (tasa base de TRAIN).

    Nunca entrena con una muestra insuficiente: menos de `min_samples`
    eventos, o una partición con menos de `min_partition_events`, devuelve
    `INSUFFICIENT_HISTORY`. El artefacto se guarda siempre con una versión
    nueva (nunca sobrescribe otro) y NO es activable por existir: requiere
    una entrada `ALLOWED` en `config/model_registry.json`. Su
    `candidate_status` es `PROMOTION_ELIGIBLE` solo si (a) supera la
    baseline en Brier Y log-loss del test y (b) se entrenó con mínimos >=
    a la política (`MIN_EVENTS_FOR_RETRAIN`/`MIN_PARTITION_EVENTS`); de lo
    contrario `REJECTED_CANDIDATE`. El test NUNCA se usa para ajustar nada.
    Las categorías de ronda se descubren ÚNICAMENTE de train."""
    dataset = build_tennis_training_dataset(history_repository)
    warnings = list(dataset.warnings)

    if dataset.size < min_samples:
        warnings.append(
            f"dataset con {dataset.size} evento(s) independiente(s) válido(s), por debajo del umbral mínimo "
            f"({min_samples}) -- no se entrena ningún modelo."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    try:
        train_dataset, validation_dataset, test_dataset = split_events_temporally(
            dataset, train_fraction=train_fraction, validation_fraction=validation_fraction
        )
    except ValueError as exc:
        warnings.append(f"split temporal imposible: {exc}")
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    partition_sizes = {
        "train": train_dataset.size,
        "validation": validation_dataset.size,
        "test": test_dataset.size,
    }
    too_small = {name: size for name, size in partition_sizes.items() if size < min_partition_events}
    if too_small:
        warnings.append(
            f"particiones por debajo del mínimo de {min_partition_events} eventos ({too_small}) -- "
            "no se entrena ningún modelo."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings
    if len({s.label for s in train_dataset.samples}) < 2:
        warnings.append("la partición de train tiene una sola clase de resultado -- no se puede ajustar el modelo.")
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

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
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
    )
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    from src.backtesting.metrics import calibration_curve, ece as compute_ece

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
    X_test = _to_matrix(test_dataset.samples)
    y_test = np.array([s.label for s in test_dataset.samples])

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

    precision = float(precision_score(y_val, val_pred, zero_division=0))
    recall = float(recall_score(y_val, val_pred, zero_division=0))
    f1 = float(f1_score(y_val, val_pred, zero_division=0))
    val_ece = compute_ece(list(y_val), list(val_proba))
    buckets = calibration_curve(list(y_val), list(val_proba))
    reliability_diagram = [
        {
            "bin_lo": b.bin_lo,
            "bin_hi": b.bin_hi,
            "mean_predicted": b.mean_predicted,
            "mean_actual": b.mean_actual,
            "n_samples": b.n_samples,
        }
        for b in buckets
    ] or None

    # --- Test temporal fuera de muestra: UNA sola evaluación, contra baseline simple ---
    test_proba = pipeline.predict_proba(X_test)[:, 1]
    test_pred = (test_proba >= 0.5).astype(int)
    test_accuracy = float(accuracy_score(y_test, test_pred))
    test_brier = float(brier_score_loss(y_test, test_proba))
    base_rate = float(np.mean(y_train))
    baseline_proba = np.full(len(y_test), min(max(base_rate, 1e-6), 1 - 1e-6))
    baseline_test_brier = float(brier_score_loss(y_test, baseline_proba))
    try:
        test_logloss: Optional[float] = float(log_loss(y_test, test_proba, labels=[0, 1]))
        baseline_test_logloss: Optional[float] = float(log_loss(y_test, baseline_proba, labels=[0, 1]))
    except ValueError as exc:
        test_logloss = None
        baseline_test_logloss = None
        warnings.append(f"log_loss del test no pudo calcularse: {exc}")

    beats_baseline = (
        test_brier < baseline_test_brier
        and test_logloss is not None
        and baseline_test_logloss is not None
        and test_logloss < baseline_test_logloss
    )
    policy_compliant = min_samples >= MIN_EVENTS_FOR_RETRAIN and min_partition_events >= MIN_PARTITION_EVENTS
    candidate_status = CANDIDATE_PROMOTION_ELIGIBLE if (beats_baseline and policy_compliant) else CANDIDATE_REJECTED
    if not beats_baseline:
        warnings.append(
            f"CANDIDATO RECHAZADO: no supera la baseline simple (tasa base de train) en el test temporal fuera de "
            f"muestra (Brier modelo={test_brier:.4f} vs baseline={baseline_test_brier:.4f}; log-loss modelo="
            f"{test_logloss} vs baseline={baseline_test_logloss}). No se activa ni se ajusta con el test."
        )
    if not policy_compliant:
        warnings.append(
            f"CANDIDATO RECHAZADO: entrenado con mínimos por debajo de la política "
            f"(min_samples={min_samples} < {MIN_EVENTS_FOR_RETRAIN} o "
            f"min_partition_events={min_partition_events} < {MIN_PARTITION_EVENTS})."
        )

    now = now or datetime.now(timezone.utc)
    model_version = f"tennis_baseline_logreg_v1_{now:%Y%m%dT%H%M%SZ}"
    models_dir.mkdir(parents=True, exist_ok=True)
    file_path = models_dir / f"{model_version}.joblib"
    joblib.dump(pipeline, file_path)
    artifact_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

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
        n_train_events=len({s.event_id for s in train_dataset.samples}),
        n_validation_events=len({s.event_id for s in validation_dataset.samples}),
        precision=precision,
        recall=recall,
        f1=f1,
        ece=val_ece,
        reliability_diagram=reliability_diagram,
        calibration_version=None,
        calibration_method=None,
        artifact_sha256=artifact_sha256,
        brier_score=brier,
        validation_event_ids=sorted({s.event_id for s in validation_dataset.samples}),
        training_dataset_spec_version=TRAINING_DATASET_SPEC_VERSION,
        min_snapshot_lead_minutes=MIN_SNAPSHOT_LEAD_MINUTES,
        train_event_ids=sorted({s.event_id for s in train_dataset.samples}),
        test_event_ids=sorted({s.event_id for s in test_dataset.samples}),
        n_test_events=len({s.event_id for s in test_dataset.samples}),
        test_brier=test_brier,
        test_accuracy=test_accuracy,
        test_log_loss=test_logloss,
        baseline_test_brier=baseline_test_brier,
        baseline_test_log_loss=baseline_test_logloss,
        candidate_status=candidate_status,
        min_events_policy=min_samples,
        min_partition_events_policy=min_partition_events,
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

    # Puerta pre-evento (CONTINUITY.md §0.38): el modelo solo predice ANTES
    # del comienzo de un evento SCHEDULED. Para un partido ya LIVE/FINAL, con
    # corte de datos posterior al inicio o sin hora de inicio, no se produce
    # ninguna probabilidad (fail-closed, mismo estado que "sin modelo").
    context_violations = preevent_violations(
        event_start_time=record.start_time,
        status=record.status,
        data_cutoff_timestamp=data_cutoff_timestamp,
    )

    if loaded_artifact is None or context_violations:
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
