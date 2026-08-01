# Plan de Ejecución — Fase 4 (PROPUESTO, NO APROBADO)

**Estado: BORRADOR para aprobación de arquitectura. Cero código escrito.**
Generado 2026-08-01, inmediatamente después del cierre formal de Fase 3
(`FASE3_CIERRE_FINAL.md`, commit `1f99e21`). Sigue exactamente el mismo
protocolo que abrió Fase 3: auditoría documental + verificación directa
del estado real del repositorio y del runtime, sin asumir nada de lo que
la documentación de cierre afirma, seguida de un plan de ejecución que el
usuario debe aprobar paso a paso antes de que se escriba una sola línea
de código (`feedback-stop-and-report-methodology`).

**Revisión 2 (2026-08-01, mismo día):** el usuario pidió una segunda
revisión arquitectónica sobre 3 puntos antes de aprobar. Los 3 se
investigaron contra el código real (no se aceptaron como buenas ideas en
abstracto) y los 3 resultaron coherentes con la arquitectura existente,
con evidencia concreta que los respalda — ver §1.8. Cambios aplicados:
D-4 se separó en D-4A/D-4B (§3), se añadió el Coverage Gate (§2, §6 Paso
4.2), y se incorporó al roadmap una auditoría de calidad de labels (§6
Paso 4.2.1) — ninguno de los tres se implementa todavía, solo se
documenta su diseño y su lugar en el orden de dependencia. Ningún
principio metodológico ya aprobado cambia (evidencia primero, sin
heurísticas fabricadas, D-3 sin cambios).

---

## 0. Metodología (reafirmada, sin cambios respecto a Fase 2/3)

Sin cambios respecto a `FASE3_EXECUTION_PLAN.md` §0. Un paso a la vez,
autorización explícita antes de cada uno, ejecución completa + tests +
`git diff --stat` + auditoría antes de cada commit, `CONTINUITY.md`
actualizado con una nueva `§0.X` antes de cada commit, ninguna
contradicción se resuelve unilateralmente.

**Regla adicional que aplica con más fuerza en Fase 4 que en Fase 3**:
Fase 3 construyó código contra fixtures sintéticos, así que "no fabricar"
se aplicaba sobre todo a fórmulas (D-3). Fase 4 trabaja contra datos
reales acumulándose en vivo — "no fabricar" aplica ahora también a
**volumen**: ningún paso de esta fase avanza tratando una muestra
pequeña como si fuera suficiente. Cada paso que dependa de datos declara
su propio umbral mínimo verificable, y el propio plan reporta cuándo ese
umbral no se cumple en vez de proceder con lo que hay.

---

## 1. Auditoría del estado real (verificado directamente, 2026-08-01)

No se asumió nada de `FASE3_CIERRE_FINAL.md` — cada afirmación de abajo
se verificó contra el repositorio, la base de datos y `launchctl` en
vivo, no contra lo que los documentos de cierre dicen.

### 1.1 Integridad de repositorio y suite

| Verificación | Resultado |
|---|---|
| `git status` | limpio, rama `phase-2-dev` |
| Suite completa | **927 passed, 0 failed** (re-ejecutada directamente) |
| `v2.0-baseline` (commit real vía `rev-parse ^{commit}`) | `2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df` — intacto, coincide con lo documentado |
| `git diff --stat v2.0-baseline HEAD` sobre paquetes de Fase 1/2 | 5 archivos, los mismos ya documentados (D-2 en `market_matcher.py`/`models/schemas.py`, extensión de `backtesting/metrics.py`, `evaluation/schemas.py` y `evaluation/learning.py` nuevos) — sin cambios no documentados |
| `data/models/` | solo `.gitkeep`, sin contaminación |
| Último commit | `ae23622` (reintento D-3, sin cambios de código) |

### 1.2 LaunchAgents (D-1) — confirmado activo, no solo "documentado como activo"

Ambos `.plist` cargados en `launchctl` con `LastExitStatus = 0`:
`local.prediction-market-engine.run-e2e-historical` (horario) y
`local.prediction-market-engine.data-maintenance` (diario). Sin
contradicción operacional esta vez.

### 1.3 D-3 (fees reales de Kalshi) — sigue abierta, reintento reciente sin éxito

Commit `ae23622`: dos `WebFetch` nuevos contra las dos rutas oficiales
(`kalshi.com/docs/kalshi-fee-schedule.pdf`, `kalshi.com/docs/fees`)
devolvieron HTTP 429 de nuevo. `_estimate_kalshi_taker_fee()` sigue
devolviendo siempre `None`; `net_ev_status` sigue siempre `UNKNOWN`. Sin
cambios respecto al cierre de Fase 3.

### 1.4 Volumen real de histórico — medido directamente en `data/engine.db`

