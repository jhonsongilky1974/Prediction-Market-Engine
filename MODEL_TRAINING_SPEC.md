# Diseño del Paso 4.3 (PROPUESTO, NO APROBADO)

**Estado: diseño para aprobación. Cero código escrito.** Responde a la
petición del usuario: presentar el diseño completo del Paso 4.3 antes
de implementar. Sigue el mismo protocolo que `ORCHESTRATOR_SPEC.md`
(Paso 4.1): investigación del código real primero, hallazgos reportados
explícitamente, decisiones abiertas señaladas sin fabricar valores.

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

1. `scripts/train_tennis_model.py` (nuevo, mismo patrón que
   `scripts/train_mlb_model.py`).
2. Corrección del gate de Elo en `src/evaluation/gate_report.py` (o un
   módulo hermano específico para Elo — ver §7).
3. Enmienda aditiva a `train_tennis_baseline_model`: exponer `ece`
   (Expected Calibration Error) en el artefacto, reutilizando
   `src.backtesting.metrics.ece` (Fase 3, Paso 3.8, ya implementado y
   testeado — verificado que existe, contrario a lo que se podría
   asumir) — hoy el artefacto solo guarda `accuracy`/`brier_score`/
   `log_loss`, no `ece`, pese a que `EVALUATION_LEARNING_SPEC.md` §2 lo
   define como parte de "calidad de la probabilidad".
4. Ejecutar el entrenamiento real contra `data/engine.db` de
   producción — con confirmación explícita separada antes de hacerlo
   (§0.5 de esta sección — ver razón).

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

### 4.2 Enmienda a `train_tennis_baseline_model` — `ece`

Después de calcular `brier`/`logloss` (ya existente, sin tocar), una
línea aditiva:
```python
from src.backtesting.metrics import ece as compute_ece
...
val_ece = compute_ece(list(y_val), list(val_proba))
```
`TennisTrainedArtifact` gana un campo `ece: Optional[float] = None`
(aditivo, mismo patrón que los campos ya opcionales del artefacto) —
`_save_tennis_artifact_metadata` ya serializa el dataclass completo por
introspección (verificar en implementación; si serializa campo por
campo explícito, se añade ahí también).

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

1. `src/models/tennis_baseline.py::train_tennis_baseline_model` —
   aditiva, `ece` calculado y añadido al artefacto (§4.2). Cero cambio
   de comportamiento en el resto de la función.
2. `src/evaluation/gate_report.py::build_sport_gate_report` — aditiva,
   parámetro opcional `eligible_count_fn` con default `None` que
   preserva el comportamiento actual exacto para todo llamador
   existente (`mlb_classifier`/`tennis_classifier` no cambian). Corrige
   el falso positivo de `mlb_elo` (§0.4) sin tocar la lógica de los
   clasificadores.

Ninguna otra enmienda — `src/models/mlb_elo.py`,
`src/orchestration/*`, `src/policy/*` quedan sin tocar.

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

- `tests/unit/test_tennis_baseline.py` (ampliado, no un archivo
  nuevo): nuevo test confirmando que `TennisTrainedArtifact.ece` se
  calcula y coincide con `src.backtesting.metrics.ece(y_val, val_proba)`
  llamado directamente (mismo patrón que ya se usa para
  `brier_score`/`log_loss` en los tests existentes de entrenamiento, si
  existen — si no existen tests de esas métricas todavía, se añaden
  ambos: uno para `ece` y confirmación de que no rompe nada existente).
  Caso `INSUFFICIENT_HISTORY` verificado ya existente — confirmar que
  `ece` no se calcula ni aparece cuando no se entrena (artefacto es
  `None`).
- `tests/unit/test_gate_report.py` (ampliado): nuevo test para
  `eligible_count_fn` — con un `HistoryRepository` de prueba donde
  `feature_snapshots_total`/`event_results_total` superan el umbral
  pero la función de elegibilidad inyectada (simulando Elo) devuelve un
  número menor, `gate_0_met` para esa clave debe ser `False` — fija
  como regresión exactamente el bug de §0.4. Test adicional
  confirmando que omitir `eligible_count_fn` preserva el comportamiento
  actual exacto (regresión de no-ruptura).
- Nuevo, opcional si aplica: `tests/unit/test_train_tennis_model_script.py`
  o extender el patrón ya usado — verificar que el script no falla con
  `INSUFFICIENT_HISTORY` simulado (mismo nivel de test que
  `data_maintenance.py`/scripts anteriores, si existiera un test
  equivalente para `train_mlb_model.py`; si no existe ninguno, no se
  inventa un nuevo nivel de cobertura no usado en ningún otro script,
  se deja igual de cubierto que su precedente).
- `tests/integration/test_e2e_real.py`: no se añade un test nuevo aquí
  — entrenar contra la API real no aplica (el entrenamiento lee de
  `HistoryRepository`, no de una API externa); el test de integración
  real de este paso es la propia ejecución manual contra
  `data/engine.db` de producción (§13, evidencia esperada), igual que
  Paso 4.0A/4.0B.
- Suite completa re-ejecutada, sin regresión.

---

## 12. Criterios de aceptación

- `scripts/train_tennis_model.py` existe, mismo patrón que
  `train_mlb_model.py`, exit 0 en ambos casos (`TRAINED`/
  `INSUFFICIENT_HISTORY`).
- `TennisTrainedArtifact.ece` calculado y persistido cuando
  `TRAINED`, reutilizando literalmente `src.backtesting.metrics.ece`.
- `GATE-0[mlb_elo]` corregido — reporta `no cumplido` con los datos
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

---

## 14. Evidencia esperada

- Salida completa de `scripts/train_tennis_model.py` corriendo contra
  `data/engine.db` real.
- Contenido del archivo de metadata JSON generado (`ece` incluido).
- `python scripts/check_training_gates.py` re-ejecutado, mostrando
  `GATE-0[mlb_elo]: no cumplido` (corregido) sin cambios en los otros
  dos.
- `SELECT model_version, calibration_version FROM opportunity_evaluations
  WHERE ...` tras una corrida real posterior de `run_e2e.py`,
  confirmando `model_version` no nulo para tenis por primera vez en el
  proyecto.
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
