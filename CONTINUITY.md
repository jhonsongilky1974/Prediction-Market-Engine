# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). Actualizado: 2026-07-26 (cierre del
Paso 5b, Bloques 1-5). **Actualizado de nuevo: 2026-07-26 (cierre del
Paso 7 — Quality Score / Incertidumbre).** Propósito: única fuente de
verdad para continuar este proyecto en una conversación nueva, sin acceso
al historial de chat. Todo lo aquí escrito fue verificado contra el
estado real del repositorio en el momento de cada actualización (comandos
git, lectura de archivos, ejecución de tests, inspección directa de
`data/engine.db`) — no reconstruido de memoria.

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
822d4dc9b69652842e3c83dbb3b2b44e38f8cd78
```
Mensaje: `Phase 2 Step 7: uncertainty/confidence quality score (HEURISTIC_V1)`

Este mismo archivo `CONTINUITY.md` se commitea por separado tras esta
actualización (mismo patrón ya usado al cerrar el Paso 5b: un commit
propio, sin tocar código).

## 4. Último paso completamente terminado

**Paso 7 (Quality Score / Incertidumbre) — COMPLETO, AUDITADO Y
COMMITTEADO.** Implementa `src/uncertainty/quality_score.py`
(`confidence_method=HEURISTIC_V1`) según `PLAN_PHASE2.md` §9, precedido
de un Design Proposal explícito revisado y aprobado por el usuario
**antes** de escribir cualquier código (fórmulas, normalización,
estrategia ante componente ausente, pesos iniciales y ejemplos numéricos
completos, todos aprobados primero).

**Nota de nombrado, ya resuelta**: al iniciar este trabajo hubo una
discrepancia real entre "Paso 6" (como lo llamó el usuario) y el
contenido efectivamente descrito, que coincidía textualmente con §9 del
plan — que es el **Paso 7** en el orden de ejecución de §12, no el Paso 6
real (que es "Elo simple MLB / Baseline 2", sin relación). Se reportó
explícitamente, el usuario confirmó que el contenido correspondía al
componente de incertidumbre/confianza, y desde entonces se trata como
**Paso 7** sin ambigüedad. El Paso 6 real (Elo MLB) sigue íntegramente
pendiente, sin iniciar.

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
| 13 | `822d4dc9b69652842e3c83dbb3b2b44e38f8cd78` | 2026-07-26 | Phase 2 Step 7: uncertainty/confidence quality score (HEURISTIC_V1) | phase-2-dev (HEAD actual) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/                                          [Fase 2]
  registry.py              CONSTRUIDO (Paso 1)
  mlb_features.py           CONSTRUIDO (Paso 2, wireado en Paso 5b)
  tennis_features.py        PENDIENTE (Paso 11)

src/models/                                             [Fase 2 -- Paso 5a+5b COMPLETOS]
  base.py / mlb_baseline.py / registry.py    CONSTRUIDOS -- ver actualización anterior
                             de este documento para el detalle completo
  tennis_baseline.py         NO EXISTE (Paso 11)

src/pricing/                                            [Fase 2]
  market_pricing.py / no_vig.py / odds_consensus.py    CONSTRUIDOS (Pasos 3-4)

src/uncertainty/                                        [Fase 2 -- Paso 7 COMPLETO]
  quality_score.py           CONSTRUIDO -- compute_quality_score(), 7 componentes,
                             confidence_method="HEURISTIC_V1", redistribución
                             dinámica de pesos, ver §8/§9 abajo para el detalle exacto

src/signals/                                            [Fase 2 -- PENDIENTE COMPLETO]
  edge.py / expected_value.py / signal_schema.py   NO EXISTEN (Pasos 8/12)

src/storage/                                            [Fase 1 + Fase 2]
  repository.py / history_repository.py    Sin cambios desde el Paso 5b

src/pipelines/                                          [Fase 1 + wiring Fase 2]
  mlb_pipeline.py / mlb_results_sync.py / tennis_pipeline.py    Sin cambios desde el Paso 5b

src/connectors/mlb.py                                   Sin cambios desde el Paso 5b (Bloque 1)

src/backtesting/                                        [Fase 2 -- PENDIENTE]
  NO EXISTE -- split_dataset_temporally (mlb_baseline.py, Paso 5b) ya es la
  fuente de verdad que este futuro paso debería reutilizar

src/evaluation/                                         [Fase 2 -- PENDIENTE]
  reports.py                 NO EXISTE

scripts/                                                Sin cambios desde el Paso 5b
```

