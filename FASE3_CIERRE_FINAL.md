# Informe Final de Cierre — Fase 3

**Fase 3 queda declarada oficialmente cerrada (2026-08-01).** Todo el
alcance clasificado como REQUIRED FOR PHASE 3 (`IMPLEMENTATION_ROADMAP_FASE3.md`)
está implementado, testeado (927 tests, 0 regresiones) y committeado. Las
3 decisiones pendientes identificadas en la auditoría original
(`FASE3_AUDIT_REPORT.md` §13) están cerradas: D-1 y D-2 resueltas, D-3
reencuadrada y documentada como dependencia externa verificable. Ver
`CONTINUITY.md` §0.2–§0.19 para el registro completo, paso a paso, de
todo el proceso.

## 1. Qué se construyó (REQUIRED FOR PHASE 3, 100% implementado)

| Componente | Estado |
|---|---|
| 17 contratos (`CONTRACTS_FASE3.md`), pydantic `StrictModel` | Cerrado, con round-trip de serialización probado |
| Policy Engine (Eligibility → Hard Block → Hard Hold → Soft Score → `decision.py`) | Cerrado, catálogo de 7 BLOCK + 6 HOLD, no-compensación probada |
| `PolicyManifest` + validación (schema/rango/consistencia) | Cerrado |
| Calibration Layer (`calibration_layer.py`) | Cerrado — **sin calibrador entrenado** (ver §3) |
| Payoff Model (`payoff_model.py`) | Cerrado — **`net_ev_status` siempre `UNKNOWN`** (ver §3, D-3) |
| Opportunity Lifecycle + `OpportunityRepository` (append-only) | Cerrado |
| Evidence Engine + Explainability Engine | Cerrado |
| `AnalysisHealth` | Cerrado |
| Extensión de `backtesting/metrics.py` (ece/clv/roi/drawdown/profit_factor) | Cerrado, funciones puras |
| Evaluation & Learning Framework (`EvaluationRecord`, 5 dimensiones) | Cerrado como **andamiaje** — probado con fixtures sintéticos, no con evaluaciones reales (ver §3) |
| Política de Retención de Datos + mecanismo de mantenimiento | Cerrado, ambos LaunchAgents activos |

Decisiones de alcance respetadas sin excepción: cero entrenamiento de
modelos, cero cambios de comportamiento en `src/` de Fase 1/2 salvo los
dos explícitamente autorizados (D-2: `DataQuality.side_selection_confidence`;
D-3: punto de enganche que siempre devuelve `None`), `v2.0-baseline`
intacto (`2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df`).

## 2. Qué está listo para producción hoy

- **El pipeline de decisión completo es ejecutable end-to-end** sobre
  datos reales de mercado: eligibilidad → hard rules → soft score →
  `PolicyDecision`, con evidencia y explicación adjuntas, persistido de
  forma append-only en `OpportunityRepository`.
- **La captura histórica real está activa de forma permanente** (D-1
  resuelto) — `event_snapshots`/`feature_snapshots` acumulan volumen
  real cada hora, con mantenimiento automatizado (rotación/backup) que
  no compromete la retención indefinida que exige la reproducibilidad.
- **El mapeo participante↔YES de Kalshi es real**, no un stub (D-2
  resuelto) — `unresolved_side_mapping` ya opera sobre una confianza
  medida, no sobre una constante.
- **Extensibilidad probada**: cualquier futuro dato real (calibrador
  entrenado, fees verificados) se integra en los puntos de enganche ya
  preparados (`_estimate_kalshi_taker_fee`, `CalibrationOutput`) sin
  requerir cambios de contrato.

## 3. Qué NO está listo para producción — depende de datos/verificación que aún no existen

Estos componentes están **implementados y probados estructuralmente**,
pero producen resultados deliberadamente conservadores (`None`/`UNKNOWN`)
hasta que exista evidencia real suficiente — esto es una decisión de
diseño explícita ("no fabricar"), no un defecto:

| Limitación actual | Depende de | Estado de la dependencia |
|---|---|---|
| Ningún calibrador de probabilidad entrenado (`CalibrationOutput.model_version=None` en la práctica) | Volumen real de histórico | **En progreso, orgánico** — D-1 resuelto, empezó a acumularse el 2026-08-01 |
| `net_ev_status` siempre `UNKNOWN`, nunca `COMPUTED` | Fórmula de fees de Kalshi verificada contra fuente primaria | **PENDIENTE — dependencia externa (D-3)**, ver §4 |
| Sin backtesting histórico real, sin Shadow Mode real, sin paper tracking real | Volumen real de histórico + calibrador entrenado | **En progreso, orgánico** (mismo bloqueo que arriba) |
| Heurísticas provisionales sin recalibrar (`HEURISTIC_V1`, umbrales de `PolicyManifest`) | Evidencia real suficiente | **En progreso, orgánico** |
| Sin lógica de clasificación ENTER/WATCH/PASS sobre `SignalInputs` | Los tres puntos anteriores | Bloqueado transitivamente |

## 4. Dependencia externa pendiente: D-3 (verificación primaria de Kalshi)

**Única decisión que sigue genuinamente abierta.** No es una decisión de
arquitectura del proyecto — es la verificación de un hecho externo:

- Kalshi cobra vía una fórmula pública basada en precio
  (`kalshi.com/docs/kalshi-fee-schedule.pdf`), no un campo por mercado.
- 3 intentos de `WebFetch` a la fuente primaria devolvieron HTTP 429
  (límite de tasa del servidor, no un bloqueo permanente).
- Dos fuentes secundarias convergen en `taker_fee ≈ 0.07 × precio ×
  (1-precio)` por contrato, pero difieren en el redondeo exacto —
  insuficiente para codificar con la certeza que el proyecto exige
  (Corrección C, "no inventar costes").
- El punto de enganche (`_estimate_kalshi_taker_fee`, `src/payoff/payoff_model.py`)
  está preparado: cuando la fórmula se verifique, ese es el único lugar
  que necesita cambiar.

**Acción recomendada**: reintentar `WebFetch` periódicamente, o que el
usuario proporcione el contenido verificado del PDF oficial. No requiere
ningún trabajo de diseño adicional una vez verificado.

## 5. Plan recomendado para la siguiente fase

Los siguientes puntos son una **propuesta de alto nivel**, no un plan de
ejecución aprobado — como en el inicio de Fase 3, requeriría su propia
auditoría contractual/arquitectónica antes de convertirse en un
`FASE4_EXECUTION_PLAN.md`. Orden de dependencia real (`IMPLEMENTATION_ROADMAP_FASE3.md`
"RECOMMENDED LATER", sin cambios):

1. **Dejar acumular histórico real** (ya en marcha, sin trabajo de código) hasta tener volumen suficiente para entrenar/calibrar con significancia estadística.
2. **Entrenar un calibrador real** (Platt/isotónica) sobre ese histórico, reemplazando el `CalibrationOutput` sin entrenar de hoy.
3. **Retirar D-3**: reintentar la verificación primaria de Kalshi y, si se confirma, implementar la fórmula en el punto de enganche ya preparado — habilita `net_ev_status=COMPUTED`.
4. **Backtesting histórico real + Shadow Mode real + paper tracking real**, una vez (2) y (3) den señales confiables — la especificación ya existe (`SHADOW_MODE_AND_PROMOTION_GATES.md`), solo falta implementarla contra datos reales.
5. **Recalibrar heurísticas provisionales** (`HEURISTIC_V1`, umbrales de `PolicyManifest`) con la evidencia real acumulada.
6. **Solo entonces**: diseñar la lógica de clasificación ENTER/WATCH/PASS sobre `SignalInputs` — el contrato ya está listo (Paso 12, Fase 2), pero implementarla antes de (1)-(5) sería decidir umbrales sin evidencia.

**Explícitamente fuera de alcance, sin cambios**: cualquier forma de
ejecución automática o `src/risk/` (Principio 21, restricción dura, no
"más adelante" — sigue fuera de la trayectoria del proyecto salvo
decisión explícita nueva del usuario).

## 6. Estado del repositorio al cierre

- **927 tests pasando, 0 fallando.**
- **`v2.0-baseline`** (Fase 2) intacto: `2d7e29329fef6c7bfe6ed2e6e31dcc9f26ca30df`.
- **Último commit de Fase 3**: `bb5c12a` (rama `phase-2-dev`).
- **`data/models/`**: solo `.gitkeep`, sin contaminación.
- **Ambos LaunchAgents activos de forma permanente**: captura histórica horaria + mantenimiento diario.
- Rama `main` permanece en el baseline de Fase 1 (`c5eb9e7`), sin cambios — decisión de ramificación de Fase 2 sin modificar.
