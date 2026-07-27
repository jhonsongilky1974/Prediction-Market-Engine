# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). Actualizado: 2026-07-26 (cierre del Paso 7 —
Quality Score / Incertidumbre). Actualizado: 2026-07-26 (cierre del
Paso 6 — Elo simple MLB / Baseline 2). Actualizado: 2026-07-26 (cierre del
Paso 8 — EDGE_YES/EDGE_NO + Expected Value). Actualizado: 2026-07-26
(cierre del Paso 9 — Backtesting: dataset + walk-forward splitter +
metrics). **Actualizado de nuevo: 2026-07-26 (cierre del Paso 10 —
Comparación de baselines: Baseline 0 vs 1 vs 2).** Propósito: única fuente
de verdad para continuar este proyecto en una conversación nueva, sin
acceso al historial de chat.
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
cfb8dc09562f198c36cd0c6528be440b79cb15e8
```
Mensaje: `Phase 2 Step 10: baseline comparison reports (Baseline 0 vs 1 vs 2)`

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado en los cierres anteriores).

## 4. Último paso completamente terminado

**Paso 10 (`src/evaluation/reports.py`) — COMPLETO, AUDITADO Y
COMMITTEADO.** Implementa la comparación Baseline 0 (mercado) vs Baseline
1 (regresión logística, Paso 5a/5b) vs Baseline 2 (Elo, Paso 6) según
`PLAN_PHASE2.md` §3/§12, reutilizando `src/backtesting/` (Paso 9) sin
modificarlo, más segmentación por EDGE/confianza/liquidez. Precedido de
una revisión contractual completa, seis ambigüedades (A-F) resueltas una
por una, un Design Proposal formal aprobado, y una auditoría técnica final
explícita con ocho verificaciones puntuales (ningún módulo cerrado
modificado, cero duplicación de métricas, cero leakage estructural, mismo
universo de eventos, Baseline 0 sin EDGE, 435 tests desde estado limpio,
diff acotado, veredicto de autorización de producción) — ver §11/§12/§13
abajo.

Con este cierre: **Pasos 0, 1, 2, 3, 4, 5a, 5b, 6, 7, 8, 9 y 10 están
todos completos.** El siguiente pendiente en el orden oficial es el
**Paso 11** (tenis: `src/features/tennis_features.py` +
`src/models/tennis_baseline.py`).

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
| 21 | `cfb8dc09562f198c36cd0c6528be440b79cb15e8` | 2026-07-26 | Phase 2 Step 10: baseline comparison reports (Baseline 0 vs 1 vs 2) | phase-2-dev (HEAD actual) |

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

scripts/                                                Sin cambios desde el Paso 6
```

Módulos ya cerrados **sin ningún cambio** en esta actualización,
verificado explícitamente antes del commit (incluida una verificación
`git diff --name-only` dirigida a cada uno): `src/pricing/market_pricing.py`,
`src/models/base.py`, `src/models/schemas.py`, `src/models/mlb_baseline.py`,
`src/models/mlb_elo.py`, `src/models/registry.py`,
`src/uncertainty/quality_score.py`, `src/backtesting/*`, `src/signals/*`, y
todos los módulos de Fase 1. **Primera vez desde el Paso 5b que un paso no
requiere ninguna extensión aditiva a un módulo cerrado** -- `reports.py`
únicamente invoca lo ya construido.

## 7. Árbol de directorios (delta desde la última actualización)

Nuevo en esta actualización:
```
src/evaluation/__init__.py                [NUEVO]
src/evaluation/reports.py                 [NUEVO]
tests/unit/test_evaluation_reports.py     [NUEVO]
```
Modificado:
- `tests/integration/test_e2e_real.py` (+1 test real).

Ningún módulo cerrado modificado — primera vez desde el Paso 5b (ver §6).

## 8. Responsabilidad de `src/evaluation/reports.py`

