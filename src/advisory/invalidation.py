"""Stop informativo + invalidación estructurada -- Tramo 5B. Funciones
puras. NUNCA ejecuta un stop ni una invalidación -- ambos son
puramente informativos para que un humano decida, mismo principio que
`PositionPlan` en `src.positions.schemas` ("F7/F10: advisory únicamente,
nunca ejecutable").

Tramo 5B no está wireado a ninguna fuente de evidencia deportiva en vivo
(eso es Market Analysis, fuera del alcance de este paquete) -- por eso
`build_invalidation_conditions` siempre devuelve, como mínimo, la
condición estructurada `CONTEXT_UNAVAILABLE`: nunca se inventa una
condición contextual sin evidencia identificable real.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from src.advisory.config import AdvisoryConfig
from src.advisory.enums import ComparisonOperator, InvalidationConditionCode
from src.advisory.schemas import InvalidationCondition, StopAdvice
from src.models.schemas import Sport
from src.positions.money import require_exact_cents


def _clamp(value: Decimal, lo: int, hi: int) -> Decimal:
    return max(Decimal(lo), min(Decimal(hi), value))


def build_stop_advice(
    *, average_entry_price_cents: Optional[Decimal], config: AdvisoryConfig
) -> Optional[StopAdvice]:
    """`None` si no hay `average_entry_price_cents` (posición sin fills
    BUY confirmados todavía -- nada contra qué anclar un stop). Siempre
    clamped a `[contract_price_min_cents, contract_price_max_cents]` --
    nunca negativo, nunca por encima del máximo válido de un contrato."""
    if average_entry_price_cents is None:
        return None
    require_exact_cents(average_entry_price_cents, "average_entry_price_cents")

    raw_stop = average_entry_price_cents - config.max_adverse_move_cents
    stop_price = _clamp(raw_stop, config.contract_price_min_cents, config.contract_price_max_cents)

    return StopAdvice(
        stop_price_cents=stop_price,
        based_on_avg_entry_price_cents=average_entry_price_cents,
        max_adverse_move_cents=config.max_adverse_move_cents,
    )


def build_invalidation_conditions(*, sport: Sport, evidence_refs: Optional[List[str]] = None) -> List[InvalidationCondition]:
    """Sin evidencia deportiva estructurada disponible (caso universal en
    Tramo 5B, que no integra Market Analysis en vivo): se devuelve
    únicamente la condición `CONTEXT_UNAVAILABLE`, nunca una condición
    fabricada sin `evidence_id` real."""
    if evidence_refs:
        # Punto de extensión preparado para una fase futura que sí reciba
        # evidencia deportiva estructurada -- Tramo 5B no la produce ni
        # la consume todavía, así que este bloque nunca se ejecuta hoy.
        return [
            InvalidationCondition(
                condition_code=InvalidationConditionCode.OTHER,
                evidence_id=ref,
                sport=sport,
                subject="evidence_reference",
                operator=ComparisonOperator.EXISTS,
                expected_value=None,
                human_explanation=f"Evidencia estructurada referenciada: {ref} (revisión manual requerida).",
            )
            for ref in evidence_refs
        ]

    return [
        InvalidationCondition(
            condition_code=InvalidationConditionCode.CONTEXT_UNAVAILABLE,
            evidence_id=None,
            sport=sport,
            subject="sport_context",
            operator=ComparisonOperator.EXISTS,
            expected_value=None,
            human_explanation=(
                "No hay evidencia deportiva estructurada disponible en Tramo 5B -- la invalidación "
                "contextual no puede evaluarse automáticamente. Revisar manualmente el contexto del evento."
            ),
        )
    ]
