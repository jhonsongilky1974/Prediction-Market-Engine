# Evidence Engine & Explainability Engine — Especificación (Fase 3)

Principios 6, 13, 14. Dos módulos separados a propósito
(`src/evidence/`, `src/explainability/`) — la separación es el
requisito, no un detalle de implementación: el Evidence Engine no sabe
qué es una decisión ni un umbral; el Explainability Engine no vuelve a
derivar hechos, solo los cita.

---

## 1. Evidence Engine (Principio 13)

`src/evidence/evidence_engine.py` produce `EvidenceItem[]`
(`CONTRACTS_FASE3.md` §6) a partir de `NormalizedRecord` +
`CalibrationOutput` + `ConfidenceProfile`, **sin conocer** `PolicyDecision`
ni ningún umbral de política. Es una función pura:

```python
def collect_evidence(
    record: NormalizedRecord,
    calibration_output: CalibrationOutput,
    confidence_profile: ConfidenceProfile,
) -> List[EvidenceItem]:
```

### 1.1 Regla de generación (no fabricar)

Cada `EvidenceItem` se genera por una plantilla condicionada a que el
campo fuente **no sea `None`** — mismo principio no negociable de toda
Fase 1/2 ("missing nunca se convierte en un valor fabricado"), aplicado
ahora a texto/hechos en vez de a números:

| Condición | `EvidenceItem.fact` (plantilla) | `direction` |
|---|---|---|
| `model_inputs.lineup_or_pitcher is not None` (MLB) | "Pitcher probable confirmado" | FOR |
| `model_inputs.lineup_or_pitcher is None` (MLB) | **No se genera ningún EvidenceItem** — ausencia de dato no es evidencia AGAINST, es ausencia | — |
| `data_quality.match_confidence` bajo pero por encima del mínimo de matching | "Confianza de emparejamiento marginal ({valor})" | AGAINST |
| `ConfidenceProfile.model_reliability is not None and > umbral` | "Modelo con historial de performance evaluado ({n} muestras)" | FOR |
| `bookmaker_consensus.consensus_probability_no_vig is not None` y diverge de `p_model_calibrated` por más de un umbral | "Divergencia significativa entre modelo y consenso de mercado" | AGAINST |

Ausencia de dato ⇒ ausencia de `EvidenceItem`, nunca un `EvidenceItem`
con `direction=AGAINST` fabricado para "compensar". Esto evita el
sesgo sutil de que la falta de evidencia positiva se transforme en
evidencia negativa artificial.

### 1.2 Lo que el Evidence Engine explícitamente no hace

- No calcula scores.
- No decide ENTER/WATCH/PASS.
- No conoce `PolicyManifest`.
- No importa nada de `src/policy/` ni de `src/explainability/` (regla de
  dependencia de `ARCHITECTURE_FASE3.md` §4).

---

## 2. Explainability Engine (Principio 14)

`src/explainability/explainability_engine.py` consume
`PolicyDecision` + `EvidenceItem[]` (ya calculados, nunca recalculados)
y produce una explicación auditable, estructurada, para humanos:

```python
class ExplanationOutput(StrictModel):
    opportunity_id: str
    evaluation_id: str
    headline: str                      # "ENTER — edge 4.2%, confianza 78/100"
    reasons_explained: List[str]       # una entrada legible por SignalReason
    evidence_for: List[str]            # subset de EvidenceItem con direction=FOR, ya en texto
    evidence_against: List[str]
    disclaimers: List[str]             # p.ej. "calibration_version=None: probabilidad sin calibrar"
    generated_at: datetime
```

### 2.1 Regla de separación (Principio 6, literal)

- El Explainability Engine **no vuelve a tocar** `NormalizedRecord`,
  `ConfidenceProfile` ni ningún dato crudo — todo lo que explica ya pasó
  por `PolicyDecision.reasons` (`SignalReason`, estructurado) y por
  `EvidenceItem` (ya generado por el Evidence Engine). Si un dato
  relevante no aparece en ninguno de los dos, el Explainability Engine no
  puede mencionarlo — fuerza a que toda razón mostrada al humano tenga un
  origen trazable y ya auditado en un contrato anterior, nunca prosa
  generada libremente sobre datos crudos.
- `disclaimers` es obligatorio y no vacío cuando `calibration_version is None`
  o `net_ev_status == UNKNOWN` — el sistema nunca presenta una probabilidad
  sin calibrar o un EV desconocido como si fueran definitivos.

### 2.2 Lo que el Explainability Engine explícitamente no hace

- No decide nada — es puramente una capa de traducción
  `PolicyDecision + EvidenceItem[] -> texto estructurado`.
- No es la fuente de verdad de auditoría — la fuente de verdad es la
  `OpportunityEvaluation` persistida completa (`CONTRACTS_FASE3.md` §13);
  `ExplanationOutput` es una vista derivada, regenerable en cualquier
  momento a partir de esa fila, nunca almacenada como única copia.

---

## 3. Por qué la separación importa (justificación arquitectónica)

Si un solo módulo generara hechos y explicación a la vez, cualquier sesgo
de redacción (elegir qué mencionar) se mezclaría con el proceso de
recolectar evidencia, dificultando auditar "¿qué sabía el sistema?" por
separado de "¿cómo lo explicó?". Con la separación:

- El Evidence Engine se puede probar con property-based tests puros
  (¿genera evidencia solo cuando el campo fuente no es `None`?) sin tocar
  texto de UI.
- El Explainability Engine se puede rediseñar completamente (mejor
  redacción, otro idioma, otro formato) sin re-auditar de dónde salió
  cada hecho.
