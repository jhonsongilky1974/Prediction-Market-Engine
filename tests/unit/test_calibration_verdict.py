"""Contrato determinista de veredicto (τ = 1e-4; ECE y Brier): fases 1 y 2, fronteras,
precedencias, veto único que nunca eleva y pureza del módulo."""
from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path

import pytest

import src.evaluation.calibration_verdict as verdict_module
from src.evaluation.calibration_verdict import (
    N_MIN_EVENTS,
    TAU,
    SplitMetrics,
    Verdict,
    VerdictResult,
    evaluate_test_veto,
    evaluate_validation,
)

EXACT_TAU = 2.0 ** -14  # potencia de 2: las diferencias de frontera son exactas en coma flotante


def m(raw_ece=0.08, cal_ece=0.08, raw_brier=0.20, cal_brier=0.20, n=73):
    return SplitMetrics(raw_ece, cal_ece, raw_brier, cal_brier, n)


def test_constants_are_the_authorized_values_and_aprobado_does_not_exist():
    assert TAU == 1e-4 and N_MIN_EVENTS == 30
    assert {v.value for v in Verdict} == {"ERROR", "INCONCLUSO", "RECHAZADO", "ELEGIBLE_PRELIMINAR", "ELEGIBLE"}


# --- fase 1: casos de frontera con τ exacta ------------------------------------------------


@pytest.mark.parametrize(
    "d_ece,d_brier,expected",
    [
        (-EXACT_TAU, 0.0, Verdict.INCONCLUSO),            # delta == -tau NO es deterioro; |delta| <= tau => efecto nulo
        (-2 * EXACT_TAU, 0.0, Verdict.RECHAZADO),         # deterioro mayor que tau
        (0.0, -2 * EXACT_TAU, Verdict.RECHAZADO),
        (EXACT_TAU, 0.0, Verdict.INCONCLUSO),             # delta == +tau NO es mejora
        (2 * EXACT_TAU, 0.0, Verdict.ELEGIBLE_PRELIMINAR),
        (0.0, 2 * EXACT_TAU, Verdict.ELEGIBLE_PRELIMINAR),
        (EXACT_TAU, EXACT_TAU, Verdict.INCONCLUSO),       # ambos exactamente en +tau
        (-EXACT_TAU, EXACT_TAU, Verdict.INCONCLUSO),      # ambos dentro de tau
        (2 * EXACT_TAU, -EXACT_TAU, Verdict.ELEGIBLE_PRELIMINAR),  # mejora en una y la otra en el borde (no deteriora)
        (2 * EXACT_TAU, -2 * EXACT_TAU, Verdict.RECHAZADO),        # una mejora no rescata un deterioro
        (-2 * EXACT_TAU, 2 * EXACT_TAU, Verdict.RECHAZADO),
    ],
)
def test_phase1_boundaries_with_exact_tau(d_ece, d_brier, expected):
    metrics = m(raw_ece=0.5, cal_ece=0.5 - d_ece, raw_brier=0.25, cal_brier=0.25 - d_brier)
    assert evaluate_validation(metrics, tau=EXACT_TAU).verdict == expected


@pytest.mark.parametrize(
    "metrics,expected",
    [
        (m(0.0800, 0.0800, 0.2000, 0.2000), Verdict.INCONCLUSO),                 # mejora exactamente cero
        (m(0.0800, 0.0799999999, 0.2000, 0.1999999999), Verdict.INCONCLUSO),     # mejora por redondeo
        (m(0.0800, 0.0800000001, 0.2000, 0.2000), Verdict.INCONCLUSO),           # empeora por ruido de redondeo
        (m(0.0800, 0.0700, 0.2000, 0.2000), Verdict.ELEGIBLE_PRELIMINAR),
        (m(0.0800, 0.0500, 0.2000, 0.1900), Verdict.ELEGIBLE_PRELIMINAR),
        (m(0.0800, 0.0900, 0.2000, 0.1900), Verdict.RECHAZADO),                   # Brier mejora, ECE empeora
        (m(0.0800, 0.0700, 0.2000, 0.2100), Verdict.RECHAZADO),                   # ECE mejora, Brier empeora
        (m(0.0800, 0.0798, 0.2000, 0.2000), Verdict.ELEGIBLE_PRELIMINAR),         # mejora 2e-4 > tau
        (m(0.0800, 0.07995, 0.2000, 0.2000), Verdict.INCONCLUSO),                 # mejora 5e-5 < tau: efecto nulo
    ],
)
def test_phase1_with_default_tau(metrics, expected):
    assert evaluate_validation(metrics).verdict == expected


