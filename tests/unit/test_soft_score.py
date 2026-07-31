"""Tests de Soft Score (Fase 3, Paso 3.4.4). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.4.4, y POLICY_ENGINE_SPEC.md §3, §3.1 -- la no-compensación
probada explícitamente para cada uno de los 4 componentes críticos, uno
a la vez, más el caso central: ev_neto_strength con
net_ev_status=UNKNOWN bloquea ENTER incluso con todo lo demás perfecto.
"""
from __future__ import annotations

import pytest

from src.payoff.schemas import NetEvStatus
from src.policy.soft_score import (
    DEFAULT_CRITICAL_MINIMUMS,
    SOFT_SCORE_COMPONENT_NAMES,
    check_enter_eligible_by_soft_score,
    compute_aggregate_soft_score,
    compute_soft_score_components,
)
from tests.unit.fase3_factories import make_confidence_profile, make_payoff_estimate, make_signal_inputs

_PERFECT_CONFIDENCE = dict(
    data_quality=90.0, model_reliability=90.0, market_quality=90.0, operational_safety=90.0
)
_PERFECT_PAYOFF = dict(
    net_ev_status=NetEvStatus.COMPUTED,
    ev_to_settlement=0.15,
    ev_to_planned_exit=0.15,
    cost_evidence_refs=["fixture"],
)


def _component(components, name):
    return next(c for c in components if c.component_name == name)


# ---------------------------------------------------------------------
# Catálogo y criticidad
# ---------------------------------------------------------------------


def test_catalog_has_exactly_five_component_names():
    assert len(SOFT_SCORE_COMPONENT_NAMES) == 5
    assert set(SOFT_SCORE_COMPONENT_NAMES) == {
        "edge_strength",
        "ev_neto_strength",
        "confidence_aggregate",
        "data_quality_floor",
        "operational_safety_floor",
    }


def test_edge_strength_is_not_critical():
    components = compute_soft_score_components(
        make_signal_inputs(), make_payoff_estimate(**_PERFECT_PAYOFF), make_confidence_profile(**_PERFECT_CONFIDENCE)
    )
    assert _component(components, "edge_strength").is_critical_minimum is False
    assert _component(components, "edge_strength").minimum_required is None


@pytest.mark.parametrize(
    "name", ["ev_neto_strength", "confidence_aggregate", "data_quality_floor", "operational_safety_floor"]
)
def test_four_components_are_critical(name):
    components = compute_soft_score_components(
        make_signal_inputs(), make_payoff_estimate(**_PERFECT_PAYOFF), make_confidence_profile(**_PERFECT_CONFIDENCE)
    )
    component = _component(components, name)
    assert component.is_critical_minimum is True
    assert component.minimum_required == DEFAULT_CRITICAL_MINIMUMS[name]


# ---------------------------------------------------------------------
# Cómputo de valores
# ---------------------------------------------------------------------


def test_edge_strength_normalizes_edge_to_percent():
    signal_inputs = make_signal_inputs(edge=0.15)
    components = compute_soft_score_components(signal_inputs, make_payoff_estimate(), make_confidence_profile())
    assert _component(components, "edge_strength").value == pytest.approx(75.0)


def test_edge_strength_none_when_edge_none():
    signal_inputs = make_signal_inputs(edge=None)
    components = compute_soft_score_components(signal_inputs, make_payoff_estimate(), make_confidence_profile())
    assert _component(components, "edge_strength").value is None


def test_ev_neto_strength_normalizes_when_computed():
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)
    components = compute_soft_score_components(make_signal_inputs(), payoff, make_confidence_profile())
    assert _component(components, "ev_neto_strength").value == pytest.approx(75.0)


def test_data_quality_floor_and_operational_safety_floor_pass_through_directly():
    confidence_profile = make_confidence_profile(data_quality=55.0, operational_safety=65.0, operational_risk=35.0)
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "data_quality_floor").value == 55.0
    assert _component(components, "operational_safety_floor").value == 65.0


