# DOCUMENTO MAESTRO DE CONTINUIDAD — Prediction-Market-Engine (Fase 2)

Generado: 2026-07-23. Actualizado: 2026-07-24 (cierre de la subfase de
automatización 0c/0d y del Paso 5a). **Actualizado de nuevo: 2026-07-26
(cierre del Paso 5b, Bloques 1-5).** Propósito: única fuente de verdad
para continuar este proyecto en una conversación nueva, sin acceso al
historial de chat. Todo lo aquí escrito fue verificado contra el estado
real del repositorio en el momento de cada actualización (comandos git,
lectura de archivos, ejecución de tests, inspección directa de
`data/engine.db`) — no reconstruido de memoria.

---

## 1. Estado actual del repositorio

Working tree limpio salvo este mismo archivo en curso de actualización
(`git status --short` → solo `CONTINUITY.md` como untracked/modified
hasta que se commitee por separado, según §2 de la instrucción vigente).

## 2. Rama activa

`phase-2-dev` — creada desde el commit baseline de Fase 1
(`c5eb9e77d51eeebb2c6c114ebce1810074b7372b`). `main` permanece exactamente
en ese mismo commit, sin cambios. Ningún merge, ningún commit directo
sobre `main`.

## 3. Último commit completo de código (hash)

```
8a155776b2a1bb9e4811f97886987b0c889b2269
```
Mensaje: `Phase 2 Step 5b, Blocks 1-5: feature_snapshots/event_results wiring + real training pipeline`

(Este mismo archivo `CONTINUITY.md` se commitea por separado inmediatamente
después, en un commit propio que no toca código — ver §13, punto 23.)

## 4. Último paso completamente terminado

**Paso 5b (Bloques 1-5) — COMPLETO, AUDITADO Y COMMITTEADO.** Conecta
`feature_snapshots` y `event_results` a flujos reales (huecos que el
Paso 5a había dejado honestamente documentados como bloqueantes) e
implementa el training pipeline real con split temporal, métricas y
`class_weight="balanced"`.

No se ha iniciado ningún trabajo de un eventual "Paso 6" — y, de hecho,
existe una ambigüedad de nombrado sin resolver sobre qué es exactamente
"Paso 6" que debe aclararse ANTES de cualquier revisión contractual (ver
nota en la instrucción vigente / próximo informe de preimplementación).

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
| 11 | `8a155776b2a1bb9e4811f97886987b0c889b2269` | 2026-07-26 | Phase 2 Step 5b, Blocks 1-5: feature_snapshots/event_results wiring + real training pipeline | phase-2-dev (HEAD actual) |

## 6. Arquitectura actual (real, no solo planeada)

