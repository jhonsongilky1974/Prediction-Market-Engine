"""Paquete de artefacto de modelo: metadatos canónicos, manifiesto de paquete y su verificación (PR-2; ver
`ARTIFACT_PACKAGE_SPEC.md` y `ARTIFACT_STORAGE_DECISION.md`, D4, D6, D12 y D20).

Un PAQUETE son tres blobs del almacén, identificados cada uno por su clave (D4: 64 hexadecimales en minúsculas,
validada con `validate_key`):

* el ARTEFACTO: un documento B1 (`safe_artifact_format`);
* los METADATOS (`model_artifact_metadata`): procedencia, código, datos, entrenamiento y límites;
* el MANIFIESTO DE PAQUETE (`artifact_package_manifest`): enlaza la clave del artefacto con la de los metadatos y
  fija sus versiones de esquema. No es el manifiesto de instantánea del libro ni el `PolicyManifest`.

Qué hace este módulo: define la forma canónica de los dos documentos nuevos, la valida de forma estricta
(fail-closed) y verifica la integridad y la coherencia de los tres blobs leídos a través de un `ArtifactReader`.

Qué NO hace: un paquete válido NO es un modelo `ALLOWED` ni activable (el registro es la única vía de promoción);
no resuelve `base_model_ref` ni `dataset_manifest_ref` (solo valida su formato, sin leer los blobs referenciados:
existencia, ciclos y aprobación se aplazan); no entrena, no publica, no escribe en el almacén (solo lee) y no se
conecta a entrenadores, cargadores, registro, libro ni evaluador. No decide elegibilidad: `git_tree_clean` es un dato.

Errores: los del almacén (`ArtifactStoreError` y derivados) se PROPAGAN sin envolver, también el de una clave de
argumento inválida (`InvalidArtifactKeyError`); los errores de B1 se envuelven como `PackageArtifactError`
conservando su causa; una clave inválida DENTRO de un documento es un `PackageSchemaError`.

Límites: el hash prueba identidad de bytes, no procedencia, calidad ni validez estadística. Un valor de prosa que
comience como una ruta absoluta o con `~` se rechaza, pero eso no detecta rutas incrustadas a mitad de frase ni
sustituye una revisión humana antes de publicar.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Union

from src.models.safe_artifact_format import (
    MAX_INPUT_COLUMNS,
    MAX_NAME_LENGTH,
    MODEL_TYPE_IMPUTED_LOGREG,
    MODEL_TYPE_PLATT,
    MODEL_TYPES,
    SCHEMA_VERSION as ARTIFACT_FORMAT_SCHEMA_VERSION,
    ImputedLogRegModel,
    PlattModel,
    SafeArtifactError,
    load_artifact,
)
from src.storage.artifact_store import ArtifactReader, InvalidArtifactKeyError, validate_key

METADATA_SCHEMA_VERSION = 1
PACKAGE_MANIFEST_SCHEMA_VERSION = 1
METADATA_DOCUMENT_TYPE = "model_artifact_metadata"
PACKAGE_MANIFEST_DOCUMENT_TYPE = "artifact_package_manifest"
ARTIFACT_FORMAT = "safe_json_b1"

MAX_METADATA_BYTES = 65_536
MAX_PACKAGE_MANIFEST_BYTES = 4_096
MAX_INTENDED_USE_CHARS = 500
MAX_LIMITATION_CHARS = 300
MAX_LIMITATIONS = 20
MAX_REF_SCHEMA_VERSION = 1_000_000
MAX_INT_DIGITS = 10

__all__ = [
    "ARTIFACT_FORMAT",
    "ArtifactComponent",
    "ArtifactPackageError",
    "ArtifactPackageManifest",
    "BaseModelRef",
    "DatasetManifestRef",
    "MAX_INTENDED_USE_CHARS",
    "MAX_LIMITATIONS",
    "MAX_LIMITATION_CHARS",
    "MAX_METADATA_BYTES",
    "MAX_PACKAGE_MANIFEST_BYTES",
    "METADATA_DOCUMENT_TYPE",
    "METADATA_SCHEMA_VERSION",
    "MetadataComponent",
    "ModelArtifactMetadata",
    "PACKAGE_MANIFEST_DOCUMENT_TYPE",
    "PACKAGE_MANIFEST_SCHEMA_VERSION",
    "PackageArtifactError",
    "PackageConsistencyError",
    "PackageFormatError",
    "PackageSchemaError",
    "Provenance",
    "VerifiedPackage",
    "canonical_metadata_bytes",
    "canonical_package_manifest_bytes",
    "parse_metadata",
    "parse_package_manifest",
    "verify_package",
]

_MODEL_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", re.ASCII)
_GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
_ENTRYPOINT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}", re.ASCII)
_ENV_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}", re.ASCII)
_TRAINED_AT_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?Z", re.ASCII
)
_PATHLIKE_START_RE = re.compile(r"[/~\\]|[A-Za-z]:[\\/]", re.ASCII)
_FORBIDDEN_KEY_RE = re.compile(r"event_ids?$|path|^test|^baseline_test|^(?:candidate_)?status$")

_METADATA_COMMON_KEYS = frozenset(
    {"schema_version", "document_type", "model_version", "model_type", "trained_at", "provenance", "data", "limits"}
)
_PROVENANCE_KEYS = frozenset({"git_commit", "git_tree_clean", "entrypoint", "environment"})
_ENVIRONMENT_KEYS = frozenset({"python", "scikit_learn"})
_DATA_KEYS = frozenset({"dataset_manifest_ref"})
_DATASET_REF_KEYS = frozenset({"key", "schema_version"})
_TRAINING_KEYS = frozenset({"feature_columns"})
_LIMITS_KEYS = frozenset({"intended_use", "known_limitations"})
_BASE_REF_KEYS = frozenset({"model_version", "package_manifest_key"})
_MANIFEST_KEYS = frozenset({"schema_version", "document_type", "model_version", "artifact", "metadata"})
_ARTIFACT_COMPONENT_KEYS = frozenset({"key", "format", "schema_version", "model_type"})
_METADATA_COMPONENT_KEYS = frozenset({"key", "schema_version"})


class ArtifactPackageError(Exception):
    """Base de los errores de este módulo (fail-closed)."""


class PackageFormatError(ArtifactPackageError):
    """Bytes inválidos: tipo, tamaño, hash distinto de la clave esperada, UTF-8, JSON, duplicados, constantes o
    números de coma flotante, o forma no canónica."""


class PackageSchemaError(ArtifactPackageError):
    """El documento no cumple el esquema: claves, tipos, cotas, formatos, claves prohibidas o claves inválidas."""


class PackageConsistencyError(ArtifactPackageError):
    """Los tres blobs son válidos por separado pero no son coherentes entre sí."""


class PackageArtifactError(ArtifactPackageError):
    """B1 rechazó el artefacto del paquete. La causa original (`SafeArtifactError`) queda en `__cause__`."""


# ---------------------------------------------------------------------
# Tipos de retorno (datos inmutables)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetManifestRef:
    """Referencia al manifiesto de instantánea (blob protegido). Solo se valida su formato."""

    key: str
    schema_version: int


@dataclass(frozen=True)
class BaseModelRef:
    """Referencia de un calibrador al manifiesto de paquete de su modelo base. Solo se valida su formato."""

    model_version: str
    package_manifest_key: str


@dataclass(frozen=True)
class Provenance:
    git_commit: str
    git_tree_clean: bool
    entrypoint: str
    python: str
    scikit_learn: str


@dataclass(frozen=True)
class ModelArtifactMetadata:
    model_version: str
    model_type: str
    trained_at: str
    base_model_ref: Optional[BaseModelRef]
    provenance: Provenance
    dataset_manifest_ref: DatasetManifestRef
    feature_columns: Optional[Tuple[str, ...]]
    intended_use: str
    known_limitations: Tuple[str, ...]


@dataclass(frozen=True)
class ArtifactComponent:
    key: str
    format: str
    schema_version: int
    model_type: str


@dataclass(frozen=True)
class MetadataComponent:
    key: str
    schema_version: int


@dataclass(frozen=True)
class ArtifactPackageManifest:
    model_version: str
    artifact: ArtifactComponent
    metadata: MetadataComponent


@dataclass(frozen=True)
class VerifiedPackage:
    """Paquete cuya integridad y coherencia se verificaron. NO es un estado `ALLOWED`: no activa ningún modelo ni
    toca el registro."""

    manifest_key: str
    manifest: ArtifactPackageManifest
    metadata: ModelArtifactMetadata
    model: Union[ImputedLogRegModel, PlattModel]


# ---------------------------------------------------------------------
# Forma canónica
# ---------------------------------------------------------------------


def _canonical_json_bytes(document: Any) -> bytes:
    try:
        text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PackageFormatError(f"documento no serializable de forma canónica: {exc!r}") from exc
    return (text + "\n").encode("ascii")


def canonical_metadata_bytes(document: Any) -> bytes:
    """Valida `document` como metadatos v1 y devuelve sus bytes canónicos (siempre cargables: también aplica el
    tope de tamaño). `PackageSchemaError` si no cumple el esquema; `PackageFormatError` si excede el tamaño."""
    _validate_metadata(document)
    data = _canonical_json_bytes(document)
    if len(data) > MAX_METADATA_BYTES:
        raise PackageFormatError(f"metadatos canónicos de {len(data)} bytes: superan el máximo {MAX_METADATA_BYTES}")
    return data


def canonical_package_manifest_bytes(document: Any) -> bytes:
    """Valida `document` como manifiesto de paquete v1 y devuelve sus bytes canónicos."""
    _validate_manifest(document)
    data = _canonical_json_bytes(document)
    if len(data) > MAX_PACKAGE_MANIFEST_BYTES:
        raise PackageFormatError(
            f"manifiesto canónico de {len(data)} bytes: supera el máximo {MAX_PACKAGE_MANIFEST_BYTES}"
        )
    return data


# ---------------------------------------------------------------------
# Carga de bytes (hash ANTES de analizar; fail-closed)
# ---------------------------------------------------------------------


def _reject_duplicates(pairs: list) -> dict:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackageFormatError(f"clave duplicada: {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise PackageFormatError(f"constante no permitida: {name}")


def _reject_float(token: str) -> Any:
    raise PackageFormatError("los números de coma flotante no están permitidos en la versión 1")


def _strict_int(token: str) -> int:
    if len(token.lstrip("-")) > MAX_INT_DIGITS:
        raise PackageFormatError("entero con demasiados dígitos")
    return int(token)


def _load_document(data: Any, expected_key: Any, max_bytes: int, what: str) -> Any:
    if type(data) is not bytes:
        raise PackageFormatError(f"{what}: los datos deben ser exactamente `bytes`")
    if len(data) > max_bytes:
        raise PackageFormatError(f"{what} de {len(data)} bytes: supera el máximo {max_bytes}")
    key = validate_key(expected_key)  # una clave de argumento inválida se propaga como InvalidArtifactKeyError
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest().encode("ascii"), key.encode("ascii")):
        raise PackageFormatError(f"{what}: los bytes no corresponden a la clave esperada (SHA-256 distinto)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageFormatError(f"{what}: UTF-8 inválido: {exc}") from exc
    if text.startswith("\ufeff"):
        raise PackageFormatError(f"{what}: no puede llevar BOM")
    if not text.endswith("\n") or "\n" in text[:-1] or "\r" in text:
        raise PackageFormatError(f"{what}: se exige un único salto de línea final (LF) y ningún otro")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
            parse_int=_strict_int,
            parse_float=_reject_float,
        )
    except ArtifactPackageError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PackageFormatError(f"{what}: JSON inválido: {exc}") from exc


def parse_metadata(data: bytes, *, expected_key: str) -> ModelArtifactMetadata:
    """Carga metadatos v1. `expected_key` (la clave del blob, que es el SHA-256 de sus bytes) es obligatoria y se
    comprueba ANTES de analizar. Orden: tipo y tamaño, clave, hash, UTF-8, JSON con controles, esquema y forma
    canónica. Una `expected_key` inválida lanza `InvalidArtifactKeyError`."""
    document = _load_document(data, expected_key, MAX_METADATA_BYTES, "metadatos")
    metadata = _validate_metadata(document)
    if _canonical_json_bytes(document) != data:
        raise PackageFormatError("metadatos: no están en forma canónica (bytes distintos de su serialización canónica)")
    return metadata


def parse_package_manifest(data: bytes, *, expected_key: str) -> ArtifactPackageManifest:
    """Carga un manifiesto de paquete v1, con el mismo orden y los mismos controles que `parse_metadata`."""
    document = _load_document(data, expected_key, MAX_PACKAGE_MANIFEST_BYTES, "manifiesto de paquete")
    manifest = _validate_manifest(document)
    if _canonical_json_bytes(document) != data:
        raise PackageFormatError(
            "manifiesto de paquete: no está en forma canónica (bytes distintos de su serialización canónica)"
        )
    return manifest


# ---------------------------------------------------------------------
# Validación estructural
# ---------------------------------------------------------------------


def _fail(message: str) -> None:
    raise PackageSchemaError(message)


def _reject_forbidden_keys(node: Any, where: str = "raíz") -> None:
    """D6 y D12: ninguna clave puede nombrar listas o resultados por `event_id`, rutas, estados del registro ni
    resultados del test, en ningún nivel (también dentro de listas)."""
    if type(node) is dict:
        for key, value in node.items():
            if type(key) is str and _FORBIDDEN_KEY_RE.search(key.lower()):
                _fail(f"{where}: clave prohibida {key!r} (D6/D12: sin listas de event_id, rutas, estados ni métricas de test)")
            _reject_forbidden_keys(value, f"{where}.{key}")
    elif type(node) is list:
        for index, item in enumerate(node):
            _reject_forbidden_keys(item, f"{where}[{index}]")


def _expect_keys(obj: Any, keys: frozenset, where: str) -> None:
    if type(obj) is not dict:
        _fail(f"{where}: se esperaba un objeto JSON")
    if set(obj) != keys:
        missing, extra = sorted(keys - set(obj)), sorted(str(k) for k in set(obj) - keys)
        _fail(f"{where}: claves inválidas (faltan {missing}, sobran {extra})")


def _expect_const(value: Any, expected: Any, where: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(f"{where}: debe ser exactamente {expected!r}")


def _expect_int(value: Any, where: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{where}: se esperaba un entero entre {minimum} y {maximum}")
    return value


def _expect_bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        _fail(f"{where}: se esperaba un booleano")
    return value


def _expect_model_version(value: Any, where: str) -> str:
    if type(value) is not str or _MODEL_VERSION_RE.fullmatch(value) is None:
        _fail(f"{where}: model_version inválido")
    return value


def _expect_model_type(value: Any, where: str) -> str:
    if type(value) is not str or value not in MODEL_TYPES:
        _fail(f"{where}: debe estar en la lista cerrada {list(MODEL_TYPES)}")
    return value


def _expect_key_field(value: Any, where: str) -> str:
    try:
        return validate_key(value)
    except InvalidArtifactKeyError:
        raise PackageSchemaError(
            f"{where}: no es una clave del almacén (64 hexadecimales en minúsculas)"
        ) from None


def _expect_text(value: Any, where: str, max_chars: int) -> str:
    if type(value) is not str:
        _fail(f"{where}: se esperaba texto")
    if not 1 <= len(value) <= max_chars:
        _fail(f"{where}: longitud fuera de rango (1..{max_chars} caracteres)")
    if not value.isprintable() or value != value.strip():
        _fail(f"{where}: solo caracteres imprimibles, en una línea y sin espacios en los extremos")
    if _PATHLIKE_START_RE.match(value):
        _fail(f"{where}: no puede comenzar como una ruta absoluta ni con '~'")
    return value


def _expect_column_name(value: Any, where: str) -> str:
    if type(value) is not str:
        _fail(f"{where}: se esperaba texto")
    if not 1 <= len(value) <= MAX_NAME_LENGTH or not value.isprintable() or value != value.strip():
        _fail(
            f"{where}: nombre de columna inválido (1..{MAX_NAME_LENGTH} caracteres imprimibles, sin espacios en "
            "los extremos)"
        )
    return value


def _expect_trained_at(value: Any, where: str) -> str:
    if type(value) is not str:
        _fail(f"{where}: se esperaba texto")
    match = _TRAINED_AT_RE.fullmatch(value)
    if match is None:
        _fail(f"{where}: formato inválido (UTC con 'Z': YYYY-MM-DDTHH:MM:SS[.f a ffffff]Z)")
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError:
        _fail(f"{where}: fecha u hora inexistente")
    return value


def _expect_entrypoint(value: Any, where: str) -> str:
    if type(value) is not str or _ENTRYPOINT_RE.fullmatch(value) is None:
        _fail(f"{where}: debe ser una ruta relativa al repositorio (letras, dígitos, '_', '.', '-' y '/'; máx. 128)")
    if any(part in ("", ".", "..") for part in value.split("/")):
        _fail(f"{where}: la ruta no puede tener componentes vacíos, '.' ni '..'")
    return value


def _expect_dataset_ref(value: Any, where: str) -> DatasetManifestRef:
    _expect_keys(value, _DATASET_REF_KEYS, where)
    return DatasetManifestRef(
        key=_expect_key_field(value["key"], f"{where}.key"),
        schema_version=_expect_int(value["schema_version"], f"{where}.schema_version", 1, MAX_REF_SCHEMA_VERSION),
    )


def _validate_provenance(value: Any) -> Provenance:
    where = "provenance"
    _expect_keys(value, _PROVENANCE_KEYS, where)
    commit = value["git_commit"]
    if type(commit) is not str or _GIT_COMMIT_RE.fullmatch(commit) is None:
        _fail(f"{where}.git_commit: se esperaban 40 hexadecimales en minúsculas")
    environment = value["environment"]
    _expect_keys(environment, _ENVIRONMENT_KEYS, f"{where}.environment")
    versions = []
    for name in ("python", "scikit_learn"):
        text = environment[name]
        if type(text) is not str or _ENV_VERSION_RE.fullmatch(text) is None:
            _fail(f"{where}.environment.{name}: versión inválida (1..32 caracteres: letras, dígitos, '.', '+', '_', '-')")
        versions.append(text)
    return Provenance(
        git_commit=commit,
        git_tree_clean=_expect_bool(value["git_tree_clean"], f"{where}.git_tree_clean"),
        entrypoint=_expect_entrypoint(value["entrypoint"], f"{where}.entrypoint"),
        python=versions[0],
        scikit_learn=versions[1],
    )


def _validate_feature_columns(value: Any) -> Tuple[str, ...]:
    where = "training.feature_columns"
    if type(value) is not list or not 1 <= len(value) <= MAX_INPUT_COLUMNS:
        _fail(f"{where}: lista de 1..{MAX_INPUT_COLUMNS} nombres")
    names = [_expect_column_name(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if len(set(names)) != len(names):
        _fail(f"{where}: nombres duplicados")
    return tuple(names)


def _validate_limits(value: Any) -> Tuple[str, Tuple[str, ...]]:
    where = "limits"
    _expect_keys(value, _LIMITS_KEYS, where)
    intended_use = _expect_text(value["intended_use"], f"{where}.intended_use", MAX_INTENDED_USE_CHARS)
    limitations = value["known_limitations"]
    if type(limitations) is not list or not 1 <= len(limitations) <= MAX_LIMITATIONS:
        _fail(f"{where}.known_limitations: lista de 1..{MAX_LIMITATIONS} textos")
    texts = tuple(
        _expect_text(item, f"{where}.known_limitations[{index}]", MAX_LIMITATION_CHARS)
        for index, item in enumerate(limitations)
    )
    return intended_use, texts


def _validate_metadata(document: Any) -> ModelArtifactMetadata:
    try:
        return _validate_metadata_document(document)
    except RecursionError:
        raise PackageSchemaError("metadatos: documento demasiado anidado") from None


def _validate_metadata_document(document: Any) -> ModelArtifactMetadata:
    _reject_forbidden_keys(document)
    if type(document) is not dict:
        _fail("raíz: se esperaba un objeto JSON")
    model_type = _expect_model_type(document.get("model_type"), "model_type")
    is_base = model_type == MODEL_TYPE_IMPUTED_LOGREG
    if is_base:
        if "base_model_ref" in document:
            _fail("base_model_ref: un modelo base no puede llevarlo (solo los calibradores)")
        if "training" not in document:
            _fail("training: es obligatorio en un modelo base")
    else:
        if "training" in document:
            _fail("training: un calibrador no lo lleva (no tiene columnas de entrada)")
        if "base_model_ref" not in document:
            _fail("base_model_ref: es obligatorio en un calibrador")
    _expect_keys(document, _METADATA_COMMON_KEYS | frozenset({"training" if is_base else "base_model_ref"}), "raíz")
    _expect_const(document["schema_version"], METADATA_SCHEMA_VERSION, "schema_version")
    _expect_const(document["document_type"], METADATA_DOCUMENT_TYPE, "document_type")
    model_version = _expect_model_version(document["model_version"], "model_version")
    trained_at = _expect_trained_at(document["trained_at"], "trained_at")

    base_ref: Optional[BaseModelRef] = None
    if not is_base:
        ref = document["base_model_ref"]
        _expect_keys(ref, _BASE_REF_KEYS, "base_model_ref")
        base_version = _expect_model_version(ref["model_version"], "base_model_ref.model_version")
        base_key = _expect_key_field(ref["package_manifest_key"], "base_model_ref.package_manifest_key")
        if base_version == model_version:
            _fail("base_model_ref: un calibrador no puede referenciarse a sí mismo (mismo model_version)")
        base_ref = BaseModelRef(model_version=base_version, package_manifest_key=base_key)

    provenance = _validate_provenance(document["provenance"])
    data = document["data"]
    _expect_keys(data, _DATA_KEYS, "data")
    dataset_ref = _expect_dataset_ref(data["dataset_manifest_ref"], "data.dataset_manifest_ref")

    feature_columns: Optional[Tuple[str, ...]] = None
    if is_base:
        training = document["training"]
        _expect_keys(training, _TRAINING_KEYS, "training")
        feature_columns = _validate_feature_columns(training["feature_columns"])

    intended_use, limitations = _validate_limits(document["limits"])
    return ModelArtifactMetadata(
        model_version=model_version,
        model_type=model_type,
        trained_at=trained_at,
        base_model_ref=base_ref,
        provenance=provenance,
        dataset_manifest_ref=dataset_ref,
        feature_columns=feature_columns,
        intended_use=intended_use,
        known_limitations=limitations,
    )


def _validate_manifest(document: Any) -> ArtifactPackageManifest:
    try:
        return _validate_manifest_document(document)
    except RecursionError:
        raise PackageSchemaError("manifiesto de paquete: documento demasiado anidado") from None


def _validate_manifest_document(document: Any) -> ArtifactPackageManifest:
    _reject_forbidden_keys(document)
    _expect_keys(document, _MANIFEST_KEYS, "raíz")
    _expect_const(document["schema_version"], PACKAGE_MANIFEST_SCHEMA_VERSION, "schema_version")
    _expect_const(document["document_type"], PACKAGE_MANIFEST_DOCUMENT_TYPE, "document_type")
    model_version = _expect_model_version(document["model_version"], "model_version")

    artifact = document["artifact"]
    _expect_keys(artifact, _ARTIFACT_COMPONENT_KEYS, "artifact")
    artifact_key = _expect_key_field(artifact["key"], "artifact.key")
    _expect_const(artifact["format"], ARTIFACT_FORMAT, "artifact.format")
    _expect_const(artifact["schema_version"], ARTIFACT_FORMAT_SCHEMA_VERSION, "artifact.schema_version")
    model_type = _expect_model_type(artifact["model_type"], "artifact.model_type")

    metadata = document["metadata"]
    _expect_keys(metadata, _METADATA_COMPONENT_KEYS, "metadata")
    metadata_key = _expect_key_field(metadata["key"], "metadata.key")
    _expect_const(metadata["schema_version"], METADATA_SCHEMA_VERSION, "metadata.schema_version")
    if artifact_key == metadata_key:
        _fail("artifact.key y metadata.key no pueden coincidir: son blobs distintos")
    return ArtifactPackageManifest(
        model_version=model_version,
        artifact=ArtifactComponent(
            key=artifact_key,
            format=ARTIFACT_FORMAT,
            schema_version=ARTIFACT_FORMAT_SCHEMA_VERSION,
            model_type=model_type,
        ),
        metadata=MetadataComponent(key=metadata_key, schema_version=METADATA_SCHEMA_VERSION),
    )


# ---------------------------------------------------------------------
# Verificación del paquete (solo lectura)
# ---------------------------------------------------------------------


def _loaded_model_type(model: Any) -> str:
    if isinstance(model, ImputedLogRegModel):
        return MODEL_TYPE_IMPUTED_LOGREG
    if isinstance(model, PlattModel):
        return MODEL_TYPE_PLATT
    raise PackageArtifactError("B1 devolvió un tipo de modelo desconocido")


def verify_package(reader: ArtifactReader, manifest_key: str, *, expected_model_version: str) -> VerifiedPackage:
    """Lee y verifica los tres blobs del paquete a través de `reader` (solo lectura: nunca llama a `put`).

    Orden fail-closed: clave del manifiesto; lectura del manifiesto (el almacén verifica su hash) y `parse`;
    `model_version` esperado; lectura del artefacto y carga con B1 (hash y `model_version` esperados); el tipo
    cargado coincide con el declarado; lectura de los metadatos y `parse`; coherencia entre los tres, incluido que
    `base_model_ref` no apunte al manifiesto de este mismo paquete (autorreferencia por clave).

    NO resuelve `base_model_ref` ni `dataset_manifest_ref` y NO consulta el registro: un paquete verificado no
    es un modelo `ALLOWED`. Los errores del almacén se propagan tal cual (incluida una `manifest_key` inválida:
    `InvalidArtifactKeyError`); los de B1 se envuelven como `PackageArtifactError`."""
    if not isinstance(reader, ArtifactReader):
        raise TypeError("reader debe ser un ArtifactReader")
    manifest_key = validate_key(manifest_key)
    if type(expected_model_version) is not str or _MODEL_VERSION_RE.fullmatch(expected_model_version) is None:
        raise PackageSchemaError("expected_model_version inválido")

    manifest = parse_package_manifest(reader.get(manifest_key), expected_key=manifest_key)
    if manifest.model_version != expected_model_version:
        raise PackageConsistencyError("el model_version del manifiesto no es el esperado")

    artifact_bytes = reader.get(manifest.artifact.key)
    try:
        model = load_artifact(
            artifact_bytes, expected_sha256=manifest.artifact.key, expected_model_version=expected_model_version
        )
    except SafeArtifactError as exc:
        raise PackageArtifactError(f"B1 rechazó el artefacto del paquete: {exc}") from exc
    if _loaded_model_type(model) != manifest.artifact.model_type:
        raise PackageConsistencyError("artifact.model_type del manifiesto distinto del tipo del artefacto cargado")

    metadata = parse_metadata(reader.get(manifest.metadata.key), expected_key=manifest.metadata.key)
    if metadata.model_version != manifest.model_version:
        raise PackageConsistencyError("los metadatos declaran otro model_version que el manifiesto")
    if metadata.model_type != manifest.artifact.model_type:
        raise PackageConsistencyError("los metadatos declaran otro model_type que el manifiesto")
    if isinstance(model, ImputedLogRegModel) and metadata.feature_columns != model.input_columns:
        raise PackageConsistencyError("training.feature_columns de los metadatos distinto de input_columns del artefacto")
    if metadata.base_model_ref is not None and metadata.base_model_ref.package_manifest_key == manifest_key:
        # Defensa en profundidad. Construirla exigiría encontrar un punto fijo de la composición de hashes, lo que se
        # considera computacionalmente inviable. No se lee ni se resuelve el paquete base.
        raise PackageConsistencyError("base_model_ref apunta al manifiesto de este mismo paquete (autorreferencia por clave)")
    return VerifiedPackage(manifest_key=manifest_key, manifest=manifest, metadata=metadata, model=model)
