# Contratos de Datos — Fase 3

Convención: todo contrato nuevo se implementa como `pydantic.BaseModel`
con `model_config = ConfigDict(extra="forbid", validate_assignment=True)`
— exactamente el patrón `StrictModel` ya establecido en
`src/models/schemas.py` (Fase 2) — salvo donde se indica explícitamente
`dataclass(frozen=True)` para replicar el patrón de `SignalInputs`
(inmutabilidad de una evaluación puntual). Ningún contrato inventa un
valor cuando la entrada real no está disponible: el campo queda `None` y,
si existe una lista de motivos/faltantes en el contrato, se registra ahí
(mismo principio no negociable de Fase 1/2).

Todo timestamp es `datetime` tz-aware UTC obligatorio — mismo invariante
que `PModelOutput`/`SignalInputs`/`HistoryRepository` ya exigen
(`ValueError` si es naive). Ver `TEMPORAL_REPRODUCIBILITY_SPEC.md` para
el contrato temporal transversal que aplica a los contratos de abajo.

Este documento definía originalmente 16 contratos (§1-§16, cierre de la
auditoría inicial). §17 (`ExplanationOutput`) se añadió durante el Paso
3.6 como adición contractual correctiva, aprobada explícitamente por el
usuario — ver §17 y `CONTINUITY.md` §0.13 para el detalle completo.

---

## 0. Contratos reutilizados sin cambios (no se listan campo por campo)

- `Sport`, `EventStatus`, `SourceStatus`, `MatchMethod`, `NormalizedRecord`,
  `MarketData`, `DataQuality` — `src/models/schemas.py` (Fase 2).
- `ModelStatus`, `PModelOutput` — `src/models/base.py` (Fase 2).
- `Side`, `SignalType`, `SignalInputs` — `src/signals/signal_schema.py`
  (Fase 2). **`SignalInputs` es el input directo del Policy Engine en
  Fase 3** — no se modifica, se ensambla desde `CalibrationOutput` +
  `PayoffEstimate` + `ConfidenceProfile` en vez de desde valores sueltos.
- `QualityScoreOutput` — `src/uncertainty/quality_score.py` (Fase 2),
  fuente de `ConfidenceProfile.data_quality`/`market_quality`.

---

## 1. `ModelOutput` (contrato lógico, no una clase nueva)

