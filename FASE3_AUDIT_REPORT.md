# Informe de Auditoría — Plan Maestro Fase 3

Fecha: 2026-07-30. Alcance: auditoría contractual y arquitectónica
completa de los 21 principios y 9 correcciones (A-I) propuestos para
Fase 3, contra el estado real del repositorio en `v2.0-baseline`
(commit `c01032d3`, idéntico a `HEAD` de `phase-2-dev` en el momento de
esta auditoría). Ningún cambio a `src/` se realizó durante esta
auditoría; ningún modelo se entrenó; `v2.0-baseline` no se movió ni se
recreó.

---

## 1. Executive Summary

El conjunto de 21 principios + 9 correcciones propuesto para Fase 3 es
arquitectónicamente sólido y compatible con la arquitectura real de Fase
2 — no se encontró ninguna contradicción irresoluble entre lo propuesto y
el código existente. Se encontraron y resolvieron 3 huecos de contrato
concretos (§6), se identificó y formalizó 1 riesgo de dependencia
temporal crítico que el plan original no hacía explícito (§5), y se
determinó que **la especificación completa puede producirse ahora**,
pero **la implementación real de las etapas que requieren histórico
(calibración entrenada, backtesting real, shadow mode real) queda
bloqueada por decisiones pendientes que preceden a Fase 3 y no fueron
resueltas por este cierre de Fase 2** (`FASE2_CIERRE_FINAL.md` §7,
puntos 1 y 2). Conclusión: **CONDITIONAL GO** — ver §15.

---

## 2. Repository Findings

- `git tag -l -n99 v2.0-baseline` confirma cierre formal, y
  `git rev-parse HEAD v2.0-baseline` + `git diff --stat v2.0-baseline HEAD`
  confirman que `HEAD` de `phase-2-dev` está exactamente en ese commit
  (mismo árbol, tag anotado apuntando al mismo commit) — la afirmación
  "repositorio listo para Fase 3 en este commit exacto" del mensaje del
  tag se verificó directamente, no se asumió.
- `pytest -q` sobre el repositorio completo: **498 passed, 0 failed**
  (mismo número que documenta `CONTINUITY.md`/`FASE2_CIERRE_FINAL.md`).
- `data/models/` contiene únicamente `.gitkeep` — confirma que el fix de
  aislamiento de tests (commit `eff754e`) sigue efectivo.
- `data/engine.db`, `data/raw/`, `data/normalized/` existen con datos de
  captura real (múltiples snapshots MLB/tenis/Kalshi) — no se leyó su
  contenido más allá de confirmar su existencia (fuera de alcance:
  ninguna tarea de esta auditoría requiere inspeccionar filas
  individuales de producción).
- No existe ningún documento previo llamado `PLAN_MASTER_FASE3.md` ni
  equivalente en el repositorio — el "Plan Maestro" auditado es el
  conjunto de principios entregado como parte de esta tarea, no un
  documento preexistente. Se documenta explícitamente para que quede
  claro que esta auditoría es la primera formalización, no una revisión
  de un plan ya escrito.
- `requirements.txt`: 5 dependencias (`requests`, `pydantic`, `pytest`,
  `python-dotenv`, `scikit-learn`) — suficientes para toda la
  especificación de Fase 3 (ver §7, "sin dependencias nuevas").

---

## 3. Architecture Findings

- 48 archivos Python en `src/`, organizados en 12 paquetes
  (`connectors`, `normalization`, `matching`, `quality`, `models`,
  `pricing`, `uncertainty`, `signals`, `storage`, `backtesting`,
  `evaluation`, `features`) — arquitectura por capas de responsabilidad
  única, consistente en todo Fase 1/2, sin acoplamiento circular
  detectado.
