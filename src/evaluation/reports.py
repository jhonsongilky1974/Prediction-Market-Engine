"""Comparación de baselines MLB (Paso 10). Ver PLAN_PHASE2.md §3/§12
("comparación Baseline 0 vs 1 vs 2") y el Design Proposal explícitamente
aprobado antes de esta implementación.

Los tres baselines:
  - Baseline 0 = el mercado mismo (`BacktestRow.p_market_yes` usado
    directamente como "predicción" -- no es un modelo entrenado, no pasa
    por `walk_forward_splits`).
  - Baseline 1 = `src/models/mlb_baseline.py` (regresión logística, Paso
    5a/5b).
  - Baseline 2 = `src/models/mlb_elo.py` (Elo, Paso 6).

Este módulo es AGNÓSTICO al modelo -- no importa `mlb_baseline` ni
`mlb_elo` (mismo principio de `src/backtesting/`, Paso 9). Quien invoque
`compare_baselines` pasa `fit_fn`/`predict_fn` ya adaptados a la firma
genérica de abajo.

Invariante central, aprobado explícitamente: los tres baselines se
evalúan sobre el MISMO universo de filas -- un único recorrido de
`walk_forward_splits` (Paso 9, sin modificar) produce los folds; dentro de
cada fold (antes de avanzar al siguiente, respetando el contrato de uso
de `splitter.py`), se entrenan Baseline 1 y Baseline 2 sobre el mismo
`fold.train_repository`, y Baseline 0 se lee directamente de
`fold.test_rows` -- nunca en pasadas separadas sobre universos distintos.

Solo en memoria (dataclasses) -- sin persistencia, sin dependencias de
visualización (Design Proposal, Ambigüedades D/E).
"""
from __future__ import annotations

import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.backtesting.dataset import BacktestDataset, BacktestRow
from src.backtesting.metrics import (
    CalibrationBucket,
    accuracy_metric,
    brier_score,
    calibration_curve,
    log_loss_metric,
)
from src.backtesting.splitter import walk_forward_splits
from src.models.base import ModelStatus, PModelOutput
from src.signals.edge import compute_edge_yes
from src.storage.history_repository import HistoryRepository

# Igual a DEFAULT_MIN_TRAINING_SAMPLES (src/models/mlb_baseline.py, Paso
# 5b) -- valor DUPLICADO deliberadamente, no importado, para que este
# módulo permanezca agnóstico y no dependa de mlb_baseline.py. Es el mayor
# de los dos umbrales ya aprobados (300 de logreg vs 50 de Elo): usar el
# umbral menor haría que Baseline 1 casi siempre reportara
# INSUFFICIENT_HISTORY en cada fold. Configurable -- este es solo el
# default documentado (Design Proposal Paso 10 §1).
DEFAULT_MIN_TRAIN_SIZE_FOR_COMPARISON = 300

# Heurística de ingeniería NUEVA (~una semana de calendario MLB completo),
# no calibrada -- mismo espíritu que otras constantes PROVISIONAL ya
# existentes (p.ej. _MARKET_LIQUIDITY_TARGET en quality_score.py).
# Configurable -- este es solo el default documentado (Design Proposal
# Paso 10 §1).
DEFAULT_TEST_BLOCK_SIZE_FOR_COMPARISON = 30

FitFn = Callable[[HistoryRepository, Path], Tuple[ModelStatus, Optional[Any], List[str]]]
PredictFn = Callable[[BacktestRow, Any], Optional[float]]

_BASELINE_0_NAME = "baseline_0_market"
_BASELINE_1_NAME = "baseline_1_logreg"
_BASELINE_2_NAME = "baseline_2_elo"


@dataclass
class BaselineReport:
    baseline_name: str
    n_predictions: int
    brier: Optional[float]
    log_loss: Optional[float]
    accuracy: Optional[float]
    calibration: List[CalibrationBucket] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class SegmentedMetric:
    segment_label: str
    n_samples: int
    brier: Optional[float]
    accuracy: Optional[float]


