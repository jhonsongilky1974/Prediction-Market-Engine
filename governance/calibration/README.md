# Gobernanza de la evaluación del calibrador de tenis

Contrato versionado que fija, **antes de entrenar**, cómo se decide si un calibrador
puede proponerse para promoción. Implementación: `src/evaluation/calibration_verdict.py`,
`src/evaluation/calibration_governance.py`, `src/evaluation/candidate_registry.py` y
`scripts/evaluate_tennis_calibrator.py`. Este directorio **no** contiene artefactos ni blobs
(ni `.joblib`, ni copias de la base de datos): solo texto estructurado y hashes.

> Este mecanismo no entrena, no promueve y no cablea nada. No modifica
> `config/model_registry.json`. El Tramo 5A sigue BLOQUEADO.

> **Sustitución normativa.** Este contrato sustituye, para toda evaluación de calibradores de
> tenis posterior a su incorporación a `main`, el criterio de aceptación de
> `CALIBRATION_SPEC.md` §6 (`calibrated_ece_oof <= raw_ece_oof` o "diferencia marginal"), y amplía
> su §2: la partición de test del modelo base, que §2 no utilizaba, se consulta exactamente una
> vez, solo como veto y solo tras `ELEGIBLE_PRELIMINAR`. En caso de conflicto prevalece este
> documento. Diferencias respecto de §6: un empate, o una diferencia dentro de τ = 1e-4, es
> `INCONCLUSO` y no cumple; ni el ECE ni el Brier pueden empeorar más que τ; al menos una de las
> dos métricas debe mejorar más que τ; "marginal" queda definido como τ = 1e-4 y solo para el no
> deterioro. `scripts/run_e2e.py` (líneas 48-55) sigue sin cablear el calibrador: este documento
> no lo cablea ni lo autoriza.

## Cuatro estados que NO son lo mismo

| Estado | Significado |
|---|---|
| **Cumple el mínimo operativo** | Precondición de datos (`n ≥ 30`, métricas válidas). No es un veredicto ni evidencia de nada. |
| **ELEGIBLE** | El candidato PUEDE PROPONERSE para promoción: no deteriora ninguna métrica y mejora más que τ al menos una, y el test no lo veta. **No demuestra mejora estadística.** No autoriza ni ejecuta la promoción. |
| **Demuestra mejora estadística** | No está definido ni es alcanzable con el repositorio actual (no hay método, intervalos ni umbral). |
| **PROMOVIDO** | Solo por autorización humana explícita, plasmada como entradas `ALLOWED` con hashes en `config/model_registry.json` mediante un PR revisable. |

## Veredicto (τ = 1e-4, ECE y Brier; menor es mejor)

```
delta_ECE   = raw_ECE   - calibrated_ECE
delta_Brier = raw_Brier - calibrated_Brier
```

**Fase 1: partición de validación** (validación cruzada fuera de muestra, agrupada por evento)

| Resultado | Condición (en este orden) |
|---|---|
| `ERROR` | métricas ausentes, NaN, infinitas o fuera de [0, 1]; conteo inválido |
| `INCONCLUSO` | entrenamiento sin completar (`INSUFFICIENT_HISTORY`, `MODEL_NOT_TRAINED`), o `n_validation < 30` |
| `RECHAZADO` | cualquier `delta < -τ` (deterioro) |
| `INCONCLUSO` | ambos `|delta| ≤ τ` (efecto nulo) |
| `ELEGIBLE_PRELIMINAR` | ningún `delta < -τ` y al menos uno `> τ` |

**Fase 2: veto del test.** Solo para un `ELEGIBLE_PRELIMINAR`; en cualquier otro caso el test
**no se lee**. El test nunca rescata ni eleva: solo puede mantener o degradar.

| Resultado | Condición |
|---|---|
| `ERROR` | datos o métricas del test inválidos |
| `INCONCLUSO` | `n_test < 30` |
| `RECHAZADO` | cualquier `delta_test < -τ` |
| `ELEGIBLE` | en otro caso |

El modelo base ya consultó el test una vez (su `candidate_status`); el veto es la segunda y
última lectura. Ambas quedan registradas; el test no se usa para ajustar nada.

## Libro append-only (`ledger.jsonl`)

