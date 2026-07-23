"""Consenso no-vig en dos pasos + gate de matching de evento (Fase 2, Paso 4).

Implementa el Paso B de PLAN_PHASE2.md §8 (agregación por mediana entre
bookmakers, tras el de-vig individual de `no_vig.py`) y el "gate de
matching de evento", reutilizando `src.matching.event_matcher.match_event`
sin modificarlo.

```
P_consensus_no_vig_YES = mediana({p_no_vig_YES_i : i en bookmakers})
P_consensus_no_vig_NO  = mediana({p_no_vig_NO_i  : i en bookmakers})
```

DECISIÓN DE ARQUITECTURA (Opción A, aprobada explícitamente por el
usuario tras el hallazgo de la revisión contractual del Paso 4):

Las fórmulas de §8 asumen `decimal_odds_YES_i`/`decimal_odds_NO_i` YA
etiquetados por bookmaker. En la práctica, `OddsApiConnector.extract_h2h_prices`
(Fase 1, `src/connectors/odds_api.py`) entrega las cuotas por NOMBRE de
participante (`outcomes = [{"name": ..., "price": ...}, ...]`), no por
YES/NO -- y `NormalizedRecord` (Fase 1, `src/models/schemas.py`) no
expone ningún campo que indique a qué participante corresponde la
posición YES de un ticker de Kalshi (`market_normalizer.py` documenta
que "cada ticker ya representa una posición YES concreta", pero esa
dirección -- ¿YES = participant_a o participant_b? -- no queda
capturada en ningún campo estructurado). Mapear nombre -> YES/NO sin esa
información sería inventar una convención no verificada (p.ej.
"YES=participant_a"), algo que PLAN_PHASE2.md prohíbe explícitamente.

**Por lo tanto, este módulo NUNCA deriva `decimal_odds_yes`/`decimal_odds_no`
a partir de `bookmaker_odds_raw` real.** Los recibe ya etiquetados, vía
`LabeledBookmakerOdds`, como contrato de entrada explícito.
**Responsabilidad delegada a una capa de integración futura, fuera de
alcance del Paso 4:** resolver, para cada `NormalizedRecord`, qué nombre
de participante de The Odds API corresponde a YES y cuál a NO (por
ejemplo a partir del título/ticker real del mercado de Kalshi -- dato
que Fase 1 no captura hoy de forma estructurada). Hasta que esa capa
exista, este módulo es completamente funcional y testeable con fixtures
ya etiquetados, pero no puede consumirse end-to-end con datos reales de
`bookmaker_odds_raw`.

**Gate de matching de evento (§8):** el matching ocurre UNA VEZ por
evento fuente (el evento de The Odds API que agrupa a todos los
bookmakers de `bookmaker_odds`) contra el `NormalizedRecord` objetivo,
reutilizando `match_event` (Fase 1, sin modificar). Si el resultado no
es confidente (`NEEDS_REVIEW`/`NO_MATCH`), TODOS los bookmakers de esa
lista quedan excluidos, con el mismo motivo registrado -- nunca se
mezclan odds de un evento ambiguamente identificado. Independientemente
del resultado del matching, cualquier bookmaker con cuotas ausentes o
inválidas se excluye individualmente (vía `no_vig.devig_bookmaker`), con
su propio motivo -- nunca se fabrica un valor.

**Elecciones de diseño no fijadas literalmente por el plan, documentadas
aquí en vez de dejarlas implícitas:**
  - `dispersion` usa desviación estándar poblacional (`statistics.pstdev`)
    sobre los bookmakers efectivamente incluidos, no muestral -- se trata
    como la población completa de bookmakers que pasaron el gate, no una
    muestra de un universo mayor. Requiere >= 2 bookmakers incluidos;
    con 0 o 1, `dispersion=None` (desviación estándar no está definida).
  - `per_bookmaker_timestamps` incluye a TODOS los bookmakers recibidos
    en `bookmaker_odds` (incluidos los excluidos), para que la salida sea
    auditable; `exclusion_reasons` distingue cuáles fueron excluidos y
    por qué.
  - `freshness` es la antigüedad (en segundos, respecto a `as_of`) del
    timestamp más antiguo entre los bookmakers EFECTIVAMENTE INCLUIDOS
    en el consenso ("el dato más viejo usado", §8) que tengan
    `last_update` no nulo; `None` si no hay ninguno incluido con
    timestamp.
  - `source_quality`: se reutiliza el enum `SourceStatus` ya existente
    en el esquema de Fase 1 (`src.models.schemas.SourceStatus`) en vez de
    definir un vocabulario nuevo -- sus valores (`OK`/`PARTIAL`/`FAILED`/
    `NOT_CONFIGURED`) coinciden exactamente con los que pide §8.
    `NOT_CONFIGURED` se usa solo cuando `ODDS_API_KEY` no está
    configurada (gate previo, ni siquiera se intenta el matching);
    `FAILED` cuando la API sí está configurada pero 0 bookmakers
    sobreviven el gate de matching o la validación de cuotas.

Cómputo puro: sin llamadas de red, sin persistencia. El booleano
`odds_api_key_configured` se recibe como parámetro (lo determina el
caller vía `config.settings.get_odds_api_key()`), no se lee aquí
directamente, para mantener este módulo testeable sin variables de
entorno.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median, pstdev
from typing import Dict, List, Optional, Sequence

from src.matching.event_matcher import match_event
from src.models.schemas import NormalizedRecord, SourceStatus
from src.pricing.no_vig import devig_bookmaker


@dataclass(frozen=True)
class LabeledBookmakerOdds:
    """Cuotas decimales de un bookmaker, YA etiquetadas por lado YES/NO.

    Esa etiquetación es responsabilidad de la capa de integración (ver
    docstring del módulo) -- este tipo es el contrato de entrada que el
    Paso 4 exige recibir, nunca lo construye a partir de datos crudos de
    `bookmaker_odds_raw`.
    """

    bookmaker: str
    decimal_odds_yes: Optional[float]
    decimal_odds_no: Optional[float]
    last_update: Optional[datetime]


@dataclass(frozen=True)
class ConsensusNoVigResult:
    """Salida obligatoria de §8, side-aware."""

    p_consensus_no_vig_yes: Optional[float]
    p_consensus_no_vig_no: Optional[float]
    bookmaker_count: int
    per_bookmaker_timestamps: Dict[str, Optional[datetime]]
    freshness: Optional[float]
    dispersion: Optional[float]
    event_match_confidence: Optional[float]
    exclusion_reasons: Dict[str, str] = field(default_factory=dict)
    source_quality: SourceStatus = SourceStatus.NOT_ATTEMPTED


def _require_utc_aware(dt: datetime, field_name: str) -> None:
    """Rechaza timestamps naive -- mismo principio no-negociable aplicado
    en Paso 0/Paso 2: nunca se asume una zona horaria."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {dt!r}")


