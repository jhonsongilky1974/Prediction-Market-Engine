# Informe Final de Cierre — Fase 2 (Capa Cuantitativa)

**Fecha de cierre formal**: 2026-07-26
**Rama**: `phase-2-dev` (partió de `main`@`c5eb9e77d51eeebb2c6c114ebce1810074b7372b`; `main` intacto)
**Commit de cierre documental**: ver `git log` — este informe se commitea junto con la actualización de cierre de `CONTINUITY.md`
**Documentos de referencia**: `PLAN_PHASE2.md` §18 (estado final de implementación), `CONTINUITY.md` (histórico técnico paso a paso completo)

Este informe resume el cierre de Fase 2. No repite el detalle exhaustivo de cada paso (ambigüedades, decisiones, hallazgos empíricos) — ese detalle vive en `CONTINUITY.md` y permanece disponible ahí. Aquí se documentan los siete puntos pedidos: objetivos, arquitectura final, componentes, cobertura de pruebas, riesgos, alcance excluido, y recomendaciones para Fase 3.

---

## 1. Objetivos alcanzados

El objetivo de Fase 2, definido en `PLAN_PHASE2.md` §3 ("Arquitectura propuesta") y verificado contra los 13 criterios de aceptación de §14, era construir la capa cuantitativa completa: histórico real, features, modelos base con reporte honesto de estado, pricing side-aware, consenso no-vig, incertidumbre heurística, edge/EV, backtesting, comparación de baselines, y el esquema de tipos para señales — sin fabricar ningún valor en ningún punto donde el dato real no existiera.

Los 13 pasos numerados en `PLAN_PHASE2.md` §12 están **completos, testeados, auditados y committeados**:

| # | Paso | Resultado |
|---|---|---|
| 0 | Histórico append-only | `event_snapshots`/`event_results` INSERT-only, con evidencia real acumulada (93 filas) |
| 1 | Feature registry | Documentado, sin funciones huérfanas |
| 2 | Features MLB | Calculadas contra fixtures reales, con test de leakage explícito |
| 3 | Pricing side-aware | `P_market_YES`/`P_market_NO`, 6 casos de §7 cubiertos |
| 4 | Consenso no-vig | Dos pasos (de-vig intra-bookmaker → agregación), degrada a `NOT_CONFIGURED` |
| 5a/5b | Infraestructura + entrenamiento MLB | `model_status` honesto (`MODEL_NOT_TRAINED`/`INSUFFICIENT_HISTORY`/`TRAINED`), nunca una probabilidad fabricada |
| 6 | Elo MLB (Baseline 2) | Segundo baseline independiente de logreg |
| 7 | Incertidumbre | `confidence_method="HEURISTIC_V1"`, explícitamente no calibrado |
| 8 | Edge/EV | `EDGE_YES`/`EDGE_NO` y `EV_*_bruto` por lado, nunca cruzados; `EV_neto` honestamente `None` |
| 9 | Backtesting | Split temporal walk-forward sobre `history_repository` real |
| 10 | Comparación de baselines | Baseline 0 (mercado) vs 1 (logreg) vs 2 (Elo), agnóstico al modelo |
| 11 | Baseline de tenis | `rest_days` + `tournament_round_context`, identidad por `espn_id` |
| 12 | Esquema de señal | `SignalType`/`SignalInputs`, sin lógica de umbral |

**Objetivo explícitamente NO exigido y NO alcanzado, por diseño**: un modelo MLB real entrenado (`model_status=TRAINED`). El histórico acumulado real (`feature_snapshots`/`event_results`=0 filas en `data/engine.db`) todavía no alcanza el umbral de suficiencia — `PLAN_PHASE2.md` §14 declara explícitamente que esto es aceptable y no bloquea el cierre de fase, siempre que el sistema lo reporte honestamente. Lo reporta.

## 2. Arquitectura final

```
src/storage/            Fase 1 + histórico append-only (Paso 0) -- repository.py con extensión aditiva (§18.3)
src/connectors/         mlb.py (extendido aditivamente, Pasos 5a/5b), espn_tennis.py (sin cambios)
src/normalization/      tennis_normalizer.py (extendido aditivamente, Paso 11), resto sin cambios
src/matching/           sin cambios desde Fase 1
src/quality/            sin cambios desde Fase 1
src/features/           mlb_features.py, tennis_features.py -- cómputo puro, sin I/O
src/models/             base.py (PModelOutput/ModelStatus), mlb_baseline.py, mlb_elo.py,
                         tennis_baseline.py (persistencia independiente), registry.py
src/pricing/             market_pricing.py, odds_consensus.py -- side-aware
src/uncertainty/         quality_score.py -- HEURISTIC_V1, componentes auditables
src/signals/             edge.py, expected_value.py, signal_schema.py -- side-aware, sin umbrales
src/backtesting/         dataset.py, splitter.py, metrics.py -- walk-forward real
src/evaluation/          reports.py -- comparación de baselines, agnóstico al modelo
src/pipelines/           mlb_pipeline.py, mlb_results_sync.py, tennis_pipeline.py, tennis_results_sync.py
scripts/                 CLIs manuales de sincronización
```

