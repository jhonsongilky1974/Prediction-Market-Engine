# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). Actualizado: 2026-07-26 (cierre del Paso 7 —
Quality Score / Incertidumbre). Actualizado: 2026-07-26 (cierre del
Paso 6 — Elo simple MLB / Baseline 2). **Actualizado de nuevo: 2026-07-26
(cierre del Paso 8 — EDGE_YES/EDGE_NO + Expected Value).** Propósito:
única fuente de verdad para continuar este proyecto en una conversación
nueva, sin acceso al historial de chat. Todo lo aquí escrito fue
verificado contra el estado real del repositorio en el momento de cada
actualización (comandos git, lectura de archivos, ejecución de tests,
inspección directa de `data/engine.db`) — no reconstruido de memoria.

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
038bff0fae343d230cef778b263b4b2f4e794b14
```
Mensaje: `Phase 2 Step 8: EDGE_YES/EDGE_NO + Expected Value (bruto)`

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado en los cierres anteriores).

## 4. Último paso completamente terminado

**Paso 8 (`src/signals/edge.py` + `expected_value.py`) — COMPLETO,
AUDITADO Y COMMITTEADO.** Implementa `EDGE_YES`/`EDGE_NO`/`EV_*_bruto`
según `PLAN_PHASE2.md` §7, precedido de un Design Proposal explícito
revisado y aprobado antes de escribir código. A diferencia de los Pasos 6
y 7, este paso venía con fórmulas y 6 escenarios de test ya definidos
literalmente en el plan — mucho menos ambiguo, sin necesidad de proponer
parámetros heurísticos nuevos.

Con este cierre: **Pasos 0, 1, 2, 3, 4, 5a, 5b, 6, 7 y 8 están todos
completos.** El siguiente pendiente en el orden oficial es el **Paso 9**
(`src/backtesting/`).

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
| 17 | `038bff0fae343d230cef778b263b4b2f4e794b14` | 2026-07-26 | Phase 2 Step 8: EDGE_YES/EDGE_NO + Expected Value (bruto) | phase-2-dev (HEAD actual) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/                                          [Fase 2]  Sin cambios desde el Paso 5b
src/models/                                             [Fase 2 -- 5a/5b/6 COMPLETOS]  Sin cambios en esta actualización
src/pricing/                                            [Fase 2]  Sin cambios
src/uncertainty/                                        [Fase 2 -- Paso 7 COMPLETO]  Sin cambios

src/signals/                                            [Fase 2 -- Paso 8 COMPLETO]
  edge.py                    CONSTRUIDO -- compute_edge_yes/compute_edge_no
  expected_value.py          CONSTRUIDO -- compute_ev_yes_bruto/compute_ev_no_bruto,
                             compute_ev_yes_neto/compute_ev_no_neto (siempre None hoy)
  signal_schema.py           NO EXISTE (Paso 12)

src/storage/                                            [Fase 1 + Fase 2]  Sin cambios desde el Paso 6
src/pipelines/                                          [Fase 1 + wiring Fase 2]  Sin cambios desde el Paso 5b
src/connectors/mlb.py                                   Sin cambios desde el Paso 5b (Bloque 1)

src/backtesting/                                        [Fase 2 -- PENDIENTE, siguiente paso]
  NO EXISTE -- split_dataset_temporally (mlb_baseline.py) y el cálculo
  secuencial de mlb_elo.py son fuentes de verdad a reutilizar, no duplicar

src/evaluation/                                         [Fase 2 -- PENDIENTE]
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
src/signals/__init__.py                  [NUEVO]
src/signals/edge.py                      [NUEVO]
src/signals/expected_value.py            [NUEVO]
tests/unit/test_edge.py                  [NUEVO]
tests/unit/test_expected_value.py        [NUEVO]
```
Modificado (sin archivos nuevos más allá de los listados arriba):
`tests/integration/test_e2e_real.py` (+1 test real).

## 8. Responsabilidad de `src/signals/edge.py` y `expected_value.py`

Funciones **100% puras y deterministas** (confirmado explícitamente antes
de implementar, y verificado por test: mismo `PModelOutput` + mismo
`NormalizedRecord` llamado 50 veces produce una única salida) — sin I/O,
sin red, sin estado mutable, sin dependencia del reloj.

