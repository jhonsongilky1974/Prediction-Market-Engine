# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). Actualizado: 2026-07-26 (cierre del Paso 7 —
Quality Score / Incertidumbre). **Actualizado de nuevo: 2026-07-26
(cierre del Paso 6 — Elo simple MLB / Baseline 2).** Propósito: única
fuente de verdad para continuar este proyecto en una conversación nueva,
sin acceso al historial de chat. Todo lo aquí escrito fue verificado
contra el estado real del repositorio en el momento de cada actualización
(comandos git, lectura de archivos, ejecución de tests, inspección
directa de `data/engine.db`) — no reconstruido de memoria.

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
03f21c0fc0af6c4e363e3ff84287edba5715b2fd
```
Mensaje: `Phase 2 Step 6: simple MLB Elo baseline (Baseline 2)`

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado en los cierres anteriores: un commit
propio, sin tocar código).

## 4. Último paso completamente terminado

**Paso 6 (Elo simple MLB / Baseline 2) — COMPLETO, AUDITADO Y
COMMITTEADO.** Implementa `src/models/mlb_elo.py` según `PLAN_PHASE2.md`
§12 ("mismo patrón infra/entrenado que 5a/5b, con un piso de datos
menor"), precedido de un Design Proposal explícito revisado y aprobado
por el usuario **antes** de escribir código (K-factor, ventaja de local,
rating inicial, umbral mínimo de partidos, persistencia independiente).

Con este cierre, la numeración "Paso 6 vs. Paso 7" queda completamente
sin ambigüedad: **Paso 6 = Elo MLB (completo, este documento)**, **Paso 7
= Quality Score/Incertidumbre (completo, cerrado en la actualización
anterior)**. Ambos cerrados, en orden invertido al numérico del plan por
la razón de nombrado ya documentada, sin consecuencias — cada uno se
implementó de forma independiente y ninguno depende del otro.

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
| 15 | `03f21c0fc0af6c4e363e3ff84287edba5715b2fd` | 2026-07-26 | Phase 2 Step 6: simple MLB Elo baseline (Baseline 2) | phase-2-dev (HEAD actual) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/                                          [Fase 2]
  registry.py / mlb_features.py    Sin cambios desde el Paso 5b
  tennis_features.py               PENDIENTE (Paso 11)

src/models/                                             [Fase 2 -- Pasos 5a/5b/6 COMPLETOS]
  base.py / mlb_baseline.py / registry.py    Sin cambios en esta actualización
                             (verificado explícitamente: ninguno aparece en
                             el diff del Paso 6)
  mlb_elo.py                 CONSTRUIDO (Paso 6) -- ver §8 abajo
  tennis_baseline.py         NO EXISTE (Paso 11)

src/pricing/                                            [Fase 2]
  market_pricing.py / no_vig.py / odds_consensus.py    Sin cambios

src/uncertainty/                                        [Fase 2 -- Paso 7 COMPLETO]
  quality_score.py           Sin cambios desde su cierre

src/signals/                                            [Fase 2 -- PENDIENTE COMPLETO]
  edge.py / expected_value.py / signal_schema.py   NO EXISTEN (Pasos 8/12)

src/storage/                                            [Fase 1 + Fase 2]
  history_repository.py      AMPLIADO (Paso 6): + get_all_event_snapshots()
                             (lectura pura, mismo patrón que los dos métodos
                             ya añadidos en Paso 5b) -- necesario para que el
                             dataset builder de Elo recorra identidad de
                             equipos/event_start_time de todos los eventos.
  repository.py              Sin cambios

src/pipelines/                                          [Fase 1 + wiring Fase 2]
  mlb_pipeline.py / mlb_results_sync.py / tennis_pipeline.py    Sin cambios desde el Paso 5b

src/connectors/mlb.py                                   Sin cambios desde el Paso 5b (Bloque 1)

src/backtesting/                                        [Fase 2 -- PENDIENTE]
  NO EXISTE -- tanto split_dataset_temporally (mlb_baseline.py) como el
  cálculo secuencial de mlb_elo.py son fuentes de verdad que este futuro
  paso debería reutilizar, no duplicar

src/evaluation/                                         [Fase 2 -- PENDIENTE]
  reports.py                 NO EXISTE

scripts/
  train_mlb_elo_model.py     NUEVO (Paso 6) -- CLI manual, sin lock, sin automatizar
  (resto sin cambios desde el Paso 5b)
```

