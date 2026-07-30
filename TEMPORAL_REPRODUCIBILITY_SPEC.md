# Temporal Integrity & Reproducibility — Especificación (Fase 3)

Principio 18, Corrección D. Este documento es transversal: aplica a
`CalibrationOutput`, `PayoffEstimate`, `OpportunityEvaluation` y
`EvaluationRecord` (`CONTRACTS_FASE3.md`).

---

## 1. Los 3 timestamps obligatorios por señal (Corrección D)

| Timestamp | Significado | Ya existe en Fase 2 |
|---|---|---|
| `decision_timestamp` | Cuándo se tomó/registró la `PolicyDecision` | No — nuevo en `OpportunityEvaluation` |
| `data_cutoff_timestamp` | El instante más reciente de datos permitido para esta evaluación | Sí — `PModelOutput.data_cutoff_timestamp` (Fase 2, `src/models/base.py`), reutilizado literalmente |
| `market_snapshot_timestamp` | Instante del snapshot de mercado usado para `market_price_yes`/`no` | No directamente — se deriva de `DataQuality.source_timestamps` (Fase 2) o de `event_snapshots.captured_at` (`HistoryRepository`, Fase 2) |

Más las 4 versiones (`model_version`, `calibration_version`,
`policy_version`, `feature_schema_version`) — ver
`CONTRACTS_FASE3.md`, resumen final. Toda `OpportunityEvaluation`
persistida lleva las 7 juntas, nunca un subconjunto.

---

## 2. Invariante de no-fuga (el más importante de este documento)

```
Para toda feature, calibración o evaluación histórica usada por una
OpportunityEvaluation con data_cutoff_timestamp = T:

    ningún dato con timestamp de origen > T puede haber influido en
    el resultado.
```

### 2.1 Ya garantizado por Fase 2 (reutilizado, no reinventado)

- `src/backtesting/splitter.py` (`walk_forward_splits`) — Fase 2 ya
  implementa split temporal walk-forward, nunca aleatorio. Fase 3 lo
  reutiliza sin cambios para entrenar/evaluar el Calibration Layer y
  cualquier `EvaluationRecord` de `model_performance`.
- `HistoryRepository.event_results` — tabla **separada** de
  `event_snapshots`, nunca unida al escribir (Fase 2, diseño explícito
  para evitar que un resultado se filtre a un snapshot pre-evento). El
  join solo ocurre al construir un dataset de backtesting, filtrando
  estrictamente `captured_at < recorded_at` — mismo patrón que Fase 3
  reutiliza para unir `OpportunityEvaluation` con resultados reales.
- Timestamps tz-aware obligatorios — `PModelOutput`, `SignalInputs`,
  `HistoryRepository` ya lanzan `ValueError` ante un timestamp naive
  (Fase 2). Todo contrato nuevo de `CONTRACTS_FASE3.md` reutiliza esa
  misma regla.

### 2.2 Nuevo en Fase 3

- `HardRuleResult.rule_id = "known_result"` (`POLICY_ENGINE_SPEC.md`
  §2.1) — bloquea explícitamente evaluar una `Opportunity` cuyo
  `event_results` ya existe antes de `data_cutoff_timestamp`, algo que
  Fase 2 no necesitaba prevenir porque no tenía Policy Engine.
- `PolicyManifest` congelado en el tiempo: `PolicyDecision.policy_version`
  + `policy_manifest_hash` permiten reconstruir exactamente qué reglas
  estaban activas en el momento de la decisión, incluso si el manifiesto
  activo cambió después (Corrección D, "policy_version" explícito).

---

## 3. Reproducibilidad determinística

Dada la 7-tupla de versiones + `data_cutoff_timestamp` +
`market_snapshot_timestamp`, y el estado exacto de
`event_snapshots`/`feature_snapshots` en ese instante, una
`OpportunityEvaluation` debe ser **reconstruible exactamente** (mismo
resultado de `PolicyDecision`) sin depender de:

- El reloj del sistema en el momento de la reconstrucción.
- El orden de ejecución de otros procesos concurrentes.
- Ningún estado mutable global (mismo principio ya declarado
  explícitamente en `edge.py`/`expected_value.py`: "100% puras y
  deterministas, sin I/O, sin dependencia del reloj").

Toda función nueva en `src/policy/`, `src/calibration/`, `src/payoff/`,
`src/evidence/` sigue la misma disciplina: recibe el "ahora" como
parámetro inyectable cuando lo necesita (mismo patrón que
`compute_quality_score(..., now: Optional[datetime] = None)`, Fase 2),
nunca llama a `datetime.now()` internamente sin parámetro.

---

## 4. Tests obligatorios (ver también `IMPLEMENTATION_ROADMAP_FASE3.md`)

| Tipo de test | Qué verifica |
|---|---|
| **Temporal leakage test** | Construir un `event_snapshots` con `captured_at` posterior a `data_cutoff_timestamp` y verificar que el Feature Builder/Calibration Layer lo excluye |
| **Reproducibility test** | Ejecutar la misma `OpportunityEvaluation` dos veces con el mismo `data_cutoff_timestamp` inyectado y verificar `PolicyDecision` bit-a-bit idéntica |
| **Known-result test** | Verificar que `known_result` (Hard Block) se dispara cuando `event_results` ya existe antes del cutoff |
| **tz-aware enforcement test** | Todo contrato nuevo rechaza timestamps naive, replicando el patrón de test ya usado para `PModelOutput`/`SignalInputs` en Fase 2 |

---

## 5. Relación con `feature_set_version` vs `feature_schema_version`

`PModelOutput.feature_set_version` (Fase 2) y
`OpportunityEvaluation.feature_schema_version` (Fase 3, `CONTRACTS_FASE3.md`
§13) son **el mismo valor** — alias de documentación, no dos campos que
puedan desincronizarse. No se introduce un nuevo esquema de versionado de
features en Fase 3; se propaga literalmente el que ya existe.