**`compare_baselines(history_repository, dataset, fit_fn_baseline_1, predict_fn_baseline_1, fit_fn_baseline_2, predict_fn_baseline_2, min_train_size=300, test_block_size=30) -> BaselineComparisonReport`** — orquesta la comparación Baseline 0 (mercado) vs Baseline 1 (logreg, Paso 5a/5b) vs Baseline 2 (Elo, Paso 6). **Invariante central: los tres se evalúan sobre el MISMO universo de filas** — un único recorrido de `walk_forward_splits` (Paso 9, sin modificar) alimenta, dentro de cada fold y antes de avanzar al siguiente, a los tres baselines: Baseline 0 se lee directamente de `fold.test_rows.p_market_yes` (no se reentrena nada); Baseline 1/2 se entrenan sobre el mismo `fold.train_repository` vía `fit_fn`/`predict_fn` provistos por el llamador. `min_train_size`/`test_block_size` son parámetros configurables con defaults documentados (300 = `DEFAULT_MIN_TRAINING_SAMPLES` de `mlb_baseline.py`, duplicado deliberadamente sin importar el módulo, para mantener `reports.py` agnóstico; 30 = heurística nueva de ingeniería, no calibrada, ~una semana de calendario MLB).

`segment_by_edge`/`segment_by_confidence`/`segment_by_liquidity` — desagregación por bucket de ancho fijo (mismo esquema que `calibration_curve`, clamping a los extremos). `segment_by_edge` reutiliza `compute_edge_yes` (Paso 8) **tal cual**, envolviendo la predicción en un `PModelOutput` mínimo — nunca reimplementa `p_model - p_market`. **Baseline 0 está estructuralmente ausente de `edge_segments`** (su EDGE es 0 por definición) — no una llave vacía, la llave simplemente no existe en el diccionario.

Agnóstico al modelo: no importa `mlb_baseline.py` ni `mlb_elo.py`; el llamador (tests hoy) adapta `predict_mlb_baseline_from_features`/`predict_mlb_elo` a la firma genérica `(BacktestRow, artefacto) -> Optional[float]`. Nota de contrato descubierta durante la implementación: `train_mlb_baseline_model` devuelve solo metadata (`MlbTrainedArtifact`), no el modelo cargado — el adaptador debe recargar vía `load_latest_mlb_artifact` (documentado explícitamente en el docstring de `compare_baselines` para que no se repita el tropiezo). Solo en memoria (dataclasses), sin persistencia, sin dependencias de visualización nuevas.

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- **Mismo universo de filas** para los tres baselines — un único recorrido de `walk_forward_splits`, nunca tres pasadas independientes.
- **Baseline 0 nunca usa EDGE** — verificado no solo por test sino por inspección directa de código: `compute_edge_yes` se invoca únicamente dentro de `segment_by_edge`, y `segment_by_edge` se invoca únicamente con los pares de Baseline 1/2.
- **`history_repository` (crudo, sin acotar) nunca llega a una función de entrenamiento** — se usa únicamente como argumento de `walk_forward_splits`; `fit_fn_baseline_1`/`fit_fn_baseline_2` reciben siempre `fold.train_repository` (verificado por inspección de código en la auditoría final, no solo por test).
- Cero duplicación de métricas — las cuatro funciones de `src.backtesting.metrics` se importan y se usan tal cual, ninguna fórmula reimplementada dentro de `reports.py`.

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo: ninguna dependencia nueva añadida; **ningún módulo cerrado modificado en absoluto** en este paso (a diferencia de todos los pasos desde el 5b, que requirieron al menos una extensión aditiva puntual).

## 11. Decisiones arquitectónicas tomadas durante el Paso 10

