# Plan de Ejecución — Fase 3

Estado: **PENDIENTE DE APROBACIÓN — NINGÚN CÓDIGO ESCRITO TODAVÍA.**
Generado: 2026-07-30, tras la aprobación de la auditoría contractual y
arquitectónica (`FASE3_AUDIT_REPORT.md`, conclusión CONDITIONAL GO) y de
la congelación de la arquitectura (`PLAN_MASTER_FASE3.md`,
`ARCHITECTURE_FASE3.md`, `CONTRACTS_FASE3.md`, y las specs derivadas).

Este documento **no toma ninguna decisión arquitectónica nueva** — toma
el plan ya aprobado (`IMPLEMENTATION_ROADMAP_FASE3.md`, pasos F3-0 a
F3-9) y lo descompone en bloques de trabajo lo suficientemente pequeños
para implementar, probar, auditar y commitear uno a la vez, siguiendo
exactamente la metodología de Fase 2. Ningún archivo de `src/` se toca
en este documento — es planeación pura.

---

## 0. Metodología (reafirmada, sin cambios respecto a Fase 2)

Por cada paso, en este orden estricto:

1. Implementar un único bloque pequeño.
2. Verificar compatibilidad total con Fase 2 (ningún archivo fuera de la
   lista declarada del paso se modifica; los 498 tests de Fase 2 siguen
   en verde sin editarlos).
3. Ejecutar todos los tests correspondientes (los nuevos del paso + la
   suite completa).
4. Auditar el resultado contra los criterios de aceptación de este
   documento.
5. Commit únicamente cuando el paso esté completamente validado — un
   commit por paso, nunca a mitad de implementación.
6. Continuar con el siguiente paso.

### 0.1 Regla de cambio arquitectónico

La arquitectura queda **congelada** (`PLAN_MASTER_FASE3.md` en
adelante). Durante la implementación de cualquier paso, si aparece una
**contradicción demostrable** (no una preferencia, no una mejora
opcional) entre lo especificado y la realidad del código, el paso se
detiene y se documenta como una Ambigüedad, con el mismo procedimiento ya
usado en toda Fase 2: problema → alternativas → Design Proposal →
aprobación explícita del usuario → recién entonces se continúa. Ningún
paso improvisa una desviación de contrato silenciosamente.

### 0.2 Convención de nombres

Los pasos de este documento (`Paso 3.X`) son la forma ejecutable de los
pasos ya aprobados en `IMPLEMENTATION_ROADMAP_FASE3.md` (`F3-X`), con
`Paso 3.4` subdividido en 5 bloques más pequeños (`3.4.1`-`3.4.5`) porque
el roadmap ya señalaba que el Policy Engine es "el componente más
grande" y recomendaba subdividirlo por sub-etapa:

| Este documento | Roadmap aprobado | Nota |
|---|---|---|
| Paso 3.0 | F3-0 | — |
| Paso 3.1 | F3-1 | — |
| Paso 3.2 | F3-2 | — |
| Paso 3.3 | F3-3 | — |
| Paso 3.4.1 – 3.4.5 | F3-4 | subdividido, ver §Paso 3.4 |
| Paso 3.5 | F3-5 | — |
| Paso 3.6 | F3-6 | — |
| Paso 3.7 | F3-7 | — |
| Paso 3.8 | F3-8 | — |
| Paso 3.9 | F3-9 | — |

Todos corresponden a la columna **REQUIRED FOR PHASE 3** de
`IMPLEMENTATION_ROADMAP_FASE3.md`. Ningún paso de este documento
implementa nada de la columna RECOMMENDED LATER (depende de D-1/D-2/D-3,
sin resolver) ni REJECTED AS PREMATURE.

### 0.3 Definición de "Done" genérica (aplica a todo paso, además de lo específico)

Un paso se considera **Done** solo si, en este orden:

- [ ] Los archivos modificados/creados son exactamente los declarados en
      la sección "Archivos" del paso — ninguno más.
- [ ] `git diff --stat HEAD -- src/<archivos fuera de este paso>` está
      vacío (ningún archivo de un paso futuro ni de Fase 1/2 se tocó).
- [ ] Los tests nuevos del paso pasan.
- [ ] La suite completa (`pytest -q`) pasa: 498 + todos los tests
      acumulados de pasos anteriores + los nuevos de este paso, cero
      fallos, cero tests saltados sin justificación.
- [ ] `data/models/` y `data/engine.db` de producción no fueron tocados
      por ningún test (mismo aislamiento ya corregido en el commit
      `eff754e` de Fase 2 — cualquier test nuevo que toque persistencia
      usa `tmp_path`/`db_path` inyectable, nunca la ruta de producción
      por defecto).
- [ ] `CONTINUITY.md` actualizado con el cierre del paso (mismo patrón
      exacto que cada Paso de Fase 2: qué se implementó, qué decisiones
      se tomaron, qué queda pendiente) — no se pospone para el final de
      Fase 3.
- [ ] Un único commit, mensaje describiendo el paso, sin mezclar con el
      siguiente.

---

## Paso 3.0 — Andamiaje de contratos

