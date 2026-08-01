# Diseño del Paso 4.3 (PROPUESTO, NO APROBADO)

**Estado: diseño para aprobación. Cero código escrito.** Responde a la
petición del usuario: presentar el diseño completo del Paso 4.3 antes
de implementar. Sigue el mismo protocolo que `ORCHESTRATOR_SPEC.md`
(Paso 4.1): investigación del código real primero, hallazgos reportados
explícitamente, decisiones abiertas señaladas sin fabricar valores.

**Revisión 2 (2026-08-01, mismo día):** el usuario aprobó el diseño y
pidió una autoauditoría adicional antes de implementar, contra 4
requisitos explícitos (partición sin data leakage, artefacto versionado
con campos mínimos, estructura preparada para calibración futura,
métricas suficientes para comparar versiones). La autoauditoría
**encontró un bug real de fuga de datos entre entrenamiento y
validación**, verificado contra datos de producción, nunca detectado
porque ningún test existente lo podía revelar — ver §0.5. Se incorpora
la corrección al diseño antes de implementar, según lo pedido.

---

## 0. Hallazgo central — "entrenar un calibrador real" no es ejecutable todavía

`FASE4_EXECUTION_PLAN.md` nombra el Paso 4.3 como "entrenar calibrador
real", heredado del roadmap de cierre de Fase 3
(`FASE3_CIERRE_FINAL.md` §5, punto 2). Verificado contra el código real
antes de diseñar nada más: **este paso, tal como está nombrado, no se
puede ejecutar hoy**, por dos motivos independientes y acumulativos.
Se reporta esto primero, no se oculta detrás de un diseño que asumiera
que sí es posible.

### 0.1 No existe ninguna implementación real de `Calibrator`

`src/calibration/calibration_layer.py:40-48` define `Calibrator` como
un `typing.Protocol`:
```python
class Calibrator(Protocol):
    calibration_version: str
    calibration_method: str
    def calibrate(self, p_raw: float) -> float: ...
```
Ninguna clase concreta lo implementa en todo el repositorio salvo
`_FakeCalibrator` en `tests/unit/test_calibration_layer.py:32-41` — un
doble de test explícitamente documentado como "NO es un calibrador real
entrenado", una función lineal de juguete sin ajustar contra ningún
dato. `MODEL_PIPELINE_SPEC.md` §3 ya lo decía explícitamente: "Ningún
`Calibrator` real (Platt scaling / isotonic regression) se entrena...
depende de histórico real". El Protocol tampoco define ningún método
`fit()` — el ajuste/entrenamiento del calibrador queda deliberadamente
fuera de su alcance por diseño, es responsabilidad de quien lo
construya.

### 0.2 No existe ningún modelo base entrenado — nada que calibrar

`data/models/` contiene únicamente `.gitkeep` (verificado con `ls -la`,
igual que en cada auditoría anterior de esta fase). `calibrate()`
(`calibration_layer.py:70`) usa literalmente
`p_raw = model_output.p_model_yes` — y `p_model_yes` es `None` mientras
`model_status != TRAINED`. **Sin un modelo base ya entrenado que
produzca probabilidades reales sobre eventos históricos, no existen
pares `(p_model_raw, resultado_real)` con los que ajustar Platt/
isotonic** — no hay nada que calibrar todavía, sin importar si
existiera una implementación de `Calibrator`.

### 0.3 Estado real de los 3 candidatos, verificado directamente (no asumido de Paso 4.2)

| Candidato | Umbral | Valor real hoy | ¿Listo? |
|---|---|---|---|
| MLB — clasificador logreg (`train_mlb_baseline_model`) | `DEFAULT_MIN_TRAINING_SAMPLES=300` | `dataset.size=87` | No |
| MLB — Elo (`train_mlb_elo_model`) | `DEFAULT_MIN_GAMES=50` | `build_mlb_elo_game_sequence(hist).size=41` (verificado en vivo) | **No** — ver §0.4 |
| Tenis — clasificador logreg (`train_tennis_baseline_model`) | `DEFAULT_MIN_TRAINING_SAMPLES_TENNIS=30` | `dataset.size=600` | **Sí** |

**Tenis es el único candidato realmente listo hoy.** Sin embargo, **no
existe ningún `scripts/train_tennis_model.py`** — `train_tennis_baseline_model`
(`src/models/tennis_baseline.py:352`) existe y funciona (mismo patrón
exacto que el MLB de Fase 2, nunca ejecutado en producción por falta de
volumen hasta ahora), pero solo es invocable hoy vía Python directo, no
por CLI — a diferencia de MLB, que sí tiene `scripts/train_mlb_model.py`/
`scripts/train_mlb_elo_model.py` desde Fase 2.

### 0.4 Hallazgo adicional — `GATE-0[mlb_elo]` del Paso 4.2 es un falso positivo, corrección requerida

