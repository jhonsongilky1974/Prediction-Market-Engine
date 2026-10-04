"""Formato de artefactos de modelo en JSON ESTRICTAMENTE de datos (B1; ver
`SAFE_ARTIFACT_FORMAT_SPEC.md`).

Representa dos objetos ya ajustados como parámetros numéricos, sin ejecutar
código al cargarlos:

* `imputed_standardized_logreg_v1`: `Pipeline(SimpleImputer(median) ->
  StandardScaler -> LogisticRegression)` binario (baseline de tenis).
* `platt_logreg_1d_v1`: `LogisticRegression` de una sola variable (calibrador Platt).

Garantías:

* Este módulo NO importa scikit-learn, numpy, joblib ni pickle, y no usa `eval`, `exec`,
  imports dinámicos ni nombres de módulos o clases leídos del archivo. Ningún valor del
  archivo elige comportamiento: `model_type` solo selecciona una de dos ramas fijas.
* Carga FAIL-CLOSED en este orden: tipo y tamaño de los bytes, SHA-256 contra el valor
  esperado (ANTES de analizar nada), UTF-8 estricto, análisis con controles
  (duplicados, NaN/Infinity, enteros enormes), validación estructural COMPLETA, igualdad
  byte a byte con la serialización canónica y `model_version` esperado. Solo entonces se
  construye un objeto inmutable.
* Representación canónica única: `json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=True, allow_nan=False)` + un único `"\\n"`. El SHA-256 se calcula sobre los
  bytes completos (salto final incluido) y es el `artifact_sha256` que usan hoy el registro
  y el libro; este módulo NO los conecta.
* La API trabaja con BYTES, no con rutas: dónde se guardan los archivos (almacenamiento)
  no se decide aquí.

Límites: el SHA-256 prueba identidad de bytes, no procedencia, calidad ni validez
estadística. Este módulo no entrena, no promueve y no toca `config/model_registry.json`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

SCHEMA_VERSION = 1
MODEL_TYPE_IMPUTED_LOGREG = "imputed_standardized_logreg_v1"
MODEL_TYPE_PLATT = "platt_logreg_1d_v1"
MODEL_TYPES = (MODEL_TYPE_IMPUTED_LOGREG, MODEL_TYPE_PLATT)

MAX_ARTIFACT_BYTES = 262_144
MAX_INPUT_COLUMNS = 256
MAX_ABS_PARAM = 1e6
MAX_NAME_LENGTH = 128
MAX_INT_DIGITS = 20

_ROOT_KEYS = frozenset({"schema_version", "model_type", "model_version", "parameters"})
_IMPUTED_KEYS = frozenset(
    {"input_columns", "imputer_statistics", "scaler_mean", "scaler_scale", "coef", "intercept", "classes"}
)
_PLATT_KEYS = frozenset({"coef", "intercept", "classes"})
_MODEL_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


class SafeArtifactError(Exception):
    """Base de todos los errores de este módulo (fail-closed)."""


class ArtifactHashError(SafeArtifactError):
    """El SHA-256 de los bytes no coincide con el esperado (o el esperado es inválido)."""


class ArtifactFormatError(SafeArtifactError):
    """Bytes inválidos: tipo, tamaño, UTF-8, JSON, duplicados, constantes no finitas o no canónico."""


class ArtifactSchemaError(SafeArtifactError):
    """El documento no cumple el esquema: claves, tipos, cotas, dimensiones o `model_version`."""


class ArtifactInputError(SafeArtifactError):
    """Entrada de predicción inválida o resultado no finito."""


class ArtifactExportError(SafeArtifactError):
    """Un objeto ajustado no se puede exportar (tipo, configuración o atributos no autorizados)."""


# ---------------------------------------------------------------------
# Representación canónica y hash
# ---------------------------------------------------------------------


def artifact_sha256(data: bytes) -> str:
    if type(data) is not bytes:
        raise ArtifactFormatError("el artefacto debe ser exactamente `bytes`")
    return hashlib.sha256(data).hexdigest()


def _serialize(document: Any) -> bytes:
    try:
        text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ArtifactFormatError(f"documento no serializable de forma canónica: {exc!r}") from exc
    return (text + "\n").encode("ascii")


def canonical_bytes(document: Any) -> bytes:
    """Valida el documento contra el esquema y devuelve sus bytes canónicos (siempre cargables: también aplica el
    tope de tamaño). Lanza `ArtifactSchemaError` si no cumple el esquema y `ArtifactFormatError` si excede el tamaño."""
    _validate_document(document)
    data = _serialize(document)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactFormatError(f"documento canónico de {len(data)} bytes: supera el máximo {MAX_ARTIFACT_BYTES}")
    return data


# ---------------------------------------------------------------------
# Validación estructural (antes de construir ningún objeto)
# ---------------------------------------------------------------------


def _fail(message: str) -> None:
    raise ArtifactSchemaError(message)


def _expect_keys(obj: Any, keys: frozenset, where: str) -> None:
    if type(obj) is not dict:
        _fail(f"{where}: se esperaba un objeto JSON")
    if set(obj) != keys:
        missing, extra = sorted(keys - set(obj)), sorted(set(obj) - keys)
        _fail(f"{where}: claves inválidas (faltan {missing}, sobran {extra})")


def _expect_float(value: Any, where: str, *, positive: bool = False) -> float:
    if type(value) is not float:
        _fail(f"{where}: se esperaba un número de coma flotante (JSON con parte decimal o exponente), no {type(value).__name__}")
    if not math.isfinite(value):
        _fail(f"{where}: valor no finito")
    if abs(value) > MAX_ABS_PARAM:
        _fail(f"{where}: |valor| supera el límite {MAX_ABS_PARAM}")
    if positive and not value > 0.0:
        _fail(f"{where}: debe ser estrictamente positivo")
    return value


def _expect_float_list(value: Any, where: str, length: Optional[int] = None, *, positive: bool = False) -> List[float]:
    if type(value) is not list:
        _fail(f"{where}: se esperaba una lista")
    if length is not None and len(value) != length:
        _fail(f"{where}: longitud {len(value)} distinta de la esperada {length}")
    if not value or len(value) > MAX_INPUT_COLUMNS:
        _fail(f"{where}: longitud fuera de rango (1..{MAX_INPUT_COLUMNS})")
    return [_expect_float(v, f"{where}[{i}]", positive=positive) for i, v in enumerate(value)]


def _expect_classes(value: Any, where: str) -> None:
    if type(value) is not list or len(value) != 2 or any(type(c) is not int for c in value) or value != [0, 1]:
        _fail(f"{where}: debe ser exactamente [0, 1]")


def _expect_column_name(value: Any, where: str) -> str:
    if type(value) is not str:
        _fail(f"{where}: se esperaba texto")
    if not 1 <= len(value) <= MAX_NAME_LENGTH or not value.isprintable() or value != value.strip():
        _fail(f"{where}: nombre de columna inválido (1..{MAX_NAME_LENGTH} caracteres imprimibles, sin espacios en los extremos)")
    return value


def _validate_document(document: Any) -> None:
    _expect_keys(document, _ROOT_KEYS, "raíz")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        _fail(f"schema_version debe ser el entero {SCHEMA_VERSION}")
    model_type = document["model_type"]
    if type(model_type) is not str or model_type not in MODEL_TYPES:
        _fail(f"model_type debe estar en la lista cerrada {list(MODEL_TYPES)}")
    model_version = document["model_version"]
    if type(model_version) is not str or _MODEL_VERSION_RE.fullmatch(model_version) is None:
        _fail("model_version inválido")
    params = document["parameters"]
    if model_type == MODEL_TYPE_IMPUTED_LOGREG:
        _validate_imputed_logreg(params)
    else:
        _validate_platt(params)


def _validate_imputed_logreg(params: Any) -> None:
    _expect_keys(params, _IMPUTED_KEYS, "parameters")
    columns = params["input_columns"]
    if type(columns) is not list or not 1 <= len(columns) <= MAX_INPUT_COLUMNS:
        _fail(f"input_columns: lista de 1..{MAX_INPUT_COLUMNS} nombres")
    names = [_expect_column_name(c, f"input_columns[{i}]") for i, c in enumerate(columns)]
    if len(set(names)) != len(names):
        _fail("input_columns: nombres duplicados")
    statistics = params["imputer_statistics"]
    if type(statistics) is not list or len(statistics) != len(names):
        _fail("imputer_statistics: longitud distinta de input_columns")
    n_kept = 0
    for i, value in enumerate(statistics):
        if value is None:
            continue
        _expect_float(value, f"imputer_statistics[{i}]")
        n_kept += 1
    if n_kept < 1:
        _fail("imputer_statistics: al menos una columna debe conservarse (no nula)")
    _expect_float_list(params["scaler_mean"], "scaler_mean", n_kept)
    _expect_float_list(params["scaler_scale"], "scaler_scale", n_kept, positive=True)
    _expect_float_list(params["coef"], "coef", n_kept)
    _expect_float(params["intercept"], "intercept")
    _expect_classes(params["classes"], "classes")


def _validate_platt(params: Any) -> None:
    _expect_keys(params, _PLATT_KEYS, "parameters")
    _expect_float(params["coef"], "coef")
    _expect_float(params["intercept"], "intercept")
    _expect_classes(params["classes"], "classes")


# ---------------------------------------------------------------------
# Predictores puros
# ---------------------------------------------------------------------


def _sigmoid(z: float) -> float:
    """Sigmoide estable (no desborda para |z| grande)."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactInputError(f"{where}: se esperaba un número, no {type(value).__name__}")
    try:
        converted = float(value)
    except OverflowError as exc:  # un `int` de Python más grande que cualquier float
        raise ArtifactInputError(f"{where}: número fuera del rango de coma flotante") from exc
    if math.isinf(converted):
        raise ArtifactInputError(f"{where}: valor infinito")
    return converted