| | |
|---|---|
| **Módulos afectados** | `src/calibration/`, `src/payoff/`, `src/policy/`, `src/opportunity/`, `src/evidence/`, `src/health/` (todos nuevos); `src/evaluation/` (paquete existente de Fase 2, se le añade un archivo nuevo) |
| **Archivos nuevos** | `src/calibration/__init__.py`, `src/calibration/schemas.py`; `src/payoff/__init__.py`, `src/payoff/schemas.py`; `src/policy/__init__.py`, `src/policy/schemas.py`; `src/opportunity/__init__.py`, `src/opportunity/schemas.py`; `src/evidence/__init__.py`, `src/evidence/schemas.py`; `src/health/__init__.py`, `src/health/schemas.py`; `src/evaluation/schemas.py` (**corrección**, ver nota abajo) |
| **Archivos modificados** | Ninguno (`src/evaluation/schemas.py` es un archivo nuevo dentro de un paquete existente — `src/evaluation/__init__.py`/`reports.py` no se tocan) |
| **Contratos involucrados** | Los 16 de `CONTRACTS_FASE3.md`: `CalibrationOutput` (§2), `PayoffEstimate`+`NetEvStatus` (§3), `ConfidenceProfile` (§4), `AnalysisHealth` (§5), `EvidenceItem`+`EvidenceDirection` (§6), `EligibilityResult` (§7), `HardRuleResult`+`HardRuleCategory` (§8), `SoftScoreComponent` (§9), `SignalReason`+`SignalReasonCode` (§10), `PolicyDecision`+`AbstentionDisposition` (§11), `Opportunity` (§12), `OpportunityEvaluation` (§13), `EvaluationRecord` (§14), `PolicyManifest` (§15) — `ModelOutput` (§1) y `SignalInputs` (§16) no generan código nuevo (composición/reutilización) |
| **Dependencias** | Ninguna — primer paso |
| **Riesgo** | Bajo — módulos nuevos, sin imports desde código de Fase 1/2, sin I/O |

**Corrección aplicada antes de implementar** (detectada al preparar este
paso, no una decisión arquitectónica nueva — ver §0.1): la tabla de
contratos ya listaba `EvaluationRecord` (§14) como parte de este paso,
pero la lista original de archivos no incluía dónde viviría su
`schemas.py` (`ARCHITECTURE_FASE3.md` solo crea `src/evaluation/learning.py`
en el Paso 3.8, con la lógica, no el contrato). Se resuelve siguiendo el
mismo patrón que todos los demás paquetes nuevos (`schemas.py` separado
del archivo de lógica): `src/evaluation/schemas.py` se crea en este paso
con únicamente `EvaluationRecord`; `src/evaluation/learning.py` (Paso
3.8) lo importará desde ahí. Ubicación de `ConfidenceProfile`: definida
en `src/policy/schemas.py` (`PLAN_MASTER_FASE3.md` §4 la dejaba abierta
entre `src/policy/` u `src/opportunity/` — se elige `policy/` porque es
consumida directamente por `soft_score.py`, Paso 3.4.4).

**Criterios de aceptación adicionales (aprobados por el usuario)**:
- Todo contrato tiene test de round-trip completo:
  `model_dump()` → `model_validate()` → objeto igual al original;
  `model_dump_json()` → `model_validate_json()` → objeto igual al
  original.
- Cada contrato dispone de una función factory de ejemplo mínimo válido
  (`tests/unit/fase3_factories.py`, mismo patrón `_kwargs(**overrides)`
  ya usado en `tests/unit/test_signal_schema.py` de Fase 2) — no
  fixtures JSON en `tests/unit/fixtures/`, para mantener paridad con el
  precedente exacto que Fase 2 ya usa para contratos tipados (a
  diferencia de los fixtures JSON de payloads crudos de conectores, que
  sí usan `tests/unit/fixtures/` vía `conftest.py`).

**Objetivo**: crear los 16 contratos como código (`pydantic.BaseModel`
con `extra="forbid"`, salvo donde `CONTRACTS_FASE3.md` indique
`dataclass(frozen=True)`), con sus invariantes como validadores, sin
ninguna función de negocio. Es la base de tipos sobre la que se
construyen todos los pasos siguientes.

**Criterios de aceptación**:
- Cada contrato existe con exactamente los campos, tipos y valores por
  defecto de `CONTRACTS_FASE3.md` — ningún campo agregado ni omitido sin
  documentarlo como Ambigüedad (§0.1).
- Cada invariante enumerado en `CONTRACTS_FASE3.md` está implementado
  como validador (`@model_validator` o `__post_init__`, según el patrón
  correspondiente) y no solo como comentario.
- Ningún contrato importa desde `src/policy/`, `src/evidence/`,
  `src/explainability/` u otro paquete de lógica — son módulos de datos
  puros (regla de dependencia de `ARCHITECTURE_FASE3.md` §4).
- **[Añadido por el usuario]** Todo contrato tiene test de round-trip
  `model_dump()`→`model_validate()` y `model_dump_json()`→
  `model_validate_json()`, verificando igualdad campo a campo con el
  objeto original.
- **[Añadido por el usuario]** Todo contrato tiene una función factory
  de ejemplo mínimo válido en `tests/unit/fase3_factories.py`.

**Pruebas que deberán pasar**:
- Un test por invariante enumerado en `CONTRACTS_FASE3.md` (mínimo 20,
  ver `IMPLEMENTATION_ROADMAP_FASE3.md`, Paso F3-0) — ejemplos
  concretos: `p_model_calibrated is not None` sin `calibration_version`
  → `ValidationError`; `signal_type=PASS` sin `disposition` →
  `ValidationError`; `signal_type=ENTER` con un `HardRuleResult(BLOCK,
  triggered=True)` presente → `ValidationError`.
- Test de `extra="forbid"`: instanciar cada contrato con un campo
  desconocido debe fallar.
- Test de timestamps naive: cada contrato con campo `datetime` rechaza
  un valor sin tz-info (mismo patrón que `PModelOutput`/`SignalInputs`
  en Fase 2).
- Test de round-trip de serialización por contrato (los 4 métodos:
  `model_dump`, `model_validate`, `model_dump_json`,
  `model_validate_json`).
