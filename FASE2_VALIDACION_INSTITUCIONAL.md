# Validación Institucional de Fase 2 — Ejecución extremo a extremo sobre mercados reales

**Fecha**: 2026-07-26 (hora real de ejecución de la validación; ver timestamps de los registros ingeridos, tomados de las APIs reales en el momento de la corrida)
**Alcance**: usar exclusivamente código ya existente (ningún módulo nuevo, ninguna función nueva) para correr el motor completo — ingesta, normalización, matching, quality score, mercado, consenso no-vig, modelo, confidence, edge/EV, señal, y verificar si existe una recomendación final — sobre mercados reales de MLB y tenis (ATP).
**Autorización**: instrucción explícita del usuario tras el cierre formal de Fase 2. No se implementó ninguna funcionalidad nueva; no se avanzó ningún "Paso 13".

---

## 1. Método

Se escribió un script de orquestación puramente diagnóstico (vive fuera del repositorio, en el scratchpad de esta sesión — no es un entregable del producto) que **importa y llama, en secuencia, funciones ya existentes** de `src/pipelines/mlb_pipeline.py`, `src/pipelines/tennis_pipeline.py`, `src/pricing/market_pricing.py`, `src/pricing/odds_consensus.py`, `src/uncertainty/quality_score.py`, `src/models/mlb_baseline.py`, `src/models/tennis_baseline.py`, `src/models/registry.py`, `src/signals/edge.py`, `src/signals/expected_value.py` y `src/signals/signal_schema.py`. Ninguna línea de lógica de negocio nueva — el script solo encadena llamadas y produce un log legible.

**Aislamiento deliberado**: `Repository`/`HistoryRepository` de esta validación apuntan a bases de datos temporales (fuera de `data/engine.db` real), para que la corrida sea de solo lectura respecto al estado real del proyecto. Verificado antes y después: `git status --short` vacío, y los 4 contadores de `data/engine.db` real (`event_snapshots=93`, `feature_snapshots=0`, `event_results=0`, `normalized_records=94`) sin cambio.

**Excepción al aislamiento — verificación deliberada de contaminación del registro de modelos**: se hizo UNA lectura (sin escritura) contra `load_latest_mlb_artifact()` con su ruta de producción por defecto, precisamente para auditar el estado real de `data/models/` — ver hallazgo §3.1. Ningún archivo fue modificado ni borrado durante esta verificación.

Se corrieron dos deportes, con datos 100% reales (APIs en vivo, sin mocks):
- **MLB**: 2 juegos reales de la fecha con partidos más próxima (`2026-07-26`), vía MLB Stats API + Kalshi.
- **Tenis (ATP)**: 2 partidos reales de la fecha con partidos más próxima, vía ESPN Tennis + Kalshi + SofaScore.

---

## 2. Resultados por etapa

### 2.1 MLB — 2 registros reales

| Etapa | Registro 1 (Cleveland Guardians vs Tampa Bay Rays, `mlb_822950`) | Registro 2 (Arizona Diamondbacks vs Washington Nationals, `mlb_822706`) |
|---|---|---|
| **Ingesta** | 15 juegos en el schedule, 42 eventos Kalshi `KXMLBGAME`, boxscore + stats de pitcher + IL roster + team hitting obtenidos sin ningún `FAIL` | Igual — todas las llamadas HTTP reales `OK` |
| **Normalización** | `status=FINAL`, `start_time` real, registro construido sin excepciones | Igual |
| **Matching** | `NEEDS_REVIEW`, `match_confidence=0.0` — mejor candidato Kalshi a 1760min de distancia temporal, excede la tolerancia de 90min | `NEEDS_REVIEW`, `match_confidence=0.0` — mismo patrón, 1680min de distancia |
| **Quality score (completeness)** | `data_completeness_score=0.5333`, 10 campos faltantes (todos honestos: sin mercado matched → `market_id`/`yes_bid`/etc. faltan por construcción) | Igual, mismo score |
| **Mercado (`P_market`)** | `P_market_YES=None`, `P_market_NO=None` — correcto, sin mercado matched no hay precio que leer | Igual |
| **Consenso no-vig** | `NOT_CONFIGURED` — `ODDS_API_KEY` no configurada (confirmado: `get_odds_api_key()` devuelve `None`) | Igual |
| **Modelo** | `model_status=MODEL_NOT_TRAINED`, `p_model_yes=None` (usando un registro de modelos AISLADO de esta validación, nunca el de producción — ver §3.1) | Igual |
| **Confidence (HEURISTIC_V1)** | `confidence=0.3939`, componentes `bookmaker_dispersion`/`sample_size`/`market_liquidity` honestamente `None` (sin datos de odds), pesos redistribuidos automáticamente entre los 4 componentes sí disponibles | Igual, `confidence=0.3939` |
| **Edge/EV** | `EDGE_YES=EDGE_NO=EV_YES=EV_NO=None` — correcto, sin `p_model_yes` no hay edge que calcular | Igual |
| **Señal (`SignalInputs`)** | Construido sin error para `Side.YES` y `Side.NO`, todos los campos numéricos `None` propagados honestamente | Igual |
| **Recomendación final** | **No calculada** — `SignalType` no tiene ninguna función que lo compute todavía (decisión institucional del Paso 12) | Igual |