Una línea JSON canónica por entrada: `seq`, `prev_sha256`, `type`, `recorded_at` (UTC),
`payload`, `entry_sha256`. Cada línea encadena el hash de la anterior (génesis `0×64`). La cadena
detecta ediciones, borrados, reordenamientos y truncamientos a mitad de línea de entradas
anteriores, salvo que quien escriba el archivo recalcule todos los hashes posteriores. Por eso la
integridad del final del libro se ancla fuera de él (véase "Ancla del libro"); sin ese ancla, el
libro por sí solo no impide truncar sus últimas entradas. Tipos:
`PREREG_SIGNED`, `SNAPSHOT_FROZEN`, `BASE_TRAINED`, `CALIBRATOR_TRAINED`, `PHASE1_VERDICT`,
`TEST_READ`, `TEST_RESULT`, `FINAL_VERDICT` y `ATTEMPT_ABANDONED`. Los cuatro que van entre
`PHASE1_VERDICT` y `FINAL_VERDICT` solo los emite el evaluador. No hay API pública para añadir
entradas sin pasar por `register_entry` (que valida cada tipo) o por `evaluate_attempt`.

**Toda entrada del libro y todo preregistro firmado se incorpora mediante PR revisable; nunca
directamente a `main`.** Todos los intentos quedan publicados; un `ELEGIBLE` no borra un
`INCONCLUSO` o `RECHAZADO` anterior.

### Ancla del libro

La cadena de hashes **por sí sola no detecta** que se trunque el final del libro ni que se
reescriba la cadena completa con hashes nuevos y válidos. El ancla principal y obligatoria es
el **historial de Git en `main`/`origin/main`**: `verify-ledger` compara el libro propuesto con
el libro aceptado en la base. El contenido ya aceptado debe coincidir **byte a byte** con el
inicio del libro propuesto y solo pueden **añadirse** entradas; además se validan la cadena de
la base, la de la propuesta y la integridad de los preregistros y manifiestos registrados.
`evaluate` solo opera si el preregistro, el snapshot, el modelo base y el calibrador del
intento **ya están aceptados en `main`** (dentro del prefijo de la base) y `verify-ledger`
valida cadena y prefijo. Si no hay base verificable, referencia en `main` o preregistro
previamente aceptado, **falla cerrado**. Solo se aceptan `main` y `origin/main` como base.

Referencia secundaria: cada cierre en `CONTINUITY.md` registra el `seq` y el `entry_sha256` de
la última entrada aceptada. Es evidencia de cierre y de revisión; **no es un ancla
criptográfica independiente** y no protege frente a quien pueda reescribir `main`.

### Qué garantiza el código y qué depende de Git, branch protection y revisión

| Garantías técnicas (las impone el código y las comprueban las pruebas) | Garantías que dependen de Git, branch protection y revisión de PR |
|---|---|
| Cadena de hashes válida; archivos registrados (preregistro, manifiesto) sin alterar | Que `main` no se reescriba (force-push, historial) y que exija PR revisado |
| El libro propuesto extiende el aceptado byte a byte (si la base de `main` es auténtica) | Que quien revisa el PR compruebe que no se hizo otra lectura del test fuera del flujo |
| Un intento abierto debe cerrarse (`FINAL_VERDICT` o `ATTEMPT_ABANDONED`) antes de otro | Que ningún preregistro o entrada llegue a `main` sin revisión humana |
| El test se lee como máximo una vez y nunca eleva un veredicto | Que el firmante sea quien dice ser (firma Git verificada preferible) |
| SHA-256 de manifiesto, artefactos y sidecars coincide con lo registrado | Que no se sustituya el entorno de ejecución del evaluador |

El hash prueba **identidad de bytes**; el ancla prueba **prefijo aceptado**. Ninguno prueba
calidad estadística. Quien controle `main` puede reescribirlo todo: ese riesgo no lo elimina
este diseño.

### Intentos abandonados (`ATTEMPT_ABANDONED`)

Estado terminal explícito alternativo a `FINAL_VERDICT`: exige `reason`, `author`,
`abandoned_at` y el `attempt_id` del intento existente; **no lleva métricas** (cualquier otra
clave se rechaza) y **nunca puede convertirse en `ELEGIBLE`**: un intento abandonado no se
evalúa ni lee el test. Un intento abierto debe terminar en `FINAL_VERDICT` o `ATTEMPT_ABANDONED`
antes de registrar otro snapshot (de cualquier preregistro). Abandonar un intento ya cerrado se
rechaza.

## Preregistro