Módulos de Fase 1/pasos ya cerrados **sin ningún cambio** en esta
actualización: `src/connectors/`, `src/normalization/`, `src/matching/`,
`src/quality/`, `src/models/schemas.py`, `src/pricing/`, `src/storage/`,
`src/pipelines/`. `quality_score.py` los **importa y reutiliza**
(`NormalizedRecord.data_quality`, `ConsensusNoVigResult`, `CORE_FIELDS`)
pero no modifica ninguno — verificado explícitamente antes del commit
(`git status --short` no mostró nada fuera de los 4 archivos nuevos).

## 7. Árbol de directorios (delta desde la última actualización)

Nuevo en esta actualización:
```
src/uncertainty/__init__.py              [NUEVO]
src/uncertainty/quality_score.py         [NUEVO]
tests/unit/test_quality_score.py         [NUEVO]
```
Modificado (sin archivos nuevos más allá de los listados arriba):
`tests/integration/test_e2e_real.py` (+1 test real: `test_quality_score_computes_on_real_mlb_pipeline_output`).

## 8. Responsabilidad de `src/uncertainty/quality_score.py`

`compute_quality_score(record, consensus=None, now=None, weights=None) -> QualityScoreOutput`.

**7 componentes**, cada uno `Optional[float]` en [0,1] o `None` si no calculable (nunca fabricado):

| Componente | Fórmula | Fuente |
|---|---|---|
| `data_completeness` | reutilizado directo | `record.data_quality.data_completeness_score` (Fase 1) |
| `match_confidence_gap` | `clip((match_confidence - 0.72) / 0.28, 0, 1)` | ancla en `EVENT_NAME_MATCH_MIN_CONFIDENCE` ya existente |
| `missing_critical` | `1 - (core_fields_ausentes / len(CORE_FIELDS))` | `CORE_FIELDS` ya existente (`src/quality/completeness.py`) — único componente que nunca es `None` en la práctica |
| `bookmaker_dispersion` | `clip(1 - dispersion/0.10, 0, 1)` | `ConsensusNoVigResult.dispersion` (Paso 4) |
| `sample_size` | `min(bookmaker_count/5, 1)` | `ConsensusNoVigResult.bookmaker_count` (interpretación aprobada: única "muestra" disponible a nivel de registro) |
| `market_liquidity` | `min(volume_o_open_interest/50000, 1)` | `MarketData.volume` (principal) / `open_interest` (respaldo). **`liquidity` NUNCA se usa** — verificado contra datos reales: siempre 0. Umbral **50,000 marcado explícitamente como PROVISIONAL** en el código (solo 3 observaciones reales disponibles al diseñarlo, rango 5.4K-144K) |
| `freshness` | `clip(1 - age_seconds/3600, 0, 1)` | antigüedad del timestamp más viejo en `record.data_quality.source_timestamps`, mismo patrón que Paso 4 |

**Agregación**: promedio ponderado con **redistribución dinámica** del peso entre los componentes disponibles — `weights` de salida son los pesos ya renormalizados de ESE cálculo específico, no los estáticos de configuración. `confidence=None` solo si el peso total disponible es 0 (caso degenerado).

**Pesos iniciales (`HEURISTIC_V1`, aprobados explícitamente, suman 1.00)**:
`data_completeness=0.18, match_confidence_gap=0.22, missing_critical=0.18, bookmaker_dispersion=0.15, sample_size=0.10, market_liquidity=0.07, freshness=0.10`.

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- `confidence_method` es siempre exactamente `"HEURISTIC_V1"` — nunca se presenta como probabilidad calibrada.
- Ningún componente de `quality_score` se fabrica cuando no es calculable — se excluye y su peso se redistribuye, verificado con test que recalcula el valor esperado de forma independiente.
- `missing_critical` es, por diseño, el único de los 7 componentes que siempre es calculable (depende solo de `missing_fields`, que siempre existe) — garantiza que `confidence` casi nunca sea `None` bajo los pesos por defecto.
- El campo `liquidity` de `MarketData` nunca se usa como base de `market_liquidity` (decisión basada en evidencia real, no en el Design Proposal en abstracto).

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo en esta actualización: ninguna dependencia nueva añadida; ningún módulo de Fase 1/pasos cerrados modificado (solo importado/reutilizado).

