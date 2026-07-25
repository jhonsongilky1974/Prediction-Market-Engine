"""Tests del contrato de salida de modelo (Paso 5a). Ver
PLAN_PHASE2.md §5 -- invariantes no negociables: `p_model_yes` nunca
fabricado mientras `model_status != TRAINED`, siempre en [0,1] cuando
existe, timestamps siempre UTC-aware.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.base import ModelStatus, PModelOutput


def _kwargs(**overrides):
    base = dict(
        p_model_yes=None,
        model_version=None,
        model_status=ModelStatus.MODEL_NOT_TRAINED,
        feature_set_version="phase2_registry_v1",
        prediction_timestamp=datetime.now(timezone.utc),
        data_cutoff_timestamp=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


def test_model_not_trained_with_p_model_yes_none_is_valid():
    output = PModelOutput(**_kwargs())
    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None


def test_insufficient_history_with_p_model_yes_none_is_valid():
    output = PModelOutput(**_kwargs(model_status=ModelStatus.INSUFFICIENT_HISTORY))
    assert output.p_model_yes is None


def test_trained_with_valid_probability_is_valid():
    output = PModelOutput(**_kwargs(model_status=ModelStatus.TRAINED, p_model_yes=0.62, model_version="v1"))
    assert output.p_model_yes == 0.62


def test_not_trained_with_fabricated_probability_raises():
    """Invariante no negociable: nunca se fabrica una probabilidad para
    aparentar que el modelo está operativo."""
    with pytest.raises(ValueError, match="p_model_yes debe ser None"):
        PModelOutput(**_kwargs(model_status=ModelStatus.MODEL_NOT_TRAINED, p_model_yes=0.5))


def test_insufficient_history_with_fabricated_probability_raises():
    with pytest.raises(ValueError, match="p_model_yes debe ser None"):
        PModelOutput(**_kwargs(model_status=ModelStatus.INSUFFICIENT_HISTORY, p_model_yes=0.5))


def test_probability_out_of_range_raises():
    with pytest.raises(ValueError, match=r"fuera de \[0,1\]"):
        PModelOutput(**_kwargs(model_status=ModelStatus.TRAINED, p_model_yes=1.5, model_version="v1"))


def test_naive_prediction_timestamp_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        PModelOutput(**_kwargs(prediction_timestamp=datetime.now()))


def test_naive_data_cutoff_timestamp_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        PModelOutput(**_kwargs(data_cutoff_timestamp=datetime.now()))


def test_confidence_defaults_to_none_never_fabricated():
    """Paso 7 (confidence_method=HEURISTIC_V1) no existe todavía -- este
    campo debe quedar explícitamente None, nunca inferido aquí."""
    output = PModelOutput(**_kwargs())
    assert output.confidence is None
    assert output.confidence_method is None