`preregistrations/<prereg_id>.md` (ver `preregistration_template.md`): parámetros, fórmula,
fecha, `git_commit_base` (40 caracteres), autor y SHA-256 del documento. Se firma **antes de
cualquier entrenamiento**: el libro rechaza un `BASE_TRAINED` cuyo `trained_at` no sea posterior
a la firma (el preregistro no tiene `trained_at`: la coherencia que se exige es de **orden**; el
mismo `trained_at` debe coincidir en el manifiesto, `BASE_TRAINED` y el sidecar del artefacto). SHA-256, commit base, autor y fecha son obligatorios; una firma Git verificada es
preferible; GPG no es obligatorio.

## Snapshot y eventos nuevos

`snapshots/<snapshot_id>.json`: `db_sha256` de la copia congelada, `cutoff_utc`, `event_id`
etiquetados y de train/validation/test (ordenados, sin duplicados, particiones disjuntas, con
su SHA-256), y el modelo base (versión, `base_trained_at` y SHA-256 del `.joblib` y del metadato).

Un intento posterior exige un snapshot genuinamente nuevo: corte posterior, copia distinta,
superconjunto de los eventos previos, **≥ 30 eventos nuevos en validación y ≥ 150 nuevos en
total**. "Nuevo" = no figuró en el conjunto etiquetado de ningún snapshot anterior, en ningún
papel; los eventos reutilizados no cuentan. Si no se cumple, no se permite repetir.

## Test: una sola lectura

`read_held_out_once` es el único acceso: exige un `ELEGIBLE_PRELIMINAR`, rechaza una segunda
lectura del mismo modelo base, escribe `TEST_READ` en el libro **antes** de calcular y
`TEST_RESULT` después. Si el proceso se interrumpe, la lectura queda consumida (no se repite).
Límite honesto: nada impide calcular métricas de test con otro código fuera de este flujo; la
revisión del PR debe comprobar que no ocurrió.

## Manifiesto exacto, sidecar estructurado y `trained_at`

`evaluate_attempt` queda atado al **manifiesto exacto** registrado y aceptado en `main`: el
SHA-256 de sus bytes canónicos debe ser el `manifest_sha256` de `SNAPSHOT_FROZEN`. Para
registrar o verificar `BASE_TRAINED`/`CALIBRATOR_TRAINED` se exige un `models_dir` explícito
(`--models-dir`) y se comprueban el SHA-256 del artefacto y del sidecar `.metadata.json`, la
versión, las métricas del calibrador y que `trained_at` sea **el mismo instante** en el
manifiesto, el libro y el sidecar. No se usa el `mtime` del sistema de archivos. Cualquier
ausencia o discrepancia es `ERROR` o falla cerrado.

## Deserialización de joblib/pickle: no se hace

Un SHA-256 confirma que los bytes son idénticos; **no demuestra seguridad, procedencia,
calidad ni validez estadística**: deserializar un `.joblib`/pickle ejecuta código. El
evaluador **no deserializa** joblib/pickle y no se improvisó un deserializador restringido:
si la evaluación lo necesitara (el veto del test de un `ELEGIBLE_PRELIMINAR`), se detiene con
`SafeLoadRequiredError`, sin escribir nada en el libro. Hará falta un mecanismo de carga
segura **auditado y separado**, más almacenamiento duradero. El entrenamiento y la evaluación
reales siguen **BLOQUEADOS**.

**Deuda registrada, separada de este PR:** los cargadores de producción heredados de los PR #7
y PR #8 (`load_latest_tennis_artifact`, `load_latest_tennis_calibrator`) comparten esa misma
exposición (hash verificado contra el registro, pero se deserializa). No se modificaron aquí.

## Registro candidato aislado

Para calibrar un modelo base aún no promovido sin tocar `config/model_registry.json`:
`candidates/<id>.json` con clave **`candidate_models`** (no `models`) y estado
`CANDIDATE_EVALUATION`. Declara exactamente un modelo base con sus SHA-256, verificados contra
los archivos y contra el libro. Si se copiara a `config/`, el cargador de producción lo
rechazaría todo (falta `models`). Se pasa con `scripts/train_tennis_calibrator.py
--candidate-registry`; sin la opción, el script usa el registro real.

## Fuera de alcance

Entrenamiento, almacenamiento de blobs, promoción y cableado. El entrenamiento permanece
BLOQUEADO hasta que exista almacenamiento duradero y verificable para datasets congelados,
modelos y demás blobs.