## 11. Decisiones arquitectónicas tomadas durante el Paso 7

- **Interpretación de `sample_size`** = `bookmaker_count` — no hay otra fuente de "tamaño de muestra" a nivel de registro individual, decisión explícita del Design Proposal, aprobada.
- **`market_liquidity` basado en `volume`/`open_interest`, nunca en `liquidity`** — decisión respaldada con evidencia real (consulta de solo lectura a los 93 `event_snapshots` ya existentes antes de proponer el umbral).
- **Umbral de `market_liquidity` (50,000) marcado explícitamente como provisional** en el propio código — no se disfrazó de decisión definitiva.
- **Pesos iniciales ajustados por el usuario** respecto a la primera propuesta del Design Proposal (`0.20/0.20/0.15/0.15/0.10/0.10/0.10` → `0.18/0.22/0.18/0.15/0.10/0.07/0.10`), con mayor énfasis relativo en `match_confidence_gap` y `missing_critical`, menor en `market_liquidity` (coherente con ser el umbral menos respaldado).
- **`confidence=None` en vez de `0.0`** en el caso degenerado de peso total cero — consistente con "nunca fabricar", no un valor por defecto arbitrario.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

La discrepancia de nombrado "Paso 6 vs. Paso 7" (documentada en la actualización anterior de este archivo) queda **resuelta**: confirmado por el usuario que el trabajo corresponde al Paso 7 real. Sin ambigüedades nuevas de tipo "A/B/C" durante la implementación de Paso 7 — todas las decisiones de diseño (fórmulas, pesos, umbrales) fueron parte del Design Proposal explícitamente revisado y aprobado antes de escribir código, no encontradas a mitad de implementación.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 29)

30. Confirmación explícita: el trabajo corresponde al Paso 7 (Quality Score/Incertidumbre), no a un "Paso 6" mal nombrado — se trata como Paso 7 desde ese momento.
31. Instrucción de NO implementar fórmulas/pesos todavía — primero un Design Proposal completo (fórmulas de los 7 componentes, normalización, estrategia ante ausencia, pesos iniciales, fórmula de agregación, ejemplos numéricos) para revisión y aprobación previa.
32. Aprobación del Design Proposal con un ajuste explícito de pesos iniciales (ver §11) + autorización de implementación completa (código + tests unitarios + integración) antes de solicitar nueva auditoría.
33. Aprobación del informe técnico de implementación + solicitud de verificación final previa (únicamente `git diff --stat` / `git diff --cached --stat` / `git status --short` + 4 confirmaciones puntuales de alcance).
34. Aprobación de la auditoría final + autorización de commit (`822d4dc`) + instrucción de ejecutar regresión rápida post-commit y entregar hash/mensaje/informe.
35. Instrucción de NO reactivar el LaunchAgent — debe permanecer descargado hasta finalizar la Fase 2 completa (ampliación explícita respecto a la instrucción anterior, que solo cubría "durante desarrollo activo").
36. Instrucción actual: actualizar este documento con el cierre del Paso 7.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta actualización)

