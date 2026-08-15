"""Esquema normalizado único para el motor de detección de valor (Fase 1).

Reglas de diseño (ver PLAN.md / instrucciones de Fase 1):
- Ningún campo se rellena con un valor inventado. Si un dato no está
  disponible en la fuente, el campo queda en `None` y su nombre se añade
  a `DataQuality.missing_fields`.
- `ModelOutput` permanece completamente en None en esta fase: no se
  calculan P_model, edge, EV, confidence ni señales de entrada/salida.
- Los precios de Kalshi se conservan tal cual llegan del payload
  (yes_bid/yes_ask/no_bid/no_ask); nunca se reconstruyen como `1 - precio`.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Sport(str, Enum):
    MLB = "MLB"
    TENNIS = "TENNIS"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    FINAL = "FINAL"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class SourceStatus(str, Enum):
    """Estado de una fuente para un registro dado."""

    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class MatchMethod(str, Enum):
    SOURCE_ID = "SOURCE_ID"
    EXACT_NAME_TIME = "EXACT_NAME_TIME"
    FUZZY_NAME_TIME = "FUZZY_NAME_TIME"
    # Tramo 1 del resolver estructural de pares (tenis, SOLO Qualifying/Round
    # Robin -- ver src/matching/tennis_pair_matcher.py). Nunca producido por
    # match_event()/find_best_kalshi_event() ni por el camino de MLB --
    # verificado por
    # tests/unit/test_tennis_pair_matcher.py::test_mlb_pipeline_never_references_tennis_pair_matcher.
    # Distinto de EXACT_NAME_TIME/FUZZY_NAME_TIME porque nunca confirma
    # proximidad temporal (ver CONTINUITY.md, investigación real Faria vs Wu
    # 2026-08-12/15).
    TENNIS_STRUCTURAL_PAIR_UNIQUE = "TENNIS_STRUCTURAL_PAIR_UNIQUE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NO_MATCH = "NO_MATCH"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MarketData(StrictModel):
    """Datos crudos/derivados de mercado. Todo opcional salvo lo calculado."""

    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    last_price: Optional[float] = None

    spread_yes: Optional[float] = None
    spread_no: Optional[float] = None

    volume: Optional[float] = None
    volume_24h: Optional[float] = None
    open_interest: Optional[float] = None
    liquidity: Optional[float] = None

    exchange_fee: Optional[float] = None
    fee_type: Optional[str] = None

    market_price_executable: Optional[float] = None
    """YES_ASK si el lado de interés es YES; NO_ASK si es NO. Ver market_normalizer."""

    robinhood_price_observed: Optional[float] = None
    """Reservado para fases futuras. Nunca poblado automáticamente en Fase 1."""


class BookmakerConsensus(StrictModel):
    bookmaker_odds_raw: Optional[List[Dict[str, Any]]] = None
    consensus_probability_raw: Optional[float] = None
    consensus_probability_no_vig: Optional[float] = None


class ModelInputs(StrictModel):
    """Insumos genéricos, agnósticos de deporte, para un futuro modelo."""

    stats: Optional[Dict[str, Any]] = None
    form: Optional[Dict[str, Any]] = None
    matchup_h2h: Optional[Dict[str, Any]] = None
    lineup_or_pitcher: Optional[Dict[str, Any]] = None
    injuries: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None


class TennisVariables(StrictModel):
    ranking_a: Optional[int] = None
    ranking_b: Optional[int] = None
    last_5: Optional[Dict[str, Any]] = None
    last_10: Optional[Dict[str, Any]] = None
    h2h: Optional[Dict[str, Any]] = None
    surface: Optional[str] = None
    surface_record: Optional[Dict[str, Any]] = None
    aces: Optional[Dict[str, Any]] = None
    double_faults: Optional[Dict[str, Any]] = None
    first_serve_pct: Optional[Dict[str, Any]] = None
    first_serve_points_won: Optional[Dict[str, Any]] = None
    second_serve_points_won: Optional[Dict[str, Any]] = None
    service_games_held: Optional[Dict[str, Any]] = None
    break_points_saved: Optional[Dict[str, Any]] = None
    break_points_converted: Optional[Dict[str, Any]] = None
    return_stats: Optional[Dict[str, Any]] = None
    rest_days: Optional[Dict[str, Any]] = None


class ModelOutput(StrictModel):
    """Debe permanecer enteramente en None hasta Fase 2 (módulo de decisión)."""

    model_probability: Optional[float] = None
    confidence: Optional[float] = None
    uncertainty: Optional[float] = None
    edge: Optional[float] = None
    expected_value: Optional[float] = None
    signal: Optional[str] = None


class DataQuality(StrictModel):
    data_completeness_score: Optional[float] = None
    missing_fields: List[str] = Field(default_factory=list)
    source_status: Dict[str, SourceStatus] = Field(default_factory=dict)
    source_timestamps: Dict[str, datetime] = Field(default_factory=dict)
    last_updated: Optional[datetime] = None

    match_confidence: Optional[float] = None
    match_method: Optional[MatchMethod] = None
    match_warnings: List[str] = Field(default_factory=list)
    needs_review: bool = False

    side_selection_confidence: Optional[float] = None
    """[0,1] o None. Distinto de `match_confidence` (que mide si el EVENTO
    de Kalshi es el correcto): esto mide si el LADO YES del `market_id`
    seleccionado corresponde realmente a `participant_a`
    (`src/matching/market_matcher.py::_select_market`, similitud de nombre
    contra `yes_sub_title`). None cuando no se pudo puntuar (sin mercado
    seleccionado, o `participant_a` ausente en el momento de seleccionar).
    Añadido en Fase 3, Paso de resolución de D-2 (ver CONTINUITY.md) --
    campo aditivo, retrocompatible, no cambia el comportamiento de ningún
    consumidor existente de DataQuality."""

    validation_errors: List[str] = Field(default_factory=list)


class NormalizedRecord(StrictModel):
    sport: Sport
    event_id: str
    source_event_ids: Dict[str, str] = Field(default_factory=dict)
    market_id: Optional[str] = None
    source_market_id: Optional[str] = None

    start_time: Optional[datetime] = None
    market_close_time: Optional[datetime] = None
    expected_settlement_time: Optional[datetime] = None
    actual_settlement_time: Optional[datetime] = None

    status: EventStatus = EventStatus.UNKNOWN

    participant_a: Optional[str] = None
    participant_b: Optional[str] = None

    market: MarketData = Field(default_factory=MarketData)
    bookmaker_consensus: BookmakerConsensus = Field(default_factory=BookmakerConsensus)
    model_inputs: ModelInputs = Field(default_factory=ModelInputs)
    tennis_variables: Optional[TennisVariables] = None
    model_output: ModelOutput = Field(default_factory=ModelOutput)
    data_quality: DataQuality = Field(default_factory=DataQuality)

    raw_refs: Dict[str, str] = Field(default_factory=dict)
    """source -> ruta del archivo JSON RAW correspondiente (reproducibilidad)."""