def test_real_defective_calibrator_values_are_rejected_only_with_enough_events():
    values = dict(raw_ece=0.0681, cal_ece=0.1366, raw_brier=0.1030, cal_brier=0.1184)
    assert evaluate_validation(m(**values, n=24)).verdict == Verdict.INCONCLUSO  # n < 30: no se rechaza ni se aprueba
    assert evaluate_validation(m(**values, n=73)).verdict == Verdict.RECHAZADO


def test_deltas_are_reported_with_the_documented_sign():
    result = evaluate_validation(m(0.0800, 0.0600, 0.2000, 0.1900))
    assert result.delta_ece == pytest.approx(0.02) and result.delta_brier == pytest.approx(0.01)  # positivo = mejora


# --- n mínimo -----------------------------------------------------------------------------------


@pytest.mark.parametrize("n,expected", [(0, Verdict.INCONCLUSO), (29, Verdict.INCONCLUSO), (30, Verdict.RECHAZADO)])
def test_n_below_30_is_inconclusive_even_with_clear_deterioration(n, expected):
    assert evaluate_validation(m(0.05, 0.20, 0.10, 0.30, n=n)).verdict == expected


def test_n_30_with_clear_improvement_is_only_preliminary_never_final():
    assert evaluate_validation(m(0.08, 0.05, 0.20, 0.19, n=30)).verdict == Verdict.ELEGIBLE_PRELIMINAR


@pytest.mark.parametrize("status", ["INSUFFICIENT_HISTORY", "MODEL_NOT_TRAINED"])
def test_incomplete_training_is_inconclusive(status):
    assert evaluate_validation(m(0.08, 0.05, 0.20, 0.19), training_status=status).verdict == Verdict.INCONCLUSO


# --- ERROR ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, -math.inf, -0.1, 1.1, True, "0.1", [0.1]])
@pytest.mark.parametrize("field", ["raw_ece", "cal_ece", "raw_brier", "cal_brier"])
def test_invalid_metrics_are_error(field, bad):
    kwargs = dict(raw_ece=0.08, cal_ece=0.05, raw_brier=0.2, cal_brier=0.19, n=73)
    kwargs[field] = bad
    assert evaluate_validation(m(**kwargs)).verdict == Verdict.ERROR


@pytest.mark.parametrize("n", [-1, 30.0, True, None, "30"])
def test_invalid_event_count_is_error(n):
    assert evaluate_validation(m(0.08, 0.05, 0.20, 0.19, n=n)).verdict == Verdict.ERROR


@pytest.mark.parametrize("tau", [math.nan, math.inf, -1e-4, None, True])
def test_invalid_tau_is_error(tau):
    assert evaluate_validation(m(0.08, 0.05, 0.20, 0.19), tau=tau).verdict == Verdict.ERROR


def test_missing_metrics_object_is_error_and_error_precedes_the_n_gate():
    assert evaluate_validation(None).verdict == Verdict.ERROR
    assert evaluate_validation(m(0.08, math.nan, 0.20, 0.19, n=5)).verdict == Verdict.ERROR  # n<30 no lo enmascara


# --- fase 2: veto del test ---------------------------------------------------------------------


def prelim():
    return evaluate_validation(m(0.08, 0.05, 0.20, 0.19))


class Provider:
    def __init__(self, metrics):
        self.metrics, self.calls = metrics, 0

    def __call__(self):
        self.calls += 1
        return self.metrics


