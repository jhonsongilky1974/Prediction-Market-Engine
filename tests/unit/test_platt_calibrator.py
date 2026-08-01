"""Tests de `PlattCalibrator`/`fit_platt_calibrator` (calibración real,
ver `CALIBRATION_SPEC.md` §3). Puramente matemático -- no conoce tenis,
`HistoryRepository` ni ningún otro módulo del proyecto."""
from __future__ import annotations

from src.calibration.platt_calibrator import PlattCalibrator, fit_platt_calibrator


def _monotonic_dataset():
    # p_raw claramente correlacionado con y -- suficiente para que
    # LogisticRegression converja a una relación monótona creciente real,
    # sin pretender que sea un caso realista de calibración.
    p_raw = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]
    y = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1]
    return p_raw, y


def test_fit_platt_calibrator_satisfies_calibrator_protocol():
    p_raw, y = _monotonic_dataset()
    calibrator = fit_platt_calibrator(p_raw, y, calibration_version="test_platt_v1")

    assert isinstance(calibrator, PlattCalibrator)
    assert calibrator.calibration_version == "test_platt_v1"
    assert calibrator.calibration_method == "PLATT_V1"
    assert hasattr(calibrator, "calibrate")


def test_calibrate_output_always_in_unit_interval():
    p_raw, y = _monotonic_dataset()
    calibrator = fit_platt_calibrator(p_raw, y, calibration_version="test_platt_v1")

    for p in (0.0, 0.01, 0.5, 0.99, 1.0):
        result = calibrator.calibrate(p)
        assert 0.0 <= result <= 1.0


def test_calibrate_preserves_monotonic_ordering():
    """Platt scaling es una transformación monótona -- p_raw más alto
    nunca debe producir una probabilidad calibrada más baja."""
    p_raw, y = _monotonic_dataset()
    calibrator = fit_platt_calibrator(p_raw, y, calibration_version="test_platt_v1")

    low = calibrator.calibrate(0.1)
    mid = calibrator.calibrate(0.5)
    high = calibrator.calibrate(0.9)
    assert low <= mid <= high


def test_calibrate_is_deterministic():
    p_raw, y = _monotonic_dataset()
    calibrator = fit_platt_calibrator(p_raw, y, calibration_version="test_platt_v1")
    assert calibrator.calibrate(0.42) == calibrator.calibrate(0.42)
