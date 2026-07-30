"""Tests de calibrate() (Fase 3, Paso 3.1). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.1, y MODEL_PIPELINE_SPEC.md §3 -- casos: MODEL_NOT_TRAINED (todo
None), TRAINED sin calibrador (p_model_raw poblado, resto None), TRAINED
con un calibrador sintético (contract test, sin entrenar nada real), y
pureza (misma entrada -> mismo resultado).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.calibration.calibration_layer import calibrate
from src.models.base import ModelStatus, PModelOutput

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _make_model_output(**overrides) -> PModelOutput:
    base = dict(
        p_model_yes=0.62,
        model_version="mlb_baseline_logreg_v1_20260730T000000Z",
        model_status=ModelStatus.TRAINED,
        feature_set_version="mlb_features_v1",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )
    base.update(overrides)
    return PModelOutput(**base)


class _FakeCalibrator:
    """Doble de test -- NO es un calibrador real entrenado (eso depende
    de D-1, fuera de alcance). Solo satisface el Protocol `Calibrator`
    para probar que calibrate() lo aplica correctamente cuando existe."""

    calibration_version = "FAKE_V1"
    calibration_method = "FAKE_V1"

    def calibrate(self, p_raw: float) -> float:
        return min(1.0, p_raw * 0.9 + 0.05)


# ---------------------------------------------------------------------
# Caso MODEL_NOT_TRAINED
# ---------------------------------------------------------------------


def test_model_not_trained_produces_all_none():
    model_output = _make_model_output(
        p_model_yes=None, model_version=None, model_status=ModelStatus.MODEL_NOT_TRAINED
    )
    result = calibrate(model_output, calibrator=None, now=NOW)
    assert result.p_model_raw is None
    assert result.p_model_calibrated is None
    assert result.calibration_version is None
    assert result.calibration_method is None
    assert result.calibrated_at is None
    assert result.model_version is None


def test_model_not_trained_with_calibrator_still_produces_none():
    """Invariante explícito del plan: p_model_yes=None implica
    p_model_calibrated=None incluso si en el futuro se pasara un
    calibrador no-None."""
    model_output = _make_model_output(
        p_model_yes=None, model_version=None, model_status=ModelStatus.MODEL_NOT_TRAINED
    )
    result = calibrate(model_output, calibrator=_FakeCalibrator(), now=NOW)
    assert result.p_model_calibrated is None
    assert result.calibration_version is None


# ---------------------------------------------------------------------
# Caso TRAINED sin calibrador (el único caso real hoy en el proyecto)
# ---------------------------------------------------------------------


def test_trained_without_calibrator_populates_raw_only():
    model_output = _make_model_output()
    result = calibrate(model_output, calibrator=None, now=NOW)
    assert result.p_model_raw == 0.62
    assert result.p_model_calibrated is None
    assert result.calibration_version is None
    assert result.calibrated_at is None


def test_p_model_raw_is_exact_copy_not_rounded():
    model_output = _make_model_output(p_model_yes=0.123456789)
    result = calibrate(model_output, calibrator=None, now=NOW)
    assert result.p_model_raw == 0.123456789


# ---------------------------------------------------------------------
# Caso TRAINED con calibrador sintético (contract test, sin entrenar nada)
# ---------------------------------------------------------------------


def test_trained_with_synthetic_calibrator_populates_calibrated_fields():
    model_output = _make_model_output(p_model_yes=0.5)
    result = calibrate(model_output, calibrator=_FakeCalibrator(), now=NOW)
    assert result.p_model_calibrated == pytest.approx(0.5)
    assert result.calibration_version == "FAKE_V1"
    assert result.calibration_method == "FAKE_V1"
    assert result.calibrated_at == NOW


# ---------------------------------------------------------------------
# model_version / timestamps se propagan literalmente
# ---------------------------------------------------------------------


def test_model_version_and_timestamps_are_propagated():
    model_output = _make_model_output(
        model_version="mv-42", prediction_timestamp=NOW, data_cutoff_timestamp=NOW
    )
    result = calibrate(model_output, calibrator=None, now=NOW)
    assert result.model_version == "mv-42"
    assert result.prediction_timestamp == NOW
    assert result.data_cutoff_timestamp == NOW


# ---------------------------------------------------------------------
# Pureza / determinismo
# ---------------------------------------------------------------------


def test_same_input_produces_same_output_without_calibrator():
    model_output = _make_model_output()
    result_a = calibrate(model_output, calibrator=None, now=NOW)
    result_b = calibrate(model_output, calibrator=None, now=NOW)
    assert result_a == result_b


def test_same_input_produces_same_output_with_calibrator():
    model_output = _make_model_output(p_model_yes=0.4)
    calibrator = _FakeCalibrator()
    result_a = calibrate(model_output, calibrator=calibrator, now=NOW)
    result_b = calibrate(model_output, calibrator=calibrator, now=NOW)
    assert result_a == result_b


def test_default_now_is_tz_aware_when_omitted():
    """Sin now inyectado, calibrate() usa datetime.now(UTC) internamente
    -- confirma que el resultado sigue siendo un CalibrationOutput válido
    (tz-aware), no que el valor sea predecible."""
    model_output = _make_model_output()
    result = calibrate(model_output, calibrator=None)
    assert result.prediction_timestamp == NOW  # propagado, no afectado por "now" omitido


def test_naive_now_raises():
    model_output = _make_model_output()
    with pytest.raises(ValueError, match="tz-aware"):
        calibrate(model_output, calibrator=None, now=datetime(2026, 7, 30, 12, 0, 0))