```
EDGE_YES = P_model_YES - YES_ASK
EDGE_NO  = (1 - P_model_YES) - NO_ASK
EV_YES_bruto = P_model_YES*(1-YES_ASK) - (1-P_model_YES)*YES_ASK
EV_NO_bruto  = P_model_NO*(1-NO_ASK)   - (1-P_model_NO)*NO_ASK
```

Ambas funciones reciben un `PModelOutput` completo (no un `float` suelto)
+ un `NormalizedRecord`, y reutilizan `market_price_yes`/`market_price_no`
(Paso 3) para el lado de mercado. `EDGE_NO`/`EV_NO_bruto` se calculan de
forma **totalmente independiente** del lado YES — nunca se cruzan ni se
derivan uno del otro (verificado explícitamente: `EDGE_NO ≠ P_model_YES - no_ask`).

`EV_*_neto` permanece `None` mientras `MarketData.exchange_fee` sea
`None` (siempre en la práctica hoy) — la fórmula de incorporación del fee
no está especificada por el plan y **no se inventa**; ambas funciones
lanzan `NotImplementedError` si alguna vez se llaman con `exchange_fee`
ya poblado, dejando explícito que ese camino requiere una decisión futura
separada, no asumida.

**Advertencia de interpretación, documentada de nuevo (mismo hueco de
Ambigüedad #2/Paso 4 y Ambigüedad C/Paso 5a-6)**: `PModelOutput.p_model_yes`
representa hoy `P(participant_a gana)`, no necesariamente el lado YES de
un contrato de Kalshi específico — la capa de integración
participante↔YES sigue sin existir. `edge.py`/`expected_value.py` aplican
la fórmula de §7 literalmente, sin intentar resolver ese mapeo.

Cubre los **6 escenarios obligatorios de §7** con aserciones exactas de
`EDGE_YES`/`EDGE_NO` (antes solo probados para `P_market_YES`/`P_market_NO`
en el Paso 3, tal como ese módulo ya anticipaba en su propio docstring).

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- `EDGE_YES`/`EDGE_NO`/`EV_*_bruto` son puros y deterministas — verificado por test dedicado, no solo documentado.
- `EDGE_NO`/`EV_NO_bruto` nunca se derivan de `EDGE_YES`/`EV_YES_bruto` ni viceversa — cada lado con su propia probabilidad y su propio precio.
- `EV_*_neto` nunca fabrica una fórmula de fee no especificada — `None` mientras `exchange_fee` sea `None`, `NotImplementedError` explícito si alguna vez dejara de serlo sin una decisión previa.

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo: ninguna dependencia nueva añadida; ningún módulo ya cerrado modificado (`market_pricing.py`, `base.py`, `schemas.py` ausentes del diff, verificado antes del commit).

## 11. Decisiones arquitectónicas tomadas durante el Paso 8

- **Funciones reciben `PModelOutput` completo, no un `float` suelto** — aprovecha la invariante ya garantizada por `base.py` (`p_model_yes=None` salvo `TRAINED`), sin duplicarla.
- **Sin dataclass envolvente** para el resultado (a diferencia de Pasos 4/5/6/7) — funciones standalone, mismo estilo minimalista que `market_pricing.py` (Paso 3), ya que no hacía falta agrupar varios componentes.
- **`EV_*_neto` implementado como *gate* con `NotImplementedError`** en vez de dejarlo simplemente sin código — decisión explícita para que cualquier intento futuro de usarlo con `exchange_fee` real falle de forma ruidosa y visible, no silenciosamente con un valor incorrecto.
- **Sin wiring a `mlb_pipeline.py`/`tennis_pipeline.py`** — mismo patrón que Pasos 3/4/5a/5b/6/7 (ambos pipelines declaran explícitamente "READ-ONLY. No calcula P_model/EDGE/EV/CONFIDENCE/señales").

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Ninguna ambigüedad nueva de tipo "A/B/C" durante el Paso 8 — el plan ya traía fórmulas y 6 escenarios de test explícitos (§7), a diferencia de los Pasos 6 y 7. La única advertencia recurrente (mapeo participante↔YES) se documentó de nuevo, sin resolverla, consistente con las tres veces anteriores.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 42)

