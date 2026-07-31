"""Hard Rules -- bloques HARD_BLOCK_PASS (Paso 3.4.2) y HARD_HOLD_WATCH
(Paso 3.4.3), Fase 3. Ver FASE3_EXECUTION_PLAN.md, Pasos 3.4.2/3.4.3, y
POLICY_ENGINE_SPEC.md §2.1-§2.2. Ambos bloques viven en este mismo
archivo -- así lo especifica `FASE3_EXECUTION_PLAN.md` (Paso 3.4.3:
"se añade el bloque HOLD al mismo archivo del paso anterior, mismo
módulo lógico"). El docstring original de este módulo (commit del Paso
3.4.2) anotaba erróneamente que el bloque HOLD viviría en un archivo
separado -- corregido aquí durante el Paso 3.4.3, sin ningún efecto en
el código del Paso 3.4.2, que no cambia.

## HARD_BLOCK_PASS

Catálogo cerrado de 7 `rule_id` (`HARD_BLOCK_RULE_IDS` abajo). Las 6
primeras son funciones puras sobre `NormalizedRecord`/`HistoryRepository`,
agregadas por `evaluate_hard_block_rules()`. La séptima
(`non_recoverable_inconsistency`) es estructuralmente distinta -- se
dispara desde el orquestador (Paso 3.4.5, no implementado todavía)
envolviendo una excepción real durante el ensamblado de `SignalInputs`
(Principio 20, fail-safe), no desde un campo de `NormalizedRecord` -- por
eso vive como función independiente (`check_non_recoverable_inconsistency`),
fuera del evaluador agregado.

Dos reglas quedan documentadas como deliberadamente conservadoras o
sin evidencia posible en el esquema actual, en vez de inventar una
heurística no aprobada:

- `invalid_event`: POLICY_ENGINE_SPEC.md §2.1 describe el disparador
  como "EventStatus in (CANCELLED,) o inconsistencia de horario
  irrecuperable". Solo la primera mitad tiene una definición concreta
  hoy -- "inconsistencia de horario irrecuperable" no está definida en
  ningún documento aprobado, así que esta implementación NO la evalúa
  (fabricar un umbral aquí sería precisamente el tipo de decisión no
  aprobada que este proyecto evita). Queda como hueco explícito, no
  oculto.
- `incompatible_contract`: `NormalizedRecord.market` (Fase 1/2,
  `MarketData`) solo modela contratos binarios YES/NO
  (`yes_bid`/`yes_ask`/`no_bid`/`no_ask`) -- no existe ningún campo que
  represente un contrato multi-outcome. Esta regla nunca puede
  dispararse contra el esquema actual: se documenta explícitamente en
  vez de inventar una heurística sin evidencia real.

Funciones 100% puras (salvo `evaluate_hard_block_rules`, que hace un
`SELECT` de solo lectura vía `HistoryRepository`, mismo patrón ya
establecido en Fase 2 para funciones que consultan histórico).

## HARD_HOLD_WATCH

Catálogo cerrado de 6 `rule_id` (`HARD_HOLD_RULE_IDS` abajo), todas
agregadas por `evaluate_hard_hold_rules()` -- a diferencia del bloque
BLOCK, ninguna regla HOLD necesita excluirse del evaluador (todas son
evaluables directamente desde datos, sin depender de una excepción de
control de flujo).

`unresolved_side_mapping` es la más importante de las 6: dispara
`triggered=True` SIEMPRE, sin condición, mientras la Ambigüedad #2 de
Fase 2 (mapeo participante<->YES de un contrato Kalshi concreto) no esté
resuelta -- DECISIÓN PENDIENTE D-2 (`PLAN_MASTER_FASE3.md` §5 Hallazgo
#2, §8). No es un placeholder temporal de esta implementación: es el
comportamiento correcto y exigido explícitamente por
`POLICY_ENGINE_SPEC.md` §2.2 ("unresolved_side_mapping... nunca se
resuelve automáticamente"). Si una refactor futura logra que deje de
dispararse sin que D-2 se haya resuelto explícitamente, eso es una
regresión, nunca una mejora -- reforzado con un test dedicado que cita
esta misma decisión.

Decisión de alcance diferida (aprobada explícitamente antes de
implementar este bloque, ver auditoría previa a este commit):
`POLICY_ENGINE_SPEC.md` §2.2 describe el umbral de horas de
`pending_lineup` como "configurable en PolicyManifest", pero el
contrato `PolicyManifest` (Paso 3.0, ya comiteado) no tiene ningún campo
para parámetros numéricos por regla Hard Rule (solo `critical_minimums`/
`soft_score_weights`, que son del Soft Score). Se implementa aquí con un
parámetro de función (`hours_threshold`, PROVISIONAL, sin respaldo
empírico) en vez de leerlo de un manifiesto -- nada consume
`PolicyManifest` todavía (eso empieza en el Paso 3.4.5), así que decidir
la forma exacta del campo (p.ej. un `Dict[str, float]` genérico
simétrico a `critical_minimums`) queda diferido a ese paso, cuando sea
una necesidad concreta y no hipotética.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.health.schemas import AnalysisHealth
from src.models.schemas import EventStatus, MatchMethod, NormalizedRecord, Sport
from src.policy.schemas import HardRuleCategory, HardRuleResult
from src.pricing.market_pricing import market_price_no, market_price_yes
from src.quality.completeness import CORE_FIELDS
from src.storage.history_repository import HistoryRepository

HARD_BLOCK_RULE_IDS = (
    "unsafe_matching",
    "invalid_event",
    "invalid_or_closed_market",
    "incompatible_contract",
    "corrupted_critical_data",
    "known_result",
    "non_recoverable_inconsistency",
)
"""Catálogo cerrado de HARD_BLOCK_PASS -- exactamente estos 7 rule_id,
ninguno más (POLICY_ENGINE_SPEC.md §2.1)."""

HARD_HOLD_RULE_IDS = (
    "pending_lineup",
    "unconfirmed_pitcher",
    "temporarily_stale_data",
    "temporarily_insufficient_liquidity",
    "recoverable_missing_information",
    "unresolved_side_mapping",
)
"""Catálogo cerrado de HARD_HOLD_WATCH -- exactamente estos 6 rule_id,
ninguno más (POLICY_ENGINE_SPEC.md §2.2)."""

DEFAULT_PENDING_LINEUP_HOURS_THRESHOLD = 3.0
"""Horas antes del inicio del evento por debajo de las cuales
lineup_or_pitcher ausente se considera "pendiente". PROVISIONAL, sin
respaldo empírico -- diferido a PolicyManifest en el Paso 3.4.5 (ver
docstring del módulo)."""

DEFAULT_STALE_DATA_THRESHOLD_SECONDS = 3600.0
"""Mismo valor que _FRESHNESS_STALE_AFTER_SECONDS (quality_score.py) y
STALE_DATA_THRESHOLD_MINUTES*60 (validators.py), ambos Fase 2 -- se
reutiliza el umbral ya establecido en el proyecto en vez de inventar uno
nuevo."""

DEFAULT_MINIMUM_OPERABLE_LIQUIDITY = 1000.0
"""Piso operativo ("prácticamente intransable por debajo de esto"),
deliberadamente distinto y muy inferior a _MARKET_LIQUIDITY_TARGET=50000.0
(quality_score.py, Fase 2, que es un objetivo de normalización para
scoring, no un piso de operabilidad). PROVISIONAL, sin respaldo
empírico."""

_CORE_FIELD_BARE_NAMES = {field.split(".")[-1] for field in CORE_FIELDS}
"""`validation_errors` (Fase 1/2, src/quality/validators.py) son texto
libre sin campo estructurado (p.ej. "yes_ask=1.5 fuera de rango [0,1]"),
nunca dotted-path como en CORE_FIELDS ("market.yes_ask") -- se compara
por el nombre "bare" (último segmento tras el punto). Heurística
PROVISIONAL: un falso positivo es posible si un mensaje de error
menciona el nombre de un campo core sin ser realmente sobre ese campo;
sin evidencia real para una alternativa mejor todavía."""


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def check_unsafe_matching(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    dq = record.data_quality
    unsafe_method = dq.match_method in (MatchMethod.NEEDS_REVIEW, MatchMethod.NO_MATCH)
    low_confidence = dq.match_confidence is not None and dq.match_confidence < EVENT_NAME_MATCH_MIN_CONFIDENCE
    triggered = unsafe_method or low_confidence
    detail = (
        f"match_method={dq.match_method}, match_confidence={dq.match_confidence} "
        f"(mínimo={EVENT_NAME_MATCH_MIN_CONFIDENCE})"
    )
    return HardRuleResult(
        rule_id="unsafe_matching",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_invalid_event(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    triggered = record.status == EventStatus.CANCELLED
    detail = f"status={record.status.value}"
    return HardRuleResult(
        rule_id="invalid_event",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_invalid_or_closed_market(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    both_prices_missing = market_price_yes(record) is None and market_price_no(record) is None
    already_settled = record.actual_settlement_time is not None
    triggered = both_prices_missing or already_settled
    detail = f"ambos precios ausentes={both_prices_missing}, actual_settlement_time={record.actual_settlement_time}"
    return HardRuleResult(
        rule_id="invalid_or_closed_market",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_incompatible_contract(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    return HardRuleResult(
        rule_id="incompatible_contract",
        category=HardRuleCategory.BLOCK,
        triggered=False,
        detail="NormalizedRecord.market solo modela contratos binarios YES/NO en Fase 1/2; sin evidencia posible hoy",
        evaluated_at=now,
    )


def check_corrupted_critical_data(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    errors = record.data_quality.validation_errors
    matching_errors = [
        error for error in errors if any(bare_name in error for bare_name in _CORE_FIELD_BARE_NAMES)
    ]
    triggered = bool(matching_errors)
    detail = f"validation_errors sobre CORE_FIELDS: {matching_errors}" if matching_errors else "sin validation_errors sobre CORE_FIELDS"
    return HardRuleResult(
        rule_id="corrupted_critical_data",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_known_result(
    record: NormalizedRecord,
    data_cutoff_timestamp: datetime,
    history_repository: HistoryRepository,
    now: datetime,
) -> HardRuleResult:
    """Dispara si existe un event_results (Fase 2, HistoryRepository)
    con recorded_at <= data_cutoff_timestamp -- un resultado registrado
    ANTES del cutoff ya era conocimiento público en ese instante, así
    que evaluar esta oportunidad no tiene sentido (bloqueo correcto, no
    una fuga). Un resultado con recorded_at POSTERIOR al cutoff se
    ignora correctamente -- usarlo sí sería una fuga temporal
    (TEMPORAL_REPRODUCIBILITY_SPEC.md §2.2)."""
    results = history_repository.get_results_for_event(record.event_id)
    known_before_cutoff = [
        r for r in results if datetime.fromisoformat(r["recorded_at"]) <= data_cutoff_timestamp
    ]
    triggered = bool(known_before_cutoff)
    detail = (
        f"{len(known_before_cutoff)} de {len(results)} event_results conocidos antes de data_cutoff_timestamp"
    )
    return HardRuleResult(
        rule_id="known_result",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_non_recoverable_inconsistency(
    exc: Optional[BaseException], now: datetime
) -> HardRuleResult:
    """Fuente de evidencia "interno" (POLICY_ENGINE_SPEC.md §2.1): no
    lee NormalizedRecord ni HistoryRepository -- recibe la excepción
    capturada (o None) por el orquestador (Paso 3.4.5) al envolver el
    ensamblado de SignalInputs."""
    triggered = exc is not None
    detail = f"{type(exc).__name__}: {exc}" if exc is not None else None
    return HardRuleResult(
        rule_id="non_recoverable_inconsistency",
        category=HardRuleCategory.BLOCK,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def evaluate_hard_block_rules(
    record: NormalizedRecord,
    data_cutoff_timestamp: datetime,
    history_repository: HistoryRepository,
    now: Optional[datetime] = None,
) -> List[HardRuleResult]:
    """Evalúa las 6 reglas HARD_BLOCK_PASS basadas en datos --
    non_recoverable_inconsistency queda fuera (ver docstring del
    módulo), invocada aparte por el orquestador."""
    now = now or datetime.now(timezone.utc)
    _require_utc_aware(now, "now")
    _require_utc_aware(data_cutoff_timestamp, "data_cutoff_timestamp")

    return [
        check_unsafe_matching(record, now),
        check_invalid_event(record, now),
        check_invalid_or_closed_market(record, now),
        check_incompatible_contract(record, now),
        check_corrupted_critical_data(record, now),
        check_known_result(record, data_cutoff_timestamp, history_repository, now),
    ]


# ---------------------------------------------------------------------
# HARD_HOLD_WATCH (Paso 3.4.3)
# ---------------------------------------------------------------------


def check_pending_lineup(
    record: NormalizedRecord,
    now: datetime,
    hours_threshold: float = DEFAULT_PENDING_LINEUP_HOURS_THRESHOLD,
) -> HardRuleResult:
    """lineup_or_pitcher ausente Y el evento empieza dentro de
    hours_threshold horas (0 <= start_time - now <= threshold). Si
    start_time es None, no hay forma de evaluar proximidad -- no se
    dispara (no se adivina)."""
    lineup_missing = record.model_inputs.lineup_or_pitcher is None
    within_window = False
    if record.start_time is not None:
        delta = record.start_time - now
        within_window = timedelta(0) <= delta <= timedelta(hours=hours_threshold)
    triggered = lineup_missing and within_window
    detail = f"lineup_or_pitcher ausente={lineup_missing}, start_time={record.start_time}, hours_threshold={hours_threshold}"
    return HardRuleResult(
        rule_id="pending_lineup",
        category=HardRuleCategory.HOLD,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_unconfirmed_pitcher(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    """Específico MLB (POLICY_ENGINE_SPEC.md §2.2) -- a diferencia de
    pending_lineup, no está condicionado a la proximidad del evento:
    dispara siempre que sea MLB y el pitcher probable no esté
    confirmado, sin importar cuánto falte para el inicio."""
    triggered = record.sport == Sport.MLB and record.model_inputs.lineup_or_pitcher is None
    detail = f"sport={record.sport.value}, lineup_or_pitcher ausente={record.model_inputs.lineup_or_pitcher is None}"
    return HardRuleResult(
        rule_id="unconfirmed_pitcher",
        category=HardRuleCategory.HOLD,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_temporarily_stale_data(
    analysis_health: AnalysisHealth,
    now: datetime,
    threshold_seconds: float = DEFAULT_STALE_DATA_THRESHOLD_SECONDS,
) -> HardRuleResult:
    staleness = analysis_health.staleness_seconds
    triggered = staleness is not None and staleness > threshold_seconds
    detail = f"staleness_seconds={staleness}, threshold={threshold_seconds}"
    return HardRuleResult(
        rule_id="temporarily_stale_data",
        category=HardRuleCategory.HOLD,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_temporarily_insufficient_liquidity(
    record: NormalizedRecord,
    now: datetime,
    minimum: float = DEFAULT_MINIMUM_OPERABLE_LIQUIDITY,
) -> HardRuleResult:
    """volume como base principal, open_interest como respaldo -- mismo
    patrón de fallback que _component_market_liquidity (quality_score.py,
    Fase 2). Ausencia total de dato (basis=None) NO dispara esta regla
    -- eso no es "liquidez insuficiente", es "sin dato", cubierto en su
    lugar por recoverable_missing_information."""
    basis = record.market.volume
    if basis is None:
        basis = record.market.open_interest
    triggered = basis is not None and basis < minimum
    detail = f"basis={basis} (volume={record.market.volume}, open_interest={record.market.open_interest}), minimum={minimum}"
    return HardRuleResult(
        rule_id="temporarily_insufficient_liquidity",
        category=HardRuleCategory.HOLD,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_recoverable_missing_information(record: NormalizedRecord, now: datetime) -> HardRuleResult:
    """missing_fields (Fase 1/2) que NO están en CORE_FIELDS -- campos
    "no-críticos ausentes" (POLICY_ENGINE_SPEC.md §2.2, literal). Los
    campos CORE_FIELDS ausentes ya están cubiertos por
    corrupted_critical_data (BLOCK) cuando generan un validation_error;
    esta regla es deliberadamente el complemento, no un duplicado."""
    missing = record.data_quality.missing_fields
    non_critical_missing = [f for f in missing if f not in CORE_FIELDS]
    triggered = bool(non_critical_missing)
    detail = f"campos no-críticos ausentes: {non_critical_missing}" if non_critical_missing else "sin campos no-críticos ausentes"
    return HardRuleResult(
        rule_id="recoverable_missing_information",
        category=HardRuleCategory.HOLD,
        triggered=triggered,
        detail=detail,
        evaluated_at=now,
    )


def check_unresolved_side_mapping(now: datetime) -> HardRuleResult:
    """SIEMPRE triggered=True mientras la Ambigüedad #2 de Fase 2
    (mapeo participante<->YES de un contrato Kalshi concreto) no esté
    resuelta -- DECISIÓN PENDIENTE D-2 (PLAN_MASTER_FASE3.md §5 Hallazgo
    #2, §8). No es condicional a ningún dato de entrada: ver el
    docstring del módulo para la advertencia completa contra
    "arreglar" esto por accidente."""
    return HardRuleResult(
        rule_id="unresolved_side_mapping",
        category=HardRuleCategory.HOLD,
        triggered=True,
        detail="Ambigüedad #2 (mapeo participante<->YES de Kalshi) sin resolver -- DECISIÓN PENDIENTE D-2",
        evaluated_at=now,
    )


def evaluate_hard_hold_rules(
    record: NormalizedRecord,
    analysis_health: AnalysisHealth,
    now: Optional[datetime] = None,
    pending_lineup_hours_threshold: float = DEFAULT_PENDING_LINEUP_HOURS_THRESHOLD,
    stale_data_threshold_seconds: float = DEFAULT_STALE_DATA_THRESHOLD_SECONDS,
    minimum_operable_liquidity: float = DEFAULT_MINIMUM_OPERABLE_LIQUIDITY,
) -> List[HardRuleResult]:
    """Evalúa las 6 reglas HARD_HOLD_WATCH -- todas basadas en datos,
    ninguna se excluye del evaluador (a diferencia de
    evaluate_hard_block_rules)."""
    now = now or datetime.now(timezone.utc)
    _require_utc_aware(now, "now")

    return [
        check_pending_lineup(record, now, pending_lineup_hours_threshold),
        check_unconfirmed_pitcher(record, now),
        check_temporarily_stale_data(analysis_health, now, stale_data_threshold_seconds),
        check_temporarily_insufficient_liquidity(record, now, minimum_operable_liquidity),
        check_recoverable_missing_information(record, now),
        check_unresolved_side_mapping(now),
    ]