@dataclass(frozen=True)
class ImputedLogRegModel:
    """`Pipeline(imputer mediana -> escalador -> regresión logística)` ya ajustado, como datos."""

    model_version: str
    input_columns: Tuple[str, ...]
    statistics: Tuple[Optional[float], ...]
    mean: Tuple[float, ...]
    scale: Tuple[float, ...]
    coef: Tuple[float, ...]
    intercept: float

    def predict_proba_vector(self, values: Union[List[Any], Tuple[Any, ...]]) -> float:
        """P(clase 1) para un vector en el orden de `input_columns` (NaN = valor faltante). Acepta solo `list` o
        `tuple` (no otras secuencias ni arreglos): cualquier otro tipo lanza `ArtifactInputError`."""
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
            raise ArtifactInputError("values debe ser una lista o tupla de números")
        if len(values) != len(self.input_columns):
            raise ArtifactInputError(f"se esperaban {len(self.input_columns)} valores, llegaron {len(values)}")
        terms: List[float] = []
        k = 0
        for column, statistic, value in zip(self.input_columns, self.statistics, values):
            number = _number(value, column)
            if statistic is None:
                continue  # columna descartada en el ajuste: no influye
            if math.isnan(number):
                number = statistic
            terms.append(((number - self.mean[k]) / self.scale[k]) * self.coef[k])
            k += 1
        z = sum(terms) + self.intercept
        if not math.isfinite(z):
            raise ArtifactInputError("el logit no es finito")
        return _sigmoid(z)

    def predict_proba_row(self, row: Mapping[str, Any]) -> float:
        """Como `_predict_proba_from_vectorized_features`: se lee por nombre y una columna ausente es NaN."""
        if not isinstance(row, Mapping):
            raise ArtifactInputError("row debe ser un mapeo nombre -> número")
        return self.predict_proba_vector([row.get(column, float("nan")) for column in self.input_columns])


