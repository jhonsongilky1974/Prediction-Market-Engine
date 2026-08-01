# Diseño del Orquestador — Paso 4.1 (PROPUESTO, NO APROBADO)

**Estado: diseño para aprobación. Cero código escrito.** Responde a la
pregunta de diseño que `FASE4_EXECUTION_PLAN.md` §6 (Paso 4.1) dejó
explícitamente abierta: dónde vive el orquestador y cómo conecta la
captura (Fase 1/2) con el Policy Engine/Opportunity Lifecycle (Fase 3),
que hoy existen como librería pura, probada, pero **nunca ejecutada
contra datos reales** (hallazgo §1.6 de `FASE4_EXECUTION_PLAN.md`).

Este documento sigue el mismo protocolo que toda decisión de arquitectura
en este proyecto: investigación del código real primero (no se asume
nada de lo que la documentación de Fase 3 sugiere), hallazgos reportados
explícitamente, decisiones abiertas señaladas sin fabricar valores,
alternativas concretas donde aplica. No se implementa nada hasta
aprobación explícita.

---

## 1. Hallazgos previos al diseño (investigación de código real)

Verificados directamente contra el código, no asumidos de la
documentación de cierre de Fase 3.

### 1.1 No existe ningún compositor de `SignalInputs`

`grep -rn "SignalInputs(" ` fuera de `tests/` no tiene resultados. Los
7 campos de `SignalInputs` (`src/signals/signal_schema.py:61-92`) se
producen hoy en 5 módulos distintos de Fase 2
(`mlb_baseline.py`/`tennis_baseline.py`, `market_pricing.py`,
`edge.py`, `expected_value.py`, `quality_score.py`), pero **ningún
módulo de `src/` los combina**. El único lugar que construye un
`SignalInputs` completo es `tests/unit/fase3_factories.py`, con valores
literales de prueba — no reutiliza ningún cálculo real. **El
orquestador es el primer código de todo el proyecto en ensamblar un
`SignalInputs` desde datos vivos.**

### 1.2 No existe ningún compositor de `ConfidenceProfile`

`grep -rn "ConfidenceProfile(" ` fuera de `tests/` solo encuentra la
propia definición de la clase (`src/policy/schemas.py:48`). `soft_score.py`,
`evidence_engine.py` y `decision.py` **consumen** `ConfidenceProfile`,
pero nada en `src/` lo **produce**. Ver §9.2 para la propuesta.

### 1.3 No existe ningún `PolicyManifest` de producción

`config/policy/` contiene únicamente `.gitkeep` (verificado con `ls -la`).
`grep -rn "PolicyManifest(" ` fuera de `tests/` no tiene resultados de
instanciación. **No hay nada que `decide()` pueda cargar hoy.** Tampoco
existe ningún valor por defecto para `enter_global_threshold`/
`watch_global_threshold` en `src/` — en los tests, ambos son siempre
parámetros explícitos del caso de prueba, nunca una constante con
nombre. Ver §9.1 — este documento **no** propone números para esos dos
campos.

### 1.4 Contradicción de contrato encontrada: `OpportunityEvaluation.model_version`

`src/opportunity/schemas.py:124` declara `model_version: str`
(obligatorio, no `Optional`). Pero `PModelOutput.model_version`
(`src/models/base.py:55`) es `Optional[str]`, y en producción **siempre**
es `None` hoy (`data/models/` solo tiene `.gitkeep` — ningún modelo
entrenado existe). Esta es **exactamente la misma clase de error ya
encontrada y corregida una vez** en `CalibrationOutput.model_version`
durante el Paso 3.1 (`CONTINUITY.md` §0.3.1) — pero esta vez en
`OpportunityEvaluation` (Paso 3.5, ya cerrado), nunca detectada porque
ningún test de Fase 3 construye un `OpportunityEvaluation` con un
`model_version` real derivado de `PModelOutput` (todos usan un string
literal de prueba). **Sin corregir esto, ninguna `OpportunityEvaluation`
real puede construirse hoy** — el orquestador fallaría en el 100% de
los casos, no en un caso extremo. Ver §8.2 para la corrección propuesta.

### 1.5 `MlbPipelineResult`/`TennisPipelineResult` no exponen lo que el orquestador necesita

`run_mlb_pipeline`/`run_tennis_pipeline` (`src/pipelines/mlb_pipeline.py`/
`tennis_pipeline.py`) ya calculan `MlbFeatureInputs`/`TennisFeatureInputs`
y `data_cutoff_timestamp` por registro (los usan para
`persist_mlb_feature_snapshot`/`predict_mlb_baseline` internamente), pero
`MlbPipelineResult`/`TennisPipelineResult` (los `@dataclass` que
devuelven al llamador) **solo exponen `records`/`steps`** — no exponen
esos objetos. El orquestador los necesita para `predict_mlb_baseline`
(no puede reconstruirlos sin recomputar features dos veces, arriesgando
inconsistencia con lo ya persistido en `feature_snapshots`). Ver §8.1
para la enmienda aditiva propuesta.

### 1.6 `decide()` nunca lanza excepción — todo lo anterior a esa llamada sí puede

`decide()` (`src/policy/decision.py`) envuelve internamente su lógica en
`try/except Exception`, traduciendo cualquier fallo interno a
`PolicyDecision(signal_type=PASS, disposition=INVALID_ANALYSIS, ...)` —
nunca propaga. Esto simplifica el manejo de errores del orquestador
**solo alrededor de esa llamada puntual**: todo lo que el orquestador
ensambla ANTES de `decide()` (`SignalInputs`, `CalibrationOutput`,
`QualityScoreOutput`, `ConfidenceProfile`, `PayoffEstimate`,
`EvidenceItem[]`, `AnalysisHealth`) no tiene ninguna protección
equivalente — una excepción ahí sí puede propagar. Ver §5.