```
src/features/                                          [Fase 2]
  registry.py              CONSTRUIDO (Paso 1)
  mlb_features.py           CONSTRUIDO (Paso 2)
                             persist_mlb_feature_snapshot AHORA SÍ se invoca
                             desde mlb_pipeline.py (Paso 5b, Bloque 2)
  tennis_features.py        PENDIENTE (Paso 11)

src/models/                                             [Fase 2 -- Paso 5a+5b COMPLETOS]
  base.py                   CONSTRUIDO -- ModelStatus, PModelOutput (contrato de salida)
  mlb_baseline.py            CONSTRUIDO -- dataset builder, split temporal
                             (split_dataset_temporally, cronológico), vectorización,
                             training pipeline (scikit-learn, class_weight="balanced",
                             métricas accuracy/log_loss/brier_score sobre validación),
                             inference contract
  registry.py                CONSTRUIDO -- model_version -> artefacto (joblib+json,
                             incluye métricas) o ausente
  tennis_baseline.py         NO EXISTE (Paso 11)

src/pricing/                                            [Fase 2]
  market_pricing.py         CONSTRUIDO (Paso 3)
  no_vig.py                  CONSTRUIDO (Paso 4)
  odds_consensus.py          CONSTRUIDO (Paso 4)

src/uncertainty/                                        [Fase 2 -- PENDIENTE]
  quality_score.py           NO EXISTE -- ver nota de ambigüedad de nombrado en §4/§13

src/signals/                                            [Fase 2 -- PENDIENTE COMPLETO]
  edge.py / expected_value.py / signal_schema.py   NO EXISTEN

src/storage/                                            [Fase 1 + Fase 2]
  repository.py              FASE 1 + busy_timeout=30s explícito
  history_repository.py      Paso 0a/0b + get_all_feature_snapshots()/get_all_event_results()
                              (usados por el dataset builder, sin cambios en esta subfase)

src/pipelines/                                          [Fase 1 + wiring Fase 2]
  mlb_pipeline.py             AMPLIADO (Paso 5b, Bloque 2): además de
                               event_snapshot, ahora TAMBIÉN llama a
                               persist_mlb_feature_snapshot (fetch_features=True
                               por defecto). bullpen_era_recent deliberadamente
                               deshabilitado (reliever_game_logs vacío).
                               opponent_dominant_hand y key_player_ids también
                               None/vacío -- sin convención definida, honesto.
  mlb_results_sync.py         NUEVO (Paso 5b, Bloque 3): sync_mlb_event_results(),
                               reutiliza get_schedule() (sin endpoint nuevo),
                               idempotente a nivel de llamador.
  tennis_pipeline.py          Sin cambios en esta subfase.

src/connectors/mlb.py                                   AMPLIADO (Paso 5b, Bloque 1):
  + get_person_handedness_splits(person_id)
  + get_injured_list_roster(team_id)
  + get_team_stats(team_id)
  (get_roster/get_person_stats existentes, sin tocar)

src/backtesting/                                        [Fase 2 -- PENDIENTE]
  dataset.py / splitter.py / metrics.py    NO EXISTEN -- pero split_dataset_temporally
                              en mlb_baseline.py ya es la fuente de verdad que
                              este futuro paso debería reutilizar, no duplicar.

src/evaluation/                                         [Fase 2 -- PENDIENTE]
  reports.py                 NO EXISTE

scripts/
  run_e2e.py                  Sin cambios en esta subfase.
  pipeline_lock.py             Sin cambios en esta subfase.
  sync_mlb_results.py          NUEVO (Paso 5b, Bloque 3) -- CLI manual, sin automatizar.
  train_mlb_model.py           NUEVO (Paso 5b, Bloque 5) -- CLI manual, sin lock
                               (solo lee HistoryRepository, escribe artefactos
                               con nombre único en data/models/).
  launchd/*.plist              Sin cambios -- ver §17, LaunchAgent DESCARGADO.
```

Módulos de Fase 1 sin cambios de lógica interna (solo wiring aditivo
donde aplica, verificado con `git diff` contra el commit baseline):
`src/normalization/`, `src/matching/`, `src/quality/`, `src/models/schemas.py`.
`src/connectors/mlb.py` recibió 3 métodos nuevos aditivos (Bloque 1) --
los métodos ya existentes no se tocaron.

## 7. Árbol de directorios (delta desde la última actualización, 2026-07-24)

Nuevo desde entonces:
```
scripts/sync_mlb_results.py                     [NUEVO]
scripts/train_mlb_model.py                      [NUEVO]
src/pipelines/mlb_results_sync.py                [NUEVO]
tests/unit/test_mlb_connector.py                 [NUEVO]
tests/unit/test_mlb_pipeline_feature_wiring.py   [NUEVO]
tests/unit/test_mlb_results_sync.py              [NUEVO]
tests/unit/test_train_mlb_model_script.py        [NUEVO]
CONTINUITY.md                                    [este archivo, ahora versionado]
```
Modificados (sin archivos nuevos más allá de los listados arriba):
`src/connectors/mlb.py`, `src/models/mlb_baseline.py`, `src/models/registry.py`,
`src/pipelines/mlb_pipeline.py`, `tests/integration/test_e2e_real.py`,
`tests/unit/test_mlb_baseline.py`, `tests/unit/test_pipeline_history_wiring.py`,
`tests/unit/test_run_e2e_modes.py`.

