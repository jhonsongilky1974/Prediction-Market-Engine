# Roadmap de Implementación — Fase 3

Pasos pequeños, reversibles y auditables (tarea obligatoria #17-19). Cada
paso: criterio de aceptación, riesgo, estrategia de rollback. Ningún paso
implica ejecutar código de decisión real contra mercados en vivo — todos
son offline hasta el gate de `SHADOW_MODE_AND_PROMOTION_GATES.md` §3.4.
Este roadmap **no se ejecuta en esta auditoría** — es la especificación
de los próximos pasos, cada uno requiere su propia sesión de
implementación con revisión, tal como exige la metodología ya usada en
toda Fase 2 (revisión contractual → ambigüedades → Design Proposal →
aprobación → implementación).

---

## Clasificación previa (tarea obligatoria #20)

| Componente | Clasificación |
|---|---|
| Contratos (`CONTRACTS_FASE3.md`), 16 modelos Pydantic/dataclass | **REQUIRED FOR PHASE 3** |
| Policy Engine (Hard Rules + Soft Score + `decision.py`) | **REQUIRED FOR PHASE 3** |
| `CalibrationOutput`/`calibration_layer.py` (sin entrenar un calibrador real) | **REQUIRED FOR PHASE 3** |
| `PayoffEstimate`/`payoff_model.py` con `net_ev_status=UNKNOWN` universal | **REQUIRED FOR PHASE 3** |
| `Opportunity`/`OpportunityEvaluation` + repositorio append-only | **REQUIRED FOR PHASE 3** |
| Evidence Engine + Explainability Engine | **REQUIRED FOR PHASE 3** |
| `AnalysisHealth` | **REQUIRED FOR PHASE 3** |
| `PolicyManifest` + validación (schema/rango/consistencia) | **REQUIRED FOR PHASE 3** |
| Extensión de `metrics.py` (ece/clv/roi/drawdown/profit_factor) | **REQUIRED FOR PHASE 3** (funciones puras, no requieren histórico real para existir y probarse) |
| `EvaluationRecord`/framework de 5 dimensiones (estructura + tests con fixtures) | **REQUIRED FOR PHASE 3** |
| Entrenar un calibrador real (Platt/isotonic) | **RECOMMENDED LATER** — depende de D-1 |
| Historical backtesting real, Shadow mode real, Paper tracking real | **RECOMMENDED LATER** — depende de D-1/GATE-0 |
| ~~Resolver Market Adapter real (participante↔YES)~~ | **RESUELTO** post-cierre del roadmap (D-2, ver `CONTINUITY.md` §0.17) — el mapeo ya existía desde Fase 1; se expuso su confianza (`DataQuality.side_selection_confidence`) |
| `exchange_fee`/spread/slippage reales en `PayoffEstimate` | **RECOMMENDED LATER** — depende de D-3, evidencia real de la API |
| Recalibrar `HEURISTIC_V1` / umbrales `PolicyManifest` con evidencia real | **RECOMMENDED LATER** — depende de D-1 |
| Migrar `models/registry.py` a ser exclusivamente genérico (eliminar la función MLB-específica) | **REJECTED AS PREMATURE** — sin beneficio hasta que exista un segundo consumidor real de `load_latest_artifact` |
| Cualquier forma de ejecución automática / `src/risk/` | **REJECTED AS PREMATURE** (Principio 21, restricción dura — no "later", explícitamente fuera de la trayectoria actual del proyecto) |
| Un framework de configuración/validación nuevo (`pandera`, `jsonschema`) en vez de `pydantic` ya usado | **REJECTED AS PREMATURE** — sin necesidad no cubierta por `extra="forbid"` ya en uso |

---

## Pasos propuestos

### Paso F3-0 — Andamiaje de contratos

- **Alcance**: crear los 16 contratos de `CONTRACTS_FASE3.md` como
  código (`src/policy/schemas.py`, `src/calibration/schemas.py`,
  `src/payoff/schemas.py`, `src/opportunity/schemas.py`,
  `src/evidence/schemas.py`, `src/health/schemas.py`), sin ninguna lógica
  de negocio — solo los modelos y sus invariantes (`model_validator`).
  Cero I/O, cero dependencia de otros pasos.
- **Criterio de aceptación**: un test por invariante listado en
  `CONTRACTS_FASE3.md` (mínimo 20 tests: uno por invariante enumerada);
  100% de los contratos rechazan campos desconocidos (`extra="forbid"`);
  suite completa de Fase 2 (498 tests) sigue en verde, sin
  modificaciones a `src/` existente.
- **Riesgo**: bajo — módulos nuevos, sin imports desde código existente.
- **Rollback**: `git rm` de los archivos nuevos; cero impacto en Fase 2.

### Paso F3-1 — Calibration Layer (sin entrenar)

- **Alcance**: `src/calibration/calibration_layer.py`, función
  `calibrate()` que devuelve `CalibrationOutput` con
  `p_model_calibrated=None`/`calibration_version=None` siempre (ningún
  `Calibrator` real todavía).
- **Criterio de aceptación**: tests confirman que
  `p_model_raw == PModelOutput.p_model_yes` exactamente, y que
  `p_model_calibrated is None` en todos los casos (estado honesto,
  Principio 20).
- **Riesgo**: bajo.
- **Rollback**: aislado, sin dependientes todavía.

### Paso F3-2 — Payoff Model

- **Alcance**: `src/payoff/payoff_model.py`, siempre
  `net_ev_status=UNKNOWN` mientras no exista evidencia real de
  `entry_fee`/`estimated_exit_fee` (estado actual verificado: Kalshi no
  los expone).
- **Criterio de aceptación**: test que verifica que, dado el
  `MarketData` real observado en Fase 2 (fixtures existentes de
  `tests/unit/test_market_pricing.py`), `net_ev_status` es siempre
  `UNKNOWN`; ningún test intenta forzar `COMPUTED` sin datos de costo
  reales.
- **Riesgo**: bajo.
- **Rollback**: aislado.

### Paso F3-3 — Evidence Engine

- **Alcance**: `src/evidence/evidence_engine.py`.
- **Criterio de aceptación**: property-based test — para cualquier
  `NormalizedRecord` generado con campos aleatoriamente `None`, ningún
  `EvidenceItem` referencia un campo fuente que sea `None` en ese
  registro.
- **Riesgo**: bajo.
- **Rollback**: aislado.

### Paso F3-4 — Policy Engine (Hard Rules + Soft Score + decision.py)

- **Alcance**: el núcleo completo de `POLICY_ENGINE_SPEC.md`, incluyendo
  `manifest.py`/`validation.py`. Depende de F3-0, F3-1, F3-2.
- **Criterio de aceptación**:
  - Test de arquitectura: ningún `HardRuleResult(category=BLOCK, triggered=True)`
    coexiste con `PolicyDecision(signal_type=ENTER)` (fuzz test sobre combinaciones).
  - Test de no-compensación: un `SoftScoreComponent` crítico en `False`
    bloquea `ENTER` sin importar `aggregate_soft_score`.
  - `unresolved_side_mapping` (Hard Hold) dispara siempre `True` en esta
    fase (D-2 sin resolver) — test que lo confirma explícitamente, para
    que no se "olvide" silenciosamente en una implementación futura.
  - `PolicyManifest` inválido (regla desconocida, umbral fuera de rango)
    es rechazado antes de ejecutarse — test negativo obligatorio.
- **Riesgo**: medio — es el componente más grande. Mitigación: subdividir
  en PRs pequeños por sub-etapa (eligibility → hard block → hard hold →
  soft score → decision), cada uno probado de forma aislada antes de
  integrar.
- **Rollback**: módulo nuevo, sin dependientes fuera de `src/policy/`
  mismo; revertible sin tocar Fase 2.

### Paso F3-5 — Opportunity Lifecycle + persistencia

- **Alcance**: `src/opportunity/`, tablas SQLite nuevas (mismo patrón
  `HISTORY_SCHEMA_SQL`, triggers append-only). Depende de F3-4.
- **Criterio de aceptación**:
  - Test que confirma que un `UPDATE`/`DELETE` crudo sobre
    `opportunity_evaluations` falla (mismo test que ya existe para
    `event_snapshots`, replicado).
  - Test de determinismo de `opportunity_id` (mismo `event_id`+`side` →
    mismo id, siempre).
  - Test de encadenamiento: una segunda evaluación de la misma
    `Opportunity` incrementa `state_version` y referencia
    `previous_signal_id` correctamente.
- **Riesgo**: medio — cambios de schema en `engine.db` (aditivos, mismo
  archivo). Mitigación: `CREATE TABLE IF NOT EXISTS`, backup verificado
  antes de la primera corrida contra `data/engine.db` real (mismo
  procedimiento de backup ya validado institucionalmente en Fase 2).
- **Rollback**: tablas nuevas se pueden `DROP` sin afectar
  `normalized_records`/`event_snapshots`/`feature_snapshots`/
  `event_results` (Fase 1/2, sin relación de FK hacia las tablas
  nuevas).

### Paso F3-6 — Explainability Engine

- **Alcance**: `src/explainability/`. Depende de F3-3, F3-4.
- **Criterio de aceptación**: test que confirma que ningún campo de
  `ExplanationOutput` referencia un dato que no provenga de
  `PolicyDecision.reasons` o `EvidenceItem` (test de arquitectura por
  introspección de imports, igual que el de `ARCHITECTURE_FASE3.md` §4).
- **Riesgo**: bajo.
- **Rollback**: aislado.

### Paso F3-7 — Analysis Health

- **Alcance**: `src/health/analysis_health.py`. Puede desarrollarse en
  paralelo a F3-4 (sin dependencia real, solo conceptual).
- **Criterio de aceptación**: test de arquitectura — `src/policy/` no
  importa `src/health/` salvo para pasar el valor a
  `OpportunityEvaluation`/`ExplanationOutput` (nunca como input de
  `soft_score.py`).
- **Riesgo**: bajo.
- **Rollback**: aislado.

### Paso F3-8 — Evaluation & Learning Framework (estructura)

- **Alcance**: extensión de `metrics.py` + `evaluation/learning.py`, con
  fixtures sintéticos (no histórico real). Depende de F3-5.
- **Criterio de aceptación**: las 5 nuevas funciones puras de
  `metrics.py` tienen paridad de estilo con las 4 existentes (mismos
  tests parametrizados: vacío → `None`, casos conocidos → valor exacto).
- **Riesgo**: bajo.
- **Rollback**: aislado, aditivo.

### Paso F3-9 — Registro genérico de modelos (extensión aditiva)

- **Alcance**: `load_latest_artifact(sport, ...)` en
  `src/models/registry.py`, sin tocar `load_latest_mlb_artifact`.
- **Criterio de aceptación**: los tests existentes de
  `load_latest_mlb_artifact` siguen pasando sin modificación; nuevo test
  para la función genérica con fixtures de un deporte sintético.
- **Riesgo**: bajo — aditivo puro sobre un archivo pequeño.
- **Rollback**: revertir la función nueva sin efecto en la existente.

---

## Orden de dependencia (resumen)

```
F3-0 --> F3-1 --> F3-2 --> F3-4 --> F3-5 --> F3-6
              \-> F3-3 -----^        \
F3-7 (paralelo, sin dependencias duras)  \-> F3-8
F3-9 (independiente, sin dependencias)
```

---

## Riesgos transversales y mitigación

| Riesgo | Mitigación |
|---|---|
| Que "GATE-0 pendiente" se ignore en la práctica y se declare Fase 3 lista para producción sin histórico real | Cada `PolicyManifest` sin `promoted_at` bloquea `ENTER` real por diseño (`ev_neto_strength` como mínimo crítico, ver `POLICY_ENGINE_SPEC.md` §3.1) — el sistema es estructuralmente incapaz de producir un ENTER real hasta D-3 (D-2 resuelto post-cierre, ver `CONTINUITY.md` §0.17; `unresolved_side_mapping` ya no bloquea de forma incondicional, solo por registro con evidencia insuficiente) |
| Crecimiento sin límite de `opportunity_evaluations` (append-only) | Misma deuda ya aceptada conscientemente para `event_snapshots`/`feature_snapshots` en Fase 2 (`FASE2_CIERRE_FINAL.md` §5) — se documenta, no se resuelve aquí |
| Que el Policy Engine se pruebe solo con fixtures "fáciles" que nunca disparan Hard Rules | Fixtures obligatorios por cada `rule_id` del catálogo cerrado (`POLICY_ENGINE_SPEC.md` §2), uno por uno, como parte del criterio de aceptación de F3-4 |