### 1.7 `ENTER` es estructuralmente inalcanzable hoy — esperado, no un bug

`ev_neto_strength` (`soft_score.py`) deriva de
`PayoffEstimate.ev_to_settlement`, que es **siempre `None`** mientras
`net_ev_status` sea `UNKNOWN` (D-3 sin resolver — ver
`FASE4_EXECUTION_PLAN.md` §1.3). Un componente crítico en `None` nunca
pasa su mínimo, así que `check_enter_eligible_by_soft_score` nunca
puede devolver `True`, sin importar qué tan bueno sea el resto —
verificado por test ya existente en Fase 3
(`test_ev_neto_strength_unknown_blocks_enter_even_with_everything_else_perfect`).
Además, `unresolved_side_mapping` (D-2) dispara `WATCH` cada vez que
`side_selection_confidence < 0.72` — frecuente dado el volumen real
observado. **El orquestador debe esperar únicamente `WATCH`/`PASS`
hasta que D-3 se resuelva** — esto se documenta como comportamiento
esperado en los criterios de aceptación (§12), no como algo a corregir
en este paso.

### 1.8 `ExplanationOutput` no tiene ningún punto de persistencia

`grep -rn "ExplanationOutput"` fuera de `src/explainability/` no
aparece en ningún repositorio de almacenamiento. `explain()` solo
necesita `PolicyDecision` + `EvidenceItem[]`, ambos ya persistidos
dentro de `OpportunityEvaluation` — **confirma que `explain()` es
deliberadamente derivable bajo demanda, no algo que este paso deba
llamar ni persistir.** Fuera de alcance del orquestador (ver §3).

---

## 2. Arquitectura

### 2.1 Ubicación: nuevo paquete `src/orchestration/`

Ni `src/policy/` ni `src/opportunity/` son candidatos correctos: las
reglas de dependencia de `ARCHITECTURE_FASE3.md` §4 mantienen a todos
los paquetes de Fase 3 deliberadamente ciegos entre sí salvo por tipos
puntuales (`opportunity/` conoce `policy/schemas.py` solo para tipos,
nunca lógica). El orquestador, por definición, necesita conocer
**todos** los paquetes (`signals/`, `models/`, `pricing/`,
`uncertainty/`, `calibration/`, `payoff/`, `evidence/`, `health/`,
`policy/`, `opportunity/`, `storage/`) — meterlo dentro de cualquiera
de ellos rompería esa regla para siempre. Un paquete nuevo,
exclusivamente de composición, preserva la regla: todo lo de abajo
sigue sin saber que `orchestration/` existe (test de arquitectura
propuesto en §11 lo verifica).

```
src/orchestration/
    signal_builder.py            -- build_signal_inputs()
    confidence_profile_builder.py -- build_confidence_profile()
    decision_pipeline.py          -- evaluate_opportunity() + run_decision_pipeline()
```

### 2.2 Wiring: dentro de `run_e2e.py::_run()`, no un script/LaunchAgent nuevo

Resuelve la pregunta abierta de `FASE4_EXECUTION_PLAN.md` §6. Se añade
como una **tercera etapa** dentro de `_run()` (`scripts/run_e2e.py:113`),
después de los bloques MLB y tenis ya existentes, operando directamente
sobre `mlb_result.records`/`tennis_result.records` — los objetos
`NormalizedRecord` que la propia corrida acaba de construir y persistir,
en memoria, sin volver a tocar la base de datos para leerlos.

**Por qué esta opción y no un script/LaunchAgent independiente** (la
alternativa considerada, re-escanear `get_all_event_snapshots()`):

| | Dentro de `run_e2e.py` (elegida) | Script/LaunchAgent independiente |
|---|---|---|
| Re-parseo de JSON | Ninguno — reutiliza los objetos ya en memoria | Requiere `NormalizedRecord.model_validate_json(...)` por fila, más `MlbFeatureInputs` no persistidos en absoluto (ver §1.5) |
| Lock | Reutiliza `data/.run_e2e.lock` ya adquirido | Requeriría su propio lock + coordinar qué eventos ya se decidieron (no existe cursor en `HistoryRepository`, ver hallazgo de la investigación previa) |
| Frescura | Evalúa el evento en el mismo instante en que se captura | Ventana de espera hasta la siguiente corrida del script nuevo |
| Escalabilidad | Acotada al volumen de una corrida horaria (ya probado) | `get_all_event_snapshots()` es un escaneo completo sin cursor — "deuda de escalabilidad ya documentada", empeora con el tiempo |
| Cambio requerido | Aditivo a `_run()` + 2 enmiendas aditivas señaladas (§8) | Cero cambios a `run_e2e.py`, pero introduce deuda nueva |

Recomendación: la opción elegida. Costo: `run_e2e.py` (Fase 1/2, ya
cerrado) recibe una adición — señalado explícitamente, no oculto, y es
estrictamente aditivo (nuevo bloque de código al final de `_run()`,
cero líneas existentes modificadas salvo las dos enmiendas de §8).

### 2.3 Extensibilidad — `SportAdapter` (añadido tras aprobación del usuario, 2026-08-01)

**Requisito añadido explícitamente por el usuario al aprobar este
diseño**: el núcleo del orquestador debe permitir incorporar deportes
futuros mediante nuevos pipelines/adaptadores, sin modificar
`src/orchestration/decision_pipeline.py`.