Módulos ya cerrados **sin ningún cambio** en esta actualización,
verificado explícitamente antes del commit: `src/models/base.py`,
`src/models/mlb_baseline.py`, `src/models/registry.py`,
`src/uncertainty/quality_score.py`, `src/connectors/`,
`src/normalization/`, `src/matching/`, `src/quality/`,
`src/models/schemas.py`, `src/pricing/`, `src/pipelines/`. `mlb_elo.py`
reutiliza `PModelOutput`/`ModelStatus` de `base.py` **sin modificarlo**.

## 7. Árbol de directorios (delta desde la última actualización)

Nuevo en esta actualización:
```
src/models/mlb_elo.py                    [NUEVO]
scripts/train_mlb_elo_model.py            [NUEVO]
tests/unit/test_mlb_elo.py                [NUEVO]
```
Modificado (sin archivos nuevos más allá de los listados arriba):
`src/storage/history_repository.py` (+`get_all_event_snapshots()`),
`tests/unit/test_history_repository.py` (+1 test),
`tests/integration/test_e2e_real.py` (+1 test real).

## 8. Responsabilidad de `src/models/mlb_elo.py`

A diferencia del baseline de regresión logística (Paso 5a/5b), Elo:
- **No usa `feature_snapshots`** -- solo necesita identidad de equipos
  (`event_snapshots.normalized_record_json` →
  `model_inputs.context.{away,home}_team_id` + `event_start_time`) +
  resultado (`event_results`). Esto es lo que el plan llama "piso de
  datos menor".
- Se entrena con **actualización secuencial estrictamente cronológica**
  por `event_start_time` real (nunca `captured_at`/`recorded_at`, nunca
  aleatorio) -- no es un split train/validation i.i.d. como en 5a/5b.
- Tiene **persistencia propia e independiente** (JSON plano -- el
  artefacto completo, `{team_id: rating}` + metadata, es directamente
  serializable, sin joblib). No se modificó ni se reutilizó
  `src/models/registry.py`.
- Reutiliza `PModelOutput`/`ModelStatus` de `src/models/base.py` **sin
  modificarlos**.

**Fórmula** (parámetros `HEURISTIC`, aprobados explícitamente):
```
R_b_efectivo = R_b + home_advantage
expected_a = 1 / (1 + 10^((R_b_efectivo - R_a) / 400))
delta = K * (actual_a - expected_a)
R_a' = R_a + delta ; R_b' = R_b - delta
```
`K=20.0`, `home_advantage=25.0` (puntos Elo para el equipo local,
`participant_b`), `initial_rating=1500.0` (equipo nunca visto),
`min_games=50` (piso de suficiencia, menor que el de 300-500 de 5a/5b).

**Ausencia de leakage verificada explícitamente**, no solo afirmada: dos
tests de regresión (`test_no_look_ahead_bias_rating_update_is_composable`,
`test_no_look_ahead_bias_future_game_outcome_never_alters_earlier_rating`)
reconstruyen a mano la actualización de un partido usando ÚNICAMENTE el
rating previo, y confirman que coincide exactamente con la salida real
sin importar el resultado de partidos posteriores.

**Limitación deliberada, documentada para una versión posterior**: no se
implementa regresión entre temporadas (season regression-to-mean).

