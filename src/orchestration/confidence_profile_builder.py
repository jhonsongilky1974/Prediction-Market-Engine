"""`build_confidence_profile` (Fase 4, Paso 4.1). Ver `ORCHESTRATOR_SPEC.md`
§9.2 -- mapeo `PROVISIONAL_V1`, aprobado explícitamente por el usuario,
reutilizando ÚNICAMENTE componentes ya calculados por
`compute_quality_score` (Fase 2, `src/uncertainty/quality_score.py`).
Cero fórmulas nuevas: cada campo es una selección o un promedio directo
de números ya aprobados, o `None` cuando no hay ninguna fuente real
(nunca se fabrica).

`ConfidenceProfile` exige rango `[0,100]` en todos sus campos numéricos
(`src/policy/schemas.py::_require_percent_range`); `QualityScoreOutput`
produce sus componentes en `[0,1]` -- este módulo reescala explícitamente
(`*100`), no cambia de escala por accidente.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from src.policy.schemas import ConfidenceProfile
from src.uncertainty.quality_score import QualityScoreOutput

# Componentes de `QualityScoreOutput.components` (Fase 2) que este mapeo
# considera "calidad de mercado" -- selección, no una fórmula nueva.
_MARKET_QUALITY_COMPONENTS = ("bookmaker_dispersion", "sample_size", "market_liquidity")


def _mean_of_available(values: Iterable[Optional[float]]) -> Optional[float]:
    """Promedio de los valores no-`None` -- `None` si ninguno está
    disponible. Mismo principio de redistribución ya usado en
    `compute_quality_score`, aplicado aquí a un promedio simple, sin
    pesos nuevos que decidir."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def build_confidence_profile(
    quality_score_output: QualityScoreOutput,
    opportunity_id: str,
    now: datetime,
) -> ConfidenceProfile:
    components = quality_score_output.components

    data_quality = components.get("data_completeness")
    if data_quality is not None:
        data_quality *= 100.0

    market_quality = _mean_of_available(components.get(name) for name in _MARKET_QUALITY_COMPONENTS)
    if market_quality is not None:
        market_quality *= 100.0

    freshness = components.get("freshness")
    operational_safety: Optional[float] = freshness * 100.0 if freshness is not None else None
    operational_risk: Optional[float] = 100.0 - operational_safety if operational_safety is not None else None

    aggregate_confidence = quality_score_output.confidence
    if aggregate_confidence is not None:
        aggregate_confidence *= 100.0

    return ConfidenceProfile(
        opportunity_id=opportunity_id,
        data_quality=data_quality,
        # Sin fuente real hoy -- cero EvaluationRecord existen todavía
        # (Coverage Gate/auditoría de labels, Paso 4.2/4.2.1, sin
        # ejecutar). Fabricar este campo violaría la Regla 3.
        model_reliability=None,
        market_quality=market_quality,
        operational_safety=operational_safety,
        operational_risk=operational_risk,
        aggregate_confidence=aggregate_confidence,
        quality_score_component_ref=quality_score_output.confidence_config_version,
        computed_at=now,
    )