Barrido completo de `src/` (`grep -rln "Sport\.MLB\|Sport\.TENNIS"`)
confirma que **todo** lo que el orquestador invoca aguas abajo de
`predict_fn` ya es genérico por deporte — `market_pricing.py`,
`edge.py`, `expected_value.py`, `quality_score.py`,
`calibration_layer.py`, `payoff_model.py`, `evidence_engine.py`,
`analysis_health.py` y el propio `decide()` operan únicamente sobre
`NormalizedRecord`/`PModelOutput`/`Sport` (el enum, como dato, nunca
como rama de código) — el único lugar del *Policy Engine* que sí
branchea por deporte es la regla `unconfirmed_pitcher`
(`hard_rules.py:341`, `record.sport == Sport.MLB`), y esa rama vive
dentro de `hard_rules.py` (Fase 3, sin tocar) y además solo se activa
si el `PolicyManifest` de ese deporte la incluye en
`hard_hold_rules` — el orquestador no necesita saber que existe.

Las **únicas** dos piezas realmente específicas por deporte, ya
identificadas en el flujo (§4.2, pasos 1 y sus dependencias), son
`predict_fn`/`load_artifact_fn` — y ambas firmas ya coinciden
estructuralmente entre MLB y tenis:

```python
predict_mlb_baseline(record, inputs: MlbFeatureInputs, data_cutoff_timestamp, loaded_artifact) -> PModelOutput
predict_tennis_baseline(record, inputs: TennisFeatureInputs, data_cutoff_timestamp, loaded_artifact) -> PModelOutput
load_latest_mlb_artifact(models_dir=DATA_MODELS_DIR) -> Optional[Tuple[Any, MlbTrainedArtifact]]
load_latest_tennis_artifact(models_dir=DATA_MODELS_DIR) -> Optional[Tuple[Any, TennisTrainedArtifact]]
```

Se formaliza esto en un tipo nuevo, `SportAdapter`
(`src/orchestration/sport_adapter.py`), en vez de pasar
`predict_fn`/`load_artifact_fn` como parámetros sueltos:

```python
@dataclass(frozen=True)
class SportAdapter:
    sport: Sport
    predict_fn: Callable[[NormalizedRecord, Any, datetime, Optional[Tuple[Any, Any]]], PModelOutput]
    load_artifact_fn: Callable[[], Optional[Tuple[Any, Any]]]
```

`decision_pipeline.py` nunca importa `mlb_baseline`/`tennis_baseline`/
`registry` directamente — solo recibe un `SportAdapter` ya construido.
`run_e2e.py` (la capa de composición, ya conoce ambos deportes) arma
un registro:

```python
SPORT_ADAPTERS: Dict[Sport, SportAdapter] = {
    Sport.MLB: SportAdapter(Sport.MLB, predict_mlb_baseline, load_latest_mlb_artifact),
    Sport.TENNIS: SportAdapter(Sport.TENNIS, predict_tennis_baseline, load_latest_tennis_artifact),
}
```

**Incorporar un tercer deporte en el futuro** requiere, exclusivamente:
(1) su propio pipeline de captura (ya el patrón establecido en Fase
1/2, fuera del alcance del orquestador); (2) su propia
`predict_<deporte>_baseline`/`load_latest_<deporte>_artifact`; (3) un
`SportAdapter(...)` nuevo registrado en `SPORT_ADAPTERS`; (4) su propio
`config/policy/<deporte>_v1.json`. **Cero líneas de
`decision_pipeline.py`, `signal_builder.py` o
`confidence_profile_builder.py` cambian** — verificado por el test de
arquitectura de §11 (ningún import de `mlb_baseline`/`tennis_baseline`
dentro de `src/orchestration/`, salvo en el propio registro de
`run_e2e.py`, que es composición, no núcleo).

### 2.4 Diagrama de dependencias

```
scripts/run_e2e.py  (composición, ya existe)
        |
        +--> src/models/{mlb_baseline,tennis_baseline,registry}.py (Fase 2, sin cambios)
        |     -- construye SPORT_ADAPTERS: Dict[Sport, SportAdapter], §2.3
        |
        | (nuevo, tercer bloque en _run())
        v
src/orchestration/decision_pipeline.py  (nuevo, recibe un SportAdapter ya construido -- nunca importa mlb_baseline/tennis_baseline directamente)
        |
        +--> src/orchestration/signal_builder.py            (nuevo)
        +--> src/orchestration/confidence_profile_builder.py (nuevo)
        +--> src/orchestration/sport_adapter.py               (nuevo, tipo SportAdapter -- §2.3)
        |
        +--> src/pricing/market_pricing.py                            (Fase 2, sin cambios)
        +--> src/signals/{edge,expected_value}.py                     (Fase 2, sin cambios)
        +--> src/uncertainty/quality_score.py                         (Fase 2, sin cambios)
        +--> src/calibration/calibration_layer.py                     (Fase 3, sin cambios)
        +--> src/payoff/payoff_model.py                               (Fase 3, sin cambios)
        +--> src/evidence/evidence_engine.py                          (Fase 3, sin cambios)
        +--> src/health/analysis_health.py                            (Fase 3, sin cambios)
        +--> src/policy/{eligibility,hard_rules,soft_score,decision}.py (Fase 3, sin cambios -- decide() ya orquesta estas 4)
        +--> src/opportunity/{schemas,opportunity_repository}.py      (Fase 3, sin cambios)
        +--> src/storage/history_repository.py                        (Fase 2, sin cambios)
```

Ningún paquete existente importa `src/orchestration/` — dependencia en
un solo sentido, de arriba hacia abajo, verificable por test (§11).

---

