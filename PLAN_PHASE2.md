# Fase 2 — Plan Técnico: Capa Cuantitativa (P_model, P_market, Edge, Incertidumbre)

Estado: **CERRADA — IMPLEMENTADA Y AUDITADA.** Cierre formal: 2026-07-26.
Los Pasos 0-12 (§12) fueron implementados, testeados, auditados y
committeados en su totalidad sobre `phase-2-dev`. Ver §18 ("Estado final
de implementación — Cierre formal de Fase 2") para el mapeo completo
paso→commit, la verificación de los 13 criterios de aceptación de §14, y
las excepciones aceptadas. `CONTINUITY.md` es la fuente de verdad
detallada para cualquier conversación nueva; este documento conserva el
texto de diseño original (Revisión 2, sección por sección) como registro
histórico de lo que se aprobó **antes** de implementar, sin reescribirlo
retroactivamente para que coincida con el resultado final — cualquier
desviación real respecto a lo aquí escrito está documentada
explícitamente en §18, nunca oculta.

**Revisión 2** — incorpora 7 correcciones obligatorias tras la revisión del
usuario: (1) histórico append-only real, (2) pricing side-aware explícito
YES/NO, (3) separación infraestructura-de-modelo vs modelo-entrenado, (4)
`confidence_method` declarado como heurística no calibrada, (5) no-vig en
dos pasos con gate de matching, (6) estrategia de rama git, (7) reorden de
implementación con el histórico append-only como Paso 0 absoluto. Los
cambios respecto a la Revisión 1 están marcados **[REV2]**. Este texto
(secciones 1-17) se conserva tal como fue aprobado antes de la
implementación — es la propuesta original, no una crónica editada después
de los hechos.

---

## 1. Inventario real de datos disponibles HOY

*(Sin cambios respecto a la Revisión 1 — verificado contra las APIs reales,
no supuesto.)*

### 1.1 MLB

| Dato | Fuente | Estado | Endpoint verificado |
|---|---|---|---|
| Calendario, equipos, pitchers probables | MLB Stats API | ✅ disponible | `schedule?hydrate=probablePitcher` |
| Boxscore, batting order confirmado | MLB Stats API | ✅ disponible (solo si el juego ya tiene lineup publicado — antes del lineup real queda `NULL`) | `game/{pk}/boxscore` |
| Stats de temporada del pitcher (ERA, WHIP, K%, BB%, IP, HR/9...) | MLB Stats API | ✅ disponible | `people/{id}/stats?stats=season&group=pitching` |
| **Splits por handedness del rival (vs LHB/RHB)** | MLB Stats API | ✅ disponible (verificado hoy) | `people/{id}/stats?stats=statSplits&sitCodes=vr,vl` |
| **Game log del pitcher (forma reciente, últimos N starts)** | MLB Stats API | ✅ disponible (verificado hoy) | `people/{id}/stats?stats=gameLog&group=pitching` |
| **Roster de lesionados (IL)** | MLB Stats API | ✅ disponible (verificado hoy) | `teams/{id}/roster?rosterType=injuredList` |
| Récord de temporada por equipo | MLB Stats API | ✅ disponible (`leagueRecord` en `schedule`) | `schedule` |
| Stats ofensivas de equipo (temporada) | MLB Stats API | ✅ disponible | `teams/{id}/stats?stats=season&group=hitting` |
| Stats de bullpen agregadas | MLB Stats API | ⚠️ parcial — se **deriva** agregando `people/stats` de relevistas (`gamesStarted=0`), no un campo directo | `teams/{id}/roster` + `people/{id}/stats` |
| Workload reciente de bullpen | MLB Stats API | ⚠️ parcial — derivable de `gameLog`, requiere N llamadas por juego | `people/{id}/stats?stats=gameLog` |
| Home/away | MLB Stats API | ✅ disponible (ya en `model_inputs.context`) | `schedule` |
| Platoon advantage | MLB Stats API | ⚠️ parcial — requiere lineup confirmado + `batSide`, a menudo `MISSING` con antelación | `boxscore` + `people/{id}` |
| Park factors | — | ❌ bloqueado — sin campo en la API ni histórico propio suficiente | — |
| Weather | — | ❌ bloqueado — sin fuente aprobada | — |
| Travel (descanso/distancia) | MLB Stats API | ⚠️ parcial — descanso derivable del `schedule` histórico; distancia real no verificada | `schedule` (histórico) |
| Robinhood price observado | — | ❌ fuera de alcance (reservado en Fase 1, sin conector) | — |

### 1.2 Tenis

| Dato | Fuente | Estado |
|---|---|---|
| Calendario, participantes, estado, torneo | ESPN Tennis | ✅ disponible (dobles ya filtrados desde Fase 1) |
| Ranking ATP/WTA | SofaScore | ❌ **bloqueado en este entorno** (403 Cloudflare) |
| Surface | ESPN (no estructurado) / SofaScore | ⚠️/❌ — no inferir por heurística de texto del torneo (ver §16) |
| Forma reciente real (W/L), H2H, serve/return | SofaScore | ❌ bloqueado |
| Rest days | ESPN (derivable de histórico propio) | ✅ parcial — requiere acumular scoreboards, no una llamada única |
| Withdrawals/injuries | — | ❌ bloqueado — sin fuente estructurada |
| Odds/consenso (ambos deportes) | The Odds API | ❌ **NOT_CONFIGURED** — sin `ODDS_API_KEY` |

### 1.3 Conclusión del inventario

MLB permite un baseline honesto hoy (pitcher + forma + splits + IL +
contexto de equipo). Tenis queda fuertemente limitado mientras SofaScore
esté bloqueado — único insumo real y verificado: quién juega, cuándo, en
qué torneo, con cuántos días de descanso.

---

## 2. Huecos de datos (consolidado)

1. **SofaScore bloqueado** → bloquea ranking, surface, forma real, H2H, serve/return de tenis. El hueco más grande de Fase 2.
2. **The Odds API sin configurar** → bloquea `P_consensus_no_vig` en ambos deportes.
3. **Sin histórico propio acumulado** → bloquea Elo/rating propio y backtesting real. **[REV2] Ya no es un simple "hueco a resolver después": es el Paso 0 absoluto, ver §11.**
4. **Sin fuente de park factors ni weather.**
5. **Bullpen y platoon requieren agregación nueva** (no bloqueados por fuente, sí por costo de implementación/red).

---

## 3. Arquitectura propuesta

Se mantiene la estructura de la Revisión 1, con una precisión adicional
**[REV2]**: `src/storage/` gana un submódulo nuevo, aditivo, para el
histórico append-only (ver §11), sin tocar `repository.py` en sus tablas
existentes.

```
src/features/           Feature engineering
  registry.py              Definición tipada de cada feature
  mlb_features.py          Cálculo de features MLB
  tennis_features.py       Cálculo de features tenis (limitado)
  feature_store.py         Persistencia versionada de vectores de features

src/models/              Modelos de predicción (P_model)
  base.py                  Interfaz común + PModelOutput tipado (incluye model_status)
  mlb_baseline.py           Infraestructura + modelo(s) baseline MLB
  tennis_baseline.py        Infraestructura + modelo(s) baseline tenis
  registry.py               model_version -> artefacto entrenado (o ausente)

src/pricing/              Traducir precios/odds observados a probabilidades
  market_pricing.py         [REV2] P_market_YES / P_market_NO side-aware
  odds_consensus.py         [REV2] Consenso no-vig en dos pasos + gate de matching
  no_vig.py                 De-vig intra-bookmaker (multiplicativo v1)

src/uncertainty/          Calidad/confianza (heurística declarada, no calibrada)
  quality_score.py          confidence_method=HEURISTIC_V1, componentes + pesos

src/signals/              EDGE/EV side-aware + ESQUEMA de señal (sin umbrales)
  edge.py                   [REV2] EDGE_YES y EDGE_NO independientes
  expected_value.py         EV bruto por lado (EV neto None mientras fee sea NULL)
  signal_schema.py          Tipos ENTER/WATCH/PASS — sin lógica de umbral

src/storage/
  repository.py             [SIN CAMBIOS destructivos] tablas Fase 1 intactas
  history_repository.py     [REV2, NUEVO] event_snapshots / feature_snapshots /
                             event_results — append-only, ver §11

src/backtesting/          Validación temporal
  dataset.py                Construcción de dataset desde history_repository
  splitter.py                Split temporal (walk-forward), nunca random
  metrics.py                 Brier score, log loss, calibration, ROI, CLV

src/evaluation/           Reportes/comparación de modelos
  reports.py                 Curvas de calibración, performance por edge/confianza/liquidez
```

**Módulos que NO se crean todavía:** `src/risk/` (bankroll/Kelly), cualquier
`src/execution/` — sin cambios respecto a Revisión 1.

**Relación con Fase 1:** sin cambios respecto a Revisión 1 — todo módulo
nuevo consume `NormalizedRecord` como entrada; ningún módulo de Fase 2
modifica `src/connectors/`, `src/normalization/`, `src/matching/`,
`src/quality/`. `src/storage/repository.py` no se toca en sus tablas
existentes; el histórico vive en un archivo nuevo (`history_repository.py`)
con sus propias tablas `CREATE TABLE IF NOT EXISTS`, aditivas.

---

## 4. Feature registry propuesto

*(Sin cambios de contenido respecto a Revisión 1 — 10 dimensiones por
feature: nombre, deporte, fuente, timestamp de disponibilidad, fórmula,
unidad, tratamiento de missing, riesgo de leakage, validación, importancia
esperada, disponibilidad actual. Detalle completo del baseline v1 MLB:
`pitcher_era_season`, `pitcher_whip/k_pct/bb_pct/ip_season`,
`pitcher_form_last5`, `pitcher_vs_opponent_handedness_ops`,
`bullpen_era_recent`, `team_record_pct/team_ops_season/home_away`,
`il_flag_key_players`. Baseline v1 tenis: `rest_days`,
`tournament_round_context`. Registry de referencia futuro para el resto de
features bloqueadas por SofaScore/histórico. Ver Revisión 1 para el detalle
línea por línea, no se repite aquí por brevedad — no ha cambiado.)*

**[REV2] Adición:** cada feature calculada, desde el Paso 2, se persiste
también en `feature_snapshots` (ver §11) — el feature registry pasa a ser
no solo una definición sino la fuente de la columna `feature_set_version`
que ancla cada snapshot a la versión exacta de fórmulas que lo produjo.

---

## 5. Diseño del modelo baseline MLB **[REV2 — reformulado]**

**Separación obligatoria, ya no opcional:**

### A) Infraestructura del modelo (se construye primero, siempre)
- Feature pipeline (Paso 2, §4).
- Dataset builder (lee de `history_repository`, no de `normalized_records`).
- Training pipeline (código que SABE entrenar, aunque no se haya ejecutado con éxito todavía).
- Model versioning (`model_version`, artefacto serializado + metadata).
- Inference contract (ver abajo) — funciona y es testeable **incluso sin modelo entrenado**.

### B) Modelo realmente entrenado y validado
Solo cuando exista histórico etiquetado suficiente. **No se entrena una
logistic regression con muestra insuficiente solo para cumplir un
criterio de aceptación.**

**Umbral de suficiencia (heurística de ingeniería, no un umbral de
decisión de apuesta — no viola el principio de "no umbrales arbitrarios",
que aplica a ENTER/WATCH/PASS, no a viabilidad estadística de
entrenamiento):** con ~7 features en el baseline v1, una regla de pulgar
conservadora (10-20 observaciones por dimensión de feature, más margen
para holdout train/val/test) sitúa el piso mínimo razonable en **el orden
de 300-500 eventos etiquetados** antes de intentar siquiera un primer
entrenamiento, y aun así el resultado se reporta con incertidumbre alta.
Este número se revisa con evidencia, no se congela.

**Contrato de salida (obligatorio para TODO modelo, entrenado o no):**

```
P_model_YES                float en [0,1], o None si no hay modelo entrenado
model_version               string, o None
model_status                 "MODEL_NOT_TRAINED" | "INSUFFICIENT_HISTORY" | "TRAINED"
feature_set_version          string
prediction_timestamp         datetime UTC-aware
data_cutoff_timestamp        datetime UTC-aware
confidence / uncertainty     ver §9 (nunca placeholder)
missing_features             lista de features NULL en esta predicción
warnings                     lista de strings
```

`model_status` distingue explícitamente: **`MODEL_NOT_TRAINED`** = la
infraestructura existe pero el entrenamiento no se ha ejecutado/persistido
todavía; **`INSUFFICIENT_HISTORY`** = se intentó construir el dataset de
entrenamiento y no alcanzó el umbral mínimo; **`TRAINED`** = hay un
artefacto real, versionado, evaluado. Mientras el estado no sea `TRAINED`,
**`P_model_YES = None` siempre** — nunca se fabrica una probabilidad para
aparentar que el modelo está operativo.

---

## 6. Diseño del modelo baseline tenis

*(Sin cambios de fondo respecto a Revisión 1: Baseline 0 mercado, Baseline
1 mínimo con `rest_days`+contexto de torneo, sin Elo de tenis por falta de
histórico. **[REV2]** Aplica el mismo contrato de §5 con `model_status` —
en tenis es previsible que `model_status` permanezca en
`INSUFFICIENT_HISTORY` durante mucho más tiempo que en MLB, dado el doble
bloqueo: SofaScore Y falta de histórico.)*

---

## 7. Diseño de P_market y pricing **[REV2 — reformulado, side-aware explícito]**

**Formalización exacta pedida:**

```
P_model_YES = probabilidad del resultado YES (salida nativa del modelo)
P_model_NO  = 1 - P_model_YES

BUY YES:
  P_market_YES = YES_ASK
  EDGE_YES     = P_model_YES - YES_ASK

BUY NO:
  P_market_NO  = NO_ASK
  EDGE_NO      = P_model_NO - NO_ASK
               = (1 - P_model_YES) - NO_ASK
```

**Nunca se compara `P_model_YES` directamente contra `NO_ASK`.** Cada lado
tiene su propio precio ejecutable y su propia probabilidad de modelo
correspondiente — no se cruzan.

```
def market_price_yes(record) -> Optional[float]:
    if record.data_quality.needs_review:
        return None
    yes_ask = record.market.yes_ask
    if yes_ask is None or not (0.0 <= yes_ask <= 1.0):
        return None   # precio fuera de rango: no se usa, no se clampa
    return yes_ask

def market_price_no(record) -> Optional[float]:
    if record.data_quality.needs_review:
        return None
    no_ask = record.market.no_ask
    if no_ask is None or not (0.0 <= no_ask <= 1.0):
        return None
    return no_ask
```

`market_price_yes` y `market_price_no` son **independientes entre sí**: si
`yes_ask` falta pero `no_ask` existe, `P_market_YES=None` pero
`P_market_NO` puede seguir siendo válido (y viceversa). Ninguno se
reconstruye a partir del otro (`P_market_NO ≠ 1 - P_market_YES` — ese sería
exactamente el error de "reconstrucción 1-precio" que Fase 1 ya prohibió
para bid/ask, extendido aquí a nivel de probabilidad de mercado).

`LAST_PRICE` **nunca** se usa como `P_market_YES` ni `P_market_NO`.
`YES_BID`, `YES_ASK`, `NO_BID`, `NO_ASK`, `LAST_PRICE` se mantienen
siempre separados en el esquema.

**EV por lado, con la probabilidad correspondiente al contrato comprado:**

```
EV_YES_bruto = P_model_YES * (1 - YES_ASK) - (1 - P_model_YES) * YES_ASK
EV_NO_bruto  = P_model_NO  * (1 - NO_ASK)  - (1 - P_model_NO)  * NO_ASK
```

`EV_neto` (por lado) permanece `None` hasta que `EXCHANGE_FEE` deje de ser
`NULL` en el esquema de Fase 1 (Kalshi no expone ese campo hoy).

**Caso `YES_ASK + NO_ASK > 1`** (posible en un mercado real, no es un bug):
`EDGE_YES` y `EDGE_NO` se siguen calculando cada uno con su propio precio,
de forma completamente independiente — la fórmula nunca asume que ambos
lados deben sumar 1. Se documenta como observación de calidad de mercado
(spread agregado ancho), no se "corrige" nada.

### Tests obligatorios **[REV2, nuevos]**

1. **Lado YES**: `P_model_YES=0.60`, `yes_ask=0.55` → `EDGE_YES=0.05` exacto.
2. **Lado NO**: mismo registro, `no_ask=0.42` → `P_model_NO=0.40`,
   `EDGE_NO=-0.02` exacto — y explícitamente `EDGE_NO ≠ P_model_YES - no_ask`.
3. **`YES_ASK + NO_ASK > 1`**: ambos `EDGE_YES`/`EDGE_NO` se calculan sin
   error y sin reescalar los precios.
4. **`NEEDS_REVIEW=True`**: `P_market_YES=None`, `P_market_NO=None`,
   `EDGE_YES=None`, `EDGE_NO=None` — ningún dato de mercado se usa.
5. **Ask faltante en un solo lado**: `yes_ask=None`, `no_ask=0.40` presente
   → `EDGE_YES=None` pero `EDGE_NO` calculable si `P_model_YES` existe.
6. **Precio fuera de rango**: `yes_ask=1.15` → `P_market_YES=None`,
   `EDGE_YES=None` (nunca se usa un precio inválido, nunca se clampa a 1.0
   en silencio).

**Nota de resolución [Paso 3 cerrado, decisión explícita del usuario]:**
la redacción anterior de §12/§13, que etiqueta estos "6 tests
obligatorios" como pertenecientes al Paso 3, generaba una ambigüedad real
con la tabla de arquitectura de §3 (que asigna `EDGE_YES`/`EDGE_NO` a
`src/signals/edge.py`, Paso 8) — el plan nunca definió pseudocódigo de
una función de EDGE, solo la fórmula. Se resuelve así: `src/pricing/market_pricing.py`
(Paso 3) implementa únicamente `market_price_yes`/`market_price_no`; los
6 escenarios se prueban ahí solo en la parte de `P_market_YES`/`P_market_NO`.
Las aserciones de `EDGE_YES`/`EDGE_NO` de estos mismos 6 escenarios se
implementan en el Paso 8 (`src/signals/edge.py`), reutilizando estas
funciones como entrada. El criterio de aceptación #5 (§14) se satisface
al cierre de la Fase 2, no al cierre del Paso 3.

---

## 8. Diseño del consenso no-vig **[REV2 — reformulado en dos pasos explícitos]**

Solo se implementa si `ODDS_API_KEY` está configurada; si no,
`P_consensus_no_vig_YES = P_consensus_no_vig_NO = None` y
`source_status["odds_api"] = NOT_CONFIGURED`.

**Paso A — de-vig DENTRO de cada bookmaker**, usando **ambos lados del
mismo mercado de ESE bookmaker** (no se mezcla con otros bookmakers todavía):

```
p_raw_YES_i    = 1 / decimal_odds_YES_i
p_raw_NO_i     = 1 / decimal_odds_NO_i
overround_i    = p_raw_YES_i + p_raw_NO_i        (> 1, contiene el vig)
p_no_vig_YES_i = p_raw_YES_i / overround_i
p_no_vig_NO_i  = p_raw_NO_i  / overround_i
```

**Paso B — agregación ENTRE bookmakers**, por outcome, después de que cada
uno ya esté sin vig individualmente:

```
P_consensus_no_vig_YES = mediana({p_no_vig_YES_i : i en bookmakers})
P_consensus_no_vig_NO  = mediana({p_no_vig_NO_i  : i en bookmakers})
```

Mediana (no promedio) por robustez a un bookmaker outlier. El método de
Shin se evalúa como mejora futura, no en v1.

**Gate de matching de evento [REV2, nuevo]:** cada evento de The Odds API
debe pasar por el mismo tipo de event-matching que ya usa Fase 1 para
Kalshi (reutilizando `src.matching.event_matcher.match_event`/
`name_similarity` — no se reimplementa una heurística nueva). Si el
matching de un bookmaker/evento contra nuestro `NormalizedRecord` es
`NEEDS_REVIEW`/`NO_MATCH`, **esas odds se excluyen por completo del
consenso para ese evento** — nunca se mezclan odds de un evento
ambiguamente identificado, aplicando el mismo principio ya validado en
Fase 1 para Kalshi (§FIX-2 de la auditoría de Fase 1).

**Salida obligatoria, con preservación explícita pedida:**

```
P_consensus_no_vig_YES / _NO   float en [0,1] o None
bookmaker_count                  int (cuántos bookmakers pasaron el gate de matching)
per_bookmaker_timestamps         {bookmaker_key: last_update} — cada timestamp, no solo uno agregado
freshness                        antigüedad del dato más viejo usado
dispersion                       desviación estándar de p_no_vig_YES_i entre bookmakers
event_match_confidence           confianza del matching Odds-API-evento -> NormalizedRecord (por bookmaker excluido, se registra el motivo)
source_quality                   bookmaker_count>=3 -> "OK", 1-2 -> "PARTIAL", 0 -> "NOT_CONFIGURED"/"FAILED"
```

---

## 9. Diseño de incertidumbre/confianza **[REV2 — declarada como heurística no calibrada]**

Se mantiene el diseño de componentes de la Revisión 1 (`data_completeness`,
`match_confidence_gap`, `missing_critical`, `bookmaker_dispersion`,
`sample_size`, `market_liquidity`, `freshness`), con una adición
obligatoria al contrato de salida:

```
confidence                 float en [0,1] — score agregado
confidence_method           "HEURISTIC_V1"   <- declarado explícitamente, siempre
confidence_config_version    string (qué versión de pesos se usó)
components                  dict completo, cada componente individual conservado
weights                      dict completo, los pesos usados en ESTE cálculo
```

**`confidence` nunca se presenta ni se documenta como una probabilidad
calibrada.** Es un score heurístico de agregación, útil para ordenar/filtrar
y para auditar, no una salida estadísticamente validada. La calibración
real de los pesos (¿qué componente realmente predice error del modelo?)
requiere histórico real (Paso 0) y se hace **después**, con evidencia — en
ese momento, `confidence_method` pasaría a algo como `"CALIBRATED_V1"`,
nunca antes.

Ejemplo de comportamiento (sin cambios de fondo): `P_model_YES=0.64` con
`data_completeness` bajo y `bookmaker_dispersion` alto produce `confidence`
bajo — el sistema deja evidencia auditable de por qué, sin imponer ninguna
regla de decisión (eso sigue siendo Fase 2G, sin umbrales).

---

## 10. Diseño de backtesting y validación

*(Sin cambios de fondo respecto a Revisión 1: dataset reproducible, split
temporal estricto nunca aleatorio, walk-forward cuando el volumen lo
permita, Brier score + log loss como métricas primarias, accuracy
secundaria, ROI simulado y CLV solo si hay historial de precios suficiente,
desagregación por deporte/edge/confianza/liquidez/tipo de mercado, regla
anti-overfitting de umbrales calibrados en validation y confirmados en
test.)*

**[REV2] Precisión de fuente de datos:** el dataset de backtesting se
construye ahora explícitamente desde `history_repository`
(`event_snapshots` + `feature_snapshots` + `event_results`, ver §11), no
desde `normalized_records` (que solo tiene el estado actual, no historia).
El join con `event_results` ocurre **únicamente** en este paso, filtrando
estrictamente `event_snapshots.captured_at < event_results.recorded_at`
para cada fila del dataset — es el punto exacto donde se aplica la regla
de "el resultado nunca contamina snapshots pre-partido".

---

## 11. Histórico append-only — diseño detallado **[REV2 — sección nueva, corrige el defecto crítico]**

**Problema identificado (correcto):** `normalized_records` (Fase 1) hace
`UPSERT` por `event_id` — es una vista del **estado actual**, no conserva
evolución histórica. Guardar features/backtesting sobre esa tabla sería
reconstruir el pasado con datos del presente: leakage estructural.

**Solución: tres tablas nuevas, aditivas, en un archivo nuevo
`src/storage/history_repository.py`** (no se toca `repository.py` ni sus
tablas `raw_captures`/`normalized_records`, que siguen funcionando
exactamente igual para lo que ya usan `scripts/run_e2e.py` y los tests de
Fase 1).

```sql
-- 1) Snapshot de mercado + calidad, uno por captura. NUNCA se hace UPDATE.
CREATE TABLE IF NOT EXISTS event_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- clave por FILA, no por event_id
    event_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    source TEXT NOT NULL,                       -- p.ej. "mlb_pipeline_run"
    captured_at TEXT NOT NULL,                  -- as_of_timestamp UTC ISO8601: CUÁNDO se tomó esta foto
    event_start_time TEXT,                      -- start_time del NormalizedRecord en ese instante
    market_id TEXT,
    yes_bid REAL, yes_ask REAL, no_bid REAL, no_ask REAL, last_price REAL,
    spread_yes REAL, spread_no REAL,
    volume REAL, volume_24h REAL, open_interest REAL, liquidity REAL,
    source_timestamps_json TEXT,                -- data_quality.source_timestamps completo, en ese instante
    data_quality_json TEXT,                      -- DataQuality completo (needs_review, match_confidence, missing_fields...)
    normalized_record_json TEXT NOT NULL,        -- NormalizedRecord COMPLETO -- ancla de reproducibilidad total
    raw_refs_json TEXT                            -- raw_refs de ese NormalizedRecord
);
CREATE INDEX IF NOT EXISTS idx_event_snapshots_event_captured
    ON event_snapshots(event_id, captured_at);

-- 2) Vector de features en un instante dado (aditiva; se activa desde el Paso 2)
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    event_snapshot_id INTEGER NOT NULL,          -- referencia al snapshot del que se derivó
    feature_set_version TEXT NOT NULL,
    data_cutoff_timestamp TEXT NOT NULL,          -- hasta qué instante de datos se permitió mirar
    computed_at TEXT NOT NULL,
    features_json TEXT NOT NULL,                  -- {nombre_feature: valor|null, ...}
    missing_features_json TEXT,
    FOREIGN KEY (event_snapshot_id) REFERENCES event_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_event
    ON feature_snapshots(event_id, computed_at);

-- 3) Resultado final. Tabla SEPARADA, append-only. El enlace a snapshots es
--    solo lógico (mismo event_id) y se materializa SOLO al construir el
--    dataset de backtesting (§10), nunca al escribir un snapshot.
CREATE TABLE IF NOT EXISTS event_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    result TEXT NOT NULL,        -- "PARTICIPANT_A_WON" | "PARTICIPANT_B_WON" | "CANCELLED" | "POSTPONED" | "NO_CONTEST"
    settled_at TEXT,             -- cuándo se decidió oficialmente (si se conoce)
    recorded_at TEXT NOT NULL,   -- cuándo NUESTRO sistema lo capturó
    source TEXT NOT NULL,
    source_payload_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_results_event ON event_results(event_id);
```

**Reglas de diseño no negociables:**

1. **INSERT-only.** Ningún método nuevo ejecuta `UPDATE`/`ON CONFLICT`
   sobre estas tres tablas. Test de regresión obligatorio: guardar dos
   snapshots del mismo `event_id` produce **dos filas**, nunca una.
2. **`normalized_record_json` es la fuente de verdad completa** de "qué
   sabíamos en ese instante" — las columnas aplanadas (`yes_bid`, etc.) son
   conveniencia de consulta derivada de ese JSON en el momento de insertar,
   nunca la única fuente. Esto responde directamente a "cada observación
   histórica debe poder reconstruir exactamente qué información estaba
   disponible en un instante determinado".
3. **`event_results` nunca se une a `event_snapshots` al escribir.** El
   join solo ocurre en la construcción del dataset de backtesting, filtrado
   estrictamente por fecha (`captured_at < recorded_at` del resultado
   correspondiente). Un snapshot pre-partido nunca lleva su propio
   resultado embebido — así se cumple "el resultado final puede enlazarse
   posteriormente, pero nunca debe contaminar snapshots pre-partido".
4. **`Repository` (Fase 1) no se modifica.** `history_repository.py` es un
   archivo nuevo con su propio `CREATE TABLE IF NOT EXISTS` (mismo patrón
   ya usado en Fase 1), sus propios métodos (`save_event_snapshot`,
   `save_feature_snapshot`, `save_event_result`), todos aditivos.
5. **`data/engine.db` es el mismo archivo SQLite** (se comparte la
   conexión/archivo, no se crea una base de datos separada) — las tablas
   nuevas conviven con `raw_captures`/`normalized_records`/`event_matches`
   de Fase 1 sin alterarlas.

**Cómo se empieza a acumular:** cada ejecución de `run_mlb_pipeline`/
`run_tennis_pipeline` (ya existentes, sin modificar su lógica interna)
gana una llamada **adicional** (no sustitutiva) a
`history_repository.save_event_snapshot(record, source=...)` justo después
de `repository.save_normalized_record(record)`. Ejecutar el pipeline
repetidamente en el tiempo (aunque sea manualmente al principio, luego
programado) es lo que genera la serie temporal.

---

## 12. Orden exacto de implementación **[REV2 — reordenado, Paso 0 primero y ampliado]**

```
Paso 0  — HISTÓRICO APPEND-ONLY (empieza YA, antes que cualquier otro paso;
          corre en paralelo mientras se construye el resto):
  0a. src/storage/history_repository.py: las 3 tablas de §11, aditivas.
  0b. Métodos save_event_snapshot / save_feature_snapshot (activado desde
      Paso 2) / save_event_result. Todos INSERT-only, con test de
      regresión "dos snapshots -> dos filas".
  0c. Wire en mlb_pipeline.py / tennis_pipeline.py: UNA llamada adicional
      a save_event_snapshot tras save_normalized_record, sin tocar la
      lógica de matching/normalización ya validada.
  0d. Empezar a ejecutar los pipelines de forma repetida desde ya (operar
      lo ya construido en Fase 1, no requiere código nuevo más allá de
      0a-0c) para que exista volumen cuando lleguen los pasos de modelo.

Paso 1  — src/features/registry.py: definición tipada, sin cálculo.

Paso 2  — src/features/mlb_features.py: cálculo del baseline v1 MLB +
          persistencia en feature_snapshots (extiende Paso 0). Tests:
          fixtures reales + tests de leakage explícitos.

Paso 3  — src/pricing/market_pricing.py: P_market_YES/NO side-aware (§7),
          con los 6 tests obligatorios de §7.

Paso 4  — src/pricing/odds_consensus.py + no_vig.py: de-vig en dos pasos
          + gate de matching de evento (§8). Solo con ODDS_API_KEY real en
          integración; si no, NOT_CONFIGURED limpio.

Paso 5a — Infraestructura de modelo MLB (§5-A): feature pipeline, dataset
          builder (lee de history_repository), training pipeline, model
          versioning, inference contract. Testeable end-to-end con
          model_status=MODEL_NOT_TRAINED/INSUFFICIENT_HISTORY.

Paso 5b — Entrenamiento real del modelo MLB (§5-B): GATED, solo cuando el
          dataset builder confirme volumen suficiente (heurística ~300-500
          eventos etiquetados). No tiene una fecha fija en este plan —
          depende de cuánto tarde el Paso 0 en acumular.

Paso 6  — Elo simple MLB (Baseline 2): mismo patrón infra/entrenado que
          5a/5b, con un piso de datos menor pero igualmente dependiente de
          resultados reales del Paso 0.

Paso 7  — src/uncertainty/quality_score.py: confidence_method=HEURISTIC_V1
          (§9), componente por componente testeado.

Paso 8  — src/signals/edge.py + expected_value.py: EDGE_YES/EDGE_NO y EV
          por lado (§7), nunca cruzados.

Paso 9  — src/backtesting/: dataset (desde history_repository) + splitter
          + metrics. Depende directamente de cuánto haya acumulado el
          Paso 0 — se declara explícitamente que puede tardar
          semanas/meses en tener volumen útil.

Paso 10 — src/evaluation/reports.py: comparación Baseline 0 vs 1 vs 2.

Paso 11 — src/features/tennis_features.py + models/tennis_baseline.py:
          al final, expectativas bajas mientras SofaScore siga bloqueado.

Paso 12 — src/signals/signal_schema.py: solo tipos ENTER/WATCH/PASS y sus
          inputs, sin lógica de umbral.
```

---

## 13. Tests que deberán existir en cada subfase **[REV2 — ampliado]**

- **Histórico append-only (Paso 0)** `[REV2, nuevo]`: dos snapshots del
  mismo `event_id` producen dos filas (nunca upsert); `event_results`
  nunca se lee al escribir un snapshot; reconstrucción completa de un
  instante pasado a partir de `normalized_record_json` verificada byte a
  byte contra lo que se guardó.
- **Feature registry (Paso 1)**: cada feature declarada tiene los 10
  atributos; toda feature "disponible ahora" tiene función de cálculo.
- **Cálculo de features (Paso 2/11)**: fixtures reales → valores
  esperados; test de leakage explícito; missing → `NULL` nunca 0 salvo
  semánticamente correcto; muestra insuficiente → `NULL`.
- **Pricing side-aware (Paso 3)** `[REV2, ampliado]`: los 6 casos de §7
  (YES, NO, spread `>1`, NEEDS_REVIEW, ask faltante por lado, precio fuera
  de rango) — cada uno como test nombrado, no genérico.
- **No-vig en dos pasos (Paso 4)** `[REV2, ampliado]`: de-vig intra-bookmaker
  suma exactamente 1.0 por bookmaker (tolerancia de redondeo); agregación
  entre bookmakers robusta a outlier (mediana); evento con matching
  `NEEDS_REVIEW` excluido del consenso, con test de regresión nombrado.
- **Infraestructura de modelo (Paso 5a)** `[REV2, nuevo]`: pipeline
  completo ejecuta end-to-end y devuelve `model_status=MODEL_NOT_TRAINED`/
  `INSUFFICIENT_HISTORY` con `P_model_YES=None` cuando corresponde — nunca
  un número fabricado.
- **Entrenamiento real (Paso 5b)**: solo se activa (y solo se escribe este
  test) cuando exista dataset real suficiente; hasta entonces no es un
  test pendiente de "arreglar", es un test que legítimamente no aplica
  todavía.
- **Incertidumbre (Paso 7)**: cada componente testeado por separado;
  `confidence_method` siempre presente y correcto; caso nombrado
  "P_model=0.64 con baja completeness ⇒ confidence bajo".
- **Edge/EV (Paso 8)** `[REV2, ampliado]`: `EDGE_YES`/`EDGE_NO`
  independientes (test explícito de que no se cruzan lados);
  `EV_neto=None` mientras `EXCHANGE_FEE` sea `NULL`.
- **Backtesting (Paso 9)**: split temporal nunca deja `start_time` de
  validation/test anterior a train; join con `event_results` respeta
  `captured_at < recorded_at`.
- **Integración real**: mismo patrón que Fase 1 — `@pytest.mark.integration`,
  fuente caída no rompe el pipeline, nunca mockeada de forma que oculte un
  fallo real.

---

## 14. Criterios de aceptación para declarar Fase 2 completada **[REV2 — reformulados]**

1. **Histórico append-only** (`event_snapshots`, `event_results`,
   `feature_snapshots` desde Paso 2) implementado, verificado como
   INSERT-only por test, y **con evidencia real de snapshots acumulándose**
   (no solo el esquema vacío).
2. Feature registry documentado con cálculo real para el subconjunto
   disponible hoy; ningún valor inventado.
3. **Infraestructura de modelo MLB completa y funcionando end-to-end**,
   incluso sin modelo entrenado (`model_status` correcto,
   `P_model_YES=None` explícito). **Ya no se exige un modelo entrenado
   como criterio de cierre de fase.**
4. Si (y solo si) el histórico acumulado alcanza el umbral de suficiencia,
   un modelo MLB entrenado, versionado, con `model_status=TRAINED`; si no,
   el sistema lo reporta honestamente — ambos desenlaces son aceptables,
   fabricar una probabilidad no lo es.
5. `P_market_YES`/`P_market_NO` y `EDGE_YES`/`EDGE_NO` correctamente
   derivados, nunca cruzados, con los 6 tests de §7 pasando.
6. `P_consensus_no_vig_YES`/`_NO` con el proceso de dos pasos verificado
   (de-vig intra-bookmaker → agregación entre bookmakers), degradando
   limpio a `NOT_CONFIGURED`, y **nunca mezclando odds de un evento con
   matching ambiguo**.
7. Sistema de incertidumbre declarando `confidence_method=HEURISTIC_V1`
   explícitamente, componentes y pesos auditables, nunca presentado como
   probabilidad calibrada.
8. `EV` bruto por lado calculado solo con la probabilidad correspondiente
   al contrato comprado; `EV_neto` sigue `None`.
9. Backtesting reproducible corriendo sobre `history_repository` real
   (aunque el volumen sea pequeño al principio), split temporal verificado,
   métricas de calibración reportadas.
10. Esquema de señal (`ENTER`/`WATCH`/`PASS`) definido en tipos, sin
    lógica de umbral implementada.
11. Suite de tests de Fase 2 en verde, sin reducir ni romper ninguno de
    los 90 tests de Fase 1.
12. Ningún módulo de Fase 2 modificó `src/connectors/`,
    `src/normalization/`, `src/matching/`, `src/quality/`; `repository.py`
    (Fase 1) recibió cero cambios; el histórico vive en un archivo nuevo
    aditivo — verificado con `git diff` contra el commit baseline.
13. **[REV2]** Todo el trabajo se realizó en la rama `phase-2-dev` (§17),
    partiendo exactamente del commit baseline, sin commits directos sobre
    `main` durante la implementación.

**Explícitamente NO es criterio de aceptación**: modelo de tenis fuerte
(bloqueado por datos), umbrales de ENTER/WATCH/PASS calibrados, ni —
**[REV2]** — un modelo MLB entrenado si el histórico todavía no alcanza el
umbral de suficiencia (eso pasaría a ser deuda técnica documentada, no un
fallo de la fase).

---

## 15. Riesgos técnicos

*(Sin cambios de fondo respecto a Revisión 1: falta de histórico como
mayor riesgo de tiempo; SofaScore bloqueado limita tenis; costo de
agregación de bullpen/platoon; leakage silencioso como el error más
peligroso; dependencia de una sola fuente de odds; sobreajuste de pesos de
incertidumbre; tamaño de vector de features cambiante.)*

**[REV2] Riesgo adicional — crecimiento de almacenamiento:** al ser
append-only, `event_snapshots`/`feature_snapshots` crecen sin límite con
cada ejecución repetida del pipeline. Mitigación: no se implementa
purgado/compactación en Fase 2 (prematuro sin saber el volumen real); se
monitorea el tamaño de `data/engine.db` y se revisita si se vuelve un
problema práctico, documentado como deuda técnica consciente, no ignorada.

---

## 16. Qué NO debe construirse todavía

*(Sin cambios respecto a Revisión 1: umbrales ENTER/WATCH/PASS, ejecución
de órdenes real, `src/risk/`, modelos complejos sin baseline validado, Elo
de tenis, park factors/weather no verificados, superficie de tenis
inferida por heurística de texto, `EV_neto` real, market context como
input de P_model, Fase 3.)*

**[REV2] Adición explícita:** no se entrena ningún modelo (logistic
regression, Elo, o cualquier otro) con una muestra que no alcance el
umbral de suficiencia declarado en §5, solo para "tener un modelo" — la
infraestructura lista con `model_status` honesto es un entregable completo
por sí sola.

---

## 17. Estrategia de rama Git **[REV2 — sección nueva]**

**Propuesta (no ejecutada todavía):** crear la rama `phase-2-dev`
exactamente desde el commit baseline de Fase 1:

```
git checkout -b phase-2-dev c5eb9e77d51eeebb2c6c114ebce1810074b7372b
```

Todo el trabajo de Fase 2 (Pasos 0-12) se realiza sobre `phase-2-dev`,
nunca directamente sobre `main`. `main` permanece exactamente en el commit
baseline hasta que, en algún punto futuro decidido explícitamente por el
usuario, se decida mergear Fase 2 — esa decisión de merge no está incluida
en este plan ni se toma unilateralmente.

Esto da, en todo momento durante la implementación:
- Un punto de restauración instantáneo (`main` en `c5eb9e77...`, intacto).
- Un `git diff main..phase-2-dev` capaz de mostrar exactamente qué tocó
  Fase 2, verificando en cualquier momento el criterio de aceptación #12
  (ningún archivo de Fase 1 modificado fuera de lo aditivo declarado).
- Posibilidad de descartar por completo `phase-2-dev` sin ningún impacto
  en Fase 1 si algo saliera mal.

**No se crea la rama todavía** — queda pendiente de tu aprobación final,
junto con el resto de la implementación.

---

## 18. Estado final de implementación — Cierre formal de Fase 2 (2026-07-26)

Esta sección se añade al cerrar Fase 2, sin alterar el texto de diseño
original de §1-17 (conservado como registro histórico de lo aprobado
antes de implementar). Documenta lo que realmente se construyó, contra
qué se verificó, y las desviaciones aceptadas respecto al texto literal
original.

### 18.1 Mapeo Paso → módulo → estado → commit

| Paso (§12) | Módulo | Estado | Commit de código |
|---|---|---|---|
| 0 | Histórico append-only (`event_snapshots`, `event_results`) | ✅ COMPLETO | `92af29d` |
| 1 | Feature Registry | ✅ COMPLETO | `a471668` |
| 2 | Cómputo de features MLB | ✅ COMPLETO | `7756319` |
| 3 | Pricing side-aware (`P_market_YES`/`P_market_NO`) | ✅ COMPLETO | `32677d6` |
| 4 | Consenso no-vig en dos pasos + gate de matching | ✅ COMPLETO | `b97092d` |
| 0c/0d | Automatización de captura histórica (LaunchAgent) | ✅ COMPLETO (descargado a propósito, ver §21 de `CONTINUITY.md`) | `b261f80`, `7175b78`, `f931822` |
| 5a | Infraestructura de modelo MLB | ✅ COMPLETO | `328e69c` |
| 5b | `feature_snapshots`/`event_results` wiring + training pipeline real | ✅ COMPLETO | `8a15577` |
| 6 | Elo simple MLB (Baseline 2) | ✅ COMPLETO | `03f21c0` |
| 7 | `src/uncertainty/quality_score.py` (HEURISTIC_V1) | ✅ COMPLETO | `822d4dc` |
| 8 | `src/signals/edge.py` + `expected_value.py` | ✅ COMPLETO | `038bff0` |
| 9 | `src/backtesting/` (dataset + walk-forward splitter + metrics) | ✅ COMPLETO | `f15fc59` |
| 10 | `src/evaluation/reports.py` (Baseline 0 vs 1 vs 2) | ✅ COMPLETO | `cfb8dc0` |
| 11 | Tenis (`tennis_features.py` + `tennis_baseline.py` + sync de resultados) | ✅ COMPLETO | `d6fc559` |
| 12 | `src/signals/signal_schema.py` (tipos, sin lógica de umbral) | ✅ COMPLETO | `08daf26` |

Detalle completo de cada paso (ambigüedades resueltas, decisiones
arquitectónicas, hallazgos empíricos) en `CONTINUITY.md`, que permanece
como la fuente de verdad para el histórico técnico paso a paso.

### 18.2 Verificación de los 13 criterios de aceptación (§14)

| # | Criterio | Estado |
|---|---|---|
| 1 | Histórico append-only implementado, INSERT-only, con evidencia real acumulándose | ✅ Cumplido — `event_snapshots`=93 filas reales verificadas |
| 2 | Feature registry documentado, sin valores inventados | ✅ Cumplido |
| 3 | Infraestructura de modelo MLB completa end-to-end (aun sin modelo entrenado) | ✅ Cumplido |
| 4 | Modelo entrenado si el histórico alcanza el umbral; si no, reporte honesto | ✅ Cumplido honestamente — histórico real insuficiente hoy (`feature_snapshots`/`event_results`=0), `model_status` reporta `MODEL_NOT_TRAINED`/`INSUFFICIENT_HISTORY` sin fabricar ninguna probabilidad. Explícitamente **no** exigido como bloqueante por §14 mismo. |
| 5 | `P_market_YES`/`NO` y `EDGE_YES`/`NO` correctos, nunca cruzados, 6 tests de §7 | ✅ Cumplido |
| 6 | No-vig en dos pasos, degradación limpia a `NOT_CONFIGURED` | ✅ Cumplido |
| 7 | Sistema de incertidumbre `HEURISTIC_V1`, nunca presentado como calibrado | ✅ Cumplido |
| 8 | `EV` bruto por lado; `EV_neto` permanece `None` | ✅ Cumplido |
| 9 | Backtesting reproducible sobre `history_repository` real | ✅ Cumplido |
| 10 | Esquema de señal (ENTER/WATCH/PASS) en tipos, sin lógica de umbral | ✅ Cumplido (Paso 12) |
| 11 | Suite de tests en verde, sin reducir los 90 de Fase 1 | ✅ Cumplido — 498 tests, 0 regresiones |
| 12 | Ningún módulo de Fase 2 modificó `connectors/`/`normalization/`/`matching/`/`quality/`; `repository.py` con cero cambios | ⚠️ **Cumplido con excepción documentada y autorizada** — ver §18.3 |
| 13 | Todo el trabajo en `phase-2-dev`, sin commits directos sobre `main` | ✅ Cumplido — verificado, `main` intacto en `c5eb9e77` |

### 18.3 Excepción aceptada — Criterio 12

El texto original de §14.12 prohíbe literalmente cualquier cambio en
`src/connectors/`, `src/normalization/`, `src/matching/`, `src/quality/`
y exige cero cambios en `repository.py`. Verificado con
`git diff --stat c5eb9e77...HEAD`, tres archivos SÍ tienen cambios:

- **`src/storage/repository.py`** (+6/-1) — wiring de la subfase de
  automatización 0c/0d (captura histórica por LaunchAgent), aditivo.
- **`src/connectors/mlb.py`** (+39) — extensión aditiva de los Pasos
  5a/5b (Bloque 1) para exponer los datos ya verificados disponibles en
  la MLB Stats API que el baseline necesitaba.
- **`src/normalization/tennis_normalizer.py`** (+27/-2) — extensión
  aditiva del Paso 11 (captura de `espn_id`/`round` en
  `model_inputs.context`), explícitamente flageada, resuelta como
  ambigüedad y aprobada en el Design Proposal de ese paso.

**Por qué se acepta como excepción y no como incumplimiento**: los tres
cambios fueron (a) estrictamente aditivos (nunca removieron ni
reinterpretaron comportamiento de Fase 1), (b) explícitamente
identificados y flageados en el momento de cada paso (nunca colados sin
mencionar), y (c) aprobados uno por uno por el usuario antes de
implementarse — el mismo nivel de rigor que exige el criterio 12 en
espíritu (evitar cambios silenciosos o no auditados a Fase 1), aunque el
texto literal ("cero cambios") no preveía que la implementación real
necesitaría estas tres extensiones puntuales. Se documenta aquí en vez de
reescribir el criterio retroactivamente para que "aparente" haberse
cumplido al pie de la letra.

### 18.4 Paso 13 y trabajo posterior

`PLAN_PHASE2.md` §12 no define ningún "Paso 13". El siguiente trabajo
conceptual — lógica de clasificación real de umbrales (ENTER/WATCH/PASS)
sobre `SignalInputs`, y cualquier trabajo de Fase 3 — **no está
autorizado por este documento** y requiere una nueva propuesta y
aprobación explícita del usuario antes de iniciarse (§16 sigue
prohibiendo explícitamente "umbrales ENTER/WATCH/PASS calibrados" sin esa
nueva decisión).

---

## Resumen ejecutivo (actualizado)

- **MLB tiene datos reales suficientes hoy** para infraestructura y,
  eventualmente, un modelo entrenado — pero el modelo entrenado depende
  ahora explícitamente de acumular histórico real (Paso 0), no se finge
  antes de tiempo.
- **Tenis sigue fuertemente bloqueado por SofaScore.**
- **The Odds API sigue sin configurar** — el consenso no-vig ahora está
  formalizado en dos pasos explícitos, con gate de matching de evento.
- **El histórico append-only es ahora el Paso 0 absoluto**, con schema
  concreto, aditivo, verificable, y empieza a ejecutarse desde ya en
  paralelo al resto.
- **Pricing y edge son explícitamente side-aware** (YES/NO nunca cruzados),
  con 6 tests de regresión obligatorios definidos.
- **Ningún modelo se entrena con muestra insuficiente** — se reporta
  `model_status` honesto en su lugar.
- **Todo el trabajo ocurre en `phase-2-dev`**, no en `main`, dejando el
  commit baseline de Fase 1 como restauración instantánea en todo momento.

**FASE 2 CERRADA — IMPLEMENTADA, AUDITADA Y APROBADA (2026-07-26). Ver §18
para el estado final de implementación y `CONTINUITY.md` para el detalle
paso a paso.**
