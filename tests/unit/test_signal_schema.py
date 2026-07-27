"""Tests del esquema de señal (Paso 12). Ver PLAN_PHASE2.md §12 y el
Design Proposal aprobado explícitamente (A1/B2/C2/D3) -- invariantes no
negociables: `SignalInputs` es por lado (nunca por evento), inmutable,
puramente datos (ningún método calcula edge/EV/confidence), y
`SignalType` no tiene ninguna función que lo compute todavía.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.models.base import ModelStatus
from src.models.schemas import Sport
from src.signals import signal_schema
from src.signals.signal_schema import Side, SignalInputs, SignalType


def _kwargs(**overrides):
    base = dict(
        event_id="evt-1",
        sport=Sport.MLB,
        side=Side.YES,
        model_status=ModelStatus.TRAINED,
        p_model=0.62,
        market_price=0.55,
        edge=0.07,
        ev_bruto=0.05,
        ev_neto=None,
        confidence=0.71,
        confidence_method="HEURISTIC_V1",
        generated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


def test_signal_type_has_exactly_enter_watch_pass():
    assert {member.value for member in SignalType} == {"ENTER", "WATCH", "PASS"}


def test_side_has_exactly_yes_no():
    assert {member.value for member in Side} == {"YES", "NO"}


def test_construction_with_valid_values_is_valid():
    inputs = SignalInputs(**_kwargs())
    assert inputs.side == Side.YES
    assert inputs.edge == 0.07


def test_yes_and_no_are_independent_objects_for_same_event():
    """Mismo invariante del Paso 8: EDGE_YES/EDGE_NO nunca cruzados --
    aquí verificado a nivel de objeto, no de función."""
    yes_signal = SignalInputs(**_kwargs(side=Side.YES, edge=0.07, ev_bruto=0.05))
    no_signal = SignalInputs(**_kwargs(side=Side.NO, edge=-0.03, ev_bruto=-0.02))
    assert yes_signal.event_id == no_signal.event_id
    assert yes_signal.side != no_signal.side
    assert yes_signal.edge != no_signal.edge
    assert yes_signal.ev_bruto != no_signal.ev_bruto


def test_all_optional_fields_can_be_none_when_not_computable():
    inputs = SignalInputs(
        **_kwargs(
            model_status=ModelStatus.MODEL_NOT_TRAINED,
            p_model=None,
            market_price=None,
            edge=None,
            ev_bruto=None,
            ev_neto=None,
            confidence=None,
            confidence_method=None,
        )
    )
    assert inputs.p_model is None
    assert inputs.confidence is None
    assert inputs.confidence_method is None


def test_naive_generated_at_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        SignalInputs(**_kwargs(generated_at=datetime.now()))


@pytest.mark.parametrize("field_name", ["p_model", "market_price", "confidence"])
def test_out_of_range_field_raises(field_name):
    with pytest.raises(ValueError, match=r"fuera de \[0,1\]"):
        SignalInputs(**_kwargs(**{field_name: 1.5}))


def test_frozen_instance_cannot_be_mutated():
    inputs = SignalInputs(**_kwargs())
    with pytest.raises(FrozenInstanceError):
        inputs.edge = 0.99  # type: ignore[misc]


def test_signal_inputs_has_no_signal_type_field():
    """Ambigüedad B (decisión B2): SignalType vive separado de
    SignalInputs -- ningún campo signal_type en el contenedor de datos."""
    inputs = SignalInputs(**_kwargs())
    assert not hasattr(inputs, "signal_type")


def test_module_defines_no_classification_function():
    """Ausencia de lógica de umbral: el único código propio del módulo
    (excluyendo imports de otros módulos) son las clases Side/SignalType/
    SignalInputs -- ninguna función de clasificación."""
    import inspect

    own_functions = [
        name
        for name, member in vars(signal_schema).items()
        if inspect.isfunction(member) and member.__module__ == signal_schema.__name__
    ]
    assert own_functions == []
