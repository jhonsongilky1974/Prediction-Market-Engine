"""Tests de CalibrationOutput (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md
§2 -- invariantes: p_model_calibrated nunca sin calibration_version;
p_model_calibrated siempre None si p_model_raw es None; rangos [0,1];
timestamps tz-aware obligatorios.

`model_version` es `Optional[str]` (rectificación aplicada durante el
Paso 3.1, ver src/calibration/schemas.py) -- refleja exactamente
`PModelOutput.model_version` (Fase 2), que es `None` en el caso real
`MODEL_NOT_TRAINED` (`mlb_baseline.py`/`tennis_baseline.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.calibration.schemas import CalibrationOutput
from tests.unit.fase3_factories import NOW, assert_round_trip, make_calibration_output


def test_construction_with_valid_values_is_valid():
    calib = make_calibration_output()
    assert calib.p_model_raw == 0.6
    assert calib.p_model_calibrated is None
    assert calib.calibration_version is None


def test_calibrated_without_version_raises():
    with pytest.raises(ValidationError, match="calibration_version"):
        make_calibration_output(p_model_calibrated=0.65, calibration_version=None)


def test_calibrated_with_version_is_valid():
    calib = make_calibration_output(
        p_model_calibrated=0.65, calibration_version="PLATT_V1", calibration_method="PLATT_V1"
    )
    assert calib.p_model_calibrated == 0.65


def test_model_not_trained_case_has_none_model_version():
    """Caso real de producción: model_status=MODEL_NOT_TRAINED implica
    p_model_yes=None Y model_version=None simultáneamente (ver
    mlb_baseline.py/tennis_baseline.py) -- CalibrationOutput debe aceptar
    ambos en None a la vez sin fabricar ningún valor."""
    calib = make_calibration_output(p_model_raw=None, model_version=None)
    assert calib.p_model_raw is None
    assert calib.model_version is None
    assert calib.p_model_calibrated is None


def test_calibrated_without_raw_raises():
    with pytest.raises(ValidationError, match="p_model_raw"):
        make_calibration_output(
            p_model_raw=None, p_model_calibrated=0.65, calibration_version="PLATT_V1"
        )


@pytest.mark.parametrize("field_name", ["p_model_raw", "p_model_calibrated"])
def test_out_of_range_field_raises(field_name):
    overrides = {field_name: 1.5}
    if field_name == "p_model_calibrated":
        overrides["calibration_version"] = "PLATT_V1"
    with pytest.raises(ValidationError, match=r"fuera de \[0,1\]"):
        make_calibration_output(**overrides)


@pytest.mark.parametrize(
    "field_name", ["prediction_timestamp", "data_cutoff_timestamp", "calibrated_at"]
)
def test_naive_timestamp_raises(field_name):
    with pytest.raises(ValidationError, match="tz-aware"):
        make_calibration_output(**{field_name: datetime(2026, 7, 30, 12, 0, 0)})


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        CalibrationOutput(
            p_model_raw=0.6,
            model_version="mv1",
            prediction_timestamp=NOW,
            data_cutoff_timestamp=NOW,
            unexpected_field="x",
        )


def test_round_trip_serialization():
    assert_round_trip(make_calibration_output())
    assert_round_trip(
        make_calibration_output(p_model_calibrated=0.65, calibration_version="PLATT_V1")
    )
    assert_round_trip(make_calibration_output(p_model_raw=None, model_version=None))
