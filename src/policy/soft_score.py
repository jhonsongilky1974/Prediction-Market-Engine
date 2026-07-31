"""Soft Score (Fase 3, Paso 3.4.4). Ver FASE3_EXECUTION_PLAN.md, Paso
3.4.4, y POLICY_ENGINE_SPEC.md §3, §3.1.

Los 5 componentes (`POLICY_ENGINE_SPEC.md` §3): `edge_strength` (no
crítico), `ev_neto_strength`, `confidence_aggregate`,
`data_quality_floor`, `operational_safety_floor` (los 4 últimos,
críticos -- Principio 9).

A diferencia del hueco encontrado en el Paso 3.4.3 (`pending_lineup`
prometía ser configurable en `PolicyManifest` sin que ese contrato
tuviera el campo), aquí NO hay contradicción: `PolicyManifest` (Paso
3.0) ya tiene `soft_score_weights: Dict[str, float]` y
`critical_minimums: Dict[str, float]` -- exactamente los dos
diccionarios que este módulo necesita. `weights`/`minimums` se reciben
como parámetros `Optional[Dict[str, float]]` con defaults PROVISIONAL
documentados abajo; el Paso 3.4.5 los pasará desde el manifiesto activo
sin necesitar ningún cambio de contrato.

## Regla de no compensación (Principio 9, literal, POLICY_ENGINE_SPEC.md §3.1)

    ENTER válido  <=>  aggregate_soft_score >= enter_global_threshold
                        AND
                        todo componente crítico tiene passed_minimum == True

Un `aggregate_soft_score` alto NUNCA compensa un mínimo crítico
incumplido -- `check_enter_eligible_by_soft_score()` implementa esto de
forma literal e independiente del cálculo del agregado.

## Por qué `ev_neto_strength` bloquea ENTER hoy, siempre

`ev_neto_strength` deriva de `PayoffEstimate.ev_to_settlement`, que es
SIEMPRE `None` en la práctica actual (`net_ev_status=UNKNOWN` universal,
Paso 3.2, DECISIÓN PENDIENTE D-3). `SoftScoreComponent` (Paso 3.0)
exige `value is None ⟹ passed_minimum is None` -- y un componente
crítico con `passed_minimum` distinto de `True` bloquea ENTER por la
regla de arriba. Consecuencia verificada por test explícito en este
paso: hoy, con los datos reales del proyecto, ningún ENTER es posible
sin importar qué tan bien se vean los demás componentes -- el mismo
hallazgo de `FASE3_AUDIT_REPORT.md` §7, ahora demostrado en código.

Funciones 100% puras, sin timestamps (`SoftScoreComponent`, a diferencia
de los demás contratos de Fase 3, no lleva ningún campo de tiempo).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from src.payoff.schemas import PayoffEstimate
from src.policy.schemas import ConfidenceProfile, SoftScoreComponent
from src.signals.signal_schema import SignalInputs

_CRITICAL_COMPONENT_NAMES = frozenset(
    {"ev_neto_strength", "confidence_aggregate", "data_quality_floor", "operational_safety_floor"}
)
"""Fijo, no configurable -- Principio 9 exige exactamente estos 4 como
críticos; PolicyManifest puede ajustar SUS UMBRALES/PESOS, nunca cuáles
componentes son críticos."""

SOFT_SCORE_COMPONENT_NAMES = (
    "edge_strength",
    "ev_neto_strength",
    "confidence_aggregate",
    "data_quality_floor",
    "operational_safety_floor",
)
"""Catálogo cerrado de 5 component_name, en orden de construcción."""

DEFAULT_SOFT_SCORE_WEIGHTS: Dict[str, float] = {
    "edge_strength": 0.20,
    "ev_neto_strength": 0.30,
    "confidence_aggregate": 0.30,
    "data_quality_floor": 0.10,
    "operational_safety_floor": 0.10,
}
"""PROVISIONAL, sin respaldo empírico -- suman 1.00. Reemplazables vía
PolicyManifest.soft_score_weights en el Paso 3.4.5."""

DEFAULT_CRITICAL_MINIMUMS: Dict[str, float] = {
    "ev_neto_strength": 50.0,
    "confidence_aggregate": 50.0,
    "data_quality_floor": 40.0,
    "operational_safety_floor": 60.0,
}
"""PROVISIONAL, sin respaldo empírico, en la misma escala [0,100] que
`value` (ver `_normalize_signed_unit_to_percent`: 50.0 en
ev_neto_strength corresponde a EV=0, breakeven, en el mapeo
[-0.30,0.30]->[0,100]). Reemplazables vía PolicyManifest.critical_minimums
en el Paso 3.4.5."""

_EDGE_EV_NORMALIZATION_RANGE = (-0.30, 0.30)
"""Mismo rango que los 12 buckets de segment_by_edge (src/evaluation/reports.py,
Fase 2, Paso 10) -- reutilizado por consistencia de escala, no un valor
nuevo inventado."""


def _normalize_signed_unit_to_percent(
    value: Optional[float], value_range: tuple = _EDGE_EV_NORMALIZATION_RANGE
) -> Optional[float]:
    """Clip a value_range y mapeo lineal a [0,100]. None se propaga tal
    cual -- nunca se fabrica un valor cuando la entrada es None."""
    if value is None:
        return None
    lo, hi = value_range
    clipped = max(lo, min(hi, value))
    return (clipped - lo) / (hi - lo) * 100.0


def _aggregate_confidence_dimensions(confidence_profile: ConfidenceProfile) -> Optional[float]:
    """Promedio simple de las dimensiones disponibles de ConfidenceProfile
    (data_quality, model_reliability, market_quality, operational_safety)
    -- mismo espíritu de redistribución que compute_quality_score (Fase
    2): si falta alguna, se promedia solo entre las presentes. None si
    las 4 son None."""
    dimensions = [
        confidence_profile.data_quality,
        confidence_profile.model_reliability,
        confidence_profile.market_quality,
        confidence_profile.operational_safety,
    ]
    available = [d for d in dimensions if d is not None]
    if not available:
        return None
    return sum(available) / len(available)


def compute_soft_score_components(
    signal_inputs: SignalInputs,
    payoff_estimate: Optional[PayoffEstimate],
    confidence_profile: ConfidenceProfile,
    weights: Optional[Dict[str, float]] = None,
    minimums: Optional[Dict[str, float]] = None,
) -> List[SoftScoreComponent]:
    """Construye los 5 SoftScoreComponent. `weight` de cada componente
    es el peso YA REDISTRIBUIDO entre los componentes con value != None
    (mismo patrón que QualityScoreOutput.weights, Fase 2) -- no el peso
    estático de configuración."""
    static_weights = dict(weights) if weights is not None else dict(DEFAULT_SOFT_SCORE_WEIGHTS)
    active_minimums = dict(minimums) if minimums is not None else dict(DEFAULT_CRITICAL_MINIMUMS)

    ev_to_settlement = payoff_estimate.ev_to_settlement if payoff_estimate is not None else None
    raw_values: Dict[str, Optional[float]] = {
        "edge_strength": _normalize_signed_unit_to_percent(signal_inputs.edge),
        "ev_neto_strength": _normalize_signed_unit_to_percent(ev_to_settlement),
        "confidence_aggregate": _aggregate_confidence_dimensions(confidence_profile),
        "data_quality_floor": confidence_profile.data_quality,
        "operational_safety_floor": confidence_profile.operational_safety,
    }

    available_names = {name for name, value in raw_values.items() if value is not None}
    total_active_weight = sum(static_weights.get(name, 0.0) for name in available_names)

    components: List[SoftScoreComponent] = []
    for name in SOFT_SCORE_COMPONENT_NAMES:
        value = raw_values[name]
        is_critical = name in _CRITICAL_COMPONENT_NAMES

        if name in available_names and total_active_weight > 0:
            effective_weight = static_weights.get(name, 0.0) / total_active_weight
        else:
            effective_weight = 0.0

        minimum_required = active_minimums.get(name, 0.0) if is_critical else None
        passed_minimum = None
        if is_critical and value is not None:
            passed_minimum = value >= minimum_required

        components.append(
            SoftScoreComponent(
                component_name=name,
                value=value,
                weight=effective_weight,
                is_critical_minimum=is_critical,
                minimum_required=minimum_required,
                passed_minimum=passed_minimum,
            )
        )
    return components


def compute_aggregate_soft_score(components: List[SoftScoreComponent]) -> Optional[float]:
    """Suma ponderada de value*weight sobre los componentes con value no
    nulo -- los weight ya vienen redistribuidos (suman 1.0 entre los
    disponibles) desde compute_soft_score_components(), así que no se
    redistribuye una segunda vez aquí. None si ningún componente tiene
    value ni peso positivo."""
    available = [(c.weight, c.value) for c in components if c.value is not None]
    total_weight = sum(weight for weight, _ in available)
    if not available or total_weight <= 0:
        return None
    return sum(weight * value for weight, value in available) / total_weight


def check_enter_eligible_by_soft_score(
    components: List[SoftScoreComponent],
    aggregate_soft_score: Optional[float],
    enter_global_threshold: float,
) -> bool:
    """Implementación literal de la regla de no compensación
    (POLICY_ENGINE_SPEC.md §3.1): True únicamente si el score global
    alcanza el umbral Y todo componente crítico tiene
    passed_minimum == True. Un solo mínimo crítico incumplido (o no
    calculable, passed_minimum=None) basta para devolver False, sin
    importar qué tan alto sea aggregate_soft_score."""
    if aggregate_soft_score is None or aggregate_soft_score < enter_global_threshold:
        return False
    for component in components:
        if component.is_critical_minimum and component.passed_minimum is not True:
            return False
    return True
