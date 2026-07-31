# Arquitectura Fase 3 — Prediction-Market-Engine

Ver [`PLAN_MASTER_FASE3.md`](PLAN_MASTER_FASE3.md) para la matriz
REUTILIZAR/EXTENDER/CREAR completa con justificación. Este documento
describe el árbol modular propuesto y el flujo de datos. **`src/` no se
modifica en esta auditoría** — el árbol de abajo es la propuesta a
implementar en pasos posteriores (`IMPLEMENTATION_ROADMAP_FASE3.md`).

---

## 1. Árbol modular propuesto

```
src/
  models/                     [Fase 2, sin cambios]
    schemas.py                  NormalizedRecord, ModelStatus... (REUTILIZAR)
    base.py                     PModelOutput (REUTILIZAR, se compone, no se edita)
    registry.py                 [EXTENDER aditivo: load_latest_artifact(sport,...) nuevo]
    mlb_baseline.py, mlb_elo.py, tennis_baseline.py   [sin cambios]

  signals/                    [Fase 2, sin cambios]
    signal_schema.py             SignalInputs/SignalType/Side (REUTILIZAR como input del Policy Engine)
    edge.py, expected_value.py   [sin cambios; *_neto sigue NotImplementedError, ver src/payoff/]

  calibration/                [NUEVO]
    schemas.py                   CalibrationOutput
    calibration_layer.py         wraps PModelOutput -> (p_model_raw, p_model_calibrated)

  payoff/                     [NUEVO]
    schemas.py                    PayoffEstimate
    payoff_model.py                por plataforma/contrato; net_ev_status=UNKNOWN si falta evidencia

  policy/                     [NUEVO]
    schemas.py                    EligibilityResult, HardRuleResult, SoftScoreComponent,
                                   PolicyDecision, SignalReason
    hard_rules.py                 HARD_BLOCK_PASS / HARD_HOLD_WATCH (Corrección A)
    soft_score.py                 Soft Score, no compensa mínimos críticos (Principio 9)
    decision.py                   orquesta: hard rules -> soft score -> PolicyDecision
    manifest.py                   PolicyManifest, carga + versión activa
    validation.py                 schema/rango/consistencia/regresión/histórico (Corrección H)

  evidence/                   [NUEVO]
    schemas.py                    EvidenceItem
    evidence_engine.py            hechos estructurados a favor/en contra (Principio 13)

  explainability/             [NUEVO]
    explainability_engine.py      decisión+razones+evidencia -> explicación auditable (Principio 14)
                                   NO importa evidence_engine internals más allá de EvidenceItem
                                   (separación de responsabilidad, Principio 6)

  health/                     [NUEVO]
    schemas.py                    AnalysisHealth
    analysis_health.py            exclusivamente informativo (Principio 5)

  opportunity/                [NUEVO]
    schemas.py                    Opportunity, OpportunityEvaluation
    opportunity_repository.py     append-only, mismo patrón que history_repository.py

  storage/                    [Fase 2, sin cambios]
    repository.py, history_repository.py   [REUTILIZAR sin editar]

  backtesting/                [Fase 2]
    dataset.py, splitter.py       [REUTILIZAR sin editar]
    metrics.py                    [EXTENDER aditivo: ece(), clv(), roi_teorico(), profit_factor(), drawdown()]

  evaluation/                 [Fase 2 + nuevo]
    reports.py                    [REUTILIZAR sin editar — Model Performance]
    learning.py                   [NUEVO] EvaluationRecord, 5 dimensiones (Principio 15)

config/
  settings.py                 [EXTENDER aditivo: paths nuevos]
  policy/                     [NUEVO, no Python] manifiestos versionados (ver POLICY_ENGINE_SPEC.md §5)
```

**Módulos que Fase 3 explícitamente NO crea** (ver
`PLAN_MASTER_FASE3.md` §3.5 y §6): `src/execution/`, `src/risk/`
(bankroll/Kelly/gestión de posición), cualquier cliente de envío de
órdenes.

---

## 2. Flujo de datos (una evaluación de oportunidad)

```
NormalizedRecord (Fase 1/2, ya existe)
        |
        v
PModelOutput (Fase 2, models/*_baseline.py, sin cambios)
        |
        v
CalibrationOutput  <-- calibration/calibration_layer.py [NUEVO]
        |  (p_model_raw = PModelOutput.p_model_yes, p_model_calibrated, calibration_version)
        v
compute_edge_yes/no, compute_ev_*_bruto (Fase 2, edge.py/expected_value.py, sin cambios)
        |
        v
PayoffEstimate  <-- payoff/payoff_model.py [NUEVO]  (EV neto real, o net_ev_status=UNKNOWN)
        |
        v
QualityScoreOutput (Fase 2, quality_score.py, sin cambios)
        |
        v
ConfidenceProfile  <-- policy/ o health/ [NUEVO]  (4 dimensiones, ver PLAN_MASTER_FASE3.md §4)
        |
        v
EvidenceItem[]  <-- evidence/evidence_engine.py [NUEVO]
        |
        v
AnalysisHealth  <-- health/analysis_health.py [NUEVO]  (informativo, no entra al Policy Engine)
        |
        v
SignalInputs (Fase 2, signal_schema.py, sin cambios) -- ensamblado desde todo lo anterior
        |
        v
EligibilityResult -> HardRuleResult[] -> SoftScoreComponent[]  <-- policy/hard_rules.py, soft_score.py [NUEVO]
        |
        v
PolicyDecision (ENTER | WATCH | PASS + disposition + SignalReason[])  <-- policy/decision.py [NUEVO]
        |
        v
Opportunity / OpportunityEvaluation (persistidos, append-only)  <-- opportunity/ [NUEVO]
        |
        v
ExplainabilityOutput (texto/estructura auditable para humano)  <-- explainability/ [NUEVO]
```

