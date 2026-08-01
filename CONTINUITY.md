# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). Actualizado: 2026-07-26 (cierre del Paso 7 —
Quality Score / Incertidumbre). Actualizado: 2026-07-26 (cierre del
Paso 6 — Elo simple MLB / Baseline 2). Actualizado: 2026-07-26 (cierre del
Paso 8 — EDGE_YES/EDGE_NO + Expected Value). Actualizado: 2026-07-26
(cierre del Paso 9 — Backtesting: dataset + walk-forward splitter +
metrics). Actualizado: 2026-07-26 (cierre del Paso 10 — Comparación de
baselines: Baseline 0 vs 1 vs 2). Actualizado: 2026-07-26 (cierre del
Paso 11 — Baseline de tenis: features + infraestructura de modelo +
sincronización de resultados). Actualizado: 2026-07-26 (cierre del
Paso 12 — Esquema de señal: SignalInputs + SignalType/Side, sin lógica de
umbral). Actualizado: 2026-07-26 — CIERRE FORMAL DE FASE 2. **Actualizado
de nuevo: 2026-07-26 — Validación Institucional post-cierre y corrección
de un defecto de aislamiento de tests (ver §0.1).** **Actualizado de
nuevo: 2026-07-30 — Auditoría contractual y arquitectónica completa del
Plan Maestro de Fase 3, documental, sin implementación (ver §0.2).**
**Actualizado de nuevo: 2026-07-30 — Aprobado FASE3_EXECUTION_PLAN.md e
implementado el Paso 3.0 de Fase 3 (andamiaje de contratos), primer
código real de Fase 3 (ver §0.3).** **Actualizado de nuevo: 2026-07-30 —
Rectificado un contrato del Paso 3.0 (§0.3.1) e implementado el Paso 3.1
(Calibration Layer, sin entrenar) (ver §0.4).** **Actualizado de nuevo:
2026-07-30 — Implementado el Paso 3.2 de Fase 3 (Payoff Model) (ver
§0.5).** **Actualizado de nuevo: 2026-07-30 — Implementado el Paso 3.3
de Fase 3 (Evidence Engine) (ver §0.6).** **Actualizado de nuevo:
2026-07-30 — Implementado el Paso 3.4.1 de Fase 3 (Policy Engine —
Eligibility) (ver §0.7).** **Actualizado de nuevo: 2026-07-30 —
Implementado el Paso 3.4.2 de Fase 3 (Policy Engine — Hard Block Rules)
(ver §0.8).** **Actualizado de nuevo: 2026-07-30 — Implementado el Paso
3.4.3 de Fase 3 (Policy Engine — Hard Hold Rules) (ver §0.9).**
**Actualizado de nuevo: 2026-07-30 — Implementado el Paso 3.4.4 de Fase 3
(Policy Engine — Soft Score) (ver §0.10).** **Actualizado de nuevo:
2026-07-31 — Implementado el Paso 3.4.5 de Fase 3 (Policy Engine —
Decision + Manifest + Validation), CIERRA EL PASO 3.4 COMPLETO (ver
§0.11).** **Actualizado de nuevo: 2026-07-31 — Implementado el Paso 3.5
de Fase 3 (Opportunity Lifecycle + persistencia) (ver §0.12).**
**Actualizado de nuevo: 2026-07-31 — Implementado el Paso 3.6 de Fase 3
(Explainability Engine), con una adición contractual correctiva
(`ExplanationOutput`) (ver §0.13).** **Actualizado de nuevo: 2026-07-31
— Implementado el Paso 3.7 de Fase 3 (Analysis Health), con una
rectificación al invariante del Principio 5 en `CONTRACTS_FASE3.md` §5
(ver §0.14).** **Actualizado de nuevo: 2026-07-31 — Implementado el Paso
3.8 de Fase 3 (Evaluation & Learning Framework, andamiaje con fixtures
sintéticos) (ver §0.15).** **Actualizado de nuevo: 2026-07-31 — Paso 3.9
declarado innecesario por hallazgo arquitectónico; CIERRE DEL ROADMAP
REQUIRED FOR PHASE 3 (ver §0.16).** **Actualizado de nuevo: 2026-07-31 —
RESUELTA LA DECISIÓN PENDIENTE D-2 (mapeo participante↔YES de Kalshi):
primera modificación de código de Fase 1/2 en todo el proceso de Fase 3,
autorizada explícitamente (ver §0.17).** **Actualizado de nuevo:
2026-07-31 — INVESTIGADA Y REENCUADRADA (no resuelta) la DECISIÓN
PENDIENTE D-3 (fórmula de fees reales de Kalshi): infraestructura
preparada, `net_ev_status` permanece `UNKNOWN` a la espera de
verificación contra la fuente primaria (ver §0.18).** **Actualizado de
nuevo: 2026-08-01 — Investigado D-1: contradicción operacional
encontrada y corregida (el LaunchAgent estaba cargado en `launchd`,
contradiciendo la documentación); diseñada e implementada la Política de
Retención de Datos (`DATA_RETENTION_POLICY.md`) con su mecanismo
(`scripts/data_maintenance.py` + LaunchAgent propio); RESUELTA LA
DECISIÓN PENDIENTE D-1: ambos LaunchAgents (captura histórica +
mantenimiento) reactivados y confirmados en ejecución permanente (ver
§0.19). **Cierra la última decisión pendiente de Fase 3 — D-1/D-2
resueltas, D-3 reencuadrada y documentada como dependencia externa.**
Propósito: única fuente de verdad para continuar este proyecto en una
conversación nueva, sin acceso al historial de chat.

## 0.2 Auditoría del Plan Maestro de Fase 3 (2026-07-30, documental, sin implementación)

El usuario pidió una auditoría contractual y arquitectónica completa de
21 principios + 9 correcciones (A-I) propuestos para Fase 3 (Policy
Engine, Model Pipeline con calibración, Evidence/Explainability Engine,
Opportunity Lifecycle, Evaluation & Learning Framework, Shadow Mode),
corregirlos, consolidarlos y dejarlos listos para implementación
institucional — **sin implementar Fase 3 todavía, sin tocar `src/`, sin
entrenar modelos, sin mover `v2.0-baseline`**.

Verificación previa: `HEAD` de `phase-2-dev` coincide exactamente con
`v2.0-baseline` (`git diff --stat v2.0-baseline HEAD` vacío), 498 tests
en verde, `data/models/` con únicamente `.gitkeep`. No existía ningún
documento previo de Fase 3 en el repositorio — el "Plan Maestro"
auditado es el conjunto de principios entregado en la propia tarea de
auditoría, no un documento preexistente.

**Documentos generados** (todos nuevos, ninguno reemplaza documentación
de Fase 2):

- [`PLAN_MASTER_FASE3.md`](PLAN_MASTER_FASE3.md) — 21 principios y 9
  correcciones consolidados, matriz REUTILIZAR/EXTENDER/CREAR/DEPRECAR/
  FUERA DE ALCANCE, 3 decisiones pendientes (D-1/D-2/D-3).
- [`ARCHITECTURE_FASE3.md`](ARCHITECTURE_FASE3.md) — árbol modular
  propuesto, flujo de datos, reglas de dependencia entre módulos nuevos.
- [`CONTRACTS_FASE3.md`](CONTRACTS_FASE3.md) — los 16 contratos de datos
  pedidos, campos, invariantes, versionado.
- [`POLICY_ENGINE_SPEC.md`](POLICY_ENGINE_SPEC.md) — Hard Block/Hold
  Rules, Soft Score sin compensación de mínimos críticos, Policy
  Validation.
- [`MODEL_PIPELINE_SPEC.md`](MODEL_PIPELINE_SPEC.md) — arquitectura
  jerárquica de P_model, Calibration Layer.
- [`EVIDENCE_EXPLAINABILITY_SPEC.md`](EVIDENCE_EXPLAINABILITY_SPEC.md) —
  Evidence Engine y Explainability Engine, separados.
- [`EVALUATION_LEARNING_SPEC.md`](EVALUATION_LEARNING_SPEC.md) —
  framework de evaluación de 5 dimensiones.
- [`TEMPORAL_REPRODUCIBILITY_SPEC.md`](TEMPORAL_REPRODUCIBILITY_SPEC.md)
  — integridad temporal, reproducibilidad, tests de fuga.
- [`SHADOW_MODE_AND_PROMOTION_GATES.md`](SHADOW_MODE_AND_PROMOTION_GATES.md)
  — release path de 5 etapas, gates cuantificables, GATE-0 de datos.
- [`IMPLEMENTATION_ROADMAP_FASE3.md`](IMPLEMENTATION_ROADMAP_FASE3.md) —
  10 pasos reversibles (F3-0 a F3-9), clasificados REQUIRED/RECOMMENDED
  LATER/REJECTED AS PREMATURE.
- [`FASE3_AUDIT_REPORT.md`](FASE3_AUDIT_REPORT.md) — informe de auditoría
  de 15 secciones, conclusión **CONDITIONAL GO**.

**Hallazgo principal de la auditoría**: `FASE2_CIERRE_FINAL.md §7` ya
documentaba un orden de dependencia (reactivar captura histórica →
resolver mapeo participante↔YES → configurar `ODDS_API_KEY` → recién
entonces diseñar clasificación ENTER/WATCH/PASS) que los 21 principios de
Fase 3, tal como fueron propuestos, no hacían explícito como bloqueante.
La auditoría formaliza esto como **GATE-0**
(`SHADOW_MODE_AND_PROMOTION_GATES.md` §2) y como 3 **decisiones
pendientes** (D-1: reactivar LaunchAgent; D-2: resolver mapeo
participante↔YES; D-3: fórmula de costos reales en el Payoff Model) que
bloquean estructuralmente cualquier `ENTER` real — ninguna se resuelve en
esta auditoría, todas quedan explícitas en
`PLAN_MASTER_FASE3.md` §8 y `FASE3_AUDIT_REPORT.md` §13.

3 huecos de contrato reales encontrados y resueltos sin romper Fase 2
(detalle en `FASE3_AUDIT_REPORT.md` §6): colisión de nombre `ModelOutput`
(ya existe una clase vacía con ese nombre en `src/models/schemas.py`,
resuelto por composición `PModelOutput`+`CalibrationOutput`, sin tocar
`schemas.py`); categoría de Hard Rule faltante para la Ambigüedad #2 de
Fase 2 (`unresolved_side_mapping`, añadida a `HARD_HOLD_WATCH`);
definición de `selection_id` (Kalshi no expone uno, se define
determinísticamente como `f"{market_id}:{side.value}"`).

**Conclusión**: CONDITIONAL GO — la especificación completa (contratos,
arquitectura, Policy Engine, Payoff Model, Calibration Layer sin
entrenar, Evidence/Explainability, Opportunity Lifecycle, andamiaje de
Evaluation Framework) está lista para implementarse con fixtures/tests,
sin histórico real. La puesta en producción de cualquier etapa que
requiera calibración real, backtesting real o shadow mode real permanece
bloqueada por D-1/D-2/D-3, sin resolver.

**Cero cambios en `src/`, cero modelos entrenados, `v2.0-baseline` sin
mover.** Verificación final (498 tests, `data/models/` limpio, `git diff
--stat`/`git status`) documentada en el commit de esta auditoría — ver
`git log` para el hash exacto.

## 0.3 Fase 3 — Paso 3.0: Andamiaje de contratos (2026-07-30, primer código real de Fase 3)

Tras aprobar la auditoría (§0.2, CONDITIONAL GO) y congelar la
arquitectura, el usuario aprobó
[`FASE3_EXECUTION_PLAN.md`](FASE3_EXECUTION_PLAN.md) (roadmap aprobado
convertido en 14 pasos ejecutables, `Paso 3.0`-`Paso 3.9`, con el Policy
Engine subdividido en `3.4.1`-`3.4.5`) y autorizó el inicio del Paso 3.0,
con dos criterios de aceptación añadidos: round-trip de serialización
(`model_dump`/`model_validate`/`model_dump_json`/`model_validate_json`)
y una factory de ejemplo mínimo válido por contrato.

**Corrección aplicada antes de implementar** (detectada al preparar el
paso, documentada en `FASE3_EXECUTION_PLAN.md` antes de escribir código,
no una desviación arquitectónica): la tabla de contratos del Paso 3.0 ya
listaba `EvaluationRecord` pero no declaraba dónde viviría su
`schemas.py`. Resuelto creando `src/evaluation/schemas.py` (archivo
nuevo dentro del paquete `evaluation/` ya existente de Fase 2, sin tocar
`reports.py`), siguiendo el mismo patrón `schemas.py` separado de lógica
que todos los demás paquetes nuevos. `ConfidenceProfile` se ubicó en
`src/policy/schemas.py` (`PLAN_MASTER_FASE3.md` §4 dejaba la ubicación
abierta entre `policy/`/`opportunity/`).

**Implementado** — 14 contratos, 13 archivos nuevos en `src/`, cero
archivos de Fase 1/2 modificados (`git diff --stat HEAD -- src/models
src/signals src/pricing src/uncertainty src/storage src/backtesting
src/evaluation src/matching src/quality src/connectors
src/normalization` vacío, confirmado directamente):

- `src/calibration/schemas.py` — `CalibrationOutput`.
- `src/payoff/schemas.py` — `PayoffEstimate`, `NetEvStatus`.
- `src/evidence/schemas.py` — `EvidenceItem`, `EvidenceDirection`.
- `src/health/schemas.py` — `AnalysisHealth`.
- `src/policy/schemas.py` — `ConfidenceProfile`, `EligibilityResult`,
  `HardRuleResult`+`HardRuleCategory`, `SoftScoreComponent`,
  `SignalReason`+`SignalReasonCode`, `PolicyDecision`+
  `AbstentionDisposition`, `PolicyManifest` (7 contratos).
