# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). Actualizado: 2026-07-26 (cierre del Paso 7 —
Quality Score / Incertidumbre). Actualizado: 2026-07-26 (cierre del
Paso 6 — Elo simple MLB / Baseline 2). Actualizado: 2026-07-26 (cierre del
Paso 8 — EDGE_YES/EDGE_NO + Expected Value). **Actualizado de nuevo:
2026-07-26 (cierre del Paso 9 — Backtesting: dataset + walk-forward
splitter + metrics).** Propósito: única fuente de verdad para continuar
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
f15fc592860d3d047a361958b2044a32c7c80b69
```
Mensaje: `Phase 2 Step 9: backtesting infrastructure (dataset + walk-forward splitter + metrics)`

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado en los cierres anteriores).

## 4. Último paso completamente terminado

**Paso 9 (`src/backtesting/`) — COMPLETO, AUDITADO Y COMMITTEADO.**
Implementa la infraestructura de backtesting según `PLAN_PHASE2.md` §10:
dataset (uniendo `event_snapshots`+`feature_snapshots`+`event_results` de
`HistoryRepository`), splitter walk-forward estrictamente temporal, y
métricas de calibración puras (Brier, log loss, accuracy, curva de
calibración). Precedido de una revisión contractual completa (10
secciones) y un Design Proposal formal, ambos con múltiples ambigüedades
señaladas explícitamente y resueltas una por una por el usuario antes de
escribir código (ver §12/§13 abajo).

Con este cierre: **Pasos 0, 1, 2, 3, 4, 5a, 5b, 6, 7, 8 y 9 están todos
completos.** El siguiente pendiente en el orden oficial es el **Paso 10**
(`src/evaluation/reports.py`).

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
| 19 | `f15fc592860d3d047a361958b2044a32c7c80b69` | 2026-07-26 | Phase 2 Step 9: backtesting infrastructure (dataset + walk-forward splitter + metrics) | phase-2-dev (HEAD actual) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/                                          [Fase 2]  Sin cambios desde el Paso 5b
src/models/                                             [Fase 2 -- 5a/5b/6 COMPLETOS]  Sin cambios en esta actualización
src/pricing/                                            [Fase 2]  Sin cambios
src/uncertainty/                                        [Fase 2 -- Paso 7 COMPLETO]  Sin cambios

src/signals/                                            [Fase 2 -- Paso 8 COMPLETO]  Sin cambios en esta actualización
  edge.py                    compute_edge_yes/compute_edge_no
  expected_value.py          compute_ev_yes_bruto/compute_ev_no_bruto,
                             compute_ev_yes_neto/compute_ev_no_neto (siempre None hoy)
  signal_schema.py           NO EXISTE (Paso 12)

src/storage/                                            [Fase 1 + Fase 2]  Sin cambios desde el Paso 6
src/pipelines/                                          [Fase 1 + wiring Fase 2]  Sin cambios desde el Paso 5b
src/connectors/mlb.py                                   Sin cambios desde el Paso 5b (Bloque 1)

src/backtesting/                                        [Fase 2 -- Paso 9 COMPLETO]
  __init__.py                CONSTRUIDO
  dataset.py                  CONSTRUIDO -- build_backtest_dataset(history_repository) -> BacktestDataset
                              (une event_snapshots+feature_snapshots+event_results,
                              reconstruye NormalizedRecord histórico, recalcula
                              P_market_YES/NO + quality_score sobre ese registro)
  splitter.py                 CONSTRUIDO -- walk_forward_splits(...) -> Iterator[Fold]
                              (HistoryRepository TEMPORAL aislado por fold, cero
                              leakage por construcción, agnóstico al modelo)
  metrics.py                   CONSTRUIDO -- brier_score/log_loss_metric/
                              accuracy_metric/calibration_curve (n_bins=10)

src/models/mlb_baseline.py                              [Fase 2 -- extensión aditiva del Paso 9]
  predict_mlb_baseline_from_features  NUEVO -- wrapper delgado sobre el mismo
                              núcleo de inferencia que predict_mlb_baseline
                              (_predict_proba_from_vectorized_features, también
                              nuevo), para aplicar el modelo a features YA
                              materializadas (histórico), sin recalcularlas en vivo

src/evaluation/                                         [Fase 2 -- PENDIENTE, siguiente paso]
  reports.py                 NO EXISTE

scripts/                                                Sin cambios desde el Paso 6
```

Módulos ya cerrados **sin ningún cambio** en esta actualización,
verificado explícitamente antes del commit: `src/pricing/market_pricing.py`,
`src/models/base.py`, `src/models/schemas.py`, `src/models/mlb_baseline.py`,
`src/models/mlb_elo.py`, `src/models/registry.py`,
`src/uncertainty/quality_score.py`, y todos los módulos de Fase 1.
`edge.py`/`expected_value.py` reutilizan `market_price_yes`/
`market_price_no` (Paso 3) y `PModelOutput` (Paso 5a) **sin modificarlos**.