Verificado en vivo (`build_mlb_elo_game_sequence(hist).size == 41`, no
≥50): el reporte `scripts/check_training_gates.py` del Paso 4.2 marcó
`GATE-0[mlb_elo] (N_min=50): CUMPLIDO` — **incorrecto**. La causa: 
`build_sport_gate_report` (`src/evaluation/gate_report.py`) compara
`feature_snapshots_total`/`event_results_total` (conteos crudos, ambos
≥50 individualmente) contra el umbral — pero Elo **no usa
`feature_snapshots` en absoluto** (§1 de la investigación: solo
`event_snapshots` + `event_results`, con su propia lógica de
elegibilidad vía `build_mlb_elo_game_sequence`, que exige identidad de
equipo + `event_start_time` + resultado binario emparejado). El gate
genérico de Paso 4.2 fue diseñado para el patrón `build_*_training_dataset`
(clasificadores), no para Elo, que tiene un pipeline de datos distinto
— un hueco de diseño no detectado hasta ahora porque nunca se había
verificado Elo contra su propia función real.

**Esto no invalida el Paso 4.2** (su diseño para los clasificadores
sigue siendo correcto, verificado por test contra el dataset builder
real) — es un caso no cubierto, encontrado ahora, que se corrige como
parte de este paso (§7). Se reporta explícitamente en vez de dejarlo
pasar en silencio.

### 0.5 Autoauditoría adicional (Revisión 2) — contra los 4 requisitos del usuario, verificados contra código y datos reales

#### 1. Partición train/validation — **bug real encontrado, corrección requerida**

`split_dataset_temporally` (`mlb_baseline.py:252`/`tennis_baseline.py:222`,
código idéntico duplicado a propósito en ambos módulos) ordena las
**muestras individuales** por `(data_cutoff_timestamp, event_id)` y
corta la cola más reciente como validación — **nunca agrupa por
`event_id`**. Un mismo evento con varias `feature_snapshots` a lo largo
de varias horas (exactamente lo que produce la captura horaria en
producción) puede tener algunas de sus muestras en `train` y otras,
del mismo evento, con el mismo resultado, en `validation`.

**Verificado directamente contra `data/engine.db` de producción, no
hipotético**:
```
dataset de tenis: 600 muestras, 120 event_id distintos
split real (validation_fraction=0.2): train=480, validation=120
event_id que aparecen en AMBAS particiones: 120 de 120 (el 100%)
```
**Los 120 eventos de validación son exactamente los mismos 120 eventos
que el modelo ya vio en entrenamiento** (con features casi idénticas de
horas antes) — la validación reportada no mide generalización a
eventos nunca vistos, la infla de forma optimista. Confirmado que el
mismo patrón existe letra por letra en `mlb_baseline.py` (aunque MLB no
se entrena en este paso, se corrige también por consistencia, ver §7).

**Por qué ningún test lo detectó**: los dos únicos tests que ejercitan
`split_dataset_temporally`
(`test_split_dataset_temporally_validation_is_most_recent_and_never_random`,
`test_split_dataset_temporally_is_deterministic_across_calls`, en
ambos archivos de test) usan exactamente **una muestra por `event_id`**
(`mlb_0`...`mlb_9`, cada uno una sola vez) — con un evento por muestra,
partición por muestra y partición por evento son indistinguibles, así
que el bug es estructuralmente invisible en esos fixtures. Solo se
manifiesta con el patrón real de captura repetida de Fase 2 en
producción, nunca antes ejercitado a este volumen.

**Corrección** (§7): `split_dataset_temporally` se reescribe para
agrupar por `event_id` primero (representando cada evento por el
`data_cutoff_timestamp` MÍNIMO de sus muestras), ordenar los EVENTOS
cronológicamente, y asignar cada evento completo (todas sus muestras)
a un solo lado de la partición — ningún `event_id` puede aparecer en
ambas. `validation_fraction` sigue interpretándose sobre el número de
eventos, no de muestras (la proporción exacta de muestras ya no puede
garantizarse al tamaño exacto pedido, es una consecuencia necesaria de
eliminar la fuga, documentada explícitamente en el docstring nuevo).
**Comportamiento preservado exactamente para todo dato con una muestra
por evento** (verificado: los tests existentes, que usan ese patrón,
deben seguir pasando sin modificar sus aserciones).

#### 2. Artefacto versionado e inmutable con campos mínimos — mayormente satisfecho, un hueco real

Verificado campo por campo contra `TennisTrainedArtifact`
(`tennis_baseline.py:253-268`):

| Requisito | Estado | Nota |
|---|---|---|
| `model_version` | ✅ existe | string único con timestamp completo |
| `feature_set_version` | ✅ existe | |
| `training_timestamp` | ✅ existe como `trained_at` | mismo significado, nombre distinto — no se renombra sin necesidad |
| `sample_count` | ✅ existe como `n_training_samples` | |
| métricas de validación | ✅ existen | `accuracy`/`log_loss`/`brier_score` |
| **identificador o hash del modelo** | ❌ **no existe** | ningún campo de hash en `TennisTrainedArtifact`/`MlbTrainedArtifact`, ni en `registry.py` (`grep -rn "hash"` sin resultados en los 3 archivos) |
| nunca sobrescribe | ✅ confirmado | `model_version` incluye timestamp completo, `_save_tennis_artifact_metadata` siempre escribe un archivo nuevo (`{model_version}.metadata.json`), nunca reutiliza un nombre |