**Resolución de la colisión de nombre** (ver `PLAN_MASTER_FASE3.md` §5,
Hallazgo #1): el contrato "ModelOutput" pedido para Fase 3 se satisface
por **composición** de dos contratos, ninguno de los cuales es la clase
`ModelOutput` que ya existe (vacía, siempre `None`) dentro de
`NormalizedRecord` en `src/models/schemas.py`.

```
ModelOutput (Fase 3, lógico) = PModelOutput (Fase 2, sin cambios)
                              + CalibrationOutput (§2, nuevo)
```

`NormalizedRecord.model_output` permanece sin poblar para siempre —
ningún componente de Fase 3 escribe en ese campo.

---

## 2. `CalibrationOutput` [NUEVO]

```python
class CalibrationOutput(StrictModel):
    p_model_raw: Optional[float]            # = PModelOutput.p_model_yes, copiado, no recalculado
    p_model_calibrated: Optional[float]      # None si no existe capa de calibración activa para
                                              # este model_version, o si p_model_raw es None
    model_version: Optional[str]             # = PModelOutput.model_version (Optional[str] en Fase
                                              # 2 también -- None cuando model_status=
                                              # MODEL_NOT_TRAINED, ver mlb_baseline.py/
                                              # tennis_baseline.py; RECTIFICADO durante el Paso 3.1,
                                              # ver nota abajo)
    calibration_version: Optional[str]       # None mientras no exista calibración entrenada
                                              # (estado válido y esperado, igual que
                                              # ModelStatus.MODEL_NOT_TRAINED en Fase 2)
    calibration_method: Optional[str]        # p.ej. "PLATT_V1", "ISOTONIC_V1"; None si no calibrado
    calibrated_at: Optional[datetime]
    prediction_timestamp: datetime           # = PModelOutput.prediction_timestamp, propagado
    data_cutoff_timestamp: datetime          # = PModelOutput.data_cutoff_timestamp, propagado
```

**Invariantes:**
- `p_model_calibrated is not None` ⟹ `calibration_version is not None` (nunca un valor calibrado sin
  saber con qué versión).
- Si `p_model_raw is None` (modelo no entrenado): `p_model_calibrated` debe ser `None` — mismo
  invariante que `PModelOutput.__post_init__` ya impone sobre `p_model_yes`.
- `p_model_calibrated`, si no es `None`, debe estar en `[0.0, 1.0]`.
- Mientras `calibration_version is None`, todo consumidor aguas abajo (Policy Engine) debe usar
  `p_model_raw` explícitamente y registrar la ausencia de calibración como un componente de
  `model_reliability` reducido en `ConfidenceProfile` — nunca sustituir `p_model_calibrated` por
  `p_model_raw` silenciosamente sin dejar rastro.

**Rectificación de contrato (aplicada durante el Paso 3.1, antes de
implementar `calibration_layer.py`, ver `CONTINUITY.md` §0.3):**
`model_version` se documentaba y se implementó en el Paso 3.0 como `str`
obligatorio. Se corrigió a `Optional[str]` porque `PModelOutput.model_version`
(su fuente literal) ya es `Optional[str]` en Fase 2, y el código real de
`mlb_baseline.py`/`tennis_baseline.py` lo construye en `None` junto con
`p_model_yes=None` cuando `model_status=MODEL_NOT_TRAINED` — el estado
más común, no un caso extremo. Exigir `str` habría hecho que
`CalibrationOutput` fallara precisamente en ese caso. No es un cambio de
diseño: es la corrección de una transcripción incompleta del propio
Paso 3.0.

---

## 3. `PayoffEstimate` [NUEVO]

Sustituye, como punto de entrada de EV neto, el `NotImplementedError`
deliberado de `compute_ev_yes_neto`/`compute_ev_no_neto` (Fase 2,
`src/signals/expected_value.py`, sin cambios).

```python
class NetEvStatus(str, Enum):
    COMPUTED = "COMPUTED"
    UNKNOWN = "UNKNOWN"          # costos no verificables con evidencia real -- nunca se inventan


class PayoffEstimate(StrictModel):
    opportunity_id: str
    side: Side
    platform: str                        # p.ej. "KALSHI"
    entry_price: Optional[float]         # market_price_yes/no ya calculado (Fase 2, reutilizado)
    payout: Optional[float]              # 1.0 para un contrato binario estándar; explícito, no asumido
    loss: Optional[float]                # = entry_price si el contrato liquida en contra
    entry_fee: Optional[float]           # None si la plataforma no lo expone (hoy: Kalshi no lo expone)
    estimated_exit_fee: Optional[float]
    spread: Optional[float]              # = MarketData.spread_yes/spread_no, reutilizado
    slippage_estimate: Optional[float]
    ev_to_settlement: Optional[float]
    ev_to_planned_exit: Optional[float]
    breakeven_probability: Optional[float]
    max_acceptable_entry_price: Optional[float]
    net_ev_status: NetEvStatus
    cost_evidence_refs: List[str] = []   # de dónde vino cada costo usado (auditable); vacío si
                                          # net_ev_status=UNKNOWN
    computed_at: datetime
```

**Invariantes:**
- `net_ev_status == NetEvStatus.COMPUTED` ⟹ `ev_to_settlement is not None` y
  `cost_evidence_refs` no vacío.
- `net_ev_status == NetEvStatus.UNKNOWN` ⟹ `ev_to_settlement is None`, `ev_to_planned_exit is None`.
  Ningún costo se estima por defecto/heurística cuando falta evidencia — corrección C, literal.
- Mientras Kalshi no exponga `exchange_fee`/`estimated_exit_fee` reales (estado actual verificado en
  Fase 2, ver `FASE2_CIERRE_FINAL.md` §5), `net_ev_status` es `UNKNOWN` para el 100% de las
  oportunidades — esto es el comportamiento correcto, no un bug.

---

## 4. `ConfidenceProfile` [NUEVO]

```python
class ConfidenceProfile(StrictModel):
    opportunity_id: str
    data_quality: Optional[float]        # [0,100], deriva de QualityScoreOutput (Fase 2)
    model_reliability: Optional[float]   # [0,100], deriva de EvaluationRecord histórico; None si
                                          # no hay histórico evaluado del model_version/calibration_version activo
    market_quality: Optional[float]      # [0,100], deriva de QualityScoreOutput (Fase 2)
    operational_safety: Optional[float]  # [0,100] = 100 - operational_risk (Corrección B)
    operational_risk: Optional[float]    # [0,100], complemento exacto del anterior
    aggregate_confidence: Optional[float]  # [0,100] agregación explícita del Policy Engine, NUNCA
                                            # usada por AnalysisHealth (Principio 5)
    quality_score_component_ref: Optional[str]  # confidence_config_version de QualityScoreOutput
                                                   # usado, para trazabilidad
    computed_at: datetime
```

**Invariantes:**
- Las 4 dimensiones nombradas usan la **misma dirección**: 100 = mejor condición, 0 = peor
  (Corrección B, literal) — `operational_risk` es la única excepción documentada, y solo porque
  existe precisamente para definir `operational_safety = 100 - operational_risk`; el Policy Engine
  nunca lee `operational_risk` directamente, siempre `operational_safety`.
- Cualquier dimensión con entrada insuficiente es `None`, nunca 0 ni 50 (no se fabrica un "neutro").
- `aggregate_confidence` es responsabilidad exclusiva de `policy/soft_score.py` — este contrato solo
  transporta el valor ya calculado, no lo calcula.

---

## 5. `AnalysisHealth` [NUEVO]

```python
class AnalysisHealth(StrictModel):
    opportunity_id: str
    completeness_signal: Optional[float]   # [0,100]
    consistency_signal: Optional[float]    # [0,100] -- p.ej. discrepancias entre fuentes
    evidence_density: Optional[int]        # conteo de EvidenceItem disponibles
    staleness_seconds: Optional[float]
    warnings: List[str] = []
    computed_at: datetime
```

**Invariante no negociable (Principio 5, reforzado como regla de
contrato):** ningún campo de `AnalysisHealth` puede aparecer como término
de `SoftScoreComponent` ni de `HardRuleResult`. Se verifica con un test
de arquitectura (`IMPLEMENTATION_ROADMAP_FASE3.md`) que falla si
`src/policy/` importa `src/health/analysis_health.py` para algo distinto
de mostrarlo en la explicación (`explainability/`).

---

## 6. `EvidenceItem` [NUEVO]

```python
class EvidenceDirection(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    NEUTRAL = "NEUTRAL"


class EvidenceItem(StrictModel):
    opportunity_id: str
    fact: str                          # hecho estructurado, no texto libre generado
    direction: EvidenceDirection
    source_field: str                  # path exacto en NormalizedRecord/PModelOutput de donde vino
    source_timestamp: Optional[datetime]
    strength: Optional[float]          # [0,1], opcional -- None si no cuantificable
    generated_at: datetime
```

**Invariante:** `fact` se construye por plantilla a partir de campos reales ya poblados (p.ej.
`"pitcher probable confirmado: {name}"` solo si `lineup_or_pitcher` no es `None`) — el Evidence Engine
nunca genera un hecho sobre un campo `None` (ver `EVIDENCE_EXPLAINABILITY_SPEC.md` §1).

---

## 7. `EligibilityResult` [NUEVO]

```python
class EligibilityResult(StrictModel):
    opportunity_id: str
    is_eligible: bool
    ineligibility_reasons: List[str] = []   # vacío si is_eligible=True
    evaluated_at: datetime
```

Primer gate del Policy Engine (`policy/decision.py`), antes de Hard
Rules: verifica que `SignalInputs` esté estructuralmente completo
(`event_id`, `sport`, `side`, `generated_at` presentes) — no evalúa
calidad de datos, solo que el input sea evaluable en absoluto.

---

## 8. `HardRuleResult` [NUEVO]

```python
class HardRuleCategory(str, Enum):
    BLOCK = "HARD_BLOCK_PASS"
    HOLD = "HARD_HOLD_WATCH"


class HardRuleResult(StrictModel):
    rule_id: str                      # p.ej. "unsafe_matching", "unresolved_side_mapping"
    category: HardRuleCategory
    triggered: bool
    detail: Optional[str]
    evaluated_at: datetime
```

Lista cerrada de `rule_id` válidos — ver `POLICY_ENGINE_SPEC.md` §2 para
el catálogo completo (Corrección A + `unresolved_side_mapping` añadida en
esta auditoría).

---

## 9. `SoftScoreComponent` [NUEVO]

```python
class SoftScoreComponent(StrictModel):
    component_name: str               # p.ej. "edge_strength", "confidence_aggregate"
    value: Optional[float]             # [0,100], None si no calculable
    weight: float                      # peso efectivo usado en ESTE cálculo (mismo patrón que
                                        # QualityScoreOutput.weights: redistribuido, no estático)
    is_critical_minimum: bool          # True si este componente tiene un mínimo individual exigido
                                        # para ENTER (Principio 9)
    minimum_required: Optional[float]  # umbral mínimo si is_critical_minimum=True
    passed_minimum: Optional[bool]     # None si value es None
```

**Invariante (Principio 9, literal):** un `SoftScoreComponent` con
`is_critical_minimum=True` y `passed_minimum=False` **bloquea ENTER**
independientemente del score global agregado — ver
`POLICY_ENGINE_SPEC.md` §3.

---

## 10. `SignalReason` [NUEVO]

```python
class SignalReasonCode(str, Enum):
    HARD_BLOCK = "HARD_BLOCK"
    HARD_HOLD = "HARD_HOLD"
    SOFT_SCORE_BELOW_GLOBAL = "SOFT_SCORE_BELOW_GLOBAL"
    CRITICAL_MINIMUM_NOT_MET = "CRITICAL_MINIMUM_NOT_MET"
    ELIGIBLE_AND_SCORED = "ELIGIBLE_AND_SCORED"


class SignalReason(StrictModel):
    code: SignalReasonCode
    detail: str
    source_component: Optional[str]     # p.ej. rule_id o component_name que lo originó
```

Una `PolicyDecision` lleva 1+ `SignalReason` — es la lista mínima,
estructurada (no texto libre), que el Explainability Engine convierte en
explicación legible (Principio 14).

---

## 11. `PolicyDecision` [NUEVO]

```python
class AbstentionDisposition(str, Enum):
    NO_VALUE = "NO_VALUE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    POLICY_REJECTED = "POLICY_REJECTED"


class PolicyDecision(StrictModel):
    opportunity_id: str
    side: Side
    signal_type: SignalType             # ENTER | WATCH | PASS (Fase 2, reutilizado)
    disposition: Optional[AbstentionDisposition]   # obligatorio si signal_type == PASS,
                                                     # None si ENTER/WATCH (Corrección G)
    reasons: List[SignalReason]         # nunca vacío
    hard_rule_results: List[HardRuleResult]
    soft_score_components: List[SoftScoreComponent]
    aggregate_soft_score: Optional[float]
    policy_version: str
    policy_manifest_hash: str           # hash de contenido del manifiesto activo, para reproducibilidad
    decided_at: datetime
```

**Invariantes:**
- `signal_type == PASS` ⟹ `disposition is not None` (Corrección G, literal — el sistema nunca
  abstiene sin decir por qué en un vocabulario cerrado).
- `signal_type == ENTER` ⟹ ningún `HardRuleResult` con `category == BLOCK` y `triggered == True`, y
  todo `SoftScoreComponent` con `is_critical_minimum == True` tiene `passed_minimum == True`
  (Principio 9, verificado a nivel de contrato con un validador, no solo de convención).
- `reasons` nunca vacío — toda decisión es trazable a al menos un motivo estructurado.

---

## 12. `Opportunity` [NUEVO]

```python
class Opportunity(StrictModel):
    opportunity_id: str                 # estable, determinístico -- ver invariante abajo
    event_id: str                       # = NormalizedRecord.event_id (Fase 1/2, reutilizado)
    market_id: Optional[str]            # = NormalizedRecord.market_id
    selection_id: str                   # = f"{market_id}:{side.value}" -- ver Hallazgo de Contrato #3
    side: Side
    sport: Sport
    first_seen_at: datetime
    last_evaluated_at: datetime
    state_version: int                  # incrementa en cada nueva OpportunityEvaluation, nunca decrece
    previous_signal_id: Optional[str]   # id de la OpportunityEvaluation anterior, encadenamiento cronológico
```

**Invariante de identidad:** `opportunity_id` se deriva determinísticamente de
`(event_id, selection_id)` — dos llamadas para el mismo evento/lado producen el mismo
`opportunity_id`, permitiendo reconstrucción sin tabla de lookup adicional (mismo espíritu que
`event_id` en Fase 1: estable, reconstruible, no un UUID aleatorio).

---

## 13. `OpportunityEvaluation` [NUEVO]

```python
class OpportunityEvaluation(StrictModel):
    evaluation_id: str                  # único por evaluación, nunca reutilizado
    opportunity_id: str
    state_version: int                  # = Opportunity.state_version en el momento de esta evaluación
    signal_inputs: SignalInputs         # Fase 2, reutilizado tal cual, embebido
    calibration_output: CalibrationOutput
    payoff_estimate: Optional[PayoffEstimate]
    confidence_profile: ConfidenceProfile
    analysis_health: AnalysisHealth
    evidence_items: List[EvidenceItem]
    policy_decision: PolicyDecision
    decision_timestamp: datetime
    data_cutoff_timestamp: datetime
    market_snapshot_timestamp: Optional[datetime]
    model_version: str
    calibration_version: Optional[str]
    policy_version: str
    feature_schema_version: str          # = feature_set_version (Fase 2), alias documentado, no
                                          # un campo nuevo distinto -- ver TEMPORAL_REPRODUCIBILITY_SPEC.md
```

**Invariante de inmutabilidad (Principio 10, literal):** una vez
persistida, una `OpportunityEvaluation` **nunca se actualiza ni se
borra** — mismo patrón `INSERT-only` + triggers `RAISE(ABORT, ...)` ya
verificado y probado en `HISTORY_SCHEMA_SQL`
(`src/storage/history_repository.py`, Fase 2). Una re-evaluación de la
misma `Opportunity` crea una **nueva** fila con `state_version`
incrementado y `previous_signal_id` apuntando a la anterior.

---

## 14. `EvaluationRecord` [NUEVO]

```python
class EvaluationRecord(StrictModel):
    record_id: str
    scope: str                          # "model_performance" | "decision_performance" |
                                         # "financial_performance" | "operational_performance" |
                                         # "learning_performance" (Principio 15)
    sport: Optional[Sport]
    market_type: Optional[str]
    model_version: Optional[str]
    calibration_version: Optional[str]
    policy_version: Optional[str]
    metric_name: str                    # p.ej. "brier_score", "clv_1h", "roi_realizado"
    metric_value: Optional[float]
    sample_size: int
    confidence_interval_low: Optional[float]
    confidence_interval_high: Optional[float]
    computed_at: datetime
    evaluation_window_start: datetime
    evaluation_window_end: datetime
```

Ver `EVALUATION_LEARNING_SPEC.md` para el catálogo completo de
`metric_name` válidos por dimensión.

---

## 15. `PolicyManifest` [NUEVO]

```python
class PolicyManifest(StrictModel):
    policy_version: str                 # semver, p.ej. "1.0.0"
    sport: Sport                        # una política por deporte (Principio 1), no global
    hard_block_rules: List[str]         # rule_ids activos de HARD_BLOCK_PASS
    hard_hold_rules: List[str]          # rule_ids activos de HARD_HOLD_WATCH
    soft_score_weights: Dict[str, float]
    critical_minimums: Dict[str, float] # component_name -> umbral mínimo (Principio 9)
    hard_rule_parameters: Dict[str, float]  # rule_id (o rule_id.param) -> valor -- RECTIFICACIÓN
                                              # ADITIVA del Paso 3.4.5 (aprobada explícitamente,
                                              # ver CONTINUITY.md §0.11): resuelve la promesa de
                                              # "pending_lineup... N configurable en PolicyManifest"
                                              # (POLICY_ENGINE_SPEC.md §2.2) que el contrato original
                                              # del Paso 3.0 no cubría. default={} , retrocompatible.
    enter_global_threshold: float
    watch_global_threshold: float
    manifest_hash: str                  # hash de contenido, recalculado, no declarado a mano
    created_at: datetime
    promoted_at: Optional[datetime]     # None mientras esté en shadow/staging
    promotion_gate_report_ref: Optional[str]
```

Ver `POLICY_ENGINE_SPEC.md` §5 para el pipeline completo de validación
(Corrección H) y `SHADOW_MODE_AND_PROMOTION_GATES.md` para
`promotion_gate_report_ref`.

---

## 16. `SignalInputs` (reutilizado, referencia)

Ver `src/signals/signal_schema.py` (Fase 2, sin cambios) — campos:
`event_id`, `sport`, `side`, `model_status`, `p_model`, `market_price`,
`edge`, `ev_bruto`, `ev_neto`, `confidence`, `confidence_method`,
`generated_at`. En Fase 3, `p_model` se puebla desde
`CalibrationOutput.p_model_calibrated` si existe, si no desde
`p_model_raw` (con la advertencia de trazabilidad de §2); `ev_neto` se
puebla desde `PayoffEstimate.ev_to_settlement` cuando
`net_ev_status == COMPUTED`, si no permanece `None` exactamente como hoy.

---

## 17. `ExplanationOutput` [NUEVO — ADICIÓN CONTRACTUAL CORRECTIVA, Paso 3.6]

`EVIDENCE_EXPLAINABILITY_SPEC.md` §2 esbozó este contrato durante la
auditoría original, pero quedó fuera de la lista cerrada de 16 (§1-§16
de este documento) y del scaffolding del Paso 3.0 — `src/explainability/`
no existía. Se incorpora aquí, formalmente, como 17ª entrada, aprobada
explícitamente por el usuario antes de crear el archivo (ver
`CONTINUITY.md` §0.13). No es un requisito nuevo: el Principio 6/14
(Evidence Engine y Explainability Engine separados) siempre exigió que
este contrato existiera en algún lugar — solo faltaba enumerarlo.

```python
class ExplanationOutput(StrictModel):
    opportunity_id: str
    evaluation_id: str
    headline: str                      # construido solo desde PolicyDecision
                                        # (signal_type/disposition/aggregate_soft_score)
    reasons_explained: List[str]       # una entrada por SignalReason real, nunca vacío
    evidence_for: List[str]            # subset de EvidenceItem.fact con direction=FOR
    evidence_against: List[str]        # subset de EvidenceItem.fact con direction=AGAINST
    disclaimers: List[str]             # obligatorio no vacío si calibration_version=None
                                        # o net_ev_status=UNKNOWN (recibidos como primitivos,
                                        # ver src/explainability/explainability_engine.py)
    generated_at: datetime
```

**Invariantes:**
- `headline` no puede estar vacío.
- `reasons_explained` no puede estar vacío — toda explicación traza al menos un `SignalReason`
  real (mismo invariante que `PolicyDecision.reasons`, §11).
- `generated_at` tz-aware obligatorio.
- `evidence_for`/`evidence_against`/`disclaimers` pueden estar vacíos (ausencia de evidencia o de
  advertencias es un estado válido, nunca se fabrica contenido de relleno).

Producido por `explain(policy_decision, evidence_items, evaluation_id, calibration_version=None,
net_ev_status_is_unknown=False, now=None)` (`src/explainability/explainability_engine.py`, Paso 3.6)
— consume únicamente `PolicyDecision` (§11) y `EvidenceItem[]` (§6) ya calculados, nunca re-deriva
desde `NormalizedRecord` ni desde `QualityScoreOutput` (Principio 6, verificado por test de
arquitectura). `calibration_version`/`net_ev_status_is_unknown` se reciben como primitivos
(`Optional[str]`/`bool`), no como `CalibrationOutput`/`NetEvStatus` completos, para no ampliar la
regla de dependencia de `ARCHITECTURE_FASE3.md` §4.

---

## Resumen de versionado transversal

Todo contrato que participe en una `OpportunityEvaluation` lleva, directa
o indirectamente, las 7 versiones exigidas por Corrección D:
`model_version`, `calibration_version`, `policy_version`,
`feature_schema_version`, más los 3 timestamps
(`decision_timestamp`/`data_cutoff_timestamp`/`market_snapshot_timestamp`).
Ver `TEMPORAL_REPRODUCIBILITY_SPEC.md` para las reglas de propagación y
los tests de fuga temporal.
