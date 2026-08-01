# Model Pipeline — Especificación (Fase 3)

Arquitectura jerárquica de `P_model` (Principio 11). Ver
[`CONTRACTS_FASE3.md`](CONTRACTS_FASE3.md) §1-2 para los contratos de
salida.

---

## 1. Las 5 capas

```
Sport Adapter  ->  Market Adapter  ->  Feature Builder  ->  Probabilistic Model  ->  Calibration Layer
```

| Capa | Responsabilidad | Estado en Fase 2 | Acción en Fase 3 |
|---|---|---|---|
| **Sport Adapter** | Traduce `NormalizedRecord` (agnóstico de deporte) a la vista específica de deporte | Implícito: `mlb_features.py`/`tennis_features.py` ya separan por deporte, pero no hay una interfaz `SportAdapter` formal | Formalizar como interfaz explícita (`Protocol`) sin mover lógica de `mlb_features.py`/`tennis_features.py` — envoltorio, no reescritura |
| **Market Adapter** | Traduce el contrato de mercado concreto (Kalshi binario YES/NO) a la forma que el modelo espera | **RESUELTO post-cierre del roadmap** (ver §2 y `CONTINUITY.md` §0.17) — `src/matching/market_matcher.py::_select_market` (Fase 1) ya selecciona el mercado cuyo YES corresponde a `participant_a`; su confianza se expone en `DataQuality.side_selection_confidence` | Ya cubierto -- ver §2. `unresolved_side_mapping` (Hard Hold) consume esa confianza en vez de bloquear incondicionalmente |
| **Feature Builder** | Calcula el vector de features desde `ModelInputs`/`TennisVariables` | `src/features/mlb_features.py`, `tennis_features.py`, `registry.py` (Fase 2) | REUTILIZAR sin cambios |
| **Probabilistic Model** | Produce `PModelOutput` (`p_model_yes`, `model_status`) | `src/models/mlb_baseline.py`, `mlb_elo.py`, `tennis_baseline.py` (Fase 2) | REUTILIZAR sin cambios |
| **Calibration Layer** | Produce `CalibrationOutput` (`p_model_raw` → `p_model_calibrated`) | No existe | CREAR (`src/calibration/`) |

**Principio de no intrusión:** las 3 primeras capas ya existen en Fase 2
con nombres distintos y sin una interfaz formal unificada. Fase 3 no
reescribe `mlb_features.py`/`tennis_baseline.py` para que "se vean" como
Sport Adapter/Feature Builder/Probabilistic Model — define las
interfaces (`Protocol` de `typing`, sin herencia obligatoria, cero
dependencia nueva) que ya satisfacen, y las documenta como tales. Esto es
consistente con Principio 16 (extensibilidad por interfaces) sin tocar
código probado.

---

## 2. Market Adapter — RESUELTO (D-2), no vía la interfaz `Protocol` esbozada originalmente

Este documento proponía originalmente un `MarketAdapter.native_label_to_side()`
que tradujera explícitamente, en tiempo de inferencia, la etiqueta
nativa del modelo al `Side` real de un `market_id` concreto. Al resolver
D-2 (ver `CONTINUITY.md` §0.17) se encontró que el problema ya estaba
resuelto por otro camino, existente desde Fase 1: `_select_market`
(`src/matching/market_matcher.py`) no traduce una etiqueta después del
hecho -- **selecciona, en el momento del matching, el mercado de Kalshi
cuyo YES ya corresponde a `participant_a`** (comparando `participant_a`
contra el `yes_sub_title` de cada mercado candidato del evento). Por
construcción, para todo registro con un `market_id` adjunto,
`Side.YES` del contrato seleccionado coincide con la etiqueta nativa del
modelo (`P(participant_a gana)`) -- la única pieza que faltaba era la
CONFIANZA de esa selección, ahora expuesta en
`DataQuality.side_selection_confidence` (mismo `best_score` que Fase 1
ya calculaba y descartaba).

No se implementó el `Protocol` `MarketAdapter` tal como se había
esbozado -- hacerlo habría sido redundante con un mecanismo que ya
resuelve el mismo problema. `src/calibration/calibration_layer.py`
sigue sin cambios (Paso 3.1, no modificado por esta resolución):
`p_model_raw` sigue siendo la probabilidad de la etiqueta nativa, que
ahora sabemos (con una confianza medible) que coincide con el YES real
del contrato seleccionado. El Hard Hold `unresolved_side_mapping`
(`POLICY_ENGINE_SPEC.md` §2.2) ya no bloquea de forma incondicional --
dispara solo cuando esa confianza es baja o ausente para un registro
concreto.

---

## 3. Calibration Layer

`src/calibration/calibration_layer.py` (nuevo):

```python
def calibrate(
    model_output: PModelOutput,
    calibrator: Optional[Calibrator],   # None = sin calibración entrenada todavía
) -> CalibrationOutput:
    ...
```

- Si `calibrator is None` o `model_output.p_model_yes is None`:
  `p_model_calibrated=None`, `calibration_version=None` — estado válido
  y esperado (mismo principio que `ModelStatus.MODEL_NOT_TRAINED` en
  Fase 2: ausencia de calibración no es un error, es un estado honesto).
- Entrenar un `Calibrator` real (Platt scaling / isotonic regression)
  requiere pares `(p_model_raw, resultado_real)` — **depende
  directamente de DECISIÓN PENDIENTE D-1** (histórico real). Sin
  histórico, `calibration_layer.py` se construye y se prueba con
  fixtures sintéticos (contract tests), pero no se entrena ningún
  calibrador real en el alcance de Fase 3 — ver
  `PLAN_MASTER_FASE3.md` §0.

---

## 4. Conservación de campos (Principio 12)

Ver `CONTRACTS_FASE3.md` §2 — `p_model_raw`, `p_model_calibrated`,
`model_version`, `calibration_version` son campos de `CalibrationOutput`,
no de `PModelOutput` (que no se modifica). `feature_set_version`
(`PModelOutput`, Fase 2) se referencia como `feature_schema_version` en
`OpportunityEvaluation` — mismo valor, alias documentado, no un campo
paralelo que pueda desincronizarse.

---

## 5. Multi-deporte, multi-modelo (Principio 16)

`src/models/registry.py` (Fase 2) hoy solo indexa artefactos MLB
(`glob("mlb_baseline_*.metadata.json")` hardcodeado). La extensión
aditiva propuesta (`PLAN_MASTER_FASE3.md` §3.2):

```python
def load_latest_artifact(sport: Sport, models_dir: Path = DATA_MODELS_DIR) -> Optional[Tuple[Any, TrainedArtifactMetadata]]:
    """Generaliza load_latest_mlb_artifact a cualquier deporte, mismo
    contrato de retorno. load_latest_mlb_artifact permanece intacta y
    en uso -- esta función es aditiva, no un reemplazo."""
```

No se migra `mlb_baseline.py`/`tennis_baseline.py` para usar la función
genérica en Fase 3 (fuera de alcance, `PLAN_MASTER_FASE3.md` §3.5) — la
función nueva se añade y se prueba de forma aislada, lista para que un
futuro modelo de Fase 3+ la use desde el principio.