def _not_configured_result() -> ConsensusNoVigResult:
    return ConsensusNoVigResult(
        p_consensus_no_vig_yes=None,
        p_consensus_no_vig_no=None,
        bookmaker_count=0,
        per_bookmaker_timestamps={},
        freshness=None,
        dispersion=None,
        event_match_confidence=None,
        exclusion_reasons={},
        source_quality=SourceStatus.NOT_CONFIGURED,
    )


def _source_quality_for_count(count: int) -> SourceStatus:
    if count >= 3:
        return SourceStatus.OK
    if count >= 1:
        return SourceStatus.PARTIAL
    return SourceStatus.FAILED


def compute_consensus_no_vig(
    *,
    odds_api_key_configured: bool,
    source_participant_a: Optional[str],
    source_participant_b: Optional[str],
    source_start_time: Optional[datetime],
    target_record: NormalizedRecord,
    bookmaker_odds: Sequence[LabeledBookmakerOdds],
    as_of: datetime,
) -> ConsensusNoVigResult:
    """Orquesta Paso A (por bookmaker) + gate de matching + Paso B (§8).

    `bookmaker_odds` debe llegar ya etiquetado YES/NO (ver docstring del
    módulo) -- ninguna cuota se reinterpreta ni se reetiqueta aquí.
    """
    _require_utc_aware(as_of, "as_of")

    if not odds_api_key_configured:
        return _not_configured_result()

    match_result = match_event(
        source_participant_a,
        source_participant_b,
        source_start_time,
        target_record.participant_a,
        target_record.participant_b,
        target_record.start_time,
    )

    per_bookmaker_timestamps: Dict[str, Optional[datetime]] = {
        bm.bookmaker: bm.last_update for bm in bookmaker_odds
    }

    if not match_result.is_confident:
        exclusion_reasons = {
            bm.bookmaker: f"event_match_failed:{match_result.method.value}" for bm in bookmaker_odds
        }
        return ConsensusNoVigResult(
            p_consensus_no_vig_yes=None,
            p_consensus_no_vig_no=None,
            bookmaker_count=0,
            per_bookmaker_timestamps=per_bookmaker_timestamps,
            freshness=None,
            dispersion=None,
            event_match_confidence=match_result.confidence,
            exclusion_reasons=exclusion_reasons,
            source_quality=SourceStatus.FAILED,
        )

    included_yes: List[float] = []
    included_no: List[float] = []
    included_timestamps: List[datetime] = []
    exclusion_reasons = {}

    for bm in bookmaker_odds:
        result = devig_bookmaker(bm.decimal_odds_yes, bm.decimal_odds_no)
        if result.p_no_vig_yes is None or result.p_no_vig_no is None:
            exclusion_reasons[bm.bookmaker] = "invalid_or_missing_odds"
            continue
        included_yes.append(result.p_no_vig_yes)
        included_no.append(result.p_no_vig_no)
        if bm.last_update is not None:
            included_timestamps.append(bm.last_update)

    bookmaker_count = len(included_yes)

    p_consensus_yes = median(included_yes) if included_yes else None
    p_consensus_no = median(included_no) if included_no else None
    dispersion = pstdev(included_yes) if len(included_yes) >= 2 else None

    freshness: Optional[float] = None
    if included_timestamps:
        oldest = min(included_timestamps)
        freshness = (as_of - oldest).total_seconds()

    return ConsensusNoVigResult(
        p_consensus_no_vig_yes=p_consensus_yes,
        p_consensus_no_vig_no=p_consensus_no,
        bookmaker_count=bookmaker_count,
        per_bookmaker_timestamps=per_bookmaker_timestamps,
        freshness=freshness,
        dispersion=dispersion,
        event_match_confidence=match_result.confidence,
        exclusion_reasons=exclusion_reasons,
        source_quality=_source_quality_for_count(bookmaker_count),
    )