**Corrección**: se añade `artifact_sha256: str`, calculado con
`hashlib.sha256` sobre los bytes del archivo `.joblib` ya escrito —
mismo principio ya usado en el proyecto para `PolicyManifest.manifest_hash`
(hash de contenido real, no un identificador inventado), aplicado aquí
al contenido binario real del artefacto en vez de a un JSON, porque es
lo que permite detectar corrupción/reentrenamiento accidental idéntico,
no solo diferenciar por timestamp.

#### 3. Estructura preparada para calibración futura — hueco real, se añade sin fabricar valores

`calibration_version`/`calibration_method` no existen hoy en
`TennisTrainedArtifact` — **sí existen ya en `CalibrationOutput`**
(`src/calibration/schemas.py`), pero ese contrato es por-predicción (en
inferencia), no por-artefacto-entrenado. No hay hoy ningún lugar en el
artefacto mismo que declare "qué calibrador corresponde a esta versión
de modelo". Se añaden como `Optional[str] = None` — permanecen `None`
literalmente (ningún `Calibrator` real existe, §0.1) hasta que un paso
futuro los complete; esto NO es fabricar un valor, es declarar la forma
del contrato por adelantado, mismo patrón ya usado repetidamente en
este proyecto (p. ej. `CalibrationOutput.calibration_version` mismo).

`ece` y una curva de fiabilidad (`reliability_diagram`) **si se pueden
calcular hoy, sobre el modelo SIN calibrar** — no fabricar información
que sí es real y barata de producir sería el error opuesto. Se añaden
POBLADOS (no `None`):
- `ece: Optional[float]` — reutiliza literalmente `src.backtesting.metrics.ece`
  (Fase 3, Paso 3.8, ya implementado y testeado, confirmado con
  `grep -n "^def ece" src/backtesting/metrics.py:109` — verificado
  directamente, no asumido).
- `reliability_diagram: Optional[List[Dict[str, float]]]` — reutiliza
  literalmente `src.backtesting.metrics.calibration_curve` (misma
  función, mismo paso de Fase 3), serializado como lista de
  `{bucket_lower, bucket_upper, mean_predicted, mean_actual, n_samples}`
  por bucket. Es la fiabilidad del modelo CRUDO, no de uno calibrado —
  el dato más directo para decidir, en un futuro paso, si vale la pena
  calibrar en absoluto.

#### 4. Métricas suficientes para comparar versiones futuras — hueco parcial, se completa

`accuracy`/`log_loss`/`brier_score` ya existen; `ece` se añade (arriba).
`precision`/`recall`/`f1` **no existen** — se añaden, calculados sobre
la misma partición de validación y las mismas predicciones (`y_val`/
`val_pred`) ya usadas para `accuracy`, vía `sklearn.metrics.precision_score`/
`recall_score`/`f1_score` (misma librería ya importada en la función,
sin dependencia nueva). Justificación: `class_weight="balanced"` ya se
usa por el desbalance de clases esperado — `accuracy` sola puede ser
engañosa bajo desbalance, `precision`/`recall`/`f1` dan una imagen más
completa para comparar versiones futuras entre sí.

**Conclusión de la autoauditoría**: el diseño original (§1-§8 de la
Revisión 1) queda vigente en su arquitectura y flujo general — el
cambio real es en el CONTENIDO del artefacto (7 campos nuevos: 2 de
calibración futura vacíos por diseño, 4 poblados con evidencia real ya
computable, 1 hash) y una corrección de un bug de fuga de datos ya
presente en Fase 2, encontrado por primera vez aquí porque nunca se
había entrenado contra datos reales con múltiples muestras por evento.
Ninguno de los 7 campos nuevos requiere inventar una fórmula: los 4
poblados reutilizan funciones ya implementadas y testeadas de Fase 3,
los 2 de calibración quedan `None` porque no hay nada real que poner
todavía, y el hash reutiliza una técnica ya establecida en el proyecto
(`PolicyManifest.manifest_hash`).

---

## 1. Alcance reencuadrado del Paso 4.3

**Se propone renombrar el contenido real de este paso a: "Entrenar el
primer modelo base real del proyecto (tenis, clasificador logreg) y
corregir el gate de Elo — la calibración real queda explícitamente
diferida a un paso futuro (§10)."** Esto seguiría el mismo espíritu que
`FASE4_EXECUTION_PLAN.md` §6 Paso 4.3+ ya anticipaba ("cada uno requiere
su propia auditoría de diseño cuando su gate correspondiente se
cumpla") — el gate real de "calibrador" (un modelo base entrenado con
probabilidades reales que calibrar) simplemente no estaba cumplido
cuando se escribió ese roadmap, y sigue sin estarlo.

**Por qué no forzar el alcance original**: escribir una implementación
de `Calibrator` hoy, sin ningún modelo base real que la ejercite, sería
exactamente el tipo de fabricación que la Regla 3 prohíbe — se estaría
adivinando qué forma debe tener el ajuste (Platt vs. isotónica, sobre
qué partición, con qué tamaño mínimo) sin ninguna evidencia real de
`p_model_raw` contra la cual validar esa elección.

