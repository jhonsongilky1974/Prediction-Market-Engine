# Policy Engine — Especificación (Fase 3)

Ver contratos en [`CONTRACTS_FASE3.md`](CONTRACTS_FASE3.md) §7-11, §15.
Módulo propuesto: `src/policy/` (nuevo, ver
[`ARCHITECTURE_FASE3.md`](ARCHITECTURE_FASE3.md) §1).

---

## 1. Núcleo común + políticas por deporte (Principio 1)

Un único motor de decisión (`policy/decision.py`) ejecuta siempre la
misma secuencia de 4 etapas (§1.1). Lo que varía por deporte es
exclusivamente el contenido de `PolicyManifest` (rule_ids activos, pesos,
umbrales) — nunca la lógica de las etapas. Esto evita que "política por
deporte" degenere en ramas de código por deporte (`if sport == MLB: ...`)
dentro del motor, que sería deuda técnica inmediata y contradiría
Principio 16 (extensibilidad por interfaces).

### 1.1 Secuencia (Principio 8, híbrido)

```
SignalInputs + CalibrationOutput + PayoffEstimate + ConfidenceProfile
        |
        v
  [1] EligibilityResult   -- ¿es evaluable en absoluto?
        | is_eligible=False -> PolicyDecision(PASS, disposition=INVALID_ANALYSIS), FIN
        v
  [2] Hard Block Rules (HARD_BLOCK_PASS)
        | cualquiera triggered=True -> PolicyDecision(PASS, disposition=POLICY_REJECTED o
        |                              MARKET_UNAVAILABLE según regla), FIN -- Soft Score NUNCA se evalúa
        v
  [3] Hard Hold Rules (HARD_HOLD_WATCH)
        | cualquiera triggered=True -> PolicyDecision(WATCH), FIN -- Soft Score NUNCA se evalúa
        v
  [4] Soft Score  (solo se llega aquí sin ningún bloqueo activo, Principio 8 literal)
        | -> PolicyDecision(ENTER | WATCH | PASS[disposition=NO_VALUE])
```

Esto formaliza literalmente el Principio 8: "Soft Rules y score solamente
si no existen bloqueos" — no es una optimización, es un invariante de
control de flujo verificado por contrato (`PolicyDecision` con
`signal_type in (ENTER,)` no puede coexistir con un `HardRuleResult`
`BLOCK` `triggered=True`, ver `CONTRACTS_FASE3.md` §11).

---

## 2. Catálogo de Hard Rules (Corrección A + 1 adición de esta auditoría)

### 2.1 `HARD_BLOCK_PASS` (bloqueo estructural, PASS inmediato)

| `rule_id` | Detecta | Fuente de evidencia |
|---|---|---|
| `unsafe_matching` | `MatchMethod in (NEEDS_REVIEW, NO_MATCH)` o `match_confidence` por debajo de `EVENT_NAME_MATCH_MIN_CONFIDENCE` (Fase 1, `config/settings.py`, reutilizado) | `NormalizedRecord.data_quality` |
| `invalid_event` | `EventStatus in (CANCELLED,)` o inconsistencia de horario irrecuperable | `NormalizedRecord.status` |
| `invalid_or_closed_market` | `market_price_yes`/`market_price_no` ambos `None` de forma persistente, o mercado ya liquidado | `src/pricing/market_pricing.py` (Fase 2, reutilizado) |
| `incompatible_contract` | El contrato no es un binario YES/NO estándar (p.ej. multi-outcome no soportado) | `NormalizedRecord.market` |
| `corrupted_critical_data` | `DataQuality.validation_errors` no vacío sobre un campo `CORE_FIELDS` | `src/quality/completeness.py` (Fase 2, reutilizado) |
| `known_result` | `event_results` (Fase 2, `HistoryRepository`) ya tiene un resultado registrado para este `event_id` antes de `data_cutoff_timestamp` — previene evaluar algo ya decidido | `HistoryRepository.get_results_for_event` |
| `non_recoverable_inconsistency` | Cualquier excepción no controlada durante el ensamblado de `SignalInputs` (Principio 20, fail-safe) | interno |