### 2.2 Tenis (ATP) — 2 registros reales

| Etapa | Registro 1 (Aidan Mayo vs Roger Pascual Ferra, `espn_tennis_atp_183126`) | Registro 2 (Alex Hernandez vs Alan Magadan, `espn_tennis_atp_183129`) |
|---|---|---|
| **Ingesta** | 166 partidos en el scoreboard ESPN, 26 eventos Kalshi `KXATPMATCH` — `OK`. SofaScore `FAIL (http_403)` — bloqueo ya documentado, no un hallazgo nuevo | Igual |
| **Normalización** | `status=SCHEDULED`, registro construido sin excepciones | Igual |
| **Matching** | **`EXACT_NAME_TIME`, `match_confidence=1.0`** — mercado Kalshi real emparejado con confianza total | `NEEDS_REVIEW`, `match_confidence=0.5` — sin mercado |
| **Quality score (completeness)** | `data_completeness_score=0.5882` | `data_completeness_score=0.2353` |
| **Mercado (`P_market`)** | **`P_market_YES=0.99`, `P_market_NO=0.02`** — precio real leído de un mercado Kalshi vivo | `None`/`None` — sin mercado |
| **Consenso no-vig** | `NOT_CONFIGURED` | `NOT_CONFIGURED` |
| **Modelo** | `model_status=MODEL_NOT_TRAINED`, `p_model_yes=None` (registro de tenis limpio, ver §3.1) | Igual |
| **Confidence (HEURISTIC_V1)** | `confidence=0.9011` — alto, impulsado por `match_confidence_gap=1.0` y `market_liquidity=1.0` (mercado real matched) | `confidence=0.3152` — bajo, sin mercado |
| **Edge/EV** | `None` en los 4 (sin `p_model_yes`, honesto) | `None` en los 4 |
| **Señal (`SignalInputs`)** | Construido con `market_price=0.99`/`0.02` reales para YES/NO, `edge=None` | Construido con todo `None` |
| **Recomendación final** | No calculada (mismo motivo institucional) | No calculada |

**Hallazgo positivo**: el registro de tenis 1 es la primera vez, en toda Fase 2, que se ejercita la cadena completa mercado→consenso→modelo→confidence→edge/EV→señal sobre un precio de mercado **real y vivo** (no sintético de test) en una sola corrida continua. El pipeline se comportó exactamente como está diseñado: propagó el precio real donde existía, y `None` honesto donde no había modelo entrenado — sin fabricar nada en ningún punto.

---

## 3. Incidencias encontradas

### 3.1 CONFIRMADO — Registro de modelos MLB de producción contaminado con artefactos sintéticos

**Evidencia directa** (verificado antes de correr la validación, con una lectura de solo-lectura contra la ruta de producción real):

```
load_latest_mlb_artifact()  # ruta de producción por defecto, sin override
  → model_version:        mlb_baseline_logreg_v1_20260727T024520Z
  → n_training_samples:    10
  → feature_set_version:   phase2_registry_v1
```

`data/models/` (producción real) contiene **23 artefactos** (`.joblib` + `.metadata.json`), con timestamps entre 2026-07-25 00:37 y 2026-07-26 22:45 (hora local). Ninguno está trackeado por git (`data/models/*` está en `.gitignore`, solo `.gitkeep` es parte del repositorio) — esto nunca contaminó ningún commit.

**Por qué es un hallazgo real, no un falso positivo**: `n_training_samples=10` es imposible a partir del histórico real — `feature_snapshots` en `data/engine.db` real tiene **0 filas** ahora mismo, y esa tabla es INSERT-only con un trigger que bloquea `DELETE`/`UPDATE` (verificado en `src/storage/history_repository.py`), así que si alguna vez hubiera tenido filas reales, seguirían ahí. Nunca las tuvo. El artefacto solo pudo generarse contra un `HistoryRepository` sintético/temporal (10 muestras fabricadas para pruebas), mientras `models_dir` quedaba en su valor por defecto (`DATA_MODELS_DIR`, producción) en vez de apuntar también a una ruta temporal.

