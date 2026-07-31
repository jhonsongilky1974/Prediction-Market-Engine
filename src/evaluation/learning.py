"""Evaluation & Learning Framework -- andamiaje (Fase 3, Paso 3.8). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.8, y EVALUATION_LEARNING_SPEC.md §1.

`build_evaluation_record()` ensambla un `EvaluationRecord` (Paso 3.0,
`src/evaluation/schemas.py`, sin cambios) a partir de un `metric_value`
YA CALCULADO por el llamador (típicamente con las funciones de
`src/backtesting/metrics.py`, Fase 2 + extensión del Paso 3.8) -- este
módulo no calcula ninguna métrica él mismo, solo valida que el
`metric_name` pertenezca al catálogo cerrado de su `EvaluationScope`
(`EVALUATION_LEARNING_SPEC.md` §1) y construye el contrato con un
`record_id` determinístico.

ADVERTENCIA DE ALCANCE (reafirmada de `PLAN_MASTER_FASE3.md` §0 y
`FASE3_AUDIT_REPORT.md` §15, GATE-0): este andamiaje se construye y se
prueba en este paso con fixtures sintéticos -- CERO histórico real
(`feature_snapshots`/`event_results` en 0 filas, DECISIÓN PENDIENTE
D-1). Ningún `EvaluationRecord` producido hoy pretende representar
performance real del sistema; `sample_size` en cualquier registro
producido con datos sintéticos debe leerse como tal, nunca como
evidencia de comportamiento en producción.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from src.evaluation.schemas import EvaluationRecord, EvaluationScope
from src.models.schemas import Sport

MODEL_PERFORMANCE_METRICS = ("brier_score", "log_loss", "ece", "calibration_curve_bucket")
DECISION_PERFORMANCE_METRICS = (
    "clv_1h",
    "clv_24h",
    "clv_at_close",
    "abstention_rate",
    "missed_opportunity_rate",
)
FINANCIAL_PERFORMANCE_METRICS = ("roi_teorico", "roi_realizado", "yield", "drawdown", "profit_factor")
OPERATIONAL_PERFORMANCE_METRICS = ("hard_hold_rate", "pipeline_error_rate", "data_staleness_p95")
LEARNING_PERFORMANCE_METRICS = ("brier_score_delta_vs_previous", "policy_regression_pass_rate")
"""Catálogo cerrado de metric_name por EvaluationScope
(EVALUATION_LEARNING_SPEC.md §1) -- ninguna métrica fuera de estas 5
listas es válida en su scope correspondiente."""

_METRICS_BY_SCOPE: Dict[EvaluationScope, Tuple[str, ...]] = {
    EvaluationScope.MODEL_PERFORMANCE: MODEL_PERFORMANCE_METRICS,
    EvaluationScope.DECISION_PERFORMANCE: DECISION_PERFORMANCE_METRICS,
    EvaluationScope.FINANCIAL_PERFORMANCE: FINANCIAL_PERFORMANCE_METRICS,
    EvaluationScope.OPERATIONAL_PERFORMANCE: OPERATIONAL_PERFORMANCE_METRICS,
    EvaluationScope.LEARNING_PERFORMANCE: LEARNING_PERFORMANCE_METRICS,
}


def compute_evaluation_record_id(
    scope: EvaluationScope,
    metric_name: str,
    model_version: Optional[str],
    calibration_version: Optional[str],
    policy_version: Optional[str],
    evaluation_window_start: datetime,
    evaluation_window_end: datetime,
) -> str:
    """record_id determinístico -- mismo espíritu que
    compute_opportunity_id (Paso 3.0, src/opportunity/schemas.py): misma
    combinación de contexto siempre produce el mismo id, sin tabla de
    lookup, reconstruible desde los parámetros."""
    return (
        f"eval:{scope.value}:{metric_name}:{model_version}:{calibration_version}:"
        f"{policy_version}:{evaluation_window_start.isoformat()}:{evaluation_window_end.isoformat()}"
    )


def build_evaluation_record(
    scope: EvaluationScope,
    metric_name: str,
    metric_value: Optional[float],
    sample_size: int,
    evaluation_window_start: datetime,
    evaluation_window_end: datetime,
    sport: Optional[Sport] = None,
    market_type: Optional[str] = None,
    model_version: Optional[str] = None,
    calibration_version: Optional[str] = None,
    policy_version: Optional[str] = None,
    confidence_interval_low: Optional[float] = None,
    confidence_interval_high: Optional[float] = None,
    now: Optional[datetime] = None,
) -> EvaluationRecord:
    """Rechaza metric_name fuera del catálogo cerrado de su scope antes
    de construir el registro -- mismo principio de "rechazar antes de
    persistir" ya usado en validate_policy_manifest (Paso 3.4.5). No
    recalcula metric_value ni sample_size: son responsabilidad exclusiva
    del llamador (backtesting/metrics.py u otra fuente ya auditada)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    valid_metrics = _METRICS_BY_SCOPE[scope]
    if metric_name not in valid_metrics:
        raise ValueError(
            f"metric_name={metric_name!r} no pertenece al catálogo cerrado de {scope.value}: "
            f"{valid_metrics}"
        )

    record_id = compute_evaluation_record_id(
        scope, metric_name, model_version, calibration_version, policy_version,
        evaluation_window_start, evaluation_window_end,
    )

    return EvaluationRecord(
        record_id=record_id,
        scope=scope,
        sport=sport,
        market_type=market_type,
        model_version=model_version,
        calibration_version=calibration_version,
        policy_version=policy_version,
        metric_name=metric_name,
        metric_value=metric_value,
        sample_size=sample_size,
        confidence_interval_low=confidence_interval_low,
        confidence_interval_high=confidence_interval_high,
        computed_at=now,
        evaluation_window_start=evaluation_window_start,
        evaluation_window_end=evaluation_window_end,
    )