## 8. Responsabilidad de los módulos nuevos/ampliados en esta subfase

- **`src/connectors/mlb.py`** (Bloque 1): `get_person_handedness_splits`/`get_injured_list_roster`/`get_team_stats`, aditivos, verificados contra la API real antes de usarse.
- **`src/pipelines/mlb_pipeline.py`** (Bloque 2): `_fetch_mlb_feature_inputs()` construye `MlbFeatureInputs` por juego; `run_mlb_pipeline` gana `fetch_features: bool = True`, gateado también por `history_repository is not None`. Bug real encontrado y corregido durante el desarrollo: el `captured_at` del stat de pitcher reutilizado y el `data_cutoff_timestamp` no pueden ser el mismo objeto/valor (violaría la desigualdad estricta de `RawDataPoint.usable()`) -- se capturan en dos momentos distintos del bucle por diseño.
- **`src/pipelines/mlb_results_sync.py`** (Bloque 3): `sync_mlb_event_results()` -- descubrimiento clave: el propio payload de `get_schedule()` ya incluye `teams.{away,home}.isWinner`/`score` para juegos `Final`, verificado en vivo -- no hizo falta ningún endpoint nuevo. Mapea `Final`+`isWinner``→PARTICIPANT_A_WON/B_WON`, `Postponed`/`Cancelled` tal cual, omite (nunca fabrica) resultados ambiguos o no decididos. Idempotente a nivel de llamador (`get_results_for_event` antes de insertar) -- `HistoryRepository.save_event_result` en sí sigue sin deduplicar nada, sin cambios en su contrato.
- **`src/models/mlb_baseline.py`** (Bloque 4): `split_dataset_temporally()` -- cronológico, nunca aleatorio, validación siempre la porción más reciente; reutiliza `build_mlb_training_dataset` como única fuente de verdad (pensado para que el futuro Paso de backtesting construya su walk-forward encima sin duplicar lógica). `train_mlb_baseline_model()` ahora entrena solo con train, evalúa `accuracy`/`log_loss`/`brier_score` solo sobre validation, usa `class_weight="balanced"`. El umbral `min_samples` se sigue evaluando sobre el dataset COMPLETO, antes de dividir. Calibración de probabilidades deliberadamente diferida.
- **`src/models/registry.py`**: metadata ampliada con los campos de split/métricas; carga hacia atrás compatible (`.get(..., default)`) con artefactos guardados antes de este bloque.
- **`scripts/sync_mlb_results.py`** / **`scripts/train_mlb_model.py`**: CLIs manuales, sin conectar a ninguna automatización, sin lock propio (justificado explícitamente en cada docstring).

## 9. Invariantes del sistema — se mantienen todos los de la versión anterior, más:

- El split train/validation es siempre cronológico (`data_cutoff_timestamp` ascendente) -- nunca `random.shuffle` ni equivalente. Verificado por test con orden de inserción deliberadamente desordenado.
- Las métricas de entrenamiento (`accuracy`/`log_loss`/`brier_score`) se calculan EXCLUSIVAMENTE sobre la porción de validación, nunca sobre training -- para no reportar una cifra optimista de forma engañosa.
- `event_results` mapeado desde `get_schedule()` nunca fabrica un ganador: si `isWinner` es ambiguo (ambos `True`, ambos `False`, o ausente) para un juego `Final`, se omite explícitamente, no se adivina.
- Un segundo `sync_mlb_event_results()` sobre el mismo juego ya concluido no duplica la fila (idempotencia de llamador), sin que `HistoryRepository` en sí deduplique nada.

## 10. Reglas que nunca deben romperse