@pytest.mark.parametrize(
    "preliminary",
    [
        evaluate_validation(m(0.08, 0.08, 0.20, 0.20)),                # INCONCLUSO (efecto nulo)
        evaluate_validation(m(0.08, 0.09, 0.20, 0.19)),                # RECHAZADO
        evaluate_validation(m(0.08, math.nan, 0.20, 0.19)),            # ERROR
        evaluate_validation(m(0.08, 0.05, 0.20, 0.19, n=29)),          # INCONCLUSO (n < 30)
        evaluate_validation(m(0.08, 0.05, 0.20, 0.19), training_status="MODEL_NOT_TRAINED"),
    ],
)
def test_test_is_never_read_unless_the_preliminary_is_eligible_and_nothing_is_elevated(preliminary):
    assert preliminary.verdict != Verdict.ELEGIBLE_PRELIMINAR
    provider = Provider(m(0.08, 0.01, 0.20, 0.10, n=100))  # un test espléndido
    result = evaluate_test_veto(preliminary, provider)
    assert provider.calls == 0
    assert result is preliminary  # ni rescata ni eleva


@pytest.mark.parametrize(
    "forged",
    [
        VerdictResult(Verdict.ELEGIBLE_PRELIMINAR, "fabricado a mano"),
        VerdictResult(Verdict.ELEGIBLE, "fabricado a mano"),
        VerdictResult(Verdict.INCONCLUSO, "fabricado a mano"),
        "ELEGIBLE_PRELIMINAR",
    ],
)
def test_f8_hand_made_preliminary_results_are_error_and_never_read_the_test(forged):
    provider = Provider(m(0.08, 0.05, 0.20, 0.19, n=100))
    result = evaluate_test_veto(forged, provider)
    assert result.verdict == Verdict.ERROR and provider.calls == 0


def test_f8_origin_mark_does_not_leak_into_repr_or_equality():
    real = evaluate_validation(m(0.08, 0.05, 0.20, 0.19))
    assert "origin" not in repr(real)
    assert real == VerdictResult(real.verdict, real.reason, real.delta_ece, real.delta_brier)


def test_missing_preliminary_is_error_without_reading_the_test():
    provider = Provider(m())
    assert evaluate_test_veto(None, provider).verdict == Verdict.ERROR
    assert provider.calls == 0


@pytest.mark.parametrize(
    "test_metrics,expected",
    [
        (m(0.08, 0.05, 0.20, 0.19, n=40), Verdict.ELEGIBLE),     # no deteriora
        (m(0.08, 0.08, 0.20, 0.20, n=40), Verdict.ELEGIBLE),     # empate: el test no veta
        (m(0.08, 0.09, 0.20, 0.19, n=40), Verdict.RECHAZADO),    # ECE empeora más que tau
        (m(0.08, 0.05, 0.20, 0.21, n=40), Verdict.RECHAZADO),    # Brier empeora más que tau
        (m(0.08, 0.05, 0.20, 0.19, n=29), Verdict.INCONCLUSO),   # n_test < 30
        (m(0.08, math.nan, 0.20, 0.19, n=40), Verdict.ERROR),
        (m(0.08, 0.05, None, 0.19, n=40), Verdict.ERROR),
        (None, Verdict.ERROR),
    ],
)
def test_veto_outcomes(test_metrics, expected):
    provider = Provider(test_metrics)
    result = evaluate_test_veto(prelim(), provider)
    assert provider.calls == 1  # exactamente una consulta
    assert result.verdict == expected


def test_eligible_message_never_claims_proven_improvement_or_promotion():
    result = evaluate_test_veto(prelim(), Provider(m(0.08, 0.05, 0.20, 0.19, n=40)))
    assert result.verdict == Verdict.ELEGIBLE
    assert "no demuestra mejora" in result.reason and "autoriza promoción" in result.reason


def test_phase1_signature_has_no_test_input_and_veto_receives_only_a_lazy_provider():
    assert list(inspect.signature(evaluate_validation).parameters) == ["metrics", "training_status", "tau", "n_min"]
    assert list(inspect.signature(evaluate_test_veto).parameters) == ["preliminary", "test_metrics_provider", "tau", "n_min"]


