# Diseño: calibración real del modelo de tenis (Platt scaling)

**Estado: diseño formal, implementación autorizada de antemano por el
usuario en el mismo mensaje** ("primero realiza un diseño formal y
recomienda el método adecuado... Implementa, prueba, audita y presenta
evidencia verificable"). A diferencia de `ORCHESTRATOR_SPEC.md` (Paso
4.1), este documento no espera una ronda de aprobación separada antes de
codificar -- pero sigue el mismo protocolo de investigación real primero,
hallazgos explícitos, cero valores fabricados. Cualquier punto que
requiera inventar un umbral sin evidencia se señala explícitamente en vez
de decidirse en silencio.

Contexto: Paso 4.3 (`MODEL_TRAINING_SPEC.md`, commits `a936048`/`23b22ff`/
`e7f74d5`) entrenó el primer y único modelo base real del proyecto
(`tennis_baseline_logreg_v1_20260801T184245Z`) y dejó la calibración real
explícitamente diferida ("no split methodology or minimum sample size
decided yet"). D-3 (fees de Kalshi) y el entrenamiento de MLB quedan
fuera de este documento -- ambos bloqueados por factores externos (rate
limit de Kalshi; volumen de datos insuficiente), verificados de nuevo hoy
mismo, tratados como deuda técnica documentada, sin fecha.

---

## 0. Investigación previa (contra código y datos reales)

### 0.1 Estado del `Calibrator` Protocol

`src/calibration/calibration_layer.py` define `Calibrator` como
`typing.Protocol` (`calibration_version: str`, `calibration_method: str`,
`calibrate(p_raw: float) -> float`), sin ninguna implementación
concreta salvo `_FakeCalibrator` en `tests/unit/test_calibration_layer.py`
(doble de test explícito, no real). `calibrate()` ya sabe aplicar
cualquier objeto que satisfaga el Protocol -- **no requiere ningún
cambio** para consumir un calibrador real.

`CONTRACTS_FASE3.md` §2 ya declara los valores esperados de
`calibration_method` por adelantado: `"PLATT_V1"`, `"ISOTONIC_V1"` --
los nombres de este documento no son una invención, ya estaban previstos
en el contrato aprobado en Fase 3.

### 0.2 Hallazgo real: `CalibrationOutput` se calcula pero nunca llega a influir ninguna decisión

Verificado leyendo `src/orchestration/decision_pipeline.py` y
`src/orchestration/signal_builder.py` de punta a punta:

- `decision_pipeline._build_record_context` (línea 80) llama
  `calibrate(model_output, calibrator=None, now=now)` -- **hardcodeado**,
  ningún llamador real puede pasar un calibrador hoy (ni siquiera existe
  un mecanismo para hacerlo).
- `build_signal_inputs` (el compositor de `SignalInputs`, el input
  directo del Policy Engine) recibe `model_output: PModelOutput` y usa
  `model_output.p_model_yes` (el crudo) para `signal_inputs.p_model`,
  `compute_edge_yes/no` y `compute_ev_yes/no_bruto`. **Nunca recibe ni
  consulta `CalibrationOutput`.**
- `evidence_engine.py` (línea 128) sí lee `calibration_output.p_model_calibrated`
  correctamente (para la evidencia de divergencia con el consenso de
  mercado) -- confirma que el resto del pipeline (`policy/decision.py`,
  `payoff_model.py`, `analysis_health.py`) no toca `p_model` en absoluto
  (grep confirmado, cero resultados), así que el único punto de conexión
  faltante es `build_signal_inputs`.

`CONTRACTS_FASE3.md` §2, invariante explícito: *"Mientras
`calibration_version is None`, todo consumidor aguas abajo (Policy
Engine) debe usar `p_model_raw` explícitamente... nunca sustituir
`p_model_calibrated` por `p_model_raw` silenciosamente sin dejar
rastro."* La lectura inversa, ya prevista por el propio contrato: **en
cuanto exista un `calibration_version` real, el consumidor debe empezar a
usar `p_model_calibrated`.** Hoy no lo hace -- es un hueco real, no una
decisión de diseño deliberada, del mismo tipo que los ya corregidos en
Paso 4.1 (`model_version` no-opcional) y Paso 4.3 (fuga de datos). Se
corrige en este paso (§4).

### 0.3 Único candidato disponible: tenis

Solo existe un modelo base entrenado (`tennis_baseline_logreg_v1_20260801T184245Z`,
verificado en `data/models/`). MLB no tiene ningún modelo (D-3/volumen,
fuera de alcance). Este diseño y su implementación son exclusivamente
para tenis -- ningún cambio a `mlb_baseline.py` salvo la consistencia
señalada en §4.3 (aditiva, sin entrenar nada de MLB).

### 0.4 Datos disponibles para ajustar el calibrador, verificado en vivo hoy

```
build_tennis_training_dataset(HistoryRepository()) -> dataset.size = 600
split_dataset_temporally(dataset) -> train=480 muestras/96 eventos, validation=120 muestras/24 eventos
```

Coincide **exactamente** con `n_train_samples=480`/`n_validation_samples=120`
del `metadata.json` del modelo ya entrenado -- misma reconstrucción,
mismo resultado. Esto es evidencia (no una garantía absoluta, ver
limitación abajo) de que recomputar el dataset/split HOY reproduce la
misma partición usada para entrenar el pipeline ya congelado: **la
validación (120 muestras/24 eventos) es segura para ajustar un
calibrador sin fuga respecto al entrenamiento del modelo base.**

**Limitación real, señalada explícitamente**: `TennisTrainedArtifact` no
persiste la lista exacta de `event_id` usados en train/validation, solo
conteos. Si `data/engine.db` creciera de forma que el punto de corte
cronológico se desplazara, recomputar el split más adelante podría dejar
de coincidir con la partición original usada para entrenar el modelo
congelado, sin ninguna señal de alarma. Verificado hoy que los conteos
coinciden exactamente (evidencia fuerte, no prueba matemática). Se
corrige la causa raíz de forma aditiva en §4.3 para toda partición
FUTURA (no puede corregir retroactivamente el artefacto ya entrenado,
que no tiene el campo).

---

## 1. Método recomendado: **Platt scaling**, no isotonic regression

Justificación, con la muestra real disponible (120 pares
`(p_raw, resultado)`, 24 eventos distintos):

- Isotonic regression es no paramétrica (ajusta una función escalón
  monótona arbitraria) -- literatura estándar de calibración
  (Niculescu-Mizil & Caruana, 2005, "Predicting Good Probabilities With
  Supervised Learning") documenta que necesita un conjunto de calibración
  grande (típicamente >1000 muestras) para no sobreajustar; con pocas
  muestras produce una función escalón inestable, memorizando ruido en
  vez de una tendencia real.
- Platt scaling ajusta solo 2 parámetros (una regresión logística 1-D
  sobre `p_raw`) -- funciona razonablemente bien incluso con conjuntos de
  calibración pequeños (decenas a cientos de muestras), exactamente el
  régimen en el que está tenis hoy.
- Mismo estilo de heurística que ya usa este proyecto para decidir
  umbrales sin inventar un número (`DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30`,
  derivado de "10-20 observaciones por dimensión" aplicado a 2
  dimensiones) -- aquí la dimensión relevante es 1 (el propio `p_raw`),
  y 120 muestras excede holgadamente cualquier lectura razonable de esa
  regla para un modelo de 2 parámetros.

**Decisión: `PLATT_V1` hoy. `ISOTONIC_V1` queda explícitamente fuera de
alcance** hasta que algún modelo (tenis en el futuro, con más histórico,
o MLB si algún día se entrena) tenga un conjunto de calibración
sustancialmente mayor -- no se fija ningún umbral numérico para ese
futuro punto de decisión, evitando inventar un número sin evidencia
todavía.

---

## 2. Estrategia de ajuste y evaluación

**Ajuste real usa el propio `validation` split ya usado para evaluar el
modelo base** (120 muestras/24 eventos, §0.4) -- es la única porción de
datos verificada como no vista por el pipeline ya entrenado. No se separa
un tercer split (`train`/`calibración-fit`/`calibración-eval`): con solo
120 eventos etiquetados en total, un tercer split dejaría cada porción
con ~10-15 eventos, demasiado pequeño para que un ECE calculado sobre él
signifique algo (varianza enorme por muy pocos ejemplos por bucket) --
inventar esa fracción sin justificación sería exactamente el tipo de
número fabricado que este proyecto prohíbe.

**Evaluación honesta sin encoger más los datos: validación cruzada
agrupada por evento (`GroupKFold`, `n_splits=5`, grupos=`event_id`)
sobre la misma validación de 120/24**, técnica estándar (es literalmente
lo que hace `sklearn.calibration.CalibratedClassifierCV` internamente) --
para cada fold, se ajusta un Platt sobre los otros 4 folds y se predice
sobre el fold retenido (out-of-fold, "OOF"); las 120 predicciones OOF
resultantes nunca vieron su propio dato durante el ajuste, dando una
estimación honesta de si calibrar realmente ayuda. `n_splits=5` es el
valor por defecto estándar de la librería (`sklearn` usa `cv=5` por
defecto en sus propias funciones de validación cruzada) -- no un número
elegido a medida para este caso.

**El calibrador FINAL que se persiste y se despliega se ajusta sobre las
120 muestras completas** (no sobre un fold) -- usa toda la evidencia
disponible; el paso de validación cruzada existe solo para producir la
métrica honesta de "¿ayuda calibrar?", no para seleccionar los datos del
artefacto final.

**Reporte, ambos calculados sobre las mismas 120 muestras (comparación
directa, mismo denominador)**:
- `raw_ece_oof`/`raw_brier_oof`: ECE/Brier de `p_raw` (el modelo base sin
  calibrar) sobre la validación completa -- ya calculado y persistido en
  el artefacto del modelo base (`ece=0.068`, `brier_score=0.103`), se
  reutiliza literalmente, no se recalcula.
- `calibrated_ece_oof`/`calibrated_brier_oof`: ECE/Brier de las
  predicciones OOF calibradas (GroupKFold, arriba).

Si el resultado muestra que calibrar NO mejora (o empeora) el ECE/Brier
frente al crudo, se reporta honestamente en la auditoría final -- no se
oculta ni se fuerza el despliegue si la evidencia no lo respalda (ver
criterio de aceptación en §6).

---

## 3. `PlattCalibrator` -- implementación

Nuevo módulo `src/calibration/platt_calibrator.py`, agnóstico de
deporte (Platt scaling no depende de tenis específicamente, reutilizable
si algún día MLB u otro deporte califica):

```python
@dataclass
class PlattCalibrator:
    calibration_version: str
    calibration_method: str  # siempre "PLATT_V1"
    _model: Any  # sklearn.linear_model.LogisticRegression ya ajustado, 1 feature

    def calibrate(self, p_raw: float) -> float: ...


def fit_platt_calibrator(p_raw, y, calibration_version) -> PlattCalibrator: ...
```

Satisface el `Calibrator` Protocol existente sin ningún cambio a
`calibration_layer.py`. `LogisticRegression` sobre una sola feature
(`p_raw`) es la técnica clásica de Platt scaling, mismo patrón que usa
internamente `sklearn.calibration.CalibratedClassifierCV(method="sigmoid")`.

---

## 4. Persistencia y cableado (amendments aditivos, señalados explícitamente)

### 4.1 `TennisCalibratorArtifact` -- persistencia independiente, mismo patrón que `TennisTrainedArtifact`

Nuevo módulo `src/calibration/tennis_calibrator_training.py`. Campos:
`calibrator_version` (`tennis_calibrator_platt_v1_<timestamp>`),
`calibration_method="PLATT_V1"`, **`base_model_version`** (el
`model_version` exacto del modelo base contra el que se ajustó -- un
calibrador Platt ajustado sobre la curva de un modelo NUNCA debe
aplicarse a otro `model_version`, aunque sea la misma arquitectura;
emparejamiento obligatorio, verificado en tiempo de carga), `trained_at`,
`n_calibration_samples`/`n_calibration_events`, `cv_folds`,
`raw_ece_oof`/`raw_brier_oof`/`calibrated_ece_oof`/`calibrated_brier_oof`,
`file_path`, `artifact_sha256` (mismo técnica que Paso 4.3). Persistencia
`.joblib` + `.metadata.json` hermano, prefijo `tennis_calibrator_platt_v1_*`
-- convive sin colisión con `tennis_baseline_*` en el mismo
`DATA_MODELS_DIR`.

`load_latest_tennis_calibrator(base_model_version, models_dir)`: busca el
calibrador más reciente CUYO `base_model_version` coincida exactamente
con el modelo base actualmente cargado. Si no hay ninguno (o el único
existente es para una versión de modelo distinta, p.ej. tras un
reentrenamiento futuro del modelo base), devuelve `None` -- nunca aplica
un calibrador desalineado, nunca lanza.

### 4.2 `build_signal_inputs` -- usar la probabilidad calibrada cuando exista (corrige el hueco de §0.2)

Firma extendida: recibe además `calibration_output: CalibrationOutput`.
Si `calibration_output.p_model_calibrated is not None`, se construye una
copia de `model_output` (`dataclasses.replace`, `PModelOutput` no es
frozen) con `p_model_yes` reemplazado por el valor calibrado -- mismo
`model_version`/`model_status`, ningún otro campo cambia -- y esa copia
(no el original) se usa para `signal_inputs.p_model`,
`compute_edge_yes/no`, `compute_ev_yes/no_bruto`/`neto`. Si
`p_model_calibrated is None` (caso de hoy para MLB, y de tenis antes de
este paso), comportamiento idéntico al actual -- cero regresión.

### 4.3 `SportAdapter` -- nuevo campo opcional `load_calibrator_fn`

`src/orchestration/sport_adapter.py`: campo aditivo
`load_calibrator_fn: Optional[Callable[[str], Optional[Calibrator]]] = None`
(recibe el `model_version` del artefacto base ya cargado, para el
emparejamiento de §4.1). `decision_pipeline._build_record_context` lo
invoca (si existe) con `model_output.model_version` y pasa el resultado a
`calibrate()` en vez de `calibrator=None`. `scripts/run_e2e.py`:
`SPORT_ADAPTERS[Sport.TENNIS]` gana `load_latest_tennis_calibrator`;
`SPORT_ADAPTERS[Sport.MLB]` no cambia (sin calibrador, campo por defecto
`None`).

### 4.4 Consistencia con `mlb_baseline.py` -- `validation_event_ids` persistido hacia adelante (sin reentrenar MLB)

Corrige la causa raíz señalada en §0.4: `TennisTrainedArtifact`/
`MlbTrainedArtifact` ganan un campo aditivo `validation_event_ids:
List[str] = field(default_factory=list)`, poblado por
`train_tennis_baseline_model`/`train_mlb_baseline_model` con los
`event_id` reales del split de validación, serializado en el
`metadata.json`. El artefacto de tenis YA entrenado hoy no lo tiene
(no se reentrena solo por esto) -- `load_latest_tennis_artifact` usa
`.get("validation_event_ids", [])` y el script de calibración degrada
con una advertencia explícita si viene vacío (cae de vuelta a la
verificación empírica de §0.4, nunca falla en silencio). Toda
**futura** re-ejecución de entrenamiento (tenis o MLB) queda protegida
sin ambigüedad. Se aplica también a `mlb_baseline.py` por consistencia
(mismo código duplicado a propósito, mismo motivo que la corrección de
fuga de datos del Paso 4.3) -- **no se entrena ningún modelo de MLB en
este paso.**

---

## 5. `scripts/train_tennis_calibrator.py`

Mismo patrón que `scripts/train_tennis_model.py`: invocación manual,
sin lock (solo lee `HistoryRepository` y el `data/models/` existente,
escribe un artefacto nuevo con nombre único). Carga el modelo base más
reciente (`load_latest_tennis_artifact`); si no hay ninguno, termina
exit 0 informando honestamente (nada que calibrar). Reconstruye el
dataset/split, verifica el emparejamiento de conteos contra el
`metadata.json` del modelo base (§0.4) y aborta con exit 1 (no fabrica
nada) si no coinciden. Ajusta y persiste el `TennisCalibratorArtifact`,
imprime el reporte completo (crudo vs. calibrado, OOF).

---

## 6. Criterio de aceptación para desplegar

El calibrador se persiste siempre que el ajuste sea numéricamente válido
(no depende de que "mejore" para existir como evidencia) -- pero **el
cableado de producción (§4.3, que hace que el pipeline real empiece a
usarlo) solo se activa si `calibrated_ece_oof <= raw_ece_oof` o la
diferencia es marginal** (evidencia de que calibrar no empeora el
modelo). Si el resultado real muestra que calibrar empeora el ECE OOF de
forma clara, se reporta en la auditoría final como hallazgo y se detiene
para pedir instrucción explícita en vez de desplegar algo que la propia
evidencia contradice -- no es una decisión que deba tomarse en silencio.

---

## 7. Pruebas

- `tests/unit/test_platt_calibrator.py`: ajuste sobre datos sintéticos
  con relación conocida (recupera una calibración razonable), contrato
  `Calibrator` Protocol satisfecho, `calibrate()` siempre en `[0,1]`.
- `tests/unit/test_tennis_calibrator_training.py`: dataset sintético
  pequeño vía `HistoryRepository(tmp_path)`, verifica
  `base_model_version` persistido, emparejamiento correcto/incorrecto en
  `load_latest_tennis_calibrator`, `INSUFFICIENT_HISTORY` honesto si no
  hay modelo base o el split de validación no alcanza `cv_folds` eventos.
- `tests/unit/test_signal_builder.py`: nuevos casos -- `p_model_calibrated`
  presente sustituye al crudo en `p_model`/`edge`/`ev_bruto`;
  `p_model_calibrated=None` dejan el comportamiento actual intacto
  (regresión cero, tests existentes no se modifican).
- `tests/unit/test_decision_pipeline.py`: `SportAdapter` con
  `load_calibrator_fn` invocado y aplicado; sin él, comportamiento
  idéntico al actual.
- Un test de integración real-API adicional (mismo patrón que
  `tests/integration/test_e2e_real.py`, `tmp_path`, nunca
  `data/engine.db`) si el tiempo de ejecución existente lo permite.

## 8. Evidencia y consecuencia operacional

Igual que el entrenamiento del modelo base (Paso 4.3) y la carga de
LaunchAgents (Paso 4.0B): correr `scripts/train_tennis_calibrator.py`
contra `data/engine.db` de producción y luego cablear el resultado en el
orquestador tiene una consecuencia real inmediata -- la próxima corrida
horaria empezaría a usar `p_model_calibrated` en vez de `p_model_raw`
para tenis, cambiando `EDGE`/`EV`/decisiones reales en producción.
Requiere confirmación explícita separada antes de ejecutarse (Regla 6),
igual tratamiento que el entrenamiento del Paso 4.3.