## 7. Árbol de directorios (delta desde la última actualización)

Nuevo en esta actualización:
```
src/backtesting/__init__.py               [NUEVO]
src/backtesting/dataset.py                [NUEVO]
src/backtesting/splitter.py               [NUEVO]
src/backtesting/metrics.py                [NUEVO]
tests/unit/test_backtesting_dataset.py    [NUEVO]
tests/unit/test_backtesting_splitter.py   [NUEVO]
tests/unit/test_backtesting_metrics.py    [NUEVO]
```
Modificado:
- `src/models/mlb_baseline.py` — extensión aditiva pre-autorizada explícitamente (ver §11): `_predict_proba_from_vectorized_features` (núcleo de inferencia extraído) + `predict_mlb_baseline_from_features` (wrapper nuevo). `predict_mlb_baseline` cambia internamente para llamar al núcleo compartido, comportamiento observable idéntico (verificado por test de equivalencia exacta).
- `tests/unit/test_mlb_baseline.py` (+3 tests para la extensión anterior).
- `tests/integration/test_e2e_real.py` (+1 test real).

## 8. Responsabilidad de `src/backtesting/`

**`dataset.py`** — `build_backtest_dataset(history_repository) -> BacktestDataset`. Une `event_snapshots`+`feature_snapshots`+`event_results` (enlace exacto vía `feature_snapshots.event_snapshot_id`, no una heurística de "snapshot más cercano"). Por cada fila válida, reconstruye el `NormalizedRecord` histórico COMPLETO desde `normalized_record_json` (verificado byte a byte por test) y recalcula sobre ese registro, con las funciones ya cerradas y SIN modificarlas, `P_market_YES`/`P_market_NO` (Paso 3) y `compute_quality_score` (Paso 7) — usando el instante histórico (`captured_at`) como `now`, nunca el reloj real. Mismo corte temporal no negociable que en 5b/6 (`computed_at < recorded_at` del resultado). Cinco categorías de exclusión, cada una con warning nombrado (versión de features incorrecta, sin snapshot correspondiente, sin resultado, leakage temporal, resultado no binario).

**`splitter.py`** — `walk_forward_splits(history_repository, dataset, min_train_size, test_block_size) -> Iterator[Fold]`. Walk-forward estrictamente temporal (ventana de train expansiva, ventana de test = siguiente bloque), agnóstico al modelo (no importa `mlb_baseline` ni `mlb_elo`). **Invariante central, confirmado explícitamente por el usuario antes de implementar: cero leakage por construcción.** Cada fold recibe un `HistoryRepository` TEMPORAL y aislado, poblado únicamente con filas cuyo timestamp es ≤ el corte del fold — el no-leakage no depende de la disciplina de la función de entrenamiento que se invoque después, sino de que los datos futuros físicamente no existen en el objeto que se le entrega. El repositorio temporal se elimina automáticamente al avanzar al siguiente fold (contrato de uso documentado explícitamente en el docstring: debe consumirse dentro de la misma iteración del `for`). Nunca se parte un grupo de filas con `data_cutoff_timestamp` idéntico entre train y test. Sin volumen suficiente → iterador vacío, nunca un error.

**`metrics.py`** — `brier_score`/`log_loss_metric`/`accuracy_metric`/`calibration_curve` (`n_bins=10`, aprobado explícitamente). Funciones puras `(y_true, y_pred) -> métrica`, sin conocer `HistoryRepository` ni ningún modelo concreto. `None` cuando no hay muestras, nunca un valor fabricado. `log_loss_metric` usa `labels=[0,1]` explícito (mismo patrón de Paso 5b) — con eso, calcula igual aunque el fold contenga una sola clase (verificado que NO es `None` en ese caso, corrigiendo una expectativa inicial incorrecta durante el desarrollo de los tests).

**Extensión en `src/models/mlb_baseline.py`** — `predict_mlb_baseline_from_features(features, loaded_artifact) -> Optional[float]`: wrapper delgado, invocado por el backtesting del baseline logreg para aplicar el modelo a features YA materializadas (`feature_snapshots`), ya que `predict_mlb_baseline` original exige `MlbFeatureInputs` en vivo (imposible para un evento pasado). Comparte, sin excepción, el mismo núcleo `_predict_proba_from_vectorized_features` que `predict_mlb_baseline` — una sola implementación, nunca duplicada, verificado por test de equivalencia exacta. `predict_mlb_elo` (Paso 6) no necesitó ninguna extensión: ya opera solo sobre `record`+artefacto, sin fetch en vivo.