- Suite completa de Fase 2: 498 passed, sin cambios.
- Archivos de test propuestos: `tests/unit/fase3_factories.py` (factories
  compartidas, sin tests propios), `tests/unit/test_calibration_schemas.py`,
  `tests/unit/test_payoff_schemas.py`, `tests/unit/test_policy_schemas.py`
  (incluye `ConfidenceProfile`, `EligibilityResult`, `HardRuleResult`,
  `SoftScoreComponent`, `SignalReason`, `PolicyDecision`,
  `PolicyManifest` — los 7 contratos de `src/policy/schemas.py`),
  `tests/unit/test_opportunity_schemas.py`,
  `tests/unit/test_evidence_schemas.py`, `tests/unit/test_health_schemas.py`,
  `tests/unit/test_evaluation_record_schema.py`.

**Estrategia de rollback**: `git rm` de los 13 archivos nuevos (6
`__init__.py` + 7 `schemas.py`, incluyendo `src/evaluation/schemas.py`)
y sus tests + `fase3_factories.py`. Cero dependientes todavía — ningún
otro módulo del proyecto los importa hasta el Paso 3.1.

**Definición de "Done"** (además de §0.3): los 16 contratos existen,
compilan, y cada uno tiene cobertura de test de sus invariantes propios
más su round-trip de serialización y su factory mínima; ningún paso
posterior necesita volver a tocar estos archivos para corregir un campo
(si eso ocurre, es señal de que `CONTRACTS_FASE3.md` tenía un error y
debe corregirse ahí primero, documentado como Ambigüedad).

---

## Paso 3.1 — Calibration Layer (sin entrenar)

| | |
|---|---|
| **Módulos afectados** | `src/calibration/` |
| **Archivos nuevos** | `src/calibration/calibration_layer.py` |
| **Archivos modificados** | Ninguno (`src/models/base.py` se importa, no se edita) |
| **Contratos involucrados** | `CalibrationOutput` (§2, ya creado en 3.0); `PModelOutput` (Fase 2, reutilizado, `src/models/base.py`) |
| **Dependencias** | Paso 3.0 |
| **Riesgo** | Bajo |

**Objetivo**: función `calibrate(model_output: PModelOutput,
calibrator: Optional[Calibrator]) -> CalibrationOutput` que hoy siempre
devuelve `calibration_version=None`/`p_model_calibrated=None` (ningún
calibrador real entrenado — depende de D-1, fuera de alcance de Fase 3,
ver `MODEL_PIPELINE_SPEC.md` §3). El tipo `Calibrator` se define como una
interfaz mínima (`Protocol`) sin ninguna implementación concreta todavía.

**Criterios de aceptación**:
- `p_model_raw == model_output.p_model_yes` exactamente, sin
  recalcular ni redondear.
- `calibrator is None` (único caso soportado en este paso) ⟹
  `p_model_calibrated is None` y `calibration_version is None`, siempre.
- `model_output.p_model_yes is None` (modelo no entrenado) ⟹
  `p_model_calibrated is None` incluso si en el futuro se pasara un
  `calibrator` no-None (invariante heredado de `PModelOutput`).
- Función pura: mismo `PModelOutput` + mismo `calibrator` → mismo
  `CalibrationOutput`, sin dependencia del reloj salvo `calibrated_at`
  inyectable (mismo patrón `now: Optional[datetime] = None` de
  `compute_quality_score`, Fase 2).

**Pruebas que deberán pasar**:
- `tests/unit/test_calibration_layer.py`: caso `MODEL_NOT_TRAINED` →
  todo `None`; caso `TRAINED` sin calibrador → `p_model_raw` poblado,
  `p_model_calibrated`/`calibration_version` `None`; test de pureza
  (misma entrada dos veces → mismo resultado, salvo `calibrated_at`
  inyectado).
- Suite completa: 498 + tests de 3.0 + tests nuevos de 3.1, todos en
  verde.

**Estrategia de rollback**: `git rm src/calibration/calibration_layer.py`
y su test. Paso 3.0 (los contratos) no se ve afectado.

**Definición de "Done"**: la función existe, es pura, y documenta
explícitamente (docstring, mismo estilo que `edge.py`/
`expected_value.py` de Fase 2) que la ausencia de calibración real es un
estado esperado, no una limitación temporal de la implementación.

---

## Paso 3.2 — Payoff Model

| | |
|---|---|
| **Módulos afectados** | `src/payoff/` |
| **Archivos nuevos** | `src/payoff/payoff_model.py` |
| **Archivos modificados** | Ninguno (`src/pricing/market_pricing.py`, `src/signals/expected_value.py` se importan, no se editan) |
| **Contratos involucrados** | `PayoffEstimate`+`NetEvStatus` (§3, ya creado en 3.0); `MarketData` (Fase 2, reutilizado) |
| **Dependencias** | Paso 3.0 |
| **Riesgo** | Bajo |

**Objetivo**: función que produce `PayoffEstimate` a partir de un
`NormalizedRecord` + `Side`, con `net_ev_status=UNKNOWN` mientras no
exista evidencia real de `entry_fee`/`estimated_exit_fee` (estado
verificado: Kalshi no los expone hoy — ver `CONTRACTS_FASE3.md` §3).

**Criterios de aceptación**:
- `record.market.exchange_fee is None` (estado real actual de todos los
  registros Kalshi observados en Fase 2) ⟹ `net_ev_status=UNKNOWN`,
  `ev_to_settlement is None`, `ev_to_planned_exit is None`,
  `cost_evidence_refs=[]`.
- `entry_price` se puebla reutilizando literalmente
  `market_price_yes`/`market_price_no` (Fase 2, sin reimplementar el
  cálculo).