```
.venv/bin/python -m pytest tests/ -q
346 passed, 1 warning in ~17s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente, no relacionado. 33 tests nuevos en esta actualización (313 → 346): 32 unitarios (`test_quality_score.py`, cubriendo cada componente por separado, el caso nombrado del plan "`P_model=0.64` con baja completeness ⇒ confidence bajo", redistribución de pesos verificada numéricamente, caso degenerado, y una integración cruzada sintética `normalize_mlb_game`→`compute_consensus_no_vig`→`compute_quality_score`) + 1 de integración real (`test_quality_score_computes_on_real_mlb_pipeline_output`, contra la API real de MLB).

## 15. Número total de tests existentes

**346** (verificado con `pytest --collect-only`). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado en el cierre de esta actualización y de nuevo post-commit. Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios — ninguna dependencia nueva en el Paso 7:
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
| 7 | `src/uncertainty/quality_score.py` | ✅ **COMPLETO** (este documento) |
| 6 | Elo simple MLB (Baseline 2) | Pendiente — sin iniciar, nombre ya sin ambigüedad (ver §4) |
| 8 | `src/signals/edge.py` + `expected_value.py` | Pendiente |
| 9 | `src/backtesting/` | Pendiente |
| 10 | `src/evaluation/reports.py` | Pendiente |
| 11 | Tenis (features + baseline) | Pendiente |
| 12 | `src/signals/signal_schema.py` | Pendiente |

(Orden de la tabla refleja el orden de cierre real, no el orden numérico del plan — Paso 7 se cerró antes que el Paso 6 real, por la razón de nombrado ya documentada en §4/§12.)

## 21. Estado de la automatización (LaunchAgent) — sin cambios operativos, alcance de la pausa ampliado

- **DESCARGADO** (`launchctl bootout`), confirmado sin cargar en el cierre de esta actualización.
- **Alcance de la pausa ampliado explícitamente por el usuario**: debe permanecer descargado **hasta finalizar la Fase 2 completa** (antes la instrucción cubría solo "durante desarrollo activo" de una subfase puntual) — ver §13, punto 35.
- Sigue sin haber corrido más que la única vez ya documentada (Bloque 2 del Paso 5b, `runs=1`, `exit 0`) — ningún dato nuevo se ha acumulado en `data/engine.db` desde entonces.
- Para reactivarlo (NO ejecutar sin autorización explícita, y ahora además sin autorización previa de "fin de Fase 2"): `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.prediction-market-engine.run-e2e-historical.plist`
- Verificar estado: `launchctl print gui/$(id -u)/local.prediction-market-engine.run-e2e-historical`

## 22. Estado real de `data/engine.db` (verificado en el cierre de esta actualización)

```
event_snapshots     -> 93
feature_snapshots   -> 0
event_results       -> 0
normalized_records  -> 94
```
Sin cambios desde la última actualización — nada en el Paso 7 toca `data/engine.db` (ver §6, `quality_score.py` consume estructuras ya en memoria, no lee la base directamente). Sigue pendiente una primera ejecución real (`scripts/run_e2e.py --mode historical` + `scripts/sync_mlb_results.py`) con el código ya committeado para que `feature_snapshots`/`event_results` empiecen a poblarse — bloqueada mientras el LaunchAgent permanezca descargado y nadie ejecute los scripts manualmente.

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento, más:
- Umbral de `market_liquidity` (50,000) en `quality_score.py` — provisional, revisar cuando haya más volumen real capturado (§8).
- Pesos de `quality_score.py` siguen sin calibrar con evidencia (`HEURISTIC_V1` por diseño, no un defecto) — la calibración real es un paso futuro separado, no antes de tener histórico de resultados reales.
- Paso 6 real (Elo MLB) sigue sin iniciar.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento — `git rev-parse HEAD` (debe ser `822d4dc9b69652842e3c83dbb3b2b44e38f8cd78` o posterior) y `git status --short`.
- **`feature_snapshots`/`event_results` siguen en 0 en `data/engine.db` real** — la tubería existe (Paso 5b) pero no se ha ejecutado ni una vez con el código final (§22).
- El LaunchAgent está DESCARGADO a propósito y debe permanecer así **hasta finalizar la Fase 2 completa** — no lo reactives sin autorización explícita nueva del usuario, ni asumas que "terminar un paso más" ya autoriza reactivarlo.
- "Paso 6" y "Paso 7" ya no tienen ambigüedad: Paso 6 = Elo MLB (pendiente, sin iniciar), Paso 7 = Quality Score/Incertidumbre (completo, este documento).
- `quality_score.py` no toca `data/engine.db`, `schemas.py`, `matching`, `pricing`, `storage` ni `pipelines` — solo los importa y reutiliza.
- Sigue el patrón de trabajo ya validado: para pasos con fórmulas/pesos sin especificar en el plan (como fue este Paso 7), un Design Proposal explícito revisado ANTES de programar es el camino ya validado dos veces — no asumas que puedes saltarte esa fase en el próximo paso con huecos similares (p. ej., Paso 8 EDGE/EV o el propio Paso 6 Elo, que también tienen huecos de especificación).
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