Sin cambios respecto a la versión anterior. Confirmado de nuevo en esta subfase: ninguna automatización nueva conectada (`sync_mlb_results.py`/`train_mlb_model.py` son manuales); ninguna dependencia nueva añadida (sigue siendo solo `scikit-learn`, ya aprobado en 5a).

## 11. Decisiones arquitectónicas tomadas durante el Paso 5b (Bloques 1-5)

- **Bloque 1**: 3 métodos nuevos en `MlbConnector`, ninguno modifica los existentes. `pitcher_game_log` no necesitó método nuevo (`get_person_stats` ya soportaba `stats_type="gameLog"`).
- **Bloque 2**: `bullpen_era_recent` deliberadamente deshabilitado por decisión explícita del usuario (costo de ~20+ llamadas extra por equipo/juego) -- preparado, no implementado. `opponent_dominant_hand`/`key_player_ids` sin convención definida por el plan -- se dejan `None`/vacío en vez de inventar una definición no respaldada.
- **Bloque 3**: `event_results` se alimenta reutilizando `get_schedule()` mirando hacia el pasado -- ningún endpoint nuevo. Ventana de lookback por defecto: 3 días (hoy + 2 anteriores).
- **Bloque 4**: split simple train/validation (no walk-forward completo, eso es un futuro paso de backtesting) pero construido para ser la base de ese walk-forward, no una implementación separada.
- **Bloque 5**: sin lock en `train_mlb_model.py` -- solo lee `HistoryRepository`, escribe artefactos con nombre único (timestamp en `model_version`), sin riesgo de colisión de escritura real.
- **Incidente de automatización durante el desarrollo**: el LaunchAgent (autorizado en la subfase anterior) se disparó por sí solo durante el Bloque 2, en producción real, usando el working tree en ese instante (`runs=1`, `exit 0`, sin daño). Se descargó (`launchctl bootout`) y permanece descargado a petición explícita del usuario -- ver §17.

## 12. Ambigüedades encontradas y resueltas (acumulado completo)

Sin ambigüedades nuevas de tipo "A/B/C" en esta subfase (las decisiones de los Bloques 1-5 fueron autorizadas explícitamente bloque por bloque antes de programar, no encontradas a mitad de implementación). Las ambigüedades previas (Paso 3 EDGE, Paso 4 YES/NO, Paso 5a A/B/C) siguen documentadas sin cambios -- ver versión anterior de este documento / commits correspondientes.

**Pendiente de resolver, señalada al cierre de esta actualización**: existe una discrepancia de nombrado entre lo que el usuario llamó "Paso 6" en la instrucción vigente y el contenido real que describió (que coincide textualmente con los componentes de §9 "Diseño de incertidumbre/confianza" de `PLAN_PHASE2.md`, que es el **Paso 7** en el orden de ejecución de §12 del plan -- "Paso 6" en ese mismo orden es "Elo simple MLB (Baseline 2)", algo completamente distinto). Esta discrepancia se reporta en el informe de preimplementación correspondiente, no se resuelve unilateralmente aquí.

## 13. Decisiones aprobadas explícitamente por el usuario (cronológico, continuación desde el punto 22)

23. Aprobación del informe post-commit del Paso 5a + instrucción de continuar con el informe de preimplementación del Paso 5b (Bloques 1-5), sin programar hasta confirmar el plan.
24. Confirmación del plan de 5 bloques propuesto, con un ajuste explícito: Bloque 2 debe dejar `bullpen_era_recent` deshabilitado (no implementar `reliever_game_logs` todavía).
25. Autorización de continuar bloque a bloque "sin pausas salvo ambigüedad material o problema real" -- patrón seguido exactamente: tests + regresión completa al final de cada bloque, sin commit intermedio.
26. Ante el hallazgo del LaunchAgent disparado en producción durante el desarrollo: autorización explícita de la Opción 2 (descargarlo temporalmente con `launchctl bootout`) mientras se terminan los Bloques 3-5, con instrucción de documentar después cómo reactivarlo.
27. Aprobación de la auditoría final de los Bloques 1-5 + autorización de commit (`8a15577`).
28. Instrucción de NO reactivar el LaunchAgent todavía -- debe permanecer descargado durante desarrollo activo.
29. Instrucción actual: actualizar este documento (commit separado, solo este archivo) + iniciar revisión contractual de solo lectura de un "Paso 6" cuyo nombrado necesita aclararse primero (ver §12) antes de programar nada, con informe de preimplementación exhaustivo y autorización explícita pendiente antes de escribir código.

