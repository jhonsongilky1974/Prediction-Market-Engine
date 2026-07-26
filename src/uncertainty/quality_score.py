"""Sistema de incertidumbre/confianza (Paso 7). Ver PLAN_PHASE2.md §9 y el
Design Proposal aprobado explícitamente por el usuario antes de esta
implementación (fórmulas, normalización, pesos iniciales y umbrales
citados abajo son exactamente los aprobados en ese documento).

`confidence` es un score heurístico de agregación (`confidence_method`
SIEMPRE `"HEURISTIC_V1"`) -- útil para ordenar/filtrar y auditar, NUNCA se
presenta ni se documenta como una probabilidad calibrada. La calibración
real de los pesos requiere histórico real y es un paso futuro separado
(en ese momento `confidence_method` pasaría a algo como `"CALIBRATED_V1"`,
nunca antes -- PLAN_PHASE2.md §9).

Principio no negociable: un componente no calculable es `None`, nunca se
fabrica ni se imputa a un valor neutro. La agregación redistribuye
dinámicamente el peso entre los componentes SÍ disponibles -- `weights` en
la salida son los pesos ya redistribuidos, efectivamente usados en ESE
cálculo, no los pesos estáticos de configuración (así se cumple
literalmente el contrato de §9: "weights: los pesos usados en ESTE
cálculo").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.pricing.odds_consensus import ConsensusNoVigResult
from src.quality.completeness import CORE_FIELDS
from src.models.schemas import NormalizedRecord

CONFIDENCE_METHOD = "HEURISTIC_V1"
CONFIDENCE_CONFIG_VERSION = "quality_score_v1"

# Pesos iniciales HEURISTIC_V1 -- aprobados explícitamente por el usuario
# (Design Proposal), suman 1.00. Ninguno calibrado con evidencia todavía.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "data_completeness": 0.18,
    "match_confidence_gap": 0.22,
    "missing_critical": 0.18,
    "bookmaker_dispersion": 0.15,
    "sample_size": 0.10,
    "market_liquidity": 0.07,
    "freshness": 0.10,
}

# Umbrales HEURISTIC_V1, aprobados en el Design Proposal.
_DISPERSION_ZERO_AT = 0.10  # desviación estándar de p_no_vig_YES entre bookmakers
_SAMPLE_SIZE_TARGET = 5  # bookmaker_count considerado "muestra plenamente suficiente"
# PROVISIONAL -- ver Design Proposal: solo 3/93 event_snapshots reales
# tenían volume/open_interest poblado en el momento de elegir este
# número (rango observado ~5.4K-144K). Revisar cuando haya más volumen
# real capturado -- es el umbral con menos respaldo empírico de los 7.
_MARKET_LIQUIDITY_TARGET = 50000.0
_FRESHNESS_STALE_AFTER_SECONDS = 3600.0  # 1h, igual a la cadencia del LaunchAgent


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


@dataclass
class QualityScoreOutput:
    """Contrato de salida obligatorio de §9."""

    confidence: Optional[float]
    confidence_method: str
    confidence_config_version: str
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------
# Componentes individuales -- cada uno None si no es calculable, nunca
# fabricado.
# ---------------------------------------------------------------------


def _component_data_completeness(record: NormalizedRecord) -> Optional[float]:
    """Reutilizado directamente de Fase 1 -- ya está en [0,1]."""
    return record.data_quality.data_completeness_score


def _component_match_confidence_gap(record: NormalizedRecord) -> Optional[float]:
    """Distancia por encima del umbral mínimo de matching ya existente
    (`EVENT_NAME_MATCH_MIN_CONFIDENCE`), normalizada a [0,1]."""
    match_confidence = record.data_quality.match_confidence
    if match_confidence is None:
        return None
    span = 1.0 - EVENT_NAME_MATCH_MIN_CONFIDENCE
    return _clip((match_confidence - EVENT_NAME_MATCH_MIN_CONFIDENCE) / span)


def _component_missing_critical(record: NormalizedRecord) -> Optional[float]:
    """Fracción de CORE_FIELDS presentes (nunca None: missing_fields
    siempre existe, aunque sea vacía)."""
    missing = set(record.data_quality.missing_fields)
    missing_core = [f for f in CORE_FIELDS if f in missing]
    return 1.0 - (len(missing_core) / len(CORE_FIELDS))


def _component_bookmaker_dispersion(consensus: Optional[ConsensusNoVigResult]) -> Optional[float]:
    """Invierte y normaliza `ConsensusNoVigResult.dispersion` (Paso 4).
    None si <2 bookmakers (mismo caso en que dispersion ya es None)."""
    if consensus is None or consensus.dispersion is None:
        return None
    return _clip(1.0 - (consensus.dispersion / _DISPERSION_ZERO_AT))


def _component_sample_size(consensus: Optional[ConsensusNoVigResult]) -> Optional[float]:
    """Interpretado como `bookmaker_count` (única "muestra" disponible a
    nivel de registro individual -- ver Design Proposal). None si no hay
    ningún bookmaker (NOT_CONFIGURED/FAILED)."""
    if consensus is None or not consensus.bookmaker_count:
        return None
    return min(consensus.bookmaker_count / _SAMPLE_SIZE_TARGET, 1.0)


def _component_market_liquidity(record: NormalizedRecord) -> Optional[float]:
    """`volume` como base principal, `open_interest` como respaldo --
    `liquidity` NO se usa (verificado contra datos reales: siempre 0
    cuando existe, inutilizable). Umbral PROVISIONAL, ver constante."""
    basis = record.market.volume
    if basis is None:
        basis = record.market.open_interest
    if basis is None:
        return None
    return min(basis / _MARKET_LIQUIDITY_TARGET, 1.0)


def _component_freshness(record: NormalizedRecord, now: datetime) -> Optional[float]:
    """Antigüedad del timestamp más viejo en `source_timestamps`, mismo
    patrón que Paso 4. None si no hay ningún timestamp registrado."""
    timestamps = record.data_quality.source_timestamps
    if not timestamps:
        return None
    oldest = min(timestamps.values())
    age_seconds = (now - oldest).total_seconds()
    return _clip(1.0 - (age_seconds / _FRESHNESS_STALE_AFTER_SECONDS))


# ---------------------------------------------------------------------
# Agregación
# ---------------------------------------------------------------------


def compute_quality_score(
    record: NormalizedRecord,
    consensus: Optional[ConsensusNoVigResult] = None,
    now: Optional[datetime] = None,
    weights: Optional[Dict[str, float]] = None,
) -> QualityScoreOutput:
    """Calcula `confidence` como promedio ponderado de los 7 componentes
    disponibles, redistribuyendo el peso de los no disponibles entre el
    resto. `confidence=None` únicamente si absolutamente ningún componente
    es calculable (caso degenerado, nunca se fabrica un valor en su
    lugar)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    active_weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)

    components: Dict[str, Optional[float]] = {
        "data_completeness": _component_data_completeness(record),
        "match_confidence_gap": _component_match_confidence_gap(record),
        "missing_critical": _component_missing_critical(record),
        "bookmaker_dispersion": _component_bookmaker_dispersion(consensus),
        "sample_size": _component_sample_size(consensus),
        "market_liquidity": _component_market_liquidity(record),
        "freshness": _component_freshness(record, now),
    }

    available = {name: value for name, value in components.items() if value is not None}
    total_weight = sum(active_weights[name] for name in available)

    if total_weight <= 0:
        return QualityScoreOutput(
            confidence=None,
            confidence_method=CONFIDENCE_METHOD,
            confidence_config_version=CONFIDENCE_CONFIG_VERSION,
            components=components,
            weights={},
        )

    weighted_sum = sum(active_weights[name] * value for name, value in available.items())
    confidence = weighted_sum / total_weight
    effective_weights = {name: active_weights[name] / total_weight for name in available}

    return QualityScoreOutput(
        confidence=confidence,
        confidence_method=CONFIDENCE_METHOD,
        confidence_config_version=CONFIDENCE_CONFIG_VERSION,
        components=components,
        weights=effective_weights,
    )