## 3. Responsabilidades

| Módulo | Responsabilidad | NO responsable de |
|---|---|---|
| `signal_builder.py` | Ensamblar `SignalInputs` desde un `NormalizedRecord` + `MlbFeatureInputs`/`TennisFeatureInputs` + `PModelOutput`, para un lado (`Side`) dado. | Cargar el artefacto del modelo (se recibe ya cargado); calcular features (ya calculadas por el pipeline); decidir nada sobre elegibilidad/reglas. |
| `confidence_profile_builder.py` | Mapear `QualityScoreOutput` (Fase 2, ya calculado) a `ConfidenceProfile` (Fase 3). | Inventar ningún componente nuevo — cada campo se justifica contra un componente ya existente y aprobado, o queda `None` (§9.2). |
| `decision_pipeline.py::evaluate_opportunity()` | Para **un** `(NormalizedRecord, Side)`: construir, en orden, `SignalInputs` → `CalibrationOutput` → `ConfidenceProfile` → `PayoffEstimate` → `EvidenceItem[]` → `AnalysisHealth` → `PolicyDecision` (`decide()`), calcular `state_version`, persistir `Opportunity` + `OpportunityEvaluation`. | Cargar/guardar registros de mercado (ya hecho por `mlb_pipeline.py`/`tennis_pipeline.py`); modificar ninguna regla de `policy/`; llamar `explain()` (§1.8, fuera de alcance). |
| `decision_pipeline.py::run_decision_pipeline()` | Iterar sobre una lista de `NormalizedRecord` (un deporte, una corrida), ambos lados, con aislamiento de fallos por evento (§5), producir un resumen agregado imprimible (mismo patrón que `MlbResultsSyncSummary`). | Nada de captura/normalización (ya ocurrió antes de que esta función se invoque). |
| `scripts/run_e2e.py` (bloque nuevo en `_run()`) | Invocar `run_decision_pipeline()` una vez por deporte, con el `PolicyManifest` correspondiente ya cargado, imprimir el resumen. | Construir ningún objeto de dominio directamente — delega todo a `decision_pipeline.py`. |

---

## 4. Flujo de ejecución

### 4.1 Nivel batch — dentro de `_run()`, después de los bloques MLB/tenis existentes

```
mlb_result = run_mlb_pipeline(...)        # ya existe, sin cambios de comportamiento
tennis_result = run_tennis_pipeline(...)  # ya existe, sin cambios de comportamiento

# --- NUEVO ---
mlb_manifest = load_policy_manifest(CONFIG_POLICY_DIR / "mlb_v1.json")      # nuevo archivo, §10
tennis_manifest = load_policy_manifest(CONFIG_POLICY_DIR / "tennis_v1.json")
opp_repo = OpportunityRepository(db_path=repo.db_path)

mlb_summary = run_decision_pipeline(
    records=mlb_result.records,
    feature_inputs_list=mlb_result.feature_inputs_list,   # nuevo campo, §8.1
    feature_cutoffs=mlb_result.feature_cutoffs,             # nuevo campo, §8.1
    sport=Sport.MLB,
    history_repository=hist_repo,           # ya construido arriba, reutilizado
    opportunity_repository=opp_repo,
    policy_manifest=mlb_manifest,
    load_artifact_fn=load_latest_mlb_artifact,
    predict_fn=predict_mlb_baseline,
)
tennis_summary = run_decision_pipeline(..., sport=Sport.TENNIS, ...)

print_decision_summary(mlb_summary)
print_decision_summary(tennis_summary)
```

El artefacto del modelo (`load_latest_mlb_artifact()`) se carga **una
vez por corrida, no una vez por registro** — evita I/O de disco
repetido; hoy siempre devuelve `None` (sin modelo entrenado), pero el
diseño ya es correcto para cuando exista uno.

### 4.2 Nivel por-evento — `evaluate_opportunity(record, feature_inputs, data_cutoff_timestamp, side, ...)`

Orden de construcción (dependencia real entre objetos, no arbitrario —
cada paso usa la salida del anterior):

```
1. model_output        = predict_fn(record, feature_inputs, data_cutoff_timestamp, loaded_artifact)
2. quality_score_output = compute_quality_score(record, consensus=None, now=now)
   -- consensus=None: confirmado que compute_consensus_no_vig no tiene
      ningún llamador en producción hoy (odds_api nunca se importa en
      pipelines/scripts) -- no se fabrica un consenso que no existe.
3. calibration_output   = calibrate(model_output, calibrator=None, now=now)
   -- calibrator=None: ningún calibrador entrenado existe (mismo motivo
      que Fase 3, sin cambios).
4. confidence_profile   = build_confidence_profile(quality_score_output, opportunity_id, now)
                          [NUEVO, §9.2]

   -- SI record.market_id es None: no hay mercado emparejado, no hay
      nada que evaluar como oportunidad -- se cuenta como "sin mercado"
      en el resumen y se pasa al siguiente lado/registro, sin construir
      Opportunity ni llamar a nada más. (Alcance explícito, no un caso
      de error.)

   Para cada side en (Side.YES, Side.NO):
5.     selection_id      = compute_selection_id(record.market_id, side)
6.     opportunity_id     = compute_opportunity_id(record.event_id, selection_id)
7.     market_price       = market_price_yes(record) si side==YES, market_price_no(record) si side==NO
8.     edge               = compute_edge_yes/no(model_output, record)
9.     ev_bruto           = compute_ev_yes/no_bruto(model_output, record)
10.    ev_neto            = compute_ev_yes/no_neto(...) SI record.market.exchange_fee es None,
                            si no: capturado, registrado como hallazgo (ver §5), ev_neto=None
11.    signal_inputs      = build_signal_inputs(...)  [NUEVO, ensambla 7-10 + model_output + quality_score_output]
12.    payoff_estimate    = estimate_payoff(record, side, opportunity_id, platform="KALSHI", now=now)
13.    evidence_items     = collect_evidence(opportunity_id, record, calibration_output, confidence_profile, now=now)
14.    analysis_health    = compute_analysis_health(opportunity_id, record, quality_score_output, evidence_items, now=now)
15.    policy_decision    = decide(opportunity_id, record, signal_inputs, payoff_estimate,
                                    confidence_profile, analysis_health, data_cutoff_timestamp,
                                    history_repository, policy_manifest, now=now)
                            -- nunca lanza (§1.6)
16.    state_version      = (opp_repo.get_latest_opportunity(opportunity_id).state_version + 1) si existe, si no 1
17.    opp_repo.save_opportunity(Opportunity(...))
18.    eval_state_version = (mismo patrón que 16, sobre get_latest_evaluation)
19.    opp_repo.save_opportunity_evaluation(OpportunityEvaluation(...))
```

