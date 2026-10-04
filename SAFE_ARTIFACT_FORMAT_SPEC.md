# Formato de artefactos de modelo en JSON de solo datos (B1)

Especificación normativa de `src/models/safe_artifact_format.py` (cargador, validador y predictor) y
`src/models/safe_artifact_export.py` (exportadores desde scikit-learn). **Solo define el formato y su
verificación.** No cambia ningún entrenamiento, cargador heredado, registro ni flujo de producción, no
genera artefactos reales y no decide almacenamiento duradero, migración, `REJECTED_CANDIDATE` ni promoción.
Tampoco hace alcanzable `ELEGIBLE` ni desbloquea el entrenamiento o el Tramo 5A.

## 1. Objetivo

Representar como JSON de parámetros numéricos dos objetos ya ajustados, de modo que **cargarlos no ejecute
código**:

- `imputed_standardized_logreg_v1`: `Pipeline(SimpleImputer(median) -> StandardScaler -> LogisticRegression)`
  binario (baseline de tenis).
- `platt_logreg_1d_v1`: `LogisticRegression` de una sola variable (calibrador Platt).

La predicción es una fórmula cerrada en Python puro. El módulo seguro no importa scikit-learn, numpy, joblib
ni pickle (lo comprueba una prueba de AST y una prueba con esos módulos bloqueados).

## 2. Esquema

Raíz (claves exactas, todas obligatorias, ninguna extra): `schema_version` (entero `1`), `model_type` (lista
cerrada), `model_version` (`[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`), `parameters`.

`imputed_standardized_logreg_v1`, en `parameters`:

| Clave | Tipo y regla |
|---|---|
| `input_columns` | lista de 1–256 textos únicos, 1–128 caracteres imprimibles, sin espacios en los extremos (admite espacios y Unicode: las categorías de ronda son texto libre) |
| `imputer_statistics` | lista de la misma longitud: flotante finito, o `null` si la columna se descartó en el ajuste (todo NaN; `keep_empty_features=False`) |
| `scaler_mean`, `scaler_scale`, `coef` | listas de flotantes finitos de longitud `n_kept` (columnas no nulas, mínimo 1); `scaler_scale` estrictamente positivo |
| `intercept` | flotante finito |
| `classes` | exactamente `[0, 1]` (enteros) |

`platt_logreg_1d_v1`, en `parameters`: `coef` (flotante), `intercept` (flotante), `classes` (`[0, 1]`).

Cotas: archivo ≤ 262 144 bytes; ≤ 256 columnas; todo número con |valor| ≤ 1e6 (`scaler_scale` en (0, 1e6]).
Tipos exactos: un entero donde va un flotante, un `bool`, un `null` (salvo en `imputer_statistics`) o un texto
numérico se rechazan.

## 3. Representación canónica

`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` seguido de **un único**
`\n`: ASCII (UTF-8 válido), sin BOM ni CR, claves ordenadas, floats en la representación más corta con ida y
vuelta exacta (se conserva `-0.0`), sin `NaN`/`Infinity`. El cargador exige que los bytes de entrada sean
**idénticos** a la serialización canónica del documento validado, de modo que cada artefacto tiene una única
forma válida. El hash es `SHA-256` hexadecimal en minúsculas sobre los bytes completos (salto final incluido);
es el `artifact_sha256` con la semántica actual del registro y del libro, que esta especificación no conecta. `canonical_bytes` aplica además el tope de tamaño, de modo que solo devuelve bytes cargables.

## 4. Carga segura (orden estricto, fail-closed)

1. Los bytes deben ser exactamente `bytes` y medir ≤ 262 144.
2. SHA-256 contra `expected_sha256` (obligatorio, comparación en tiempo constante), **antes de analizar nada**.
3. UTF-8 estricto, sin BOM, un único `\n` final y ningún otro, sin CR.
4. `json.loads` con controles: claves duplicadas, `NaN`/`Infinity`, enteros de más de 20 dígitos y flotantes no
   finitos se rechazan; `RecursionError` y `ValueError` se convierten en `ArtifactFormatError`.