**`predict_mlb_elo()`**: equipo nunca visto en el artefacto → usa
`initial_rating` como prior neutro (con `warning` explícito, nunca se
niega a predecir ni fabrica un valor arbitrario). `data_cutoff_timestamp`
de la salida es `artifact.trained_at` (cuándo se actualizaron los
ratings por última vez), no "ahora" -- a diferencia de
`predict_mlb_baseline`, Elo no calcula nada en vivo.

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- Elo se procesa en un único paso hacia adelante, en orden cronológico estricto por `event_start_time` -- ningún partido usa información de partidos posteriores (verificado por test, no solo por inspección de código).
- La predicción (`expected_a`) de un partido se calcula ANTES de leer su propio resultado -- el resultado solo se usa para derivar el ajuste posterior.
- Un equipo sin historial nunca bloquea una predicción -- usa `initial_rating` como prior neutro, explícitamente señalado en `warnings`, nunca fabricado como si fuera un rating real medido.

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo en esta actualización: ninguna dependencia nueva añadida; ningún módulo ya cerrado modificado salvo la extensión aditiva de lectura ya explicada en `history_repository.py`.

## 11. Decisiones arquitectónicas tomadas durante el Paso 6

- **Fuente de datos**: `event_snapshots` (identidad + `event_start_time`) + `event_results` (resultado) -- nunca `feature_snapshots`, que Elo no necesita.
- **`get_all_event_snapshots()` añadido a `HistoryRepository`** -- tercera extensión de lectura aditiva del mismo patrón (tras las dos de Paso 5b), sin tocar el contrato append-only de escritura.
- **Persistencia independiente de `registry.py`** -- el artefacto de Elo es JSON puro, sin necesidad de joblib/sklearn; se decidió no forzarlo dentro del registro tipado a `MlbTrainedArtifact` del Paso 5a/5b.
- **`feature_set_version` del contrato compartido `PModelOutput`** reinterpretado para Elo como `"mlb_elo_v1_no_features"` (constante `ELO_FEATURE_SET_VERSION`) -- Elo no usa el feature registry de `src/features/registry.py`, se documentó explícitamente esta reinterpretación en vez de dejarlo ambiguo.
- **Verificación explícita de ausencia de look-ahead bias**, a pedido directo del usuario tras la implementación -- se añadieron dos tests de regresión matemática (no solo inspección de código) antes de la auditoría final.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Sin ambigüedades nuevas de tipo "A/B/C" durante el Paso 6 -- todas las decisiones de diseño (parámetros, persistencia, reinterpretación de `feature_set_version`) fueron parte del Design Proposal explícitamente revisado y aprobado antes de escribir código. La numeración "Paso 6 vs. Paso 7" (documentada en actualizaciones anteriores) queda ahora completamente resuelta con ambos pasos cerrados -- ver §4.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 36)

37. Instrucción de identificar el siguiente componente pendiente según el orden oficial del plan y comenzar únicamente ese -- identificado como Paso 6 (Elo simple MLB), sin reiniciar pasos ya completados.
38. Aprobación del Design Proposal de Elo con ajustes explícitos: `K=20` (no 10), `home_advantage=25` (no 24), `initial_rating=1500` y `min_games=50` mantenidos, persistencia independiente confirmada, regresión entre temporadas explícitamente diferida.
39. Autorización de implementación completa (código + tests unitarios + integración + regresión) antes de solicitar nueva auditoría.
40. Solicitud de confirmación explícita, puntual, de ausencia de look-ahead bias -- respondida con trazado de código línea por línea + dos tests de regresión matemática nuevos, verificados antes de la auditoría.
41. Aprobación de la auditoría final + autorización de commit (`03f21c0`) + instrucción de ejecutar regresión rápida post-commit y confirmar estado de `data/engine.db`/LaunchAgent.
42. Instrucción actual: actualizar este documento con el cierre del Paso 6.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
370 passed, 1 warning in ~19s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente, no relacionado. 24 tests nuevos en esta actualización (346 → 370): 22 en `test_mlb_elo.py` (secuencia cronológica/exclusiones honestas, cálculo puro verificado a mano, dos tests dedicados de ausencia de look-ahead bias, umbral de suficiencia, roundtrip de persistencia, inferencia con/sin artefacto/equipo desconocido/`team_id` faltante) + 1 en `test_history_repository.py` (`get_all_event_snapshots`) + 1 de integración real (`test_mlb_elo_inference_works_on_real_pipeline_output`).

## 15. Número total de tests existentes