- `src/opportunity/schemas.py` — `Opportunity`, `OpportunityEvaluation`
  (`frozen=True`, inmutable — Principio 10), más
  `compute_selection_id`/`compute_opportunity_id` (identidad
  determinística, Hallazgo de Contrato #3).
- `src/evaluation/schemas.py` — `EvaluationRecord`, y `EvaluationScope`
  (enum nuevo, formaliza como vocabulario cerrado las 5 dimensiones del
  Principio 15 — mejora menor no solicitada explícitamente pero
  consistente con el patrón ya usado en todo el proyecto para
  vocabularios cerrados; documentada, no oculta).

Todos los 14 contratos reutilizan `StrictModel` (`src/models/schemas.py`,
Fase 2, `extra="forbid"`) y, donde aplica, `Sport`/`Side`/`SignalType`/
`SignalInputs` (Fase 1/2, sin cambios) — ningún tipo se duplicó.
`OpportunityEvaluation` embebe `SignalInputs` (dataclass estándar de
Fase 2, no un `BaseModel`) directamente como campo tipado; se confirmó
con test dedicado que pydantic v2 lo serializa/reconstruye
correctamente en round-trip dict y JSON (caso de composición más
delicado del paso).

**Tests**: `tests/unit/fase3_factories.py` (factories de ejemplo mínimo
válido para los 14 contratos + helper `assert_round_trip`, mismo patrón
`_kwargs(**overrides)` de `test_signal_schema.py`) + 7 archivos de test
(`test_calibration_schemas.py`, `test_payoff_schemas.py`,
`test_evidence_schemas.py`, `test_health_schemas.py`,
`test_policy_schemas.py`, `test_opportunity_schemas.py`,
`test_evaluation_record_schema.py`) — **106 tests nuevos**, cubriendo
cada invariante de `CONTRACTS_FASE3.md`, `extra="forbid"`, timestamps
naive, y el round-trip de serialización de los 4 métodos pedido por el
usuario.

**Suite completa**: 498 (Fase 2, sin modificar ningún test existente) +
106 (Fase 3, Paso 3.0) = **604 passed, 0 failed**, verificado
directamente. `data/models/` con únicamente `.gitkeep` (ningún test de
este paso hace I/O — son contratos puros, sin persistencia todavía; la
persistencia real llega en el Paso 3.5, contra `tmp_path` exclusivamente
según `FASE3_EXECUTION_PLAN.md`).

**Definición de "Done" del Paso 3.0** (`FASE3_EXECUTION_PLAN.md` §0.3 +
sección del Paso 3.0): cumplida en su totalidad — archivos exactamente
los declarados, Fase 1/2 sin tocar, tests nuevos y suite completa en
verde, sin I/O de producción, este cierre documentado en `CONTINUITY.md`
antes del commit.

**Pendiente**: Paso 3.1 (Calibration Layer, sin entrenar) — no iniciado,
requiere nueva autorización explícita del usuario por paso, según la
metodología acordada.

### 0.3.1 Rectificación de contrato encontrada al preparar el Paso 3.1 (2026-07-30)

Al preparar la implementación de `calibration_layer.py`, se detectó una
contradicción real entre el contrato ya comiteado en el Paso 3.0
(`CalibrationOutput.model_version: str`, obligatorio) y el comportamiento
verificado de Fase 2: `PModelOutput.model_version` (`src/models/base.py`)
es `Optional[str]`, y `mlb_baseline.py:449`/`tennis_baseline.py:479`
construyen `PModelOutput(model_version=None, model_status=
MODEL_NOT_TRAINED, ...)` en producción — el estado más común, no un caso
extremo. El contrato de Fase 3, tal como se había comiteado, habría hecho
fallar `CalibrationOutput` exactamente en ese caso, que el propio Paso
3.1 exige manejar como criterio de aceptación.

Siguiendo la instrucción explícita del usuario ("cualquier contradicción
arquitectónica debe detener la implementación y reportarse antes de
continuar"), la implementación se detuvo, se reportaron la causa (error
de transcripción del Paso 3.0, no una decisión de diseño), el impacto y
3 alternativas; el usuario autorizó la Alternativa 1.

**Corrección aplicada** (no es un cambio arquitectónico — es la
rectificación de un contrato ya comiteado para que refleje exactamente
su fuente en Fase 2):

- `src/calibration/schemas.py`: `model_version: str` → `Optional[str] = None`.
- `CONTRACTS_FASE3.md` §2: actualizado con la nota de rectificación.
- `tests/unit/test_calibration_schemas.py`: nuevo test
  `test_model_not_trained_case_has_none_model_version` (cubre
  explícitamente `p_model_raw=None` + `model_version=None`
  simultáneamente, el caso real de `MODEL_NOT_TRAINED`) + caso adicional
  de round-trip de serialización con `model_version=None`.

Suite completa re-ejecutada tras la corrección: sin regresiones (ver
hash de commit de esta rectificación en `git log`). Ningún otro archivo
tocado — la corrección quedó limitada exactamente al campo señalado.

## 0.4 Fase 3 — Paso 3.1: Calibration Layer, sin entrenar (2026-07-30)

El usuario autorizó el Paso 3.1 con la misma disciplina del Paso 3.0
(alcance limitado, sin desviaciones arquitectónicas, sin entrenar
modelos, pruebas + suite completa + auditoría antes del commit), y
pidió explícitamente detener la implementación ante cualquier
contradicción con Fase 2 — lo que ocurrió antes de escribir código de
este paso (§0.3.1).

**Implementado**: `src/calibration/calibration_layer.py` —
`calibrate(model_output: PModelOutput, calibrator: Optional[Calibrator] = None,
now: Optional[datetime] = None) -> CalibrationOutput`, función 100% pura
(mismo estándar que `edge.py`/`expected_value.py`, Fase 2). `Calibrator`
es un `Protocol` mínimo, sin implementación concreta en el repositorio
— hoy todo llamador real pasa `calibrator=None` (ningún calibrador
entrenado existe, depende de D-1), por lo que el resultado observable en
producción es siempre `p_model_calibrated=None`/`calibration_version=None`.
La función sí aplica un `calibrator` sintético cuando se le pasa uno
(contract test con un doble de test, `_FakeCalibrator`, **no** un
calibrador entrenado real) — satisface literalmente
`MODEL_PIPELINE_SPEC.md` §3: "se construye y se prueba con fixtures
sintéticos, pero no se entrena ningún calibrador real en el alcance de
Fase 3".

**Invariantes verificados por test**: `p_model_raw` es copia exacta de
`model_output.p_model_yes`, nunca recalculado ni redondeado;
`calibrator=None` o `p_model_yes=None` (individualmente o juntos) ⟹
`p_model_calibrated`/`calibration_version`/`calibrated_at` en `None`
simultáneamente — incluido el caso explícito "calibrador presente pero
modelo no entrenado" (invariante que el propio plan pedía cubrir
mirando al futuro); `model_version`/`prediction_timestamp`/
`data_cutoff_timestamp` se propagan literalmente desde `PModelOutput`;
pureza confirmada (misma entrada, con y sin calibrador, dos llamadas →
resultado idéntico); `now` naive rechazado.

**Archivos**: exactamente los dos declarados en `FASE3_EXECUTION_PLAN.md`
para el Paso 3.1 — `src/calibration/calibration_layer.py` y
`tests/unit/test_calibration_layer.py`. Cero archivos de Fase 1/2
tocados (`git diff --stat` sobre los paquetes de Fase 1/2 vacío,
confirmado directamente).

**Tests**: 10 nuevos en `tests/unit/test_calibration_layer.py`. Suite
completa: 605 (Fase 2 + Paso 3.0 + rectificación) + 10 = **615 passed,
0 failed**. `data/models/` con únicamente `.gitkeep` (esta función no
hace I/O).

**Definición de "Done" del Paso 3.1**: cumplida — función pura, invariantes
cubiertos uno a uno, sin tocar Fase 1/2, este cierre documentado en
`CONTINUITY.md` antes del commit.

**Pendiente**: Paso 3.2 (Payoff Model) — no iniciado, requiere nueva
autorización explícita del usuario.

## 0.5 Fase 3 — Paso 3.2: Payoff Model (2026-07-30)

El usuario autorizó el Paso 3.2 con la misma disciplina de los pasos
anteriores. No apareció ninguna contradicción arquitectónica durante la
implementación — sí una decisión de alcance que se resolvió sin detener
el paso, documentada abajo, porque ya estaba prevista explícitamente por
DECISIÓN PENDIENTE D-3 (`PLAN_MASTER_FASE3.md` §8), no era nueva.

**Implementado**: `src/payoff/payoff_model.py` —
`estimate_payoff(record, side, opportunity_id, platform="KALSHI", now=None)
-> PayoffEstimate`, función 100% pura. `entry_price` reutiliza
literalmente `market_price_yes`/`market_price_no` (Fase 2,
`src/pricing/market_pricing.py`, sin cambios). `entry_fee`/`spread` se
propagan desde `NormalizedRecord.market` cuando existen (siempre `None`
en los datos reales de Kalshi observados hasta ahora). `payout=1.0` y
`breakeven_probability=entry_price` solo para `platform="KALSHI"` (hecho
estructural de la plataforma, no un dato inventado por evento) —
cualquier otra plataforma queda sin asumir.

**Decisión de alcance confirmada durante la implementación (no
detención, ya prevista por D-3)**: `net_ev_status` es **siempre**
`NetEvStatus.UNKNOWN`, incluso en el caso hipotético de que
`exchange_fee` estuviera poblado — verificado con un test explícito
(`test_net_ev_status_is_unknown_even_when_exchange_fee_is_populated`).
La razón: no existe una fórmula aprobada para combinar costos en un EV
neto real (`PLAN_MASTER_FASE3.md` §8, D-3), así que esta función no
recibe ninguna probabilidad de modelo como parámetro y no puede ni debe
intentar calcular `ev_to_settlement` — hacerlo habría exigido inventar
la fórmula que D-3 deja explícitamente pendiente. `max_acceptable_entry_price`
permanece `None` por el mismo motivo (requeriría una probabilidad que
esta función no recibe).

**Archivos**: exactamente los dos declarados en `FASE3_EXECUTION_PLAN.md`
para el Paso 3.2 — `src/payoff/payoff_model.py` y
`tests/unit/test_payoff_model.py`. Cero archivos de Fase 1/2 tocados.

**Tests**: 22 nuevos en `tests/unit/test_payoff_model.py`, incluida una
parametrización que recorre variantes de los 6 escenarios obligatorios
de `tests/unit/test_market_pricing.py` (Fase 2) confirmando
`net_ev_status=UNKNOWN` en todos. Suite completa: 615 + 22 = **637
passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.2**: cumplida — función pura, alcance
de D-3 respetado explícitamente (nunca se produce `COMPUTED`), sin tocar
Fase 1/2, este cierre documentado antes del commit.

**Pendiente**: Paso 3.3 (Evidence Engine) — no iniciado, requiere nueva
autorización explícita del usuario.

## 0.6 Fase 3 — Paso 3.3: Evidence Engine (2026-07-30)

El usuario autorizó el Paso 3.3. No apareció ninguna contradicción
arquitectónica que exigiera detener la implementación (ninguna colisión
con Fase 2, ninguna decisión de fórmula sin aprobar). Sí se encontró y
corrigió, sin detener el paso, un desajuste menor de documentación:
`ARCHITECTURE_FASE3.md` §4 no listaba `policy/schemas.py`
(`ConfidenceProfile`) ni `calibration/schemas.py` (`CalibrationOutput`)
como dependencias de `evidence/`, aunque la firma de `collect_evidence()`
ya definida en `EVIDENCE_EXPLAINABILITY_SPEC.md` §1 siempre los exigió
como parámetros. Se corrigió la línea de dependencia en
`ARCHITECTURE_FASE3.md` (mismo patrón ya usado por `opportunity/`, que
también depende de `policy/schemas.py` solo para tipos de datos, nunca
para lógica) — no es una decisión nueva, es sincronizar el diagrama con
una decisión ya tomada en el Paso 3.0 (dónde vive `ConfidenceProfile`).

**Implementado**: `src/evidence/evidence_engine.py` —
`collect_evidence(opportunity_id, record, calibration_output,
confidence_profile, now=None) -> List[EvidenceItem]`, función 100%
pura, sin ningún conocimiento de `PolicyDecision` ni de
`src/policy/hard_rules.py`/`soft_score.py`/`decision.py`/`manifest.py`/
`validation.py` ni de `src/explainability/` (verificado con test de
arquitectura por inspección del código fuente). 4 plantillas
(`EVIDENCE_EXPLAINABILITY_SPEC.md` §1.1): pitcher probable confirmado
(FOR), confianza de emparejamiento marginal (AGAINST), modelo con
historial de performance evaluado (FOR), divergencia significativa
modelo/consenso (AGAINST) — cada una se genera únicamente cuando su
campo fuente no es `None`, nunca como relleno.

**Adaptación menor respecto al texto de diseño original**: la plantilla
3 mencionaba "(n muestras)", pero `ConfidenceProfile` (contrato ya
comiteado) no expone un conteo de muestras — se usa el score
`model_reliability` en su lugar, documentado en el docstring del módulo,
para no fabricar un número que la función no recibe.

**Umbrales nuevos, PROVISIONAL** (sin respaldo empírico, mismo espíritu
que constantes ya existentes en Fase 2): banda de confianza de
emparejamiento marginal (+0.10 sobre el mínimo), umbral de
`model_reliability` para FOR (50.0/100), umbral de divergencia
modelo/consenso para AGAINST (0.10, mismo valor que
`_DISPERSION_ZERO_AT` de `quality_score.py`, Fase 2, reutilizado por
consistencia de escala).

**Archivos**: `src/evidence/evidence_engine.py`,
`tests/unit/test_evidence_engine.py` (los 2 declarados) +
`ARCHITECTURE_FASE3.md` (corrección de documentación, no código). Cero
archivos de Fase 1/2 tocados.

