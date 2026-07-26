"""Métricas de calibración para backtesting (Paso 9). Ver PLAN_PHASE2.md
§10 y el Design Proposal explícitamente aprobado antes de esta
implementación.

Funciones puras `(y_true, y_pred) -> métrica` -- no conocen
`HistoryRepository`, `NormalizedRecord` ni ningún modelo concreto (mismo
principio de agnosticismo de `dataset.py`/`splitter.py`). Nunca fabrican
un valor cuando la entrada es insuficiente: devuelven `None`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

DEFAULT_CALIBRATION_BINS = 10  # aprobado explícitamente por el usuario


def brier_score(y_true: Sequence[int], y_pred: Sequence[float]) -> Optional[float]:
    """Brier score = mean((p_i - y_i)^2). `None` si no hay muestras."""
    n = len(y_true)
    if n == 0:
        return None
    return sum((p - y) ** 2 for y, p in zip(y_true, y_pred)) / n


def log_loss_metric(y_true: Sequence[int], y_pred: Sequence[float]) -> Optional[float]:
    """Log loss binario. `None` si no hay muestras. `labels=[0, 1]`
    explícito (mismo patrón ya usado en Paso 5b para
    `train_mlb_baseline_model`) permite calcularlo igualmente contra el
    espacio de clases conocido del problema aunque el fold contenga una
    sola clase -- el `try/except` que envuelve la llamada queda como
    resguardo defensivo para cualquier otro caso que `sklearn` rechace,
    nunca se fabrica un número cuando no aplica."""
    n = len(y_true)
    if n == 0:
        return None
    from sklearn.metrics import log_loss

    try:
        return float(log_loss(y_true, y_pred, labels=[0, 1]))
    except ValueError:
        return None


def accuracy_metric(y_true: Sequence[int], y_pred: Sequence[float], threshold: float = 0.5) -> Optional[float]:
    """Fracción de predicciones correctas al umbral dado (0.5 por
    defecto, mismo valor ya usado en Paso 5b). `None` si no hay
    muestras."""
    n = len(y_true)
    if n == 0:
        return None
    correct = sum(1 for y, p in zip(y_true, y_pred) if (p >= threshold) == bool(y))
    return correct / n


@dataclass
class CalibrationBucket:
    bin_lo: float
    bin_hi: float
    mean_predicted: float
    mean_actual: float
    n_samples: int


def calibration_curve(
    y_true: Sequence[int], y_pred: Sequence[float], n_bins: int = DEFAULT_CALIBRATION_BINS
) -> List[CalibrationBucket]:
    """Agrupa `y_pred` en `n_bins` buckets de ancho fijo sobre [0, 1] y
    reporta, por bucket con al menos una muestra, la probabilidad predicha
    promedio vs. la tasa real observada -- buckets vacíos se omiten
    (nunca se rellenan con 0/None fabricado)."""
    width = 1.0 / n_bins
    buckets_items: List[List[tuple]] = [[] for _ in range(n_bins)]

    for y, p in zip(y_true, y_pred):
        idx = int(p * n_bins)
        idx = max(0, min(idx, n_bins - 1))
        buckets_items[idx].append((y, p))

    result: List[CalibrationBucket] = []
    for i, items in enumerate(buckets_items):
        if not items:
            continue
        ys = [item[0] for item in items]
        ps = [item[1] for item in items]
        result.append(
            CalibrationBucket(
                bin_lo=i * width,
                bin_hi=(i + 1) * width,
                mean_predicted=sum(ps) / len(ps),
                mean_actual=sum(ys) / len(ys),
                n_samples=len(items),
            )
        )
    return result