### Dentro de alcance de este paso

1. **Corrección de fuga de datos en `split_dataset_temporally`**
   (`mlb_baseline.py` y `tennis_baseline.py`, ambos — §0.5.1): partición
   por `event_id` agrupado, no por muestra individual. Prerrequisito de
   correctitud antes de entrenar nada — sin esto, cualquier métrica de
   validación reportada sería optimista de forma no detectada.
2. `scripts/train_tennis_model.py` (nuevo, mismo patrón que
   `scripts/train_mlb_model.py`).
3. Corrección del gate de Elo en `src/evaluation/gate_report.py` (§0.4,
   §4.3).
4. Enmienda aditiva a `TennisTrainedArtifact`/`train_tennis_baseline_model`
   (§0.5.2-4): `artifact_sha256` (hash del `.joblib`),
   `calibration_version`/`calibration_method` (`None`, estructura
   preparada), `ece`/`reliability_diagram` (poblados, reutilizando
   `src.backtesting.metrics`), `precision`/`recall`/`f1` (poblados,
   `sklearn`).
5. Ejecutar el entrenamiento real contra `data/engine.db` de
   producción — con confirmación explícita separada antes de hacerlo
   (ver "Consecuencia importante" más abajo).

### Fuera de alcance de este paso (diferido explícitamente)

- Cualquier implementación de `Calibrator` (Platt/isotónica) — §10.
- Entrenar MLB (clasificador o Elo) — ninguno de los dos alcanza su
  umbral todavía; este paso no adelanta trabajo sin datos reales
  suficientes.
- Cualquier cambio a la lógica de `decide()`/Policy Engine — el nuevo
  modelo entrenado se recoge automáticamente por el orquestador ya
  existente (Paso 4.1), sin tocar `src/policy/`/`src/orchestration/`.

### Consecuencia importante a confirmar explícitamente antes de ejecutar (no solo de diseñar)

El orquestador (Paso 4.1, ya en producción, corre cada hora vía
`local.prediction-market-engine.run-e2e-historical`) llama
`adapter.load_artifact_fn()` en cada corrida. **En el momento en que
exista un artefacto real de tenis en `data/models/`, la siguiente
corrida horaria lo recogerá automáticamente** y `p_model_yes` dejará de
ser `None` para tenis en producción real — `edge`/`ev_bruto`/
`confidence` empezarán a reflejar una probabilidad real, no un
`None` en cascada. `ENTER` sigue estructuralmente bloqueado (D-3,
`ev_neto_strength` sigue `None`), pero las decisiones `WATCH` reales
empezarán a basarse en un modelo real por primera vez en el proyecto.
Esto es exactamente el objetivo de este paso, pero es un cambio de
comportamiento real de producción, no solo la creación de un archivo
para inspección — **se reporta aquí y se pide confirmación separada
antes de ejecutar el entrenamiento real** (Regla 6 de la metodología,
mismo tratamiento que la carga del LaunchAgent en el Paso 4.0B),
distinta de la aprobación general de este diseño.

---

## 2. Arquitectura

Ningún paquete nuevo. Todo el código de entrenamiento ya vive en
`src/models/tennis_baseline.py` (Fase 2, sin tocar salvo la enmienda
aditiva de `ece`, §7) — este paso es, en esencia, **escribir el CLI que
faltaba** (mismo patrón que `scripts/train_mlb_model.py`) y **corregir
un gate** (`src/evaluation/gate_report.py`, aditivo). No se introduce
ninguna abstracción nueva tipo `SportAdapter` — a diferencia del
orquestador, entrenar un modelo no es una operación compuesta que deba
generalizarse a través de deportes en el mismo objeto; cada deporte ya
tiene su propio script de entrenamiento independiente (mismo patrón
"desacoplado a propósito" ya documentado para MLB/tenis desde Fase 2,
`registry.py` vs. persistencia propia de tenis).

```
scripts/train_tennis_model.py   (NUEVO, mismo patrón que train_mlb_model.py)
        |
        v
src/models/tennis_baseline.py::train_tennis_baseline_model()  (Fase 2, enmienda aditiva: +ece)
        |
        +--> src/models/tennis_baseline.py::build_tennis_training_dataset()  (Fase 2, sin cambios)
        +--> src/backtesting/metrics.py::ece()  (Fase 3 Paso 3.8, sin cambios, reutilizado)
        +--> sklearn (LogisticRegression, ya usado, sin cambios)

src/evaluation/gate_report.py  (Fase 4 Paso 4.2, enmienda: gate de Elo específico)
        |
        +--> src/models/mlb_elo.py::build_mlb_elo_game_sequence()  (Fase 2, sin cambios, reutilizado)
```

---

## 3. Responsabilidades

