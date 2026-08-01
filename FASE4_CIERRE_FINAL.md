# Informe Final de Cierre — Fase 4

**Fase 4 queda declarada oficialmente cerrada (2026-08-01).** Todo el
alcance de `FASE4_EXECUTION_PLAN.md` (Revisión 2, aprobada) está
implementado, testeado (1002 tests, 0 regresiones) y committeado. Las
3 deudas técnicas identificadas durante la fase (D-3, entrenamiento de
MLB, calibración real) quedan documentadas explícitamente como no
resueltas, bloqueadas por factores verificables, sin fecha — no se
fabricó ningún resultado para cerrar la fase artificialmente. Ver
`CONTINUITY.md` §0.21–§0.27 para el registro completo, paso a paso.

## 1. Qué se construyó (100% del plan aprobado)

| Componente | Estado |
|---|---|
| D-4A: backfill puntual de `event_results` | Cerrado — `event_results` 0 → 295 |
| D-4B: sincronización continua (`scripts/sync_results.py` + LaunchAgent diario 03:30) | Cerrado, verificado con `launchctl kickstart` real |
| Orquestador (`src/orchestration/`: `SportAdapter`, `signal_builder`, `confidence_profile_builder`, `decision_pipeline`) | Cerrado, wireado en `run_e2e.py` |
| GATE-0 + Coverage Gate (`src/evaluation/gate_report.py`) | Cerrado, incluye fix del falso positivo de `GATE-0[mlb_elo]` |
| Auditoría de calidad de labels (`src/evaluation/label_quality_audit.py`) | Cerrado, sin anomalías reales encontradas |
| Primer modelo real entrenado (tenis, `tennis_baseline_logreg_v1_20260801T184245Z`) | Cerrado — incluye fix de fuga de datos en `split_dataset_temporally` (ambos deportes) |
| Calibración real (Platt scaling, tenis) | Cerrado — **implementada y NO desplegada** (ver §3) |

Decisiones de alcance respetadas sin excepción: ningún trabajo de
`src/risk/` ni ejecución automática (Principio 21), `v2.0-baseline`
intacto (`2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df`).

## 2. Qué está listo para producción hoy

- **Tres LaunchAgents activos de forma permanente**: `run-e2e-historical`
  (horaria), `data-maintenance` (diaria 03:00), `sync-results` (diaria
  03:30) — captura, orquestación y sincronización de resultados
  corriendo sin intervención manual.
- **El orquestador produce `Opportunity`/`OpportunityEvaluation` reales**
  sobre `data/engine.db` de producción, confirmado por SQL directo en
  cada paso de la fase.
- **Tenis tiene un modelo base real entrenado** (`p_model` con valores
  reales por primera vez en el proyecto) — MLB sigue en
  `MODEL_NOT_TRAINED`/`INSUFFICIENT_HISTORY`, honesto, no un fallo.
- **`build_signal_inputs` ahora consume `CalibrationOutput` correctamente**
  cuando existe un calibrador emparejado — hueco real corregido contra
  el propio invariante de `CONTRACTS_FASE3.md` §2, verificado con test.
- **`GATE-0`/Coverage Gate/auditoría de labels son chequeos repetibles**,
  ejecutables en cualquier momento vía `scripts/check_training_gates.py`
  sin tocar `data/engine.db`.

## 3. Qué NO está listo para producción — deuda técnica documentada, sin fecha

| Deuda | Depende de | Estado verificado hoy (2026-08-01) |
|---|---|---|
| **D-3**: `net_ev_status` siempre `UNKNOWN` | Verificación primaria de la fórmula de fees de Kalshi | **BLOQUEADO** — 3er intento de `WebFetch` a `kalshi.com/docs/kalshi-fee-schedule.pdf`/`/docs/fees`, HTTP 429 en ambos, mismo resultado que en Fase 3 |
| **Entrenamiento de MLB** (clasificador y Elo) | Volumen real de `event_results` de MLB | **BLOQUEADO** — `mlb_classifier` 87/300 muestras, `mlb_elo` 41/50 juegos elegibles (`build_mlb_elo_game_sequence`, no conteo crudo), verificado vía `check_training_gates.py` |
| **Calibración real de tenis (Platt)** | Volumen de validación suficiente para que calibrar mejore el modelo | **IMPLEMENTADA, NO DESPLEGADA** — evidencia real (`GroupKFold` OOF, 120 muestras/24 eventos): `ece` calibrado 0.137 > crudo 0.068, criterio de aceptación no cumplido; infraestructura lista pero inactiva (`CALIBRATION_SPEC.md`, `CONTINUITY.md` §0.27) |

Ninguna de las tres bloquea funcionalmente el pipeline de decisión —
`ENTER` permanece estructuralmente inalcanzable mientras D-3 esté
abierto (por diseño, `enter_global_threshold` exige `ev_neto_strength`
no-`None`), y `WATCH`/`PASS` operan con el modelo crudo de tenis
(razonablemente calibrado por sí mismo, `ece=0.068`) y sin modelo de
MLB.

## 4. Plan recomendado para el futuro (no una fase aprobada)

1. **D-3**: reintentar la verificación primaria de Kalshi periódicamente, o que el usuario provea el contenido verificado del PDF oficial.
2. **MLB**: dejar acumular histórico real (los 3 LaunchAgents ya lo hacen orgánicamente) hasta alcanzar los umbrales; solo entonces evaluar si vale la pena entrenar.
3. **Calibración de tenis**: reconsiderar únicamente si el volumen de validación crece sustancialmente (sin umbral numérico fijado hoy, para no inventar uno sin evidencia).
4. Backtesting histórico real, Shadow Mode real, paper tracking real — quedan exactamente donde los dejó el cierre de Fase 3, sin nuevo trabajo en Fase 4.

**Explícitamente fuera de alcance, sin cambios**: cualquier forma de
ejecución automática o `src/risk/` (Principio 21).

## 5. Estado del repositorio al cierre

- **1002 tests pasando, 0 fallando** (`tests/unit` + `tests/integration`).
- **`v2.0-baseline`** (Fase 2) intacto: `2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df`.
- **Último commit de Fase 4**: `233fc65` (rama `phase-2-dev`).
- **`data/models/`**: contiene el primer modelo base real de tenis y su
  calibrador Platt (evidencia, gitignored, no versionado) — ningún
  artefacto de MLB.
- **Tres LaunchAgents activos de forma permanente** (§2).