**Explícitamente diferido de esta iteración (aprobado así por el usuario)**: ROI simulado y CLV (ni siquiera un stub — `event_snapshots`/`event_results` reales en 0 filas hoy no ejercitarían ese código); reentrenamiento walk-forward real de un modelo concreto y comparación entre modelos (queda para quien invoque `walk_forward_splits`, hoy solo los tests — el Paso 10 lo hará en serio); persistencia en disco de resultados de backtest (todo en memoria, dataclasses).

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- **Cero leakage por construcción** en el walk-forward: cada fold recibe un `HistoryRepository` físicamente incapaz de contener filas futuras — verificado por test dedicado (`test_train_repository_never_contains_future_rows`), no solo documentado.
- `dataset.py`/`splitter.py`/`metrics.py` son agnósticos al modelo — no importan `mlb_baseline` ni `mlb_elo`.
- `predict_mlb_baseline_from_features` y `predict_mlb_baseline` comparten una única implementación de inferencia — nunca dos caminos que puedan divergir.
- Ningún grupo de filas con `data_cutoff_timestamp` idéntico se parte entre train y test de un mismo fold.

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo: ninguna dependencia nueva añadida; único módulo cerrado modificado es `mlb_baseline.py`, y solo de forma aditiva, explícitamente flageada y autorizada antes de tocarlo (ver §11).

## 11. Decisiones arquitectónicas tomadas durante el Paso 9

- **Mecanismo de cero-leakage vía `HistoryRepository` temporal por fold** (en vez de parametrizar un cutoff dentro de `build_mlb_training_dataset`/`build_mlb_elo_game_sequence`, que hubiera exigido modificar esos módulos cerrados) — la garantía de no-leakage se vuelve estructural (los datos futuros no existen en el objeto), no una promesa de disciplina de código, y permite reutilizar `train_mlb_baseline_model`/`train_mlb_elo_model` **sin modificarlos en absoluto**.
- **Extensión aditiva a `mlb_baseline.py` explícitamente autorizada**, con una condición estricta del usuario: `predict_mlb_baseline_from_features` debe ser exclusivamente un wrapper delgado sobre una única implementación compartida (`_predict_proba_from_vectorized_features`), nunca una lógica duplicada ni un camino alternativo — implementado exactamente así y verificado por test de equivalencia bit a bit con `predict_mlb_baseline`.
- **Interfaz genérica agnóstica al modelo** (Ambigüedad B, aprobada): `dataset.py`/`splitter.py`/`metrics.py` no acoplan a ningún algoritmo concreto; quien invoca `walk_forward_splits` decide qué función de entrenamiento/inferencia usar por fold.
- **ROI/CLV diferidos por completo** (Ambigüedad C, aprobada) — ni siquiera un stub `None`-gated, a diferencia de `EV_neto` (Paso 8), porque no hay ningún dato real hoy que ejercite ese código.
- **`min_train_size`/`test_block_size` sin default embebido** (Ambigüedad D, aprobada) — el llamador debe pasarlos explícitamente; para el baseline logreg reutilizar `DEFAULT_MIN_TRAINING_SAMPLES=300`, para Elo `DEFAULT_MIN_GAMES=50` (mismos umbrales ya aprobados en 5b/6, ningún número nuevo inventado).
- **Solo en memoria** (Ambigüedad E, aprobada) — sin persistencia de resultados de backtest; queda para el Paso 10.
- **`n_bins=10`** para `calibration_curve`, aprobado explícitamente.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Paso 9 tuvo la revisión de ambigüedades más extensa hasta ahora — cinco preguntas explícitas (A-E), todas resueltas por el usuario antes de redactar el Design Proposal formal:
- **Ambigüedad A** (cómo obtener `P_model` histórico sin leakage): resuelta como A1 — reentrenar por fold, con prioridad absoluta sobre cualquier otra consideración ("bajo ninguna circunstancia un modelo puede ver datos futuros").
- **Ambigüedad B** (alcance de modelos): interfaz genérica.
- **Ambigüedad C** (ROI/CLV): diferido por completo.
- **Ambigüedad D** (tamaño de fold): reutilizar umbrales ya aprobados, sin default embebido en el módulo.
- **Ambigüedad E** (persistencia): solo en memoria.
Una sexta decisión de implementación (no ambigüedad de negocio, sino de diseño técnico) se resolvió durante el Design Proposal: el mecanismo exacto para garantizar A1 sin modificar `train_mlb_baseline_model`/`train_mlb_elo_model` (repositorio temporal aislado por fold, §11).

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 46)

