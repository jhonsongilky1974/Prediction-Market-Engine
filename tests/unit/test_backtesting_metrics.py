"""Tests de `src/backtesting/metrics.py` (Paso 9): funciones puras de
calibración, sin conocimiento de HistoryRepository/modelo alguno.

Extendido en Fase 3, Paso 3.8 (ver EVALUATION_LEARNING_SPEC.md §3) con
`ece`/`clv`/`roi_teorico`/`drawdown`/`profit_factor` -- mismo archivo,
para mantener paridad con las 4 funciones originales; ninguno de los
tests de arriba se modificó."""
from __future__ import annotations

import pytest

from src.backtesting.metrics import (
    accuracy_metric,
    brier_score,
    calibration_curve,
    clv,
    drawdown,
    ece,
    log_loss_metric,
    profit_factor,
    roi_teorico,
)


# ---------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------


def test_brier_score_exact_value():
    y_true = [1, 0, 1, 0]
    y_pred = [0.8, 0.2, 0.4, 0.6]
    expected = ((0.8 - 1) ** 2 + (0.2 - 0) ** 2 + (0.4 - 1) ** 2 + (0.6 - 0) ** 2) / 4
    assert brier_score(y_true, y_pred) == pytest.approx(expected)


def test_brier_score_perfect_predictions_is_zero():
    assert brier_score([1, 0, 1], [1.0, 0.0, 1.0]) == pytest.approx(0.0)


def test_brier_score_none_when_empty():
    assert brier_score([], []) is None


# ---------------------------------------------------------------------
# log_loss_metric
# ---------------------------------------------------------------------


def test_log_loss_metric_exact_value_matches_manual_formula():
    import math

    y_true = [1, 0]
    y_pred = [0.9, 0.1]
    expected = -(math.log(0.9) + math.log(0.9)) / 2
    assert log_loss_metric(y_true, y_pred) == pytest.approx(expected)


def test_log_loss_metric_computes_even_with_single_class_present():
    """`labels=[0, 1]` explícito (mismo patrón de Paso 5b) evita el
    ValueError que sklearn lanzaría de otro modo cuando `y_true` solo
    contiene una clase -- el fold igual reporta un log_loss válido contra
    el espacio de clases conocido del problema, nunca None por esto."""
    result = log_loss_metric([1, 1, 1], [0.9, 0.8, 0.7])
    assert result is not None
    assert result > 0


def test_log_loss_metric_none_when_empty():
    assert log_loss_metric([], []) is None


# ---------------------------------------------------------------------
# accuracy_metric
# ---------------------------------------------------------------------


def test_accuracy_metric_exact_value():
    y_true = [1, 0, 1, 0]
    y_pred = [0.8, 0.2, 0.3, 0.4]  # 3ra predicción incorrecta (0.3 < 0.5 pero label=1)
    assert accuracy_metric(y_true, y_pred) == pytest.approx(0.75)


def test_accuracy_metric_respects_custom_threshold():
    y_true = [1, 1]
    y_pred = [0.55, 0.58]
    assert accuracy_metric(y_true, y_pred, threshold=0.5) == pytest.approx(1.0)
    assert accuracy_metric(y_true, y_pred, threshold=0.6) == pytest.approx(0.0)


def test_accuracy_metric_none_when_empty():
    assert accuracy_metric([], []) is None


# ---------------------------------------------------------------------
# calibration_curve
# ---------------------------------------------------------------------


def test_calibration_curve_buckets_assignment_exact():
    y_true = [1, 1, 0, 0]
    y_pred = [0.05, 0.15, 0.85, 0.95]  # cae en buckets 0, 1, 8, 9 de 10

    buckets = calibration_curve(y_true, y_pred, n_bins=10)

    assert len(buckets) == 4
    lo_bounds = sorted(b.bin_lo for b in buckets)
    assert lo_bounds == pytest.approx([0.0, 0.1, 0.8, 0.9])
    for b in buckets:
        assert b.n_samples == 1


def test_calibration_curve_groups_multiple_samples_per_bucket():
    y_true = [1, 0, 1]
    y_pred = [0.61, 0.64, 0.69]  # los 3 caen en el bucket [0.6, 0.7)

    buckets = calibration_curve(y_true, y_pred, n_bins=10)

    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.bin_lo == pytest.approx(0.6)
    assert bucket.bin_hi == pytest.approx(0.7)
    assert bucket.n_samples == 3
    assert bucket.mean_predicted == pytest.approx((0.61 + 0.64 + 0.69) / 3)
    assert bucket.mean_actual == pytest.approx((1 + 0 + 1) / 3)