Pasos 1-4 se calculan **una vez por registro** (no dependen de `side`);
pasos 5-19 se repiten **una vez por lado** — evita recalcular
`model_output`/`quality_score_output`/`calibration_output`/
`confidence_profile` dos veces para el mismo evento.

### 4.3 Ciclo de vida de una `Opportunity` a través de corridas sucesivas

Cada corrida horaria que vuelve a capturar el mismo evento (todavía no
decidido) produce un **nuevo** `event_snapshot` y, por diseño ya
establecido en Fase 3 (`state_version`), una **nueva** fila de
`Opportunity`/`OpportunityEvaluation` con `state_version` incrementado
— esto es el comportamiento **previsto** del Opportunity Lifecycle
(re-evaluación conforme llega información nueva), no un riesgo. Se
documenta aquí para que quede explícito en el flujo, no solo implícito
en el esquema.

---

## 5. Manejo de errores y aislamiento de fallos

**Hallazgo relevante (§1)**: los bucles `for game in games` /
`for match in matches` de `mlb_pipeline.py`/`tennis_pipeline.py` **no
aíslan fallos por evento** hoy — una excepción no capturada aborta todo
el lote de ese deporte. El orquestador **no hereda esa fragilidad**:
es una decisión de diseño explícita, no una corrección del código
existente (que queda fuera de alcance, sin tocar).

```python
for record in records:
    try:
        # pasos 1-4 de §4.2 (comunes a ambos lados)
        ...
    except Exception as exc:
        summary.skipped_errors.append((record.event_id, "pre-side", repr(exc)))
        continue  # el resto del lote sigue

    for side in (Side.YES, Side.NO):
        try:
            # pasos 5-19 de §4.2
            ...
        except Exception as exc:
            summary.skipped_errors.append((record.event_id, side.value, repr(exc)))
            continue  # el otro lado y el resto del lote siguen
```

Dos niveles de aislamiento: uno por registro (para los pasos comunes),
uno por lado (para los pasos 5-19) — un fallo en el lado `YES` no
impide evaluar el lado `NO` del mismo evento.

**Caso especial: `compute_ev_yes/no_neto` con `exchange_fee` poblado**
(paso 10). Hoy `exchange_fee` es siempre `None` (D-3), así que esta
rama nunca se ejecuta en producción — pero si alguna vez cambiara sin
que D-3 esté resuelto, `compute_ev_yes/no_neto` lanza
`NotImplementedError` explícitamente (Fase 2, código existente, sin
tocar). El orquestador **no debe silenciar esto con un `except`
genérico que lo trate igual que cualquier otro error** — es una señal
operacional relevante (posible evidencia nueva para D-3), así que se
captura específicamente, se registra con una etiqueta distinta
(`summary.exchange_fee_populated_unexpectedly`, contador separado de
`skipped_errors`), y **no aborta** el resto del procesamiento de ese
lado (`ev_neto` cae a `None`, el resto de `SignalInputs` se construye
igual).

`decide()` (paso 15) no necesita su propio `try/except` — ya es
fail-safe (§1.6).

---

## 6. Recuperación / idempotencia

- **Sin mecanismo de reintento explícito.** Si el orquestador falla a
  mitad de un lote (p. ej. el proceso muere), los eventos ya
  procesados en esa corrida quedan con su `Opportunity`/
  `OpportunityEvaluation` persistidos (cada `save_*` es una
  transacción SQLite independiente); los eventos restantes de esa
  corrida simplemente no se evalúan en esta hora.
- **Autocorrección natural, no forzada**: la siguiente corrida horaria
  de `run_e2e.py` captura un `event_snapshot` nuevo para cualquier
  evento que siga vigente y lo evalúa de nuevo (nuevo `state_version`)
  — el mismo principio que ya tolera huecos de captura (`DATA_RETENTION_POLICY.md`
  §1: "ritmo irregular por sueño de la máquina"). Un evento que ya
  concluyó/desapareció entre corridas simplemente no vuelve a
  aparecer — no se fabrica una evaluación retroactiva.
- **`OpportunityRepository` ya impone su propia protección contra
  corrupción**: `save_opportunity`/`save_opportunity_evaluation`
  exigen `state_version == previous + 1` exactamente — si el
  orquestador leyera un `state_version` desactualizado (p. ej. por un
  bug de concurrencia), la escritura fallaría con `ValueError` en vez
  de crear un hueco o una versión duplicada silenciosa. Este error, si
  ocurre, cae dentro del aislamiento de fallos de §5 (se registra, no
  aborta el lote).