**370** (verificado con `pytest --collect-only`). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado en el cierre de esta actualización y de nuevo post-commit. Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios -- ninguna dependencia nueva en el Paso 6:
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
| 7 | `src/uncertainty/quality_score.py` | ✅ COMPLETO |
| 6 | Elo simple MLB (Baseline 2) | ✅ **COMPLETO** (este documento) |
| 8 | `src/signals/edge.py` + `expected_value.py` | Pendiente -- siguiente en orden oficial |
| 9 | `src/backtesting/` | Pendiente |
| 10 | `src/evaluation/reports.py` | Pendiente |
| 11 | Tenis (features + baseline) | Pendiente |
| 12 | `src/signals/signal_schema.py` | Pendiente |

Con el cierre de este paso, **Paso 8 es el siguiente pendiente en el orden oficial del plan** (0-7 y 6 ya cerrados).

## 21. Estado de la automatización (LaunchAgent) — sin cambios

- **DESCARGADO** (`launchctl bootout`), confirmado sin cargar en el cierre de esta actualización.
- Debe permanecer descargado **hasta finalizar la Fase 2 completa** (instrucción vigente, sin cambios).
- Sigue sin haber corrido más que la única vez ya documentada (Bloque 2 del Paso 5b) -- ningún dato nuevo acumulado en `data/engine.db`.
- Para reactivarlo (NO ejecutar sin autorización explícita): `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.prediction-market-engine.run-e2e-historical.plist`
- Verificar estado: `launchctl print gui/$(id -u)/local.prediction-market-engine.run-e2e-historical`

## 22. Estado real de `data/engine.db` (verificado en el cierre de esta actualización)

```
event_snapshots     -> 93
feature_snapshots   -> 0
event_results       -> 0
normalized_records  -> 94
```
Sin cambios desde la última actualización -- el Paso 6 no toca `data/engine.db` (lee `HistoryRepository` solo cuando se invoca manualmente `scripts/train_mlb_elo_model.py`, no ejecutado contra la base real todavía). Con `event_results` en 0, `train_mlb_elo_model()` reportaría `INSUFFICIENT_HISTORY` si se ejecutara ahora mismo -- honesto y esperado, no un error.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- Elo no implementa regresión entre temporadas -- documentado como limitación deliberada para una versión posterior (§8).
- `compute_mlb_elo_ratings()` solo devuelve ratings finales, no predicciones intermedias partido-por-partido -- suficiente para el propósito actual (rating vigente para inferencia en vivo), pero el futuro Paso 9 (backtesting) necesitará una extensión que también exponga esas predicciones intermedias para evaluar la precisión histórica de Elo mediante Brier score/log loss.
- Ambos baselines MLB (regresión logística y Elo) seguirán reportando `INSUFFICIENT_HISTORY`/`MODEL_NOT_TRAINED` hasta que exista una primera ejecución real de `scripts/run_e2e.py --mode historical` + `scripts/sync_mlb_results.py` con el código ya committeado (§22).

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `03f21c0fc0af6c4e363e3ff84287edba5715b2fd` o posterior) y `git status --short`.
- **Pasos 6 y 7 están AMBOS completos** -- el siguiente pendiente en el orden oficial del plan es el **Paso 8** (`src/signals/edge.py` + `expected_value.py`).
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real -- ambos baselines MLB (regresión logística y Elo) reportarán honestamente `INSUFFICIENT_HISTORY`/`MODEL_NOT_TRAINED` hasta la primera ejecución real (§22/§23).
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así hasta finalizar la Fase 2 completa -- no lo reactives sin autorización explícita nueva.
- `src/models/mlb_elo.py` no toca `src/models/registry.py`, `base.py` (solo lo importa), ni ningún módulo de Pasos 1-5b/7 -- persistencia y dataset builder completamente propios.
- Patrón de trabajo ya validado tres veces (Paso 5b, 7, 6): para pasos con fórmulas/parámetros sin especificar en el plan, un Design Proposal explícito revisado y aprobado ANTES de programar es obligatorio -- no lo saltes en el Paso 8 (EDGE/EV), que probablemente también tenga huecos de especificación similares.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
