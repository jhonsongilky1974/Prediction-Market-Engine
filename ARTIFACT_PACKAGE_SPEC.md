# Paquete de artefacto de modelo: metadatos y manifiesto (PR-2)

Especificación normativa de `src/models/artifact_package.py`. **Solo define el formato de dos documentos nuevos y la
verificación de un paquete de tres blobs.** No cambia ningún entrenamiento, cargador heredado, registro, libro ni flujo
de producción; no genera paquetes reales; no promueve; y **un paquete válido no es un modelo `ALLOWED`**. Tampoco hace
alcanzable `ELEGIBLE` ni desbloquea el entrenamiento o el Tramo 5A. Las decisiones que la fundamentan están en
`ARTIFACT_STORAGE_DECISION.md` (D4, D6, D12 y D20).

## 1. Objetivo y alcance

Un **paquete** son tres blobs del almacén (`ArtifactStore`), cada uno identificado por su clave:

1. el **artefacto**: un documento B1 (`SAFE_ARTIFACT_FORMAT_SPEC.md`), uno de los dos `model_type` seguros
   (`imputed_standardized_logreg_v1` o `platt_logreg_1d_v1`). MLB queda fuera;
2. los **metadatos** (`model_artifact_metadata`): procedencia, código, datos, entrenamiento y límites del artefacto;
3. el **manifiesto de paquete** (`artifact_package_manifest`): enlaza la clave del artefacto con la de los metadatos
   y fija sus versiones de esquema. **No es** el manifiesto de instantánea del libro (`governance/calibration/`) ni el
   `PolicyManifest` de `config/policy/`.

Este módulo define la forma canónica de los dos documentos nuevos, la valida de forma estricta (fail-closed) y verifica
la integridad y la coherencia de los tres blobs leídos a través de un `ArtifactReader`. No escribe en el almacén.

## 2. Claves y hashes (D4)

- Una **clave del almacén** es la cadena de 64 hexadecimales en minúsculas que acepta `validate_key`; es el SHA-256 de
  los bytes del blob. Los campos llamados `key` o `*_key` la contienen y se validan con `validate_key`.
- La disposición interna del backend local (`sha256/<2 hex>/<64 hex>`) no es una clave: no aparece en ningún documento
  ni en la API, y `validate_key` la rechaza. Ningún consumidor entrega una ruta.
- Un campo llamado `*_sha256` contendría exactamente 64 hexadecimales en minúsculas, el SHA-256 de unos bytes
  cualesquiera que no tienen por qué ser un blob del almacén. La versión 1 no define ningún campo `*_sha256`.
- Una clave inválida como ARGUMENTO (`manifest_key`, `expected_key`) lanza `InvalidArtifactKeyError`; una clave inválida
  DENTRO de un documento es un `PackageSchemaError`.

## 3. Forma canónica

`json.dumps(documento, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` seguido de **un único**
`\n`: ASCII, sin BOM ni CR, claves ordenadas, sin espacios. El cargador exige que los bytes de entrada sean **idénticos**
a la serialización canónica del documento validado. La clave del blob es el SHA-256 de los bytes completos (salto final
incluido).

La versión 1 **no admite números de coma flotante** en ningún lugar: los enteros son `int` exactos (no `bool`) y de
como máximo 10 dígitos en la carga. Los demás tipos son exactos: no se aceptan subclases ni tuplas donde va una lista.

Límites: `MAX_METADATA_BYTES = 65536` y `MAX_PACKAGE_MANIFEST_BYTES = 4096`, sobre los bytes canónicos.

Orden de carga, fail-closed: tipo `bytes` exacto y tamaño; clave esperada válida; SHA-256 contra la clave **antes de
analizar nada**; UTF-8 estricto sin BOM; un único LF final y ningún otro, sin CR; análisis JSON con controles
(claves duplicadas, `NaN` e `Infinity`, floats y enteros de más de 10 dígitos, y exceso de anidamiento se rechazan);
validación estructural completa; igualdad byte a byte con la forma canónica.

## 4. Metadatos v1 (`model_artifact_metadata`)

Claves exactas: ninguna extra y ninguna ausente. `training` existe solo en un modelo base y `base_model_ref` solo en un
calibrador (el tipo lo fija `model_type`).