Principios arquitectónicos mantenidos en los 13 pasos sin excepción: separación estricta features/modelo/pricing/incertidumbre/señales; ningún valor fabricado (siempre `None` honesto cuando el dato no existe); aislamiento temporal sin leakage (`data_cutoff_timestamp` en cada punto relevante); side-awareness estricto (YES/NO, o por lado, nunca cruzados); persistencia de tenis independiente de la de MLB; y — desde el Paso 7 en adelante — todo módulo nuevo precedido de revisión contractual, resolución de ambigüedades con metodología de 6 puntos, Design Proposal, y aprobación explícita antes de escribir código.

## 3. Componentes implementados

- **Histórico**: `event_snapshots`, `event_results`, `feature_snapshots` (esquema listo, 0 filas reales de features/resultados todavía).
- **Modelos**: baseline logístico MLB, Elo MLB, baseline de tenis (dos features), todos con contrato `PModelOutput` común y `model_status` honesto.
- **Pricing**: `P_market_YES`/`P_market_NO` side-aware; consenso no-vig en dos pasos con gate de matching.
- **Incertidumbre**: `QualityScoreOutput` con 7 componentes ponderados, redistribución dinámica de pesos, `HEURISTIC_V1`.
- **Señales**: `EDGE_YES`/`EDGE_NO`, `EV_*_bruto` (puros, deterministas); `SignalType`/`SignalInputs` (tipos, sin clasificación).
- **Backtesting/evaluación**: splitter walk-forward, métricas (Brier, log-loss, accuracy, calibración), comparación Baseline 0/1/2 con segmentación por edge/confianza/liquidez.
- **Automatización**: LaunchAgent de captura horaria (construido, **descargado a propósito** hasta el cierre completo de Fase 2 — ver decisión pendiente en §7 de este informe).

## 4. Cobertura de pruebas

```
.venv/bin/python -m pytest tests/ -q
498 passed, 1 warning (NotOpenSSLWarning de urllib3/LibreSSL, preexistente, no relacionado con el código del proyecto)
```

498 tests (43 archivos unitarios + 5 de integración), 0 regresiones sobre los 90 tests originales de Fase 1. Cada paso de Fase 2 añadió su propia batería con casos nombrados (no genéricos) para cada invariante: leakage, side-awareness, honestidad de `model_status`, no fabricación de valores, tz-awareness, rangos válidos. Regresión completa verificada en verde antes y después de cada commit de código, con caché de bytecode purgada.

## 5. Riesgos conocidos (deuda técnica documentada, no ignorada)