`AnalysisHealth` se calcula en paralelo a `SignalInputs`, nunca como
insumo de `soft_score.py` — el flujo lo dibuja fuera de la cadena que
entra al Policy Engine para reforzar visualmente el Principio 5.

---

## 3. Persistencia

Dos opciones eran viables para `opportunity_repository.py` y las tablas
de política/evaluación; se elige explícitamente **la opción A**:

- **Opción A (elegida): mismo `data/engine.db` (SQLite), tablas nuevas
  aditivas** — mismo patrón que `history_repository.py` (Paso 0 de Fase
  2): `CREATE TABLE IF NOT EXISTS`, triggers append-only para
  `opportunity_evaluations`/`evaluation_records`, sin tocar las tablas de
  `repository.py`/`history_repository.py`. Justificación: cero
  dependencias nuevas, mismo proceso de backup/restauración ya validado
  institucionalmente, y las consultas cruzadas (unir un
  `feature_snapshot` con su `OpportunityEvaluation`) son triviales en el
  mismo archivo.
- **Opción B (rechazada): base de datos separada por dominio.** Añadiría
  una segunda ruta de backup/restauración y complicaría joins sin
  beneficio real al volumen esperado (single-writer, un proceso).

Tablas nuevas propuestas (nombres, no DDL final — el DDL exacto se
resuelve en la implementación siguiendo el patrón exacto de
`HISTORY_SCHEMA_SQL`):

| Tabla | Append-only | Corresponde a |
|---|---|---|
| `opportunities` | Sí (solo `state_version` nuevo es INSERT, nunca UPDATE de una fila existente) | `Opportunity` |
| `opportunity_evaluations` | Sí | `OpportunityEvaluation` |
| `policy_manifests` | Sí (una fila por versión publicada) | `PolicyManifest` |
| `evaluation_records` | Sí | `EvaluationRecord` |

---

## 4. Dependencias entre módulos nuevos (para evitar ciclos)

```
policy/  ---depends on--->  signals/ (Fase 2), calibration/, payoff/, health/schemas.py
                             (AnalysisHealth -- corrección aplicada en el Paso 3.4.3:
                             check_temporarily_stale_data necesita AnalysisHealth.staleness_seconds,
                             POLICY_ENGINE_SPEC.md §2.2, y esta lista no lo reflejaba; solo el
                             contrato de datos, nunca health/analysis_health.py, que sigue sin
                             implementar -- Paso 3.7)
calibration/  ---depends on--->  models/base.py (Fase 2)
payoff/  ---depends on--->  pricing/ (Fase 2), signals/expected_value.py (Fase 2)
evidence/  ---depends on--->  models/schemas.py (Fase 2), uncertainty/quality_score.py (Fase 2),
                               calibration/schemas.py, policy/schemas.py (ConfidenceProfile --
                               corrección aplicada en el Paso 3.3: EVIDENCE_EXPLAINABILITY_SPEC.md
                               ya definía collect_evidence(record, calibration_output,
                               confidence_profile), y esta lista no lo reflejaba; consistente con
                               el patrón ya usado por opportunity/, que también depende de
                               policy/schemas.py solo para tipos de datos, nunca para lógica)
explainability/  ---depends on--->  policy/schemas.py, evidence/schemas.py   [NUNCA al revés]
health/  ---depends on--->  uncertainty/quality_score.py (Fase 2), evidence/schemas.py
opportunity/  ---depends on--->  policy/schemas.py, matching/ (Fase 2, solo tipos de id)
evaluation/learning.py  ---depends on--->  backtesting/metrics.py (extendido), opportunity/
```

Regla dura: **ningún módulo nuevo importa desde `explainability/` o
`opportunity/`** — son consumidores terminales del grafo, nunca
proveedores. Verificable estáticamente (test de arquitectura, ver
`IMPLEMENTATION_ROADMAP_FASE3.md`).

---

## 5. Relación con Fase 1/Fase 2 (invariante reafirmado)

Igual que Fase 2 nunca modificó `src/connectors/`, `src/normalization/`,
`src/matching/` ni `src/quality/` de Fase 1, Fase 3 no modifica ningún
archivo de `src/models/`, `src/signals/`, `src/pricing/`,
`src/uncertainty/`, `src/storage/`, `src/backtesting/`, `src/evaluation/`
salvo las dos extensiones aditivas documentadas explícitamente en
`PLAN_MASTER_FASE3.md` §3.2 (`backtesting/metrics.py`,
`models/registry.py`). Todo lo demás es lectura, nunca escritura de
código existente.
