"""Contrato de respuesta HTTP de `/analyze` (Fase 5). Ver
`HTTP_SERVICE_SPEC.md` §1.

Capa de PRESENTACIÓN únicamente -- ningún campo aquí se calcula, todos
se leen literalmente de contratos ya cerrados del motor
(`OpportunityEvaluation`, `ConfidenceProfile`, `EvidenceItem`). No
reemplaza ni duplica esos contratos.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class UncertaintyBreakdown(BaseModel):
    data_quality: Optional[float] = None
    model_reliability: Optional[float] = None
    market_quality: Optional[float] = None
    operational_safety: Optional[float] = None
    operational_risk: Optional[float] = None
    aggregate_confidence: Optional[float] = None


class InfluentialVariable(BaseModel):
    fact: str
    direction: str
    source_field: str
    strength: Optional[float] = None


class Freshness(BaseModel):
    analysis_timestamp: datetime
    """Cuándo se generó esta respuesta (inicio del procesamiento de este request)."""
    market_timestamp: datetime
    """`capture_ts` real del fetch en vivo a Kalshi para este ticker -- no
    un timestamp fabricado ni el de una captura histórica anterior."""
    data_freshness_seconds: float
    """`(analysis_timestamp - market_timestamp).total_seconds()` --
    siempre >= 0 por construcción (el mercado se captura antes de
    terminar el análisis)."""


class AnalyzeResponse(BaseModel):
    ticker: str
    event_id: str
    sport: str
    participant_a: Optional[str] = None
    participant_b: Optional[str] = None

    p_model: Optional[float] = None
    p_market: Optional[float] = None
    p_consensus_no_vig: Optional[float] = None
    p_consensus_no_vig_unavailable_reason: Optional[str] = None

    edge: Optional[float] = None
    ev_bruto: Optional[float] = None
    ev_neto: Optional[float] = None
    net_ev_status: str

    recommendation: str
    recommendation_reasons: List[str]

    uncertainty: UncertaintyBreakdown
    most_influential_variables: List[InfluentialVariable]

    model_version: Optional[str] = None
    calibration_version: Optional[str] = None
    policy_version: str
    feature_schema_version: str

    freshness: Freshness
    enrichment_mode: str
    """"full" o "reduced" -- tenis desactiva el enriquecimiento SofaScore
    en la vía en vivo para mantener la latencia razonable; MLB siempre
    "full" (sin lever equivalente). Ver `event_resolver.ResolvedEvent`."""
    processing_time_ms: float
    """Tiempo total de procesamiento de este request (fetch en vivo +
    orquestador), en milisegundos -- para monitoreo de rendimiento."""


class AnalyzeError(BaseModel):
    detail: str
