"""Explainability Engine (Fase 3, Paso 3.6). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.6, y EVIDENCE_EXPLAINABILITY_SPEC.md §2.

`explain()` consume ÚNICAMENTE `PolicyDecision` (Paso 3.0/3.4.5) y
`EvidenceItem[]` (Paso 3.0/3.3) ya calculados -- nunca re-deriva nada
desde `NormalizedRecord` ni desde ningún dato crudo (Principio 6: el
Explainability Engine está separado del Evidence Engine, y ambos del
resto del sistema). Toda razón mostrada en `ExplanationOutput` es
trazable a un `SignalReason` real (`policy_decision.reasons`) o a un
`EvidenceItem` real -- ninguna prosa libre inventada sobre datos que
esta función no recibió.

`calibration_version`/`net_ev_status_is_unknown` se reciben como
parámetros PRIMITIVOS (str/bool), no como los tipos `CalibrationOutput`/
`NetEvStatus` completos -- mismo principio ya usado en
`src/signals/signal_schema.py` (Fase 2: "todos los valores derivados...
viajan como primitivos ya extraídos"). Evita que este módulo dependa de
`src/calibration/schemas.py`/`src/payoff/schemas.py`, manteniendo la
regla de dependencia de `ARCHITECTURE_FASE3.md` §4 sin necesitar
ampliarla.

Función 100% pura: sin I/O, `now` inyectable (mismo patrón que los pasos
anteriores).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from src.evidence.schemas import EvidenceDirection, EvidenceItem
from src.explainability.schemas import ExplanationOutput
from src.policy.schemas import PolicyDecision


def explain(
    policy_decision: PolicyDecision,
    evidence_items: List[EvidenceItem],
    evaluation_id: str,
    calibration_version: Optional[str] = None,
    net_ev_status_is_unknown: bool = False,
    now: Optional[datetime] = None,
) -> ExplanationOutput:
    """disclaimers no vacío cuando calibration_version is None o
    net_ev_status_is_unknown=True -- el sistema nunca presenta una
    probabilidad sin calibrar o un EV desconocido como si fueran
    definitivos (EVIDENCE_EXPLAINABILITY_SPEC.md §2.1, literal)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    headline = _build_headline(policy_decision)
    reasons_explained = [
        f"{reason.code.value}: {reason.detail}" for reason in policy_decision.reasons
    ]
    evidence_for = [item.fact for item in evidence_items if item.direction == EvidenceDirection.FOR]
    evidence_against = [item.fact for item in evidence_items if item.direction == EvidenceDirection.AGAINST]

    disclaimers: List[str] = []
    if calibration_version is None:
        disclaimers.append(
            "Probabilidad del modelo sin calibrar (calibration_version=None) -- no se trata como definitiva."
        )
    if net_ev_status_is_unknown:
        disclaimers.append(
            "Valor esperado neto desconocido (net_ev_status=UNKNOWN) -- no se pudo incorporar el costo real "
            "de la operación."
        )

    return ExplanationOutput(
        opportunity_id=policy_decision.opportunity_id,
        evaluation_id=evaluation_id,
        headline=headline,
        reasons_explained=reasons_explained,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        disclaimers=disclaimers,
        generated_at=now,
    )


def _build_headline(policy_decision: PolicyDecision) -> str:
    """Construida enteramente desde campos de PolicyDecision -- nunca
    desde datos externos a ese contrato."""
    parts = [policy_decision.signal_type.value]
    if policy_decision.disposition is not None:
        parts.append(f"({policy_decision.disposition.value})")
    if policy_decision.aggregate_soft_score is not None:
        parts.append(f"— score {policy_decision.aggregate_soft_score:.1f}/100")
    return " ".join(parts)