## 14. Estado exacto de todos los tests (verificado en el cierre de esta subfase)

```
.venv/bin/python -m pytest tests/ -q
313 passed, 1 warning in ~16-17s
```
El único warning sigue siendo `NotOpenSSLWarning` de `urllib3`/LibreSSL, preexistente, no relacionado. 22 tests nuevos en esta subfase (291 → 313): `test_mlb_connector.py` (5), `test_mlb_pipeline_feature_wiring.py` (2), `test_mlb_results_sync.py` (8), ampliaciones de `test_mlb_baseline.py` (+5: split temporal + métricas + class_weight + umbral pre-split), `test_train_mlb_model_script.py` (2), más los ajustes de compatibilidad en `test_pipeline_history_wiring.py`/`test_run_e2e_modes.py` (sin tests nuevos, solo mocks añadidos).

## 15. Número total de tests existentes

**313** (verificado con `pytest --collect-only`). Cero tests de pasos anteriores rotos o reducidos.

## 16. Estado de la regresión completa

Verde, sin excepciones, verificado en el cierre de esta subfase y de nuevo en la verificación post-commit. Comando exacto: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).

## 17. Dependencias actuales

Sin cambios respecto a la versión anterior -- ninguna dependencia nueva en el Paso 5b:
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
| 5b | `feature_snapshots`/`event_results` wiring + training pipeline real | ✅ **COMPLETO** (este documento) |
| 6 | Elo simple MLB (Baseline 2) | Pendiente -- **ver nota de ambigüedad §12/§4**: no confundir con el contenido de incertidumbre/confianza, que es el Paso 7 |
| 7 | `src/uncertainty/quality_score.py` (§9: data_completeness, match_confidence_gap, missing_critical, bookmaker_dispersion, sample_size, market_liquidity, freshness) | Pendiente |
| 8 | `src/signals/edge.py` + `expected_value.py` | Pendiente |
| 9 | `src/backtesting/` | Pendiente |
| 10 | `src/evaluation/reports.py` | Pendiente |
| 11 | Tenis (features + baseline) | Pendiente |
| 12 | `src/signals/signal_schema.py` | Pendiente |

## 21. Estado de la automatización (LaunchAgent) — actualizado