- `src/signals/signal_schema.py` (Paso 12 de Fase 2) fue diseñado
  explícitamente como el punto de entrada para una futura lógica de
  clasificación ("esa lógica de clasificación... queda fuera de este
  archivo, en un módulo futuro separado") — el Policy Engine propuesto
  en `POLICY_ENGINE_SPEC.md` ocupa exactamente ese hueco, confirmando que
  la arquitectura de Fase 2 fue diseñada anticipando esta continuación.
- `src/signals/expected_value.py` deja `compute_ev_*_neto` como
  `NotImplementedError` explícito, documentado como decisión deliberada
  ("la fórmula exacta... NO está especificada por el plan y no se
  inventa aquí") — el `PayoffModel` propuesto (Corrección C) es la
  resolución correcta de ese hueco, no una desviación.
- Ningún módulo de Fase 3 propuesto requiere modificar
  `src/connectors/`, `src/normalization/`, `src/matching/`,
  `src/quality/` (Fase 1) — verificado contra el flujo de datos completo
  en `ARCHITECTURE_FASE3.md` §2.

---

## 4. Statistical and Modeling Risks

- **Calibración sin histórico**: el Principio 12 exige conservar
  `p_model_raw`/`p_model_calibrated`, pero ningún calibrador puede
  entrenarse honestamente con `feature_snapshots=0`/`event_results=0`.
  Riesgo mitigado por diseño: `CalibrationOutput` con
  `calibration_version=None` es un estado válido y explícito (§Model
  Pipeline Spec §3), no un placeholder disfrazado.
- **`HEURISTIC_V1` no calibrado usado como insumo de
  `ConfidenceProfile`**: Fase 2 ya documenta esto explícitamente
  (`quality_score.py`: "útil para ordenar/filtrar y auditar, NUNCA se
  presenta ni se documenta como una probabilidad calibrada"). Riesgo: que
  `ConfidenceProfile.data_quality`/`market_quality` (derivados de
  `HEURISTIC_V1`) se interpreten como más confiables de lo que son.
  Mitigación adoptada: `ConfidenceProfile.quality_score_component_ref`
  (`CONTRACTS_FASE3.md` §4) obliga a trazar de qué `confidence_config_version`
  proviene, y `EXPLAINABILITY` (§2.1) exige `disclaimers` cuando
  `calibration_version is None`.
- **Umbrales de liquidez/staleness sin respaldo empírico**: Fase 2 ya
  documenta `_MARKET_LIQUIDITY_TARGET=50000.0` como "el umbral con menos
  respaldo empírico de los 7" (solo 3/93 snapshots con volumen real
  poblado al momento de elegirlo). El Policy Engine de Fase 3 reutiliza
  esta misma señal (vía `ConfidenceProfile`) sin corregir el umbral —
  riesgo heredado, no nuevo, documentado aquí para que no se pierda al
  cruzar de Fase 2 a Fase 3.
- **Riesgo de sobreajuste de `PolicyManifest` a un manifiesto único
  "MLB" con volumen pequeño**: mitigado por el requisito de Policy
  Validation §5.4-5 (`POLICY_ENGINE_SPEC.md`) — ningún manifiesto se
  promueve sin comparación de regresión.

---

## 5. Temporal Leakage Risks

- **Riesgo mayor identificado en esta auditoría** (no estaba en la lista
  original de 21 principios de forma explícita, aunque el Principio 18 lo
  cubre en general): el plan de evaluación (Principio 15, Corrección F)
  presupone histórico suficiente para producir Brier/ECE/CLV/ROI con
  significancia estadística real. Sin ese histórico
  (`feature_snapshots=0` verificado en §2), cualquier `EvaluationRecord`
  producido sería, en el mejor caso, ruido de muestra pequeña, y en el
  peor caso, una falsa señal de que el sistema "funciona" antes de tener
  evidencia real. Se formalizó como GATE-0
  (`SHADOW_MODE_AND_PROMOTION_GATES.md` §2) — bloqueando estructuralmente
  la promoción de cualquier manifiesto hasta cumplirse.
- **Fuga vía `event_results` no filtrado**: mitigado — Fase 2 ya separa
  `event_results` de `event_snapshots` sin join automático
  (`history_repository.py`, diseño explícito). El nuevo Hard Block
  `known_result` (`POLICY_ENGINE_SPEC.md` §2.1) formaliza esta protección
  también a nivel de Policy Engine, no solo de dataset builder.
- **Fuga vía missed-opportunity analysis retroalimentando la decisión
  original**: riesgo nuevo, propio de Fase 3 (no existía en Fase 2 porque
  no había evaluación retroactiva). Mitigado explícitamente en
  `EVALUATION_LEARNING_SPEC.md` §4: "estrictamente post-hoc, nunca usado
  para re-decidir la señal original".

---

## 6. Contract Gaps

1. **Colisión de nombre `ModelOutput`** (`src/models/schemas.py` ya
   tiene una clase vacía con ese nombre) — resuelto por composición
   `PModelOutput + CalibrationOutput`, sin tocar `schemas.py`
   (`PLAN_MASTER_FASE3.md` §5.1).
2. **Ambigüedad #2 de Fase 2 (participante↔YES) sin categoría en el
   catálogo de Hard Rules propuesto originalmente** — resuelto añadiendo
   `unresolved_side_mapping` a `HARD_HOLD_WATCH`
   (`PLAN_MASTER_FASE3.md` §5.2, `POLICY_ENGINE_SPEC.md` §2.2).
3. **`selection_id` no tiene definición de dominio** (Kalshi no expone un
   id de selección separado) — resuelto:
   `selection_id = f"{market_id}:{side.value}"`, determinístico
   (`PLAN_MASTER_FASE3.md` §5.3).
4. **`feature_set_version` (Fase 2) vs `feature_schema_version`
   (solicitado para Fase 3)** — resuelto como alias del mismo valor, no
   un campo nuevo paralelo (`TEMPORAL_REPRODUCIBILITY_SPEC.md` §5).
5. **`src/models/registry.py` hardcodeado a MLB** — no es un gap de
   contrato de datos, pero es un gap de extensibilidad real que
   bloquearía Principio 16 si no se generaliza — resuelto como extensión
   aditiva (`PLAN_MASTER_FASE3.md` §3.2, Paso F3-9).

---

## 7. Policy Engine Risks

- **Riesgo de que Soft Score compense un mínimo crítico por error de
  implementación** (no de diseño): mitigado exigiendo que la invariante
  se verifique a nivel de contrato (`PolicyDecision`, `CONTRACTS_FASE3.md`
  §11), no solo como convención de código en `soft_score.py`.
- **Riesgo de que un `PolicyManifest` mal formado se cargue en
  producción**: mitigado por Policy Validation obligatoria antes de
  cualquier uso (`POLICY_ENGINE_SPEC.md` §5), incluida validación
  cross-field contra el catálogo cerrado de `rule_id`/`component_name`.
- **Riesgo de "bloqueo permanente disfrazado de temporal"**: el Hard Hold
  `unresolved_side_mapping` nunca se resuelve automáticamente — es
  responsabilidad explícita de DECISIÓN PENDIENTE D-2. Riesgo aceptado y
  documentado, no oculto: mientras D-2 no se resuelva, el sistema no
  puede producir un `ENTER` real, lo cual es la postura correcta dado el
  Principio 2 (prioridad conservadora), no un defecto del diseño.

---

## 8. Evaluation Risks

- Ver §5 (fuga temporal) y §4 (riesgo estadístico) — ambos aplican
  directamente a la Evaluation & Learning Framework.
- **Riesgo de confundir "significancia estadística" con "volumen
  disponible"**: mitigado exigiendo `sample_size` y, cuando exista
  evidencia suficiente, intervalos de confianza en todo `EvaluationRecord`
  (`CONTRACTS_FASE3.md` §14) — nunca un punto estimado sin su incertidumbre
  asociada.
- **Riesgo de doble conteo entre `decision_performance` y
  `financial_performance`**: mitigado por la distinción obligatoria de
  las 5 preguntas separadas (`EVALUATION_LEARNING_SPEC.md` §2).

---

## 9. Proposed Corrections (resumen, detalle en `PLAN_MASTER_FASE3.md`)

1. Formalizar GATE-0 como prerrequisito de datos antes de Historical
   Backtesting/Shadow Mode (nuevo, no estaba en el plan original).
2. Añadir `unresolved_side_mapping` al catálogo de Hard Hold Rules.
3. Resolver la colisión `ModelOutput` por composición, no por
   renombrado de la clase existente.
4. Definir `selection_id` determinísticamente.
5. Tratar `ev_neto_strength` como mínimo crítico del Soft Score —
   consecuencia directa de Corrección C aplicada con rigor: mientras
   `net_ev_status=UNKNOWN` sea universal, ningún ENTER real es posible.
6. Generalizar `models/registry.py` de forma aditiva, sin migrar el
   código MLB existente.

---

## 10. Accepted Recommendations

Ver `IMPLEMENTATION_ROADMAP_FASE3.md`, columna **REQUIRED FOR PHASE 3** —
los 9 pasos F3-0 a F3-9 (excepto lo marcado como posterior), representan
la totalidad de la arquitectura, contratos y Policy Engine, construibles
y probables ahora, sin histórico real.

## 11. Deferred Recommendations

Ver `IMPLEMENTATION_ROADMAP_FASE3.md`, columna **RECOMMENDED LATER**:
entrenar un calibrador real, historical backtesting/shadow/paper tracking
reales, resolver el Market Adapter real, incorporar costos reales al
Payoff Model, recalibrar `HEURISTIC_V1`/umbrales con evidencia real. Todas
dependen de D-1/D-2/D-3 (§13).

## 12. Rejected Recommendations

- Cualquier forma de ejecución automática o `src/risk/` — rechazado, no
  diferido (Principio 21 es una restricción dura del proyecto, no una
  fase futura implícita).
- Introducir una librería de validación nueva (`pandera`/`jsonschema`)
  — rechazado por falta de necesidad no cubierta por `pydantic`
  (`extra="forbid"`) ya en uso.
- Migrar `models/registry.py` a ser exclusivamente genérico eliminando la
  función MLB-específica — rechazado por prematuro, sin un segundo
  consumidor real todavía.

---

## 13. Decisiones Pendientes (no resueltas por esta auditoría)

| Cod. | Decisión | Bloquea |
|---|---|---|
| D-1 | Reactivar LaunchAgent de captura histórica | Historical backtesting real, Shadow Mode real, calibración real, recalibración de `HEURISTIC_V1`/umbrales |
| D-2 | Resolver mapeo participante↔YES de un contrato Kalshi específico | `ENTER` real (el Hard Hold `unresolved_side_mapping` permanece activo indefinidamente sin esto) |
| D-3 | Fórmula de incorporación de `exchange_fee`/spread/slippage reales | `net_ev_status=COMPUTED` en producción (el mínimo crítico `ev_neto_strength` permanece imposible de cumplir sin esto) |

Ninguna de las tres se resuelve, asume, ni se decide unilateralmente en
esta auditoría — quedan explícitamente abiertas, tal como exige la
restricción "no declares GO si existen decisiones contractuales sin
resolver" (interpretada aquí como: la especificación arquitectónica
completa sí puede declararse GO; la puesta en producción de las etapas
que dependen de D-1/D-2/D-3 no puede).

---

## 14. Final Architecture

Ver [`ARCHITECTURE_FASE3.md`](ARCHITECTURE_FASE3.md) — árbol modular
completo, flujo de datos de una evaluación de oportunidad de extremo a
extremo, y reglas de dependencia entre módulos nuevos (ninguno importa
desde `explainability/`/`opportunity/`, que son terminales del grafo).

---

## 15. Implementation Readiness Assessment — Conclusión

**CONDITIONAL GO.**

- **GO** para: construir la especificación completa de contratos,
  arquitectura, Policy Engine, Payoff Model, Calibration Layer (sin
  entrenar), Evidence/Explainability Engine, Opportunity Lifecycle, y el
  andamiaje del Evaluation & Learning Framework — todo probable con
  fixtures/unit/contract tests, sin dependencia de histórico real, sin
  tocar `src/` de Fase 2 salvo las 2 extensiones aditivas documentadas y
  con reversibilidad completa paso a paso (`IMPLEMENTATION_ROADMAP_FASE3.md`).
- **NO GO todavía** para: cualquier forma de calibración real, historical
  backtesting real, shadow mode real, paper tracking real, o promoción de
  un `PolicyManifest` a `promoted_at != None` — bloqueado
  estructuralmente por GATE-0 y por las Decisiones Pendientes D-1/D-2/D-3
  (§13), ninguna de las cuales es responsabilidad de esta auditoría
  resolver.
- Esta conclusión es consistente con, y no contradice,
  `FASE2_CIERRE_FINAL.md §7` — de hecho la refuerza formalmente: los
  puntos 1-3 de esa sección (reactivar captura, resolver mapeo
  participante↔YES, configurar `ODDS_API_KEY`) son literalmente D-1, D-2,
  y un prerrequisito de D-3 documentados aquí con el mismo orden de
  dependencia.

No se declara GO pleno porque tres decisiones contractuales reales
permanecen sin resolver (§13), tal como exige la restricción del alcance
de esta auditoría. No se declara NO-GO porque no existe ninguna
contradicción arquitectónica ni de datos que impida construir y probar la
especificación completa ahora mismo.