**Tests**: 35 nuevos en `tests/unit/test_evidence_engine.py`, incluida
una combinatoria completa de 16 casos (2⁴, supera el mínimo de 8 pedido)
que confirma la regla de no-fabricación sobre el producto cruzado de las
4 plantillas. Suite completa: 637 + 35 = **672 passed, 0 failed**.
`data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.3**: cumplida — función pura, las 4
plantillas cubiertas una a una más la combinatoria completa, regla de
dependencia verificada por test, sin tocar Fase 1/2, este cierre
documentado antes del commit.

**Pendiente**: Paso 3.4.1 (Policy Engine — Eligibility) — no iniciado,
requiere nueva autorización explícita del usuario.

## 0.7 Fase 3 — Paso 3.4.1: Policy Engine — Eligibility (2026-07-30)

Primer sub-bloque del Paso 3.4 (Policy Engine), el más grande del
roadmap, subdividido en 5 commits independientes según lo acordado. El
usuario confirmó el protocolo exacto por subpaso: autoriza → se
implementa → tests del subpaso → suite completa → resumen → el usuario
audita antes de autorizar el siguiente.

No apareció ninguna contradicción arquitectónica. Sí se corrigió, antes
de ejecutar la suite completa, un falso positivo en el propio test de
arquitectura nuevo de este subpaso: `test_does_not_import_hard_rules_or_soft_score_or_decision`
comparaba el texto completo del archivo (incluido el docstring, que
menciona en prosa "hard_rules.py" al explicar qué NO hace este módulo)
contra una lista de tokens prohibidos — el docstring disparaba un falso
"import" detectado. Corregido para inspeccionar únicamente los nodos
`Import`/`ImportFrom` del AST, no el texto crudo del archivo. No afecta
`src/policy/eligibility.py` en sí (nunca importó nada prohibido) — era
un defecto del test, detectado y corregido antes del commit, no una
contradicción de diseño.

**Implementado**: `src/policy/eligibility.py` —
`check_eligibility(opportunity_id, event_id, sport, side, generated_at,
now=None) -> EligibilityResult`, función 100% pura, primer gate del
Policy Engine (`POLICY_ENGINE_SPEC.md` §1.1, etapa [1]). Los 4 campos se
reciben como `Optional` deliberadamente -- `SignalInputs` (Fase 2) ya
los exige no-nulos por tipo, así que este gate existe para decidir,
ANTES de intentar construir un `SignalInputs`, si los datos de origen
alcanzan para evaluarlo en absoluto. No conoce Hard Rules ni Soft Score
(verificado por test de arquitectura vía AST).

**Archivos**: exactamente los 2 declarados —
`src/policy/eligibility.py`, `tests/unit/test_policy_eligibility.py`.
Cero archivos de Fase 1/2 tocados.

**Tests**: 10 nuevos (un caso por cada uno de los 4 campos obligatorios
ausente, `event_id` vacío/blank, todos ausentes a la vez, caso feliz,
regla de dependencia, pureza, `now` naive). Suite completa: 672 + 10 =
**682 passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.4.1**: cumplida.

**Pendiente**: Paso 3.4.2 (Policy Engine — Hard Block Rules) — no
iniciado, requiere nueva autorización explícita del usuario.

## 0.8 Fase 3 — Paso 3.4.2: Policy Engine — Hard Block Rules (2026-07-30)

Ninguna contradicción arquitectónica. Dos huecos deliberados, documentados
explícitamente en vez de inventar una decisión no aprobada:

- `invalid_event`: `POLICY_ENGINE_SPEC.md` §2.1 describe el disparador
  como "`EventStatus in (CANCELLED,)` o inconsistencia de horario
  irrecuperable" -- solo se implementó la primera mitad
  (`status == CANCELLED`); "inconsistencia de horario irrecuperable" no
  tiene una definición concreta en ningún documento aprobado, así que no
  se evaluó. Queda como hueco explícito para una futura decisión, no
  oculto en el código.
- `incompatible_contract`: `NormalizedRecord.market` (Fase 1/2) solo
  modela contratos binarios YES/NO -- no existe ningún campo que
  represente un contrato multi-outcome. La regla existe (satisface el
  catálogo cerrado de 7) pero `triggered=False` siempre contra el
  esquema actual, documentado explícitamente como tal, verificado por
  test dedicado (`test_incompatible_contract_never_triggers_today`).

**Implementado**: `src/policy/hard_rules.py` — 6 funciones puras
(`check_unsafe_matching`, `check_invalid_event`,
`check_invalid_or_closed_market`, `check_incompatible_contract`,
`check_corrupted_critical_data`, `check_known_result`) más
`evaluate_hard_block_rules()` que las agrega. La séptima regla
(`check_non_recoverable_inconsistency`) queda deliberadamente fuera del
evaluador -- su fuente de evidencia es "interno" (una excepción real
capturada por el orquestador, Paso 3.4.5, no un campo de
`NormalizedRecord`), así que vive como función independiente que ese
futuro orquestador invocará dentro de su propio `try/except`.

`check_known_result` reutiliza `HistoryRepository.get_results_for_event`
(Fase 2, sin cambios) y respeta el filtro temporal: un resultado
registrado ANTES de `data_cutoff_timestamp` dispara el bloqueo (era
conocimiento público en ese instante); uno registrado DESPUÉS se ignora
correctamente (usarlo sí sería la fuga) — cubierto por
`test_known_result_triggers_when_recorded_before_cutoff` y
`test_known_result_does_not_trigger_when_recorded_after_cutoff`.
`check_corrupted_critical_data` compara `validation_errors` (texto libre,
Fase 1/2) contra los nombres "bare" de `CORE_FIELDS` -- heurística
PROVISIONAL documentada como tal (sin campo estructurado en Fase 1/2
que vincule un error a un nombre de campo exacto).

**Archivos**: exactamente los 2 declarados —
`src/policy/hard_rules.py`, `tests/unit/test_hard_block_rules.py`. Cero
archivos de Fase 1/2 tocados.

**Tests**: 24 nuevos, incluidos los dos casos de fuga temporal de
`known_result` (con `db_path=tmp_path`, nunca la ruta de producción) y
el catálogo cerrado de 7 `rule_id`. Suite completa: 682 + 24 = **706
passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.4.2**: cumplida — las 7 reglas
existen (6 en el evaluador + 1 independiente), cada una trazable a un
campo real o a la evidencia "interno" que le corresponde, sin tocar
Fase 1/2.

**Pendiente**: Paso 3.4.3 (Policy Engine — Hard Hold Rules) — no
iniciado, requiere nueva autorización explícita del usuario.

## 0.9 Fase 3 — Paso 3.4.3: Policy Engine — Hard Hold Rules (2026-07-30)

Antes de escribir código se reportaron 2 hallazgos, siguiendo el
protocolo acordado:

1. **Corrección menor, sin decisión pendiente**: el docstring del Paso
   3.4.2 anotaba que el bloque HOLD viviría en un archivo separado
   (`hard_hold_rules.py`), pero `FASE3_EXECUTION_PLAN.md` dice
   explícitamente que se añade al mismo `hard_rules.py`. Se siguió el
   plan aprobado (autoridad del documento) y se corrigió el comentario
   desactualizado -- sin impacto en el código del Paso 3.4.2.
2. **Gap real entre documentos aprobados, con decisión del usuario**:
   `POLICY_ENGINE_SPEC.md` §2.2 prometía que el umbral de horas de
   `pending_lineup` sería "configurable en `PolicyManifest`", pero el
   contrato `PolicyManifest` (Paso 3.0) no tiene ningún campo para
   parámetros numéricos por regla Hard Rule. El usuario aprobó diferir
   esa decisión al Paso 3.4.5 (cuando `PolicyManifest` se cargue por
   primera vez) e implementar por ahora con un parámetro de función
   PROVISIONAL, sin modificar el contrato ya comiteado.

**Implementado**: 6 reglas HARD_HOLD_WATCH añadidas a
`src/policy/hard_rules.py` (mismo archivo del Paso 3.4.2, según el
plan): `check_pending_lineup` (time-gated, `hours_threshold` PROVISIONAL
= 3.0h), `check_unconfirmed_pitcher` (específico MLB, NO time-gated --
distinción deliberada de `pending_lineup`), `check_temporarily_stale_data`
(reutiliza el umbral de 3600s ya establecido en Fase 2, no uno nuevo),
`check_temporarily_insufficient_liquidity` (piso PROVISIONAL = 1000.0,
deliberadamente distinto del objetivo de normalización 50000.0 de
`quality_score.py`), `check_recoverable_missing_information`
(`missing_fields` menos `CORE_FIELDS`, complemento literal de
`corrupted_critical_data`, nunca duplicado), y
`check_unresolved_side_mapping` (**siempre** `triggered=True` -- D-2 sin
resolver, probado con un test que cita explícitamente
`PLAN_MASTER_FASE3.md` §5 Hallazgo #2 para que no se "arregle" por
accidente).

`evaluate_hard_hold_rules()` agrega las 6 -- a diferencia del evaluador
BLOCK, ninguna regla HOLD se excluye (todas son evaluables directamente
desde datos).

**Corrección de documentación** (no de código): `ARCHITECTURE_FASE3.md`
§4 no listaba `health/schemas.py` (`AnalysisHealth`) como dependencia de
`policy/`, aunque `check_temporarily_stale_data` la necesita
(`POLICY_ENGINE_SPEC.md` §2.2) -- corregido, mismo patrón que la
corrección análoga del Paso 3.3. Solo el contrato de datos;
`health/analysis_health.py` (la lógica, Paso 3.7) sigue sin
implementar.

**Bug propio corregido antes de la suite completa**: el helper local
`_record(**overrides)` del nuevo archivo de test hardcodeaba `sport=
Sport.MLB` como kwarg posicional, chocando con `overrides` cuando un
test necesitaba `sport=Sport.TENNIS` (`TypeError: multiple values for
keyword argument`). Corregido al patrón `dict(...).update(overrides)`
ya usado en los demás archivos de test de Fase 3 -- no afectó ningún
archivo de `src/`.

**Archivos**: `src/policy/hard_rules.py` (modificado, aditivo),
`tests/unit/test_hard_hold_rules.py` (nuevo) + `ARCHITECTURE_FASE3.md`
(corrección de documentación). Cero archivos de Fase 1/2 tocados.

**Tests**: 27 nuevos en `tests/unit/test_hard_hold_rules.py`, incluido
el catálogo cerrado de 6 `rule_id` y 4 verificaciones independientes de
que `unresolved_side_mapping` es constante. Suite completa: 706 + 27 =
**733 passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.4.3**: cumplida — 6 reglas HOLD
implementadas, `unresolved_side_mapping` verificablemente constante y
documentado por qué, decisión de `PolicyManifest` diferida
explícitamente (no oculta), sin tocar Fase 1/2.

**Pendiente**: Paso 3.4.4 (Policy Engine — Soft Score) — no iniciado,
requiere nueva autorización explícita del usuario.

## 0.10 Fase 3 — Paso 3.4.4: Policy Engine — Soft Score (2026-07-30)

Sin contradicciones arquitectónicas ni de contrato. A diferencia del
Paso 3.4.3, aquí no hubo ningún gap que reportar: `PolicyManifest`
(Paso 3.0) ya tenía `soft_score_weights`/`critical_minimums` como
campos `Dict[str, float]`, exactamente lo que este módulo necesita —
confirmado antes de escribir código. `weights`/`minimums` se reciben
como parámetros PROVISIONAL con defaults documentados; el Paso 3.4.5
los pasará desde el manifiesto real sin ningún cambio de contrato.

**Implementado**: `src/policy/soft_score.py` — `compute_soft_score_components()`
(los 5 componentes: `edge_strength` no crítico; `ev_neto_strength`,
`confidence_aggregate`, `data_quality_floor`, `operational_safety_floor`
críticos, fijo por Principio 9, no configurable), `compute_aggregate_soft_score()`
(suma ponderada sobre pesos ya redistribuidos, mismo patrón que
`compute_quality_score`, Fase 2), y `check_enter_eligible_by_soft_score()`
(implementación literal de la regla de no compensación,
`POLICY_ENGINE_SPEC.md` §3.1).

`edge_strength`/`ev_neto_strength` se normalizan a `[0,100]` reutilizando
el mismo rango `[-0.30, 0.30]` que `segment_by_edge`
(`src/evaluation/reports.py`, Fase 2, Paso 10) -- no un rango nuevo
inventado. `confidence_aggregate` promedia las 4 dimensiones de
`ConfidenceProfile` disponibles, redistribuyendo si falta alguna (mismo
espíritu que Fase 2). Todo componente crítico declara `minimum_required`
siempre, incluso cuando `value` es `None` (exigido por el propio
contrato `SoftScoreComponent`, Paso 3.0).

**Verificado en código el hallazgo central de la auditoría**: con
`PayoffEstimate` por defecto (`net_ev_status=UNKNOWN`, estado real y
universal del proyecto hoy -- Paso 3.2), `ev_neto_strength.value` y
`.passed_minimum` son `None`, lo que bloquea `ENTER` aunque
`edge_strength`/`confidence_aggregate`/`data_quality_floor`/
`operational_safety_floor` sean perfectos y `aggregate_soft_score` supere
el umbral (`test_ev_neto_strength_unknown_blocks_enter_even_with_everything_else_perfect`).
Se probó lo mismo, uno a la vez, para los otros 3 componentes críticos
(`test_single_critical_minimum_failure_blocks_enter_despite_high_aggregate`,
parametrizado) -- en los 4 casos, un score global alto NUNCA compensa un
mínimo crítico incumplido.

Dos bugs propios (no de `src/`) corregidos antes de la suite completa:
un caso de test violaba el invariante ya existente
`operational_safety + operational_risk == 100` (Corrección B, Paso 3.0)
al no declarar `operational_risk`; y una estimación manual de
`aggregate_soft_score` en el test parametrizado no coincidía con el
cálculo real (58.0 vs. una aserción de >=60.0) -- corregido ajustando el
umbral de la aserción a 50.0, que sigue demostrando el punto (score
global por encima del umbral, ENTER igualmente bloqueado) sin alterar
`src/policy/soft_score.py`.

**Archivos**: exactamente los 2 declarados —
`src/policy/soft_score.py`, `tests/unit/test_soft_score.py`. Cero
archivos de Fase 1/2 tocados.

**Tests**: 27 nuevos. Suite completa: 733 + 27 = **760 passed, 0
failed**. `data/models/` con únicamente `.gitkeep` (funciones sin I/O).

**Definición de "Done" del Paso 3.4.4**: cumplida — la no-compensación
está probada explícitamente para cada uno de los 4 componentes
críticos, uno a la vez, sin tocar Fase 1/2.

**Pendiente**: Paso 3.4.5 (Policy Engine — Decision + Manifest +
Validation) — no iniciado, requiere nueva autorización explícita del
usuario. Cierra el Paso 3.4 completo (5 sub-bloques).

## 0.11 Fase 3 — Paso 3.4.5: Policy Engine — Decision + Manifest + Validation (2026-07-31)

**CIERRA EL PASO 3.4 COMPLETO** (5 sub-bloques: 3.4.1 Eligibility, 3.4.2
Hard Block, 3.4.3 Hard Hold, 3.4.4 Soft Score, 3.4.5 Decision+Manifest+
Validation — mismo nivel de detalle que Fase 2 documentó el Paso 5b con
sus 5 bloques internos).

### Decisión pendiente resuelta (autorizada explícitamente antes de tocar código)

Al preparar `decide()`, resolver el diferimiento del Paso 3.4.3
(`pending_lineup` "configurable en `PolicyManifest`", sin campo para
ello) requería modificar el contrato `PolicyManifest` ya comiteado
(Paso 3.0). Siguiendo la instrucción explícita del usuario de detenerse
antes de tocar un contrato existente, se reportaron 3 alternativas; el
usuario aprobó la Alternativa 1.

**Rectificación aditiva aplicada**: `PolicyManifest.hard_rule_parameters:
Dict[str, float] = Field(default_factory=dict)` (`src/policy/schemas.py`)
-- simétrico a `critical_minimums`, retrocompatible (default `{}`, ningún
consumidor existente afectado). Catálogo cerrado de claves válidas
(`KNOWN_HARD_RULE_PARAMETER_KEYS`, aditivo en `hard_rules.py`):
`pending_lineup_hours_threshold`, `temporarily_stale_data_threshold_seconds`,
`temporarily_insufficient_liquidity_minimum`. `decide()` usa el valor del
manifiesto cuando la clave existe, y cae al default PROVISIONAL ya
declarado en `hard_rules.py` cuando no -- exactamente el diseño que el
usuario aprobó. `CONTRACTS_FASE3.md` §15, `tests/unit/fase3_factories.py`
y `tests/unit/test_policy_schemas.py` actualizados en consecuencia (2
tests nuevos: default vacío retrocompatible, round-trip con el campo
poblado).

### Bug real encontrado y corregido (no un contrato, código propio no comiteado)

Al probar la ruta ENTER, `PolicyDecision` (Paso 3.0) rechazó la
construcción: su propio invariante ("ningún `signal_type=ENTER` puede
coexistir con un `HardRuleResult` `BLOCK` `triggered=True` en su
lista") no distingue reglas activas de inactivas -- `decide()` estaba
pasando el catálogo COMPLETO evaluado (incluida una regla
`triggered=True` pero no activada en el manifiesto) al campo
`hard_rule_results` del `PolicyDecision` final, autorrechazándose el
propio `ENTER` legítimo. Corregido enteramente dentro de `decision.py`
(código nuevo, no comiteado todavía): `hard_rule_results` en el
resultado final ahora contiene únicamente las reglas ACTIVAS según el
manifiesto (evaluadas igual, pero filtradas antes de persistir) -- una
regla que no forma parte de la política no debe aparecer en la
auditoría de la decisión que esa política produjo. Ningún contrato
tocado; el fix vive enteramente en la orquestación.

**Implementado**:
- `src/policy/validation.py` -- `validate_policy_manifest()`: las 3
  validaciones determinísticas de Corrección H (cross-field consistency
  contra los catálogos cerrados de `hard_rules.py`/`soft_score.py`;
  range validation de valores de `critical_minimums`/`soft_score_weights`/
  `hard_rule_parameters`). Las 3 restantes (regression/histórico/
  promoción) dependen de histórico real o de un manifiesto previo --
  fuera de alcance, documentado explícitamente, no implementado a
  medias.
- `src/policy/manifest.py` -- `load_policy_manifest()`/
  `save_policy_manifest()`: I/O de archivo JSON únicamente, validando
  siempre antes de aceptar. `config/policy/` creado, vacío (el primer
  manifiesto real se publica en un paso posterior).
- `src/policy/decision.py` -- `decide()`: orquesta las 4 etapas
  (Eligibility -> Hard Block -> Hard Hold -> Soft Score), deteniéndose
  en la primera que produce una decisión. Fail-safe: cualquier excepción
  no controlada (incluida una re-validación defensiva del manifiesto, o
  `policy_manifest.sport != record.sport`) se traduce a
  `PolicyDecision(PASS, INVALID_ANALYSIS)`, nunca se propaga.

**Verificado en código, a nivel de orquestación completa, el hallazgo
central de la auditoría**: con el catálogo REALISTA completo activo
(las 7 reglas BLOCK + las 6 HOLD, incluida `unresolved_side_mapping`),
ningún `ENTER` es posible hoy aunque todo lo demás sea perfecto --
`unresolved_side_mapping` fuerza `WATCH` antes de llegar siquiera a
Soft Score (`test_watch_forced_by_unresolved_side_mapping_even_when_everything_else_perfect`).

**Archivos**: `src/policy/decision.py`, `src/policy/manifest.py`,
`src/policy/validation.py`, `config/policy/.gitkeep` (los declarados) +
`src/policy/schemas.py`, `CONTRACTS_FASE3.md`,
`tests/unit/fase3_factories.py`, `tests/unit/test_policy_schemas.py`
(rectificación aprobada) + `src/policy/hard_rules.py` (aditivo,
`KNOWN_HARD_RULE_PARAMETER_KEYS`). Cero archivos de Fase 1/2 tocados.

**Tests**: 21 (`test_policy_decision.py`, incluido el fuzz test
parametrizado de no-ENTER-con-bloqueo activo) + 16
(`test_policy_manifest_validation.py`) + 7 (`test_policy_fail_safe.py`)
+ 2 (`test_policy_schemas.py`, el campo nuevo) = 46 nuevos. Suite
completa: 760 + 46 = **806 passed, 0 failed**. `data/models/` con
únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.4 completo**: cumplida -- el Policy
Engine completo recibe inputs sintéticos y produce una `PolicyDecision`
determinista y trazable; el fuzz test de no-ENTER-con-bloqueo pasa sobre
el espacio de combinaciones probado; este cierre documentado antes del
commit.

**Pendiente**: Paso 3.5 (Opportunity Lifecycle + persistencia) — no
iniciado, requiere nueva autorización explícita del usuario. Primer
paso que tocará `data/engine.db` (solo vía `tmp_path` en tests, según lo
ya acordado).

## 0.12 Fase 3 — Paso 3.5: Opportunity Lifecycle + persistencia (2026-07-31)

Sin contradicciones arquitectónicas ni de contrato. Ninguna decisión
requirió pausar la implementación.

**Implementado**: `src/opportunity/opportunity_repository.py` --
`OpportunityRepository`, mismo patrón exacto que `HistoryRepository`
(Fase 2, Paso 0 — `CREATE TABLE IF NOT EXISTS`, triggers `RAISE(ABORT,
...)` que rechazan `UPDATE`/`DELETE` incluso con SQL crudo,
`PRAGMA foreign_keys = ON` por conexión). Dos tablas nuevas, aditivas,
en el mismo `data/engine.db`: `opportunities` (una fila por CADA
`state_version` de una `Opportunity` -- confirmado en
`ARCHITECTURE_FASE3.md` §3, "solo `state_version` nuevo es INSERT,
nunca UPDATE") y `opportunity_evaluations` (una fila por
`OpportunityEvaluation`, ya `frozen=True` a nivel de contrato).

Sin FK dura entre ambas tablas -- mismo motivo que `event_snapshots`/
`event_results` en Fase 2 (el enlace es lógico por `opportunity_id`, no
de fila; `opportunities` no tiene una fila "canónica" única por
`opportunity_id`, tiene una por `state_version`).

**Validación de secuencia añadida** (no exigida por ningún contrato de
Paso 3.0, decisión de implementación dentro del alcance de este paso,
consistente con "rechazar antes de persistir" ya usado en
`validate_policy_manifest`, Paso 3.4.5): `save_opportunity()`/
`save_opportunity_evaluation()` exigen `state_version == último + 1`
(o `1` si es la primera fila) -- rechazan saltos y duplicados.
`save_opportunity()` también exige `previous_signal_id=None` únicamente
en `state_version==1`, no vacío en cualquier versión posterior --
validación de presencia, no de igualdad exacta contra un
`evaluation_id` concreto (esa correlación exacta depende de un futuro
orquestador de punta a punta que todavía no existe en ningún paso del
roadmap; inventar esa regla exacta aquí habría sido una decisión de
diseño no pedida por este paso, documentada explícitamente en vez de
improvisada).

**Archivos**: exactamente los 2 declarados —
`src/opportunity/opportunity_repository.py`,
`tests/unit/test_opportunity_repository.py`. Cero archivos de Fase 1/2
tocados (incluidos `src/storage/repository.py`/`history_repository.py`,
verificado también por test de arquitectura vía AST).

**Tests**: 17 nuevos, TODOS contra `db_path=tmp_path / "test.db"` --
nunca `data/engine.db` de producción (confirmado: `data/engine.db` está
en `.gitignore`, sin diff registrable, y su MD5 se verificó sin cambios
antes/después de correr la suite). Cubren: inserción simple + round-trip
completo, determinismo de `opportunity_id`, encadenamiento de
`state_version`/`previous_signal_id` (2 versiones consecutivas, primera
fila nunca sobrescrita), rechazo de salto/duplicado de `state_version`,
rechazo de `previous_signal_id` ausente tras la primera versión, rechazo
de `UPDATE`/`DELETE` crudo sobre ambas tablas, `PRAGMA foreign_keys=ON`
confirmado. Suite completa: 806 + 17 = **823 passed, 0 failed**.
`data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.5**: cumplida -- repositorio completo,
probado exclusivamente contra bases de datos temporales, sin ninguna
ejecución contra `data/engine.db` de producción todavía (esa primera
ejecución real queda para cuando exista un orquestador de punta a punta
que efectivamente llame a este repositorio con datos reales -- ningún
paso del roadmap actual lo hace todavía).