- **DESCARGADO** (`launchctl bootout`), confirmado sin cargar. Permanece así por instrucción explícita del usuario mientras continúe el desarrollo activo.
- Última vez que corrió: una sola vez, durante el Bloque 2 de esta subfase, disparado por su propio `StartInterval=3600` mientras el working tree tenía cambios en curso (`runs=1`, `exit code 0`, sin crash). Capturó 15 juegos MLB + 78 partidos de tenis reales, honestamente, con el código que hubiera en el working tree en ese instante -- no con el código final de los Bloques 1-5 (por eso `feature_snapshots`/`event_results` en `data/engine.db` siguen en 0, ver §22).
- Para reactivarlo: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.prediction-market-engine.run-e2e-historical.plist`
- Verificar estado: `launchctl print gui/$(id -u)/local.prediction-market-engine.run-e2e-historical`
- Volver a descargar si hiciera falta: `launchctl bootout gui/$(id -u)/local.prediction-market-engine.run-e2e-historical`
- **Riesgo aprendido, sin resolver todavía**: mientras apunte al working tree real, cualquier sesión de desarrollo con cambios sin commitear corre el mismo riesgo de que se dispare a mitad de una edición. Vale la pena decidir en algún momento si debe quedar descargado por defecto durante desarrollo activo, de forma más permanente que esta pausa puntual.

## 22. Estado real de `data/engine.db` (verificado en el cierre de esta subfase)

```
event_snapshots     -> 93
feature_snapshots   -> 0
event_results       -> 0
normalized_records  -> 94
```
`feature_snapshots`/`event_results` siguen en 0 pese a que el Bloque 2/3 ya conectaron la tubería real -- porque la única ejecución real ocurrida hasta ahora (el disparo accidental del LaunchAgent, ver §21) sucedió con código anterior a que esa tubería quedara completa. **La próxima vez que se ejecute `scripts/run_e2e.py --mode historical` (manualmente, o al reactivar el LaunchAgent) con el código ya committeado, `feature_snapshots` debería empezar a poblarse de verdad; `event_results` requiere además una corrida de `scripts/sync_mlb_results.py`, que sigue sin haberse ejecutado ni una vez contra la base real.**

## 23. Pendientes técnicos (deuda documentada, acumulado)

Todos los de la versión anterior de este documento salvo los dos ya resueltos en esta subfase (conectar `persist_mlb_feature_snapshot` a un flujo real; mecanismo de alimentación de `event_results`), más:
- `feature_snapshots`/`event_results` reales en `data/engine.db` siguen en 0 -- pendiente de una primera ejecución real con el código ya committeado (ver §22), no de más código.
- WTA no cubierto por el LaunchAgent actual.
- Sin deduplicación, retención, purga ni compresión de `event_snapshots`.
- `bullpen_era_recent` deshabilitado (Bloque 2, decisión explícita) -- pendiente de una mejora futura si se decide implementar `reliever_game_logs`.
- `opponent_dominant_hand`/`key_player_ids` sin convención definida -- features `pitcher_vs_opponent_handedness_ops`/`il_flag_key_players` seguirán `None` hasta que se decida.
- Mapeo participante↔YES de un contrato de Kalshi específico sigue sin resolver (Ambigüedad #2 del Paso 4 / Ambigüedad C del Paso 5a).
- Calibración de probabilidades diferida al Paso 9/10, como fue autorizado.
- **Ambigüedad de nombrado "Paso 6" sin resolver** (ver §12) -- primer punto a aclarar antes de cualquier código nuevo.

## 24. Todo lo que un chat nuevo debe saber antes de escribir una sola línea de código

- Verifica tú mismo el estado real antes de asumir nada de este documento -- `git rev-parse HEAD` (debe ser `8a155776b2a1bb9e4811f97886987b0c889b2269` o posterior) y `git status --short`.
- **`feature_snapshots`/`event_results` YA tienen tubería de alimentación real (Bloques 2/3), pero `data/engine.db` real sigue mostrando 0 en ambas** -- no asumas que hay datos de entrenamiento reales sin verificarlo tú mismo (§22).
- El LaunchAgent está DESCARGADO a propósito -- no lo reactives sin autorización explícita del usuario.
- Antes de tocar cualquier "Paso 6": confirma con el usuario si se refiere al Paso 6 real de `PLAN_PHASE2.md` §12 (Elo MLB) o al Paso 7 (incertidumbre/`quality_score.py`) -- hay una discrepancia de nombrado sin resolver, ver §12.
- Sigue el patrón de trabajo ya validado: revisión contractual antes de programar, ambigüedades reportadas (nunca resueltas por inferencia silenciosa), aprobación explícita antes de cada acción irreversible, auditoría antes de cierre, commit solo con autorización separada.
- Para correr tests: `.venv/bin/python -m pytest tests/ -q` (nunca `python3` del sistema).
- `p_model_yes` (cuando exista) es `P(participant_a gana)`, no el lado YES de un contrato de Kalshi específico.