def test_confidence_aggregate_averages_available_dimensions():
    confidence_profile = make_confidence_profile(
        data_quality=40.0,
        model_reliability=None,
        market_quality=None,
        operational_safety=60.0,
        operational_risk=40.0,
    )
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "confidence_aggregate").value == pytest.approx(50.0)


def test_confidence_aggregate_none_when_all_four_dimensions_none():
    confidence_profile = make_confidence_profile(
        data_quality=None, model_reliability=None, market_quality=None, operational_safety=None
    )
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "confidence_aggregate").value is None


# ---------------------------------------------------------------------
# minimum_required siempre declarado en críticos, incluso con value=None
# ---------------------------------------------------------------------


def test_minimum_required_populated_even_when_ev_neto_value_is_none():
    """payoff por defecto (fixture) tiene net_ev_status=UNKNOWN,
    ev_to_settlement=None -- caso real del proyecto hoy."""
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), make_confidence_profile())
    ev_component = _component(components, "ev_neto_strength")
    assert ev_component.value is None
    assert ev_component.minimum_required == DEFAULT_CRITICAL_MINIMUMS["ev_neto_strength"]
    assert ev_component.passed_minimum is None


# ---------------------------------------------------------------------
# passed_minimum correcto por umbral
# ---------------------------------------------------------------------


def test_passed_minimum_true_when_above_threshold():
    confidence_profile = make_confidence_profile(data_quality=90.0)
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "data_quality_floor").passed_minimum is True


def test_passed_minimum_false_when_below_threshold():
    confidence_profile = make_confidence_profile(data_quality=10.0)
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "data_quality_floor").passed_minimum is False


def test_passed_minimum_true_at_exact_threshold():
    confidence_profile = make_confidence_profile(data_quality=DEFAULT_CRITICAL_MINIMUMS["data_quality_floor"])
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), confidence_profile)
    assert _component(components, "data_quality_floor").passed_minimum is True


# ---------------------------------------------------------------------
# Pesos: redistribución entre componentes disponibles
# ---------------------------------------------------------------------


def test_weights_sum_to_one_when_all_available():
    components = compute_soft_score_components(
        make_signal_inputs(), make_payoff_estimate(**_PERFECT_PAYOFF), make_confidence_profile(**_PERFECT_CONFIDENCE)
    )
    assert sum(c.weight for c in components) == pytest.approx(1.0)


def test_weights_redistribute_when_one_component_unavailable():
    """ev_neto_strength no disponible (UNKNOWN, caso real) -- su peso
    estático (0.30) se redistribuye entre los otros 4."""
    components = compute_soft_score_components(make_signal_inputs(), make_payoff_estimate(), make_confidence_profile(**_PERFECT_CONFIDENCE))
    assert _component(components, "ev_neto_strength").weight == 0.0
    assert sum(c.weight for c in components) == pytest.approx(1.0)


# ---------------------------------------------------------------------
# compute_aggregate_soft_score
# ---------------------------------------------------------------------


def test_compute_aggregate_soft_score_matches_manual_calculation():
    signal_inputs = make_signal_inputs(edge=0.15)  # -> 75.0
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)  # ev 0.15 -> 75.0
    confidence_profile = make_confidence_profile(**_PERFECT_CONFIDENCE)  # todas 90.0 -> confidence_aggregate=90.0
    components = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    aggregate = compute_aggregate_soft_score(components)
    # 0.20*75 + 0.30*75 + 0.30*90 + 0.10*90 + 0.10*90 = 15+22.5+27+9+9 = 82.5
    assert aggregate == pytest.approx(82.5)


def test_compute_aggregate_soft_score_none_when_no_component_has_value():
    signal_inputs = make_signal_inputs(edge=None)
    confidence_profile = make_confidence_profile(
        data_quality=None, model_reliability=None, market_quality=None, operational_safety=None
    )
    components = compute_soft_score_components(signal_inputs, make_payoff_estimate(), confidence_profile)
    assert compute_aggregate_soft_score(components) is None


# ---------------------------------------------------------------------
# check_enter_eligible_by_soft_score -- no compensación (Principio 9)
# ---------------------------------------------------------------------