47. Instrucción de realizar primero la revisión contractual completa del Paso 9 (10 secciones específicas) sin escribir código, siguiendo el mismo flujo institucional.
48. Aprobación de Ambigüedad A = A1 con énfasis explícito: "El principio de no leakage tiene prioridad absoluta."
49. Resolución de Ambigüedades B/C/D/E, las cuatro con la opción recomendada.
50. Aprobación del Design Proposal completo, con una condición estricta sobre `predict_mlb_baseline_from_features` (wrapper delgado, una sola implementación, sin camino alternativo) y `n_bins=10` confirmado.
51. Autorización explícita para implementar el Paso 9 completo, manteniendo como invariantes: cero leakage por construcción, `HistoryRepository` temporal por fold, una única implementación de inferencia, y el wrapper delgado exacto — con instrucción de ejecutar la batería completa + regresión y no commitear hasta revisar la auditoría.
52. Aprobación de la auditoría técnica del Paso 9 + autorización de commit (`f15fc59`), con instrucción explícita de: regresión final, confirmación exacta de la salida de pytest, commit, actualización de `CONTINUITY.md`, y entrega del hash con el repositorio limpio.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
423 passed, 1 warning in ~25s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente. 35 tests nuevos en esta actualización (388 → 423): 3 en `test_mlb_baseline.py` (extensión `predict_mlb_baseline_from_features`) + 11 en `test_backtesting_dataset.py` + 6 en `test_backtesting_splitter.py` + 14 en `test_backtesting_metrics.py` + 1 de integración real (`test_backtest_dataset_builds_honestly_on_real_mlb_pipeline_output_without_results`).

## 15. Número total de tests existentes

**423** (verificado con `pytest --collect-only` y con la salida final de pytest). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado antes del commit, y de nuevo post-commit (`f15fc59`). Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios — ninguna dependencia nueva en el Paso 9:
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
| 9 | `src/backtesting/` | ✅ **COMPLETO** (este documento) |
| 10 | `src/evaluation/reports.py` | Pendiente — **siguiente en orden oficial** |
| 11 | Tenis (features + baseline) | Pendiente |
| 12 | `src/signals/signal_schema.py` | Pendiente |

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
Sin cambios desde la última actualización (mismo `mtime`, 24 jul 23:58) — el Paso 9 no toca `data/engine.db` en absoluto: `walk_forward_splits` opera exclusivamente sobre repositorios temporales (`tempfile`), nunca sobre la base de producción. Con `feature_snapshots`/`event_results` reales en 0 filas, `build_backtest_dataset(history_repository)` contra la base real produciría hoy un `BacktestDataset` vacío (0 filas) — honesto, verificado por el test de integración real de esta iteración.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- ROI simulado y CLV completamente sin implementar (ni stub) — pendiente de que exista historial de precios real suficiente (§10 del plan).
- El walk-forward reentrena un modelo completo (incluyendo, para el baseline logreg, un `fit` de scikit-learn) por cada fold vía un `HistoryRepository` temporal repoblado desde cero — funcionalmente correcto y verificado, pero no optimizado para volumen alto; aceptable dado que el volumen real hoy es ≈0 y no es un requisito de esta iteración.
- Mapeo participante↔YES de un contrato de Kalshi específico sigue sin resolver (Ambigüedad #2/Paso 4, Ambigüedad C/Paso 5a-6, señalada de nuevo en Paso 8) — afecta la interpretación real de cualquier `P_model`/`EDGE`/backtest contra mercados reales.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `f15fc592860d3d047a361958b2044a32c7c80b69` o posterior) y `git status --short`.
- **Pasos 0-9 están todos completos.** El siguiente pendiente en el orden oficial del plan es el **Paso 10** (`src/evaluation/reports.py` — comparación Baseline 0 vs 1 vs 2).
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real -- `build_backtest_dataset` contra la base real produce hoy un dataset vacío, honesto (§22).
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así hasta finalizar la Fase 2 completa -- no lo reactives sin autorización explícita nueva.
- `src/backtesting/` no toca ningún módulo de Pasos 0-8 -- solo los importa. La única modificación a un módulo cerrado en todo Fase 2 hasta ahora es la extensión aditiva de `mlb_baseline.py` (Paso 9, §11), explícitamente autorizada.
- **Contrato de uso importante de `walk_forward_splits`**: el `HistoryRepository` de un fold debe entrenarse/consultarse dentro de la misma iteración del `for`, antes de pedir el siguiente fold -- el directorio temporal se borra al avanzar el generador (ver docstring de `src/backtesting/splitter.py`).
- Patrón de trabajo ya validado en cinco pasos consecutivos (5b, 7, 6, 8, 9): revisión contractual → Design Proposal si hay huecos de especificación → aprobación explícita (ambigüedad por ambigüedad si hace falta) → implementación → tests → auditoría → commit separado de código → commit separado de `CONTINUITY.md`. El Paso 10 (`evaluation/reports.py`, comparación de modelos) probablemente también tenga huecos de especificación -- no saltarse el Design Proposal ahí tampoco.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