**Pendiente**: Paso 3.6 (Explainability Engine) — no iniciado, requiere
nueva autorización explícita del usuario.

## 0.13 Fase 3 — Paso 3.6: Explainability Engine (2026-07-31)

### Adición contractual correctiva (autorizada explícitamente antes de tocar código)

Al preparar `explain()`, se encontró que `ExplanationOutput`
(esbozado en `EVIDENCE_EXPLAINABILITY_SPEC.md` §2 durante la auditoría
original) nunca se incluyó en la lista cerrada de 16 contratos de
`CONTRACTS_FASE3.md`, ni se scaffoldeó `src/explainability/` en el Paso
3.0 — `FASE3_EXECUTION_PLAN.md`, Paso 3.6, solo declaraba
`explainability_engine.py` como archivo nuevo, asumiendo implícitamente
un contrato que no existía. Siguiendo la instrucción explícita del
usuario de detenerse antes de introducir comportamiento nuevo o tocar
contratos, se reportaron 3 alternativas; el usuario aprobó la
Alternativa 1.

**Aplicado**: `src/explainability/schemas.py` (nuevo) — `ExplanationOutput`
como `StrictModel`, mismo patrón que los 16 contratos originales
(invariantes: `headline`/`reasons_explained` no vacíos, `generated_at`
tz-aware). Documentado como §17 de `CONTRACTS_FASE3.md` (adición
correctiva, no un contrato "menos válido" que los 16 originales — misma
exigencia de tests: invariantes, `extra="forbid"`, round-trip completo,
factory en `fase3_factories.py`). `PLAN_MASTER_FASE3.md` actualizado
para reflejar 17 contratos totales.

### Implementado

`src/explainability/explainability_engine.py` — `explain(policy_decision,
evidence_items, evaluation_id, calibration_version=None,
net_ev_status_is_unknown=False, now=None) -> ExplanationOutput`, función
100% pura. Consume únicamente `PolicyDecision`/`EvidenceItem[]` ya
calculados — nunca re-deriva desde `NormalizedRecord` ni desde
`QualityScoreOutput` (Principio 6, verificado por test de arquitectura
vía AST: solo puede importar `policy.schemas`/`evidence.schemas`/
`explainability.schemas`). `calibration_version`/`net_ev_status_is_unknown`
se reciben como primitivos (`Optional[str]`/`bool`), no como
`CalibrationOutput`/`NetEvStatus` completos -- decisión de diseño (no
una contradicción: el propio criterio de aceptación de este paso ya
exigía que la función tuviera acceso a esa información de algún modo)
que evita ampliar la regla de dependencia de `ARCHITECTURE_FASE3.md` §4
para incluir `calibration/`/`payoff/`.

`headline` se construye enteramente desde campos de `PolicyDecision`
(`signal_type`/`disposition`/`aggregate_soft_score`) -- nunca desde
datos externos a ese contrato. `disclaimers` obligatorio no vacío
cuando `calibration_version is None` o `net_ev_status_is_unknown=True`,
verificado con los 4 casos (ninguno, uno, otro, ambos).

**Archivos**: `src/explainability/__init__.py`,
`src/explainability/schemas.py` (adición aprobada),
`src/explainability/explainability_engine.py` (declarado en el plan) +
`tests/unit/fase3_factories.py` (aditivo, `make_explanation_output`).
Cero archivos de Fase 1/2 tocados.

**Tests**: 7 (`test_explainability_schemas.py`, mismo rigor que los 16
contratos originales) + 14 (`test_explainability_engine.py`, incluido
el test de arquitectura de imports). Suite completa: 823 + 21 = **844
passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.6**: cumplida — toda razón mostrada en
`ExplanationOutput` es trazable a un `SignalReason` o `EvidenceItem`
real, verificado por test.

**Pendiente**: Paso 3.7 (Analysis Health) — no iniciado, requiere nueva
autorización explícita del usuario.

## 0.14 Fase 3 — Paso 3.7: Analysis Health (2026-07-31)

### Contradicción encontrada y rectificada (autorizada explícitamente antes de tocar código)