def test_enter_eligible_true_when_everything_passes():
    signal_inputs = make_signal_inputs(edge=0.15)
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)
    confidence_profile = make_confidence_profile(**_PERFECT_CONFIDENCE)
    components = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    aggregate = compute_aggregate_soft_score(components)
    assert check_enter_eligible_by_soft_score(components, aggregate, enter_global_threshold=60.0) is True


def test_enter_not_eligible_when_aggregate_below_threshold():
    signal_inputs = make_signal_inputs(edge=0.15)
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)
    confidence_profile = make_confidence_profile(**_PERFECT_CONFIDENCE)
    components = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    aggregate = compute_aggregate_soft_score(components)
    assert check_enter_eligible_by_soft_score(components, aggregate, enter_global_threshold=95.0) is False


def test_ev_neto_strength_unknown_blocks_enter_even_with_everything_else_perfect():
    """EL caso central de este paso: net_ev_status=UNKNOWN (payoff por
    defecto, estado real y universal del proyecto hoy -- Paso 3.2) hace
    que ev_neto_strength.value/passed_minimum sean None, lo cual BLOQUEA
    ENTER sin importar que edge/confianza/calidad de datos sean
    perfectos. Prueba en código el hallazgo central de
    FASE3_AUDIT_REPORT.md §7."""
    signal_inputs = make_signal_inputs(edge=0.15)
    payoff = make_payoff_estimate()  # default: net_ev_status=UNKNOWN
    confidence_profile = make_confidence_profile(**_PERFECT_CONFIDENCE)
    components = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    aggregate = compute_aggregate_soft_score(components)

    ev_component = _component(components, "ev_neto_strength")
    assert ev_component.value is None
    assert ev_component.passed_minimum is None
    # El score global, calculado solo sobre los componentes disponibles,
    # sigue siendo alto -- y aun así ENTER debe quedar bloqueado.
    assert aggregate is not None and aggregate >= 60.0
    assert check_enter_eligible_by_soft_score(components, aggregate, enter_global_threshold=60.0) is False


@pytest.mark.parametrize(
    "overrides,failing_component",
    [
        (dict(data_quality=10.0), "data_quality_floor"),
        (dict(operational_safety=10.0, operational_risk=90.0), "operational_safety_floor"),
        (
            dict(data_quality=40.0, operational_safety=60.0, operational_risk=40.0, model_reliability=20.0, market_quality=20.0),
            "confidence_aggregate",
        ),
    ],
)
def test_single_critical_minimum_failure_blocks_enter_despite_high_aggregate(overrides, failing_component):
    """Un mínimo crítico incumplido bloquea ENTER incluso cuando
    aggregate_soft_score sigue por encima del umbral -- la esencia de la
    no-compensación (Principio 9), probada por separado para cada
    componente crítico (salvo ev_neto_strength, que tiene su propio test
    dedicado arriba por ser el caso real hoy)."""
    signal_inputs = make_signal_inputs(edge=0.15)
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)
    base_confidence = dict(_PERFECT_CONFIDENCE)
    base_confidence.update(overrides)
    confidence_profile = make_confidence_profile(**base_confidence)

    components = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    aggregate = compute_aggregate_soft_score(components)

    failing = _component(components, failing_component)
    assert failing.passed_minimum is False
    # score global sigue por encima de un umbral razonable (50) en los 3 casos,
    # y aun así ENTER queda bloqueado por el mínimo crítico incumplido.
    assert aggregate is not None and aggregate >= 50.0
    assert check_enter_eligible_by_soft_score(components, aggregate, enter_global_threshold=50.0) is False


# ---------------------------------------------------------------------
# Pureza
# ---------------------------------------------------------------------


def test_same_input_produces_same_output():
    signal_inputs = make_signal_inputs(edge=0.15)
    payoff = make_payoff_estimate(**_PERFECT_PAYOFF)
    confidence_profile = make_confidence_profile(**_PERFECT_CONFIDENCE)
    components_a = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    components_b = compute_soft_score_components(signal_inputs, payoff, confidence_profile)
    assert components_a == components_b