| Campo | Regla |
|---|---|
| `schema_version` | entero `1` |
| `document_type` | `"model_artifact_metadata"` |
| `model_version` | `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}` |
| `model_type` | `imputed_standardized_logreg_v1` (modelo base) o `platt_logreg_1d_v1` (calibrador) |
| `trained_at` | UTC con `Z`: `YYYY-MM-DDTHH:MM:SS` y fracción opcional de 1 a 6 dígitos, seguido de `Z`; fecha y hora reales |
| `base_model_ref` | **solo calibrador, obligatorio**: `{model_version, package_manifest_key}`; la clave se valida con `validate_key`; un calibrador no puede referenciarse a sí mismo (mismo `model_version`). **Prohibido** en un modelo base |
| `provenance.git_commit` | 40 hexadecimales en minúsculas |
| `provenance.git_tree_clean` | `bool` exacto. Es un dato: este módulo no decide elegibilidad |
| `provenance.entrypoint` | ruta relativa al repositorio: `[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}`, sin componentes vacíos, `.` ni `..`, sin `/` inicial, sin `\`, sin `:` (por tanto sin forma absoluta de Windows) |
| `provenance.environment` | `{python, scikit_learn}`, cada uno `[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}` |
| `data.dataset_manifest_ref` | `{key, schema_version}`: `key` con `validate_key`; `schema_version` entero de 1 a 1000000 |
| `training.feature_columns` | **solo modelo base, obligatorio**: lista única de 1 a 256 nombres de 1 a 128 caracteres imprimibles, sin espacios en los extremos. **Prohibido** en un calibrador |
| `limits.intended_use` | texto de 1 a 500 caracteres |
| `limits.known_limitations` | lista de 1 a 20 textos de 1 a 300 caracteres |

Texto de prosa (`intended_use` y cada limitación): imprimible, en una línea, sin espacios en los extremos, y **no puede
comenzar** con `/`, `~`, `\` ni con una unidad de Windows (`C:\`, `C:/`).

**Aplazado a `schema_version` 2 (fuera de la versión 1):** la sección `validation`, `partition_counts`,
`partition_time_ranges`, los hashes de las listas de eventos, `db_sha256`, `prereg_id`, `data.cutoff_utc`, los
hiperparámetros y mínimos de política, `feature_set_version`, `training_dataset_spec_version`, `round_categories`,
`limits.not_validated_for`, y `role`, `sport` y `algorithm` (derivables de `model_type`).

## 5. Manifiesto de paquete v1 (`artifact_package_manifest`)

| Campo | Regla |
|---|---|
| `schema_version` | entero `1` |
| `document_type` | `"artifact_package_manifest"` |
| `model_version` | igual que en los metadatos y en el artefacto |
| `artifact.key` | clave del almacén del artefacto (`validate_key`) |
| `artifact.format` | `"safe_json_b1"` |
| `artifact.schema_version` | el `SCHEMA_VERSION` de B1 (hoy `1`) |
| `artifact.model_type` | uno de los `model_type` de B1 |
| `metadata.key` | clave del almacén de los metadatos (`validate_key`); distinta de `artifact.key` |
| `metadata.schema_version` | entero `1` |

Sin marcas de tiempo, para que la clave del manifiesto dependa solo de su contenido.

## 6. Reglas de contenido (D6 y D12)

- **Claves prohibidas**, en cualquier nivel y también dentro de listas, con el mensaje «clave prohibida»: las que
  terminan en `event_id` o `event_ids`; las que contienen `path` (incluidas `file_path` y `artifact_path`); `status` y
  `candidate_status`; y las que empiezan por `test` o `baseline_test`. El estado de un modelo vive solo en el registro,
  y las métricas del test solo en el libro.
- **Nunca** hay listas completas de `event_id` ni resultados por `event_id` en estos documentos: la lista completa queda
  en el manifiesto de instantánea, un blob protegido. Los hashes de esas listas aportan integridad, no confidencialidad.
- **Límite honesto:** el rechazo de valores de prosa que comienzan como rutas absolutas o con `~` **no detecta rutas
  incrustadas a mitad de frase** ni sustituye una revisión humana antes de publicar.

## 7. Verificación: `verify_package(reader, manifest_key, *, expected_model_version)`

Solo lee a través de un `ArtifactReader` y nunca llama a `put`. Orden fail-closed:

1. `manifest_key` válida (`validate_key`) y `expected_model_version` válido, antes de leer nada;
2. lectura del manifiesto (el almacén verifica su hash) y carga con los controles del apartado 3;
3. `model_version` del manifiesto igual al esperado (`PackageConsistencyError`);
4. lectura del artefacto y carga con B1 (`load_artifact`, con su clave como hash esperado y el `model_version` esperado);
   un rechazo de B1 se envuelve como `PackageArtifactError`, con su causa en `__cause__`;
5. el tipo del modelo cargado coincide con `artifact.model_type` (`PackageConsistencyError`);
6. lectura de los metadatos y carga con los controles del apartado 3;
7. coherencia: mismo `model_version` y mismo `model_type` que el manifiesto; en un modelo base, `training.feature_columns`
   igual a `input_columns` del artefacto, en valor y en orden; y en un calibrador, que `base_model_ref.package_manifest_key`
   no sea la clave del propio manifiesto (`PackageConsistencyError`). Esta última comprobación no lee ni resuelve el
   paquete base.

Devuelve un `VerifiedPackage` inmutable (`manifest_key`, `manifest`, `metadata`, `model`). **No es un estado `ALLOWED`**: no
consulta el registro, no activa ningún modelo y no decide nada sobre su calidad.

## 8. Qué se verifica y qué se aplaza

| Verificación | PR-2 | Se aplaza a |
|---|---|---|
| Forma canónica, límites, tipos y claves exactas de los dos documentos | Sí | — |
| Hash antes de analizar; clave verificada por el almacén | Sí | — |
| El artefacto carga bajo B1 con su hash y su `model_version` | Sí | — |
| Coherencia artefacto–metadatos–manifiesto | Sí | — |
| `base_model_ref`: formato, presencia solo en un calibrador, no autorreferencia directa (mismo `model_version`) ni por clave (la del propio manifiesto) | Sí | — |
| `base_model_ref`: que el manifiesto base exista, verifique como paquete, tenga el `model_version` declarado, sea un modelo base y esté aprobado; ciclos | **No** | PR-3 (registro) y PR-4 (cargadores) |
| `dataset_manifest_ref`: formato de `key` y de `schema_version`, **sin leer el blob** | Sí | — |
| Resolución del manifiesto de instantánea desde el libro (`SNAPSHOT_FROZEN` por `manifest_key`): PR-5 valida el contenido del manifiesto al resolverlo (existencia del blob, formato y versión de esquema, límite de tamaño, hashes de las listas y `snapshot_id` del propio manifiesto) | **No** | PR-5 |
| Construcción y publicación del manifiesto de instantánea (congelado de datos y herramienta del manifiesto) | No | PR-6 (alcance documentado en `ARTIFACT_STORAGE_DECISION.md` §8, sin cambios) |
| `dataset_manifest_ref` comprobado desde un paquete: existencia del blob, formato y versión de esquema esperados, hashes de las listas y `snapshot_id`, y que la clave concuerde con el manifiesto registrado en el libro. PR-5 valida ese contenido al resolver el manifiesto desde el libro, pero no lo comprueba a partir del `dataset_manifest_ref` de un paquete | **No** | Fuera de PR-5. **Aplazada** |
| Verificación de paquetes de base y calibrador por el libro (referencias de paquetes) | No | **Aplazada** |
| Cruce de las métricas de validación del calibrador con el artefacto | No | **Aplazada** |
| Coherencia de `trained_at` entre los metadatos de un paquete y el libro | No | **Aplazada** |
| Existencia de `git_commit` en el repositorio | No | **Aplazada** |
| Estado en el registro y referencias desde el libro | No | **Aplazada** |
| Que los entrenadores produzcan estos documentos | No | PR-7 |

La autorreferencia se rechaza por dos vías. Por `model_version`, al cargar los metadatos (`PackageSchemaError`). Por clave
(que `base_model_ref.package_manifest_key` sea la clave del propio manifiesto), en `verify_package`
(`PackageConsistencyError`), que es el único lugar donde se conoce esa clave. Esta segunda comprobación es **defensa en
profundidad**. Construirla exigiría encontrar un punto fijo de la composición de hashes, lo que se considera
computacionalmente inviable. Por eso las pruebas la ejercitan simulando la igualdad.

### Dependencias de lo aplazado

Cada comprobación aplazada depende de cosas distintas. **De todas ellas, solo la de métricas requiere el esquema v2 de metadatos.** Las filas «Aplazada» no tienen asignado ningún trabajo concreto ni fecha.

- **`dataset_manifest_ref` desde un paquete.** Depende de que los paquetes pasen por la verificación del libro (siguiente punto) y de definir cómo se compara su `key` con el manifiesto registrado en el libro. No requiere el esquema v2.
- **Paquetes de base y calibrador.** Depende de cambiar el esquema de `BASE_TRAINED` y `CALIBRATOR_TRAINED` (hoy con `*_artifact_sha256` y `*_metadata_sha256` del artefacto y del sidecar heredados), que PR-5 no toca, y de adaptar `src/evaluation/candidate_registry.py`, que casa esos campos. No requiere el esquema v2.
- **Métricas.** Es la única que requiere el esquema v2: los metadatos v1 no tienen la sección `validation`, aplazada a `schema_version` 2 (§4), y hoy `CALIBRATOR_TRAINED` cruza las métricas con el sidecar heredado.
- **`trained_at`.** Los metadatos v1 ya incluyen `trained_at`. Depende de que los paquetes pasen por la verificación del libro. No requiere el esquema v2. La comprobación actual contra el sidecar heredado se conserva.
- **`git_commit`.** Los metadatos v1 ya incluyen `provenance.git_commit`. Depende de lo mismo, de definir qué significa «existe» (cualquier objeto del repositorio o ancestro de `main`) y de que `git` esté disponible donde se verifica. No requiere el esquema v2.
- **Estado en el registro.** No requiere el esquema v2. Un candidato se evalúa antes de promoverse, así que no figura `ALLOWED` al evaluarse, y ningún documento define todavía qué referencia concreta enlaza una entrada del libro con una del registro v2. Depende de los pendientes de D8 (requisitos de la referencia del calibrador) y de que `ELEGIBLE` sea alcanzable (D21). La forma y la selección del registro v2 ya se validan (PR-3).

### Registro real de un `SNAPSHOT_FROZEN`

La resolución del manifiesto desde el libro (PR-5) no autoriza registrar ningún `SNAPSHOT_FROZEN` real. Los requisitos propuestos para un registro real son **propuestas, no reglas aprobadas**, y figuran en `ARTIFACT_STORAGE_DECISION.md` §8.1.

## 9. Errores

`ArtifactPackageError` es la base de `PackageFormatError` (bytes, hash, UTF-8, JSON, forma canónica), `PackageSchemaError`
(esquema, claves, cotas, claves prohibidas, claves inválidas dentro de un documento), `PackageConsistencyError` (los tres
blobs no son coherentes entre sí) y `PackageArtifactError` (B1 rechazó el artefacto; la causa queda en `__cause__`).

Los errores del almacén (`ArtifactStoreError` y derivados) **se propagan sin envolver**: un fallo de configuración del
almacén nunca se disfraza de problema del paquete, y una `manifest_key` inválida lanza `InvalidArtifactKeyError`. Los errores
de B1 no son errores del almacén y se envuelven.

## 10. Vectores canónicos

Cada vector es el documento en su forma canónica (una sola línea; en el archivo va seguido de un único `\n`) y su clave
del almacén. Las pruebas comprueban que esta especificación contiene cada vector, y que el código los reproduce.

### A1. Artefacto B1 del modelo base (`imputed_standardized_logreg_v1`)

```text
{"model_type":"imputed_standardized_logreg_v1","model_version":"pkg_example_v1","parameters":{"classes":[0,1],"coef":[0.5,-0.25],"imputer_statistics":[3.0,null,0.0],"input_columns":["rest_days.participant_a","rest_days.participant_b","tournament_round.Final"],"intercept":0.1,"scaler_mean":[2.5,0.2],"scaler_scale":[1.5,0.4]},"schema_version":1}
```

Clave del almacén: `34b65f82c62b24aba4b48b5cfeb20fdfe9292a330061853015a0867df2f871e0`

### M1. Metadatos del modelo base

```text
{"data":{"dataset_manifest_ref":{"key":"42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067","schema_version":1}},"document_type":"model_artifact_metadata","limits":{"intended_use":"Vector de ejemplo de documentacion: no es un modelo real.","known_limitations":["Ejemplo sintetico; no representa ningun entrenamiento."]},"model_type":"imputed_standardized_logreg_v1","model_version":"pkg_example_v1","provenance":{"entrypoint":"scripts/example_trainer.py","environment":{"python":"3.9.6","scikit_learn":"1.6.1"},"git_commit":"1234567890abcdef1234567890abcdef12345678","git_tree_clean":true},"schema_version":1,"trained_at":"2026-11-21T20:00:00Z","training":{"feature_columns":["rest_days.participant_a","rest_days.participant_b","tournament_round.Final"]}}
```

Clave del almacén: `98f38d38ae1a54d484e36886fc6a58840c828c5fb1995538eceba91c8d958ec6`

### F1. Manifiesto de paquete del modelo base

```text
{"artifact":{"format":"safe_json_b1","key":"34b65f82c62b24aba4b48b5cfeb20fdfe9292a330061853015a0867df2f871e0","model_type":"imputed_standardized_logreg_v1","schema_version":1},"document_type":"artifact_package_manifest","metadata":{"key":"98f38d38ae1a54d484e36886fc6a58840c828c5fb1995538eceba91c8d958ec6","schema_version":1},"model_version":"pkg_example_v1","schema_version":1}
```

Clave del almacén: `11254d6d22e7a1bb60d1d0f72b0d5c291be5dcc54b691b702560d318ec86d876`

### A2. Artefacto B1 del calibrador (`platt_logreg_1d_v1`)

```text
{"model_type":"platt_logreg_1d_v1","model_version":"pkg_calibrator_v1","parameters":{"classes":[0,1],"coef":1.2,"intercept":-0.6},"schema_version":1}
```

Clave del almacén: `9f6b88c174cad856144ad5cffd1e2eb66358907f074138aa6bc1336aa2c93bc3`

### M2. Metadatos del calibrador (con `base_model_ref` hacia `F1`, solo con formato)

```text
{"base_model_ref":{"model_version":"pkg_example_v1","package_manifest_key":"11254d6d22e7a1bb60d1d0f72b0d5c291be5dcc54b691b702560d318ec86d876"},"data":{"dataset_manifest_ref":{"key":"42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067","schema_version":1}},"document_type":"model_artifact_metadata","limits":{"intended_use":"Vector de ejemplo de un calibrador: no es un modelo real.","known_limitations":["Ejemplo sintetico.","Referencia al modelo base solo con formato, sin resolver."]},"model_type":"platt_logreg_1d_v1","model_version":"pkg_calibrator_v1","provenance":{"entrypoint":"scripts/example_calibrator.py","environment":{"python":"3.9.6","scikit_learn":"1.6.1"},"git_commit":"1234567890abcdef1234567890abcdef12345678","git_tree_clean":true},"schema_version":1,"trained_at":"2026-11-21T20:00:00.123456Z"}
```

Clave del almacén: `a4a1ffe736b2075f996b69e10a4e7a9959cd02d6ab74a85ce78354016c08621e`

### F2. Manifiesto de paquete del calibrador

```text
{"artifact":{"format":"safe_json_b1","key":"9f6b88c174cad856144ad5cffd1e2eb66358907f074138aa6bc1336aa2c93bc3","model_type":"platt_logreg_1d_v1","schema_version":1},"document_type":"artifact_package_manifest","metadata":{"key":"a4a1ffe736b2075f996b69e10a4e7a9959cd02d6ab74a85ce78354016c08621e","schema_version":1},"model_version":"pkg_calibrator_v1","schema_version":1}
```

Clave del almacén: `9c445d5c29d9860fc140c9af450d811c9cc3d23f8d11e2fb38ace67a1ebf2684`

### Referencia de datos de los vectores

`dataset_manifest_ref.key` de los metadatos es el SHA-256 de los bytes `dataset-manifest-example`: `42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067`. Ese blob no se publica ni se lee: solo se valida el formato de la clave.


## 11. Amenazas

Cubiertas: ejecución de código al cargar (los documentos son JSON de solo datos y el módulo no importa deserializadores ni
bibliotecas numéricas); alteración de bytes; maleabilidad de la representación; denegación por el analizador (tamaño,
profundidad, enteros enormes, duplicados, floats); intercambio de metadatos o de artefacto entre paquetes; incoherencia entre
los tres blobs; y filtración por claves que nombran rutas, estados, resultados del test o listas de eventos.

No cubiertas: procedencia, calidad y validez estadística; la raíz de confianza (quien controla `main` o el registro);
parámetros maliciosos pero válidos con un hash legítimamente registrado; que `git_commit` o `environment` digan la verdad;
rutas incrustadas en la prosa; y la disponibilidad y la durabilidad de los blobs.

## 12. Fuera de alcance

Entrenadores, cargadores, registro, libro, evaluador y su cableado; el manifiesto de instantánea como blob; la resolución
de `base_model_ref` y de `dataset_manifest_ref`; las model cards de producción (solo existe la plantilla
`governance/models/MODEL_CARD_TEMPLATE.md`); MLB; y cualquier decisión de elegibilidad, aprobación o promoción. El
entrenamiento y el Tramo 5A siguen bloqueados.