43. Instrucción de iniciar el Paso 8 con el mismo flujo institucional, exigiendo un Design Proposal completo (objetivo, alcance, arquitectura, fórmulas, anti-contaminación P_model/P_market, casos límite, integración, compatibilidad, plan de tests, confirmación de no tocar componentes cerrados) antes de programar.
44. Aprobación del Design Proposal con una única condición: confirmar explícitamente que EDGE/EV serían funciones 100% puras y deterministas antes de proceder — confirmado, sin ajustes al diseño, y se implementó con un test dedicado de determinismo.
45. Aprobación de la auditoría final + autorización de commit (`038bff0`), con instrucción explícita de regresión rápida post-commit y confirmaciones puntuales (working tree, `data/engine.db`, LaunchAgent, número de tests, hash).
46. Instrucción actual: actualizar este documento con el cierre del Paso 8. No avanzar al Paso 9 sin autorización explícita adicional.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
388 passed, 1 warning in ~21-23s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente. 18 tests nuevos en esta actualización (370 → 388): 10 en `test_edge.py` (los 6 escenarios exactos de §7 + `model_status` + determinismo + 2 de integración real con `predict_mlb_elo`/`train_mlb_elo_model` reales) + 7 en `test_expected_value.py` + 1 de integración real (`test_edge_and_ev_compute_honestly_on_real_mlb_pipeline_output`).

## 15. Número total de tests existentes

**388** (verificado con `pytest --collect-only`). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado en el cierre de esta actualización y de nuevo post-commit. Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios — ninguna dependencia nueva en el Paso 8:
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
| 8 | `src/signals/edge.py` + `expected_value.py` | ✅ **COMPLETO** (este documento) |
| 9 | `src/backtesting/` | Pendiente — **siguiente en orden oficial** |
| 10 | `src/evaluation/reports.py` | Pendiente |
| 11 | Tenis (features + baseline) | Pendiente |
| 12 | `src/signals/signal_schema.py` | Pendiente |

## 21. Estado de la automatización (LaunchAgent) — sin cambios

- **DESCARGADO** (`launchctl bootout`), confirmado sin cargar en el cierre de esta actualización.
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
Sin cambios desde la última actualización — el Paso 8 no toca `data/engine.db` en absoluto (funciones puras, sin persistencia). Ambos baselines MLB (regresión logística y Elo) seguirán reportando `INSUFFICIENT_HISTORY`/`MODEL_NOT_TRAINED` hasta una primera ejecución real, y por tanto `EDGE_YES`/`EDGE_NO` seguirán siendo `None` en la práctica hasta ese momento — honesto, no un error.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- `EV_*_neto` sin implementar de verdad (gate con `NotImplementedError`) — pendiente de una decisión futura sobre la fórmula exacta de incorporación de `exchange_fee`/`fee_type`, cuando Kalshi exponga ese dato.
- Mapeo participante↔YES de un contrato de Kalshi específico sigue sin resolver (Ambigüedad #2/Paso 4, Ambigüedad C/Paso 5a-6, señalada de nuevo en Paso 8) — afecta la interpretación real de `EDGE_YES`/`EDGE_NO` contra mercados reales.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `038bff0fae343d230cef778b263b4b2f4e794b14` o posterior) y `git status --short`.
- **Pasos 0-8 están todos completos** (incluyendo 6 y 7, cerrados en orden invertido al numérico por la razón de nombrado ya documentada). El siguiente pendiente en el orden oficial del plan es el **Paso 9** (`src/backtesting/`).
- `feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real -- `EDGE_YES`/`EDGE_NO` seguirán siendo `None` en la práctica hasta una primera ejecución real (§22).
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así hasta finalizar la Fase 2 completa -- no lo reactives sin autorización explícita nueva.
- `src/signals/edge.py`/`expected_value.py` no tocan `market_pricing.py`, `base.py`, `schemas.py` ni ningún módulo de Pasos 0-7 -- solo los importan.
- Patrón de trabajo ya validado en cuatro pasos consecutivos (5b, 7, 6, 8): revisión contractual → Design Proposal si hay huecos de especificación → aprobación explícita → implementación → tests → auditoría → commit separado de código → commit separado de `CONTINUITY.md`. El Paso 9 (backtesting) probablemente también tenga huecos de especificación (walk-forward exacto, métricas) — no saltarse el Design Proposal ahí tampoco.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
