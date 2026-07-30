# Shadow Mode y Promotion Gates — Especificación (Fase 3)

Principio 19, Corrección I. Sin ejecución automática en ninguna etapa
(Principio 21, restricción dura, reafirmada en todo este documento).

---

## 1. Release Path (5 etapas, orden obligatorio)

```
[1] Offline unit & contract testing
        |
        v
[2] Historical backtesting          <-- GATE DE DATOS, ver §2
        |
        v
[3] Shadow mode
        |
        v
[4] Paper tracking
        |
        v
[5] Manual decision support
```

**No existe una etapa 6 de ejecución automática.** Este plan no la
diseña, no la deja "preparada para después" con un flag apagado, y no
introduce ningún cliente de envío de órdenes — ver
`PLAN_MASTER_FASE3.md` §6 (restricción dura reafirmada).

---

## 2. Gate de entrada a la etapa [2] (encontrado en esta auditoría)

La etapa [1] no depende de datos reales — se ejecuta con fixtures desde
el momento en que el código de Fase 3 exista. La etapa [2] (Historical
Backtesting) **sí depende de histórico real**: hoy
`feature_snapshots=0`, `event_results=0`
(`FASE2_VALIDACION_INSTITUCIONAL.md`, verificado). El gate explícito:

```
GATE-0 (entrada a Historical Backtesting):
    feature_snapshots.count() >= N_min_por_deporte
    AND
    event_results.count() >= N_min_por_deporte
    AND
    DECISIÓN PENDIENTE D-1 resuelta (LaunchAgent reactivado y corriendo
    el tiempo suficiente para acumular ese volumen)
```

`N_min_por_deporte` no se fija en este documento con un número inventado
— debe derivarse del mismo criterio ya usado en Fase 2 para
`DEFAULT_MIN_TRAINING_SAMPLES`/`DEFAULT_MIN_TRAIN_SIZE_FOR_COMPARISON`
(`src/evaluation/reports.py`, 300 para MLB logreg) cuando se calibre con
evidencia real, no antes.

**Mientras GATE-0 no se cumpla, ninguna promoción a `promoted_at != None`
de un `PolicyManifest` es válida** (`CONTRACTS_FASE3.md` §15) — el
sistema puede construirse, probarse con fixtures, y quedar completamente
listo, pero no "graduarse" de la etapa [1].

---

## 3. Promotion Gates cuantificables (por etapa)

### 3.1 [1] → [2]: Offline testing → Historical backtesting

| Gate | Umbral |
|---|---|
| Cobertura de contract tests sobre los 16 contratos de `CONTRACTS_FASE3.md` | 100% (cada contrato tiene al menos un test de invariante) |
| Temporal leakage tests (`TEMPORAL_REPRODUCIBILITY_SPEC.md` §4) | 0 fallos |
| Policy validation (schema/rango/consistencia, `POLICY_ENGINE_SPEC.md` §5.1-3) | 0 fallos sobre el `PolicyManifest` propuesto |
| GATE-0 (§2) | Cumplido |

### 3.2 [2] → [3]: Historical backtesting → Shadow mode

| Gate | Umbral |
|---|---|
| `EvaluationRecord` de `model_performance` con `sample_size` suficiente | Definido cuando exista evidencia real, no antes (evitar Corrección: "no inventar costes/valores" aplicado también a umbrales de gate) |
| Regression test vs. manifiesto anterior (`POLICY_ENGINE_SPEC.md` §5.4) | Sin degradación no explicada en `brier_score`/`ece` |
| Historical comparison (§5.5) | Documentada y revisada por el usuario |

### 3.3 [3] → [4]: Shadow mode → Paper tracking

| Gate | Umbral |
|---|---|
| Duración mínima en shadow mode | A definir por calendario real de eventos del deporte (MLB: temporada activa; Tenis: bloqueado hasta desbloquear SofaScore, ver `FASE2_CIERRE_FINAL.md` §5) |
| `operational_performance.pipeline_error_rate` (`EVALUATION_LEARNING_SPEC.md` §1) | Sin fallos no controlados durante la ventana de shadow |
| Ninguna `PolicyDecision` con `disposition=INVALID_ANALYSIS` por causa de un bug del propio motor (vs. datos genuinamente insuficientes) | 0 |

### 3.4 [4] → [5]: Paper tracking → Manual decision support

| Gate | Umbral |
|---|---|
| `financial_performance` con registro manual suficiente para intervalos de confianza no triviales | A definir con evidencia real |
| Revisión humana explícita del usuario | Obligatoria — este es el único gate que nunca se automatiza, por diseño |

---

## 4. Shadow Mode — mecánica

Shadow mode ejecuta el Policy Engine completo (`SignalInputs` →
`PolicyDecision`) sobre oportunidades reales, en tiempo real o casi-real,
**sin exponer la decisión a ningún flujo de acción** — se persiste como
`OpportunityEvaluation` igual que cualquier otra, marcada con el
`policy_version` en shadow. No hay diferencia de código entre "shadow" y
"activo": la diferencia es exclusivamente que el `PolicyManifest` en
shadow no tiene `promoted_at` — mismo principio de "un núcleo, config
distinta" ya establecido en `POLICY_ENGINE_SPEC.md` §1.

## 5. Paper tracking — mecánica

Idéntico a shadow mode, más un registro manual explícito por parte del
usuario de "qué hubiera hecho" — nunca generado ni simulado por el
sistema. Es la única forma en que `roi_realizado`
(`EVALUATION_LEARNING_SPEC.md` §1) puede existir sin ejecución
automática.
