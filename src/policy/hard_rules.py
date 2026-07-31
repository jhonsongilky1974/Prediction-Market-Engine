"""Hard Rules -- bloque HARD_BLOCK_PASS (Fase 3, Paso 3.4.2). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.2, y POLICY_ENGINE_SPEC.md §2.1.

Catálogo cerrado de 7 `rule_id` de `HARD_BLOCK_PASS`
(`HARD_BLOCK_RULE_IDS` abajo). Las 6 primeras son funciones puras sobre
`NormalizedRecord`/`HistoryRepository`, agregadas por
`evaluate_hard_block_rules()`. La séptima (`non_recoverable_inconsistency`)
es estructuralmente distinta -- se dispara desde el orquestador (Paso
3.4.5, no implementado todavía) envolviendo una excepción real durante
el ensamblado de `SignalInputs` (Principio 20, fail-safe), no desde un
campo de `NormalizedRecord` -- por eso vive como función independiente
(`check_non_recoverable_inconsistency`), fuera del evaluador agregado.

Bloque HARD_HOLD_WATCH (Paso 3.4.3) vive en un archivo separado
(mismo patrón de nomenclatura, `hard_hold_rules.py`) para mantener cada
subpaso en su propio archivo/commit, tal como acordó el usuario.

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
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.models.schemas import EventStatus, MatchMethod, NormalizedRecord
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