| Módulo | Responsabilidad | NO responsable de |
|---|---|---|
| `scripts/train_tennis_model.py` | Invocar `train_tennis_baseline_model`, imprimir resultado (mismo formato que `train_mlb_model.py`) | Ninguna lógica de entrenamiento propia — delega todo |
| `train_tennis_baseline_model` (enmendado) | Entrenar + persistir el artefacto + calcular métricas de validación, ahora incluido `ece` | Calibración — sigue sin calibrador, `p_model_calibrated` sigue `None` en cascada hasta el paso futuro |
| `gate_report.py` (corregido) | Reportar GATE-0 con la lógica de elegibilidad REAL de cada modelo (clasificador vs. Elo) | Decidir si entrenar — solo informa, igual que antes |

---

## 4. Flujo de ejecución

### 4.1 `scripts/train_tennis_model.py` (nuevo, mismo patrón que `train_mlb_model.py`)

```
1. history_repository = HistoryRepository()  (producción real)
2. model_status, artifact, warnings = train_tennis_baseline_model(
       history_repository, min_samples=DEFAULT_MIN_TRAINING_SAMPLES_TENNIS,
       validation_fraction=DEFAULT_VALIDATION_FRACTION,
   )
3. if model_status == INSUFFICIENT_HISTORY:
       imprimir warnings, exit 0 (honesto, nunca falla la corrida --
       mismo patrón ya usado en train_mlb_model.py)
   else (TRAINED):
       imprimir model_version, feature_set_version, n_training_samples,
       n_train_samples, n_validation_samples, accuracy, log_loss,
       brier_score, ece (NUEVO), file_path
4. return 0
```

Sin argumentos de CLI más allá de los ya usados en `train_mlb_model.py`
(`--min-samples`, `--validation-fraction`, `--models-dir`) — mismo
patrón, sin inventar opciones nuevas.

### 4.0 Corrección de `split_dataset_temporally` (§0.5.1) — MLB y tenis

Reescritura de la función (idéntica en ambos módulos, mismo patrón ya
duplicado deliberadamente):
```python
def split_dataset_temporally(dataset, validation_fraction=DEFAULT_VALIDATION_FRACTION):
    samples_by_event: Dict[str, List[Sample]] = {}
    for s in dataset.samples:
        samples_by_event.setdefault(s.event_id, []).append(s)

    # Cada evento representado por su data_cutoff_timestamp MÍNIMO --
    # cuándo entró por primera vez al histórico observable.
    event_order = sorted(samples_by_event, key=lambda eid: min(s.data_cutoff_timestamp for s in samples_by_event[eid]))

    n_validation_events = round(len(event_order) * validation_fraction)
    n_validation_events = max(1, min(n_validation_events, len(event_order) - 1)) if len(event_order) > 1 else 0

    train_events = set(event_order[: len(event_order) - n_validation_events])
    train_samples = [s for s in dataset.samples if s.event_id in train_events]
    validation_samples = [s for s in dataset.samples if s.event_id not in train_events]
    ...  # construcción de los 2 TrainingDataset, igual que hoy
```
`validation_fraction` sigue interpretándose sobre el número de EVENTOS,
no de muestras — la proporción exacta de muestras deja de poder
garantizarse al tamaño exacto pedido (consecuencia necesaria de
eliminar la fuga), documentado en el docstring nuevo de la función.
**Comportamiento preservado exactamente cuando cada evento tiene una
sola muestra** (caso de todos los tests existentes, que deben seguir
pasando sin tocar sus aserciones).

### 4.1b Enmiendas a `TennisTrainedArtifact`/`train_tennis_baseline_model` (§0.5.2-4)

```python
@dataclass
class TennisTrainedArtifact:
    ...  # campos ya existentes, sin cambios
    n_validation_events: int = 0          # nuevo, transparencia del split por evento
    n_train_events: int = 0               # nuevo
    precision: Optional[float] = None     # nuevo, poblado
    recall: Optional[float] = None        # nuevo, poblado
    f1: Optional[float] = None            # nuevo, poblado
    ece: Optional[float] = None           # nuevo, poblado
    reliability_diagram: Optional[List[Dict[str, float]]] = None  # nuevo, poblado
    calibration_version: Optional[str] = None   # nuevo, permanece None
    calibration_method: Optional[str] = None    # nuevo, permanece None
    artifact_sha256: str = ""             # nuevo, poblado (hash real del .joblib)
```
Después de calcular `val_proba`/`val_pred` (ya existente, sin tocar):
```python
from sklearn.metrics import f1_score, precision_score, recall_score
from src.backtesting.metrics import calibration_curve, ece as compute_ece

precision = float(precision_score(y_val, val_pred, zero_division=0))
recall = float(recall_score(y_val, val_pred, zero_division=0))
f1 = float(f1_score(y_val, val_pred, zero_division=0))
val_ece = compute_ece(list(y_val), list(val_proba))
buckets = calibration_curve(list(y_val), list(val_proba))
reliability_diagram = [
    {"bin_lo": b.bin_lo, "bin_hi": b.bin_hi,
     "mean_predicted": b.mean_predicted, "mean_actual": b.mean_actual, "n_samples": b.n_samples}
    for b in buckets
] or None
```
Después de `joblib.dump(pipeline, file_path)` (ya existente):
```python
import hashlib
artifact_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
```
`_save_tennis_artifact_metadata` gana las líneas explícitas
correspondientes a cada campo nuevo (serializa campo por campo, no por
introspección genérica — verificado directamente en el código real).