- **No se diseña ningún mecanismo de "reprocesar corridas fallidas"
  en este paso** — sería anticipar un problema no observado todavía;
  si el volumen de fallos reales lo justifica, es una extensión
  futura explícita, no algo a resolver preventivamente aquí.

---

## 7. Logs

Mismo patrón que **todo** el resto del proyecto: `print()`, sin el
módulo `logging` (verificado: solo 2 usos aislados de
`logger.warning` en todo `src/`, ninguno en ningún script). No se
introduce un patrón nuevo sin discutirlo aparte.

`run_decision_pipeline()` devuelve un resumen estructurado
(`DecisionPipelineSummary`, mismo espíritu que `MlbResultsSyncSummary`)
que `run_e2e.py` imprime, capturado por la redirección de `launchd` ya
existente (`logs/run_e2e.stdout.log`/`.stderr.log` — sin archivos de
log nuevos, ya que el orquestador vive dentro de `run_e2e.py`, §2.2):

```
=== Policy Engine / Opportunity Lifecycle: MLB ===
  Registros evaluados:            41
  Sin market_id (sin evaluar):     3
  Opportunities creadas:          76   (38 eventos x 2 lados)
  Evaluaciones creadas:           76
  signal_type=ENTER:               0   (esperado -- D-3 sin resolver, ver §1.7)
  signal_type=WATCH:               52
  signal_type=PASS:                24
  Errores (aislados, no abortan): 0
  exchange_fee poblado inesperadamente: 0
```

---

## 8. Enmiendas necesarias a código ya cerrado (Fase 2/3) — señaladas explícitamente

Ninguna de las dos siguientes es un cambio de comportamiento oculto —
ambas se reportan aquí para aprobación explícita antes de tocar
código ya comiteado, según la Regla 2 de la metodología.

### 8.1 `MlbPipelineResult`/`TennisPipelineResult` — campos aditivos

```python
# src/pipelines/mlb_pipeline.py (y el equivalente en tennis_pipeline.py)
@dataclass
class MlbPipelineResult:
    records: List[Any] = field(default_factory=list)
    steps: List[PipelineStepResult] = field(default_factory=list)
    feature_inputs_list: List[Optional[MlbFeatureInputs]] = field(default_factory=list)  # NUEVO
    feature_cutoffs: List[Optional[datetime]] = field(default_factory=list)               # NUEVO
```
Poblados en el mismo punto donde `mlb_pipeline.py` ya los calcula
internamente (línea donde arma `feature_inputs_list`/`feature_cutoffs`
para `zip(...)`, §1.5) — **cero cálculo nuevo, solo se dejan de
descartar**. Aditivo, retrocompatible: cualquier código existente que
ya desestructura `MlbPipelineResult` por posición o solo lee
`.records`/`.steps` sigue funcionando exactamente igual (mismo patrón
ya usado para `PolicyManifest.hard_rule_parameters` en Fase 3, §0.11).

### 8.2 `OpportunityEvaluation.model_version` — rectificación de contrato

```python
# src/opportunity/schemas.py:124
model_version: str            # actual, incorrecto
model_version: Optional[str] = None   # propuesto
```
Mismo patrón exacto que la rectificación ya aprobada y aplicada a
`CalibrationOutput.model_version` en el Paso 3.1 (`CONTINUITY.md`
§0.3.1) — mismo error de transcripción, mismo campo semántico, misma
corrección. Test nuevo espejo del ya existente
(`test_model_not_trained_case_has_none_model_version`, adaptado a
`OpportunityEvaluation`).

**Ninguna otra enmienda a código de Fase 1/2/3 es necesaria** —
verificado explícitamente contra `AnalysisHealth`, `PolicyManifest`,
`Opportunity` (§1, ningún otro campo obligatorio tiene esta
contradicción).

---

## 9. Decisiones abiertas que este documento NO resuelve

Tres puntos requieren tu aprobación explícita antes de implementar —
ninguno se decide unilateralmente aquí, seas indulgente conmigo, según
la Regla 2/3 de la metodología ("no fabricar").

### 9.1 `enter_global_threshold` / `watch_global_threshold` del `PolicyManifest`

No existe ningún valor precedente en todo `src/` (§1.3) — cualquier
número que proponga sería inventado. Tres alternativas:

**Alternativa 1 — Umbrales "razonables" intermedios (ej. enter=80,
watch=50)**: la opción más intuitiva, pero es fabricar exactamente el
tipo de número que la Corrección C del proyecto prohíbe sin evidencia
— quedaría marcado "PROVISIONAL" pero seguiría siendo inventado, no
derivado de nada real.

**Alternativa 2 — Umbrales "límite", sin pretender saber un corte real
(recomendada)**: `enter_global_threshold` fuera del rango alcanzable
(ej. `101.0` — el agregado nunca puede pasar de 100, así que `ENTER`
queda estructuralmente imposible por construcción, coherente y
explícito con el hallazgo §1.7, en vez de depender accidentalmente de
que `ev_neto_strength` sea `None`); `watch_global_threshold=0.0` — todo
lo que sobreviva a Hard Block/Hard Hold y tenga un `aggregate_soft_score`
calculable se clasifica `WATCH`, nunca se descarta a `PASS` por un
corte arbitrario de score. No pretende saber nada que no se sabe —
documenta la ausencia de evidencia en vez de simularla.

**Alternativa 3 — No construir ningún `PolicyManifest` todavía, dejar
el Paso 4.1 sin llamar a `decide()`**: descartada como impráctica —
`OpportunityEvaluation.policy_decision` es un campo obligatorio (no
`Optional`), así que sin un `PolicyDecision` no se puede persistir
ninguna evaluación en absoluto, vaciando el criterio de aceptación del
propio paso (§12).