**Causa raíz más probable** (hipótesis razonada, no verificada con certeza absoluta): comandos de verificación manual (`python -c "..."`) ejecutados en sesiones anteriores de este mismo proceso institucional, para auditar el comportamiento de `train_mlb_baseline_model` con una muestra pequeña — igual al patrón `min_samples=10` que usa `tests/unit/test_model_registry.py::_train_tiny_model`. Se revisaron **todos** los call-sites reales de `train_mlb_baseline_model()`/`save_artifact_metadata()` en `tests/` y `scripts/`: los de `tests/` pasan `models_dir=` explícitamente en absolutamente todos los casos (correctamente aislados); `scripts/train_mlb_model.py` (el único CLI oficial) usa la ruta de producción **por diseño intencional** (para eso existe), pero con `min_samples=300` por defecto — no genera artefactos de 10 muestras salvo que alguien pase `--min-samples 10` manualmente, y aun así leería el `HistoryRepository()` real (0 filas), nunca produciría `TRAINED`. Ningún módulo de `src/` tiene un bug — es contaminación operativa de comandos ad-hoc, no un defecto de código de producto.

**Riesgo real si no se corrige**: cualquier código futuro que llame `load_latest_mlb_artifact()` sin especificar `models_dir` (comportamiento por defecto, el mismo que usaría en producción) recogería hoy mismo este artefacto sintético como si fuera un modelo real entrenado, reportando `model_status=TRAINED` con una probabilidad derivada de 10 muestras fabricadas — una violación directa del invariante más fundamental de todo el proyecto ("nunca fabricar `P_model`"). Esta validación evitó ese riesgo usando deliberadamente un registro aislado (ver §1); el registro de producción real seguiría estando comprometido si se consultara sin ese aislamiento.

**Tenis no está afectado**: verificado — cero archivos `tennis_baseline_*` en `data/models/`.

### 3.2 Observación (no es una incidencia de código) — cobertura de mercados MLB limitada en la fecha probada

Los dos juegos MLB reales usados no encontraron ningún evento Kalshi correspondiente dentro de la tolerancia de 90 minutos (candidato más cercano a 1760/1680 minutos de distancia). El sistema respondió **correctamente**: `match_confidence=0.0`, `NEEDS_REVIEW=True`, y cada etapa posterior propagó `None` en vez de adivinar. No es un defecto — es el comportamiento exacto que exige el diseño (nunca fabricar un match). Refleja un hueco de cobertura real de mercados Kalshi para esa fecha/esos equipos, ya contemplado como riesgo conocido en `FASE2_CIERRE_FINAL.md` §5.

### 3.3 Sin otras incidencias

Las 10 etapas (ingesta, normalización, matching, quality score, mercado, consenso no-vig, modelo, confidence, edge/EV, señal) corrieron sin ninguna excepción, en 4 registros reales de 2 deportes distintos, con y sin mercado matched, con y sin modelo entrenado. Ningún valor fabricado en ningún punto — cada `None` observado corresponde a un dato real no disponible, no a un error silencioso.

---

## 4. Corrección propuesta (NO ejecutada — pendiente de tu autorización)

1. **Limpiar `data/models/`**: eliminar los 23 artefactos sintéticos (`*.joblib` + `*.metadata.json` con `n_training_samples` incompatible con el histórico real), conservando `.gitkeep`. Acción local, reversible en el sentido de que ninguno está en git ni es irremplazable — pero es una eliminación de archivos reales, así que no se ejecuta sin tu confirmación explícita.
2. **Disciplina operativa hacia adelante** (no es un cambio de código): cualquier verificación manual futura de `train_mlb_baseline_model`/`predict_mlb_baseline` con datos sintéticos debe pasar explícitamente `models_dir=<ruta temporal>` — nunca dejar el valor por defecto de producción cuando el `HistoryRepository` usado no es el real. Esto ya es la práctica correcta usada en todos los tests; el hallazgo es que no se siguió consistentemente en verificaciones ad-hoc fuera de pytest.

No se propone ningún cambio a `src/` — no hay ningún defecto de código de producto, verificado explícitamente revisando cada call-site real.

¿Autorizas la limpieza de `data/models/` (punto 1)? Es la única acción pendiente de esta validación.
