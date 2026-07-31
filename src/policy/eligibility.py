"""Eligibility (Fase 3, Paso 3.4.1). Ver FASE3_EXECUTION_PLAN.md, Paso
3.4.1, y POLICY_ENGINE_SPEC.md §1.1, etapa [1].

`check_eligibility()` es el primer gate del Policy Engine, antes de
Hard Rules (Paso 3.4.2) y Soft Score (Paso 3.4.4): verifica únicamente
que los 4 campos obligatorios de `SignalInputs` (Fase 2,
`src/signals/signal_schema.py`, sin cambios) -- `event_id`, `sport`,
`side`, `generated_at` -- estén presentes. No evalúa calidad de datos,
no conoce reglas de negocio, no importa nada de `hard_rules.py`/
`soft_score.py`/`decision.py` (esos archivos no existen todavía).

Los 4 campos se reciben como `Optional` deliberadamente: `SignalInputs`
en sí (Fase 2) los exige no-nulos por tipo, así que una instancia ya
construida siempre los tiene -- este gate existe precisamente para
decidir, ANTES de intentar construir un `SignalInputs`, si los datos de
origen (que sí pueden venir incompletos aguas arriba) alcanzan para
evaluarlo en absoluto. Por eso `check_eligibility()` no recibe un
`SignalInputs` como parámetro: si ya se pudo construir uno, la
elegibilidad estructural quedó demostrada por el propio constructor.

Función 100% pura: sin I/O, `now` inyectable (mismo patrón que los pasos
anteriores).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from src.models.schemas import Sport
from src.policy.schemas import EligibilityResult
from src.signals.signal_schema import Side


def check_eligibility(
    opportunity_id: str,
    event_id: Optional[str],
    sport: Optional[Sport],
    side: Optional[Side],
    generated_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> EligibilityResult:
    """is_eligible=False con al menos un motivo en ineligibility_reasons
    por cada uno de los 4 campos ausente; is_eligible=True solo si los 4
    están presentes."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    reasons: List[str] = []

    if event_id is None or not event_id.strip():
        reasons.append("event_id ausente")
    if sport is None:
        reasons.append("sport ausente")
    if side is None:
        reasons.append("side ausente")
    if generated_at is None:
        reasons.append("generated_at ausente")

    return EligibilityResult(
        opportunity_id=opportunity_id,
        is_eligible=not reasons,
        ineligibility_reasons=reasons,
        evaluated_at=now,
    )
