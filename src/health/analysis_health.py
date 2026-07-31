"""Analysis Health (Fase 3, Paso 3.7). Ver FASE3_EXECUTION_PLAN.md, Paso
3.7, y CONTRACTS_FASE3.md §5.

`compute_analysis_health()` produce `AnalysisHealth` (Paso 3.0,
`src/health/schemas.py`, sin cambios) desde `QualityScoreOutput` (Fase
2, `src/uncertainty/quality_score.py`, reutilizado sin editar) + un
conteo de `EvidenceItem` (Paso 3.3) + `NormalizedRecord.data_quality.source_timestamps`
(Fase 1/2, para `staleness_seconds` en segundos crudos -- `QualityScoreOutput`
solo expone el componente `freshness` ya normalizado a [0,1], no los
segundos reales, así que este cálculo se rehace aquí con el mismo patrón
exacto que `_component_freshness`/`validate_staleness` de Fase 2: el
timestamp más viejo en `source_timestamps`).

Principio 5, RECTIFICADO en `CONTRACTS_FASE3.md` §5 durante este mismo
paso (ver CONTINUITY.md §0.14): `AnalysisHealth` es exclusivamente
informativo respecto de `soft_score.py` -- NUNCA es su input, ni directa
ni indirectamente (verificado por test de arquitectura). Sí puede
alimentar una Hard Rule específica ya catalogada
(`temporarily_stale_data`, Paso 3.4.3) -- eso no es "doble ponderación",
es la fuente de evidencia de una compuerta binaria de catálogo cerrado,
distinta de un score ponderado.

Función 100% pura: sin I/O, `now` inyectable (mismo patrón que los pasos
anteriores).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from src.evidence.schemas import EvidenceItem
from src.health.schemas import AnalysisHealth
from src.models.schemas import NormalizedRecord
from src.uncertainty.quality_score import QualityScoreOutput


def _percent(value: Optional[float]) -> Optional[float]:
    """QualityScoreOutput.components ya están en [0,1] (Fase 2) --
    escalado directo a [0,100], sin reinterpretar el significado del
    componente."""
    return None if value is None else value * 100.0


def _compute_staleness_seconds(record: NormalizedRecord, now: datetime) -> Optional[float]:
    timestamps = record.data_quality.source_timestamps
    if not timestamps:
        return None
    oldest = min(timestamps.values())
    return (now - oldest).total_seconds()


def compute_analysis_health(
    opportunity_id: str,
    record: NormalizedRecord,
    quality_score_output: QualityScoreOutput,
    evidence_items: List[EvidenceItem],
    now: Optional[datetime] = None,
) -> AnalysisHealth:
    """completeness_signal/consistency_signal derivan de
    QualityScoreOutput.components["data_completeness"]/["bookmaker_dispersion"]
    (Fase 2, ya calculados, nunca recalculados aquí). evidence_density es
    el conteo simple de evidence_items. staleness_seconds se calcula
    directamente del timestamp de fuente más viejo -- None si no hay
    ninguno registrado, nunca fabricado."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    completeness_signal = _percent(quality_score_output.components.get("data_completeness"))
    consistency_signal = _percent(quality_score_output.components.get("bookmaker_dispersion"))
    evidence_density = len(evidence_items)
    staleness_seconds = _compute_staleness_seconds(record, now)

    warnings: List[str] = []
    if staleness_seconds is None:
        warnings.append("sin timestamps de fuente registrados -- no se puede calcular staleness")
    if evidence_density == 0:
        warnings.append("sin evidencia estructurada disponible (EvidenceItem)")

    return AnalysisHealth(
        opportunity_id=opportunity_id,
        completeness_signal=completeness_signal,
        consistency_signal=consistency_signal,
        evidence_density=evidence_density,
        staleness_seconds=staleness_seconds,
        warnings=warnings,
        computed_at=now,
    )