@dataclass(frozen=True)
class PlattModel:
    """Calibrador Platt (regresión logística de 1 variable) ya ajustado, como datos."""

    model_version: str
    coef: float
    intercept: float

    def calibrate(self, p_raw: float) -> float:
        if isinstance(p_raw, bool) or not isinstance(p_raw, (int, float)):
            raise ArtifactInputError("p_raw debe ser un número")
        try:
            value = float(p_raw)
        except OverflowError as exc:  # un `int` de Python más grande que cualquier float
            raise ArtifactInputError("p_raw fuera del rango de coma flotante") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ArtifactInputError("p_raw debe ser finito y estar en [0, 1]")
        return _sigmoid(self.coef * value + self.intercept)


LoadedModel = Union[ImputedLogRegModel, PlattModel]


def _build(document: Dict[str, Any]) -> LoadedModel:
    params = document["parameters"]
    if document["model_type"] == MODEL_TYPE_IMPUTED_LOGREG:
        return ImputedLogRegModel(
            model_version=document["model_version"],
            input_columns=tuple(params["input_columns"]),
            statistics=tuple(params["imputer_statistics"]),
            mean=tuple(params["scaler_mean"]),
            scale=tuple(params["scaler_scale"]),
            coef=tuple(params["coef"]),
            intercept=params["intercept"],
        )
    return PlattModel(model_version=document["model_version"], coef=params["coef"], intercept=params["intercept"])