### 2.2 `HARD_HOLD_WATCH` (recuperable, WATCH)

| `rule_id` | Detecta | Fuente de evidencia |
|---|---|---|
| `pending_lineup` | `model_inputs.lineup_or_pitcher is None` y el evento está a menos de N horas de inicio (N configurable en `PolicyManifest`) | `NormalizedRecord.model_inputs` |
| `unconfirmed_pitcher` | Específico MLB: pitcher probable no confirmado | `model_inputs.lineup_or_pitcher` (MLB) |
| `temporarily_stale_data` | `AnalysisHealth.staleness_seconds` por encima de un umbral | `health/analysis_health.py` (nuevo) |
| `temporarily_insufficient_liquidity` | `market.volume`/`open_interest` por debajo de un mínimo operable (distinto del componente informativo de `quality_score.py`) | `NormalizedRecord.market` |
| `recoverable_missing_information` | Campos no-críticos de `CORE_FIELDS` ausentes pero no bloqueantes | `DataQuality.missing_fields` |
| `unresolved_side_mapping` **[añadido en esta auditoría]** | Siempre `triggered=True` mientras la Ambigüedad #2 de Fase 2 (mapeo participante↔YES de un contrato Kalshi concreto) no esté resuelta — ver `PLAN_MASTER_FASE3.md` §5, Hallazgo #2 y DECISIÓN PENDIENTE D-2 | Constante de configuración, no derivada del registro individual — aplica a todo `Opportunity` de MLB/Tenis hasta que D-2 se resuelva |

**Consecuencia directa de `unresolved_side_mapping`:** con el catálogo de
arriba, ninguna `Opportunity` puede alcanzar `ENTER` hasta que D-2 se
resuelva explícitamente — el sistema queda, por diseño, en el estado más
conservador posible (nunca `WATCH` se degrada a `ENTER` por accidente).
Esto es intencional y debe declararse así en cualquier ejecución real
antes de que D-2 se resuelva.

Todo `rule_id` fuera de estas dos listas es rechazado por
`policy/validation.py` (Corrección H) al cargar un `PolicyManifest`
— lista cerrada, no extensible sin actualizar este documento primero.

---

## 3. Soft Score (Principio 9)

`policy/soft_score.py` calcula `SoftScoreComponent[]` y los agrega en
`aggregate_soft_score` (`[0,100]`) **solo si** ninguna Hard Rule
disparó. Componentes propuestos (configurables por `PolicyManifest`, no
hardcoded):

| `component_name` | `is_critical_minimum` | Fuente |
|---|---|---|
| `edge_strength` | No | `SignalInputs.edge` normalizado |
| `ev_neto_strength` | Sí | `PayoffEstimate.ev_to_settlement` — si `net_ev_status=UNKNOWN`, `value=None`, `passed_minimum=None` ⟹ no puede pasar el mínimo, nunca ENTER con EV desconocido |
| `confidence_aggregate` | Sí | `ConfidenceProfile` (las 4 dimensiones agregadas) |
| `data_quality_floor` | Sí | `ConfidenceProfile.data_quality` |
| `operational_safety_floor` | Sí | `ConfidenceProfile.operational_safety` |

### 3.1 Regla de no compensación (Principio 9, literal)

```
ENTER es válido  <=>  aggregate_soft_score >= PolicyManifest.enter_global_threshold
                       AND
                       para todo c en soft_score_components donde c.is_critical_minimum:
                           c.passed_minimum == True
```

