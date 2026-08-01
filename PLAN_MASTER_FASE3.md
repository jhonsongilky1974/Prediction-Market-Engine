# Plan Maestro — Fase 3: Motor de Decisión (Policy Engine + Evaluación)

Estado: **PROPUESTA AUDITADA, CORREGIDA Y CONSOLIDADA — NO IMPLEMENTADA.**
Generado: 2026-07-30, por auditoría contractual y arquitectónica completa
contra el estado real del repositorio en el commit `v2.0-baseline`
(`c01032d3`, idéntico a `HEAD` en `phase-2-dev`, 498 tests en verde,
`data/models/` limpio).

Este documento consolida, corrige y versiona los 21 principios y las 9
correcciones contractuales (A-I) propuestos para Fase 3, después de
auditarlos contra la arquitectura real de Fase 2 (no contra una
arquitectura hipotética). Ningún principio aprobado se eliminó sin
documentar problema/alternativa/razón/impacto/riesgo — ver §3. El detalle
narrativo de la auditoría completa vive en
[`FASE3_AUDIT_REPORT.md`](FASE3_AUDIT_REPORT.md); este documento es la
especificación resultante, no el informe de auditoría.

**Fase 3 sigue sin implementarse.** Este documento, junto con los demás
listados en §7, es la especificación lista para implementación
institucional — no la implementación en sí. Ver
[`IMPLEMENTATION_ROADMAP_FASE3.md`](IMPLEMENTATION_ROADMAP_FASE3.md) para
los pasos concretos, reversibles y auditables.

---

## 0. Decisión de alcance encontrada durante la auditoría (léase primero)

`FASE2_CIERRE_FINAL.md §7` ya documentaba, con aprobación implícita del
cierre de Fase 2, un orden de dependencia para cualquier trabajo futuro:

1. Reactivar captura histórica real (hoy `feature_snapshots=0`,
   `event_results=0` — el LaunchAgent permanece descargado a propósito).