# ---------------------------------------------------------------------
# Carga segura
# ---------------------------------------------------------------------


def _reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactFormatError(f"clave duplicada: {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ArtifactFormatError(f"constante no permitida: {name}")


def _strict_int(token: str) -> int:
    if len(token.lstrip("-")) > MAX_INT_DIGITS:
        raise ArtifactFormatError("entero con demasiados dígitos")
    return int(token)


def _strict_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ArtifactFormatError("número fuera del rango de coma flotante")
    return value


def load_artifact(data: bytes, *, expected_sha256: str, expected_model_version: str) -> LoadedModel:
    """Carga un artefacto JSON de solo datos. FAIL-CLOSED: cualquier fallo lanza una subclase de
    `SafeArtifactError`. `expected_sha256` y `expected_model_version` son obligatorios: el hash se
    comprueba ANTES de analizar los bytes."""
    if type(data) is not bytes:
        raise ArtifactFormatError("el artefacto debe ser exactamente `bytes`")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactFormatError(f"artefacto de {len(data)} bytes: supera el máximo {MAX_ARTIFACT_BYTES}")
    if type(expected_sha256) is not str or _HEX64_RE.fullmatch(expected_sha256) is None:
        raise ArtifactHashError("expected_sha256 debe ser un SHA-256 hexadecimal en minúsculas (64 caracteres)")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest().encode("ascii"), expected_sha256.encode("ascii")):
        raise ArtifactHashError("el SHA-256 del artefacto no coincide con el esperado")
    if type(expected_model_version) is not str or _MODEL_VERSION_RE.fullmatch(expected_model_version) is None:
        raise ArtifactSchemaError("expected_model_version inválido")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactFormatError(f"UTF-8 inválido: {exc}") from exc
    if text.startswith("\ufeff"):
        raise ArtifactFormatError("el artefacto no puede llevar BOM")
    if not text.endswith("\n") or "\n" in text[:-1] or "\r" in text:
        raise ArtifactFormatError("se exige un único salto de línea final (LF) y ningún otro")

    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
            parse_int=_strict_int,
            parse_float=_strict_float,
        )
    except SafeArtifactError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ArtifactFormatError(f"JSON inválido: {exc}") from exc

    _validate_document(document)
    if _serialize(document) != data:
        raise ArtifactFormatError("el artefacto no está en forma canónica (bytes distintos de su serialización canónica)")
    if document["model_version"] != expected_model_version:
        raise ArtifactSchemaError("model_version distinto del esperado")
    return _build(document)