- **Un único recorrido compartido de `walk_forward_splits`** en vez de tres pasadas independientes (una por baseline) — es la única forma de garantizar "mismo universo de filas" sin depender de que folds generados por separado coincidan por casualidad.
- **`min_train_size`/`test_block_size` como parámetros configurables CON default documentado** (300/30) — ajuste explícito del usuario sobre el Design Proposal original (que proponía dejarlos sin ningún default, mismo estilo que `walk_forward_splits`); aquí sí se fija un default para que `compare_baselines` sea invocable sin fricción, pero siguen siendo parámetros reales, no valores ocultos (verificado por test de configurabilidad).
- **EDGE de evaluación reutiliza `compute_edge_yes` (Paso 8) vía un `PModelOutput` mínimo construido ad-hoc**, en vez de recalcular la fórmula inline — evita cualquier riesgo de divergencia entre la fórmula de señales real y la de evaluación.
- **Baseline 0 excluido estructuralmente de `edge_segments`** (la llave no existe, no es un valor `None`/vacío) — decisión explícita (Ambigüedad B del Design Proposal) porque su EDGE es 0 por definición.
- **Solo EDGE_YES segmentado, no EDGE_NO** — alcance acotado a propósito, documentado.
- **Sin persistencia, sin visualización** — mismo patrón que Paso 9.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Paso 10 tuvo seis ambigüedades explícitas (A-F), todas resueltas por el usuario antes del Design Proposal formal:
- **Ambigüedad A** (¿mismo universo de filas?): A1 — `min_train_size`/`test_block_size` comunes a los tres baselines.
- **Ambigüedad B** (EDGE de Baseline 0): excluir de la segmentación, documentar que es 0 por definición.
- **Ambigüedad C** (buckets de segmentación): reutilizar el esquema propuesto (ancho fijo, mismo estilo que `calibration_curve`).
- **Ambigüedad D** (persistencia): solo memoria, sin artefactos en disco.
- **Ambigüedad E** (visualización): solo buckets numéricos, sin dependencias gráficas.
- **Ambigüedad F** (volumen real ≈0): comportamiento honesto, reporte válido sin fabricar ni fallar.
Un ajuste adicional sobre el Design Proposal aprobado: mantener `min_train_size`/`test_block_size` como parámetros configurables pero **con** default documentado (300/30), a diferencia del enfoque sin-default de `walk_forward_splits`.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 52)

53. Instrucción de iniciar la revisión contractual del Paso 10 con la misma metodología institucional (contractual → ambigüedades → Design Proposal → aprobación → implementación mínima → tests → auditoría → commit).
54. Resolución explícita de las Ambigüedades A-F, todas con la opción recomendada.
55. Aprobación del Design Proposal formal, con un único ajuste: `min_train_size`/`test_block_size` configurables con los defaults propuestos documentados (no sin default).
56. Autorización para implementar el Paso 10 completo + ejecutar suite completa + auditoría técnica + presentar reporte antes del commit.
57. Solicitud de una auditoría final adicional, con ocho verificaciones puntuales explícitas (módulos cerrados, duplicación de métricas, leakage, mismo universo, Baseline 0 sin EDGE, 435 tests desde estado limpio, diff acotado, veredicto de autorización de producción) — todas confirmadas por inspección directa de código, no solo por los tests ya escritos.
58. Aprobación de la auditoría final + autorización de commit (`cfb8dc0`), con instrucción explícita de: verificación post-commit, actualización de `CONTINUITY.md`, confirmación de hashes/número de tests, y **no iniciar el Paso 11** hasta nueva autorización — solo presentar su revisión contractual.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
435 passed, 1 warning in ~28-30s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente. 12 tests nuevos en esta actualización (423 → 435): 11 en `test_evaluation_reports.py` (comparación end-to-end, exclusión de Baseline 0 de `edge_segments`, segmentación exacta por bucket, configurabilidad de `min_train_size`/`test_block_size`, dataset vacío honesto) + 1 de integración real (`test_compare_baselines_builds_honestly_on_real_mlb_pipeline_output_without_results`). Verificado además desde un estado limpio (`__pycache__` purgado antes de correr, en la auditoría final).

## 15. Número total de tests existentes