2. Resolver el mapeo participante↔YES de un contrato Kalshi específico
   (Ambigüedad #2, abierta desde el Paso 4 de Fase 2).
3. Configurar `ODDS_API_KEY`.
4. **Solo entonces**: diseñar la lógica de clasificación ENTER/WATCH/PASS.

Los 21 principios de Fase 3 solicitados en esta auditoría (§1) especifican
un Policy Engine, un Model Pipeline con calibración, y un Evaluation &
Learning Framework con métricas que requieren histórico y modelos
entrenados reales (Brier, ECE, CLV, ROI). **Esa dependencia no desaparece
por especificar la arquitectura.** La resolución adoptada en este plan
(no una desviación de lo aprobado, sino la forma correcta de secuenciar
ambos conjuntos de requisitos) es:

- **Se puede y se debe** diseñar, construir y probar en Fase 3 toda la
  arquitectura, los contratos, el Policy Engine, el Payoff Model y el
  Evaluation Framework **con datos sintéticos/fixtures controlados**
  (unit tests, contract tests, property-based tests) — esto no depende de
  histórico real y no viola ningún principio del cierre de Fase 2.
- **No se puede** completar Historical Backtesting real, Shadow Mode
  real, ni calibración real de pesos/umbrales hasta que exista volumen
  real de `feature_snapshots`/`event_results`. Este plan trata esas
  etapas como **bloqueadas por datos**, con un gate explícito (ver
  [`SHADOW_MODE_AND_PROMOTION_GATES.md`](SHADOW_MODE_AND_PROMOTION_GATES.md)
  §2), no como pasos que se puedan "simular" para declarar Fase 3
  completa.
- La reactivación del LaunchAgent de captura histórica y la resolución
  del mapeo participante↔YES **no son parte del alcance de Fase 3 tal
  como fue solicitada** (construir el Policy Engine/Evaluation
  Framework) — son prerrequisitos operativos externos, cada uno
  requiere su propia decisión explícita del usuario. Se documentan como
  **DECISIÓN PENDIENTE D-1 y D-2** en §8, no se asume su resolución.

Esta es la corrección más importante que introduce esta auditoría: sin
ella, "Fase 3 completa" se declararía sobre una arquitectura que nunca
podría ejecutarse con datos reales, ocultando el problema real detrás de
código que pasa tests con fixtures. Ver `FASE3_AUDIT_REPORT.md` §5
("Riesgos Estadísticos y de Modelado") para el desarrollo completo.

---

## 1. Los 21 principios aprobados, tal como se corrigen aquí

Cada principio se lista con su estado tras la auditoría. "Sin cambios" =
aprobado literalmente. "Precisado" = mismo principio, redacción o alcance
aclarado sin cambiar su intención. Ningún principio fue rechazado.

| # | Principio | Estado tras auditoría | Detalle |
|---|---|---|---|
| 1 | Núcleo común de decisión con políticas específicas por deporte | Sin cambios | Ver `POLICY_ENGINE_SPEC.md` §1 |
| 2 | Señales ENTER/WATCH/PASS, prioridad conservadora | Sin cambios | `SignalType` ya existe (`src/signals/signal_schema.py`, Fase 2) — se reutiliza, no se recrea |
| 3 | Decisión basada en EDGE, EV neto, confianza, elegibilidad | Precisado | EV neto hoy no existe (`compute_ev_*_neto` lanza `NotImplementedError` deliberado en Fase 2) — depende del Payoff Model nuevo (Corrección C) |
| 4 | Confianza en 4 dimensiones (Data Quality / Model Reliability / Market Quality / Operational Safety) | Precisado | Reestructuración aditiva sobre `QualityScoreOutput` (Fase 2, `HEURISTIC_V1`), no un reemplazo — ver §4 y `CONTRACTS_FASE3.md` (`ConfidenceProfile`) |
| 5 | Analysis Health Score informativo, sin doble ponderación en el Policy Engine | Sin cambios | Invariante reforzado como regla de contrato en `CONTRACTS_FASE3.md` (`AnalysisHealth`) |
| 6 | Explainability Engine separado del Evidence Engine | Sin cambios | Ver `EVIDENCE_EXPLAINABILITY_SPEC.md` |
| 7 | Políticas configurables, versionadas, separadas de los modelos | Sin cambios | Ver `POLICY_ENGINE_SPEC.md` §5 (`PolicyManifest`) |
| 8 | Policy Engine híbrido: Hard Block → PASS, Hard Hold → WATCH, Soft Rules/score solo si no hay bloqueos | Precisado | Separación exacta Block/Hold formalizada en Corrección A — ver §4 |
| 9 | Soft Score no compensa componentes críticos; ENTER exige score global Y mínimos individuales | Sin cambios | Ver `POLICY_ENGINE_SPEC.md` §3 |
| 10 | Opportunity Lifecycle con identidad estable y evaluaciones inmutables | Sin cambios | Ver `CONTRACTS_FASE3.md` (`Opportunity`, `OpportunityEvaluation`) — mismo patrón append-only ya validado en `HistoryRepository` (Fase 2) |
| 11 | Arquitectura jerárquica de P_model (Sport Adapter → Market Adapter → Feature Builder → Probabilistic Model → Calibration Layer) | Sin cambios | Ver `MODEL_PIPELINE_SPEC.md` |
| 12 | Conservar p_model_raw, p_model_calibrated, model_version, calibration_version | Precisado | Colisión de nombre resuelta — ver §5, Hallazgo de Contrato #1 |
| 13 | Evidence Engine: hechos estructurados a favor/en contra | Sin cambios | Ver `EVIDENCE_EXPLAINABILITY_SPEC.md` §1 |
| 14 | Explainability Engine: decisiones/razones/evidencia → explicación auditable | Sin cambios | Ver `EVIDENCE_EXPLAINABILITY_SPEC.md` §2 |
| 15 | Evaluation & Learning Framework, 5 dimensiones | Precisado | Requiere histórico real para producir valores no triviales — ver §0 y `EVALUATION_LEARNING_SPEC.md` |
| 16 | Arquitectura extensible por interfaces/contratos | Sin cambios | Mismo patrón ya usado en Fase 2 (`ModelStatus`/`PModelOutput` como contrato agnóstico de deporte/algoritmo) |
| 17 | Contract & Invariant Framework | Precisado | Se construye sobre `pydantic.BaseModel(extra="forbid")` (ya usado en `src/models/schemas.py`, Fase 2) en vez de introducir una librería nueva — ver Corrección de dependencias en §6 |
| 18 | Temporal Integrity & Reproducibility | Sin cambios | Ver `TEMPORAL_REPRODUCIBILITY_SPEC.md` |
| 19 | Shadow Mode y Promotion Gates | Precisado | Gate de datos añadido como prerrequisito de entrada — ver §0 y `SHADOW_MODE_AND_PROMOTION_GATES.md` |
| 20 | Reliability, Observability, Fail-Safe Behavior | Sin cambios | Fail-safe = `PASS/INSUFFICIENT_EVIDENCE` ante cualquier excepción no controlada, nunca una señal fabricada (mismo principio ya vigente en toda Fase 2: "MISSING nunca se convierte en 0") |
| 21 | Sin ejecución automática ni gestión de banca en esta fase | Sin cambios | Reafirmado como restricción dura — ver §6 |

---

## 2. Correcciones contractuales obligatorias (A-I), estado final

| Cod. | Corrección | Estado | Dónde se especifica |
|---|---|---|---|
| A | Separar `HARD_BLOCK_PASS` vs `HARD_HOLD_WATCH` | Aceptada, + 1 categoría añadida | `POLICY_ENGINE_SPEC.md` §2 — se añade `unresolved_side_mapping` a `HARD_HOLD_WATCH` (ver Hallazgo de Contrato #2, §5) |
| B | `operational_risk`/`operational_safety`, misma dirección (100=mejor) en todos los componentes de score | Aceptada | `CONTRACTS_FASE3.md` (`ConfidenceProfile`), `POLICY_ENGINE_SPEC.md` §3.1 |
| C | PayoffModel por plataforma/contrato, `net_ev_status=UNKNOWN` si no hay evidencia de costos | Aceptada | `CONTRACTS_FASE3.md` (`PayoffEstimate`) — sustituye el `NotImplementedError` deliberado de `compute_ev_*_neto` (Fase 2) por una resolución explícita, sin modificar ese archivo (ver §4) |
| D | Integridad temporal completa por señal | Aceptada | `TEMPORAL_REPRODUCIBILITY_SPEC.md` |
| E | Opportunity Identity | Aceptada | `CONTRACTS_FASE3.md` (`Opportunity`) — `selection_id` se define como `f"{market_id}:{side.value}"` (decisión nueva, ver Hallazgo de Contrato #3, §5) |
| F | Evaluación multi-dimensión | Aceptada | `EVALUATION_LEARNING_SPEC.md` |
| G | Safe Abstention con `disposition` estructurada | Aceptada | `CONTRACTS_FASE3.md` (`PolicyDecision.disposition`) |
| H | Policy Validation (schema/rango/consistencia/regresión/histórico/promoción) | Aceptada | `POLICY_ENGINE_SPEC.md` §5 |
| I | Release Path sin ejecución automática | Aceptada | `SHADOW_MODE_AND_PROMOTION_GATES.md` |

---

## 3. Matriz REUTILIZAR / EXTENDER / CREAR / DEPRECAR / FUERA DE ALCANCE

Base: inventario real de `src/` en `v2.0-baseline` (48 módulos Python,
498 tests). Ninguna fila de esta matriz fue asumida — cada módulo listado
fue leído directamente.

### 3.1 REUTILIZAR (sin cambios, se consumen tal cual)

| Módulo Fase 2 | Rol en Fase 3 |
|---|---|
| `src/models/schemas.py` (`NormalizedRecord`, `Sport`, `EventStatus`, `SourceStatus`, `MatchMethod`, `MarketData`, `DataQuality`, `BookmakerConsensus`, `ModelInputs`, `TennisVariables`) | Entrada única de todo el pipeline de Fase 3. `NormalizedRecord.model_output` (el campo `ModelOutput` embebido) permanece **vestigial, siempre `None`, nunca poblado** — ver Hallazgo de Contrato #1 |
| `src/models/base.py` (`ModelStatus`, `PModelOutput`) | Contrato de salida del modelo, `p_model_raw` = `PModelOutput.p_model_yes`. Se compone, no se modifica — ver §4 |
| `src/signals/signal_schema.py` (`Side`, `SignalType`, `SignalInputs`) | `SignalInputs` pasa a ser el input directo del Policy Engine — es exactamente el contrato que Fase 2 dejó preparado para esto (`PLAN_PHASE2.md §12`) |
| `src/signals/edge.py`, `src/signals/expected_value.py` (funciones `*_bruto`) | Fuente de `edge`/`ev_bruto` en `SignalInputs`. Las funciones `*_neto` (que hoy lanzan `NotImplementedError`) se reemplazan como **punto de entrada** por el nuevo `PayoffModel` (Corrección C) — el archivo no se edita, el nuevo cálculo vive en `src/payoff/` |
| `src/pricing/market_pricing.py`, `odds_consensus.py`, `no_vig.py` | Sin cambios, fuente de `market_price`/consenso |
| `src/uncertainty/quality_score.py` (`HEURISTIC_V1`) | Se reutiliza como **uno de los insumos** de la dimensión `Data Quality`/`Market Quality` de `ConfidenceProfile` (Principio 4) — no se reemplaza ni se renombra |
| `src/quality/completeness.py` | Insumo de la dimensión Data Quality |
| `src/storage/history_repository.py` (`event_snapshots`, `feature_snapshots`, `event_results`, triggers append-only) | Fuente de datos para backtesting/evaluación. Patrón (triggers append-only, INSERT-only, `db_path` inyectable) se replica en los repositorios nuevos, sin tocar este archivo |
| `src/storage/repository.py` | Sin cambios |
| `src/backtesting/dataset.py`, `splitter.py` | Reutilizados tal cual por el Evaluation Framework nuevo |
| `src/backtesting/metrics.py` | Se extiende de forma aditiva (nuevas funciones puras, mismo estilo `(y_true, y_pred) -> Optional[metric]`) — ver §4 |
| `src/evaluation/reports.py` | Reutilizado como generador de Model Performance (una de las 5 dimensiones) |
| `src/matching/event_matcher.py`, `market_matcher.py` | Fuente de `event_id`/`market_id` para `Opportunity` |
| `src/connectors/*`, `src/normalization/*` | Sin relación directa, sin cambios |
| `config/settings.py` (paths, `HttpPolicy`) | Se añaden constantes de ruta nuevas (aditivo, ver §4), sin tocar las existentes |

### 3.2 EXTENDER (modificación aditiva a un módulo existente)

| Módulo | Extensión propuesta | Riesgo de romper Fase 2 | Estrategia de compatibilidad |
|---|---|---|---|
| `src/backtesting/metrics.py` | Añadir `ece()`, `clv()`, `roi_teorico()`, `profit_factor()`, `drawdown()` — funciones puras nuevas, mismo estilo que las 4 existentes | Bajo — solo aditivo | Ningún test ni firma existente se modifica; nuevas funciones, nuevos tests |
| `src/models/registry.py` | Generalizar de MLB-únicamente (`glob("mlb_baseline_*.metadata.json")` hardcodeado) a multi-deporte + artefactos de calibración | Medio — la función `load_latest_mlb_artifact` es usada por `scripts/train_mlb_model.py` y tests existentes | No se renombra ni se elimina `load_latest_mlb_artifact`; se añade una función nueva `load_latest_artifact(sport, models_dir)` en paralelo. Migración real de `mlb_baseline.py` a la función genérica queda fuera de alcance de Fase 3 (ver §6) — ambas coexisten |
| `config/settings.py` | Añadir `DATA_POLICY_DIR`, `DATA_OPPORTUNITIES_DIR` (o tabla en `engine.db`, ver `ARCHITECTURE_FASE3.md` §3) | Bajo — mismo patrón de las constantes existentes | Aditivo al final del archivo, mismo estilo (`_dir.mkdir(...)`) |

### 3.3 CREAR (módulos nuevos, ninguno existe hoy)

| Módulo nuevo | Contenido | Depende de |
|---|---|---|
| `src/policy/` | `hard_rules.py`, `soft_score.py`, `decision.py`, `manifest.py`, `validation.py` | `signal_schema.py` (REUTILIZAR) |
| `src/payoff/` | `payoff_model.py` (por plataforma/contrato, EV neto real) | `market_pricing.py`, `expected_value.py` |
| `src/opportunity/` | `schemas.py` (`Opportunity`, `OpportunityEvaluation`), `opportunity_repository.py` (append-only, mismo patrón que `history_repository.py`) | `matching` (event_id/market_id) |
| `src/calibration/` | `schemas.py` (`CalibrationOutput`), `calibration_layer.py` | `models/base.py` (`PModelOutput`, REUTILIZAR) |
| `src/evidence/` | `evidence_engine.py`, `schemas.py` (`EvidenceItem`) | `NormalizedRecord`, `quality_score.py` |
| `src/explainability/` | `explainability_engine.py` | `policy/decision.py`, `evidence/` (Principio 6: separado) |
| `src/health/` | `analysis_health.py` (`AnalysisHealth`, informativo) | `quality_score.py`, `evidence/` |
| `src/evaluation/learning.py` (dentro del paquete existente `evaluation/`, archivo nuevo) | Evaluation & Learning Framework, 5 dimensiones | `backtesting/metrics.py` (extendido), `opportunity/` |
| `config/policy/` (directorio nuevo, no Python) | Manifiestos de política versionados (formato en `POLICY_ENGINE_SPEC.md` §5) | — |

### 3.4 DEPRECAR

**Ninguno.** No se identificó ningún módulo de Fase 2 cuya eliminación
sea necesaria para Fase 3. `NormalizedRecord.model_output` (schemas.py)
queda formalmente **inerte** (nunca poblado, nunca leído por el Policy
Engine) en vez de deprecado — eliminarlo sería un cambio no solicitado a
un contrato Pydantic `extra="forbid"` consumido en 40+ tests de Fase 1/2;
mantenerlo vacío no tiene costo de mantenimiento real.

### 3.5 FUERA DE ALCANCE (explícito, ver también §6)

- Reactivación del LaunchAgent de captura histórica (DECISIÓN PENDIENTE D-1).
- Resolución del mapeo participante↔YES de Kalshi (DECISIÓN PENDIENTE D-2).
- Configuración de `ODDS_API_KEY`.
- Cualquier forma de ejecución automática de órdenes o gestión de banca
  (Principio 21, restricción dura).
- Reentrenar o recalibrar `HEURISTIC_V1` con evidencia real (depende de
  D-1).
- Migrar `src/models/registry.py` a ser exclusivamente genérico
  (eliminar `load_latest_mlb_artifact`) — la generalización aditiva sí
  entra en Fase 3, la migración/limpieza no.

---

## 4. Cómo se resuelve el Principio 4 (Confianza en 4 dimensiones) sin romper `HEURISTIC_V1`

`QualityScoreOutput` (Fase 2) produce un único escalar `confidence` a
partir de 7 componentes (`data_completeness`, `match_confidence_gap`,
`missing_critical`, `bookmaker_dispersion`, `sample_size`,
`market_liquidity`, `freshness`), sin ninguna noción de "Model
Reliability" (no hay insumo de performance del modelo, porque en Fase 2
no existía evaluación con histórico real).

`ConfidenceProfile` (nuevo, `src/policy/` o `src/opportunity/`, ver
`CONTRACTS_FASE3.md`) se define como una **composición**, no un
reemplazo:

| Dimensión de `ConfidenceProfile` | Se deriva de |
|---|---|
| `data_quality` | `QualityScoreOutput.components["data_completeness"]` + `["missing_critical"]` + `["freshness"]` (reutilizados, no recalculados) |
| `market_quality` | `QualityScoreOutput.components["bookmaker_dispersion"]` + `["sample_size"]` + `["market_liquidity"]` + `["match_confidence_gap"]` |
| `model_reliability` | **Nuevo** — proviene de `EvaluationRecord` histórico del `model_version`/`calibration_version` activo (Principio 15). `None` mientras no exista suficiente histórico evaluado — nunca se fabrica |
| `operational_safety` | **Nuevo** — `100 - operational_risk` (Corrección B), agregando señales operativas (staleness, `HardRuleResult` de tipo HOLD activos, latencia de fuentes) |

`QualityScoreOutput` (`confidence_method=HEURISTIC_V1`) sigue existiendo
exactamente igual, se sigue calculando igual, y sus tests no cambian.
`ConfidenceProfile` lo consume como una de sus fuentes. Esto satisface
literalmente Corrección B (misma dirección 100=mejor en todos los
componentes) sin retocar `_clip`/pesos de `quality_score.py`.

---

## 5. Tres hallazgos de contrato resueltos en esta auditoría

1. **Colisión de nombre `ModelOutput`.** `src/models/schemas.py` ya
   define una clase `ModelOutput` (vestigial, siempre `None`, campo de
   `NormalizedRecord`). El contrato `ModelOutput` pedido en la tarea de
   auditoría (con `p_model_raw`/`p_model_calibrated`/`model_version`/
   `calibration_version`) **no puede ser esa clase** sin romper el
   invariante de Fase 1 ("ModelOutput permanece completamente en None en
   esta fase"). Resolución: el contrato se satisface con la composición
   `PModelOutput` (Fase 2, sin cambios) + `CalibrationOutput` (nuevo) —
   ver `CONTRACTS_FASE3.md`. `NormalizedRecord.model_output` no se toca
   ni se puebla nunca desde Fase 3.
2. **Ambigüedad #2 sin resolver (participante↔YES).** Los Hard Rules
   (Corrección A) necesitan una categoría para el caso "el modelo predice
   sobre la etiqueta nativa, no necesariamente sobre el YES real del
   contrato". Se añade `unresolved_side_mapping` a `HARD_HOLD_WATCH` (no
   a `HARD_BLOCK_PASS`: es un caso recuperable, no un error estructural)
   — ver `POLICY_ENGINE_SPEC.md` §2.
3. **`selection_id` no existe en el dominio.** Kalshi no expone un id de
   selección separado del contrato binario. Se define
   `selection_id = f"{market_id}:{side.value}"`, determinístico,
   reconstruible sin estado — ver `CONTRACTS_FASE3.md` (`Opportunity`).

Ver `FASE3_AUDIT_REPORT.md` §6 para la lista completa de huecos de
contrato encontrados (incluye 2 adicionales de menor impacto).

---

## 6. Restricciones duras (reafirmadas)

- No se modifica `src/` en esta auditoría documental.
- No se entrena ningún modelo.
- No se borra ningún artefacto existente.
- No se mueve ni recrea `v2.0-baseline`.
- No se implementa Fase 3 todavía — solo se especifica.
- Ningún contrato de Fase 2 se altera sin la estrategia de compatibilidad
  de §3.2.
- No se agregan dependencias nuevas. `pyproject.toml`/`requirements.txt`
  (`requests`, `pydantic`, `pytest`, `python-dotenv`, `scikit-learn`)
  bastan: `pydantic.BaseModel(extra="forbid")` ya cubre el Contract &
  Invariant Framework (Principio 17) sin `pandera`/`jsonschema` u otra
  librería nueva.
- No se usan datos futuros en ninguna prueba (ver
  `TEMPORAL_REPRODUCIBILITY_SPEC.md`).
- No se ejecutan órdenes ni se gestiona banca (Principio 21).

---

## 7. Documentos de esta especificación

| Documento | Contenido |
|---|---|
| `PLAN_MASTER_FASE3.md` | Este documento — consolidación y correcciones |
| [`ARCHITECTURE_FASE3.md`](ARCHITECTURE_FASE3.md) | Árbol modular, flujo de datos |
| [`CONTRACTS_FASE3.md`](CONTRACTS_FASE3.md) | Los contratos de datos, campos, invariantes (16 originales + `ExplanationOutput`, adición correctiva del Paso 3.6) |
| [`POLICY_ENGINE_SPEC.md`](POLICY_ENGINE_SPEC.md) | Hard Rules, Soft Score, decisión |
| [`MODEL_PIPELINE_SPEC.md`](MODEL_PIPELINE_SPEC.md) | Arquitectura jerárquica de P_model |
| [`EVIDENCE_EXPLAINABILITY_SPEC.md`](EVIDENCE_EXPLAINABILITY_SPEC.md) | Evidence Engine / Explainability Engine |
| [`EVALUATION_LEARNING_SPEC.md`](EVALUATION_LEARNING_SPEC.md) | Framework de evaluación, 5 dimensiones |
| [`TEMPORAL_REPRODUCIBILITY_SPEC.md`](TEMPORAL_REPRODUCIBILITY_SPEC.md) | Integridad temporal, reproducibilidad |
| [`SHADOW_MODE_AND_PROMOTION_GATES.md`](SHADOW_MODE_AND_PROMOTION_GATES.md) | Release path, gates |
| [`IMPLEMENTATION_ROADMAP_FASE3.md`](IMPLEMENTATION_ROADMAP_FASE3.md) | Pasos reversibles, criterios de aceptación |
| [`FASE3_AUDIT_REPORT.md`](FASE3_AUDIT_REPORT.md) | Informe de auditoría completo, conclusión GO/CONDITIONAL-GO/NO-GO |

---

## 8. Decisiones pendientes (no se improvisan, quedan explícitas)

| Cod. | Decisión pendiente | Por qué no se resuelve aquí | Bloquea |
|---|---|---|---|
| ~~D-1~~ | **RESUELTA** (2026-08-01, ver `CONTINUITY.md` §0.19) — reactivado el LaunchAgent de captura histórica de forma permanente, tras corregir una contradicción operacional (estaba cargado sin autorización de Fase 3, contradiciendo la documentación) y cerrar la Política de Retención de Datos (`DATA_RETENTION_POLICY.md`) con su mecanismo de mantenimiento automatizado. | Historical Backtesting real, Shadow Mode, calibración real de `ConfidenceProfile.model_reliability`, todo `EVALUATION_LEARNING_SPEC.md` con datos reales ya no están bloqueados por falta de captura — sí siguen dependiendo del volumen de datos que se acumule con el tiempo |
| ~~D-2~~ | **RESUELTA** (post-cierre del roadmap, ver `CONTINUITY.md` §0.17) — el mapeo participante↔YES ya existía desde Fase 1 (`src/matching/market_matcher.py::_select_market`, selecciona el mercado de Kalshi cuyo `yes_sub_title` corresponde a `participant_a`); lo que faltaba era exponer su confianza. Se añadió `DataQuality.side_selection_confidence` (campo aditivo en Fase 1) y `unresolved_side_mapping` (Hard Hold, Fase 3) ahora la consume en vez de disparar como constante. | Ya no bloquea de forma incondicional — `unresolved_side_mapping` dispara solo cuando `side_selection_confidence` es `None` o está por debajo de `EVENT_NAME_MATCH_MIN_CONFIDENCE` |
| D-3 | Fórmula exacta de incorporación de `exchange_fee`/spread/slippage en `PayoffEstimate` | **REENCUADRADA** (ver `CONTINUITY.md` §0.18): no es "esperar a que Kalshi exponga un campo" (nunca lo hará por diseño de su API) — es una fórmula pública basada en precio (`kalshi.com/docs/kalshi-fee-schedule.pdf`), verificable pero no verificada todavía (3 intentos de `WebFetch` a la fuente primaria devolvieron HTTP 429). Punto de enganche preparado (`_estimate_kalshi_taker_fee`, `src/payoff/payoff_model.py`), sin implementar la fórmula de fuentes secundarias | `net_ev_status` distinto de `UNKNOWN` en producción — sigue bloqueado hasta verificación directa contra la fuente primaria |

D-1 y D-2 quedan resueltas; D-3 permanece reencuadrada y sin resolver por
diseño (dependencia externa verificable, no una decisión de arquitectura)
— ver `FASE3_AUDIT_REPORT.md` §15 y `CONTINUITY.md` §0.17/§0.18/§0.19
para el estado actualizado.
