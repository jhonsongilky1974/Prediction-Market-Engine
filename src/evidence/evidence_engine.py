"""Evidence Engine (Fase 3, Paso 3.3). Ver FASE3_EXECUTION_PLAN.md, Paso
3.3, y EVIDENCE_EXPLAINABILITY_SPEC.md §1.

`collect_evidence()` produce `EvidenceItem[]` (Paso 3.0,
`src/evidence/schemas.py`, sin cambios) a partir de un `NormalizedRecord`
(Fase 1/2, sin cambios), un `CalibrationOutput` (Paso 3.1) y un
`ConfidenceProfile` (Paso 3.0) -- sin ningún conocimiento de
`PolicyDecision` ni de umbrales de política (Principio 6: separado del
Explainability Engine, que no existe todavía -- Paso 3.6).

Regla no negociable (mismo principio de toda Fase 1/2: "MISSING nunca se
convierte en un valor fabricado"), aplicada aquí a hechos en vez de a
números: cada `EvidenceItem` se genera únicamente cuando su campo fuente
NO es `None`. La ausencia de un dato nunca genera evidencia AGAINST "de
relleno" -- simplemente no se genera ningún item para esa plantilla.

Cuatro plantillas (`EVIDENCE_EXPLAINABILITY_SPEC.md` §1.1):
  1. Pitcher probable confirmado (MLB) -- FOR.
  2. Confianza de emparejamiento marginal -- AGAINST.
  3. Modelo con historial de performance evaluado -- FOR.
  4. Divergencia significativa entre modelo y consenso de mercado -- AGAINST.

Los umbrales de las plantillas 2-4 son heurísticas de ingeniería
PROVISIONAL, sin respaldo empírico (mismo espíritu que otras constantes
PROVISIONAL ya existentes en el proyecto, p.ej. `_MARKET_LIQUIDITY_TARGET`
en `src/uncertainty/quality_score.py`, Fase 2) -- a revisar cuando exista
evidencia real (depende de DECISIÓN PENDIENTE D-1).

Adaptación respecto al texto original de `EVIDENCE_EXPLAINABILITY_SPEC.md`
§1.1 (plantilla 3): el texto de diseño mencionaba "({n} muestras)", pero
`ConfidenceProfile` (contrato ya comiteado en el Paso 3.0) no expone un
conteo de muestras, solo el score `model_reliability` en [0,100] -- se
usa ese score en el texto del hecho en su lugar, para no fabricar un
número que esta función no recibe. No es una contradicción de contrato:
la plantilla del spec siempre fue ilustrativa ("por plantilla"), no un
campo obligatorio.

Función 100% pura: sin I/O, `now` inyectable (mismo patrón que
`calibration_layer.py`/`payoff_model.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.calibration.schemas import CalibrationOutput
from src.evidence.schemas import EvidenceDirection, EvidenceItem
from src.models.schemas import NormalizedRecord
from src.policy.schemas import ConfidenceProfile

_MATCH_CONFIDENCE_MARGINAL_BAND = 0.10
"""Banda por encima de EVENT_NAME_MATCH_MIN_CONFIDENCE considerada
"marginal" -- PROVISIONAL, sin respaldo empírico."""

_MODEL_RELIABILITY_FOR_THRESHOLD = 50.0
"""Umbral en escala [0,100] por encima del cual model_reliability se
reporta como evidencia FOR -- PROVISIONAL, sin respaldo empírico."""

_CONSENSUS_DIVERGENCE_AGAINST_THRESHOLD = 0.10
"""Divergencia absoluta entre p_model_calibrated y
consensus_probability_no_vig por encima de la cual se reporta AGAINST --
mismo valor que _DISPERSION_ZERO_AT en quality_score.py (Fase 2),
reutilizado por consistencia de escala, no recalculado."""


def collect_evidence(
    opportunity_id: str,
    record: NormalizedRecord,
    calibration_output: CalibrationOutput,
    confidence_profile: ConfidenceProfile,
    now: Optional[datetime] = None,
) -> List[EvidenceItem]:
    """Ningún EvidenceItem referencia un campo que sea None en las
    entradas -- ver las 4 plantillas en el docstring del módulo."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    items: List[EvidenceItem] = []
    record_timestamp = record.data_quality.last_updated

    # 1. Pitcher probable confirmado (MLB) -- FOR
    lineup_or_pitcher = record.model_inputs.lineup_or_pitcher
    if lineup_or_pitcher is not None:
        items.append(
            EvidenceItem(
                opportunity_id=opportunity_id,
                fact="Pitcher probable confirmado",
                direction=EvidenceDirection.FOR,
                source_field="model_inputs.lineup_or_pitcher",
                source_timestamp=record_timestamp,
                generated_at=now,
            )
        )

    # 2. Confianza de emparejamiento marginal -- AGAINST
    match_confidence = record.data_quality.match_confidence
    if match_confidence is not None:
        marginal_ceiling = EVENT_NAME_MATCH_MIN_CONFIDENCE + _MATCH_CONFIDENCE_MARGINAL_BAND
        if EVENT_NAME_MATCH_MIN_CONFIDENCE <= match_confidence < marginal_ceiling:
            items.append(
                EvidenceItem(
                    opportunity_id=opportunity_id,
                    fact=f"Confianza de emparejamiento marginal ({match_confidence:.2f})",
                    direction=EvidenceDirection.AGAINST,
                    source_field="data_quality.match_confidence",
                    source_timestamp=record_timestamp,
                    generated_at=now,
                )
            )

    # 3. Modelo con historial de performance evaluado -- FOR
    model_reliability = confidence_profile.model_reliability
    if model_reliability is not None and model_reliability > _MODEL_RELIABILITY_FOR_THRESHOLD:
        items.append(
            EvidenceItem(
                opportunity_id=opportunity_id,
                fact=f"Modelo con historial de performance evaluado (score={model_reliability:.1f}/100)",
                direction=EvidenceDirection.FOR,
                source_field="confidence_profile.model_reliability",
                source_timestamp=confidence_profile.computed_at,
                generated_at=now,
            )
        )

    # 4. Divergencia significativa entre modelo y consenso de mercado -- AGAINST
    p_model_calibrated = calibration_output.p_model_calibrated
    consensus_no_vig = record.bookmaker_consensus.consensus_probability_no_vig
    if p_model_calibrated is not None and consensus_no_vig is not None:
        divergence = abs(p_model_calibrated - consensus_no_vig)
        if divergence > _CONSENSUS_DIVERGENCE_AGAINST_THRESHOLD:
            items.append(
                EvidenceItem(
                    opportunity_id=opportunity_id,
                    fact=(
                        "Divergencia significativa entre modelo "
                        f"({p_model_calibrated:.2f}) y consenso de mercado ({consensus_no_vig:.2f})"
                    ),
                    direction=EvidenceDirection.AGAINST,
                    source_field="bookmaker_consensus.consensus_probability_no_vig",
                    source_timestamp=record_timestamp,
                    generated_at=now,
                )
            )

    return items