Un score global alto **nunca** compensa un mínimo crítico incumplido —
verificado como invariante de contrato en `PolicyDecision`
(`CONTRACTS_FASE3.md` §11), no solo como convención de implementación.
`ev_neto_strength` como mínimo crítico es la corrección más importante de
esta sección: significa que, mientras `net_ev_status=UNKNOWN` sea el
estado universal (ver §2.1 de `CONTRACTS_FASE3.md`, DECISIÓN PENDIENTE
D-3), **ningún ENTER real es posible** — el sistema permanece en
`WATCH`/`PASS` hasta que exista evidencia real de costos. Esto es
consistente con Principio 21 (sin ejecución automática) y con la postura
conservadora exigida en Principio 2.

---

## 4. Un núcleo, políticas por deporte — ejemplo concreto

```
PolicyManifest(policy_version="1.0.0", sport=MLB,
    hard_hold_rules=[..., "unconfirmed_pitcher", "unresolved_side_mapping"], ...)

PolicyManifest(policy_version="1.0.0", sport=TENNIS,
    hard_hold_rules=[..., "unresolved_side_mapping"],   # sin "unconfirmed_pitcher": no aplica
    critical_minimums={"data_quality_floor": 40.0, ...})  # tenis, con SofaScore bloqueado
                                                            # (ver FASE2_CIERRE_FINAL.md §5),
                                                            # requiere un piso de calidad de datos
                                                            # más permisivo o el sistema nunca sale
                                                            # de PASS -- decisión de calibración,
                                                            # NO se fija un valor aquí (ver §5)
```

---

## 5. Policy Validation (Corrección H)

`policy/validation.py`, ejecutado antes de que cualquier
`PolicyManifest` pueda usarse (incluso en shadow mode):

1. **Schema validation** — `PolicyManifest` es un `StrictModel`
   (`extra="forbid"`), rechaza campos desconocidos automáticamente.
2. **Range validation** — todos los umbrales `[0,100]` o `[0,1]` según
   corresponda; `enter_global_threshold >= watch_global_threshold`
   (obligatorio, si no la jerarquía ENTER > WATCH > PASS se rompe).
3. **Cross-field consistency validation** — todo `rule_id` en
   `hard_block_rules`/`hard_hold_rules` existe en el catálogo cerrado de
   §2; todo `component_name` en `critical_minimums` existe en el
   catálogo de §3; suma de `soft_score_weights` > 0.
4. **Regression tests** — el manifiesto nuevo se ejecuta contra el mismo
   conjunto fijo de fixtures de `tests/unit/` usados para el manifiesto
   anterior; cualquier `PolicyDecision` que cambie de categoría
   (ENTER↔WATCH↔PASS) se reporta explícitamente, no se bloquea
   automáticamente pero requiere revisión humana antes de promoción.
5. **Historical comparison** — cuando exista histórico real (D-1), el
   manifiesto nuevo se compara contra el activo sobre el mismo dataset de
   backtesting (mismo patrón que `compare_baselines`, Fase 2,
   `src/evaluation/reports.py`, reutilizado como precedente de diseño).
6. **Promotion criteria** — ver
   [`SHADOW_MODE_AND_PROMOTION_GATES.md`](SHADOW_MODE_AND_PROMOTION_GATES.md).

Una configuración que falla cualquiera de 1-3 es **rechazada antes de
ejecutarse** (Corrección H, literal) — nunca se carga un
`PolicyManifest` inválido en memoria para "ver qué pasa".

---

## 6. Fail-safe (Principio 20 aplicado al Policy Engine)

Cualquier excepción no controlada dentro de `policy/decision.py` se
captura en el borde externo del módulo (nunca dentro de `hard_rules.py`/
`soft_score.py`, que deben ser puras) y se traduce a
`PolicyDecision(signal_type=PASS, disposition=INVALID_ANALYSIS)` con
`reasons=[SignalReason(code=HARD_BLOCK, detail=<mensaje de la excepción>)]`.
El sistema nunca deja una `Opportunity` sin `PolicyDecision` ni fabrica un
`ENTER`/`WATCH` por defecto ante un error interno.