- Ningún campo de costo (`entry_fee`, `estimated_exit_fee`, `spread`,
  `slippage_estimate`) se rellena con un valor inventado cuando la fuente
  es `None` — se propaga `None`.

**Pruebas que deberán pasar**:
- `tests/unit/test_payoff_model.py`: reutiliza los fixtures existentes
  de `tests/unit/test_market_pricing.py` (Fase 2) para confirmar que,
  con los datos reales observados, `net_ev_status` es siempre `UNKNOWN`;
  test explícito que rechaza (falla a propósito, como documentación
  ejecutable) cualquier intento de forzar `COMPUTED` sin
  `cost_evidence_refs`.
- Suite completa: 498 + acumulados + nuevos de 3.2.

**Estrategia de rollback**: `git rm src/payoff/payoff_model.py` y su
test.

**Definición de "Done"**: la función existe, es pura, y el 100% de los
fixtures reales de Fase 2 pasados a través de ella producen
`net_ev_status=UNKNOWN` — confirmando en código el hallazgo de la
auditoría (`FASE3_AUDIT_REPORT.md` §7, "ningún ENTER real es posible
mientras esto sea así").

---

## Paso 3.3 — Evidence Engine

| | |
|---|---|
| **Módulos afectados** | `src/evidence/` |
| **Archivos nuevos** | `src/evidence/evidence_engine.py` |
| **Archivos modificados** | Ninguno |
| **Contratos involucrados** | `EvidenceItem`+`EvidenceDirection` (§6, ya creado en 3.0) |
| **Dependencias** | Paso 3.0 |
| **Riesgo** | Bajo |

**Objetivo**: `collect_evidence(record, calibration_output,
confidence_profile) -> List[EvidenceItem]`, generando hechos solo desde
campos no-`None` (`EVIDENCE_EXPLAINABILITY_SPEC.md` §1.1), sin ningún
conocimiento de `PolicyDecision` ni de umbrales.

**Criterios de aceptación**:
- Ningún `EvidenceItem` referencia (`source_field`) un campo que sea
  `None` en el `NormalizedRecord`/`CalibrationOutput`/`ConfidenceProfile`
  de entrada.
- Ausencia de dato nunca genera un `EvidenceItem` con
  `direction=AGAINST` "de relleno" — ver tabla de plantillas de
  `EVIDENCE_EXPLAINABILITY_SPEC.md` §1.1.
- No importa nada de `src/policy/` ni `src/explainability/` (regla de
  dependencia).

**Pruebas que deberán pasar**:
- `tests/unit/test_evidence_engine.py`: casos concretos de la tabla de
  plantillas (§1.1) uno por uno.
- Property-based test (usar `hypothesis` **no** — no se agregan
  dependencias nuevas; en su lugar, un test parametrizado que recorre
  combinaciones de campos `None`/poblados generadas manualmente con
  `pytest.mark.parametrize`, mismo patrón ya usado en
  `tests/unit/test_market_pricing.py` de Fase 2) que confirma la regla
  de no-fabricación sobre al menos 8 combinaciones.
- Suite completa: 498 + acumulados + nuevos de 3.3.

**Estrategia de rollback**: `git rm src/evidence/evidence_engine.py` y
su test.

**Definición de "Done"**: la función existe, es pura, y el test
parametrizado cubre explícitamente el caso "campo ausente → ningún
`EvidenceItem` generado para ese campo" para cada plantilla de la tabla
de `EVIDENCE_EXPLAINABILITY_SPEC.md` §1.1.

---

## Paso 3.4 — Policy Engine (subdividido en 5 bloques)

El roadmap ya señala este como el componente más grande y de riesgo
medio; se subdivide siguiendo exactamente el orden de la cadena de
control de `POLICY_ENGINE_SPEC.md` §1.1, cada bloque commiteado por
separado.

### Paso 3.4.1 — Eligibility

| | |
|---|---|
| **Archivos nuevos** | `src/policy/eligibility.py` |
| **Contratos involucrados** | `EligibilityResult` (§7) |
| **Dependencias** | Paso 3.0 |
| **Riesgo** | Bajo |

**Objetivo**: `check_eligibility(signal_inputs_fields...) ->
EligibilityResult` — primer gate, verifica solo que el input sea
estructuralmente evaluable (`POLICY_ENGINE_SPEC.md` §1.1, etapa [1]).

**Criterios de aceptación**: `is_eligible=False` con al menos un motivo
en `ineligibility_reasons` cuando falta `event_id`/`sport`/`side`/
`generated_at`; `is_eligible=True` en caso contrario — no evalúa calidad
de datos, solo estructura.

**Pruebas**: `tests/unit/test_policy_eligibility.py` — un caso por
campo obligatorio ausente, más el caso feliz. Suite completa en verde.

**Rollback**: `git rm src/policy/eligibility.py` y su test — sin
dependientes todavía.

**Done**: función pura, cubierta, sin dependencia de Hard Rules ni Soft
Score.

### Paso 3.4.2 — Hard Block Rules

| | |
|---|---|
| **Archivos nuevos** | `src/policy/hard_rules.py` (bloque BLOCK únicamente en este paso) |
| **Contratos involucrados** | `HardRuleResult`+`HardRuleCategory` (§8) |
| **Dependencias** | Paso 3.4.1 |
| **Riesgo** | Medio — 7 reglas, cada una con su propia fuente de evidencia |

**Objetivo**: implementar las 7 reglas de `HARD_BLOCK_PASS`
(`POLICY_ENGINE_SPEC.md` §2.1: `unsafe_matching`, `invalid_event`,
`invalid_or_closed_market`, `incompatible_contract`,
`corrupted_critical_data`, `known_result`, `non_recoverable_inconsistency`),
como funciones independientes agregadas por un evaluador único.

**Criterios de aceptación**: catálogo cerrado — exactamente estas 7
`rule_id`, ninguna más, ninguna menos, en este paso; `known_result`
consulta `HistoryRepository.get_results_for_event` (Fase 2, reutilizado
sin editar) y respeta el filtro temporal (`captured_at`/`data_cutoff_timestamp`,
ver `TEMPORAL_REPRODUCIBILITY_SPEC.md` §2.2).

**Pruebas**: `tests/unit/test_hard_block_rules.py` — un test por regla
que la dispara, uno por regla que no se dispara con datos limpios;
`test_known_result_temporal_leakage` (usa `HistoryRepository` con
`db_path=tmp_path`, nunca la ruta de producción) confirmando que un
`event_results` posterior a `data_cutoff_timestamp` **no** dispara la
regla (no es fuga, es un resultado futuro correctamente ignorado) y uno
anterior sí. Suite completa en verde.

**Rollback**: `git rm src/policy/hard_rules.py` y su test; Paso 3.4.1 no
se ve afectado (Hard Rules no depende de `eligibility.py` en código,
solo en la secuencia orquestada del Paso 3.4.5).

**Done**: las 7 reglas existen, cada una con evidencia trazable a un
campo real de `NormalizedRecord`/`HistoryRepository`, ninguna
hardcodea un resultado.

### Paso 3.4.3 — Hard Hold Rules

| | |
|---|---|
| **Archivos modificados** | `src/policy/hard_rules.py` (se añade el bloque HOLD al mismo archivo del paso anterior, mismo módulo lógico) |
| **Contratos involucrados** | `HardRuleResult`+`HardRuleCategory` (§8) |
| **Dependencias** | Paso 3.4.2 |
| **Riesgo** | Bajo |

**Objetivo**: las 6 reglas de `HARD_HOLD_WATCH`
(`POLICY_ENGINE_SPEC.md` §2.2): `pending_lineup`, `unconfirmed_pitcher`,
`temporarily_stale_data`, `temporarily_insufficient_liquidity`,
`recoverable_missing_information`, y **`unresolved_side_mapping`**.

**Criterios de aceptación**: catálogo cerrado, 6 reglas exactas;
`unresolved_side_mapping` **siempre `triggered=True`** en este paso —
no es condicional a ningún dato de entrada, es una constante mientras
D-2 no se resuelva (`POLICY_ENGINE_SPEC.md` §2.2, literal). Este es el
criterio más importante del bloque: si algún test futuro logra que
`unresolved_side_mapping` no se dispare, eso es una regresión que debe
bloquear el paso, no un "mejor caso".

**Pruebas**: `tests/unit/test_hard_hold_rules.py` — un test por regla;
`test_unresolved_side_mapping_always_triggered` explícito, con un
comentario citando `PLAN_MASTER_FASE3.md` §5 Hallazgo #2 y DECISIÓN
PENDIENTE D-2, para que no se "arregle" por accidente en una refactor
futura sin pasar por la decisión explícita del usuario. Suite completa
en verde.

**Rollback**: revertir el diff aditivo sobre `hard_rules.py` (el archivo
vuelve al estado de 3.4.2); su test se elimina.

**Done**: 6 reglas HOLD implementadas, `unresolved_side_mapping`
verificablemente constante, documentado por qué.

### Paso 3.4.4 — Soft Score

| | |
|---|---|
| **Archivos nuevos** | `src/policy/soft_score.py` |
| **Contratos involucrados** | `SoftScoreComponent` (§9) |
| **Dependencias** | Paso 3.4.3 (solo se invoca cuando no hay bloqueos, pero se puede implementar y probar de forma aislada con inputs sintéticos) |
| **Riesgo** | Medio — la regla de no-compensación es el invariante más importante de todo el Policy Engine |

**Objetivo**: los 5 componentes de `POLICY_ENGINE_SPEC.md` §3
(`edge_strength`, `ev_neto_strength`, `confidence_aggregate`,
`data_quality_floor`, `operational_safety_floor`), agregación en
`aggregate_soft_score`, con `ev_neto_strength`,
`confidence_aggregate`, `data_quality_floor`, `operational_safety_floor`
marcados `is_critical_minimum=True`.

**Criterios de aceptación** (§3.1, literal): `ENTER` requiere
`aggregate_soft_score >= enter_global_threshold` **Y** todo componente
crítico con `passed_minimum=True` — un score global alto nunca compensa
un mínimo crítico incumplido. Dado que `ev_neto_strength` depende de
`PayoffEstimate.net_ev_status`, y ese es `UNKNOWN` universalmente (Paso
3.2), `ev_neto_strength.value=None`/`passed_minimum=None` en la práctica
actual — el test debe confirmar que esto **excluye** `ENTER` incluso con
todos los demás componentes perfectos.

**Pruebas**: `tests/unit/test_soft_score.py` — caso "todo perfecto
salvo un mínimo crítico" → score global alto pero `ENTER` no procede;
caso "`ev_neto_strength` con `net_ev_status=UNKNOWN`" → mismo resultado,
confirmando el hallazgo de la auditoría en código, no solo en
documentación. Suite completa en verde.

**Rollback**: `git rm src/policy/soft_score.py` y su test.

**Done**: la no-compensación está probada explícitamente para cada uno
de los 4 componentes críticos, uno a la vez.

### Paso 3.4.5 — Decision (orquestación) + Manifest + Validation

| | |
|---|---|
| **Archivos nuevos** | `src/policy/decision.py`, `src/policy/manifest.py`, `src/policy/validation.py`; `config/policy/` (directorio, sin contenido todavía — el primer `PolicyManifest` real se crea en un paso posterior, fuera de este documento, cuando exista un deporte listo para shadow mode) |
| **Contratos involucrados** | `PolicyDecision`+`AbstentionDisposition` (§11), `SignalReason`+`SignalReasonCode` (§10), `PolicyManifest` (§15) |
| **Dependencias** | Pasos 3.4.1-3.4.4 |
| **Riesgo** | Medio-alto — integra todo lo anterior; es el punto donde un error de orquestación (no de regla individual) podría producir un `ENTER` indebido |

**Objetivo**: `decide(signal_inputs, ...) -> PolicyDecision` siguiendo
la secuencia exacta de `POLICY_ENGINE_SPEC.md` §1.1 (Eligibility → Hard
Block → Hard Hold → Soft Score), más `manifest.py` (carga de
`PolicyManifest`) y `validation.py` (las 6 validaciones de Corrección H,
`POLICY_ENGINE_SPEC.md` §5: schema, rango, consistencia cruzada,
regresión, comparación histórica, criterios de promoción — las 3
primeras implementables ahora; regresión/histórico/promoción dependen de
tener al menos dos manifiestos para comparar, se prueban con fixtures
sintéticos en este paso).

**Criterios de aceptación**:
- Test de arquitectura (fuzz sobre combinaciones de `HardRuleResult`):
  ningún `PolicyDecision(signal_type=ENTER)` coexiste con un
  `HardRuleResult(BLOCK, triggered=True)` — 0 violaciones sobre el
  espacio de combinaciones probado.
- `signal_type=PASS` siempre lleva `disposition` no nulo.
- Excepción no controlada dentro de la orquestación → `PolicyDecision`
  con `disposition=INVALID_ANALYSIS`, nunca una excepción propagada al
  llamador (Principio 20, fail-safe — `POLICY_ENGINE_SPEC.md` §6).
- `validation.py` rechaza un `PolicyManifest` con un `rule_id`
  desconocido, con `enter_global_threshold < watch_global_threshold`, o
  con un `component_name` en `critical_minimums` fuera del catálogo de
  §3 — **antes** de que `decision.py` pueda usarlo.

**Pruebas**: `tests/unit/test_policy_decision.py` (orquestación
completa, con dobles/fixtures de cada etapa anterior),
`tests/unit/test_policy_manifest_validation.py` (los 3 casos de
rechazo negativo listados arriba, más el caso positivo de un manifiesto
válido), `tests/unit/test_policy_fail_safe.py` (excepción forzada en
cada etapa → `INVALID_ANALYSIS`, nunca propagación). Suite completa: 498
+ todos los acumulados de 3.0-3.4.4 + nuevos de 3.4.5.

**Estrategia de rollback**: `git rm` de los 3 archivos nuevos y sus
tests; Pasos 3.4.1-3.4.4 quedan intactos y reutilizables por una
reimplementación futura de la orquestación.

**Definición de "Done"** (cierra Paso 3.4 completo): el Policy Engine
completo puede recibir un `SignalInputs` sintético y producir una
`PolicyDecision` determinista y trazable; el fuzz test de no-ENTER-con-
bloqueo pasa sobre el espacio completo de combinaciones de reglas;
`CONTINUITY.md` documenta el cierre de Paso 3.4 (los 5 sub-bloques,
mismo nivel de detalle que Fase 2 documentó el Paso 5b con sus 5
bloques internos).

---

## Paso 3.5 — Opportunity Lifecycle + persistencia

| | |
|---|---|
| **Módulos afectados** | `src/opportunity/`, `data/engine.db` (tablas nuevas, aditivas) |
| **Archivos nuevos** | `src/opportunity/opportunity_repository.py` |
| **Archivos modificados** | Ninguno (`config/settings.py` no requiere cambios: `opportunity_repository.py` reutiliza `DB_PATH` ya existente) |
| **Contratos involucrados** | `Opportunity` (§12), `OpportunityEvaluation` (§13) |
| **Dependencias** | Paso 3.4.5 (una `OpportunityEvaluation` embebe `PolicyDecision`) |
| **Riesgo** | Medio — primer paso que toca `data/engine.db` real |

**Objetivo**: `OpportunityRepository` con tablas `opportunities`,
`opportunity_evaluations` (append-only, triggers `RAISE(ABORT, ...)`
sobre `UPDATE`/`DELETE`, mismo patrón exacto que `HISTORY_SCHEMA_SQL`,
`src/storage/history_repository.py`, Fase 2), `db_path` inyectable con
default a `DB_PATH` (mismo patrón que `HistoryRepository`).

**Criterios de aceptación**:
- `opportunity_id` determinístico: `(event_id, selection_id)` idénticos
  → mismo `opportunity_id` siempre, sin tabla de lookup.
- Insertar una segunda `OpportunityEvaluation` para la misma
  `Opportunity` incrementa `state_version` y referencia
  `previous_signal_id` correctamente — nunca sobrescribe la anterior.
- `UPDATE`/`DELETE` crudo (SQL directo, fuera de la clase) sobre
  `opportunity_evaluations` falla con `RAISE(ABORT, ...)` — mismo test
  que ya existe para `event_snapshots` en Fase 2, replicado.
- `PRAGMA foreign_keys = ON` en cada conexión (mismo hallazgo de
  auditoría de Fase 2 Paso 0, reutilizado).
- Cero cambios a `repository.py`/`history_repository.py`.

**Pruebas**: `tests/unit/test_opportunity_repository.py` — todos con
`db_path=tmp_path / "test.db"`, **nunca** contra `data/engine.db` real
(mismo aislamiento exigido por §0.3 de este documento); casos: inserción
simple, determinismo de `opportunity_id`, encadenamiento de
`state_version`/`previous_signal_id`, rechazo de `UPDATE`/`DELETE`
crudo, foreign key inválida rechazada. Suite completa en verde.

**Estrategia de rollback**: `git rm
src/opportunity/opportunity_repository.py` y su test. Las tablas nuevas
en `data/engine.db` de producción **no se crean** hasta que este código
se ejecute contra la base real por primera vez — mientras eso no ocurra
(no ocurre en este paso, que solo corre contra `tmp_path` en tests), no
hay nada que revertir en la base real. Si en un paso posterior ya se
hubiera ejecutado contra producción, el rollback sería `DROP TABLE
opportunities, opportunity_evaluations` — sin FK hacia
`normalized_records`/`event_snapshots`/`feature_snapshots`/
`event_results`, por lo que no arrastra ninguna tabla de Fase 1/2.
- **Antes de ejecutar por primera vez contra `data/engine.db` real
  (fuera del alcance de este paso, que solo usa `tmp_path`): backup
  verificado del archivo, mismo procedimiento ya validado
  institucionalmente en Fase 2.**

**Definición de "Done"**: repositorio completo, probado exclusivamente
contra bases de datos temporales, sin ninguna ejecución contra
`data/engine.db` de producción todavía (eso ocurre recién en shadow mode,
fuera de alcance de este documento — ver `SHADOW_MODE_AND_PROMOTION_GATES.md`).

---

## Paso 3.6 — Explainability Engine

| | |
|---|---|
| **Módulos afectados** | `src/explainability/` |
| **Archivos nuevos** | `src/explainability/explainability_engine.py` |
| **Archivos modificados** | Ninguno |
| **Contratos involucrados** | `ExplanationOutput` (`EVIDENCE_EXPLAINABILITY_SPEC.md` §2) |
| **Dependencias** | Pasos 3.3, 3.4.5 |
| **Riesgo** | Bajo |

**Objetivo**: `explain(policy_decision, evidence_items) ->
ExplanationOutput`, consumiendo únicamente `PolicyDecision.reasons` y
`EvidenceItem[]` ya calculados — nunca re-derivando desde
`NormalizedRecord` (regla de separación, Principio 6).

**Criterios de aceptación**:
- Test de arquitectura por introspección de imports: el módulo
  `explainability_engine.py` no importa `src/models/schemas.py` ni
  `src/uncertainty/quality_score.py` (datos crudos) — solo tipos de
  `src/policy/schemas.py` y `src/evidence/schemas.py`.
- `disclaimers` no vacío cuando `calibration_version is None` o
  `net_ev_status=UNKNOWN` está presente en la cadena de razones.

**Pruebas**: `tests/unit/test_explainability_engine.py` — casos ENTER/
WATCH/PASS con distintos `disposition`; test de arquitectura de imports
(usar `ast`/`importlib` sobre el archivo fuente, sin dependencia nueva).
Suite completa en verde.

**Estrategia de rollback**: `git rm
src/explainability/explainability_engine.py` y su test.

**Definición de "Done"**: toda razón mostrada en `ExplanationOutput` es
trazable a un `SignalReason` o `EvidenceItem` real, verificado por test.

---

## Paso 3.7 — Analysis Health

| | |
|---|---|
| **Módulos afectados** | `src/health/` |
| **Archivos nuevos** | `src/health/analysis_health.py` |
| **Archivos modificados** | Ninguno |
| **Contratos involucrados** | `AnalysisHealth` (§5, ya creado en 3.0) |
| **Dependencias** | Paso 3.0 únicamente (puede desarrollarse en paralelo a 3.1-3.6) |
| **Riesgo** | Bajo |

**Objetivo**: cálculo de `AnalysisHealth` desde `QualityScoreOutput`
(Fase 2, reutilizado) + conteo de `EvidenceItem` — exclusivamente
informativo.

**Criterios de aceptación**: test de arquitectura confirma que
`src/policy/` (ningún archivo de 3.4) importa
`src/health/analysis_health.py` para otra cosa que no sea transportar el
valor hacia `OpportunityEvaluation`/`ExplanationOutput` — nunca como
input de `soft_score.py` (invariante del Principio 5, verificado en
código, no solo en documentación).

**Pruebas**: `tests/unit/test_analysis_health.py`; test de arquitectura
de imports (reutiliza el mismo mecanismo del Paso 3.6). Suite completa
en verde.

**Estrategia de rollback**: `git rm src/health/analysis_health.py` y su
test.

**Definición de "Done"**: el test de arquitectura que impide su uso en
`soft_score.py` está en verde y se mantiene en verde en cada paso
posterior (se re-ejecuta como parte de la suite completa desde este
punto en adelante).

---

## Paso 3.8 — Evaluation & Learning Framework (estructura, sin histórico real)

| | |
|---|---|
| **Módulos afectados** | `src/backtesting/metrics.py` (extendido), `src/evaluation/learning.py` (nuevo) |
| **Archivos nuevos** | `src/evaluation/learning.py` |
| **Archivos modificados** | `src/backtesting/metrics.py` (aditivo: `ece()`, `clv()`, `roi_teorico()`, `drawdown()`, `profit_factor()` — ninguna firma existente se toca) |
| **Contratos involucrados** | `EvaluationRecord` (§14) |
| **Dependencias** | Paso 3.5 (para construir `EvaluationRecord` desde `OpportunityEvaluation` históricas, aunque en este paso se prueba con fixtures sintéticos, no histórico real) |
| **Riesgo** | Bajo — funciones puras aditivas |

**Objetivo**: las 5 funciones nuevas en `metrics.py`
(`EVALUATION_LEARNING_SPEC.md` §3) con la misma disciplina que las 4
existentes (`None` si no hay muestras, nunca un valor fabricado); y el
andamiaje de `learning.py` que ensambla `EvaluationRecord` por las 5
dimensiones (`model_performance`, `decision_performance`,
`financial_performance`, `operational_performance`,
`learning_performance`) a partir de fixtures — **no** de histórico real
(bloqueado por D-1/GATE-0, fuera de alcance).

**Criterios de aceptación**:
- Los 4 tests existentes de `tests/unit/test_backtesting_metrics.py`
  (Fase 2) siguen pasando sin modificación.
- Las 5 funciones nuevas: `None` con secuencia vacía; valor exacto
  contra un caso de referencia calculado a mano (mismo patrón que
  `brier_score`/`log_loss_metric` ya prueban).
- `EvaluationRecord.sample_size=0` cuando no hay datos — nunca se
  fabrica un `metric_value` sin muestras.

**Pruebas**: `tests/unit/test_backtesting_metrics.py` (extendido con
casos de las 5 funciones nuevas, mismo archivo, no uno separado, para
mantener paridad con el archivo existente), `tests/unit/test_evaluation_learning.py`.
Suite completa: 498 + acumulados + nuevos de 3.8.

**Estrategia de rollback**: revertir el diff aditivo de `metrics.py`
(sin afectar las 4 funciones/tests existentes); `git rm
src/evaluation/learning.py` y su test.

**Definición de "Done"**: framework de 5 dimensiones ensamblable con
fixtures; ningún `EvaluationRecord` producido en este paso pretende
representar performance real (se documenta explícitamente en
`CONTINUITY.md` al cerrar el paso que sigue bloqueado por D-1, igual que
`FASE3_AUDIT_REPORT.md` §15 ya concluye).

---

## Paso 3.9 — Registro genérico de modelos (extensión aditiva)

| | |
|---|---|
| **Módulos afectados** | `src/models/registry.py` |
| **Archivos nuevos** | Ninguno |
| **Archivos modificados** | `src/models/registry.py` (aditivo: nueva función `load_latest_artifact(sport, models_dir)`, `load_latest_mlb_artifact` intacta) |
| **Contratos involucrados** | Ninguno nuevo — reutiliza `ModelStatus`/metadata ya existente |
| **Dependencias** | Ninguna — independiente del resto de Fase 3, puede hacerse en cualquier momento |
| **Riesgo** | Bajo |

**Objetivo**: generalizar el registro de artefactos sin tocar
`load_latest_mlb_artifact` ni sus 2 archivos hermanos
(`{model_version}.joblib`/`{model_version}.metadata.json`).

**Criterios de aceptación**:
- Los tests existentes de `load_latest_mlb_artifact` (parte de la suite
  de 498) pasan sin modificación alguna.
- La función nueva acepta un patrón de glob parametrizado por `sport` en
  vez de hardcodear `mlb_baseline_*`.
- Ningún llamador existente (`scripts/train_mlb_model.py`,
  `src/evaluation/reports.py`) se modifica para usar la función nueva —
  la migración real queda fuera de alcance (`PLAN_MASTER_FASE3.md`
  §3.5).

**Pruebas**: nuevo caso en `tests/unit/test_model_registry.py` (Fase 2,
extendido) con un artefacto de un "deporte sintético" de fixture,
confirmando que `load_latest_mlb_artifact` sigue funcionando igual sobre
los mismos fixtures que ya usaba. Suite completa en verde.

**Estrategia de rollback**: revertir el diff aditivo — `registry.py`
vuelve a su estado de `v2.0-baseline` exacto.

**Definición de "Done"**: `git diff src/models/registry.py` muestra
únicamente líneas añadidas, cero líneas eliminadas o modificadas sobre
código existente.

---

## Orden de dependencia (resumen ejecutable)

```
3.0 --> 3.1 --> 3.2 --> 3.4.1 --> 3.4.2 --> 3.4.3 --> 3.4.4 --> 3.4.5 --> 3.5 --> 3.6
              \-> 3.3 --------------------------------------------^        \
3.7 (paralelo, solo depende de 3.0)                                        \-> 3.8
3.9 (independiente, sin dependencias)
```

15 commits en total (3.0, 3.1, 3.2, 3.3, 3.4.1, 3.4.2, 3.4.3, 3.4.4,
3.4.5, 3.5, 3.6, 3.7, 3.8, 3.9 = 14 pasos numerados, más el cierre de
Paso 3.4 completo documentado en `CONTINUITY.md` al terminar 3.4.5,
igual que Fase 2 documentó cierres de sub-bloques y del paso padre por
separado).

---

## Qué no incluye este plan (reafirmado)

Ningún paso de este documento produce un `PolicyManifest` promovido
(`promoted_at != None`), ningún calibrador entrenado real, ningún
backtesting sobre histórico real, ningún shadow mode real — todo eso
permanece bloqueado por GATE-0 y las Decisiones Pendientes D-1/D-2/D-3
(`PLAN_MASTER_FASE3.md` §8), exactamente como concluyó
`FASE3_AUDIT_REPORT.md` §15. Este plan solo construye y prueba la
arquitectura aprobada con fixtures — la primera vez que cualquier paso
toque `data/engine.db` de producción (no `tmp_path`) será una decisión
explícita, señalada como tal cuando se proponga, no algo que ocurra por
default dentro de estos 14 pasos.

---

## Próximo paso

Este documento queda a la espera de aprobación. Ninguna implementación
comienza hasta que se confirme. Tras la aprobación, se inicia el Paso
3.0 siguiendo el protocolo de §0 y §0.3 de este documento.