### 4.3 Corrección del gate de Elo

`build_sport_gate_report` gana un parámetro opcional
`eligible_count_fn: Optional[Callable[[HistoryRepository], int]] = None`
por umbral — cuando se provee para una clave de `thresholds`, GATE-0 de
esa clave específica compara contra `eligible_count_fn(hist)` en vez de
`feature_snapshots_total`/`event_results_total`. `scripts/check_training_gates.py`
pasa `lambda hist: build_mlb_elo_game_sequence(hist).size` para la
clave `mlb_elo`, dejando `mlb_classifier`/`tennis_classifier` con el
comportamiento actual (correcto, ya verificado). Alternativa considerada
y descartada: crear un gate completamente separado solo para Elo —
descartada porque duplicaría la estructura de `SportGateReport` sin
necesidad; un parámetro opcional es la enmienda mínima.

---

## 5. Manejo de errores

`train_tennis_baseline_model` ya es honesto por diseño (Fase 2): nunca
lanza una excepción no controlada en el camino esperado —
`INSUFFICIENT_HISTORY` es un valor de retorno, no una excepción. El
script nuevo no necesita ningún `try/except` propio para ese caso
(mismo patrón que `train_mlb_model.py`, verificado). Si `sklearn`/
`joblib` fallan por una razón inesperada (p. ej. disco lleno al
escribir el artefacto), la excepción se propaga sin capturar — mismo
comportamiento que `train_mlb_model.py` ya tiene hoy, no se introduce
un manejo distinto sin motivo.

## 6. Recuperación / idempotencia

Entrenar dos veces no es destructivo: cada corrida escribe un artefacto
nuevo con `model_version` timestamped (`tennis_baseline_logreg_v1_{timestamp}`)
— `load_latest_tennis_artifact()` siempre toma el más reciente por
nombre de archivo. No hay ningún lock necesario (invocación manual,
mismo patrón que `train_mlb_model.py`, que tampoco lo tiene) — un
entrenamiento no compite por escritura con `run_e2e.py`/
`data_maintenance.py`/`sync_results.py` (archivo distinto,
`data/models/`, no `data/engine.db`).

## 7. Logs

`print()`, mismo patrón que todo el proyecto (`train_mlb_model.py` como
precedente exacto). Sin archivo de log nuevo (invocación manual, salida
a stdout).

---

## 8. Enmiendas a código ya cerrado

1. **`src/models/tennis_baseline.py::split_dataset_temporally` y
   `src/models/mlb_baseline.py::split_dataset_temporally`** —
   **corrección de comportamiento** (no aditiva pura como las demás):
   elimina la fuga de datos de §0.5.1. Cambia el contenido exacto de la
   partición train/validation para cualquier dataset con >1 muestra por
   evento (nunca antes ejercitado con datos reales) — preserva el
   comportamiento exacto para datasets con 1 muestra por evento
   (verificado: todos los tests existentes deben seguir pasando sin
   modificar sus aserciones). Se toca `mlb_baseline.py` aunque MLB no
   se entrena en este paso, por consistencia — dejar el mismo bug sin
   corregir en el gemelo del archivo sería diferir su descubrimiento,
   no evitarlo.
2. `src/models/tennis_baseline.py::TennisTrainedArtifact`/
   `train_tennis_baseline_model` — aditiva, 9 campos nuevos (§4.1b):
   `n_validation_events`/`n_train_events`/`precision`/`recall`/`f1`/
   `ece`/`reliability_diagram`/`calibration_version`/`calibration_method`/
   `artifact_sha256`. Cero cambio de comportamiento en el resto de la
   función (algoritmo, umbral, artefacto `.joblib` en sí).
3. `src/evaluation/gate_report.py::build_sport_gate_report` — aditiva,
   parámetro opcional `eligible_count_fn` con default `None` que
   preserva el comportamiento actual exacto para todo llamador
   existente (`mlb_classifier`/`tennis_classifier` no cambian). Corrige
   el falso positivo de `mlb_elo` (§0.4) sin tocar la lógica de los
   clasificadores.

Ninguna otra enmienda — `src/models/mlb_elo.py`,
`src/orchestration/*`, `src/policy/*` quedan sin tocar. La corrección
de `split_dataset_temporally` en `mlb_baseline.py` (punto 1) es la
única de las 3 que no es puramente aditiva — se señala con más énfasis
por eso mismo.

---

## 9. Decisiones abiertas que este documento no resuelve

Ninguna decisión numérica nueva es necesaria para el alcance
reencuadrado (§1) — `min_samples`/`validation_fraction` ya son
constantes aprobadas de Fase 2, reutilizadas tal cual, no inventadas
aquí. La única decisión genuina:

**¿Ejecutar el entrenamiento real ahora, dado el efecto automático
sobre producción (§1, "Consecuencia importante")?** Alternativas:

1. **Ejecutar ahora, con confirmación explícita separada
   (recomendada)** — produce evidencia real inmediata (mismo estándar
   que todos los pasos anteriores de Fase 4), dejando que el
   orquestador ya aprobado (Paso 4.1) empiece a usar probabilidades
   reales de tenis en la próxima corrida horaria.
2. **Implementar pero no ejecutar todavía** — el código queda listo y
   testeado, pero `data/models/` sigue vacío hasta una autorización
   posterior específica. Retrasa sin necesidad el primer resultado real
   del proyecto.

Recomendación: Alternativa 1, con la confirmación explícita pedida
antes de correr el script contra producción (no antes de implementarlo
ni testearlo).

---

## 10. Próximo paso futuro, explícitamente fuera de este documento

Una vez exista un modelo de tenis real entrenado y corriendo en
producción durante suficiente tiempo para acumular predicciones reales
(el propio `val_proba`/`y_val` de la partición de validación de ESTE
entrenamiento ya sería una primera fuente, aunque pequeña — ~120
muestras dado `validation_fraction=0.2` sobre 600), un futuro paso
(sin numerar todavía, análogo al propio `FASE4_EXECUTION_PLAN.md` §6
Paso 4.3+) tendría que decidir, con su propia auditoría de diseño:
Platt vs. isotónica, sobre qué partición ajustar (¿la validación de
este entrenamiento, o un conjunto nuevo separado para no reutilizar la
misma partición que ya influyó en las métricas reportadas del modelo
base?), y un umbral mínimo de muestras para el propio calibrador
(ninguno existe hoy en ningún documento aprobado). No se diseña aquí
por el mismo motivo que `FASE4_EXECUTION_PLAN.md` ya daba para todo el
Paso 4.3+: hacerlo sin ver primero cómo luce el `ece`/`brier_score`
reales del modelo sin calibrar sería fabricar una solución antes de
conocer el problema.

---

## 11. Pruebas previstas

- **`split_dataset_temporally` (ambos archivos)** — la prueba central de
  este paso: un dataset sintético con >1 muestra por `event_id` (mismo
  patrón real que reveló el bug, §0.5.1) confirma que **ningún
  `event_id` aparece en ambas particiones** tras el fix — regresión
  directa del hallazgo real. Todos los tests ya existentes de
  `split_dataset_temporally` (`..._validation_is_most_recent_and_never_random`,
  `..._is_deterministic_across_calls`) deben seguir pasando SIN
  modificar sus aserciones (confirma comportamiento preservado para 1
  muestra/evento). Caso límite: un solo evento con muchas muestras (no
  hay forma de particionar sin fuga — documentar el comportamiento
  exacto, ej. devolver todo a `train`).
- `tests/unit/test_tennis_baseline.py` (ampliado): un test por campo
  nuevo del artefacto — `precision`/`recall`/`f1` coinciden con
  `sklearn` llamado directamente sobre los mismos `y_val`/`val_pred`;
  `ece`/`reliability_diagram` coinciden con
  `src.backtesting.metrics.ece`/`calibration_curve` llamados
  directamente; `artifact_sha256` coincide con
  `hashlib.sha256(file_path.read_bytes()).hexdigest()` calculado en el
  test; `calibration_version`/`calibration_method` son `None` siempre
  (ningún calibrador existe); `n_train_events`/`n_validation_events`
  sensatos (`<=` sus respectivos `n_train_samples`/`n_validation_samples`,
  suman el total de eventos distintos). Caso `INSUFFICIENT_HISTORY`
  verificado ya existente — confirmar que ninguno de los campos nuevos
  aparece poblado cuando no se entrena (artefacto es `None`).
- `tests/unit/test_gate_report.py` (ampliado): nuevo test para
  `eligible_count_fn` — con un `HistoryRepository` de prueba donde
  `feature_snapshots_total`/`event_results_total` superan el umbral
  pero la función de elegibilidad inyectada (simulando Elo) devuelve un
  número menor, `gate_0_met` para esa clave debe ser `False` — fija
  como regresión exactamente el bug de §0.4. Test adicional
  confirmando que omitir `eligible_count_fn` preserva el comportamiento
  actual exacto (regresión de no-ruptura).
- `tests/integration/test_e2e_real.py`: no se añade un test nuevo aquí
  — entrenar contra la API real no aplica (el entrenamiento lee de
  `HistoryRepository`, no de una API externa); el test de integración
  real de este paso es la propia ejecución manual contra
  `data/engine.db` de producción (§14, evidencia esperada), igual que
  Paso 4.0A/4.0B.
- Suite completa re-ejecutada, sin regresión.

---

## 12. Criterios de aceptación

- `scripts/train_tennis_model.py` existe, mismo patrón que
  `train_mlb_model.py`, exit 0 en ambos casos (`TRAINED`/
  `INSUFFICIENT_HISTORY`).
- `split_dataset_temporally` corregido en ambos archivos — ningún
  `event_id` aparece en ambas particiones, verificado por test con
  datos multi-muestra-por-evento (no solo con los fixtures antiguos de
  1 muestra/evento, que nunca lo habrían revelado).
