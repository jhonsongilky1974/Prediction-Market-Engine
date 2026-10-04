"""Reglas de elegibilidad PRE-EVENTO de un snapshot de features -- fix de la
fuga temporal del baseline de tenis (ver CONTINUITY.md §0.38).

Causa raíz que este módulo previene: el dataset de entrenamiento original
solo exigía `computed_at < result.recorded_at` (cuándo el SISTEMA se enteró
del resultado), no que el snapshot fuera anterior al INICIO del partido.
Como los resultados se cargaron en bloque (backfill), pasaron snapshots
tomados después del partido -- cuyos features (en particular `rest_days`,
que incluía el SIGUIENTE partido del ganador como "partido previo") ya
codificaban el resultado. Función pura, sin I/O ni dependencias de
`src.features`/`src.pipelines`: reutilizable por el dataset de
entrenamiento, por `compute_tennis_features` y por la inferencia.

Política temporal (decisión explícita, no se ajusta mirando métricas):
- `MIN_SNAPSHOT_LEAD_MINUTES = 60`: un snapshot de ENTRENAMIENTO debe ser
  anterior al `event_start_time` por al menos 60 minutos.
- Estado exigido: `SCHEDULED`.
- Exactamente un snapshot por evento (`select_one_snapshot_per_event`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar

MIN_SNAPSHOT_LEAD_MINUTES = 60
REQUIRED_EVENT_STATUS = "SCHEDULED"

T = TypeVar("T")


class PreeventViolation(str, Enum):
    MISSING_START_TIME = "MISSING_START_TIME"
    STATUS_NOT_SCHEDULED = "STATUS_NOT_SCHEDULED"
    CUTOFF_NOT_BEFORE_START = "CUTOFF_NOT_BEFORE_START"
    COMPUTED_AT_NOT_BEFORE_START = "COMPUTED_AT_NOT_BEFORE_START"
    CAPTURED_AT_NOT_BEFORE_START = "CAPTURED_AT_NOT_BEFORE_START"
    INSUFFICIENT_LEAD = "INSUFFICIENT_LEAD"


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def _status_value(status: Any) -> Optional[str]:
    if status is None:
        return None
    return getattr(status, "value", status)


def preevent_violations(
    *,
    event_start_time: Optional[datetime],
    status: Any,
    data_cutoff_timestamp: Optional[datetime] = None,
    computed_at: Optional[datetime] = None,
    captured_at: Optional[datetime] = None,
    min_lead_minutes: Optional[int] = None,
) -> List[PreeventViolation]:
    """Lista (vacía = elegible) de violaciones de la regla pre-evento.
    Cada timestamp provisto debe ser estrictamente anterior a
    `event_start_time`; `min_lead_minutes` (solo para ENTRENAMIENTO, no
    para inferencia en vivo) exige además `event_start_time - computed_at`
    >= ese margen. Parámetros omitidos (`None`) no se evalúan."""
    violations: List[PreeventViolation] = []

    if event_start_time is None:
        return [PreeventViolation.MISSING_START_TIME]
    _require_aware(event_start_time, "event_start_time")

    if _status_value(status) != REQUIRED_EVENT_STATUS:
        violations.append(PreeventViolation.STATUS_NOT_SCHEDULED)

    for value, name, violation in (
        (data_cutoff_timestamp, "data_cutoff_timestamp", PreeventViolation.CUTOFF_NOT_BEFORE_START),
        (computed_at, "computed_at", PreeventViolation.COMPUTED_AT_NOT_BEFORE_START),
        (captured_at, "captured_at", PreeventViolation.CAPTURED_AT_NOT_BEFORE_START),
    ):
        if value is None:
            continue
        _require_aware(value, name)
        if not (value < event_start_time):
            violations.append(violation)

    if min_lead_minutes is not None and computed_at is not None:
        if computed_at < event_start_time and (event_start_time - computed_at) < timedelta(minutes=min_lead_minutes):
            violations.append(PreeventViolation.INSUFFICIENT_LEAD)

    return violations


def select_one_snapshot_per_event(
    candidates: Iterable[T],
    *,
    event_id_of: Callable[[T], str],
    computed_at_of: Callable[[T], datetime],
    tie_break_of: Callable[[T], Any],
) -> Dict[str, T]:
    """Exactamente UN snapshot válido por evento: el de mayor
    `computed_at` (el más cercano al inicio que ya cumple la anticipación
    mínima), con desempate determinista por `tie_break_of` (id). Regla
    fijada ANTES de ver resultados -- nunca se elige el snapshot según
    cuál produce mejor predicción."""
    chosen: Dict[str, T] = {}
    for candidate in candidates:
        event_id = event_id_of(candidate)
        current = chosen.get(event_id)
        if current is None or (computed_at_of(candidate), tie_break_of(candidate)) > (
            computed_at_of(current),
            tie_break_of(current),
        ):
            chosen[event_id] = candidate
    return chosen
