"""Métricas de calibración para backtesting (Paso 9). Ver PLAN_PHASE2.md
§10 y el Design Proposal explícitamente aprobado antes de esta
implementación.

Funciones puras `(y_true, y_pred) -> métrica` -- no conocen
`HistoryRepository`, `NormalizedRecord` ni ningún modelo concreto (mismo
principio de agnosticismo de `dataset.py`/`splitter.py`). Nunca fabrican
un valor cuando la entrada es insuficiente: devuelven `None`.

Extensión aditiva (Fase 3, Paso 3.8, ver FASE3_EXECUTION_PLAN.md y
EVALUATION_LEARNING_SPEC.md §3): `ece`, `clv`, `roi_teorico`, `drawdown`,
`profit_factor` -- misma disciplina que las 4 funciones originales de
Fase 2 (`None` sin muestras, nunca un valor fabricado). Ninguna firma
existente se modifica.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

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


# ---------------------------------------------------------------------
# Extensión aditiva (Fase 3, Paso 3.8) -- EVALUATION_LEARNING_SPEC.md §3
# ---------------------------------------------------------------------


def ece(
    y_true: Sequence[int], y_pred: Sequence[float], n_bins: int = DEFAULT_CALIBRATION_BINS
) -> Optional[float]:
    """Expected Calibration Error: promedio ponderado (por n_samples) de
    |mean_predicted - mean_actual| sobre los buckets de calibration_curve()
    -- reutiliza esa función tal cual, no reimplementa el binning. `None`
    si no hay muestras."""
    if len(y_true) == 0:
        return None
    buckets = calibration_curve(y_true, y_pred, n_bins)
    if not buckets:
        return None
    total = sum(bucket.n_samples for bucket in buckets)
    weighted_error = sum(bucket.n_samples * abs(bucket.mean_predicted - bucket.mean_actual) for bucket in buckets)
    return weighted_error / total


def clv(entry_price: float, closing_price: float) -> Optional[float]:
    """Closing Line Value de una sola observación = closing_price -
    entry_price (precio ~ probabilidad implícita en un contrato binario
    -- un cierre más alto que la entrada significa que el mercado se
    movió a favor del lado comprado). `None` si cualquiera de los dos
    precios está fuera de [0,1] -- nunca se clampa (mismo principio no
    negociable de `market_pricing.py`, Fase 2, §7). Agregación (media/
    percentiles por horizonte) es responsabilidad del llamador, esta
    función es puramente una observación individual."""
    if entry_price is None or closing_price is None:
        return None
    if not (0.0 <= entry_price <= 1.0) or not (0.0 <= closing_price <= 1.0):
        return None
    return closing_price - entry_price


def roi_teorico(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """pairs = [(stake, payout_neto), ...] -- ROI teórico como
    sum(payout_neto) / sum(stake), si se hubiera apostado exactamente lo
    indicado por cada señal ENTER. `None` si no hay pares o si la suma
    de stakes es <= 0 (no se puede dividir por una base inválida)."""
    if not pairs:
        return None
    total_stake = sum(stake for stake, _ in pairs)
    if total_stake <= 0:
        return None
    total_payout_neto = sum(payout_neto for _, payout_neto in pairs)
    return total_payout_neto / total_stake


def drawdown(equity_curve: Sequence[float]) -> Optional[float]:
    """Máxima caída peak-to-trough ABSOLUTA (mismas unidades que
    equity_curve, no un porcentaje -- evita asumir una normalización no
    pedida) de una curva de equity teórica. `None` si la curva está
    vacía."""
    if not equity_curve:
        return None
    peak = equity_curve[0]
    max_drop = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drop = peak - value
        if drop > max_drop:
            max_drop = drop
    return max_drop


def profit_factor(gains: Sequence[float], losses: Sequence[float]) -> Optional[float]:
    """sum(gains) / abs(sum(losses)). `None` si losses está vacío o su
    suma es 0 (no se puede dividir por una base inválida) -- mismo
    principio que roi_teorico."""
    if not losses:
        return None
    total_losses = sum(losses)
    if total_losses == 0:
        return None
    return sum(gains) / abs(total_losses)
