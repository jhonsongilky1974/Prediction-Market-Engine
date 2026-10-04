"""Contrato determinista de veredicto del calibrador de tenis (ECE/Brier,
τ = 1e-4). Ver `governance/calibration/README.md`.

Funciones PURAS: sin I/O, sin reloj, sin estado global (mismo principio de
`TEMPORAL_REPRODUCIBILITY_SPEC.md` §3). Son la única definición del criterio
de §6 de `CALIBRATION_SPEC.md` tras el preregistro: no existe ningún otro
camino que declare "cumplido".

Definiciones (menor es mejor en ECE y en Brier):
    delta_ECE   = raw_ECE   - calibrated_ECE      # > 0  ⇒ el calibrador mejora el ECE
    delta_Brier = raw_Brier - calibrated_Brier    # > 0  ⇒ el calibrador mejora el Brier

Fase 1 (partición de validación, `evaluate_validation`):
    ERROR                 métricas ausentes/NaN/infinitas/fuera de [0, 1], conteo inválido
    INCONCLUSO            entrenamiento sin completar, o n_validation < 30 (mínimo operativo)
    RECHAZADO             cualquier delta < -τ (deterioro)
    INCONCLUSO            ambos |delta| <= τ (efecto nulo)
    ELEGIBLE_PRELIMINAR   ningún delta < -τ y al menos uno > τ

Fase 2 (veto del test, `evaluate_test_veto`): SOLO si la fase 1 dio
ELEGIBLE_PRELIMINAR; el test se obtiene mediante un proveedor perezoso que
en cualquier otro caso NO se invoca. El veto nunca eleva un resultado:
    ERROR                 datos o métricas inválidos del test
    INCONCLUSO            n_test < 30
    RECHAZADO             cualquier delta_test < -τ
    ELEGIBLE              en otro caso (no deteriora en test)

Determinismo en los bordes de τ: los deltas se calculan en `Decimal` sobre la
representación más corta de cada `float` (`repr`), de modo que una diferencia
decimal de exactamente 1e-4 es EXACTAMENTE τ (empate), sin ruido binario.
Escalares NumPy admitidos (convertidos a `float`/`int` de Python antes de validar):
`numpy.floating` e `numpy.integer`; se rechazan `numpy.bool_`, `Decimal`, `Fraction`,
`bool`, texto y cualquier otro tipo (resultado ERROR).

Procedencia: `evaluate_test_veto` solo acepta un resultado preliminar producido por
`evaluate_validation` (lleva una marca interna de procedencia); uno fabricado a mano da
ERROR y NO lee el test.

Estados distintos que NUNCA deben confundirse:
    * cumple el mínimo operativo -> n >= 30 y datos válidos (precondición, no veredicto);
    * ELEGIBLE -> puede PROPONERSE para promoción; NO demuestra mejora estadística;
    * demuestra mejora estadística -> no definido ni alcanzable con el repositorio actual;
    * PROMOVIDO -> solo por autorización humana vía PR sobre `config/model_registry.json`.
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional

TAU = 1e-4
N_MIN_EVENTS = 30  # mínimo operativo (MIN_PARTITION_EVENTS de la política); NO es garantía estadística

_INCOMPLETE_TRAINING_STATES = ("INSUFFICIENT_HISTORY", "MODEL_NOT_TRAINED")
_PHASE1_ORIGIN = object()  # marca interna: solo `evaluate_validation` la pone


class Verdict(str, Enum):
    ERROR = "ERROR"
    INCONCLUSO = "INCONCLUSO"
    RECHAZADO = "RECHAZADO"
    ELEGIBLE_PRELIMINAR = "ELEGIBLE_PRELIMINAR"
    ELEGIBLE = "ELEGIBLE"


@dataclass(frozen=True)
class SplitMetrics:
    """Métricas de UNA partición: crudas y calibradas, sobre los mismos eventos."""

    raw_ece: Any
    calibrated_ece: Any
    raw_brier: Any
    calibrated_brier: Any
    n_events: Any


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    reason: str
    delta_ece: Optional[float] = None
    delta_brier: Optional[float] = None
    origin: Any = field(default=None, repr=False, compare=False)


def _is_python_or_numpy_scalar(value: Any) -> bool:
    return isinstance(value, (int, float)) or type(value).__module__ == "numpy"


def _as_float(value: Any, upper: Optional[float] = 1.0) -> Optional[float]:
    """`float` finito en [0, upper] o `None`. Admite int/float de Python y `numpy.floating`/`numpy.integer`."""
    if isinstance(value, bool) or not _is_python_or_numpy_scalar(value) or not isinstance(value, numbers.Real):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(converted) or converted < 0.0 or (upper is not None and converted > upper):
        return None
    return converted


def _as_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not _is_python_or_numpy_scalar(value) or not isinstance(value, numbers.Integral):
        return None
    converted = int(value)
    return converted if converted >= 0 else None


def _dec(value: float) -> Decimal:
    """Decimal EXACTO de la representación más corta del float (determinista entre plataformas)."""
    return Decimal(repr(value))


class _Normalized:
    __slots__ = ("raw_ece", "cal_ece", "raw_brier", "cal_brier", "n", "tau", "n_min")


def _normalize(metrics: Any, tau: Any, n_min: Any):
    """`(_Normalized, None)` o `(None, motivo)`."""
    if not isinstance(metrics, SplitMetrics):
        return None, "métricas ausentes (no es un SplitMetrics)"
    out = _Normalized()
    for name, attr in (
        ("raw_ece", "raw_ece"), ("calibrated_ece", "cal_ece"), ("raw_brier", "raw_brier"), ("calibrated_brier", "cal_brier"),
    ):
        raw_value = getattr(metrics, name)
        converted = _as_float(raw_value)
        if converted is None:
            return None, f"métrica inválida o ausente: {name}={raw_value!r} (se exige un número finito en [0, 1])"
        setattr(out, attr, converted)
    out.n = _as_count(metrics.n_events)
    if out.n is None:
        return None, f"conteo de eventos inválido: n_events={metrics.n_events!r}"
    out.tau = _as_float(tau, upper=None)
    if out.tau is None:
        return None, f"tau inválida: {tau!r}"
    out.n_min = _as_count(n_min)
    if out.n_min is None:
        return None, f"n_min inválido: {n_min!r}"
    return out, None


def _classify(norm: _Normalized) -> tuple:
    """`(estado, delta_ece, delta_brier)` con estado en {'deterioro', 'nulo', 'mejora'}; deltas en Decimal."""
    d_ece = _dec(norm.raw_ece) - _dec(norm.cal_ece)
    d_brier = _dec(norm.raw_brier) - _dec(norm.cal_brier)
    tau = _dec(norm.tau)
    if d_ece < -tau or d_brier < -tau:
        return "deterioro", d_ece, d_brier
    if abs(d_ece) <= tau and abs(d_brier) <= tau:
        return "nulo", d_ece, d_brier
    return "mejora", d_ece, d_brier  # ningún delta < -tau y al menos uno > tau


def _result(verdict: Verdict, reason: str, d_ece=None, d_brier=None, origin=None) -> VerdictResult:
    return VerdictResult(
        verdict, reason,
        None if d_ece is None else float(d_ece), None if d_brier is None else float(d_brier), origin,
    )


def evaluate_validation(
    metrics: SplitMetrics,
    training_status: Optional[str] = None,
    tau: float = TAU,
    n_min: int = N_MIN_EVENTS,
) -> VerdictResult:
    """Fase 1: veredicto sobre la partición de validación (OOF)."""
    norm, problem = _normalize(metrics, tau, n_min)
    if norm is None:
        return _result(Verdict.ERROR, problem, origin=_PHASE1_ORIGIN)
    if training_status in _INCOMPLETE_TRAINING_STATES:
        return _result(Verdict.INCONCLUSO, f"entrenamiento sin completar ({training_status})", origin=_PHASE1_ORIGIN)
    if norm.n < norm.n_min:
        return _result(
            Verdict.INCONCLUSO, f"n_validation={norm.n} < {norm.n_min}: no se alcanza el mínimo operativo", origin=_PHASE1_ORIGIN
        )
    state, d_ece, d_brier = _classify(norm)
    detail = f"delta_ECE={d_ece}, delta_Brier={d_brier}"
    if state == "deterioro":
        return _result(Verdict.RECHAZADO, f"deterioro mayor que tau={tau}: {detail}", d_ece, d_brier, _PHASE1_ORIGIN)
    if state == "nulo":
        return _result(Verdict.INCONCLUSO, f"efecto nulo dentro de tau={tau}: {detail}", d_ece, d_brier, _PHASE1_ORIGIN)
    return _result(
        Verdict.ELEGIBLE_PRELIMINAR, f"sin deterioro y con mejora mayor que tau={tau}: {detail}", d_ece, d_brier, _PHASE1_ORIGIN
    )


def evaluate_test_veto(
    preliminary: VerdictResult,
    test_metrics_provider: Callable[[], SplitMetrics],
    tau: float = TAU,
    n_min: int = N_MIN_EVENTS,
) -> VerdictResult:
    """Fase 2: veto del test. `test_metrics_provider` SOLO se invoca si `preliminary` es ELEGIBLE_PRELIMINAR
    y procede de `evaluate_validation`; con cualquier otro estado se devuelve `preliminary` sin tocar el
    test (nunca rescata ni eleva); un resultado sin esa procedencia da ERROR y tampoco lee el test."""
    if not isinstance(preliminary, VerdictResult) or preliminary.origin is not _PHASE1_ORIGIN:
        return VerdictResult(
            Verdict.ERROR, "resultado preliminar ausente o sin procedencia de evaluate_validation (no se lee el test)"
        )
    if preliminary.verdict != Verdict.ELEGIBLE_PRELIMINAR:
        return preliminary
    metrics = test_metrics_provider()
    norm, problem = _normalize(metrics, tau, n_min)
    if norm is None:
        return _result(Verdict.ERROR, f"test: {problem}")
    if norm.n < norm.n_min:
        return _result(Verdict.INCONCLUSO, f"n_test={norm.n} < {norm.n_min}: el veto no puede confirmar el candidato")
    state, d_ece, d_brier = _classify(norm)
    if state == "deterioro":
        return _result(
            Verdict.RECHAZADO,
            f"veto del test: deterioro mayor que tau={tau}: delta_ECE={d_ece}, delta_Brier={d_brier}",
            d_ece, d_brier,
        )
    return _result(
        Verdict.ELEGIBLE,
        "el test no deteriora ninguna métrica más que tau; ELEGIBLE no demuestra mejora ni autoriza promoción",
        d_ece, d_brier,
    )
