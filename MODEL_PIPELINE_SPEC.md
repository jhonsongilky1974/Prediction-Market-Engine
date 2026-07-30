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
| **Market Adapter** | Traduce el contrato de mercado concreto (Kalshi binario YES/NO) a la forma que el modelo espera | No existe — es exactamente el hueco de la Ambigüedad #2 (mapeo participante↔YES) | Diseño de interfaz aquí (§2); implementación real depende de DECISIÓN PENDIENTE D-2 |
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

## 2. Market Adapter — el eslabón que hoy no existe

Es la pieza que resolvería la Ambigüedad #2 de forma definitiva
(DECISIÓN PENDIENTE D-2, `PLAN_MASTER_FASE3.md` §8). Su contrato
propuesto (para cuando D-2 se resuelva, **no implementado en Fase 3**):

```python
class MarketAdapter(Protocol):
    def native_label_to_side(self, market_id: str, native_probability_target: str) -> Side:
        """Traduce la etiqueta nativa del modelo (p.ej. 'participant_a gana')
        al Side (YES/NO) del contrato Kalshi real para ese market_id."""
```

Mientras D-2 no se resuelva, `src/calibration/calibration_layer.py`
**no invoca ningún `MarketAdapter`** — `p_model_raw` sigue
interpretándose, exactamente como en Fase 2, como "probabilidad de la
etiqueta nativa del modelo", y el Hard Hold `unresolved_side_mapping`
(`POLICY_ENGINE_SPEC.md` §2.2) queda activo permanentemente hasta
entonces. Esto es lo que impide que la ausencia del Market Adapter real
se oculte silenciosamente detrás de una interfaz que aparenta estar
completa.

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