**Recomendación**: Alternativa 2.

### 9.2 Mapeo de `ConfidenceProfile` (propuesta `PROVISIONAL_V1`, sujeta a aprobación)

Reutiliza únicamente componentes que `compute_quality_score` (Fase 2)
ya calcula — cero fórmulas nuevas, solo selección/promedio de números
ya aprobados:

| Campo `ConfidenceProfile` | Mapeo propuesto | Justificación |
|---|---|---|
| `data_quality` | `components["data_completeness"]` | Reuso directo, sin transformación |
| `market_quality` | promedio de `{bookmaker_dispersion, sample_size, market_liquidity}` (`None` los que falten, redistribuye — mismo patrón de `compute_quality_score`) | Los 3 componentes ya existentes más directamente relacionados con "calidad del mercado", no del evento |
| `operational_safety` | `components["freshness"] * 100` | Frescura ya modela literalmente riesgo operacional (dato desactualizado) |
| `operational_risk` | `100 - operational_safety` | Satisface el invariante ya exigido por el propio contrato (`operational_safety + operational_risk == 100`) |
| `model_reliability` | `None`, siempre, hoy | **No existe ninguna fuente real** — cero evaluaciones históricas (`EvaluationRecord`) existen todavía. Fabricar este campo violaría la Regla 3 directamente. Se redistribuye automáticamente en `soft_score.py` (mismo patrón ya usado en todo el proyecto para componentes ausentes). |
| `aggregate_confidence` | `quality_score_output.confidence` | Reuso directo del agregado `HEURISTIC_V1` ya aprobado, sin recalcular |
| `quality_score_component_ref` | `quality_score_output.confidence_config_version` (`"quality_score_v1"`) | Trazabilidad al origen exacto, sin inventar un identificador nuevo |

Etiquetado `PROVISIONAL_V1` en el docstring del módulo — mismo
tratamiento que `HEURISTIC_V1`/los umbrales provisionales ya existentes
en Fase 2/3: documentado como no calibrado, revisable cuando haya
evidencia real (Evaluation Framework, todavía andamiaje sin evaluaciones
reales).

### 9.3 ¿Evaluar ambos lados (`YES`/`NO`) o solo uno?

**Recomendación: ambos.** `compute_edge_yes`/`compute_edge_no` y
`compute_ev_yes/no_bruto` ya existen como funciones separadas desde
Fase 2 precisamente para esto — no evaluar ambos lados dejaría la
mitad de esa infraestructura sin usar y potencialmente ocultaría valor
real en el lado no evaluado. Costo: duplica el volumen de
`Opportunity`/`OpportunityEvaluation` por evento (hasta 2), aceptable
dado el volumen real observado (decenas de eventos por corrida, no
miles).

---

## 10. `PolicyManifest` inicial propuesto (contenido, sujeto a §9.1)

Dos archivos nuevos, `config/policy/mlb_v1.json` y
`config/policy/tennis_v1.json` — reutilizan **únicamente** constantes
ya existentes y aprobadas en `src/policy/hard_rules.py`/`soft_score.py`
(cero valores nuevos salvo los de §9.1):

```json
{
  "policy_version": "mlb_v1",
  "sport": "MLB",
  "hard_block_rules": ["unsafe_matching", "invalid_event", "invalid_or_closed_market",
                         "incompatible_contract", "corrupted_critical_data", "known_result"],
  "hard_hold_rules": ["pending_lineup", "unconfirmed_pitcher", "temporarily_stale_data",
                        "temporarily_insufficient_liquidity", "recoverable_missing_information",
                        "unresolved_side_mapping"],
  "soft_score_weights": { /* = DEFAULT_SOFT_SCORE_WEIGHTS, sin cambios */ },
  "critical_minimums": { /* = DEFAULT_CRITICAL_MINIMUMS, sin cambios */ },
  "hard_rule_parameters": {
    "pending_lineup_hours_threshold": 3.0,
    "temporarily_stale_data_threshold_seconds": 3600.0,
    "temporarily_insufficient_liquidity_minimum": 1000.0
  },
  "enter_global_threshold": 101.0,
  "watch_global_threshold": 0.0,
  "manifest_hash": "<calculado>",
  "created_at": "<fecha real de creación>",
  "promoted_at": null,
  "promotion_gate_report_ref": null
}
```
`tennis_v1.json` idéntico salvo `sport`/`policy_version`/omitiendo
`unconfirmed_pitcher` (regla específica de MLB). Validado con
`validate_policy_manifest()` (ya existente, sin cambios) antes de
comitear — criterio de aceptación explícito (§12).

---

## 11. Pruebas previstas

- `tests/unit/test_signal_builder.py` — `build_signal_inputs()`:
  propagación de `None` cuando `model_status=MODEL_NOT_TRAINED`;
  `market_price=None` cuando `needs_review=True`; `ev_neto=None` +
  contador de "exchange_fee poblado" cuando `NotImplementedError` se
  captura (mock de `exchange_fee` poblado); round-trip básico.
- `tests/unit/test_confidence_profile_builder.py` — la tabla completa
  de §9.2, incluida la redistribución cuando un componente de origen
  es `None`, y el invariante `operational_safety + operational_risk ==
  100` verificado explícitamente.