@dataclass
class BaselineComparisonReport:
    baseline_reports: Dict[str, BaselineReport] = field(default_factory=dict)
    # SOLO baseline_1/baseline_2 -- Baseline 0 se excluye a propósito: su
    # EDGE es 0 por definición (P_model := P_market), no hay nada que
    # segmentar (Design Proposal Paso 10, Ambigüedad B).
    edge_segments: Dict[str, List[SegmentedMetric]] = field(default_factory=dict)
    confidence_segments: Dict[str, List[SegmentedMetric]] = field(default_factory=dict)
    liquidity_segments: Dict[str, List[SegmentedMetric]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _build_baseline_report(baseline_name: str, pairs: List[Tuple[BacktestRow, float]]) -> BaselineReport:
    if not pairs:
        return BaselineReport(
            baseline_name=baseline_name,
            n_predictions=0,
            brier=None,
            log_loss=None,
            accuracy=None,
            calibration=[],
            warnings=[f"{baseline_name}: 0 predicciones disponibles"],
        )
    y_true = [row.label for row, _ in pairs]
    y_pred = [p for _, p in pairs]
    return BaselineReport(
        baseline_name=baseline_name,
        n_predictions=len(pairs),
        brier=brier_score(y_true, y_pred),
        log_loss=log_loss_metric(y_true, y_pred),
        accuracy=accuracy_metric(y_true, y_pred),
        calibration=calibration_curve(y_true, y_pred),
        warnings=[],
    )


def _edge_yes_for_prediction(row: BacktestRow, p_model_yes: float) -> Optional[float]:
    """Reutiliza `compute_edge_yes` (Paso 8) TAL CUAL -- nunca recalcula
    `p_model - p_market` inline -- construyendo el `PModelOutput` mínimo
    que ese contrato exige."""
    model_output = PModelOutput(
        p_model_yes=p_model_yes,
        model_version="paso10_evaluation",
        model_status=ModelStatus.TRAINED,
        feature_set_version=row.feature_set_version,
        prediction_timestamp=row.data_cutoff_timestamp,
        data_cutoff_timestamp=row.data_cutoff_timestamp,
    )
    return compute_edge_yes(model_output, row.record)


def _segment_pairs(
    pairs: List[Tuple[BacktestRow, float]],
    value_fn: Callable[[BacktestRow, float], Optional[float]],
    lo: float,
    hi: float,
    width: float,
) -> List[SegmentedMetric]:
    """Segmentación genérica de ancho fijo, clamping a los extremos --
    mismo estilo que `calibration_curve` (Paso 9). Filas sin el valor
    calculable se omiten (nunca se fabrica), consistente en toda la Fase
    2."""
    n_bins = round((hi - lo) / width)
    buckets: Dict[int, List[Tuple[int, float]]] = defaultdict(list)

    for row, p in pairs:
        value = value_fn(row, p)
        if value is None:
            continue
        idx = int((value - lo) / width)
        idx = max(0, min(idx, n_bins - 1))
        buckets[idx].append((row.label, p))

    result: List[SegmentedMetric] = []
    for idx in sorted(buckets):
        items = buckets[idx]
        bin_lo = lo + idx * width
        bin_hi = bin_lo + width
        if idx == 0:
            label = f"< {bin_hi:.2f}"
        elif idx == n_bins - 1:
            label = f">= {bin_lo:.2f}"
        else:
            label = f"[{bin_lo:.2f}, {bin_hi:.2f})"
        y_true = [label_value for label_value, _ in items]
        y_pred = [p for _, p in items]
        result.append(
            SegmentedMetric(
                segment_label=label,
                n_samples=len(items),
                brier=brier_score(y_true, y_pred),
                accuracy=accuracy_metric(y_true, y_pred),
            )
        )
    return result


def segment_by_edge(pairs: List[Tuple[BacktestRow, float]]) -> List[SegmentedMetric]:
    """EDGE_YES únicamente (no EDGE_NO en esta iteración, ver Design
    Proposal). 12 buckets de ancho 0.05 en [-0.30, 0.30], extremos
    abiertos. No aplicable a Baseline 0 -- ver `BaselineComparisonReport`."""
    return _segment_pairs(pairs, _edge_yes_for_prediction, lo=-0.30, hi=0.30, width=0.05)


def segment_by_confidence(pairs: List[Tuple[BacktestRow, float]]) -> List[SegmentedMetric]:
    """`quality_score.confidence` (Paso 7), ya en [0,1]. 10 buckets de
    ancho fijo, mismo esquema que `calibration_curve`."""
    return _segment_pairs(pairs, lambda row, _p: row.quality_score.confidence, lo=0.0, hi=1.0, width=0.1)


def segment_by_liquidity(pairs: List[Tuple[BacktestRow, float]]) -> List[SegmentedMetric]:
    """`quality_score.components["market_liquidity"]` (Paso 7), ya en
    [0,1]. 10 buckets de ancho fijo, mismo esquema que `calibration_curve`."""
    return _segment_pairs(
        pairs, lambda row, _p: row.quality_score.components.get("market_liquidity"), lo=0.0, hi=1.0, width=0.1
    )


def compare_baselines(
    history_repository: HistoryRepository,
    dataset: BacktestDataset,
    fit_fn_baseline_1: FitFn,
    predict_fn_baseline_1: PredictFn,
    fit_fn_baseline_2: FitFn,
    predict_fn_baseline_2: PredictFn,
    min_train_size: int = DEFAULT_MIN_TRAIN_SIZE_FOR_COMPARISON,
    test_block_size: int = DEFAULT_TEST_BLOCK_SIZE_FOR_COMPARISON,
) -> BaselineComparisonReport:
    """Orquesta la comparación Baseline 0 vs 1 vs 2 (PLAN_PHASE2.md §12,
    Paso 10) sobre el MISMO universo de filas -- un único recorrido de
    `walk_forward_splits` (Paso 9). `min_train_size`/`test_block_size` son
    configurables; los defaults documentados arriba son los propuestos y
    aprobados en el Design Proposal, no valores fijos ocultos.

    `fit_fn_baseline_1`/`fit_fn_baseline_2` reciben `(fold.train_repository,
    models_dir_temporal)` y devuelven `(ModelStatus, artefacto_o_None,
    warnings)`, donde `artefacto` es exactamente lo que el `predict_fn`
    correspondiente espera recibir -- para Elo, `train_mlb_elo_model`
    devuelve directamente ese artefacto; para el baseline logreg,
    `train_mlb_baseline_model` solo devuelve la metadata (`MlbTrainedArtifact`)
    y el llamador debe recargar el modelo vía
    `src.models.registry.load_latest_mlb_artifact` dentro de su propio
    `fit_fn_baseline_1` antes de devolverlo (mismo patrón ya usado por
    `scripts/train_mlb_model.py`) -- este glue es responsabilidad del
    adaptador, no de este módulo, que permanece agnóstico. `predict_fn_baseline_1`/
    `predict_fn_baseline_2` reciben `(BacktestRow, artefacto)` y devuelven
    `Optional[float]` (`p_model_yes`) ya normalizado -- el llamador adapta
    `predict_mlb_baseline_from_features`/`predict_mlb_elo` a esta forma.

    Sin volumen suficiente para ningún fold, o sin ninguna predicción
    válida en los tres baselines: devuelve un reporte válido con
    `n_predictions=0` en cada uno, nunca una excepción ni un número
    fabricado."""
    warnings: List[str] = []
    pairs_0: List[Tuple[BacktestRow, float]] = []
    pairs_1: List[Tuple[BacktestRow, float]] = []
    pairs_2: List[Tuple[BacktestRow, float]] = []

    for fold in walk_forward_splits(history_repository, dataset, min_train_size, test_block_size):
        for row in fold.test_rows:
            if row.p_market_yes is not None:
                pairs_0.append((row, row.p_market_yes))

        with tempfile.TemporaryDirectory(prefix="pme_eval_baseline1_") as tmp1:
            status1, artifact1, w1 = fit_fn_baseline_1(fold.train_repository, Path(tmp1))
            warnings.extend(w1)
            if status1 == ModelStatus.TRAINED:
                for row in fold.test_rows:
                    p = predict_fn_baseline_1(row, artifact1)
                    if p is not None:
                        pairs_1.append((row, p))

        with tempfile.TemporaryDirectory(prefix="pme_eval_baseline2_") as tmp2:
            status2, artifact2, w2 = fit_fn_baseline_2(fold.train_repository, Path(tmp2))
            warnings.extend(w2)
            if status2 == ModelStatus.TRAINED:
                for row in fold.test_rows:
                    p = predict_fn_baseline_2(row, artifact2)
                    if p is not None:
                        pairs_2.append((row, p))

    if not (pairs_0 or pairs_1 or pairs_2):
        warnings.append(
            "compare_baselines: 0 predicciones en los tres baselines (sin folds posibles o sin volumen suficiente)"
        )

    baseline_reports = {
        _BASELINE_0_NAME: _build_baseline_report(_BASELINE_0_NAME, pairs_0),
        _BASELINE_1_NAME: _build_baseline_report(_BASELINE_1_NAME, pairs_1),
        _BASELINE_2_NAME: _build_baseline_report(_BASELINE_2_NAME, pairs_2),
    }

    edge_segments = {
        _BASELINE_1_NAME: segment_by_edge(pairs_1),
        _BASELINE_2_NAME: segment_by_edge(pairs_2),
    }

    confidence_segments = {
        _BASELINE_0_NAME: segment_by_confidence(pairs_0),
        _BASELINE_1_NAME: segment_by_confidence(pairs_1),
        _BASELINE_2_NAME: segment_by_confidence(pairs_2),
    }

    liquidity_segments = {
        _BASELINE_0_NAME: segment_by_liquidity(pairs_0),
        _BASELINE_1_NAME: segment_by_liquidity(pairs_1),
        _BASELINE_2_NAME: segment_by_liquidity(pairs_2),
    }

    return BaselineComparisonReport(
        baseline_reports=baseline_reports,
        edge_segments=edge_segments,
        confidence_segments=confidence_segments,
        liquidity_segments=liquidity_segments,
        warnings=warnings,
    )