Al preparar `analysis_health.py`, releer el invariante literal de
`CONTRACTS_FASE3.md` §5 ("ningún campo de `AnalysisHealth` puede
aparecer como término de `SoftScoreComponent` **ni de `HardRuleResult`**")
reveló una contradicción real con código YA COMITEADO: `POLICY_ENGINE_SPEC.md`
§2.2 diseñó explícitamente la regla Hard Hold `temporarily_stale_data`
para usar `AnalysisHealth.staleness_seconds`, y así se implementó en el
Paso 3.4.3 (`check_temporarily_stale_data`, ya en 3 commits: 3.4.3,
3.4.4 sin afectar, 3.4.5). El propio `FASE3_EXECUTION_PLAN.md`, Paso
3.7, ya formulaba el criterio real de forma más estrecha ("nunca como
input de `soft_score.py`"), coincidiendo con lo implementado -- solo el
texto de `CONTRACTS_FASE3.md` §5 quedó redactado más amplio de lo
realmente aprobado.

Siguiendo la instrucción explícita del usuario, se detuvo la
implementación, se reportaron 3 alternativas con el análisis completo;
el usuario aprobó la Alternativa 1 (corregir el texto del invariante,
sin tocar código ya comiteado).

**Rectificación aplicada**: `CONTRACTS_FASE3.md` §5 corregido -- el
Principio 5 ("sin doble ponderación dentro del Policy Engine") prohíbe
específicamente que `AnalysisHealth` sea input de `soft_score.py` (ahí
sí habría doble conteo real, porque `ConfidenceProfile` ya agrega
señales de calidad equivalentes en el score ponderado). Una Hard Rule
específica y ya catalogada (`temporarily_stale_data`) SÍ puede leer un
campo de `AnalysisHealth` como su fuente de evidencia -- una compuerta
binaria de catálogo cerrado no es "ponderación". Ningún código de
`src/` se modificó por esta rectificación.

### Implementado

`src/health/analysis_health.py` -- `compute_analysis_health(opportunity_id,
record, quality_score_output, evidence_items, now=None) -> AnalysisHealth`,
función 100% pura. `completeness_signal`/`consistency_signal` derivan de
`QualityScoreOutput.components["data_completeness"]`/["bookmaker_dispersion"]`
(Fase 2, escalados de [0,1] a [0,100], nunca recalculados).
`evidence_density` es el conteo simple de `EvidenceItem`.
`staleness_seconds` se calcula en segundos crudos desde el timestamp de
fuente más viejo en `NormalizedRecord.data_quality.source_timestamps`
(mismo patrón que `_component_freshness`/`validate_staleness`, Fase 2 --
`QualityScoreOutput` solo expone la versión ya normalizada a [0,1], no
los segundos reales).

**Verificado por 3 tests de arquitectura, no solo documentado**:
`soft_score.py` nunca importa `src.health.analysis_health` ni
`src.health.schemas` (regla rectificada); `hard_rules.py` importa
`src.health.schemas` (el contrato, ya usado por
`temporarily_stale_data` desde el Paso 3.4.3) pero nunca
`src.health.analysis_health` (la lógica de cómputo); `decision.py`
tampoco importa la lógica de cómputo, solo recibe un `AnalysisHealth`
ya calculado como parámetro.

**Archivos**: exactamente los 2 declarados —
`src/health/analysis_health.py`, `tests/unit/test_analysis_health.py` +
la rectificación aprobada en `CONTRACTS_FASE3.md` §5. Cero archivos de
Fase 1/2 tocados.

**Tests**: 14 nuevos, incluidos los 3 de arquitectura. Suite completa:
844 + 14 = **858 passed, 0 failed**. `data/models/` con únicamente
`.gitkeep`.

**Definición de "Done" del Paso 3.7**: cumplida -- el test de
arquitectura que impide el uso de `AnalysisHealth` en `soft_score.py`
está en verde y se re-ejecuta como parte de la suite completa desde
este punto en adelante.

**Pendiente**: Paso 3.8 (Evaluation & Learning Framework, estructura) —
no iniciado, requiere nueva autorización explícita del usuario.

## 0.15 Fase 3 — Paso 3.8: Evaluation & Learning Framework (2026-07-31)

Sin contradicciones arquitectónicas ni de contrato. Ninguna decisión
requirió pausar la implementación.

**Implementado**:
- `src/backtesting/metrics.py` (extendido, aditivo) — `ece()` (reutiliza
  `calibration_curve()` tal cual, promedio ponderado de
  `|mean_predicted - mean_actual|`), `clv()` (Closing Line Value de una
  observación, `closing_price - entry_price`, `None` si algún precio
  está fuera de `[0,1]` -- nunca se clampa, mismo principio de
  `market_pricing.py` Fase 2), `roi_teorico()`, `drawdown()` (caída
  peak-to-trough ABSOLUTA, no porcentual -- decisión explícita para no
  asumir una normalización no pedida), `profit_factor()`. Las 4
  funciones originales de Fase 2 no se tocaron (mismo archivo de test
  extendido, sus tests siguen intactos).
- `src/evaluation/learning.py` (nuevo) — `build_evaluation_record()`:
  ensambla un `EvaluationRecord` (Paso 3.0) a partir de un
  `metric_value` ya calculado por el llamador, validando que
  `metric_name` pertenezca al catálogo cerrado de su `EvaluationScope`
  (`EVALUATION_LEARNING_SPEC.md` §1) antes de construir el registro.
  `record_id` determinístico (`compute_evaluation_record_id`, mismo
  espíritu que `compute_opportunity_id`, Paso 3.0). El invariante
  `sample_size=0 ⟹ metric_value=None` ya estaba en el contrato
  `EvaluationRecord` desde el Paso 3.0 -- este módulo no necesitó
  reimplementarlo, solo lo hereda al construir.

**Advertencia de alcance reafirmada** (GATE-0, `PLAN_MASTER_FASE3.md`
§0, `FASE3_AUDIT_REPORT.md` §15): todo `EvaluationRecord` producido en
este paso usa fixtures sintéticos pequeños (4 muestras en el caso de
integración de `brier_score`, por ejemplo) -- ninguno pretende
representar performance real del sistema. Sigue bloqueado por DECISIÓN
PENDIENTE D-1 (histórico real: `feature_snapshots`/`event_results` en 0
filas).

**Archivos**: `src/backtesting/metrics.py` (modificado, aditivo),
`src/evaluation/learning.py` (nuevo) + sus tests. Cero archivos de Fase
1/2 tocados fuera de la extensión aditiva ya declarada — confirmado que
ninguna de las 4 funciones/tests originales de `metrics.py` cambió.

**Tests**: 19 nuevos en `tests/unit/test_backtesting_metrics.py`
(extendido, mismo archivo que las 14 pruebas de Fase 2, todas intactas)
+ 18 nuevos en `tests/unit/test_evaluation_learning.py` (incluido un
caso por cada una de las 5 dimensiones y 3 casos de integración de
punta a punta con `metrics.py`). Suite completa: 858 + 19 + 18 = **895
passed, 0 failed**. `data/models/` con únicamente `.gitkeep`.

**Definición de "Done" del Paso 3.8**: cumplida -- framework de 5
dimensiones ensamblable con fixtures; ningún `EvaluationRecord`
producido pretende representar performance real, documentado
explícitamente aquí.

**Pendiente**: Paso 3.9 (registro genérico de modelos) — no iniciado,
requiere nueva autorización explícita del usuario. Último paso del
roadmap aprobado.

## 0.16 Paso 3.9 declarado innecesario + CIERRE DEL ROADMAP REQUIRED FOR PHASE 3 (2026-07-31)

### Paso 3.9: hallazgo arquitectónico, autorizado sin implementar código

Al preparar la implementación, verificar directamente el código reveló
que la premisa del Paso 3.9 ("`registry.py` hoy solo indexa MLB, hay que
generalizarlo") es falsa: `src/models/tennis_baseline.py` (Fase 2, Paso
11) ya tiene su propio `TennisTrainedArtifact` y su propia
`load_latest_tennis_artifact()` -- persistencia completa e
independiente, mismo patrón de archivos hermanos que usa `registry.py`
para MLB. No es un descuido: el docstring de `tennis_baseline.py`
documenta una **decisión explícita y ya aprobada del Design Proposal de
Fase 2** (Ambigüedad C/D): *"`registry.py` está acoplado a
`MlbTrainedArtifact` específicamente"*, cada deporte con persistencia
propia, deliberadamente desacoplada. `TennisTrainedArtifact` tampoco es
un superset de `MlbTrainedArtifact` (tiene `round_categories: List[str]`
propio) -- no son unificables bajo un tipo genérico sin inventar algo
no pedido.

Siguiendo la instrucción explícita del usuario, se detuvo la
implementación antes de escribir cualquier código, se reportaron 3
alternativas; el usuario aprobó la Alternativa 1: declarar el Paso 3.9
innecesario, sin implementar ningún código, sin romper el
desacoplamiento entre deportes que Fase 2 ya estableció
deliberadamente. `FASE3_EXECUTION_PLAN.md` actualizado con el hallazgo
completo, texto original del paso conservado como registro histórico
(mismo criterio que todo este documento: no se reescribe retroactivamente
lo ya aprobado, se documenta la desviación explícitamente).

**Cero archivos de `src/` tocados por este hallazgo** -- es
exclusivamente documental.

### CIERRE DEL ROADMAP REQUIRED FOR PHASE 3 -- auditoría final

Verificación de punta a punta ejecutada al cerrar este documento (no una
recopilación de los cierres individuales, sino comandos re-ejecutados
ahora mismo contra el estado real del repositorio):

- **16 commits** desde `v2.0-baseline` (`4f602cf` a `66875f0`, más este
  cierre): 1 auditoría documental, 1 plan de ejecución, 14 pasos de
  implementación (3.0, la rectificación de 3.0, 3.1, 3.2, 3.3, 3.4.1-
  3.4.5, 3.5, 3.6, 3.7, 3.8) + este cierre.
- **`git diff --stat v2.0-baseline HEAD` sobre los paquetes de Fase 1/2**
  (`src/models`, `src/signals`, `src/pricing`, `src/uncertainty`,
  `src/storage`, `src/backtesting`, `src/evaluation`, `src/matching`,
  `src/quality`, `src/connectors`, `src/normalization`): únicamente 3
  archivos, los 3 ya aprobados explícitamente -- `src/backtesting/metrics.py`
  (aditivo, Paso 3.8), `src/evaluation/learning.py` y
  `src/evaluation/schemas.py` (archivos NUEVOS dentro del paquete
  `evaluation/` ya existente, Pasos 3.0/3.8). `src/evaluation/reports.py`
  (Fase 2) confirmado sin ningún cambio. Ningún otro archivo de Fase 1/2
  tocado en ningún momento de todo el proceso.
- **Suite completa**: `pytest -q` → **895 passed, 0 failed** (498 de
  Fase 2 + 397 nuevos de Fase 3, acumulados sin ninguna regresión en
  ningún punto del proceso).
- **`data/models/`**: únicamente `.gitkeep`.
- **`data/engine.db`**: MD5 `663480bdd2526d88351e19dcb84c0bfa`, sin
  cambios desde antes del Paso 3.5 (primer y único paso que construyó
  código capaz de tocarlo, y solo lo hizo contra `tmp_path` en tests).
- **`v2.0-baseline`**: sin mover ni recrear en ningún momento.

### Qué se construyó (resumen)

Los 16 contratos originales + `ExplanationOutput` (adición correctiva
del Paso 3.6, ahora 17) como código validado (`pydantic`,
`extra="forbid"`); Calibration Layer (sin calibrador real entrenado);
Payoff Model (siempre `net_ev_status=UNKNOWN`, D-3 pendiente); Evidence
Engine (4 plantillas, no-fabricación verificada); Policy Engine completo
(Eligibility, 7 Hard Block Rules, 6 Hard Hold Rules incluida
`unresolved_side_mapping` siempre activa, Soft Score con no-compensación
verificada, `decide()` orquestando las 4 etapas con fail-safe);
`PolicyManifest` con validación de Corrección H (schema/rango/
consistencia); Opportunity Lifecycle con persistencia append-only
(probada solo contra `tmp_path`); Explainability Engine; Analysis
Health (con su regla de no-uso en Soft Score verificada por test);
Evaluation & Learning Framework (andamiaje de 5 dimensiones con
fixtures sintéticos).

### Qué queda estructuralmente bloqueado (reafirmado, no resuelto aquí)

Exactamente lo que `FASE3_AUDIT_REPORT.md` §15 y `PLAN_MASTER_FASE3.md`
§8 ya concluían, ahora confirmado en código real y probado en cada capa
(Paso 3.2, 3.4.3, 3.4.4, 3.4.5): mientras D-1 (histórico real), D-2
(mapeo participante↔YES de Kalshi) y D-3 (fórmula de costos reales) no
se resuelvan con una decisión explícita del usuario, el sistema **no
puede producir un `ENTER` real** -- `unresolved_side_mapping` fuerza
`WATCH` incondicionalmente, y `ev_neto_strength` (mínimo crítico) nunca
puede pasar su umbral mientras `net_ev_status` sea `UNKNOWN` de forma
universal. Esto es el comportamiento correcto y deliberado, no una
limitación de esta implementación.

### Conclusión

**Todo el roadmap REQUIRED FOR PHASE 3 de `IMPLEMENTATION_ROADMAP_FASE3.md`
está completo.** Las columnas RECOMMENDED LATER y REJECTED AS PREMATURE
permanecen exactamente donde `FASE3_AUDIT_REPORT.md` las dejó -- ninguna
se promovió a REQUIRED sin pasar por una decisión explícita del usuario
en el camino. La conclusión CONDITIONAL GO de `FASE3_AUDIT_REPORT.md`
§15 se mantiene sin cambios: la especificación y ahora también la
implementación completa de la arquitectura (contratos, Policy Engine,
Payoff Model, Evidence/Explainability, Opportunity Lifecycle, Evaluation
Framework) están listas y probadas con fixtures; la puesta en producción
de cualquier etapa que dependa de histórico real, del mapeo de Kalshi, o
de costos reales, sigue bloqueada por D-1/D-2/D-3, sin resolver.

## 0.17 Resolución de D-2: mapeo participante↔YES (2026-07-31)

### Contexto y autorización

Tras el cierre del roadmap REQUIRED FOR PHASE 3 (§0.16), el usuario
autorizó explícitamente abordar DECISIÓN PENDIENTE D-2 ("resolver el
mapeo participante↔YES de un contrato Kalshi concreto"), con la misma
disciplina de todo el proceso: detenerse ante cualquier contradicción
arquitectónica/contractual/de diseño, reportarla con alternativas antes
de decidir, y no ampliar el alcance sin aprobación.

### Investigación (antes de proponer nada)

Se inspeccionó directamente el código y datos reales capturados
(`data/raw/kalshi/*.json`) antes de diseñar cualquier solución. Hallazgo
central: **D-2 estaba, en gran parte, ya resuelto desde Fase 1**
(commit baseline `c5eb9e7`, anterior a Fase 2). Cada evento de Kalshi
publica 2 mercados (uno por participante), cada uno con un
`yes_sub_title` que nombra explícitamente a qué participante se refiere
ese YES (verificado contra 2 eventos reales, MLB y ATP:
`"yes_sub_title": "Atlanta"` / `"Terence Atmane"`, con el `title` del
mercado literalmente fraseado como "¿Ganará X?"). `src/matching/market_matcher.py::_select_market`
ya selecciona, de esos 2 mercados, el que tiene mayor similitud de
nombre (`name_similarity`) entre `yes_sub_title` y `participant_a` --
es decir, el `market_id` que llega a `NormalizedRecord` ya es, por
construcción, el contrato cuyo YES corresponde a `participant_a`. Esto
es exactamente la "capa de integración participante→YES" que 4 archivos
de Fase 1/2 (`src/models/base.py`, `mlb_baseline.py`,
`tennis_baseline.py`, `src/signals/edge.py`) documentaban reiteradamente
como inexistente -- una afirmación desactualizada desde Fase 1, nunca
corregida en Fase 2, heredada sin verificar en toda la documentación de
Fase 3 (incluida la propia auditoría original, por mí).

**El hueco real, no cosmético**: `_select_market` es heurístico (fuzzy
name matching) y su confianza (`best_score`) se calculaba pero se
descartaba -- solo se convertía en una advertencia de texto libre
(`match_warnings`) cuando caía por debajo de `0.72`, y se perdía en
silencio cuando era alta. No existía ningún campo estructurado y
consultable con el que el Policy Engine pudiera saber "qué tan seguro
estoy de que este `market_id` es el lado de `participant_a`".

### Decisión (reportada, con alternativas, autorizada explícitamente)

Se detuvo la implementación antes de escribir código, se presentaron 3
alternativas (exponer la confianza como campo nuevo en `DataQuality`;
resolver solo documentalmente sin tocar Fase 1/2; reconstruir la señal
parseando texto de `match_warnings`). El usuario autorizó la
Alternativa 1 explícitamente, incluyendo tocar código de Fase 1/2 --
**la primera vez en las 17 commits previas de todo el proceso de Fase 3
que se modifica un archivo de Fase 1/2**.

### Implementado

**Fase 1 (autorizado explícitamente, cambios estrictamente aditivos)**:
- `src/models/schemas.py` -- `DataQuality.side_selection_confidence: Optional[float] = None`
  (campo nuevo, default `None`, retrocompatible -- `StrictModel` con
  `extra="forbid"`, ninguna construcción existente de `DataQuality` en
  ~15 archivos de test se ve afectada).
- `src/matching/market_matcher.py` -- `_select_market()` ahora devuelve
  también el `best_score` ya calculado (antes descartado) como tercer
  elemento de la tupla; `KalshiEventMatch` gana el campo
  `market_selection_confidence: Optional[float] = None`;
  `find_best_kalshi_event()` lo propaga; `apply_kalshi_match()` lo
  persiste en `record.data_quality.side_selection_confidence`
  únicamente cuando efectivamente se adjuntan datos de mercado (mismo
  gate ya existente para `MARKET_DEPENDENT_FIELDS`). Ningún
  comportamiento de selección/matching existente cambia -- se sigue
  eligiendo exactamente el mismo mercado que antes, con los mismos
  criterios; lo único nuevo es que el número ya calculado ahora se
  guarda en vez de descartarse.

**Fase 3 (dentro del alcance ya establecido de este proceso)**:
- `src/policy/hard_rules.py::check_unresolved_side_mapping` -- ya NO es
  una constante `triggered=True`. Ahora recibe `record` y dispara
  únicamente cuando `side_selection_confidence` es `None` o está por
  debajo de `EVENT_NAME_MATCH_MIN_CONFIDENCE` (Fase 1,
  `config/settings.py` -- mismo umbral que `_select_market` ya usa,
  ninguno nuevo inventado). `evaluate_hard_hold_rules()` actualizado
  para pasarle `record`.

### Contratos afectados

| Contrato | Cambio | Tipo |
|---|---|---|
| `DataQuality` (Fase 1, `src/models/schemas.py`) | Campo nuevo `side_selection_confidence: Optional[float] = None` | Aditivo, retrocompatible |
| `KalshiEventMatch` (Fase 1, dataclass interno de `market_matcher.py`, no un contrato Pydantic público) | Campo nuevo `market_selection_confidence: Optional[float] = None` | Aditivo, retrocompatible |
| `HardRuleResult` (Fase 3, Paso 3.0) | Sin cambios de schema -- solo cambia la LÓGICA que produce el `rule_id="unresolved_side_mapping"` | N/A (comportamiento, no contrato) |

Ningún contrato perdió campos, cambió tipos, ni rompió `extra="forbid"`.

### Documentación actualizada

`PLAN_MASTER_FASE3.md` §8, `POLICY_ENGINE_SPEC.md` §2.2,
`FASE3_AUDIT_REPORT.md` §7/§13/§15, `MODEL_PIPELINE_SPEC.md` §2,
`IMPLEMENTATION_ROADMAP_FASE3.md` -- todos marcan D-2 como resuelta,
conservando el texto original tachado/anotado (no reescrito
retroactivamente, mismo criterio de todo este proyecto) con un puntero
a esta sección.

### Auditoría final de este cambio

- **Tests nuevos**: 4 en `tests/unit/test_market_matcher.py` (Fase 1,
  extendido) + 4 en `tests/unit/test_hard_hold_rules.py` (Fase 3,
  reemplazando 2 tests que protegían la constante `True` -- incluido un
  test que confirma el mismo umbral que `_select_market` ya usa).
- **Regresión de Fase 1/2**: los 7 tests originales de
  `test_market_matcher.py` pasan SIN modificación. Todos los demás
  archivos de Fase 1/2 que construyen `DataQuality(...)` (≈15 archivos)
  siguen pasando sin tocar una sola línea -- el campo nuevo tiene
  default `None`.
- **Regresión de Fase 3**: `test_policy_decision.py`/`test_policy_fail_safe.py`
  (Paso 3.4.5, escenario "catálogo completo activo") confirmados sin
  cambios -- sus fixtures no fijan `side_selection_confidence`
  explícitamente, así que siguen recibiendo `None` por defecto y
  `unresolved_side_mapping` sigue disparando exactamente igual que
  antes en esos escenarios "sin evidencia".
- **Suite completa**: `pytest -q` → **899 passed, 0 failed** (895 tras
  el cierre del roadmap + 8 nuevos, 4 de Fase 1 + 4 de Fase 3, neto 0
  por el reemplazo en `test_hard_hold_rules.py`).
- **`data/models/`**: únicamente `.gitkeep`.
- **`v2.0-baseline`**: sin mover.

### Impacto arquitectónico (resumen)

D-2 pasa de "decisión pendiente, bloqueo incondicional" a "resuelta,
bloqueo condicionado a evidencia real por registro". `unresolved_side_mapping`
ya no es un techo estructural absoluto sobre `ENTER` -- ahora se
comporta como el resto del catálogo Hard Hold, activo por registro según
datos reales. **Esto NO habilita `ENTER` real por sí solo**: D-3
(fórmula de costos reales, `net_ev_status` siempre `UNKNOWN`) sigue
bloqueando `ev_neto_strength` como mínimo crítico del Soft Score,
independientemente de D-2. D-1 (histórico real) sigue bloqueando toda
evaluación con significancia estadística real. La conclusión
CONDITIONAL GO de `FASE3_AUDIT_REPORT.md` §15 se mantiene: 2 decisiones
pendientes en vez de 3, ninguna resuelta por asunción.

## 0.18 Investigación y reencuadre de D-3: fees reales de Kalshi (2026-07-31, NO RESUELTA)

### Contexto y autorización

Tras resolver D-2, el usuario pidió priorizar D-3 (fórmula de costos
reales) antes de abrir D-1 (histórico), "porque completa el modelo
económico del motor antes de comenzar la integración con datos
históricos" -- misma disciplina: detenerse ante cualquier contradicción,
reportar con alternativas, esperar aprobación.

### Investigación (mismo rigor que D-2, con un resultado distinto)

Verificación directa contra datos y código propios: ningún payload de
Kalshi jamás capturado (`data/raw/kalshi/*.json`, ~2000+ mercados en 8
capturas) contiene un campo de fee/comisión; `src/connectors/kalshi.py`
solo llama a `/events`/`/markets`, nunca un endpoint de fees -- coincide
exactamente con la premisa original de D-3.

**Pero D-3 estaba mal encuadrada**: no es "esperar a que Kalshi exponga
un campo" -- Kalshi cobra vía una **fórmula pública basada en precio**
(`kalshi.com/docs/kalshi-fee-schedule.pdf`, "Fee Schedule for July
2026 - 7.7.26 Update" según los resultados de búsqueda), no un campo por
mercado. Se intentó `WebFetch` a la fuente primaria **3 veces**; las 3
devolvieron HTTP 429 (límite de tasa del servidor). Dos fuentes
secundarias (búsqueda web sintetizada + `pm.wiki`, que dice citar el fee
schedule oficial) convergen en la estructura: `taker_fee ≈ 0.07 × precio
× (1-precio)` por contrato (simétrica, máximo en precio=0.50,
`maker_fee ≈ 25%` del taker) -- pero DIFIEREN en la regla de redondeo
exacta, y ninguna es la fuente primaria verificada.

### Decisión (reportada, autorizada explícitamente: NO implementar)

El usuario aprobó explícitamente **no** codificar la fórmula con esta
evidencia -- "prefiero mantener `net_ev_status=UNKNOWN` antes que
introducir un cálculo financiero basado únicamente en fuentes
secundarias" -- mismo estándar de evidencia que D-2 (verificación
directa, nunca de memoria ni de fuentes no primarias), aplicado aquí en
sentido contrario: en D-2 la evidencia directa SÍ alcanzaba; en D-3 no
alcanza, y el sistema se queda como estaba en vez de forzar una
resolución. El usuario pidió explícitamente dejar la infraestructura
preparada para incorporar la fórmula "inmediatamente después de validar
la fuente primaria".

### Implementado (Fase 3 únicamente -- cero cambios de Fase 1/2 en este paso)

`src/payoff/payoff_model.py` -- nueva función
`_estimate_kalshi_taker_fee(price) -> Optional[float]`: **siempre
devuelve `None`**, con un docstring extenso que documenta la
verificación pendiente, cita la fuente primaria exacta, y advierte
explícitamente contra rellenarla con la fórmula de fuentes secundarias
sin repetir la verificación. `estimate_payoff()` ahora calcula
`entry_fee` probando primero el campo real del registro
(`record.market.exchange_fee`, sigue siendo siempre `None` en la
práctica -- Kalshi no lo expone) y, si falta, consulta el punto de
enganche (`platform == "KALSHI"` únicamente) -- que hoy también devuelve
siempre `None`. **Cero cambio de comportamiento observable**:
`entry_fee` sigue siendo `None` en todos los escenarios reales,
`net_ev_status` sigue siendo `NetEvStatus.UNKNOWN` siempre, exactamente
como antes de este paso.

### Contratos afectados

Ninguno. `PayoffEstimate` (Paso 3.0) no cambia -- `entry_fee` ya era
`Optional[float]`, la nueva lógica solo decide de dónde intenta leerlo,
nunca cambia su tipo ni sus invariantes.

### Auditoría de este cambio

- **Tests nuevos**: 3 en `tests/unit/test_payoff_model.py` -- confirman
  que el punto de enganche devuelve `None` para 6 precios distintos
  (incluido `None`), que `entry_fee` sigue `None` vía el punto de
  enganche cuando `platform=KALSHI`, y que plataformas distintas de
  KALSHI no lo consultan en absoluto. Documentación ejecutable: si
  alguien rellena `_estimate_kalshi_taker_fee()` sin pasar por esta
  misma verificación, el primer test falla.
- **Regresión**: los 22 tests originales de `test_payoff_model.py`
  (incluidos los que ya confirmaban `net_ev_status=UNKNOWN` universal,
  Paso 3.2) pasan SIN modificación.
- **Suite completa**: `pytest -q` → **902 passed, 0 failed** (899 tras
  la resolución de D-2 + 3 nuevos).
- **`data/models/`**: únicamente `.gitkeep`. **`v2.0-baseline`**: sin
  mover. **Fase 1/2**: cero archivos tocados en este paso (a diferencia
  de D-2).

### Documentación actualizada

`PLAN_MASTER_FASE3.md` §8, `FASE3_AUDIT_REPORT.md` §13/§15 -- D-3
marcada como "REENCUADRADA", no como "resuelta" -- distinción
deliberada: D-2 se resolvió con evidencia verificada; D-3 se investigó,
se entendió mejor, y se dejó preparada, pero sigue abierta.

### Estado para continuar

**D-3 sigue sin resolver.** Próximo paso si se retoma: reintentar
`WebFetch` a `https://kalshi.com/docs/kalshi-fee-schedule.pdf` (el 429
puede ser temporal, no un bloqueo permanente), o que el usuario
proporcione el contenido verificado del fee schedule oficial. Cuando
eso ocurra, el único cambio necesario es rellenar el cuerpo de
`_estimate_kalshi_taker_fee()` con la fórmula confirmada y actualizar
`net_ev_status`/`ev_neto_strength` en consecuencia -- ningún otro
archivo debería necesitar cambios, ese es el propósito del punto de
enganche. **D-1 (histórico real) permanece como la única decisión
restante no abordada todavía.**

## 0.19 Resolución de D-1: contradicción operacional, Política de Retención, reactivación permanente (2026-08-01, RESUELTA)

### Contexto y autorización

Tras el reencuadre de D-3 (§0.18), el usuario autorizó abrir D-1
(captura histórica) "siguiendo el mismo proceso de auditoría: si
detectas cualquier contradicción arquitectónica, contractual o de
diseño, detente, repórtala y espera aprobación".

### Contradicción operacional encontrada (no de código)

Investigación directa de `launchctl print
gui/501/local.prediction-market-engine.run-e2e-historical` mostró un
registro activo (`runs = 3`, `last exit code = 0`), no el error
`"Could not find service"` que la documentación describía. Evidencia
cruzada:

- `logs/run_e2e.stdout.log` (552 KB) registraba **7 ejecuciones reales**
  entre 2026-07-29 y 2026-07-31, con llamadas reales a MLB Stats API,
  ESPN Tennis, SofaScore y Kalshi.
- `data/engine.db` mostraba escrituras reales recientes en
  `event_snapshots` (660+ filas nuevas).
- `scripts/run_e2e.py` no fija sus propios paths de log -- las rutas
  solo coinciden con las de `StandardOutPath`/`StandardErrorPath` del
  plist si `launchd` lo invocó, descartando una ejecución manual.

Esto contradecía directamente `CONTINUITY.md` (esta misma sección, texto
histórico): *"El LaunchAgent sigue DESCARGADO... Debe permanecer
descargado hasta finalizar la Fase 2 completa"* -- en algún momento
posterior al cierre de Fase 2, el LaunchAgent fue cargado
(`launchctl bootstrap`) fuera de cualquier sesión de este proyecto
documentada, sin autorización de Fase 3. Reportado de inmediato, sin
tomar ninguna acción, siguiendo la disciplina estándar de "detente y
reporta".

**Resolución (Alternativa 1, aprobada):** `launchctl bootout` sobre el
job activo, restableciendo el estado documentado. Verificado:
`launchctl print` volvió a devolver `"Could not find service"`,
`launchctl list` dejó de mostrarlo. Revisión de
`scripts/run_e2e.py`/`scripts/pipeline_lock.py` confirmó que
`--mode historical` no tiene comportamiento oculto ni guardas de
confirmación -- coincide exactamente con lo documentado en el commit
`f931822`. Ninguna otra contradicción arquitectónica o contractual
encontrada.

### Política de Retención de Datos (prerrequisito exigido antes de reactivar)

El usuario pidió cerrar la política de retención/purgado (recomendación
#1 y #7 de `FASE2_CIERRE_FINAL.md` §7) antes de reactivar D-1 de forma
permanente. Investigación previa a diseñar encontró una segunda
contradicción real: la recomendación original pedía "purgado de
`event_snapshots`/`feature_snapshots`", pero esas tablas son
**append-only a nivel de base de datos** (`src/storage/history_repository.py`,
triggers `RAISE(ABORT, ...)` en `UPDATE`/`DELETE`) y su inmutabilidad es
un contrato explícito de `TEMPORAL_REPRODUCIBILITY_SPEC.md` §3
(reproducibilidad determinística). Reportado, con 3 alternativas; el
usuario aprobó la Alternativa 1: **retención indefinida, sin purga, para
las tablas históricas del motor** -- rotación/compresión/purga
únicamente para `data/raw/*.json` y `logs/*.log`, más respaldo periódico
de `data/engine.db` completo. Archivado en frío de las tablas del motor
queda explícitamente diferido.

Documento resultante: [`DATA_RETENTION_POLICY.md`](DATA_RETENTION_POLICY.md)
(propuesta completa, basada en tasas de crecimiento reales medidas:
~2 MB/día en `engine.db`, ~9 MB/corrida en `data/raw`, 129 GiB libres).

### Implementado (mecanismo de la política, Fase 3 únicamente)

- `scripts/data_maintenance.py`: funciones puras e inyectables
  (`classify_raw_file`, `classify_rotated_log`, `file_age_days`,
  `process_raw_files`, `rotate_log_if_needed`, `purge_old_logs`,
  `backup_database`, `prune_old_backups`, `run_maintenance`) -- mismo
  patrón de pureza que `estimate_payoff`/`calibrate` (`now` inyectable,
  sin I/O oculto). Backup de `engine.db` vía la API de backup en
  caliente de `sqlite3` (segura en concurrencia con `run_e2e.py`, no
  ejecuta SQL sobre las tablas del motor). Lock de instancia única
  propio (`data/.maintenance.lock`, reutiliza
  `scripts/pipeline_lock.py`), independiente del lock de
  `run_e2e.py`. Nunca actúa sobre archivos con menos de 1 día de
  antigüedad.
- `scripts/launchd/local.prediction-market-engine.data-maintenance.plist`:
  segundo LaunchAgent, diario a las 03:00, mismo protocolo que el
  histórico (`RunAtLoad=false`, versionado en el repo, copia instalada
  en `~/Library/LaunchAgents/`).
- `config/settings.py`: nueva constante `DATA_BACKUPS_DIR` (`data/backups/`),
  mismo patrón que los directorios existentes.
- `.gitignore`: `data/backups/*` (excepto `.gitkeep`), `data/.maintenance.lock`.

### Contratos afectados

Ninguno. Este paso es puramente operacional (`scripts/`, `config/settings.py`,
documentación) -- cero cambios en `src/`.

### Auditoría de este cambio

- **Tests nuevos**: 25 en `tests/unit/test_data_maintenance.py` --
  umbrales exactos de clasificación (7/90/14 días), guarda de antigüedad
  mínima, rotación por tamaño y por cambio de día, backup+restauración
  verificada byte-a-byte, poda de backups, idempotencia end-to-end, y un
  test AST (no substring, mismo patrón que Paso 3.4.1) que falla si
  `data_maintenance.py` alguna vez importa `history_repository`.
- **Suite completa**: `pytest -q` → **927 passed, 0 failed** (902 previos
  + 25 nuevos).
- **`data/models/`**: únicamente `.gitkeep`. **`v2.0-baseline`**: sin
  mover (verificado explícitamente: `2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df`,
  intacto). **Fase 1/2 (`src/`)**: cero archivos tocados.
- Dry-run manual contra `data/raw/` real de producción confirmó que
  ningún archivo actual (todos <3 días) sería tocado -- comportamiento
  esperado, sin pérdida de datos recientes.

### Reactivación (D-1 RESUELTA)

Con el mecanismo implementado, probado y auditado, ambos LaunchAgents
fueron cargados de forma permanente:
`local.prediction-market-engine.run-e2e-historical` (captura horaria,
D-1) y `local.prediction-market-engine.data-maintenance` (mantenimiento
diario 03:00) -- ambos vía `launchctl bootstrap` desde sus copias en
`~/Library/LaunchAgents/`, verificados con `launchctl list`/`launchctl print`
tras la carga. `RunAtLoad=false` en ambos: cargar no dispara una corrida
inmediata, solo arma el próximo ciclo.

### Documentación actualizada

`DATA_RETENTION_POLICY.md` (nuevo), `FASE2_CIERRE_FINAL.md` §7 punto 1
(D-1) y punto 7 (purgado) marcados resueltos, `PLAN_MASTER_FASE3.md` §8
(D-1 marcada RESUELTA).

### Estado para continuar

**Las 3 decisiones pendientes de Fase 3 quedan cerradas**: D-1 resuelta
(captura histórica activa de forma permanente, con mantenimiento
automatizado), D-2 resuelta (§0.17), D-3 reencuadrada y documentada como
dependencia externa verificable (§0.18, sin resolver por diseño --
requiere fuente primaria). No hay ningún trabajo de Fase 3 adicional
autorizado en este momento. El histórico real (`event_snapshots`/
`feature_snapshots`) empezará a acumular volumen suficiente para
calibración/backtesting con datos reales de forma orgánica a partir de
ahora -- ningún paso de código adicional es necesario para eso, solo
tiempo de captura.

## 0. CIERRE FORMAL DE FASE 2 (2026-07-26)

**Fase 2 queda declarada oficialmente cerrada.** Los 13 pasos de
`PLAN_PHASE2.md` §12 están completos, testeados (498 tests, 0
regresiones) y committeados. El objetivo definido en `PLAN_PHASE2.md` se
considera cumplido. Documentos formales del cierre:

- `PLAN_PHASE2.md` §18 ("Estado final de implementación — Cierre formal
  de Fase 2") — mapeo paso→commit, verificación de los 13 criterios de
  aceptación de §14 contra el código real, y la excepción documentada al
  criterio 12 (tres archivos de Fase 1 con extensiones aditivas
  autorizadas: `repository.py`, `connectors/mlb.py`,
  `normalization/tennis_normalizer.py`).
- [`FASE2_CIERRE_FINAL.md`](FASE2_CIERRE_FINAL.md) — Informe Final de
  Cierre: objetivos alcanzados, arquitectura final, componentes,
  cobertura de pruebas, riesgos conocidos, alcance explícitamente
  excluido, y recomendaciones para una futura Fase 3.

**No existe ningún "Paso 13" en el plan.** Cualquier trabajo posterior
(lógica de clasificación de umbrales ENTER/WATCH/PASS, o cualquier otro
punto de las recomendaciones de Fase 3 en `FASE2_CIERRE_FINAL.md` §7)
requiere una nueva propuesta y aprobación explícita del usuario antes de
iniciarse — no está autorizado por el cierre de Fase 2 en sí.

## 0.1 Validación Institucional post-cierre + fix de aislamiento de tests (2026-07-26)

Tras el cierre formal, el usuario pidió una Validación Institucional:
correr el motor extremo a extremo sobre mercados reales (MLB + tenis
ATP) usando exclusivamente código ya existente. Reporte completo:
[`FASE2_VALIDACION_INSTITUCIONAL.md`](FASE2_VALIDACION_INSTITUCIONAL.md).
Resultado: las 10 etapas (ingesta, normalización, matching, quality
score, mercado, consenso no-vig, modelo, confidence, edge/EV, señal)
corrieron sin ninguna excepción sobre 4 registros reales, con propagación
honesta de `None` en cada punto sin dato real disponible — incluido un
caso con mercado Kalshi real emparejado (tenis, `P_market_YES=0.99`) que
ejercitó la cadena completa por primera vez sobre un precio vivo.

**Hallazgo real encontrado y corregido** (commit `eff754e`): el registro
de modelos MLB de producción (`data/models/`, ignorado por git, nunca
comprometido en ningún commit) se contaminaba con artefactos sintéticos
en **cada corrida de `pytest`** — `tests/unit/test_train_mlb_model_script.py`
aislaba correctamente `HistoryRepository`, pero `scripts/train_mlb_model.py`
nunca exponía forma de redirigir dónde se escribe el artefacto entrenado,
cayendo siempre a la ruta de producción por defecto. Corrección aplicada,
estrictamente limitada al aislamiento del test/script (flag
`--models-dir` opcional en el script, pasado explícitamente a `tmp_path`
en los tests) — **cero cambios en `src/`**, ninguna lógica de predicción/
pipeline/modelo/EDGE/EV/clasificación tocada. Verificado con 3 corridas
independientes tras el fix (dos de la batería completa, una del archivo
antes ofensivo en aislamiento): `data/models/` queda con únicamente
`.gitkeep` cada vez, reproducible. `data/engine.db` real sin cambios en
todo el proceso (`event_snapshots=93`, `feature_snapshots=0`,
`event_results=0`, `normalized_records=94`).

**Repositorio verificado limpio y listo para Fase 3** al cierre de esta
actualización: `git status --short` vacío, 498 tests en verde,
`data/models/` sin artefactos sintéticos y sin regenerarlos en corridas
futuras de `pytest`.

Todo lo aquí escrito fue verificado contra el estado real del repositorio
en el momento de cada actualización (comandos git, lectura de archivos,
ejecución de tests, inspección directa de `data/engine.db`) — no
reconstruido de memoria.

---

## 1. Estado actual del repositorio

Working tree limpio (`git status --short` → sin salida), verificado
inmediatamente antes de esta actualización.

## 2. Rama activa

`phase-2-dev` — creada desde el commit baseline de Fase 1
(`c5eb9e77d51eeebb2c6c114ebce1810074b7372b`). `main` permanece exactamente
en ese mismo commit, sin cambios. Ningún merge, ningún commit directo
sobre `main`.

## 3. Último commit completo de código (hash)

```
eff754ef8054adbd9aacc65d7ba825aea1bbe674
```
Mensaje: `Fix test-isolation defect: scripts/train_mlb_model.py leaked synthetic artifacts into production data/models/`

Post-cierre de Fase 2 (§0/§0.1): único cambio de código autorizado desde
el cierre formal, estrictamente de aislamiento de test/script (flag
`--models-dir` en `scripts/train_mlb_model.py`, uso explícito de
`tmp_path` en `tests/unit/test_train_mlb_model_script.py`). Cero cambios
en cualquier otro archivo de `src/` (`git diff --name-only -- src/`
vacío, verificado). El commit de código de Fase 2 propiamente dicha
(Paso 12) sigue siendo `08daf260` — ver §5 para la línea de tiempo
completa incluyendo los commits documentales del cierre.

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado en los cierres anteriores).

## 4. Último paso completamente terminado

**Paso 12 (`src/signals/signal_schema.py`) — COMPLETO, AUDITADO Y
COMMITTEADO.** Implementa el esquema de señal pedido literalmente por
`PLAN_PHASE2.md` §12 ("solo tipos ENTER/WATCH/PASS y sus inputs, sin
lógica de umbral"): `Side` (YES/NO), `SignalType` (ENTER/WATCH/PASS) y
`SignalInputs` (`dataclass(frozen=True)`, por lado, nunca por evento).
Precedido de una revisión contractual completa, cuatro ambigüedades (A-D)
resueltas una por una con la metodología de 6 puntos pedida
explícitamente por el usuario (descripción/ventajas/desventajas/impacto
en arquitectura/impacto en escalabilidad futura/recomendación final), y
una auditoría arquitectónica final de 6 propiedades (aditividad total,
ausencia de ciclo de dependencias, ausencia de acoplamiento nuevo,
reutilizable por futuros motores de clasificación, `SignalInputs` = solo
datos nunca comportamiento, lógica de clasificación fuera del archivo) —
las seis verificadas contra el código real (`grep`/`git diff`) antes de
escribir una sola línea. Decisiones aprobadas: **A1** (un `SignalInputs`
por lado, nunca ambos lados en un objeto — mismo invariante "nunca
cruzados" del Paso 8, ahora reforzado a nivel de tipo); **B2**
(`SignalType` vive separado de `SignalInputs`, sin ningún campo
`signal_type` en el contenedor de datos — mismo patrón ya usado
`PModelOutput`→`QualityScoreOutput`, tipo nuevo en vez de mutar uno
existente); **C2** (`dataclass(frozen=True)`, no pydantic — refuerza la
pureza ya declarada en `edge.py`/`expected_value.py`); **D3** (acoplamiento
mínimo: reutiliza solo `ModelStatus`/`Sport`, dos enums estables sin
lógica ya usados por `edge.py`/`expected_value.py`/`evaluation/reports.py`
— nunca embebe `PModelOutput`/`QualityScoreOutput`/`NormalizedRecord`
completos). Ningún módulo existente modificado — dos archivos nuevos
únicamente, verificado con `git diff --name-only HEAD` (vacío) antes del
commit.

Con este cierre: **Pasos 0, 1, 2, 3, 4, 5a, 5b, 6, 7, 8, 9, 10, 11 y 12
están todos completos.** El plan oficial (`PLAN_PHASE2.md` §12) no
enumera pasos posteriores al 12 con nombre de archivo — el siguiente
trabajo pendiente es la lógica de clasificación de umbrales
(ENTER/WATCH/PASS real) sobre `SignalInputs`, explícitamente diferida y
no autorizada todavía (§16 sigue prohibiendo "umbrales ENTER/WATCH/PASS
calibrados" sin nueva decisión explícita).

## 5. Todos los commits (orden cronológico, `git log --reverse`)

| # | Hash completo | Fecha | Mensaje | Rama |
|---|---|---|---|---|
| 1 | `c5eb9e77d51eeebb2c6c114ebce1810074b7372b` | 2026-07-21 | Phase 1 baseline: audited data infrastructure and safe matching | main (= inicio de phase-2-dev) |
| 2 | `92af29db5564053000219f21076198766e625c61` | 2026-07-22 | Phase 2 Step 0: append-only historical storage | phase-2-dev |
| 3 | `a471668c2086a2054b06c7493af37a63151f0be9` | 2026-07-22 | Phase 2 Step 1: Feature Registry | phase-2-dev |
| 4 | `7756319a6169b1ddecb6ffb1b8a34fbcb7f4d531` | 2026-07-23 | Phase 2 Step 2: MLB feature computation | phase-2-dev |
| 5 | `32677d66ef33e9595ba0c1e0e3edace2375c156c` | 2026-07-23 | Phase 2 Step 3: side-aware market pricing (P_market_YES/P_market_NO) | phase-2-dev |
| 6 | `b97092d166cf7a0bfc7f65f9bb8754ccdf65b12c` | 2026-07-23 | Phase 2 Step 4: no-vig consensus in two steps + event matching gate | phase-2-dev |
| 7 | `b261f80d1bef58b105fad4da0c302c156f00b78f` | 2026-07-24 | Complete HistoryRepository pipeline and entry-point wiring for Step 0c/0d | phase-2-dev |
| 8 | `7175b788d539cbd375728ca4628e2a3adc516d2c` | 2026-07-24 | Prepare Step 0d for automation: single-instance lock, historical capture mode, SQLite busy_timeout | phase-2-dev |
| 9 | `f9318227a40336136fcff1120ea536b80d377dfd` | 2026-07-24 | Add LaunchAgent for hourly historical capture (Step 0d automation) | phase-2-dev |
| 10 | `328e69c0acd392b2f67c2e3e09c83ff8ce7384ce` | 2026-07-24 | Phase 2 Step 5a: MLB model infrastructure (dataset builder, training pipeline, inference contract) | phase-2-dev |
| 11 | `8a155776b2a1bb9e4811f97886987b0c889b2269` | 2026-07-26 | Phase 2 Step 5b, Blocks 1-5: feature_snapshots/event_results wiring + real training pipeline | phase-2-dev |
| 12 | `dce1e464357b912ec23ecda66ac2c057a2fb47c2` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 5b (Blocks 1-5) | phase-2-dev |
| 13 | `822d4dc9b69652842e3c83dbb3b2b44e38f8cd78` | 2026-07-26 | Phase 2 Step 7: uncertainty/confidence quality score (HEURISTIC_V1) | phase-2-dev |
| 14 | `215f62b7e4f6d20ea4faaa51129ec50870fa4bc8` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 7 (Quality Score / Uncertainty) | phase-2-dev |
| 15 | `03f21c0fc0af6c4e363e3ff84287edba5715b2fd` | 2026-07-26 | Phase 2 Step 6: simple MLB Elo baseline (Baseline 2) | phase-2-dev |
| 16 | `7ac93e1cf12c53769fcc0eb0df294ac4099ac417` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 6 (MLB Elo baseline) | phase-2-dev |
| 17 | `038bff0fae343d230cef778b263b4b2f4e794b14` | 2026-07-26 | Phase 2 Step 8: EDGE_YES/EDGE_NO + Expected Value (bruto) | phase-2-dev |
| 18 | `945170bec1bfb4747bad0268a1015dfcbf10a350` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 8 (EDGE/EV) | phase-2-dev |
| 19 | `f15fc592860d3d047a361958b2044a32c7c80b69` | 2026-07-26 | Phase 2 Step 9: backtesting infrastructure (dataset + walk-forward splitter + metrics) | phase-2-dev |
| 20 | `72e5f19ddb717b8689bf3fa51ae3d5c033d8567a` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 9 (backtesting infrastructure) | phase-2-dev |
| 21 | `cfb8dc09562f198c36cd0c6528be440b79cb15e8` | 2026-07-26 | Phase 2 Step 10: baseline comparison reports (Baseline 0 vs 1 vs 2) | phase-2-dev |
| 22 | `99e902968b3ec194fb698a170686a6386495ea1e` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 10 (baseline comparison reports) | phase-2-dev |
| 23 | `d6fc559a28f3244d7f4ca1b97d66275dc1d70c60` | 2026-07-26 | Phase 2 Step 11: tennis baseline (features + model infra + results sync) | phase-2-dev |
| 24 | `7e7d94536cc2d7360efee282850cf246c9a0d671` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 11 (tennis baseline) | phase-2-dev |
| 25 | `08daf2603bf25ec542f44a526f551c94118a423e` | 2026-07-26 | Phase 2 Step 12: signal schema (SignalInputs + SignalType/Side, no threshold logic) | phase-2-dev |
| 26 | `05e6d9bcb6d694fae73fff8a693f22c69956b1d9` | 2026-07-26 | Update CONTINUITY.md: close out Phase 2 Step 12 (signal schema) | phase-2-dev |
| 27 | `57768b4445353e3b1bfb7be236f268f738a66e69` | 2026-07-26 | Formalize Phase 2 closure in PLAN_PHASE2.md | phase-2-dev |
| 28 | `016975f` (hash corto; commit self-referencial, ver `git log` para el completo) | 2026-07-26 | Update CONTINUITY.md + add FASE2_CIERRE_FINAL.md: formal closure of Phase 2 | phase-2-dev |
| 29 | `0ad6da11807f376230326eaf774168f2a87837ad` | 2026-07-26 | CONTINUITY.md: record actual hash of the previous self-referential closure commit | phase-2-dev |
| 30 | `ff7372801a01655047616d435d64e14de6d89c57` | 2026-07-26 | Add institutional end-to-end validation report for Phase 2 | phase-2-dev |
| 31 | `eff754ef8054adbd9aacc65d7ba825aea1bbe674` | 2026-07-26 | Fix test-isolation defect: scripts/train_mlb_model.py leaked synthetic artifacts into production data/models/ | phase-2-dev |
| 32 | (este commit, ver `git log` tras cerrar) | 2026-07-26 | Update CONTINUITY.md + FASE2_VALIDACION_INSTITUCIONAL.md: post-closure validation and test-isolation fix | phase-2-dev (HEAD tras este cierre) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/mlb_features.py                            [Fase 2]  Sin cambios desde el Paso 5b
src/features/tennis_features.py                        [Fase 2 -- Paso 11 COMPLETO]
  compute_rest_days           start_time del partido menos start_time del último
                              partido ANTERIOR conocido del mismo jugador (emparejado
                              por espn_id), corte de leakage = data_cutoff_timestamp
  compute_tournament_round_context   directo -- competition.round.displayName
                              (verificado real contra la API de ESPN, nunca heurística
                              de texto, prohibida por PLAN_PHASE2.md §16)
  TennisFeatureInputs/compute_tennis_features/persist_tennis_feature_snapshot
                              mismo patrón que mlb_features.py (Paso 2/5b)

src/models/mlb_baseline.py, mlb_elo.py, registry.py     [Fase 2 -- 5a/5b/6/9 COMPLETOS]  Sin cambios en esta actualización
src/models/tennis_baseline.py                           [Fase 2 -- Paso 11 COMPLETO]
  build_tennis_training_dataset / split_dataset_temporally / train_tennis_baseline_model
                              mismo patrón que mlb_baseline.py, DUPLICADO (no importado)
                              para no acoplar tennis_baseline.py a un módulo cerrado
  TennisTrainedArtifact + persistencia INDEPENDIENTE (JSON+joblib propios,
                              prefijo de archivo "tennis_baseline_*" -- convive sin
                              colisión con "mlb_baseline_*" en el mismo DATA_MODELS_DIR,
                              nunca importa/modifica registry.py)
  DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30  heurística de ingeniería PROVISIONAL
                              (10-20 obs/dimensión aplicado a 2 features de tenis,
                              no las ~26 de MLB), revisable con evidencia
  predict_tennis_baseline / predict_tennis_baseline_from_features  núcleo de
                              inferencia único compartido, mismo patrón que MLB (Paso 9)
  Vectorización: rest_days.participant_{a,b} escalares directos;
                              tournament_round_context codificado como bandera 0/1 por
                              categoría DESCUBIERTA en el split de TRAIN (nunca una lista
                              fija inventada, nunca de validación)

src/pricing/                                            [Fase 2]  Sin cambios
src/uncertainty/                                        [Fase 2 -- Paso 7 COMPLETO]  Sin cambios

src/signals/                                            [Fase 2 -- Pasos 8 y 12 COMPLETOS]
  edge.py                    compute_edge_yes/compute_edge_no -- sin cambios en esta actualización
  expected_value.py          compute_ev_yes_bruto/compute_ev_no_bruto,
                             compute_ev_yes_neto/compute_ev_no_neto (siempre None hoy)
                             -- sin cambios en esta actualización
  signal_schema.py           [NUEVO -- Paso 12 COMPLETO]
    Side(YES/NO)             vocabulario nuevo, autocontenido
    SignalType(ENTER/WATCH/PASS)  vocabulario puro, ninguna función lo calcula todavía
    SignalInputs             dataclass(frozen=True), por lado (nunca por evento):
                             event_id/sport/side/model_status/p_model/market_price/
                             edge/ev_bruto/ev_neto/confidence/confidence_method/
                             generated_at. __post_init__ solo valida (tz-aware,
                             rangos [0,1]) -- nunca calcula ni decide.
                             Importa únicamente ModelStatus (models.base) y
                             Sport (models.schemas) -- mismos dos enums que ya
                             usan edge.py/expected_value.py/evaluation/reports.py.
                             Ninguna función de clasificación en este archivo.

src/storage/                                            [Fase 1 + Fase 2]  Sin cambios desde el Paso 6
src/pipelines/mlb_pipeline.py, mlb_results_sync.py      Sin cambios desde el Paso 5b
src/pipelines/tennis_pipeline.py                        [Fase 2 -- extensión aditiva del Paso 11]
  fetch_features=True (default) + _fetch_tennis_feature_inputs  -- wiring de
                              feature_snapshots, mismo patrón que el Bloque 2 del
                              Paso 5b para MLB. Consulta SOLO event_snapshots ya
                              persistidos (nunca red), empareja por espn_id.
src/pipelines/tennis_results_sync.py                    [Fase 2 -- Paso 11 NUEVO]
  sync_tennis_event_results   mismo patrón que mlb_results_sync.py; reutiliza
                              EspnTennisConnector.get_scoreboard ya existente
                              (competitors[].winner, verificado real). NO distingue
                              POSTPONED/CANCELLED (sin verificar cómo ESPN Tennis los
                              representa) -- se cuentan honestamente como
                              not_yet_decided, nunca fabricados.
src/normalization/tennis_normalizer.py                  [Fase 2 -- extensión aditiva del Paso 11]
  model_inputs.context gana participant_{a,b}_espn_id + tournament_round (mismo
                              rol que away_team_id/home_team_id en MLB)
src/connectors/mlb.py                                   Sin cambios desde el Paso 5b (Bloque 1)
src/connectors/espn_tennis.py                           Sin cambios -- extract_matches ya preservaba
                              competitor.id/round vía dict(competition), sin saberlo
                              hasta que Paso 11 lo aprovechó

src/backtesting/                                        [Fase 2 -- Paso 9 COMPLETO]  Sin cambios en esta actualización
  __init__.py / dataset.py / splitter.py / metrics.py    build_backtest_dataset,
                              walk_forward_splits (HistoryRepository TEMPORAL por
                              fold), brier_score/log_loss_metric/accuracy_metric/
                              calibration_curve (n_bins=10)

src/models/mlb_baseline.py                              [Fase 2 -- extensión aditiva del Paso 9]  Sin cambios en esta actualización
  predict_mlb_baseline_from_features  wrapper delgado sobre el mismo núcleo de
                              inferencia que predict_mlb_baseline
                              (_predict_proba_from_vectorized_features)

src/evaluation/                                         [Fase 2 -- Paso 10 COMPLETO]
  __init__.py                CONSTRUIDO
  reports.py                  CONSTRUIDO -- compare_baselines(history_repository,
                              dataset, fit_fn_1, predict_fn_1, fit_fn_2,
                              predict_fn_2, min_train_size=300, test_block_size=30)
                              -> BaselineComparisonReport. Un único recorrido de
                              walk_forward_splits (Paso 9) alimenta Baseline 0
                              (mercado, directo de BacktestRow.p_market_yes),
                              Baseline 1 (logreg) y Baseline 2 (Elo) sobre el
                              MISMO universo de test_rows. segment_by_edge (solo
                              baseline_1/baseline_2, reutiliza compute_edge_yes de
                              Paso 8 vía un PModelOutput mínimo) / segment_by_confidence
                              / segment_by_liquidity (ancho fijo, mismo esquema que
                              calibration_curve). Agnóstico al modelo -- no importa
                              mlb_baseline.py ni mlb_elo.py. Solo en memoria, sin
                              persistencia ni dependencias de visualización.

scripts/sync_tennis_results.py                          [Fase 2 -- Paso 11 NUEVO]  CLI manual, mismo patrón que sync_mlb_results.py
scripts/ (resto)                                        Sin cambios desde el Paso 6
```

Módulos ya cerrados **sin ningún cambio** en esta actualización,
verificado explícitamente antes del commit (`git diff --name-only HEAD`
vacío para todos): `src/models/base.py`, `src/models/schemas.py`,
`src/models/mlb_baseline.py`, `src/models/mlb_elo.py`,
`src/models/tennis_baseline.py`, `src/models/registry.py`,
`src/pricing/*`, `src/uncertainty/quality_score.py`, `src/backtesting/*`,
`src/evaluation/reports.py`, `src/signals/edge.py`,
`src/signals/expected_value.py`, `src/pipelines/*`, `src/features/*`,
`src/connectors/*`, `src/normalization/*`, y todos los módulos de Fase 1.
El Paso 12 **no modificó ningún archivo existente** — dos archivos nuevos
únicamente (`src/signals/signal_schema.py`,
`tests/unit/test_signal_schema.py`), confirmado con
`git status --porcelain` (solo `??`, cero `M`).

## 7. Árbol de directorios (delta desde la última actualización)

Nuevo en esta actualización:
```
src/signals/signal_schema.py             [NUEVO]
tests/unit/test_signal_schema.py         [NUEVO]
```
Ningún archivo existente modificado.

## 8. Responsabilidad de `src/features/tennis_features.py` + `src/models/tennis_baseline.py`

**`tennis_features.py`** — `compute_rest_days(match_start_time, prior_match_start_times, data_cutoff_timestamp)`: resta el `start_time` del último partido ANTERIOR conocido (filtrado por `< data_cutoff_timestamp`, nunca por el `start_time` del propio partido) del `start_time` del partido a predecir. `compute_tournament_round_context(tournament_round)`: passthrough directo de `competition.round.displayName` (ESPN), verificado real, nunca heurística de texto (prohibida por §16). Ambas son los dos únicos `compute_function_name` FULLY_SPECIFIED de tenis ya anclados en el registry desde el Paso 1 — verificado por test cruzado (`test_every_computable_tennis_feature_has_a_matching_function_in_this_module`). `TennisFeatureInputs`/`compute_tennis_features`/`persist_tennis_feature_snapshot`: mismo patrón exacto que `mlb_features.py` (Paso 2/5b) — nunca hace red ni consulta `HistoryRepository` directamente, recibe los datos ya obtenidos por el llamador.

**`tennis_baseline.py`** — mismo patrón estructural que `mlb_baseline.py` (dataset builder -> vectorización -> training -> inferencia), con dos diferencias deliberadas: **persistencia independiente** (`TennisTrainedArtifact`, JSON+joblib propios con prefijo `tennis_baseline_*`, nunca importa/modifica `registry.py`, que está acoplado a `MlbTrainedArtifact`) y **umbral propio** (`DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30`, heurística "10-20 obs/dimensión" aplicada a 2 features de tenis en vez de las ~26 de MLB, PROVISIONAL). `tournament_round_context` (vocabulario abierto) se codifica como bandera 0/1 por categoría **descubierta únicamente en el split de TRAIN** (nunca de validación, nunca una lista fija inventada) — una categoría no vista en entrenamiento produce una fila en ceros, nunca fabricada. `predict_tennis_baseline`/`predict_tennis_baseline_from_features` comparten un único núcleo de inferencia (mismo patrón que Paso 9), disponible desde ya por si un futuro paso reutiliza `src/backtesting/`/`src/evaluation/reports.py` sobre tenis (explícitamente diferido, Ambigüedad F).

**`tennis_results_sync.py`** — mismo patrón que `mlb_results_sync.py`; reutiliza `EspnTennisConnector.get_scoreboard`/`extract_matches` ya existentes (`competitors[].winner`, verificado real). A diferencia de MLB, no distingue POSTPONED/CANCELLED (sin verificar cómo ESPN Tennis los representa) — se cuentan honestamente como `not_yet_decided`.

**Extensión en `tennis_normalizer.py`/`tennis_pipeline.py`** — captura `competitor.id` (identidad estable, verificada real: el mismo jugador conserva el mismo id entre partidos distintos) y `competition.round.displayName` en `model_inputs.context`; wiring de `feature_snapshots` mediante `_fetch_tennis_feature_inputs`, que consulta `event_snapshots` ya persistidos (emparejando por `espn_id`, nunca por nombre de texto) — sin ninguna llamada de red adicional.

**Hallazgos empíricos clave** (verificados contra la API real de ESPN ANTES de diseñar, no asumidos): `competition.round.displayName` existe y es estable ("Qualifying 1st Round", "Qualifying Final", etc.); `competitor.id` es un identificador numérico estable entre partidos del mismo jugador; `competitors[].winner` está presente y correcto para partidos finalizados.

## 8b. Responsabilidad de `src/signals/signal_schema.py` (Paso 12)

Módulo de puros tipos, sin ninguna función. `Side(YES/NO)`: vocabulario nuevo y autocontenido. `SignalType(ENTER/WATCH/PASS)`: el vocabulario pedido literalmente por §12, sin ninguna función en todo el proyecto que lo calcule todavía. `SignalInputs`: `dataclass(frozen=True)`, representa los inputs de **un lado de un evento** (nunca ambos lados en el mismo objeto — mismo invariante "nunca cruzados" del Paso 8, aquí reforzado a nivel de tipo: `Side.YES` y `Side.NO` del mismo `event_id` son dos instancias independientes). Campos: `event_id`, `sport` (`Sport`, reutilizado de `models.schemas`), `side`, `model_status` (`ModelStatus`, reutilizado de `models.base`), `p_model`, `market_price`, `edge`, `ev_bruto`, `ev_neto`, `confidence`, `confidence_method` (todos `Optional`, nunca fabricados), `generated_at` (tz-aware obligatorio). `__post_init__` solo valida (tz-aware, rangos `[0,1]`) — la misma disciplina ya usada en `PModelOutput.__post_init__`, nunca una decisión de negocio. Ninguna función de clasificación vive en este archivo ni en ningún otro todavía — verificado por test dedicado (`test_module_defines_no_classification_function`).

**Acoplamiento deliberadamente mínimo** (Ambigüedad D, decisión D3): únicos dos imports externos, `ModelStatus` (`src.models.base`) y `Sport` (`src.models.schemas`) — los mismos dos enums estables sin lógica que ya reutilizan `edge.py`/`expected_value.py`/`evaluation/reports.py`. Nunca embebe `PModelOutput`/`QualityScoreOutput`/`NormalizedRecord` completos como campos — todos los valores derivados viajan como primitivos ya extraídos por el llamador, igual que ya hace `QualityScoreOutput` con sus propios campos.

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- **`rest_days` nunca usa datos posteriores a `data_cutoff_timestamp`** — verificado por test dedicado (`test_compute_rest_days_excludes_matches_not_yet_knowable_before_cutoff`), corte por instante de conocimiento, no por el `start_time` del propio partido.
- **Identidad de jugador por `espn_id`, nunca por nombre de texto** — en `rest_days`, en el wiring del pipeline, y en la sincronización de resultados.
- **`tournament_round_context` (categórico abierto) se descubre solo del split de TRAIN** — nunca de validación, nunca una lista fija inventada; una categoría desconocida en inferencia produce ceros, nunca se fabrica.
- **Persistencia de tenis totalmente independiente de `registry.py`** — verificado por test de coexistencia sin colisión en el mismo `DATA_MODELS_DIR`.
- `predict_tennis_baseline_from_features`/`predict_tennis_baseline` comparten una única implementación de inferencia — mismo principio que MLB (Paso 9).
- **`SignalInputs` es por lado, nunca por evento** — un `Side.YES` y un `Side.NO` del mismo `event_id` son siempre dos objetos independientes, nunca uno solo con ambos lados embebidos (Paso 12).
- **`SignalInputs` es inmutable (`frozen=True`) y no contiene ningún campo `signal_type`** — el vocabulario `SignalType` (ENTER/WATCH/PASS) vive separado; ninguna función de este proyecto lo calcula todavía (Paso 12).

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo: ninguna dependencia nueva añadida; el Paso 12 no modificó ningún módulo cerrado (dos archivos nuevos únicamente, ver §6/§7).

## 11. Decisiones arquitectónicas tomadas durante el Paso 12

- **`SignalInputs` por lado, nunca por evento** (Ambigüedad A, decisión A1) — mismo invariante "nunca cruzados" ya establecido en el Paso 8, ahora reforzado a nivel de tipo en vez de solo por convención de código.
- **`SignalType` separado de `SignalInputs`, sin campo `signal_type` en el contenedor de datos** (Ambigüedad B, decisión B2) — mismo patrón ya usado `PModelOutput`→`QualityScoreOutput` en los Pasos 5a/7 (un tipo nuevo separado en vez de mutar/dejar un campo `None` a la espera en el original).
- **`dataclass(frozen=True)`, no pydantic** (Ambigüedad C, decisión C2) — consistente con el patrón mayoritario de Fase 2 (`PModelOutput`, `QualityScoreOutput`), y la inmutabilidad refuerza al nivel del tipo la misma pureza que `edge.py`/`expected_value.py` ya declaran por escrito.
- **Acoplamiento mínimo: solo `ModelStatus`/`Sport`** (Ambigüedad D, decisión D3) — reutiliza únicamente dos enums estables sin lógica, ya usados por `edge.py`/`expected_value.py`/`evaluation/reports.py`; nunca embebe `PModelOutput`/`QualityScoreOutput`/`NormalizedRecord` completos.
- **Auditoría arquitectónica final de 6 propiedades antes de autorizar la implementación** (pedida explícitamente por el usuario, adicional a la metodología de 6 puntos ya estándar): aditividad total, ausencia de ciclo de dependencias, ausencia de acoplamiento nuevo, reutilizable por futuros motores de clasificación, `SignalInputs` = solo datos nunca comportamiento, lógica de clasificación fuera del archivo — las seis verificadas contra el código real (`grep`/`git diff`) antes de escribir código, no solo argumentadas en abstracto.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Paso 11 tuvo seis ambigüedades explícitas (A-F, ver historial previo de este documento). Paso 12 tuvo cuatro ambigüedades explícitas (A-D), resueltas con la misma metodología de 6 puntos (descripción/ventajas/desventajas/impacto en arquitectura/impacto en escalabilidad futura/recomendación final), pedida explícitamente por el usuario:
- **Ambigüedad A** (señal por lado o por evento): por lado (A1) — mismo invariante "nunca cruzados" del Paso 8, reforzado a nivel de tipo.
- **Ambigüedad B** (dónde vive `signal_type`): separado de `SignalInputs` (B2) — mismo patrón `PModelOutput`→`QualityScoreOutput`.
- **Ambigüedad C** (`dataclass`/`pydantic`): `dataclass(frozen=True)` (C2) — consistente con el patrón de Fase 2, refuerza pureza.
- **Ambigüedad D** (acoplamiento a `PModelOutput`/`QualityScoreOutput`/`NormalizedRecord`): mínimo, solo `ModelStatus`/`Sport` (D3) — mismo patrón ya usado por `evaluation/reports.py`.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 63)

59-63. (Paso 11, ver historial previo de este documento.)
64. Instrucción de iniciar la revisión contractual del Paso 12 (objetivos, alcance, arquitectura, riesgos, dependencias, módulos permitidos/prohibidos, ambigüedades, plan de pruebas), sin código, siguiendo el proceso institucional.
65. Aprobación general de la revisión contractual y del Design Proposal inicial (A1/B2/C2/D3), con instrucción explícita de preparar las cuatro recomendaciones con la metodología de 6 puntos completa (descripción/ventajas/desventajas/impacto arquitectura/impacto escalabilidad futura/recomendación final) antes de aprobar definitivamente, y de no implementar nada todavía.
66. Presentación de las cuatro recomendaciones (A1/B2/C2/D3) con el método de 6 puntos y del Design Proposal completo del Paso 12.
67. Instrucción de realizar una auditoría arquitectónica final de 6 propiedades (aditividad total, ausencia de ciclo de dependencias, ausencia de acoplamiento nuevo, reutilizable por futuros motores de clasificación, `SignalInputs` = solo datos, lógica de clasificación fuera del archivo) antes de autorizar la implementación.
68. Aprobación explícita de la implementación tras la auditoría satisfactoria, con instrucción de ejecutar los tests correspondientes, realizar la auditoría post-implementación y actualizar `CONTINUITY.md`.
69. Instrucción de seguir el proceso institucional antes de iniciar cualquier implementación nueva: confirmar repo limpio, confirmar commits del Paso 12, releer `CONTINUITY.md`, identificar el siguiente paso del plan, y elaborar el Design Proposal del "Paso 13" siguiendo la metodología institucional, sin escribir código hasta aprobación explícita.
70. Tras reportar que `PLAN_PHASE2.md` §12 termina en el Paso 12 (no existe un Paso 13 definido) y presentar la discrepancia del criterio de aceptación #12 (§14) — repository.py/connectors/mlb.py/tennis_normalizer.py con cambios aditivos autorizados pero no "cero cambios" literal — el usuario declaró oficialmente cerrada la Fase 2, con instrucción explícita de: (1) formalizar el cierre, (2) actualizar `PLAN_PHASE2.md` reflejando el estado final real y documentando la excepción, (3) verificar consistencia entre `CONTINUITY.md` y `PLAN_PHASE2.md`, (4) no iniciar ningún Paso 13 ni funcionalidad nueva, y (5) preparar un Informe Final de Cierre (objetivos, arquitectura final, componentes, cobertura de pruebas, riesgos, alcance excluido, recomendaciones para Fase 3) — sin implementar nada hasta una nueva decisión de arquitectura.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
498 passed, 1 warning in ~27s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente. 12 tests nuevos en esta actualización (486 → 498), todos en `tests/unit/test_signal_schema.py`: construcción válida, `SignalType`/`Side` con exactamente los valores esperados, YES/NO como objetos independientes para el mismo evento, todos los campos opcionales aceptando `None`, `generated_at` naive rechazado, cada campo `[0,1]` fuera de rango rechazado (parametrizado ×3), inmutabilidad (`FrozenInstanceError` al mutar), ausencia de campo `signal_type` en `SignalInputs`, y ausencia de cualquier función de clasificación propia en el módulo. Verificado desde estado limpio (`__pycache__` purgado) antes del commit y de nuevo post-commit.

## 15. Número total de tests existentes

**498** (verificado con la salida final de pytest tras purgar `__pycache__`). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado antes del commit (con caché de bytecode purgada) y de nuevo post-commit (`08daf26`). Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios — ninguna dependencia nueva en el Paso 12:
```
requests>=2.32,<3
pydantic>=2.11,<3
pytest>=8.4,<9
python-dotenv>=1.2,<2
scikit-learn>=1.3,<1.7
```

## 18. Restricciones del proyecto

Sin cambios respecto a la versión anterior.

## 19. Estado de `PLAN_PHASE2.md`

**Actualizado en el cierre formal de Fase 2 (commit `57768b4`).** El
texto de diseño original (secciones 1-17, Revisión 2) se conserva sin
reescribir, como registro histórico de lo aprobado antes de implementar.
Se añadió §18 ("Estado final de implementación — Cierre formal de Fase
2"): mapeo paso→commit de los 13 pasos, verificación de los 13 criterios
de §14 contra el código real, y la excepción documentada al criterio 12
(ver §0 de este documento). La línea final ya no dice "ESPERANDO
APROBACIÓN FINAL" — dice explícitamente **"FASE 2 CERRADA — IMPLEMENTADA,
AUDITADA Y APROBADA (2026-07-26)"**.

## 20. Qué pasos quedan pendientes

| Paso (numeración de `PLAN_PHASE2.md` §12) | Contenido | Estado |
|---|---|---|
| 5a | Infraestructura de modelo MLB | ✅ COMPLETO |
| 5b | `feature_snapshots`/`event_results` wiring + training pipeline real | ✅ COMPLETO |
| 6 | Elo simple MLB (Baseline 2) | ✅ COMPLETO |
| 7 | `src/uncertainty/quality_score.py` | ✅ COMPLETO |
| 8 | `src/signals/edge.py` + `expected_value.py` | ✅ COMPLETO |
| 9 | `src/backtesting/` | ✅ COMPLETO |
| 10 | `src/evaluation/reports.py` | ✅ COMPLETO |
| 11 | Tenis (`src/features/tennis_features.py` + `src/models/tennis_baseline.py`) | ✅ COMPLETO |
| 12 | `src/signals/signal_schema.py` | ✅ **COMPLETO** (este documento) |

## 21. Estado de la automatización (LaunchAgent) — sin cambios

- **DESCARGADO** (`launchctl bootout`), confirmado sin cargar en el cierre de esta actualización (`launchctl print` devuelve "Could not find service... in domain").
- Debe permanecer descargado **hasta finalizar la Fase 2 completa** (instrucción vigente, sin cambios).
- Para reactivarlo (NO ejecutar sin autorización explícita): `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.prediction-market-engine.run-e2e-historical.plist`
- Verificar estado: `launchctl print gui/$(id -u)/local.prediction-market-engine.run-e2e-historical`

## 22. Estado real de `data/engine.db` (verificado en el cierre de esta actualización)

```
event_snapshots     -> 93
feature_snapshots   -> 0
event_results       -> 0
normalized_records  -> 94
```
Sin cambios desde la última actualización (mismo `mtime`) — el Paso 12 no toca `data/engine.db` en absoluto: `SignalInputs` es un tipo puro en memoria, sus tests no abren ninguna base de datos ni fixture de repositorio.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- `DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30` es una heurística de ingeniería nueva, no calibrada — revisar cuando haya volumen real de tenis.
- `tennis_results_sync.py` no distingue POSTPONED/CANCELLED (a diferencia de MLB) — no verificado contra datos reales cómo ESPN Tennis los representa; se cuentan como `not_yet_decided` hasta que se verifique y, si aplica, se extienda.
- `_fetch_tennis_feature_inputs` hace un recorrido lineal sobre TODO `event_snapshots` por cada partido normalizado — misma deuda de escalabilidad ya documentada para `build_backtest_dataset`/`build_mlb_elo_game_sequence`, aceptable dado el volumen real actual.
- `src/backtesting/`/`src/evaluation/reports.py` nunca se ejecutaron sobre datos de tenis (Ambigüedad F, diferido a propósito) — agnósticos al modelo por diseño, no requieren cambios cuando se decida hacerlo.
- Mapeo participante↔YES de un contrato de Kalshi específico sigue sin resolver (Ambigüedad #2/Paso 4) — afecta también a tenis igual que a MLB.
- Doble bloqueo de tenis (SofaScore 403 + histórico propio bajo) sigue vigente — `model_status` de tenis previsiblemente permanecerá en `INSUFFICIENT_HISTORY` por mucho tiempo, resultado aceptado explícitamente por el plan (§6/§14).
- `signal_schema.py` (Paso 12) no ha sido ejercitado todavía por ningún pipeline real ni por ninguna función de clasificación — es deliberado (§16 sigue prohibiendo umbrales ENTER/WATCH/PASS calibrados sin nueva decisión explícita), no una omisión.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- **FASE 2 ESTÁ FORMALMENTE CERRADA (2026-07-26), Y VALIDADA INSTITUCIONALMENTE end-to-end sobre mercados reales (2026-07-26, ver §0.1).** Verifica tú mismo antes de asumir nada de este documento -- `git rev-parse HEAD` y `git status --short` (debe estar limpio). El objetivo de `PLAN_PHASE2.md` se considera cumplido; ver §0/§0.1 de este documento, `PLAN_PHASE2.md` §18, [`FASE2_CIERRE_FINAL.md`](FASE2_CIERRE_FINAL.md) (Informe Final de Cierre) y [`FASE2_VALIDACION_INSTITUCIONAL.md`](FASE2_VALIDACION_INSTITUCIONAL.md) (validación real + fix de aislamiento de tests aplicado).
- **`data/models/` está limpio y NO se regenera solo** -- verificado con 3 corridas independientes de la batería completa tras el fix de `eff754e` (§0.1). Si alguna vez vuelve a aparecer un artefacto sintético ahí, es una regresión real, no un comportamiento esperado.
- **No existe ningún "Paso 13" ni trabajo de Fase 3 autorizado.** El siguiente trabajo conceptual (lógica de clasificación de umbrales ENTER/WATCH/PASS sobre `SignalInputs`, reactivación del LaunchAgent, integración participante↔YES, configuración de `ODDS_API_KEY`, etc. -- ver recomendaciones en `FASE2_CIERRE_FINAL.md` §7) requiere una **nueva propuesta y aprobación explícita del usuario**, siguiendo el mismo proceso institucional (revisión contractual → ambigüedades con metodología de 6 puntos → Design Proposal → aprobación → implementación → tests → auditoría → commits separados). No inicies nada de eso sin esa aprobación nueva, aunque parezca una continuación natural.
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real (§22) -- tanto MLB como tenis seguirán en `MODEL_NOT_TRAINED`/`INSUFFICIENT_HISTORY` hasta que exista volumen real. Esto **no bloqueó** el cierre de Fase 2 -- `PLAN_PHASE2.md` §14 lo declara explícitamente aceptable.
- El LaunchAgent sigue DESCARGADO. El cierre de Fase 2 no lo reactiva automáticamente -- sigue requiriendo autorización explícita nueva y separada (es la recomendación #1 de `FASE2_CIERRE_FINAL.md` §7 para una futura Fase 3, no una acción ya aprobada).
- **Excepción documentada al criterio de aceptación #12** (`PLAN_PHASE2.md` §14): `repository.py`, `connectors/mlb.py` y `normalization/tennis_normalizer.py` tienen cambios aditivos reales respecto al baseline de Fase 1 (verificado con `git diff --stat`), cada uno autorizado individualmente en su paso correspondiente -- documentado explícitamente en `PLAN_PHASE2.md` §18.3, no oculto ni reescrito para "aparentar" cumplimiento literal.
- **`SignalInputs` es por lado, nunca por evento** (`Side.YES`/`Side.NO` del mismo `event_id` son objetos independientes) -- mismo invariante "nunca cruzados" del Paso 8, reforzado a nivel de tipo.
- **`SignalType` (ENTER/WATCH/PASS) vive separado de `SignalInputs`** -- ningún campo `signal_type` en el contenedor de datos, ninguna función en el proyecto lo calcula todavía. Un futuro motor de clasificación define su propio tipo de salida encima, sin modificar `signal_schema.py`.
- **`tennis_baseline.py` tiene persistencia totalmente independiente de `registry.py`** (prefijo de archivo `tennis_baseline_*`) — nunca reutilizar/generalizar `registry.py` para tenis sin una nueva decisión explícita.
- **Identidad de jugador de tenis = `competitor.id` de ESPN** (`model_inputs.context.participant_{a,b}_espn_id`), nunca nombre de texto — verificado estable contra la API real.
- **`round.displayName`** (ESPN) es la fuente directa de `tournament_round_context` — verificado real, no bloqueado por SofaScore.
- Patrón de trabajo ya validado en ocho pasos consecutivos de Fase 2 (5b, 7, 6, 8, 9, 10, 11, 12) y en el propio cierre de fase: revisión contractual → (si hay ambigüedades) resolución punto por punto con metodología de 6 puntos → Design Proposal → aprobación explícita → (cuando aplique) auditoría de propiedades concretas antes de autorizar → implementación → tests → auditoría → commit separado de código/contenido → commit separado de `CONTINUITY.md`. Sigue este mismo patrón para cualquier trabajo futuro, incluida una eventual Fase 3.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