**435** (verificado con `pytest --collect-only` y con la salida final de pytest). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado antes del commit, en la auditoría final (con caché de bytecode purgada), y de nuevo post-commit (`cfb8dc0`). Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios — ninguna dependencia nueva en el Paso 10:
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
| 10 | `src/evaluation/reports.py` | ✅ **COMPLETO** (este documento) |
| 11 | Tenis (`src/features/tennis_features.py` + `src/models/tennis_baseline.py`) | Pendiente — **siguiente en orden oficial; solo revisión contractual autorizada, NO implementación** |
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
Sin cambios desde la última actualización (mismo `mtime`, 24 jul 23:58) — el Paso 10 no toca `data/engine.db` en absoluto: `compare_baselines` opera exclusivamente a través de `walk_forward_splits` (repositorios temporales) y directorios temporales para artefactos de modelo (`tempfile.TemporaryDirectory`), nunca sobre la base de producción ni `data/models/` real. Con `feature_snapshots`/`event_results` reales en 0 filas, `compare_baselines` contra la base real produce hoy un `BaselineComparisonReport` con `n_predictions=0` en los tres baselines — honesto, verificado por el test de integración real de esta iteración.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- `test_block_size=30` es una heurística de ingeniería nueva, no calibrada (igual que `_MARKET_LIQUIDITY_TARGET` en `quality_score.py`) — revisar cuando haya volumen real.
- Segmentación de EDGE limitada a `EDGE_YES` (no `EDGE_NO`) — alcance acotado a propósito en esta iteración.
- `compare_baselines` reentrena un modelo completo por fold para CADA uno de los dos baselines entrenados (el doble de trabajo que el walk-forward de Paso 9 por sí solo) — funcionalmente correcto, no optimizado para volumen alto (misma deuda ya documentada en Paso 9, ahora duplicada).
- Mapeo participante↔YES de un contrato de Kalshi específico sigue sin resolver (Ambigüedad #2/Paso 4) — afecta la interpretación real de cualquier comparación de baselines contra mercados reales.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `cfb8dc09562f198c36cd0c6528be440b79cb15e8` o posterior) y `git status --short`.
- **Pasos 0-10 están todos completos.** El siguiente pendiente en el orden oficial del plan es el **Paso 11** (tenis: `src/features/tennis_features.py` + `src/models/tennis_baseline.py`) — **el usuario autorizó únicamente su revisión contractual, NO su implementación.** No escribas código de Paso 11 sin una autorización explícita nueva y separada.
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real -- `compare_baselines` contra la base real produce hoy un reporte honesto con `n_predictions=0` en los tres baselines (§22).
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así hasta finalizar la Fase 2 completa -- no lo reactives sin autorización explícita nueva.
- **Ningún módulo cerrado fue modificado en el Paso 10** — primera vez desde el Paso 5b. `src/evaluation/reports.py` solo invoca `src/backtesting/*`, `src/models/mlb_baseline.py`/`mlb_elo.py`, `src/signals/edge.py`, `src/uncertainty/quality_score.py`.
- **Contrato de uso importante heredado de `walk_forward_splits`** (Paso 9, sin cambios): el `HistoryRepository` de un fold debe consultarse dentro de la misma iteración del `for`, antes de pedir el siguiente fold.
- **Nota de contrato de `compare_baselines`**: el `fit_fn` del baseline logreg debe recargar el artefacto vía `load_latest_mlb_artifact` antes de devolverlo (a diferencia de Elo, cuyo artefacto es directamente utilizable) — ver docstring de `compare_baselines`.
- Patrón de trabajo ya validado en seis pasos consecutivos (5b, 7, 6, 8, 9, 10): revisión contractual → Design Proposal si hay huecos de especificación → aprobación explícita (ambigüedad por ambigüedad) → implementación → tests → auditoría (incluyendo, en el Paso 10, una auditoría final adicional con verificaciones puntuales por inspección directa de código) → commit separado de código → commit separado de `CONTINUITY.md`. El Paso 11 (tenis) probablemente tenga huecos de especificación aún mayores que los anteriores, dado el bloqueo de SofaScore y la falta de histórico — no saltarse la revisión contractual ni el Design Proposal ahí tampoco.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
