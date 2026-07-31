"""Decision -- orquestación del Policy Engine (Fase 3, Paso 3.4.5). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.5, y POLICY_ENGINE_SPEC.md §1.1.

`decide()` ejecuta la secuencia exacta de 4 etapas ya especificada:

    [1] Eligibility -> [2] Hard Block -> [3] Hard Hold -> [4] Soft Score

deteniéndose en la primera etapa que produce una decisión (Eligibility
inválida o Hard Block activo -> PASS inmediato, sin llegar a Soft Score;
Hard Hold activo -> WATCH inmediato, sin llegar a Soft Score) -- mismo
principio ya implementado por separado en cada paso anterior (3.4.1-
3.4.4), ahora integrado.

## Resolución de las 2 decisiones diferidas en 3.4.3/3.4.4

`hard_rule_parameters` (Paso 3.4.5, rectificación aditiva aprobada
explícitamente, ver CONTINUITY.md §0.11) se usa por clave cuando existe;
las claves ausentes caen a los defaults PROVISIONAL ya declarados en
`hard_rules.py` -- nunca se fabrica un valor nuevo aquí.
`soft_score_weights`/`critical_minimums` del manifiesto se MEZCLAN con
los defaults de `soft_score.py` (`{**DEFAULT, **manifest_dict}`) en vez
de reemplazarlos por completo -- así un manifiesto que solo personaliza
un componente no deja a los demás con peso/mínimo cero por accidente.
Este merge vive aquí, en el orquestador, no dentro de
`compute_soft_score_components()` (Paso 3.4.4, sin cambios): mantiene
esa función con su contrato simple ya probado ("weights=None usa
defaults, weights=dict usa ese dict tal cual") y coloca la
responsabilidad de resolver la precedencia de configuración donde
corresponde -- el orquestador.

## Activación por manifiesto: solo las reglas activas quedan en el resultado

`evaluate_hard_block_rules()`/`evaluate_hard_hold_rules()` (Pasos 3.4.2/
3.4.3, sin cambios) siempre evalúan el catálogo completo. `decide()`
filtra ese resultado a únicamente las reglas ACTIVAS según
`policy_manifest.hard_block_rules`/`hard_hold_rules` antes de decidir
Y antes de construir el `PolicyDecision` final -- un `rule_id`
`triggered=True` pero no activado ni bloquea ni aparece en
`hard_rule_results`. Esto no es solo estilo: `PolicyDecision` (Paso 3.0)
ya exige que ningún `signal_type=ENTER` coexista con un `HardRuleResult`
`BLOCK` `triggered=True` en su propia lista -- sin este filtro, un ENTER
legítimo con una regla inactiva-pero-triggered en el catálogo completo
haría que `PolicyDecision` se auto-rechazara al construirse (bug real
encontrado durante este paso, corregido aquí sin tocar el contrato de
Paso 3.0 -- ver CONTINUITY.md §0.11).

## Fail-safe (Principio 20, POLICY_ENGINE_SPEC.md §6)

Cualquier excepción no controlada durante la orquestación (incluida una
`PolicyManifest` que falle su propia re-validación defensiva, o un
`policy_manifest.sport` que no coincida con `record.sport`) se captura
en el borde externo de `decide()` y se traduce a
`PolicyDecision(signal_type=PASS, disposition=INVALID_ANALYSIS)` -- el
Policy Engine nunca propaga una excepción a su llamador ni deja una
`Opportunity` sin decisión.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.health.schemas import AnalysisHealth
from src.models.schemas import NormalizedRecord
from src.payoff.schemas import PayoffEstimate
from src.policy.hard_rules import (
    DEFAULT_MINIMUM_OPERABLE_LIQUIDITY,
    DEFAULT_PENDING_LINEUP_HOURS_THRESHOLD,
    DEFAULT_STALE_DATA_THRESHOLD_SECONDS,
    check_non_recoverable_inconsistency,
    evaluate_hard_block_rules,
    evaluate_hard_hold_rules,
)
from src.policy.schemas import (
    AbstentionDisposition,
    ConfidenceProfile,
    HardRuleCategory,
    PolicyDecision,
    PolicyManifest,
    SignalReason,
    SignalReasonCode,
)
from src.policy.soft_score import (
    DEFAULT_CRITICAL_MINIMUMS,
    DEFAULT_SOFT_SCORE_WEIGHTS,
    check_enter_eligible_by_soft_score,
    compute_aggregate_soft_score,
    compute_soft_score_components,
)
from src.policy.eligibility import check_eligibility
from src.policy.validation import validate_policy_manifest
from src.signals.signal_schema import SignalInputs, SignalType
from src.storage.history_repository import HistoryRepository


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


def _pass_decision(
    opportunity_id: str,
    signal_inputs: SignalInputs,
    disposition: AbstentionDisposition,
    reasons: list,
    hard_rule_results: list,
    policy_manifest: PolicyManifest,
    now: datetime,
) -> PolicyDecision:
    return PolicyDecision(
        opportunity_id=opportunity_id,
        side=signal_inputs.side,
        signal_type=SignalType.PASS,
        disposition=disposition,
        reasons=reasons,
        hard_rule_results=hard_rule_results,
        soft_score_components=[],
        aggregate_soft_score=None,
        policy_version=policy_manifest.policy_version,
        policy_manifest_hash=policy_manifest.manifest_hash,
        decided_at=now,
    )


def decide(
    opportunity_id: str,
    record: NormalizedRecord,
    signal_inputs: SignalInputs,
    payoff_estimate: Optional[PayoffEstimate],
    confidence_profile: ConfidenceProfile,
    analysis_health: AnalysisHealth,
    data_cutoff_timestamp: datetime,
    history_repository: HistoryRepository,
    policy_manifest: PolicyManifest,
    now: Optional[datetime] = None,
) -> PolicyDecision:
    """Punto de entrada único del Policy Engine. Nunca lanza -- cualquier
    excepción interna se traduce a PolicyDecision(PASS, INVALID_ANALYSIS)
    (fail-safe, ver docstring del módulo)."""
    now = now or datetime.now(timezone.utc)
    try:
        _require_utc_aware(now, "now")
        _require_utc_aware(data_cutoff_timestamp, "data_cutoff_timestamp")
        return _decide_inner(
            opportunity_id,
            record,
            signal_inputs,
            payoff_estimate,
            confidence_profile,
            analysis_health,
            data_cutoff_timestamp,
            history_repository,
            policy_manifest,
            now,
        )
    except Exception as exc:  # noqa: BLE001 -- frontera fail-safe deliberada (Principio 20)
        non_recoverable = check_non_recoverable_inconsistency(exc, now)
        return _pass_decision(
            opportunity_id=opportunity_id,
            signal_inputs=signal_inputs,
            disposition=AbstentionDisposition.INVALID_ANALYSIS,
            reasons=[
                SignalReason(
                    code=SignalReasonCode.HARD_BLOCK,
                    detail=non_recoverable.detail or "excepción no controlada durante la orquestación",
                    source_component="non_recoverable_inconsistency",
                )
            ],
            hard_rule_results=[non_recoverable],
            policy_manifest=policy_manifest,
            now=now,
        )


def _decide_inner(
    opportunity_id: str,
    record: NormalizedRecord,
    signal_inputs: SignalInputs,
    payoff_estimate: Optional[PayoffEstimate],
    confidence_profile: ConfidenceProfile,
    analysis_health: AnalysisHealth,
    data_cutoff_timestamp: datetime,
    history_repository: HistoryRepository,
    policy_manifest: PolicyManifest,
    now: datetime,
) -> PolicyDecision:
    # Defensa en profundidad: manifest.py ya valida al cargar/guardar
    # (Corrección H), pero decide() vuelve a validar aquí -- si falla,
    # cae en el try/except externo y se traduce a INVALID_ANALYSIS.
    validate_policy_manifest(policy_manifest)

    if policy_manifest.sport != record.sport:
        raise ValueError(
            f"policy_manifest.sport ({policy_manifest.sport}) no coincide con "
            f"record.sport ({record.sport}) -- un manifiesto es por deporte (Principio 1)"
        )

    # [1] Eligibility
    eligibility = check_eligibility(
        opportunity_id,
        signal_inputs.event_id,
        signal_inputs.sport,
        signal_inputs.side,
        signal_inputs.generated_at,
        now=now,
    )
    if not eligibility.is_eligible:
        return _pass_decision(
            opportunity_id=opportunity_id,
            signal_inputs=signal_inputs,
            disposition=AbstentionDisposition.INVALID_ANALYSIS,
            reasons=[
                SignalReason(
                    code=SignalReasonCode.HARD_BLOCK,
                    detail="; ".join(eligibility.ineligibility_reasons),
                    source_component="eligibility",
                )
            ],
            hard_rule_results=[],
            policy_manifest=policy_manifest,
            now=now,
        )

    # [2] Hard Block
    hard_block_results = evaluate_hard_block_rules(record, data_cutoff_timestamp, history_repository, now=now)
    active_block_results = [r for r in hard_block_results if r.rule_id in policy_manifest.hard_block_rules]
    triggered_blocks = [r for r in active_block_results if r.triggered]
    if triggered_blocks:
        return _pass_decision(
            opportunity_id=opportunity_id,
            signal_inputs=signal_inputs,
            disposition=AbstentionDisposition.POLICY_REJECTED,
            reasons=[
                SignalReason(code=SignalReasonCode.HARD_BLOCK, detail=r.detail or r.rule_id, source_component=r.rule_id)
                for r in triggered_blocks
            ],
            hard_rule_results=active_block_results,
            policy_manifest=policy_manifest,
            now=now,
        )

    # [3] Hard Hold
    hard_hold_results = evaluate_hard_hold_rules(
        record,
        analysis_health,
        now=now,
        pending_lineup_hours_threshold=policy_manifest.hard_rule_parameters.get(
            "pending_lineup_hours_threshold", DEFAULT_PENDING_LINEUP_HOURS_THRESHOLD
        ),
        stale_data_threshold_seconds=policy_manifest.hard_rule_parameters.get(
            "temporarily_stale_data_threshold_seconds", DEFAULT_STALE_DATA_THRESHOLD_SECONDS
        ),
        minimum_operable_liquidity=policy_manifest.hard_rule_parameters.get(
            "temporarily_insufficient_liquidity_minimum", DEFAULT_MINIMUM_OPERABLE_LIQUIDITY
        ),
    )
    active_hold_results = [r for r in hard_hold_results if r.rule_id in policy_manifest.hard_hold_rules]
    active_hard_rule_results = active_block_results + active_hold_results
    triggered_holds = [r for r in active_hold_results if r.triggered]
    if triggered_holds:
        return PolicyDecision(
            opportunity_id=opportunity_id,
            side=signal_inputs.side,
            signal_type=SignalType.WATCH,
            disposition=None,
            reasons=[
                SignalReason(code=SignalReasonCode.HARD_HOLD, detail=r.detail or r.rule_id, source_component=r.rule_id)
                for r in triggered_holds
            ],
            hard_rule_results=active_hard_rule_results,
            soft_score_components=[],
            aggregate_soft_score=None,
            policy_version=policy_manifest.policy_version,
            policy_manifest_hash=policy_manifest.manifest_hash,
            decided_at=now,
        )

    # [4] Soft Score -- solo se llega aquí sin ningún bloqueo activo (Principio 8, literal)
    effective_weights = {**DEFAULT_SOFT_SCORE_WEIGHTS, **policy_manifest.soft_score_weights}
    effective_minimums = {**DEFAULT_CRITICAL_MINIMUMS, **policy_manifest.critical_minimums}
    components = compute_soft_score_components(
        signal_inputs, payoff_estimate, confidence_profile, weights=effective_weights, minimums=effective_minimums
    )
    aggregate = compute_aggregate_soft_score(components)
    critical_failures = [c for c in components if c.is_critical_minimum and c.passed_minimum is not True]
    enter_ok = check_enter_eligible_by_soft_score(components, aggregate, policy_manifest.enter_global_threshold)
    meets_watch_floor = aggregate is not None and aggregate >= policy_manifest.watch_global_threshold

    if enter_ok:
        signal_type = SignalType.ENTER
        disposition = None
        reasons = [
            SignalReason(
                code=SignalReasonCode.ELIGIBLE_AND_SCORED,
                detail=f"aggregate_soft_score={aggregate} >= enter_global_threshold={policy_manifest.enter_global_threshold}, todos los mínimos críticos superados",
                source_component="soft_score",
            )
        ]
    elif critical_failures:
        signal_type = SignalType.WATCH if meets_watch_floor else SignalType.PASS
        disposition = None if meets_watch_floor else (
            AbstentionDisposition.INSUFFICIENT_EVIDENCE
            if any(c.value is None for c in critical_failures)
            else AbstentionDisposition.NO_VALUE
        )
        reasons = [
            SignalReason(
                code=SignalReasonCode.CRITICAL_MINIMUM_NOT_MET,
                detail=f"componentes críticos sin pasar el mínimo: {[c.component_name for c in critical_failures]}",
                source_component="soft_score",
            )
        ]
    else:
        signal_type = SignalType.WATCH if meets_watch_floor else SignalType.PASS
        disposition = None if meets_watch_floor else AbstentionDisposition.NO_VALUE
        reasons = [
            SignalReason(
                code=SignalReasonCode.SOFT_SCORE_BELOW_GLOBAL,
                detail=f"aggregate_soft_score={aggregate} < enter_global_threshold={policy_manifest.enter_global_threshold}",
                source_component="soft_score",
            )
        ]

    return PolicyDecision(
        opportunity_id=opportunity_id,
        side=signal_inputs.side,
        signal_type=signal_type,
        disposition=disposition,
        reasons=reasons,
        hard_rule_results=active_hard_rule_results,
        soft_score_components=components,
        aggregate_soft_score=aggregate,
        policy_version=policy_manifest.policy_version,
        policy_manifest_hash=policy_manifest.manifest_hash,
        decided_at=now,
    )