| Tabla | Filas | Notas |
|---|---|---|
| `event_snapshots` | **815** | MLB: 102 filas / **56 eventos distintos**. TENNIS: 713 filas / **205 eventos distintos** |
| `feature_snapshots` | **722** | |
| `raw_captures` | 1851 | **817 con `ok=0`** (44%) — ver §1.6 |
| `normalized_records` | 262 | tabla de estado actual, no histórico acumulativo |
| `event_matches` | **0** | caché de matching cruzado de Fase 1/2, no relacionado con resultados |
| **`event_results`** | **0** | **cero resultados etiquetados, de ningún deporte, en ningún momento** |

Rango temporal real: `2026-07-25` → `2026-08-01`, pero **solo 4 días
calendario con actividad de captura** dentro de esa ventana de 7 días
(`DATA_RETENTION_POLICY.md` §1 ya lo documentaba: "ritmo irregular por
sueño de la máquina" — confirmado, no es una regresión nueva).

### 1.5 Hallazgo crítico — `event_results` en cero, no es un problema de volumen sino de un paso nunca ejecutado

`FASE3_CIERRE_FINAL.md` §5, punto 1 decía "dejar acumular histórico real
(ya en marcha, sin trabajo de código)" como si fuera solo cuestión de
tiempo. **Esto es impreciso.** La causa raíz, verificada en código:

- `scripts/sync_mlb_results.py` y `scripts/sync_tennis_results.py`
  existen desde Fase 2 (Paso 5b, Bloque 3) y son los **únicos**
  escritores de `HistoryRepository.save_event_result()`.
- Ambos son **de invocación manual únicamente, por diseño explícito**
  (docstring de `sync_mlb_results.py`: "Invocación MANUAL únicamente --
  no está conectado a ningún LaunchAgent ni automatización todavía...
  nueva automatización requiere autorización aparte").
- **Ninguno de los dos se ha ejecutado ni una sola vez** desde que
  existen — `event_results` está en `0`, no en "todavía poco volumen".

`event_snapshots`/`feature_snapshots` sí acumulan solos (D-1 resuelto,
LaunchAgent horario activo) — pero eso captura **precios de mercado**,
no **resultados de los eventos**. Sin resultados, ningún snapshot es
utilizable para entrenar ni para calibrar: no hay etiqueta contra la
cual medir si el modelo acertó.

Esto ya estaba anticipado exactamente por el propio diseño de Fase 3 —
`SHADOW_MODE_AND_PROMOTION_GATES.md` §2 define **GATE-0** como
`feature_snapshots.count() >= N_min AND event_results.count() >= N_min`,
las dos condiciones con la conjunción `AND`, no solo la primera. El
hallazgo no es que el gate esté mal diseñado; es que la fase anterior no
dejó ningún mecanismo corriendo para satisfacer la segunda mitad.

### 1.6 Hallazgo secundario — el pipeline de decisión de Fase 3 nunca se ha ejecutado contra datos reales

`FASE3_CIERRE_FINAL.md` §2 afirma "el pipeline de decisión completo es
ejecutable end-to-end sobre datos reales de mercado". Verificado: esto es
cierto en el sentido de que **puede componerse** (probado exhaustivamente
con fixtures, 927 tests), pero **no está conectado a ningún script que
se ejecute en producción**:

- `grep` de `policy`/`Opportunity`/`calibrat`/`payoff` en
  `scripts/run_e2e.py` (el único script programado vía LaunchAgent): sin
  resultados. El job horario captura y normaliza mercado —
  nunca invoca `eligibility.py`/`hard_rules.py`/`soft_score.py`/
  `decision.py`/`opportunity_repository.py`.
- `OpportunityRepository` (`src/opportunity/opportunity_repository.py`)
  usa `db_path=DB_PATH` (la base real) por defecto, y crea sus tablas
  (`opportunities`, `opportunity_evaluations`) con
  `CREATE TABLE IF NOT EXISTS` al conectar — pero **esas tablas no
  existen hoy en `data/engine.db`**, lo que confirma directamente que
  nunca se ha instanciado contra la base real (el propio código de
  Fase 3 documenta que en tests siempre se usa `tmp_path`).

No es una regresión ni un defecto — Fase 3 explícitamente construyó
librería pura sin orquestador (Principio de alcance: "sin ejecución
automática", `Principio 21`). Pero significa que "acumular histórico
suficiente" no basta por sí solo para tener `OpportunityEvaluation`
reales acumulándose: hace falta un **paso de orquestación** nuevo,
todavía no diseñado en ningún documento de Fase 3, que conecte captura
→ Policy Engine → persistencia, para que el histórico de decisiones
(no solo de precios) empiece a existir.

### 1.7 Hallazgo menor — tasa de fallo de `raw_captures`, no bloqueante

817/1851 (44%) de las capturas crudas fallaron. Desglose real:
`sofascore` → **815** fallos `http_403` (bloqueo de IP/WAF, **ya
documentado y manejado como degradación aceptable** en
`src/pipelines/tennis_pipeline.py` — el pipeline continúa sin ese
enriquecimiento, `SourceStatus.FAILED` se registra pero no bloquea); 2
fallos de resolución DNS aislados (`espn_tennis`, `mlb` — errores
puntuales de red, no un patrón). No requiere acción en Fase 4, se deja
documentado para que no se re-descubra como sorpresa.

### 1.8 Hallazgos de la revisión arquitectónica del usuario (2026-08-01, Revisión 2)

Verificados contra código real antes de aceptar cualquiera de los 3
puntos planteados por el usuario — ninguno se incorporó por parecer
razonable en abstracto:

- **`event_results` no tiene restricción `UNIQUE` sobre `event_id`**
  (`history_repository.py` — `CREATE TABLE event_results`, solo un
  índice no único). El propio docstring de `sync_mlb_event_results` lo
  admite explícitamente: "Esto NO cambia el contrato append-only de
  `HistoryRepository` (que sigue sin deduplicar nada por sí mismo)". La
  deduplicación hoy es responsabilidad exclusiva del llamador
  (`get_results_for_event` antes de insertar) — un caller distinto, una
  ejecución concurrente, o una inserción manual podría producir
  duplicados reales, no hipotéticos. **Confirma el punto 3 del usuario.**
- **`build_mlb_training_dataset`/`build_tennis_training_dataset`
  (`src/models/mlb_baseline.py:142`, `tennis_baseline.py:118`) ya
  resuelven duplicados por `event_id` tomando el más reciente por
  `recorded_at`** ("puede haber correcciones") — pero **sin verificar
  si los valores en conflicto realmente difieren**. Un bug real que
  produjera un resultado incorrecto seguido de uno correcto (o
  viceversa) se trataría igual que una corrección legítima, sin ninguna
  señal visible de que ocurrió. **Gap real, no cubierto hoy por ningún
  mecanismo — confirma más el punto 3.**
- **CANCELLED/POSTPONED ya se excluyen del dataset de entrenamiento**
  (`excluded_non_binary_result`, ambos builders) — pero solo como efecto
  secundario silencioso de construir el dataset, nunca como un chequeo
  previo explícito e inspeccionable antes de decidir si vale la pena
  intentar entrenar.
- **La cobertura (features con resultado ya sincronizado, sobre el
  total de features) ya se calcula implícitamente** vía el contador
  `excluded_no_result` de ambos builders — es literalmente
  `1 - coverage`. No existe hoy como una métrica nombrada, expuesta
  antes del entrenamiento, ni como parte de ningún gate formal.
  **Confirma el punto 2 del usuario: la señal ya existe en el código,
  solo falta nombrarla y convertirla en un chequeo previo.**

Conclusión: los 3 puntos se incorporan al plan (§2, §3, §6) porque cada
uno corrige un gap verificado en el código existente, no porque "suenen
bien" — consistente con la Regla 1 de la metodología.

---

## 2. Respuesta a la pregunta central: ¿hay histórico suficiente para entrenar?

**No — de forma inequívoca, y no es una cuestión de "todavía no", sino
de un mecanismo que aún no se ha activado ni una sola vez.**

Umbrales ya definidos en Fase 1/2 (no inventados para este plan):

| Modelo | Umbral mínimo | Constante | Muestras etiquetadas disponibles hoy |
|---|---|---|---|
| MLB — clasificador (`mlb_baseline.py`) | 300 | `DEFAULT_MIN_TRAINING_SAMPLES` | **0** |
| MLB — Elo (`mlb_elo.py`, más permisivo a propósito) | 50 | `DEFAULT_MIN_GAMES` | **0** |
| Tennis — clasificador (`tennis_baseline.py`) | 30 | `DEFAULT_MIN_TRAINING_SAMPLES_TENNIS` | **0** |

Incluso si se sincronizaran resultados hoy mismo para *todos* los
eventos ya capturados (56 MLB, 205 tennis), MLB seguiría muy por debajo
de su umbral de clasificador (56 < 300; sí superaría el umbral,
más permisivo, del baseline Elo). Tennis, en cambio, ya tiene volumen
bruto de eventos potencialmente suficiente (205 > 30) — **si** esos
eventos ya finalizaron y **si** se sincronizan. La proyección a ritmo
observado (~14 eventos MLB/día, ~51 eventos tennis/día en los días con
captura activa) sugiere que MLB necesitaría del orden de 3 semanas
adicionales de captura activa y continua para alcanzar 300 muestras
etiquetadas — una estimación aproximada a partir de una cadencia
irregular (4 de 7 días), no una garantía.

**Conclusión operativa**: Fase 4 no puede empezar por "entrenar un
calibrador" (paso 2 del roadmap propuesto al cierre de Fase 3). Debe
empezar por resolver por qué `event_results` está en cero — eso es
lo que bloquea todo lo demás, no el volumen de `event_snapshots`.

**Corrección incorporada en la Revisión 2**: la tabla de arriba, por sí
sola, es insuficiente incluso una vez `event_results` deje de estar en
cero. `N_min` mide un conteo absoluto de `event_results`, no qué
fracción de las `feature_snapshots` capturadas terminan teniendo un
resultado utilizable. Es posible cumplir `event_results.count() >= 300`
y aun así tener una cobertura de unión (features con resultado ÷
features totales) muy baja, si los resultados sincronizados provienen
de un subconjunto de eventos no representativo (p. ej. solo los días en
que la máquina no durmió). §1.8 confirma que esta señal ya se calcula
implícitamente (`excluded_no_result` en `build_mlb_training_dataset`/
`build_tennis_training_dataset`) pero nunca se expone como gate — se
formaliza como **Coverage Gate** en §6, Paso 4.2.

---

## 3. Decisiones pendientes D-4A / D-4B (NUEVAS, no resueltas en este documento)

**Separadas en la Revisión 2** (originalmente una sola D-4) a petición
del usuario: backfill puntual y sincronización permanente son acciones
operativas de riesgo distinto y deben aprobarse por separado, igual que
`DATA_RETENTION_POLICY.md` ya separó "diseñar la política" de "cargar el
LaunchAgent" como dos puntos de aprobación independientes. Backfill es
una ejecución única, acotada, fácil de razonar de principio a fin;
automatizar es un compromiso operativo permanente (cadencia, superposición
con otros LaunchAgents, mantenimiento) — mezclarlas en una sola decisión
oscurecía esa diferencia de alcance y de reversibilidad.

### D-4A — Backfill histórico inicial de `event_results` (ejecución única)

Poblar `event_results` retroactivamente para todo lo ya capturado
(2026-07-25 en adelante), una sola vez. Acción read-mostly: los scripts
(`sync_mlb_results.py`/`sync_tennis_results.py`, sin cambios) leen de la
API pública correspondiente y escriben únicamente vía
`save_event_result` (append-only, mismas garantías que
`event_snapshots`/`feature_snapshots`). No requiere ningún LaunchAgent
nuevo, no es un compromiso permanente — se ejecuta, se verifica el
resultado (`event_results.count() > 0`), termina.

**Alternativas**: (1) ejecutar ya, con `--lookback-days` suficiente para
cubrir el 2026-07-25 (recomendada — sin costo de esperar, el mecanismo
ya existe y está probado desde Fase 2); (2) no ejecutar todavía. No hay
una alternativa intermedia razonable para una acción de una sola vez,
reversible en el sentido de que no compromete nada a futuro por sí sola.

**Recomendación**: ejecutar. Es la única forma de que exista, hoy,
aunque sea una muestra pequeña, algo etiquetado sobre lo cual razonar
(incluido correr el futuro Coverage Gate y la auditoría de calidad de
labels de §6 con datos reales en vez de cero filas).

### D-4B — Sincronización continua y automática de `event_results` (responsabilidad permanente)

Decidir si, además del backfill puntual (D-4A), se automatiza la
sincronización hacia adelante — para que `event_results` deje de
depender de que alguien recuerde ejecutar el script manualmente. Esta es
la parte que **sí** es una responsabilidad operativa permanente, del
mismo tipo que D-1 (activar el LaunchAgent horario) — requiere su propia
confirmación explícita, separada de D-4A, por la Regla 6 de la
metodología.

**Alternativa 1 — Tercer LaunchAgent nuevo (recomendada)**: mismo patrón
que `data-maintenance` (`.plist` versionado, `launchctl bootstrap` solo
con autorización explícita), cadencia diaria o cada pocas horas —
suficiente dado que los resultados de un evento no cambian una vez
`Final`/decidido, a diferencia de los precios de mercado que sí
necesitan cadencia horaria. Costo: diseño del `.plist` + tests del mismo
nivel que `data_maintenance.py` (ningún cambio a la lógica de sync ya
existente).

**Alternativa 2 — Seguir con invocación manual, sin automatizar**:
mantener el diseño original de Fase 2 (manual, "requiere autorización
aparte" — ya se está cumpliendo esa condición si el usuario elige esto).
Riesgo: `event_results` se desactualiza entre invocaciones, el histórico
etiquetado crece a saltos en vez de continuamente — ralentiza
directamente cuánto tarda en cumplirse GATE-0 y el Coverage Gate.

**Recomendación**: Alternativa 1. Es la única que hace que "dejar
acumular histórico real" (el punto 1 del roadmap de cierre de Fase 3)
sea cierto en la práctica también para resultados, no solo para
precios — sin depender de que una persona se acuerde de ejecutar un
script cada cierto número de días.

---

## 4. Alcance de Fase 4

### 4.1 Dentro de alcance (condicionado a datos suficientes, gate por gate)

1. Resolver D-4A (este documento, §3) — backfill puntual.
2. Resolver D-4B (este documento, §3) — decidir automatización permanente.
3. Diseñar el **orquestador** captura→Policy Engine→persistencia
   (hallazgo §1.6) — sin el cual nunca existirá histórico de
   `OpportunityEvaluation`, sea cual sea el volumen de mercado.
4. Verificación continua de GATE-0 **y del Coverage Gate** (no una
   migración única — un chequeo repetible: `feature_snapshots.count()`/
   `event_results.count()` por deporte vs. los umbrales de §2, más la
   fracción de features con resultado utilizable, formalizando la señal
   ya calculada implícitamente por `excluded_no_result`, §1.8).
5. Auditoría de calidad de labels (§6, Paso 4.2.1) — corre antes de
   cualquier entrenamiento, incluso si GATE-0/Coverage Gate ya se
   cumplen; un volumen suficiente con labels corruptos sigue sin ser
   entrenable.
6. Entrenar calibrador real (Platt/isotónica) — **solo** cuando GATE-0,
   Coverage Gate y la auditoría de labels pasen, para el deporte
   correspondiente.
7. Reintentar D-3 periódicamente (mismo mecanismo ya usado, sin diseño
   nuevo) — no bloquea el resto del roadmap, corre en paralelo.
8. Historical Backtesting real (etapa [2] de
   `SHADOW_MODE_AND_PROMOTION_GATES.md`) — solo tras (3)+(4)+(5)+(6).
9. Shadow Mode real (etapa [3]) y Paper Tracking real (etapa [4]) — solo
   tras (8), con sus propios promotion gates cuantificables ya
   especificados (`SHADOW_MODE_AND_PROMOTION_GATES.md` §3).
10. Recalibrar heurísticas provisionales (`HEURISTIC_V1`, umbrales de
    `PolicyManifest`) con evidencia real — solo tras (9).

### 4.2 Explícitamente fuera de alcance (sin cambios respecto a Fase 3)

- **Cualquier forma de ejecución automática de órdenes, o `src/risk/`**
  (Principio 21 — restricción dura, reafirmada de nuevo en este
  documento, no "más adelante").
- Diseñar la lógica de clasificación ENTER/WATCH/PASS sobre
  `SignalInputs` — depende transitivamente de (4.1: 6, 8, 9, 10), no
  empieza en Fase 4 salvo que todo lo anterior se cumpla dentro de esta
  fase (poco probable dado el ritmo de acumulación observado).
- Archivado en frío de `event_snapshots`/`feature_snapshots`/
  `event_results` (diferido explícitamente en `DATA_RETENTION_POLICY.md`
  §5, sin cambios).
- Eliminar/repropósito de `data/normalized/` (vestigio sin uso,
  señalado, no resuelto).
- Cualquier cambio al fee schedule de Kalshi sin verificación primaria
  (D-3, sin cambios de postura).

---

## 5. Orden de dependencia actualizado (reemplaza `FASE3_CIERRE_FINAL.md` §5)

```
D-4A (backfill puntual de event_results)  [decisión operativa, §3]
        |
        v
D-4B (¿automatizar sync continua?)  [decisión operativa separada, §3]
        |
        v
Orquestador captura -> Policy Engine -> OpportunityRepository  [código nuevo, §4.1.3]
        |
        v
Acumulación continua CON etiquetas (precios + resultados + decisiones)
        |
        v
GATE-0 (feature_snapshots + event_results >= N_min)
    AND Coverage Gate (fracción de features con resultado utilizable)   [chequeo repetible, §6 Paso 4.2]
        |
        v
Auditoría de calidad de labels (duplicados/conflictos/void/anomalías)  [chequeo repetible, §6 Paso 4.2.1]
        |
        +--> (en paralelo, sin bloquear lo anterior) reintentos periódicos de D-3
        |
        v
Entrenar calibrador real (por deporte, cuando GATE-0 + Coverage Gate + auditoría de labels pasen)
        |
        v
Historical Backtesting real -> Shadow Mode real -> Paper Tracking real
        |
        v
Recalibrar heurísticas provisionales con evidencia real
        |
        v
[FUERA DE ALCANCE DE FASE 4, condicionado] Diseño ENTER/WATCH/PASS
```

Diferencia clave respecto al roadmap propuesto al cierre de Fase 3: se
inserta D-4A/D-4B y el orquestador **antes** del primer paso ("dejar
acumular"), porque la auditoría de esta fase encontró que ese primer
paso, tal como estaba, nunca iba a producir datos entrenables por sí
solo.

---

## 6. Pasos ejecutables propuestos (numeración `Paso 4.N`, mismo patrón que Fase 3)

Cada paso requiere autorización explícita individual antes de
implementarse, según la metodología. Los pasos 4.3 en adelante son
**gated por datos** — no tienen fecha, tienen una condición verificable.

### Paso 4.0A — Resolver D-4A: backfill puntual de `event_results`
- **Prerrequisito**: aprobación de D-4A (§3).
- **Alcance**: ejecutar `sync_mlb_results.py --lookback-days N` (N
  suficiente para cubrir el 2026-07-25) y el equivalente de tenis, una
  vez, manualmente. Cero cambios de código.
- **Criterio de aceptación**: `event_results.count() > 0` verificado
  directamente contra `data/engine.db`, desglosado por deporte.
- **No incluye**: ningún cambio a `sync_mlb_results.py`/
  `sync_tennis_results.py` (funcionan según lo diseñado, verificado por
  lectura de código) ni automatización (eso es 4.0B, decisión separada).

### Paso 4.0B — Resolver D-4B: automatización de sync continua (si se aprueba)
- **Prerrequisito**: Paso 4.0A cerrado + aprobación separada de D-4B
  (§3) — puede aprobarse en el mismo momento que D-4A o diferirse, son
  decisiones independientes.
- **Alcance**: diseñar
  `local.prediction-market-engine.sync-results.plist` (mismo patrón que
  `data-maintenance`); tests del nuevo LaunchAgent si aplica lógica
  nueva (probablemente ninguna — los scripts ya existen y están
  testeados desde Fase 2).
- **Criterio de aceptación**: LaunchAgent nuevo cargado y con
  `LastExitStatus = 0` tras al menos una ejecución real, sin coincidir
  en horario con `run-e2e-historical` de forma que compita por el lock
  de `run_e2e.py` (verificar `pipeline_lock.py` antes de fijar la
  cadencia).

### Paso 4.1 — Orquestador: captura → Policy Engine → `OpportunityRepository`
- **Prerrequisito**: Paso 4.0A cerrado (no estrictamente dependiente en
  código, pero sin resultados el orquestador solo produciría
  `PolicyDecision` con `ev_neto_strength`/mínimos críticos en `None` —
  mismo hallazgo ya probado en Paso 3.4.4 de Fase 3, útil para
  contract-testing pero no para acumular decisiones evaluables).
- **Diseño completo**: [`ORCHESTRATOR_SPEC.md`](ORCHESTRATOR_SPEC.md)
  (propuesto 2026-08-01, pendiente de aprobación) — resuelve la
  pregunta abierta de dónde vive el orquestador (dentro de
  `run_e2e.py`, §2.2 de ese documento) y documenta 3 decisiones que
  requieren aprobación explícita antes de implementar (umbrales
  globales del `PolicyManifest`, mapeo `PROVISIONAL_V1` de
  `ConfidenceProfile`, evaluar uno o ambos lados YES/NO), más 2
  enmiendas aditivas necesarias a código ya cerrado de Fase 1/2/3
  (`MlbPipelineResult`/`TennisPipelineResult`, y una rectificación de
  contrato en `OpportunityEvaluation.model_version` — mismo error ya
  corregido una vez en `CalibrationOutput` durante el Paso 3.1).
- **Criterio de aceptación**: tablas `opportunities`/
  `opportunity_evaluations` existen y tienen filas reales en
  `data/engine.db`; cero cambios de comportamiento en `src/policy/`,
  `src/opportunity/` (código de Fase 3 ya cerrado, reutilizado tal
  cual) — ver `ORCHESTRATOR_SPEC.md` §12 para el criterio completo.

### Paso 4.2 — Verificación de GATE-0 y Coverage Gate como chequeo repetible
- **Alcance**: función pura + script/reporte que evalúe, por deporte:
  (a) GATE-0 — `feature_snapshots.count()`/`event_results.count()`
  contra los 3 umbrales de §2; (b) **Coverage Gate** (nuevo, Revisión
  2) — la fracción de `feature_snapshots` que terminan con un resultado
  utilizable (`PARTICIPANT_A_WON`/`PARTICIPANT_B_WON`, no
  CANCELLED/POSTPONED, sin fuga temporal), reutilizando literalmente la
  misma lógica de exclusión ya escrita en `build_mlb_training_dataset`/
  `build_tennis_training_dataset` (§1.8) en vez de reimplementarla —
  ambos builders devuelven `warnings` con los contadores
  `excluded_no_result`/`excluded_non_binary_result`/`excluded_leakage`;
  este paso los expone como una métrica nombrada e inspeccionable antes
  de intentar entrenar, no después. **Sin umbral fijado todavía** para
  el Coverage Gate — el propio usuario pidió no fijar uno arbitrario
  ahora; se decide con evidencia real cuando GATE-0 esté cerca de
  cumplirse.
- **Invocable manualmente en cualquier momento** (no un gate automático
  que desbloquee nada por sí solo — solo informa, mismo espíritu que el
  resto de los chequeos de este proyecto).
- **Criterio de aceptación**: reporte reproducible, sin efectos
  secundarios, mismo patrón `now` inyectable que el resto del proyecto;
  cero duplicación de la lógica de exclusión ya existente en los dos
  dataset builders.

### Paso 4.2.1 — Auditoría de calidad de labels (nuevo, Revisión 2, diseño únicamente en este documento)
No se implementa en este documento — se incorpora al roadmap porque
§1.8 encontró gaps reales, no hipotéticos, en la integridad de
`event_results`. Corre **antes** de cualquier entrenamiento, incluso si
GATE-0 y el Coverage Gate ya pasaron: volumen suficiente con labels
corruptos sigue sin ser entrenable, y ninguno de los dos gates de arriba
lo detectaría por sí solo.

- **Alcance propuesto** (a diseñar en detalle cuando se autorice el
  paso, no antes): función pura de auditoría, sin efectos secundarios,
  sobre `HistoryRepository.get_all_event_results()` +
  `get_all_feature_snapshots()`, que detecte y reporte (nunca corrija
  automáticamente — cualquier corrección de dato es una decisión humana,
  no una heurística):
  - **Resultados en conflicto por `event_id`** (mismo evento, múltiples
    filas de `event_results` con `result` distinto entre sí) — hoy
    invisible, `build_mlb_training_dataset` los resuelve en silencio
    tomando el más reciente (§1.8); este paso lo convierte en una señal
    explícita, sin cambiar esa resolución por defecto.
  - **Duplicados exactos** (misma fila, mismo `result`, reinsertada) —
    inocuos para el dataset builder (mismo valor, no importa cuál se
    tome) pero indicativos de un bug en el llamador si aparecen.
  - **Mercados cancelados/void ya sincronizados como tales**
    (`CANCELLED`/`POSTPONED`) — contarlos explícitamente, ya excluidos
    del dataset por diseño (`excluded_non_binary_result`), pero útil
    verlos como proporción del total para detectar un problema
    sistemático de fuente (p. ej. muchos `Postponed` reales de un tramo
    de temporada, no un error).
  - **Eventos con `feature_snapshots` pero sin ningún `event_results`**
    ("sin resolución") — mismo número que ya computa el Coverage Gate
    (Paso 4.2); este paso lo reutiliza, no lo recalcula por separado.
  - Cualquier otra anomalía que surja al implementar (p. ej. `sport`
    inconsistente entre `event_snapshots` y `event_results` para el
    mismo `event_id`) se reporta como hallazgo nuevo en su momento, no
    se anticipa aquí sin evidencia.
- **Relación con el Coverage Gate (Paso 4.2)**: complementarios, no
  duplicados — el Coverage Gate mide *cuánto* está etiquetado: la
  auditoría mide *si lo que está etiquetado es confiable*. Ambos
  reutilizan la misma fuente de verdad (`HistoryRepository`) para no
  mantener dos implementaciones de la misma pregunta.
- **Criterio de aceptación (cuando se autorice)**: reporte reproducible;
  ningún entrenamiento real (Paso 4.3+) procede mientras la auditoría
  reporte anomalías sin resolver explícitamente por el usuario.

### Paso 4.3 — Diseño completo: [`MODEL_TRAINING_SPEC.md`](MODEL_TRAINING_SPEC.md) (propuesto 2026-08-01, pendiente de aprobación)

Verificado contra el código real antes de diseñar (mismo protocolo que
`ORCHESTRATOR_SPEC.md`): "entrenar un calibrador real", tal como este
documento lo nombraba, **no es ejecutable todavía** — no existe ninguna
implementación de `Calibrator` (solo un `Protocol` + un doble de test),
y no existe ningún modelo base entrenado sobre el cual calibrar nada
(`data/models/` solo tiene `.gitkeep`). De los 3 candidatos (MLB
clasificador, MLB Elo, tenis clasificador), **solo tenis alcanza hoy su
propio umbral** (`dataset.size=600 >= 30`) — MLB clasificador (87/300) y
MLB Elo (**41/50, verificado con la función real de elegibilidad de
Elo, no con los conteos crudos de GATE-0**) siguen sin alcanzarlo.
`MODEL_TRAINING_SPEC.md` reencuadra el alcance a "entrenar el primer
modelo base real (tenis)" + corregir un falso positivo encontrado en
`GATE-0[mlb_elo]` del Paso 4.2 (el gate genérico no cubría la lógica de
elegibilidad específica de Elo) — la calibración real queda diferida
explícitamente a un paso futuro sin numerar, una vez exista un modelo
real que produzca probabilidades reales sobre las cuales calibrar.

### Paso 4.4+ — Gated, sin diseño detallado todavía
Historical Backtesting real, Shadow Mode real, Paper Tracking real,
recalibración de heurísticas, y la calibración real diferida por el
Paso 4.3 (ver `MODEL_TRAINING_SPEC.md` §10): cada uno requiere su
propia auditoría de diseño cuando su gate correspondiente se cumpla
(mismo protocolo que abrió Fase 3), **no se diseñan en detalle en este
documento** porque hacerlo hoy — sin saber qué shape tendrá el
histórico real disponible entonces — sería el mismo tipo de fabricación
que la Regla 3 de la metodología prohíbe para fórmulas de costos,
aplicada ahora a diseño de pipeline. `MODEL_PIPELINE_SPEC.md`,
`SHADOW_MODE_AND_PROMOTION_GATES.md` y `EVALUATION_LEARNING_SPEC.md` ya
contienen la especificación de contrato para cuando llegue ese momento.

---

## 7. Riesgos

- **Confundir volumen de `event_snapshots` con volumen entrenable**
  (el riesgo central que esta auditoría existe para prevenir) — mitigado
  exigiendo que todo chequeo de suficiencia mire `event_results`, nunca
  solo `feature_snapshots`.
- **Cadencia de captura irregular** (4/7 días activos, "sueño de la
  máquina" ya documentado en `DATA_RETENTION_POLICY.md`) — alarga
  cualquier proyección de tiempo hasta GATE-0; no se propone solución en
  este documento (cambiar la política de energía de la máquina es una
  decisión fuera del alcance de este repositorio).
- **Sobreajuste de un calibrador entrenado con la primera cohorte
  pequeña que cruce el umbral mínimo** — el umbral mínimo (300/50/30) es
  un piso de suficiencia, no una garantía de generalización; Paso 4.3+
  debe decidir explícitamente sobre validación out-of-time, no solo
  volumen bruto.
- **Fuga temporal al construir el dataset de entrenamiento** — riesgo ya
  identificado y mitigado por diseño en Fase 3
  (`known_result` Hard Block, separación estricta `event_results` vs.
  `event_snapshots`, `TEMPORAL_REPRODUCIBILITY_SPEC.md`) — se reafirma
  aquí, no se re-diseña.
- **D-3 sigue bloqueando `net_ev_status=COMPUTED`** — cualquier backtest
  o shadow mode de Fase 4 operará con EV neto `UNKNOWN` mientras D-3 no
  se resuelva; esto es una limitación conocida heredada, no nueva de
  Fase 4, y no bloquea el resto del roadmap (Alternativa recomendada:
  seguir reintentando en paralelo, §4.1.7).
- **Alta cobertura absoluta enmascarando baja cobertura de unión**
  (nuevo, Revisión 2) — `event_results.count() >= N_min` no garantiza
  que esas filas correspondan a eventos con `feature_snapshots`
  utilizables; mitigado por el Coverage Gate (Paso 4.2), que mide la
  intersección, no los dos conteos por separado.
- **Resultados en conflicto silenciosamente resueltos por
  "el más reciente gana"** (nuevo, Revisión 2, confirmado en código,
  §1.8) — `event_results` no tiene `UNIQUE` sobre `event_id`; un bug de
  sync que escriba un resultado incorrecto y luego el correcto (o
  viceversa) es indistinguible hoy de una corrección legítima; mitigado
  por la auditoría de calidad de labels (Paso 4.2.1), que hace visible
  el conflicto sin cambiar la resolución por defecto del dataset
  builder.

---

## 8. Criterios de aceptación de Fase 4 (a nivel de fase, no de paso)

A diferencia de Fase 3 (alcance de código fijo, "Done" = todo
implementado), Fase 4 es **dependiente de datos** — su criterio de
cierre no es una fecha ni una lista fija de commits, sino:

- D-4A resuelta y verificada (`event_results.count() > 0`, backfill
  ejecutado).
- D-4B resuelta explícitamente en algún sentido (automatizada, o
  conscientemente dejada manual) — no puede quedar implícita.
- Orquestador real produciendo `OpportunityEvaluation` persistidas
  contra datos de mercado reales, verificable directamente en
  `data/engine.db`.
- GATE-0 **y** Coverage Gate evaluados y su resultado (cumplido o no,
  por deporte) reportado con números reales, no proyectado.
- Auditoría de calidad de labels ejecutada al menos una vez sobre el
  histórico real, con sus hallazgos (si los hay) explícitamente
  reportados y, para cualquier entrenamiento que proceda, resueltos por
  el usuario — no simplemente ignorados por tener volumen suficiente.
- Si GATE-0 y Coverage Gate se cumplen para al menos un deporte dentro
  de esta fase, y la auditoría de labels no reporta anomalías sin
  resolver: calibrador entrenado, backtesting real ejecutado, resultados
  reportados con intervalos de confianza (`CONTRACTS_FASE3.md` §14),
  nunca un punto estimado sin incertidumbre.
- Si alguno de los tres gates no se cumple para ningún deporte: Fase 4
  se cierra igualmente en el punto donde el dato real lo permita (mismo
  espíritu que D-3 en Fase 3 — "reencuadrada, no resuelta, no bloquea el
  cierre formal de la fase si la infraestructura queda lista y
  documentada").
- 927+ tests pasando en todo momento, `v2.0-baseline` intacto,
  `data/models/` limpio salvo el/los modelo(s) real(es) que se entrenen
  y comiteen explícitamente si los tres gates (GATE-0, Coverage Gate,
  auditoría de labels) se cumplen.

---

## 9. Próximo paso

Este documento es una propuesta de arquitectura y alcance, no una
autorización para empezar a escribir código. Antes de tocar `src/` en
Fase 4, se necesitan explícitamente:

1. **Decisión sobre D-4A** (§3) — ejecutar el backfill, ¿ya o después?
2. **Decisión sobre D-4B** (§3) — automatizar con un tercer LaunchAgent,
   o mantener invocación manual. Independiente de D-4A.
3. **Aprobación del alcance de §4** y del orden de dependencia de §5,
   incluyendo el Coverage Gate y la auditoría de calidad de labels como
   pasos gated (Paso 4.2/4.2.1) — sin umbral de cobertura fijado
   todavía, a decidir con evidencia real más adelante.
4. **Respuesta a la pregunta de diseño abierta del Paso 4.1** (dónde
   vive el orquestador) — puede diferirse hasta que se autorice
   específicamente ese paso, no bloquea aprobar el resto del documento.

Una vez aprobado, se procede paso a paso exactamente como en Fase 3:
autorización → implementación → tests del paso → suite completa →
auditoría → `CONTINUITY.md` → commit.
