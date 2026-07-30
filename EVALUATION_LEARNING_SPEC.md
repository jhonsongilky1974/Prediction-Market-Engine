# Evaluation & Learning Framework — Especificación (Fase 3)

Principio 15, Corrección F. Módulo propuesto: `src/evaluation/learning.py`
(nuevo, dentro del paquete `evaluation/` ya existente). Ver
[`CONTRACTS_FASE3.md`](CONTRACTS_FASE3.md) §14 (`EvaluationRecord`).

**Advertencia de alcance (reafirmada de `PLAN_MASTER_FASE3.md` §0):**
este framework se construye y se prueba en Fase 3 con fixtures
controlados. Producir `EvaluationRecord` con valores estadísticamente
significativos sobre datos reales depende de DECISIÓN PENDIENTE D-1
(histórico real: hoy `feature_snapshots=0`, `event_results=0`). Ningún
`sample_size` se infla ni se simula para aparentar significancia.

---

## 1. Las 5 dimensiones (Principio 15)

| Dimensión (`EvaluationRecord.scope`) | Responde a | Métricas (catálogo `metric_name`) |
|---|---|---|
| `model_performance` | ¿Qué tan buena es la probabilidad, aislada del mercado y de la decisión? | `brier_score`, `log_loss`, `ece`, `calibration_curve_bucket` |
| `decision_performance` | ¿La clasificación ENTER/WATCH/PASS fue razonable dado lo que se sabía en ese momento? | `clv_1h`, `clv_24h`, `clv_at_close`, `abstention_rate`, `missed_opportunity_rate` |
| `financial_performance` | ¿Qué resultado monetario tuvo, si se registró manualmente? | `roi_teorico`, `roi_realizado`, `yield`, `drawdown`, `profit_factor` |
| `operational_performance` | ¿El sistema operó de forma confiable? | `hard_hold_rate`, `pipeline_error_rate`, `data_staleness_p95` |
| `learning_performance` | ¿La calibración/política mejora versión sobre versión? | `brier_score_delta_vs_previous`, `policy_regression_pass_rate` |

Cada métrica es una fila `EvaluationRecord` — nunca un solo número
agregado sin `sample_size`/intervalo de confianza asociado (Corrección
F, literal).

---

## 2. Distinciones obligatorias (Corrección F, literal)

El framework debe poder responder estas 5 preguntas por separado, nunca
mezcladas en un solo score:

1. **Calidad de la probabilidad** (`model_performance`) — ¿`p_model_calibrated`
   estaba bien calibrado? (Brier, ECE) — independiente de si el sistema
   decidió ENTER o no.
2. **Calidad de la decisión** (`decision_performance`) — ¿Dado lo que se
   sabía en `data_cutoff_timestamp`, la clasificación fue razonable?
   Evaluable incluso cuando el resultado del evento salió mal (una
   decisión puede ser correcta con información incompleta y aun así
   perder).
3. **Resultado del evento** — el hecho crudo (`event_results`, Fase 2,
   reutilizado), sin interpretación.
4. **Resultado financiero** (`financial_performance`) — depende de
   `PayoffEstimate` real y de si hubo registro manual de ejecución
   (Principio 21: no hay ejecución automática, así que "ROI realizado"
   depende de que un humano registre manualmente qué hizo).
5. **Movimiento posterior del mercado** — CLV (`decision_performance`):
   compara el precio de entrada contra el precio de cierre/en horizontes
   posteriores, independientemente de si el modelo tenía razón sobre el
   resultado final.

Reutiliza el precedente de Fase 2: `src/evaluation/reports.py` ya
distingue calibración de un modelo de accuracy de umbral (Baseline 0 vs
1 vs 2) — este framework generaliza ese principio a las 5 dimensiones.

---

## 3. Extensión de `src/backtesting/metrics.py` (aditiva)

Nuevas funciones puras, mismo estilo `(y_true, y_pred) -> Optional[T]`
que las 4 ya existentes (`brier_score`, `log_loss_metric`,
`accuracy_metric`, `calibration_curve`):

```python
def ece(y_true: Sequence[int], y_pred: Sequence[float], n_bins: int = DEFAULT_CALIBRATION_BINS) -> Optional[float]:
    """Expected Calibration Error -- construida sobre calibration_curve()
    ya existente, no reimplementa el binning."""

def clv(entry_price: float, closing_price: float) -> Optional[float]:
    """Closing Line Value de una sola observación -- agregación
    (media/percentiles por horizonte) es responsabilidad del llamador,
    no de esta función pura."""

def roi_teorico(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """(stake, payout_neto) -- ROI si se hubiera apostado 1 unidad por
    señal ENTER. None si no hay pares."""

def drawdown(equity_curve: Sequence[float]) -> Optional[float]:
    """Máxima caída peak-to-trough de una curva de equity teórica."""

def profit_factor(gains: Sequence[float], losses: Sequence[float]) -> Optional[float]:
    """sum(gains) / abs(sum(losses)). None si losses está vacío o suma 0."""
```

Ninguna firma ni función existente de `metrics.py` se modifica — 100%
aditivo, mismo criterio de "`None` si no hay muestras, nunca un valor
fabricado" que ya rige las 4 funciones actuales.

---

## 4. Abstention analysis y missed-opportunity analysis (Corrección F)

Dos análisis explícitos, no opcionales, sobre `OpportunityEvaluation`
históricas:

- **Abstention analysis**: para toda `PolicyDecision` con
  `signal_type=PASS`, agrupar por `disposition` (Corrección G) y medir
  cuántas veces cada `disposition` se disparó — si `POLICY_REJECTED`
  domina desproporcionadamente, es señal de que el manifiesto es
  demasiado conservador (o el mercado real no ofrece valor, lo cual
  también es una conclusión válida).
- **Missed-opportunity analysis**: para toda `PolicyDecision` con
  `signal_type in (WATCH, PASS)`, comparar retroactivamente el resultado
  real del evento contra qué hubiera pasado con un ENTER hipotético —
  **estrictamente post-hoc, nunca usado para re-decidir la señal
  original** (violaría integridad temporal, ver
  `TEMPORAL_REPRODUCIBILITY_SPEC.md`). Su único uso es alimentar
  `learning_performance` (¿el manifiesto está dejando pasar valor real
  de forma sistemática?).

---

## 5. Segmentación (reutiliza precedente de Fase 2)

`src/evaluation/reports.py` (Fase 2) ya segmenta por edge/confianza/
liquidez (`segment_by_edge`, `segment_by_confidence`,
`segment_by_liquidity`). El framework de Fase 3 reutiliza exactamente ese
patrón (`_segment_pairs`, buckets de ancho fijo) para producir
`EvaluationRecord` segmentados por:

- `sport`
- `market_type`
- `policy_version`

Sin reimplementar el binning — se extiende `reports.py` importando su
función genérica de segmentación, o se replica el patrón exacto en
`learning.py` si `_segment_pairs` no se expone públicamente (decisión de
implementación, no de diseño, a resolver en el paso correspondiente del
roadmap).
