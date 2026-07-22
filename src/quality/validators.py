"""Reglas de validación de calidad de datos sobre `NormalizedRecord`.

Cada validador devuelve una lista de strings de error (vacía si todo OK).
Los validadores nunca "arreglan" el dato ni inventan valores: solo detectan
y reportan. El pipeline decide qué hacer con los errores (loggear, marcar
needs_review, excluir del resultado final, etc).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.models.schemas import NormalizedRecord

STALE_DATA_THRESHOLD_MINUTES = 60


def validate_price_ranges(record: NormalizedRecord) -> List[str]:
    errors: List[str] = []
    m = record.market
    for field_name in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price"):
        value = getattr(m, field_name)
        if value is None:
            continue
        if not (0.0 <= value <= 1.0):
            errors.append(f"{field_name}={value} fuera de rango [0,1]")
    return errors


def validate_bid_ask_consistency(record: NormalizedRecord) -> List[str]:
    errors: List[str] = []
    m = record.market
    if m.yes_bid is not None and m.yes_ask is not None and m.yes_ask < m.yes_bid:
        errors.append(f"yes_ask ({m.yes_ask}) < yes_bid ({m.yes_bid})")
    if m.no_bid is not None and m.no_ask is not None and m.no_ask < m.no_bid:
        errors.append(f"no_ask ({m.no_ask}) < no_bid ({m.no_bid})")
    return errors


def validate_timestamps(record: NormalizedRecord) -> List[str]:
    errors: List[str] = []
    st = record.start_time
    close = record.market_close_time
    expected_settlement = record.expected_settlement_time

    if st is not None and close is not None and close < st:
        errors.append(f"market_close_time ({close}) es anterior a start_time ({st})")
    if st is not None and expected_settlement is not None and expected_settlement < st - timedelta(hours=1):
        errors.append(
            f"expected_settlement_time ({expected_settlement}) es notablemente anterior a start_time ({st})"
        )
    return errors


def validate_participants(record: NormalizedRecord) -> List[str]:
    errors: List[str] = []
    if not record.participant_a:
        errors.append("participant_a vacío")
    if not record.participant_b:
        errors.append("participant_b vacío")
    if record.participant_a and record.participant_b and record.participant_a == record.participant_b:
        errors.append("participant_a y participant_b son idénticos")
    return errors


def validate_staleness(record: NormalizedRecord, now: Optional[datetime] = None) -> List[str]:
    """Compara `now` contra la captura RAW más antigua usada para construir
    este registro (`data_quality.source_timestamps`).

    Deliberadamente NO se compara contra `last_updated`: ese campo lo
    estampa el pipeline justo antes de normalizar/validar (ver
    mlb_pipeline.py / tennis_pipeline.py), así que en producción siempre
    vale "ahora mismo" -- comparar "ahora" contra "ahora" nunca puede
    detectar nada y el check quedaba muerto en la práctica (ver auditoría
    de Fase 1). `source_timestamps` sí refleja cuándo se capturó el dato
    crudo de cada fuente, que es lo que realmente puede quedar stale."""
    errors: List[str] = []
    now = now or datetime.now(timezone.utc)
    timestamps = record.data_quality.source_timestamps
    if not timestamps:
        return errors
    oldest_source, oldest_ts = min(timestamps.items(), key=lambda kv: kv[1])
    age_minutes = (now - oldest_ts).total_seconds() / 60.0
    if age_minutes > STALE_DATA_THRESHOLD_MINUTES:
        errors.append(
            f"dato de fuente '{oldest_source}' con antigüedad de {age_minutes:.0f} min "
            f"(> {STALE_DATA_THRESHOLD_MINUTES} min)"
        )
    return errors


def find_duplicate_markets(records: List[NormalizedRecord]) -> List[str]:
    """Detecta mercados duplicados dentro de un lote: mismo market_id en más
    de un registro."""
    errors: List[str] = []
    seen: Dict[str, int] = {}
    for record in records:
        if not record.market_id:
            continue
        seen[record.market_id] = seen.get(record.market_id, 0) + 1
    for market_id, count in seen.items():
        if count > 1:
            errors.append(f"market_id duplicado: {market_id} aparece {count} veces")
    return errors


def annotate_duplicate_markets(records: List[NormalizedRecord]) -> List[str]:
    """Corre `find_duplicate_markets` sobre el lote y añade el error a
    `validation_errors` de cada registro CUYO market_id esté duplicado (in
    place). Se llama una vez por pipeline, después de procesar todos los
    registros del lote -- antes de este fix, `find_duplicate_markets`
    estaba implementado pero ningún pipeline lo invocaba nunca, así que
    "mercados duplicados" (criterio de aceptación explícito de Fase 1)
    nunca se detectaba en la práctica. Devuelve también la lista de errores
    a nivel de lote, por si se quiere loggear aparte."""
    batch_errors = find_duplicate_markets(records)
    if not batch_errors:
        return batch_errors

    counts: Dict[str, int] = {}
    for record in records:
        if record.market_id:
            counts[record.market_id] = counts.get(record.market_id, 0) + 1

    for record in records:
        if record.market_id and counts.get(record.market_id, 0) > 1:
            record.data_quality.validation_errors.append(
                f"market_id duplicado en el lote: {record.market_id} aparece {counts[record.market_id]} veces"
            )
    return batch_errors


def validate_schema_sanity(raw_payload: Optional[Dict[str, Any]], required_keys: List[str], source: str) -> List[str]:
    """Chequeo defensivo genérico para detectar cambios de schema en una
    fuente: no lanza, solo reporta claves top-level esperadas que faltan."""
    errors: List[str] = []
    if raw_payload is None:
        return [f"{source}: payload vacío/None"]
    if not isinstance(raw_payload, dict):
        return [f"{source}: payload no es un objeto JSON (tipo {type(raw_payload).__name__})"]
    for key in required_keys:
        if key not in raw_payload:
            errors.append(f"{source}: posible cambio de schema, falta clave esperada '{key}'")
    return errors


def validate_record(record: NormalizedRecord) -> List[str]:
    """Corre todas las validaciones aplicables a nivel de registro individual."""
    errors: List[str] = []
    errors.extend(validate_price_ranges(record))
    errors.extend(validate_bid_ask_consistency(record))
    errors.extend(validate_timestamps(record))
    errors.extend(validate_participants(record))
    errors.extend(validate_staleness(record))
    return errors