def test_calibration_curve_p_equals_one_falls_in_last_bin_not_overflow():
    buckets = calibration_curve([1], [1.0], n_bins=10)
    assert len(buckets) == 1
    assert buckets[0].bin_lo == pytest.approx(0.9)
    assert buckets[0].bin_hi == pytest.approx(1.0)


def test_calibration_curve_empty_buckets_are_omitted():
    buckets = calibration_curve([1, 0], [0.05, 0.95], n_bins=10)
    assert len(buckets) == 2  # nunca 10 -- los 8 buckets vacíos no se rellenan


def test_calibration_curve_empty_input_returns_empty_list():
    assert calibration_curve([], []) == []


# =========================================================================
# Extensión Fase 3, Paso 3.8 (EVALUATION_LEARNING_SPEC.md §3)
# =========================================================================

# ---------------------------------------------------------------------
# ece
# ---------------------------------------------------------------------


def test_ece_exact_value_single_bucket():
    y_true = [1, 0, 1]
    y_pred = [0.61, 0.64, 0.69]  # mismo dataset que test_calibration_curve_groups...
    mean_predicted = (0.61 + 0.64 + 0.69) / 3
    mean_actual = (1 + 0 + 1) / 3
    expected = abs(mean_predicted - mean_actual)
    assert ece(y_true, y_pred) == pytest.approx(expected)


def test_ece_weighted_across_multiple_buckets():
    y_true = [1, 1, 0, 0]
    y_pred = [0.05, 0.15, 0.85, 0.95]  # 4 buckets de 1 muestra cada uno
    # cada bucket: |mean_predicted - mean_actual| = 0.95, 0.85, 0.85, 0.95
    expected = (0.95 + 0.85 + 0.85 + 0.95) / 4
    assert ece(y_true, y_pred) == pytest.approx(expected)


def test_ece_none_when_empty():
    assert ece([], []) is None


# ---------------------------------------------------------------------
# clv
# ---------------------------------------------------------------------


def test_clv_exact_value():
    assert clv(entry_price=0.55, closing_price=0.62) == pytest.approx(0.07)


def test_clv_negative_when_price_moved_against_entry():
    assert clv(entry_price=0.60, closing_price=0.50) == pytest.approx(-0.10)


def test_clv_none_when_entry_price_out_of_range():
    assert clv(entry_price=1.5, closing_price=0.5) is None


def test_clv_none_when_closing_price_out_of_range():
    assert clv(entry_price=0.5, closing_price=-0.1) is None


def test_clv_none_when_price_is_none():
    assert clv(entry_price=None, closing_price=0.5) is None
    assert clv(entry_price=0.5, closing_price=None) is None


def test_clv_never_clamped():
    """Documentación ejecutable del invariante -- ver market_pricing.py
    §7, mismo principio reutilizado aquí."""
    assert clv(entry_price=1.5, closing_price=0.5) is None  # nunca se clampa a 1.0


# ---------------------------------------------------------------------
# roi_teorico
# ---------------------------------------------------------------------


def test_roi_teorico_exact_value():
    pairs = [(1.0, 0.5), (1.0, -0.3), (2.0, 1.0)]
    assert roi_teorico(pairs) == pytest.approx(0.3)


def test_roi_teorico_none_when_empty():
    assert roi_teorico([]) is None


def test_roi_teorico_none_when_total_stake_is_zero():
    assert roi_teorico([(0.0, 5.0)]) is None


def test_roi_teorico_none_when_total_stake_is_negative():
    assert roi_teorico([(-1.0, 5.0)]) is None


# ---------------------------------------------------------------------
# drawdown
# ---------------------------------------------------------------------


def test_drawdown_exact_value():
    equity_curve = [100.0, 120.0, 90.0, 130.0, 80.0]
    assert drawdown(equity_curve) == pytest.approx(50.0)


def test_drawdown_zero_for_monotonically_increasing_curve():
    assert drawdown([100.0, 110.0, 120.0]) == pytest.approx(0.0)


def test_drawdown_none_when_empty():
    assert drawdown([]) is None


# ---------------------------------------------------------------------
# profit_factor
# ---------------------------------------------------------------------


def test_profit_factor_exact_value():
    gains = [10.0, 20.0, 5.0]
    losses = [-5.0, -10.0]
    assert profit_factor(gains, losses) == pytest.approx(35.0 / 15.0)


def test_profit_factor_none_when_losses_empty():
    assert profit_factor([10.0], []) is None


def test_profit_factor_none_when_losses_sum_to_zero():
    assert profit_factor([10.0], [5.0, -5.0]) is None