- `tests/unit/test_decision_pipeline.py`:
  - Camino feliz: un `NormalizedRecord` con `market_id` produce 2
    `Opportunity` (YES/NO) + 2 `OpportunityEvaluation`, `state_version=1`
    en ambos, persistidos en `tmp_path`.
  - Segunda corrida sobre el mismo `opportunity_id` → `state_version=2`.
  - `market_id=None` → cero `Opportunity` creadas, contador
    `sin_market_id` incrementado.
  - **Aislamiento de fallos** (la garantía central de este paso, §5):
    un registro que lanza una excepción durante el ensamblaje no
    detiene el procesamiento de los registros siguientes — probado
    inyectando un fallo deliberado a mitad de una lista de 3 registros
    y verificando que los otros 2 sí se persisten.
  - Con el `PolicyManifest` de §10 real: ningún `signal_type=ENTER`
    aparece nunca (documenta/fija como regresión el hallazgo §1.7).
  - Test de arquitectura (AST, mismo patrón que Fase 3): ningún módulo
    de `src/policy/`, `src/opportunity/`, `src/evidence/`, etc. importa
    `src/orchestration/` (dependencia en un solo sentido, §2.3).
- `tests/unit/test_opportunity_schemas.py` (existente, ampliado): caso
  `model_version=None` para `OpportunityEvaluation`, espejo exacto del
  ya existente para `CalibrationOutput` (§8.2).
- `tests/unit/test_mlb_pipeline.py`/`test_tennis_pipeline.py`
  (existentes): confirmar que los 2 campos nuevos de §8.1 se pueblan
  correctamente sin romper ningún test ya existente sobre `.records`/
  `.steps`.
- Suite completa re-ejecutada, sin regresión (932 + los nuevos).

---

## 12. Criterios de aceptación

- `opportunities`/`opportunity_evaluations` tienen filas reales en
  `data/engine.db` tras al menos una corrida real de `run_e2e.py`
  (verificado directamente por SQL, no solo por el resumen impreso).
- `signal_type=ENTER` no aparece nunca en las filas reales (esperado,
  §1.7 — se documenta explícitamente, no se investiga como anomalía).
- El aislamiento de fallos por evento está probado (test dedicado,
  §11) — un evento problemático no puede abortar la corrida completa.
- Las 2 enmiendas de §8 están limitadas exactamente a lo declarado
  (`git diff --stat` sobre `src/pipelines/`/`src/opportunity/schemas.py`
  no muestra nada fuera de lo descrito aquí).
- `config/policy/{mlb,tennis}_v1.json` pasan `validate_policy_manifest()`
  sin errores.
- Suite completa en verde, sin regresión.
- `git status`/`git diff --stat` limpios salvo los archivos declarados.
- `CONTINUITY.md` actualizado con el informe del paso antes del commit.

---

## 13. Riesgos

- **Volumen por corrida**: hasta 2 × (eventos MLB + eventos tenis) por
  hora — decenas, no miles, dado el volumen real observado
  (`FASE4_EXECUTION_PLAN.md` §1.4). Sin paginación ni límite de tasa
  necesarios a este volumen; revisar si el volumen real crece
  significativamente.
- **`ConfidenceProfile` `PROVISIONAL_V1` sin calibrar** — mismo riesgo
  ya aceptado y documentado para `HEURISTIC_V1`; cualquier
  recalibración futura debe versionarse (`quality_score_component_ref`/
  `policy_version` ya dan trazabilidad).
- **Falsa expectativa de que "no hay `ENTER`" es un bug** — mitigado
  documentándolo explícitamente en criterios de aceptación (§12) y en
  el resumen impreso (§7).
- **`enter_global_threshold=101.0`/`watch_global_threshold=0.0` (§9.1,
  Alternativa 2) parecen "números mágicos" fuera de contexto** —
  mitigado con el comentario explícito en el propio manifiesto JSON y
  en este documento sobre por qué son límites, no estimaciones.
- **Concurrencia entre corridas para el mismo `opportunity_id`**: no
  es un riesgo real hoy (`run_e2e.py` usa lock de instancia única, una
  sola corrida a la vez) — señalado como límite conocido del diseño,
  no como algo a resolver en este paso.

---

## 14. Evidencia esperada (tras implementar, tal como se hizo para 4.0A/4.0B)

- Conteo de filas antes/después en `opportunities`/`opportunity_evaluations`,
  verificado por SQL directo.
- Tabla de distribución `signal_type` (ENTER/WATCH/PASS) de una corrida
  real, confirmando `ENTER=0`.
- Inspección de 2-3 filas reales de `OpportunityEvaluation` completas
  (spot-check, mismo estándar que Paso 4.0A/4.0B).
- Suite completa (932 + nuevos), `git diff --stat` mostrando
  exactamente los archivos declarados en §8/§11.
- Confirmación explícita de que `config/policy/*.json` pasó
  `validate_policy_manifest()`.

---

## 15. Próximo paso

Este documento no autoriza ningún cambio de código. Antes de
implementar, se necesita tu decisión explícita sobre:

1. **§9.1** — ¿Alternativa 2 (umbrales límite) u otra?
2. **§9.2** — ¿apruebas el mapeo `PROVISIONAL_V1` de `ConfidenceProfile`
   tal como está, o quieres ajustar algún campo?
3. **§9.3** — ¿evaluar ambos lados (recomendado) o solo uno?
4. **§8** — ¿apruebas las 2 enmiendas a código ya cerrado de Fase 1/2/3?
5. Aprobación general de la arquitectura (§2), el flujo (§4) y el
   manejo de errores (§5).

Con eso aprobado, se procede a implementar con la misma disciplina de
siempre: un commit de código + un commit de `CONTINUITY.md`, suite
completa antes de cada uno, sin avanzar a ningún paso posterior sin
nueva aprobación.
