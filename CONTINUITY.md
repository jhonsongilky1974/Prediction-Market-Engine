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
sincronización de resultados). **Actualizado de nuevo: 2026-07-26 (cierre
del Paso 12 — Esquema de señal: SignalInputs + SignalType/Side, sin
lógica de umbral).** Propósito: única fuente de verdad para continuar
este proyecto en una conversación nueva, sin acceso al historial de chat.
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
08daf2603bf25ec542f44a526f551c94118a423e
```
Mensaje: `Phase 2 Step 12: signal schema (SignalInputs + SignalType/Side, no threshold logic)`

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
| 25 | `08daf2603bf25ec542f44a526f551c94118a423e` | 2026-07-26 | Phase 2 Step 12: signal schema (SignalInputs + SignalType/Side, no threshold logic) | phase-2-dev (HEAD actual) |

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

Sin cambios desde el cierre del Paso 3 (commit `32677d6`). Sigue terminando en **"PLAN FASE 2 CORREGIDO — ESPERANDO APROBACIÓN FINAL"**, cosmético/desactualizado, no corregido, no solicitado.

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

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `08daf2603bf25ec542f44a526f551c94118a423e` o posterior) y `git status --short`.
- **Pasos 0-12 están todos completos.** El plan oficial (`PLAN_PHASE2.md` §12) no enumera ningún paso posterior al 12 con nombre de archivo concreto -- el siguiente trabajo conceptual pendiente es la lógica de clasificación de umbrales (ENTER/WATCH/PASS real) sobre `SignalInputs`, explícitamente diferida y no autorizada todavía (§16).
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real (§22) -- tanto MLB como tenis seguirán en `MODEL_NOT_TRAINED`/`INSUFFICIENT_HISTORY` hasta que exista volumen real.
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así hasta finalizar la Fase 2 completa -- no lo reactives sin autorización explícita nueva.
- **Ningún módulo cerrado fue modificado en el Paso 12** -- dos archivos nuevos únicamente (`src/signals/signal_schema.py`, `tests/unit/test_signal_schema.py`), verificado con `git diff --name-only HEAD` (vacío antes del commit).
- **`SignalInputs` es por lado, nunca por evento** (`Side.YES`/`Side.NO` del mismo `event_id` son objetos independientes) -- mismo invariante "nunca cruzados" del Paso 8, reforzado a nivel de tipo.
- **`SignalType` (ENTER/WATCH/PASS) vive separado de `SignalInputs`** -- ningún campo `signal_type` en el contenedor de datos, ninguna función en el proyecto lo calcula todavía. Un futuro motor de clasificación define su propio tipo de salida encima, sin modificar `signal_schema.py`.
- **`tennis_baseline.py` tiene persistencia totalmente independiente de `registry.py`** (prefijo de archivo `tennis_baseline_*`) — nunca reutilizar/generalizar `registry.py` para tenis sin una nueva decisión explícita.
- **Identidad de jugador de tenis = `competitor.id` de ESPN** (`model_inputs.context.participant_{a,b}_espn_id`), nunca nombre de texto — verificado estable contra la API real.
- **`round.displayName`** (ESPN) es la fuente directa de `tournament_round_context` — verificado real, no bloqueado por SofaScore.
- Patrón de trabajo ya validado en ocho pasos consecutivos (5b, 7, 6, 8, 9, 10, 11, 12): revisión contractual → (si hay ambigüedades) resolución punto por punto con metodología de 6 puntos → Design Proposal → aprobación explícita → (opcional, ya usado en el Paso 12) auditoría arquitectónica final de propiedades concretas antes de autorizar → implementación → tests → auditoría → commit separado de código → commit separado de `CONTINUITY.md`. Sigue este mismo patrón para cualquier trabajo futuro sobre clasificación de señales.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