- **Histórico real insuficiente**: `feature_snapshots`/`event_results` en 0 filas reales — ningún modelo (MLB ni tenis) puede alcanzar `TRAINED` hasta que se acumule volumen. Depende directamente de cuánto tiempo corra la captura histórica.
- **Tenis doblemente bloqueado**: SofaScore devuelve 403 (Cloudflare) en este entorno, y el histórico propio es bajo — `tennis_baseline` permanecerá en `INSUFFICIENT_HISTORY` por tiempo indeterminado.
- **The Odds API sin configurar** (`ODDS_API_KEY` ausente) — el consenso no-vig degrada limpio a `NOT_CONFIGURED`, sin fallar, pero no está operativo.
- **Mapeo participante↔YES de un contrato Kalshi específico sin resolver** (Ambigüedad #2, Paso 4) — afecta la interpretación de `EDGE_YES`/`EDGE_NO` en ambos deportes: hoy miden "edge contra la etiqueta nativa del modelo", no garantizadamente contra el YES real de un mercado Kalshi.
- **`EV_neto` permanece `None`** — Kalshi no expone `exchange_fee` en la práctica hoy; la fórmula de incorporación del fee está deliberadamente sin especificar hasta que exista el dato real.
- **Crecimiento de almacenamiento sin límite** (`event_snapshots`/`feature_snapshots` append-only) — sin purgado/compactación todavía, aceptado como deuda consciente hasta que el volumen real lo exija.
- **`DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30`** y **`_MARKET_LIQUIDITY_TARGET=50000.0`** (en `quality_score.py`) son heurísticas de ingeniería provisionales, con respaldo empírico bajo — a revisar cuando exista más volumen real.
- **`tennis_results_sync.py` no distingue POSTPONED/CANCELLED** — no verificado contra datos reales cómo ESPN Tennis los representa; se cuenta honestamente como `not_yet_decided`.
- **Excepción documentada al criterio de aceptación #12** (ver `PLAN_PHASE2.md` §18.3) — tres archivos de Fase 1 (`repository.py`, `connectors/mlb.py`, `normalization/tennis_normalizer.py`) recibieron extensiones aditivas, cada una flageada y aprobada individualmente, pero el texto literal original de §14.12 exigía cero cambios.
- **`src/backtesting/`/`src/evaluation/reports.py` nunca se ejecutaron sobre datos de tenis** — agnósticos al modelo por diseño, disponibles sin cambios cuando se decida ejercitarlos.

## 6. Trabajo explícitamente fuera de alcance de Fase 2

Confirmado sin cambios respecto a `PLAN_PHASE2.md` §16 ("Qué NO debe construirse todavía"):

- Umbrales ENTER/WATCH/PASS calibrados (lógica de clasificación real) — el Paso 12 solo definió los tipos.
- Ejecución de órdenes real.
- `src/risk/` (gestión de riesgo/posición).
- Modelos complejos sin baseline previamente validado.
- Elo de tenis (solo existe para MLB).
- Park factors / weather no verificados contra una fuente real.
- Superficie de tenis inferida por heurística de texto (prohibido explícitamente).
- `EV_neto` real (depende de `exchange_fee`, no disponible).
- Market context como input directo de `P_model`.
- Entrenar cualquier modelo con muestra por debajo del umbral de suficiencia, solo para "tener un modelo".
- Fase 3 en su totalidad.
- Reactivación del LaunchAgent de captura histórica (permanece descargado a propósito).

## 7. Recomendaciones para una futura Fase 3

En orden de dependencia, no de prioridad de negocio (cada punto depende del anterior o de datos que hoy no existen):

1. **Reactivar y mantener corriendo la captura histórica** (LaunchAgent) el tiempo suficiente para que `feature_snapshots`/`event_results` acumulen volumen real — es el bloqueante de fondo de casi todo lo demás (modelos entrenados, backtesting con datos reales, calibración de incertidumbre). Requiere una decisión explícita nueva, ya que hoy permanece descargado a propósito.
2. **Diseñar la capa de integración participante↔YES** para un contrato de Kalshi específico — resuelve la Ambigüedad #2 pendiente desde el Paso 4, y es prerrequisito para que `EDGE_YES`/`EDGE_NO` signifiquen literalmente "edge contra el YES de un mercado real", no solo "contra la etiqueta nativa del modelo".
3. **Configurar `ODDS_API_KEY`** (The Odds API) para activar el consenso no-vig en producción — hoy la infraestructura existe pero está `NOT_CONFIGURED`.
4. **Solo cuando (1) y (2) tengan datos reales suficientes**: diseñar la lógica de clasificación de umbrales ENTER/WATCH/PASS sobre `SignalInputs` (Paso 12 ya deja el contrato listo para esto) — con la misma metodología institucional usada en toda Fase 2 (revisión contractual → ambigüedades → Design Proposal → aprobación → implementación).
5. **Recalibrar heurísticas provisionales** (`DEFAULT_MIN_TRAINING_SAMPLES_TENNIS`, `_MARKET_LIQUIDITY_TARGET`, pesos de `HEURISTIC_V1`) con evidencia real acumulada, en vez de los valores actuales derivados de una muestra pequeña.
6. **Revisitar el desbloqueo de SofaScore** (o una fuente alternativa) para tenis — mientras siga bloqueado, cualquier mejora al baseline de tenis está limitada a `rest_days`/`tournament_round_context`.
7. **Diseñar la política de purgado/compactación** de `event_snapshots`/`feature_snapshots` cuando el volumen real empiece a ser un problema práctico de almacenamiento — no antes, para no resolver un problema hipotético.

Ninguna de estas recomendaciones está autorizada para implementarse todavía — quedan como insumo para cuando el usuario decida abrir formalmente una Fase 3, con su propio plan técnico revisado y aprobado, siguiendo el mismo proceso institucional usado en Fase 2.