- Los 9 campos nuevos de `TennisTrainedArtifact` calculados y
  persistidos correctamente cuando `TRAINED`
  (`precision`/`recall`/`f1`/`ece`/`reliability_diagram`/
  `artifact_sha256`/`n_train_events`/`n_validation_events` poblados;
  `calibration_version`/`calibration_method` en `None`).
  `GATE-0[mlb_elo]` corregido — reporta `no cumplido` con los datos
  reales de hoy (41 < 50), verificado por test y por corrida real.
- Con confirmación explícita separada (§9): entrenamiento real
  ejecutado contra `data/engine.db` de producción, artefacto real
  inspeccionado (metadata JSON legible, `model_status=TRAINED`,
  métricas numéricas sensatas — `0 <= accuracy <= 1`,
  `0 <= brier_score <= 1`, `0 <= ece <= 1`).
- Próxima corrida horaria real de `run_e2e.py` (o una corrida manual
  controlada, `--mode sample`) confirmada recogiendo el artefacto
  (`model_status=TRAINED`, `p_model_yes` no `None` para al menos un
  registro de tenis con `market_id`, `model_version` no `None` en la
  `OpportunityEvaluation` resultante) — verificado por SQL directo,
  mismo estándar que Paso 4.1.
- `ENTER` sigue sin aparecer nunca (D-3 sigue bloqueando
  independientemente) — verificado, no solo asumido.
- Suite completa en verde, `git diff --stat` limpio salvo lo declarado.
- `CONTINUITY.md` actualizado antes del commit.

---

## 13. Riesgos

- **El modelo de tenis entrenado con 600 muestras podría tener mala
  calidad real** (`accuracy`/`brier`/`ece` mediocres) — no es un riesgo
  a mitigar en este paso, es exactamente la información que este paso
  existe para producir honestamente. No se oculta un mal resultado ni
  se reintenta con otros hiperparámetros sin autorización nueva.
- **Cambio de comportamiento de producción no trivial** (§1) — mitigado
  exigiendo confirmación explícita separada antes de ejecutar (no solo
  de diseñar/implementar).
- **Categorías de `tournament_round_context` descubiertas solo del
  split de train** (ya documentado en el propio código, Fase 2) — si la
  validación contiene una categoría nunca vista en entrenamiento, esa
  columna queda en `NaN`/imputada, comportamiento ya existente y ya
  aceptado, no una novedad de este paso.
- **El artefacto de tenis nunca se ha probado contra datos reales de
  producción en absoluto** (ni siquiera como contrato) — mitigado por
  el criterio de aceptación que exige verificar la recogida real por el
  orquestador vía SQL, no solo confiar en que "debería funcionar".
- **La corrección de `split_dataset_temporally` cambia las métricas de
  validación reportadas respecto a lo que un entrenamiento con el bug
  habría mostrado** (probablemente peores, al eliminar la fuga
  optimista) — no es un riesgo a mitigar, es la corrección funcionando
  como se espera; documentado aquí para que un futuro lector no lo
  interprete como una regresión de calidad del modelo.
- **`n_validation_events`/`n_train_events` pueden dar una validación
  más pequeña de lo que `validation_fraction=0.2` sugeriría** (la
  partición ahora es por evento, no por muestra — con eventos de
  distinto número de muestras, la fracción exacta de FILAS ya no es
  0.2 exacto) — documentado explícitamente en el docstring de la
  función corregida, no oculto.

---

## 14. Evidencia esperada

- Test dedicado demostrando la ausencia de fuga (cero `event_id` en
  ambas particiones) contra un dataset sintético con múltiples muestras
  por evento — la evidencia más directa de que el hallazgo de §0.5.1
  quedó corregido, no solo documentado.
- Salida completa de `scripts/train_tennis_model.py` corriendo contra
  `data/engine.db` real.
- Contenido completo del archivo de metadata JSON generado (los 9
  campos nuevos incluidos, `calibration_version`/`calibration_method`
  visiblemente `null`).
- `python scripts/check_training_gates.py` re-ejecutado, mostrando
  `GATE-0[mlb_elo]: no cumplido` (corregido) sin cambios en los otros
  dos.
- `SELECT model_version, calibration_version FROM opportunity_evaluations
  WHERE ...` tras una corrida real posterior de `run_e2e.py`,
  confirmando `model_version` no nulo para tenis por primera vez en el
  proyecto, `calibration_version` todavía `NULL` (honesto, ningún
  calibrador existe).
- Suite completa (978 + nuevos), `git diff --stat`.

---

## 15. Próximo paso (de este documento)

Este documento no autoriza código todavía. Se necesita:

1. Aprobación general de §1-§8 (alcance reencuadrado, arquitectura,
   flujo, enmiendas).
2. Aprobación de la Alternativa 1 de §9 (ejecutar el entrenamiento real
   como parte de este mismo paso, con su propia confirmación separada
   antes de correrlo).

Con eso aprobado, se implementa con la disciplina ya establecida: un
commit de código + un commit de `CONTINUITY.md`, suite completa antes
de cada uno, confirmación explícita antes de la corrida real contra
producción, sin avanzar a ningún paso posterior sin nueva aprobación.