# --- pureza -------------------------------------------------------------------------------------


def test_module_is_pure_no_io_clock_or_global_state():
    tree = ast.parse(Path(verdict_module.__file__).read_text(encoding="utf-8"))
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imports <= {"__future__", "math", "numbers", "decimal", "dataclasses", "enum", "typing"}
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"now", "utcnow", "today", "open", "read_text", "write_text"}
    assert not [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Dict, ast.List, ast.Set))]


# --- F7: comparaciones deterministas en los bordes de τ = 1e-4 (aritmética decimal exacta) ---------------------------


@pytest.mark.parametrize(
    "raw,cal,expected",
    [
        (0.08, 0.0799, Verdict.INCONCLUSO),            # delta decimal EXACTO = 1e-4 = tau => empate, no es mejora (en float daría 1.0000000000000286e-4)
        (0.08, 0.0798, Verdict.ELEGIBLE_PRELIMINAR),   # 2e-4 > tau
        (0.0799, 0.08, Verdict.INCONCLUSO),            # delta decimal exacto = -1e-4: no es deterioro
        (0.0798, 0.08, Verdict.RECHAZADO),             # -2e-4 < -tau
        (0.3, 0.2999, Verdict.INCONCLUSO),             # otro par donde la resta binaria cae del lado erróneo
        (0.7, 0.6999, Verdict.INCONCLUSO),
        (0.1, 0.0999, Verdict.INCONCLUSO),
    ],
)
def test_f7_decimal_exact_boundaries_at_the_default_tau(raw, cal, expected):
    assert evaluate_validation(m(raw, cal, 0.20, 0.20)).verdict == expected
    assert evaluate_validation(m(0.20, 0.20, raw, cal)).verdict == expected  # idéntico para Brier


def test_f7_the_same_inputs_always_give_the_same_deltas_and_verdict():
    results = {evaluate_validation(m(0.08, 0.0799, 0.20, 0.20)) for _ in range(5)}
    assert len(results) == 1


# --- F9: escalares NumPy admitidos y rechazados de forma explícita ---------------------------------------------------


def test_f9_numpy_scalars_are_admitted_and_equivalent_to_python_numbers():
    np = pytest.importorskip("numpy")
    plain = evaluate_validation(m(0.08, 0.05, 0.20, 0.19, n=40))
    numpy_metrics = SplitMetrics(np.float64(0.08), np.float64(0.05), np.float64(0.20), np.float64(0.19), np.int64(40))
    assert evaluate_validation(numpy_metrics).verdict == plain.verdict == Verdict.ELEGIBLE_PRELIMINAR
    assert evaluate_validation(numpy_metrics).delta_ece == plain.delta_ece


@pytest.mark.parametrize("bad", ["numpy_bool", "decimal", "fraction", "text", "bool", "numpy_nan", "numpy_inf", "numpy_negative_count"])
def test_f9_other_types_are_rejected_with_error(bad):
    np = pytest.importorskip("numpy")
    from decimal import Decimal
    from fractions import Fraction
    values = {
        "numpy_bool": SplitMetrics(np.bool_(True), 0.05, 0.20, 0.19, 40),
        "decimal": SplitMetrics(Decimal("0.08"), 0.05, 0.20, 0.19, 40),
        "fraction": SplitMetrics(Fraction(2, 25), 0.05, 0.20, 0.19, 40),
        "text": SplitMetrics("0.08", 0.05, 0.20, 0.19, 40),
        "bool": SplitMetrics(True, 0.05, 0.20, 0.19, 40),
        "numpy_nan": SplitMetrics(np.float64("nan"), 0.05, 0.20, 0.19, 40),
        "numpy_inf": SplitMetrics(np.float64("inf"), 0.05, 0.20, 0.19, 40),
        "numpy_negative_count": SplitMetrics(0.08, 0.05, 0.20, 0.19, np.int64(-1)),
    }
    assert evaluate_validation(values[bad]).verdict == Verdict.ERROR