5. Validación estructural completa (claves, tipos, cotas, dimensiones, lista cerrada de `model_type`).
6. Igualdad byte a byte con la serialización canónica.
7. `model_version` igual a `expected_model_version` (obligatorio).
8. Solo entonces se construye un objeto inmutable (`dataclass` congelada con tuplas).

No hay `pickle`, `joblib`, `eval`, `exec`, imports dinámicos, `getattr` sobre datos ni nombres de módulos o
clases leídos del archivo: `model_type` solo elige una de dos ramas fijas del código.

## 5. Predicción

Modelo de tenis: se sustituyen los NaN por la estadística de la columna, se omiten las columnas descartadas, se
estandariza y se aplica `z = Σ ((x − media) / escala) · coef + intercepto` (suma secuencial en el orden de los
índices) y una sigmoide estable de dos ramas. `predict_proba_row` lee por nombre y trata una columna ausente
como NaN, igual que `_predict_proba_from_vectorized_features`; rechaza `inf`, `bool`, texto y resultados no
finitos (como scikit-learn rechaza `inf`). Platt: `sigmoide(coef · p_raw + intercepto)`; `p_raw` debe ser finito
y estar en [0, 1] (más estricto que scikit-learn, que extrapolaría).

## 6. Exportadores

Reciben **objetos ya ajustados en memoria**; no leen archivos, no usan joblib ni pickle, no escriben nada y
devuelven bytes canónicos. scikit-learn se importa de forma perezosa dentro de cada función. Solo aceptan tipos
**exactos** (no subclases): `Pipeline` con los pasos `imputer`, `scaler`, `logreg` en ese orden;
`SimpleImputer(median, missing_values=NaN, add_indicator=False, keep_empty_features=False, fill_value=None)`;
`StandardScaler(with_mean=True, with_std=True)`; `LogisticRegression` binaria con `fit_intercept=True` y
`classes_ == [0, 1]`; atributos `float64` finitos y de forma coherente. Antes de devolver, comprueban que
`load_artifact` acepta exactamente esos bytes. Ningún `__init__`, flujo, entrenamiento, evaluación o cargador
heredado los invoca: no están cableados a nada.

## 7. Paridad con scikit-learn

Diferencia absoluta máxima ≤ 1e-12 en `predict_proba[:, 1]` frente al objeto ajustado, sobre escenarios con
semilla fija: columna siempre vacía, columna constante, una sola columna, hasta 256 columnas, entradas extremas
y logits saturados; y con el pipeline real de tenis entrenado sobre eventos sintéticos en `tmp_path`.

## 8. Amenazas

Cubiertas: ejecución de código al cargar; alteración de bytes; maleabilidad de la representación; denegación
por parser (tamaño, profundidad, enteros enormes, duplicados); valores no finitos, dimensiones incoherentes y
confusión de tipos; intercambio de archivos (`expected_model_version`); entradas no finitas en la predicción.

No cubiertas: procedencia, calidad y validez estadística; la raíz de confianza del hash esperado (si quien
controla `main` altera el registro o el libro, esto no lo detecta); parámetros maliciosos pero válidos con un
hash legítimamente registrado; cambios semánticos de futuras versiones de scikit-learn (solo se detectan al
ejecutar las pruebas de paridad con la versión instalada; rango declarado `scikit-learn>=1.3,<1.7`); defectos
del analizador `json` de CPython; otras familias de modelos; almacenamiento y disponibilidad de los archivos.

## 9. Fuera de alcance

Almacenamiento duradero, migración de cargadores y de scripts de entrenamiento, entrenamiento, `--db-path` y
congelado de copias, CLI del manifiesto, proveedor de métricas del test, MLB, registro de producción, cableado
y promoción. Estas decisiones siguen abiertas.
