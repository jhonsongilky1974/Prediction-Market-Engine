"""Paquete de artefacto (`src/models/artifact_package.py`; ver `ARTIFACT_PACKAGE_SPEC.md`): metadatos canónicos,
manifiesto de paquete y verificación de los tres blobs. Solo bytes sintéticos y directorios temporales (`tmp_path`):
ninguna prueba crea archivos dentro del repositorio ni conecta el módulo a entrenadores, cargadores, registro, libro
ni evaluador.

Las pruebas usan los vectores canónicos FIJOS de la especificación y solo la API pública del módulo, de B1 y del
almacén: no dependen de funciones privadas de B1 ni de las expresiones regulares de B1. La regla canónica se
reescribe aquí (`rule`) de forma independiente."""
from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.models import artifact_package as ap
from src.models.artifact_package import (
    ArtifactPackageError,
    PackageArtifactError,
    PackageConsistencyError,
    PackageFormatError,
    PackageSchemaError,
    VerifiedPackage,
    canonical_metadata_bytes,
    canonical_package_manifest_bytes,
    parse_metadata,
    parse_package_manifest,
    verify_package,
)
from src.models.safe_artifact_format import SafeArtifactError, canonical_bytes
from src.storage.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactReader,
    ArtifactStoreError,
    InvalidArtifactKeyError,
    StoreConfigurationError,
)
from src.storage.local_filesystem_store import LocalFilesystemStore

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "models" / "artifact_package.py"
SPEC_PATH = REPO_ROOT / "ARTIFACT_PACKAGE_SPEC.md"
TEMPLATE_PATH = REPO_ROOT / "governance" / "models" / "MODEL_CARD_TEMPLATE.md"
MAX_BLOB = 300_000

# =====================================================================
# Vectores canónicos FIJOS (los mismos que figuran en ARTIFACT_PACKAGE_SPEC.md §10)
# =====================================================================

A1_BYTES = b'{"model_type":"imputed_standardized_logreg_v1","model_version":"pkg_example_v1","parameters":{"classes":[0,1],"coef":[0.5,-0.25],"imputer_statistics":[3.0,null,0.0],"input_columns":["rest_days.participant_a","rest_days.participant_b","tournament_round.Final"],"intercept":0.1,"scaler_mean":[2.5,0.2],"scaler_scale":[1.5,0.4]},"schema_version":1}\n'
A1_KEY = "34b65f82c62b24aba4b48b5cfeb20fdfe9292a330061853015a0867df2f871e0"
A2_BYTES = b'{"model_type":"platt_logreg_1d_v1","model_version":"pkg_calibrator_v1","parameters":{"classes":[0,1],"coef":1.2,"intercept":-0.6},"schema_version":1}\n'
A2_KEY = "9f6b88c174cad856144ad5cffd1e2eb66358907f074138aa6bc1336aa2c93bc3"
M1_BYTES = b'{"data":{"dataset_manifest_ref":{"key":"42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067","schema_version":1}},"document_type":"model_artifact_metadata","limits":{"intended_use":"Vector de ejemplo de documentacion: no es un modelo real.","known_limitations":["Ejemplo sintetico; no representa ningun entrenamiento."]},"model_type":"imputed_standardized_logreg_v1","model_version":"pkg_example_v1","provenance":{"entrypoint":"scripts/example_trainer.py","environment":{"python":"3.9.6","scikit_learn":"1.6.1"},"git_commit":"1234567890abcdef1234567890abcdef12345678","git_tree_clean":true},"schema_version":1,"trained_at":"2026-11-21T20:00:00Z","training":{"feature_columns":["rest_days.participant_a","rest_days.participant_b","tournament_round.Final"]}}\n'
M1_KEY = "98f38d38ae1a54d484e36886fc6a58840c828c5fb1995538eceba91c8d958ec6"
M2_BYTES = b'{"base_model_ref":{"model_version":"pkg_example_v1","package_manifest_key":"11254d6d22e7a1bb60d1d0f72b0d5c291be5dcc54b691b702560d318ec86d876"},"data":{"dataset_manifest_ref":{"key":"42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067","schema_version":1}},"document_type":"model_artifact_metadata","limits":{"intended_use":"Vector de ejemplo de un calibrador: no es un modelo real.","known_limitations":["Ejemplo sintetico.","Referencia al modelo base solo con formato, sin resolver."]},"model_type":"platt_logreg_1d_v1","model_version":"pkg_calibrator_v1","provenance":{"entrypoint":"scripts/example_calibrator.py","environment":{"python":"3.9.6","scikit_learn":"1.6.1"},"git_commit":"1234567890abcdef1234567890abcdef12345678","git_tree_clean":true},"schema_version":1,"trained_at":"2026-11-21T20:00:00.123456Z"}\n'
M2_KEY = "a4a1ffe736b2075f996b69e10a4e7a9959cd02d6ab74a85ce78354016c08621e"
F1_BYTES = b'{"artifact":{"format":"safe_json_b1","key":"34b65f82c62b24aba4b48b5cfeb20fdfe9292a330061853015a0867df2f871e0","model_type":"imputed_standardized_logreg_v1","schema_version":1},"document_type":"artifact_package_manifest","metadata":{"key":"98f38d38ae1a54d484e36886fc6a58840c828c5fb1995538eceba91c8d958ec6","schema_version":1},"model_version":"pkg_example_v1","schema_version":1}\n'
F1_KEY = "11254d6d22e7a1bb60d1d0f72b0d5c291be5dcc54b691b702560d318ec86d876"
F2_BYTES = b'{"artifact":{"format":"safe_json_b1","key":"9f6b88c174cad856144ad5cffd1e2eb66358907f074138aa6bc1336aa2c93bc3","model_type":"platt_logreg_1d_v1","schema_version":1},"document_type":"artifact_package_manifest","metadata":{"key":"a4a1ffe736b2075f996b69e10a4e7a9959cd02d6ab74a85ce78354016c08621e","schema_version":1},"model_version":"pkg_calibrator_v1","schema_version":1}\n'
F2_KEY = "9c445d5c29d9860fc140c9af450d811c9cc3d23f8d11e2fb38ace67a1ebf2684"
DATASET_KEY = "42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067"

VECTORS = {
    "A1": (A1_BYTES, A1_KEY), "A2": (A2_BYTES, A2_KEY), "M1": (M1_BYTES, M1_KEY),
    "M2": (M2_BYTES, M2_KEY), "F1": (F1_BYTES, F1_KEY), "F2": (F2_BYTES, F2_KEY),
}

COLUMNS = ["rest_days.participant_a", "rest_days.participant_b", "tournament_round.Final"]
GIT_COMMIT = "1234567890abcdef1234567890abcdef12345678"

ART_IMPUTED_DOC = {
    "schema_version": 1, "model_type": "imputed_standardized_logreg_v1", "model_version": "pkg_example_v1",
    "parameters": {
        "input_columns": COLUMNS, "imputer_statistics": [3.0, None, 0.0], "scaler_mean": [2.5, 0.2],
        "scaler_scale": [1.5, 0.4], "coef": [0.5, -0.25], "intercept": 0.1, "classes": [0, 1],
    },
}
ART_PLATT_DOC = {
    "schema_version": 1, "model_type": "platt_logreg_1d_v1", "model_version": "pkg_calibrator_v1",
    "parameters": {"coef": 1.2, "intercept": -0.6, "classes": [0, 1]},
}
META_BASE_DOC = {
    "schema_version": 1, "document_type": "model_artifact_metadata", "model_version": "pkg_example_v1",
    "model_type": "imputed_standardized_logreg_v1", "trained_at": "2026-11-21T20:00:00Z",
    "provenance": {
        "git_commit": GIT_COMMIT, "git_tree_clean": True, "entrypoint": "scripts/example_trainer.py",
        "environment": {"python": "3.9.6", "scikit_learn": "1.6.1"},
    },
    "data": {"dataset_manifest_ref": {"key": DATASET_KEY, "schema_version": 1}},
    "training": {"feature_columns": COLUMNS},
    "limits": {
        "intended_use": "Vector de ejemplo de documentacion: no es un modelo real.",
        "known_limitations": ["Ejemplo sintetico; no representa ningun entrenamiento."],
    },
}
META_CAL_DOC = {
    "schema_version": 1, "document_type": "model_artifact_metadata", "model_version": "pkg_calibrator_v1",
    "model_type": "platt_logreg_1d_v1", "trained_at": "2026-11-21T20:00:00.123456Z",
    "base_model_ref": {"model_version": "pkg_example_v1", "package_manifest_key": F1_KEY},
    "provenance": {
        "git_commit": GIT_COMMIT, "git_tree_clean": True, "entrypoint": "scripts/example_calibrator.py",
        "environment": {"python": "3.9.6", "scikit_learn": "1.6.1"},
    },
    "data": {"dataset_manifest_ref": {"key": DATASET_KEY, "schema_version": 1}},
    "limits": {
        "intended_use": "Vector de ejemplo de un calibrador: no es un modelo real.",
        "known_limitations": ["Ejemplo sintetico.", "Referencia al modelo base solo con formato, sin resolver."],
    },
}
MANIFEST_BASE_DOC = {
    "schema_version": 1, "document_type": "artifact_package_manifest", "model_version": "pkg_example_v1",
    "artifact": {"key": A1_KEY, "format": "safe_json_b1", "schema_version": 1, "model_type": "imputed_standardized_logreg_v1"},
    "metadata": {"key": M1_KEY, "schema_version": 1},
}
MANIFEST_CAL_DOC = {
    "schema_version": 1, "document_type": "artifact_package_manifest", "model_version": "pkg_calibrator_v1",
    "artifact": {"key": A2_KEY, "format": "safe_json_b1", "schema_version": 1, "model_type": "platt_logreg_1d_v1"},
    "metadata": {"key": M2_KEY, "schema_version": 1},
}

# --- utilidades -----------------------------------------------------------------------------------------------

DEL = object()


def rule(document) -> bytes:
    """La regla canónica documentada (spec §3), reescrita aquí: claves ordenadas, sin espacios, ASCII, un único LF."""
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mutate(document, path, value):
    new = copy.deepcopy(document)
    node = new
    for step in path[:-1]:
        node = node[step]
    if value is DEL:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return new


def parse_meta(document):
    data = rule(document)
    return parse_metadata(data, expected_key=sha(data))


def parse_manifest(document):
    data = rule(document)
    return parse_package_manifest(data, expected_key=sha(data))


class FakeReader(ArtifactReader):
    """Lector en memoria que registra las claves pedidas; puede devolver bytes arbitrarios o lanzar un error."""

    def __init__(self, blobs=None, error=None):
        self.blobs = dict(blobs or {})
        self.error = error
        self.calls = []

    def get(self, key):
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        if key not in self.blobs:
            raise ArtifactNotFoundError(key)
        return self.blobs[key]

    def exists(self, key):
        return key in self.blobs

    def verify(self, key):
        return None


@pytest.fixture
def root(tmp_path) -> Path:
    path = tmp_path / "store_root"
    path.mkdir()
    os.chmod(path, 0o700)
    return path


@pytest.fixture
def store(root) -> LocalFilesystemStore:
    return LocalFilesystemStore(root, max_blob_bytes=MAX_BLOB)


def blob_path(root, key) -> Path:
    return Path(root) / "sha256" / key[:2] / key


def listing(root) -> list:
    return sorted((os.path.relpath(os.path.join(c, n), root), os.stat(os.path.join(c, n)).st_mode)
                  for c, d, f in os.walk(root) for n in d + f)


def publish_vectors(store, *names) -> None:
    for name in names:
        data, key = VECTORS[name]
        assert store.put(data) == key


def artifact_doc(kind, version, columns=None):
    doc = copy.deepcopy(ART_IMPUTED_DOC if kind == "base" else ART_PLATT_DOC)
    doc["model_version"] = version
    if columns is not None:
        doc["parameters"]["input_columns"] = list(columns)
    return doc


def metadata_doc(kind, version, columns=None, base_version="pkg_other_base_v1"):
    doc = copy.deepcopy(META_BASE_DOC if kind == "base" else META_CAL_DOC)
    doc["model_version"] = version
    if kind == "base" and columns is not None:
        doc["training"]["feature_columns"] = list(columns)
    if kind != "base":
        doc["base_model_ref"]["model_version"] = base_version
    return doc


def manifest_doc(version, artifact_bytes, model_type, metadata_bytes):
    return {
        "schema_version": 1, "document_type": "artifact_package_manifest", "model_version": version,
        "artifact": {"key": sha(artifact_bytes), "format": "safe_json_b1", "schema_version": 1, "model_type": model_type},
        "metadata": {"key": sha(metadata_bytes), "schema_version": 1},
    }


BASE_TYPE = "imputed_standardized_logreg_v1"
PLATT_TYPE = "platt_logreg_1d_v1"


def publish_package(store, kind, version, *, columns=None, artifact_columns=None, manifest_type=None,
                    metadata_kind=None, metadata_version=None):
    """Publica un paquete coherente (o, con los argumentos opcionales, uno deliberadamente incoherente) y devuelve
    sus tres claves."""
    artifact_bytes = canonical_bytes(artifact_doc(kind, version, artifact_columns))
    metadata_bytes = canonical_metadata_bytes(
        metadata_doc(metadata_kind or kind, metadata_version or version, columns)
    )
    model_type = manifest_type or (BASE_TYPE if kind == "base" else PLATT_TYPE)
    manifest_bytes = canonical_package_manifest_bytes(manifest_doc(version, artifact_bytes, model_type, metadata_bytes))
    return {
        "artifact": store.put(artifact_bytes), "metadata": store.put(metadata_bytes),
        "manifest": store.put(manifest_bytes),
    }


# =====================================================================
# Vectores canónicos fijos
# =====================================================================


@pytest.mark.parametrize(
    "name, document, canonical",
    [
        ("M1", META_BASE_DOC, canonical_metadata_bytes), ("M2", META_CAL_DOC, canonical_metadata_bytes),
        ("F1", MANIFEST_BASE_DOC, canonical_package_manifest_bytes), ("F2", MANIFEST_CAL_DOC, canonical_package_manifest_bytes),
    ],
)
def test_the_fixed_vectors_are_the_exact_canonical_bytes_and_keys(name, document, canonical):
    data, key = VECTORS[name]
    assert canonical(document) == data
    assert rule(document) == data
    assert sha(data) == key
    assert data.endswith(b"\n") and data.count(b"\n") == 1 and all(byte < 128 for byte in data)


def test_the_b1_artifact_vectors_are_the_documented_ones_and_follow_the_same_canonical_rule():
    assert canonical_bytes(ART_IMPUTED_DOC) == A1_BYTES and canonical_bytes(ART_PLATT_DOC) == A2_BYTES
    assert sha(A1_BYTES) == A1_KEY and sha(A2_BYTES) == A2_KEY
    assert rule(json.loads(A1_BYTES)) == A1_BYTES and rule(json.loads(A2_BYTES)) == A2_BYTES


def test_the_vectors_reference_each_other_through_keys_only():
    assert json.loads(F1_BYTES)["artifact"]["key"] == A1_KEY and json.loads(F1_BYTES)["metadata"]["key"] == M1_KEY
    assert json.loads(F2_BYTES)["artifact"]["key"] == A2_KEY and json.loads(F2_BYTES)["metadata"]["key"] == M2_KEY
    assert json.loads(M2_BYTES)["base_model_ref"]["package_manifest_key"] == F1_KEY
    assert json.loads(M1_BYTES)["data"]["dataset_manifest_ref"]["key"] == DATASET_KEY == sha(b"dataset-manifest-example")


def test_the_fixed_vectors_parse_back_into_immutable_data_objects():
    base = parse_metadata(M1_BYTES, expected_key=M1_KEY)
    assert (base.model_version, base.model_type, base.trained_at) == ("pkg_example_v1", BASE_TYPE, "2026-11-21T20:00:00Z")
    assert base.base_model_ref is None and base.feature_columns == tuple(COLUMNS)
    assert base.provenance.git_commit == GIT_COMMIT and base.provenance.git_tree_clean is True
    assert base.provenance.entrypoint == "scripts/example_trainer.py"
    assert (base.provenance.python, base.provenance.scikit_learn) == ("3.9.6", "1.6.1")
    assert (base.dataset_manifest_ref.key, base.dataset_manifest_ref.schema_version) == (DATASET_KEY, 1)
    assert base.intended_use.startswith("Vector de ejemplo") and len(base.known_limitations) == 1
    calibrator = parse_metadata(M2_BYTES, expected_key=M2_KEY)
    assert calibrator.feature_columns is None and calibrator.trained_at == "2026-11-21T20:00:00.123456Z"
    assert (calibrator.base_model_ref.model_version, calibrator.base_model_ref.package_manifest_key) == ("pkg_example_v1", F1_KEY)
    manifest = parse_package_manifest(F1_BYTES, expected_key=F1_KEY)
    assert manifest.model_version == "pkg_example_v1" and manifest.artifact.key == A1_KEY
    assert (manifest.artifact.format, manifest.artifact.schema_version, manifest.artifact.model_type) == ("safe_json_b1", 1, BASE_TYPE)
    assert (manifest.metadata.key, manifest.metadata.schema_version) == (M1_KEY, 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        base.model_version = "otro"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.artifact.key = M1_KEY  # type: ignore[misc]
    assert isinstance(base.known_limitations, tuple)


def test_the_canonical_form_is_independent_of_insertion_order_and_escapes_non_ascii_names():
    shuffled = dict(reversed(list(META_BASE_DOC.items())))
    shuffled["provenance"] = dict(reversed(list(META_BASE_DOC["provenance"].items())))
    assert canonical_metadata_bytes(shuffled) == M1_BYTES
    names = ["partido_año", "señal_ñ", "día_ü"]
    document = mutate(META_BASE_DOC, ("training", "feature_columns"), names)
    data = canonical_metadata_bytes(document)
    assert all(byte < 128 for byte in data) and b"\\u00f1" in data
    assert parse_metadata(data, expected_key=sha(data)).feature_columns == tuple(names)
    assert rule(document) == data


def test_the_constants_are_the_documented_ones():
    assert (ap.METADATA_SCHEMA_VERSION, ap.PACKAGE_MANIFEST_SCHEMA_VERSION) == (1, 1)
    assert (ap.MAX_METADATA_BYTES, ap.MAX_PACKAGE_MANIFEST_BYTES) == (65_536, 4_096)
    assert (ap.MAX_INTENDED_USE_CHARS, ap.MAX_LIMITATION_CHARS, ap.MAX_LIMITATIONS) == (500, 300, 20)
    assert ap.METADATA_DOCUMENT_TYPE == "model_artifact_metadata"
    assert ap.PACKAGE_MANIFEST_DOCUMENT_TYPE == "artifact_package_manifest" and ap.ARTIFACT_FORMAT == "safe_json_b1"


def test_the_error_hierarchy_keeps_package_errors_apart_from_store_and_b1_errors():
    for error in (PackageFormatError, PackageSchemaError, PackageConsistencyError, PackageArtifactError):
        assert issubclass(error, ArtifactPackageError)
    assert not issubclass(ArtifactPackageError, (ArtifactStoreError, SafeArtifactError))


# =====================================================================
# Carga de bytes: hash antes de analizar, forma canónica, controles del analizador
# =====================================================================

PARSERS = [("metadatos", parse_metadata, ap.MAX_METADATA_BYTES), ("manifiesto", parse_package_manifest, ap.MAX_PACKAGE_MANIFEST_BYTES)]
PARSER_IDS = [name for name, _, _ in PARSERS]


@pytest.mark.parametrize("name, parser, cap", PARSERS, ids=PARSER_IDS)
@pytest.mark.parametrize("data", [bytearray(b"{}\n"), memoryview(b"{}\n"), "{}\n", None, 1, [b"{}\n"]])
def test_only_exact_bytes_are_accepted(name, parser, cap, data):
    with pytest.raises(PackageFormatError):
        parser(data, expected_key=sha(b"x"))


@pytest.mark.parametrize("name, parser, cap", PARSERS, ids=PARSER_IDS)
def test_the_size_limit_applies_before_the_key_and_the_hash(name, parser, cap):
    data = b"x" * (cap + 1)
    with pytest.raises(PackageFormatError, match="supera el máximo"):
        parser(data, expected_key="no-es-una-clave")
    with pytest.raises(PackageFormatError, match="supera el máximo"):
        parser(data, expected_key=sha(data))


@pytest.mark.parametrize("name, parser, cap", PARSERS, ids=PARSER_IDS)
@pytest.mark.parametrize(
    "bad_key",
    ["sha256/" + "ab" + "/" + "a" * 64, "a" * 63, "a" * 65, ("A" * 64), "g" * 64, "", None, b"a" * 64, 123, " " + "a" * 63],
)
def test_an_invalid_expected_key_raises_invalid_artifact_key_error_unwrapped(name, parser, cap, bad_key):
    with pytest.raises(InvalidArtifactKeyError):
        parser(b"{}\n", expected_key=bad_key)


@pytest.mark.parametrize("name, parser, cap", PARSERS, ids=PARSER_IDS)
def test_the_hash_is_checked_before_parsing_anything(name, parser, cap):
    with pytest.raises(PackageFormatError, match="SHA-256 distinto"):
        parser(b"esto no es JSON\n", expected_key=sha(b"otros bytes"))
    valid = M1_BYTES if parser is parse_metadata else F1_BYTES
    with pytest.raises(PackageFormatError, match="SHA-256 distinto"):
        parser(valid, expected_key=A1_KEY)
    with pytest.raises(PackageFormatError, match="SHA-256 distinto"):
        parser(valid + b" ", expected_key=sha(valid))


def _structural_cases(valid: bytes, document: dict) -> dict:
    pretty = (json.dumps(document, sort_keys=True, indent=1) + "\n").encode("ascii")
    spaced = (json.dumps(document, sort_keys=True) + "\n").encode("ascii")
    unsorted = (json.dumps(document, sort_keys=False, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    return {
        "utf8_invalido": b"\xff\xfe\n",
        "bom": b"\xef\xbb\xbf" + valid,
        "sin_salto_final": valid[:-1],
        "dos_saltos_finales": valid + b"\n",
        "crlf": valid[:-1] + b"\r\n",
        "salto_incrustado": pretty,
        "duplicados": b'{"schema_version":1,"schema_version":1}\n',
        "constante_nan": b'{"schema_version":NaN}\n',
        "constante_infinity": b'{"schema_version":Infinity}\n',
        "float_con_decimal": b'{"schema_version":1.0}\n',
        "float_con_exponente": b'{"schema_version":1e0}\n',
        "entero_enorme": b'{"schema_version":' + b"9" * 11 + b"}\n",
        "no_es_json": b"no es json\n",
        "json_vacio": b"\n",
        # 1500 niveles (3001 bytes): caben bajo los dos topes de tamaño y superan el límite de recursión del analizador
        "anidamiento_profundo": b"[" * 1500 + b"]" * 1500 + b"\n",
        "espacios": spaced,
        "claves_sin_ordenar": unsorted,
        "no_es_objeto": b"[1,2]\n",
    }


STRUCTURAL_MESSAGES = {
    "utf8_invalido": "UTF-8 inválido", "bom": "no puede llevar BOM", "sin_salto_final": "único salto de línea",
    "dos_saltos_finales": "único salto de línea", "crlf": "único salto de línea", "salto_incrustado": "único salto de línea",
    "duplicados": "clave duplicada", "constante_nan": "constante no permitida", "constante_infinity": "constante no permitida",
    "float_con_decimal": "coma flotante", "float_con_exponente": "coma flotante", "entero_enorme": "demasiados dígitos",
    "no_es_json": "JSON inválido", "json_vacio": "JSON inválido", "anidamiento_profundo": "JSON inválido",
    "espacios": "forma canónica", "claves_sin_ordenar": "forma canónica",
}


@pytest.mark.parametrize("name, parser, cap", PARSERS, ids=PARSER_IDS)
@pytest.mark.parametrize("case", list(_structural_cases(M1_BYTES, META_BASE_DOC)))
def test_malformed_or_non_canonical_bytes_are_refused_even_with_a_correct_hash(name, parser, cap, case):
    valid, document = (M1_BYTES, META_BASE_DOC) if parser is parse_metadata else (F1_BYTES, MANIFEST_BASE_DOC)
    data = _structural_cases(valid, document)[case]
    if case in ("no_es_objeto",):
        with pytest.raises(PackageSchemaError, match="objeto JSON"):
            parser(data, expected_key=sha(data))
        return
    with pytest.raises(PackageFormatError, match=STRUCTURAL_MESSAGES[case]) as excinfo:
        parser(data, expected_key=sha(data))
    assert "SHA-256 distinto" not in str(excinfo.value), "debe fallar por su propia causa, no por el hash"


def test_every_structural_case_has_its_own_expected_message():
    assert set(STRUCTURAL_MESSAGES) | {"no_es_objeto"} == set(_structural_cases(M1_BYTES, META_BASE_DOC))


def test_non_ascii_written_without_escapes_is_not_canonical_even_with_a_correct_hash():
    document = mutate(META_BASE_DOC, ("training", "feature_columns"), ["señal"])
    data = (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    with pytest.raises(PackageFormatError, match="canónica"):
        parse_metadata(data, expected_key=sha(data))


def test_floats_are_never_accepted_in_v1_neither_in_documents_nor_on_the_wire():
    for document, canonical, parser in (
        (mutate(META_BASE_DOC, ("schema_version",), 1.0), canonical_metadata_bytes, parse_meta),
        (mutate(MANIFEST_BASE_DOC, ("metadata", "schema_version"), 1.0), canonical_package_manifest_bytes, parse_manifest),
    ):
        with pytest.raises(PackageSchemaError):
            canonical(document)
        with pytest.raises(PackageFormatError, match="coma flotante"):
            parser(document)


# =====================================================================
# Metadatos: esquema (casos negativos deterministas)
# =====================================================================

K_BAD = [
    "sha256/" + "ab" + "/" + "a" * 64, "a" * 63, "a" * 65, "A" * 64, "g" * 64, "", None, 7,
    ["a" * 64], {"k": "a" * 64}, " " + "a" * 63, "a" * 63 + "\n",
]  # solo valores serializables en JSON: los `bytes` se prueban aparte, solo contra el constructor
BAD_TRAINED_AT = [
    "2026-11-21T20:00:00", "2026-11-21T20:00:00+00:00", "2026-11-21 20:00:00Z", "2026-11-21T20:00:00z",
    "2026-11-21T20:00Z", "2026-13-21T20:00:00Z", "2026-02-30T20:00:00Z", "2025-02-29T20:00:00Z",
    "2026-11-21T24:00:00Z", "2026-11-21T20:60:00Z", "2026-11-21T20:00:60Z", "0000-11-21T20:00:00Z",
    "2026-11-21T20:00:00.Z", "2026-11-21T20:00:00.1234567Z", "2026-11-21T20:00:00,5Z", " 2026-11-21T20:00:00Z",
    "2026-11-21T20:00:00Z ", "2026-11-21T20:00:00Z\n", "２０２６-11-21T20:00:00Z", "", None, 20261121, True,
]
GOOD_TRAINED_AT = [
    "2026-11-21T20:00:00Z", "2026-11-21T20:00:00.1Z", "2026-11-21T20:00:00.123456Z", "2024-02-29T00:00:00Z",
    "0001-01-01T00:00:00Z", "9999-12-31T23:59:59.999999Z",
]
BAD_ENTRYPOINTS = [
    "/abs/script.py", "../x.py", "a/../b.py", "a/./b.py", "./a.py", "a//b.py", "a/", "", ".", "..", "~/x.py",
    "C:\\x.py", "C:/x.py", "\\\\srv\\share\\x.py", "a\\b.py", "a b.py", "a\nb.py", "-x.py", "x" * 129, None, 1, ["a.py"],
    "scripts/ñ.py", "a:b.py",
]
BAD_TEXTS = [
    "", " x", "x ", "/etc/passwd", "~/secreto", "~", "\\\\servidor\\recurso", "\\x", "C:\\Users\\x", "C:/Users/x",
    "z:\\x", "línea\nsalto", "tab\tulacion", "nul\x00", "\u00a0espacio-duro", None, 1, ["x"], {"x": "y"},
]


def _meta_negatives():
    cases = {}

    def add(name, path, value, base=META_BASE_DOC):
        cases[name] = mutate(base, path, value)

    for value in (2, 0, True, "1", None, [1]):
        add(f"schema_version={value!r}", ("schema_version",), value)
    for value in ("artifact_package_manifest", "", None, 1):
        add(f"document_type={value!r}", ("document_type",), value)
    for value in ("", "a b", "-abc", "_abc", "a" * 129, 1, None, "ñ"):
        add(f"model_version={value!r}", ("model_version",), value)
    for value in ("pickle_v1", "", None, 1, "IMPUTED_STANDARDIZED_LOGREG_V1"):
        add(f"model_type={value!r}", ("model_type",), value)
    for value in BAD_TRAINED_AT:
        add(f"trained_at={value!r}", ("trained_at",), value)
    for value in ("A" * 40, "1" * 39, "1" * 41, "g" * 40, "", None, 1, " " + "1" * 39):
        add(f"git_commit={value!r}", ("provenance", "git_commit"), value)
    for value in (1, 0, "true", "false", None, []):
        add(f"git_tree_clean={value!r}", ("provenance", "git_tree_clean"), value)
    for value in BAD_ENTRYPOINTS:
        add(f"entrypoint={value!r}", ("provenance", "entrypoint"), value)
    for value in ("", "a b", "x" * 33, 3, None, "-3.9", "3.9/x", "3.9\n"):
        add(f"python={value!r}", ("provenance", "environment", "python"), value)
        add(f"scikit_learn={value!r}", ("provenance", "environment", "scikit_learn"), value)
    add("environment_sin_python", ("provenance", "environment", "python"), DEL)
    add("environment_con_numpy", ("provenance", "environment", "numpy"), "1.26.0")
    add("provenance_sin_entrypoint", ("provenance", "entrypoint"), DEL)
    add("provenance_con_extra", ("provenance", "hostname"), "equipo")
    add("provenance_no_objeto", ("provenance",), [])
    add("data_con_extra", ("data", "cutoff"), "x")
    add("data_sin_ref", ("data", "dataset_manifest_ref"), DEL)
    add("data_ref_con_extra", ("data", "dataset_manifest_ref", "snapshot"), "x")
    add("data_ref_sin_key", ("data", "dataset_manifest_ref", "key"), DEL)
    for value in K_BAD:
        add(f"dataset_key={value!r}", ("data", "dataset_manifest_ref", "key"), value)
    for value in (0, -1, True, False, "1", None, 1_000_001, [1]):
        add(f"dataset_schema_version={value!r}", ("data", "dataset_manifest_ref", "schema_version"), value)
    add("training_ausente", ("training",), DEL)
    add("training_con_extra", ("training", "algorithm"), "logreg")
    add("training_sin_columnas", ("training", "feature_columns"), DEL)
    add("columnas_no_lista", ("training", "feature_columns"), "a,b")
    add("columnas_vacias", ("training", "feature_columns"), [])
    add("columnas_duplicadas", ("training", "feature_columns"), ["a", "a"])
    add("columnas_257", ("training", "feature_columns"), [f"c{i}" for i in range(257)])
    for value in ("", " a", "a ", "a\tb", "a\nb", "x" * 129, 1, None, ["a"]):
        add(f"columna={value!r}", ("training", "feature_columns"), ["ok", value])
    add("base_model_ref_en_modelo_base", ("base_model_ref",),
        {"model_version": "otro_v1", "package_manifest_key": F1_KEY})
    for value in BAD_TEXTS:
        add(f"intended_use={value!r}", ("limits", "intended_use"), value)
        add(f"limitacion={value!r}", ("limits", "known_limitations"), ["ok", value])
    add("intended_use_501", ("limits", "intended_use"), "x" * 501)
    add("limitacion_301", ("limits", "known_limitations"), ["x" * 301])
    add("limitaciones_21", ("limits", "known_limitations"), ["x"] * 21)
    add("limitaciones_vacias", ("limits", "known_limitations"), [])
    add("limitaciones_no_lista", ("limits", "known_limitations"), "x")
    add("limits_sin_uso", ("limits", "intended_use"), DEL)
    add("limits_con_extra", ("limits", "approved_by"), "alguien")
    add("raiz_sin_limits", ("limits",), DEL)
    add("raiz_con_validation_aplazada", ("validation",), {"partition": "validation"})
    add("raiz_con_extra", ("owner",), "x")
    return cases


def _calibrator_negatives():
    cases = {}

    def add(name, path, value):
        cases[name] = mutate(META_CAL_DOC, path, value)

    add("calibrador_sin_base_model_ref", ("base_model_ref",), DEL)
    add("calibrador_con_training", ("training",), {"feature_columns": ["a"]})
    add("base_ref_con_extra", ("base_model_ref", "status_hint"), "x")
    add("base_ref_sin_version", ("base_model_ref", "model_version"), DEL)
    add("base_ref_sin_clave", ("base_model_ref", "package_manifest_key"), DEL)
    add("base_ref_no_objeto", ("base_model_ref",), "x")
    for value in ("", "a b", "-x", "a" * 129, 1, None):
        add(f"base_version={value!r}", ("base_model_ref", "model_version"), value)
    for value in K_BAD:
        add(f"base_key={value!r}", ("base_model_ref", "package_manifest_key"), value)
    add("calibrador_autorreferencia_directa", ("base_model_ref", "model_version"), META_CAL_DOC["model_version"])
    return cases


META_NEGATIVES = _meta_negatives()
CAL_NEGATIVES = _calibrator_negatives()
ALL_META_NEGATIVES = {**{f"base:{k}": v for k, v in META_NEGATIVES.items()}, **{f"cal:{k}": v for k, v in CAL_NEGATIVES.items()}}


def test_the_negative_matrices_are_not_trivially_small():
    assert len(META_NEGATIVES) > 150 and len(CAL_NEGATIVES) > 20
    # Se compara la serialización JSON, no la igualdad de Python (donde `True == 1` y `1 == 1.0`): cada caso debe
    # diferir de verdad del documento válido del que parte.
    assert all(rule(document) != rule(META_BASE_DOC) for document in META_NEGATIVES.values())
    assert all(rule(document) != rule(META_CAL_DOC) for document in CAL_NEGATIVES.values())
    assert all(rule(document) != rule(MANIFEST_BASE_DOC) for document in MANIFEST_NEGATIVES.values())


def _short_ids(names) -> list:
    return [f"{index:03d}_{re.sub(r'[^A-Za-z0-9_.=:-]', '', name)[:40]}" for index, name in enumerate(names)]


@pytest.mark.parametrize("name", list(ALL_META_NEGATIVES), ids=_short_ids(ALL_META_NEGATIVES))
def test_invalid_metadata_is_refused_by_the_builder_and_by_the_parser(name):
    document = ALL_META_NEGATIVES[name]
    with pytest.raises(PackageSchemaError):
        canonical_metadata_bytes(document)
    data = rule(document)
    with pytest.raises(PackageSchemaError):
        parse_metadata(data, expected_key=sha(data))


@pytest.mark.parametrize("value", GOOD_TRAINED_AT)
def test_trained_at_accepts_utc_with_z_and_an_optional_fraction_of_one_to_six_digits(value):
    document = mutate(META_BASE_DOC, ("trained_at",), value)
    assert parse_meta(document).trained_at == value
    assert json.loads(canonical_metadata_bytes(document))["trained_at"] == value


@pytest.mark.parametrize("value", ["scripts/train_tennis_model.py", "a", "a.py", "_x/y_z/w-1.2.py", "x" * 128, "dir/sub/file"])
def test_entrypoint_accepts_a_controlled_relative_path(value):
    assert parse_meta(mutate(META_BASE_DOC, ("provenance", "entrypoint"), value)).provenance.entrypoint == value


def test_inclusive_limits_are_accepted_and_round_trip():
    columns = [f"c{i:03d}" + "x" * 120 for i in range(256)]
    document = mutate(META_BASE_DOC, ("training", "feature_columns"), columns)
    document = mutate(document, ("limits", "intended_use"), "u" * 500)
    document = mutate(document, ("limits", "known_limitations"), ["l" * 300] * 20)
    data = canonical_metadata_bytes(document)
    assert len(data) <= ap.MAX_METADATA_BYTES
    parsed = parse_metadata(data, expected_key=sha(data))
    assert len(parsed.feature_columns) == 256 and len(parsed.intended_use) == 500
    assert len(parsed.known_limitations) == 20 and len(parsed.known_limitations[0]) == 300
    assert parse_meta(mutate(META_BASE_DOC, ("model_version",), "a" * 128)).model_version == "a" * 128
    assert parse_meta(mutate(META_BASE_DOC, ("provenance", "environment", "python"), "p" * 32)).provenance.python == "p" * 32


def test_the_builders_apply_their_size_caps_even_when_the_caps_are_lowered(monkeypatch):
    """Un manifiesto válido ocupa unos 650 bytes como máximo, así que su tope no se alcanza con un documento válido:
    se baja el límite para ejercitar la rama."""
    monkeypatch.setattr(ap, "MAX_PACKAGE_MANIFEST_BYTES", 100)
    with pytest.raises(PackageFormatError, match="supera el máximo"):
        canonical_package_manifest_bytes(MANIFEST_BASE_DOC)
    monkeypatch.setattr(ap, "MAX_METADATA_BYTES", 100)
    with pytest.raises(PackageFormatError, match="superan el máximo"):
        canonical_metadata_bytes(META_BASE_DOC)
    assert max(len(rule(doc)) for doc in (MANIFEST_BASE_DOC, MANIFEST_CAL_DOC)) < 700  # justifica el comentario


def test_the_canonical_size_cap_applies_to_the_builder_and_the_parser():
    columns = ["é" * 127 + chr(0x4E00 + i) for i in range(256)]
    document = mutate(META_BASE_DOC, ("training", "feature_columns"), columns)
    assert len(rule(document)) > ap.MAX_METADATA_BYTES
    with pytest.raises(PackageFormatError, match="superan el máximo"):
        canonical_metadata_bytes(document)
    with pytest.raises(PackageFormatError, match="supera el máximo"):
        parse_metadata(rule(document), expected_key=sha(rule(document)))


# --- reglas D6 y D12: claves prohibidas ---------------------------------------------------------------------

FORBIDDEN_PATHS = [
    ("event_ids",), ("event_id",), ("train_event_ids",), ("validation_event_ids",), ("test_event_ids",),
    ("labeled_event_ids",), ("file_path",), ("artifact_path",), ("model_path",), ("PATH",), ("status",), ("Status",),
    ("candidate_status",), ("test_brier",), ("test_metrics",), ("baseline_test_log_loss",),
    ("provenance", "script_path"), ("provenance", "event_ids"), ("limits", "validation_event_id"),
    ("data", "test_split"), ("data", "dataset_manifest_ref", "path"), ("provenance", "environment", "status"),
]


@pytest.mark.parametrize("path", FORBIDDEN_PATHS, ids=["/".join(p) for p in FORBIDDEN_PATHS])
@pytest.mark.parametrize("base_doc", [META_BASE_DOC, META_CAL_DOC], ids=["base", "calibrador"])
def test_forbidden_keys_are_refused_at_any_level_with_a_specific_message(base_doc, path):
    document = mutate(base_doc, path, ["espn_1", "espn_2"] if path[-1].endswith("ids") else "x")
    with pytest.raises(PackageSchemaError, match="clave prohibida"):
        canonical_metadata_bytes(document)
    data = rule(document)
    with pytest.raises(PackageSchemaError, match="clave prohibida"):
        parse_metadata(data, expected_key=sha(data))


def test_forbidden_keys_are_also_found_inside_lists_and_in_manifests():
    document = mutate(META_BASE_DOC, ("training", "feature_columns"), [{"event_ids": []}])
    with pytest.raises(PackageSchemaError, match="clave prohibida"):
        canonical_metadata_bytes(document)
    for path in (("file_path",), ("artifact", "artifact_path"), ("metadata", "status"), ("test_brier",), ("event_ids",)):
        manifest = mutate(MANIFEST_BASE_DOC, path, "x")
        with pytest.raises(PackageSchemaError, match="clave prohibida"):
            canonical_package_manifest_bytes(manifest)


def test_legitimate_keys_are_not_mistaken_for_forbidden_ones():
    for document in (META_BASE_DOC, META_CAL_DOC):
        assert canonical_metadata_bytes(document)
    for document in (MANIFEST_BASE_DOC, MANIFEST_CAL_DOC):
        assert canonical_package_manifest_bytes(document)


def test_a_deeply_nested_python_document_is_a_schema_error_not_a_recursion_error():
    node = current = {}
    for _ in range(3000):
        current["a"] = {}
        current = current["a"]
    with pytest.raises(PackageSchemaError):
        canonical_metadata_bytes(node)
    with pytest.raises(PackageSchemaError):
        canonical_package_manifest_bytes(node)


@pytest.mark.parametrize("kind_doc", [META_BASE_DOC, META_CAL_DOC], ids=["base", "calibrador"])
@pytest.mark.parametrize("not_a_dict", [None, [], "x", 1, (), b"{}"])
def test_metadata_must_be_an_object(kind_doc, not_a_dict):
    with pytest.raises(PackageSchemaError):
        canonical_metadata_bytes(not_a_dict)
    with pytest.raises(PackageSchemaError):
        canonical_package_manifest_bytes(not_a_dict)


def test_role_rules_are_enforced_in_both_directions():
    """Punto 4 pedido: un calibrador sin base_model_ref es rechazado, y un modelo base con ese campo también."""
    # Los mensajes son específicos del rol (no el genérico de «claves inválidas»): el rechazo no depende solo de las
    # claves exactas.
    with pytest.raises(PackageSchemaError, match="obligatorio en un calibrador"):
        canonical_metadata_bytes(mutate(META_CAL_DOC, ("base_model_ref",), DEL))
    with pytest.raises(PackageSchemaError, match="un modelo base no puede llevarlo"):
        canonical_metadata_bytes(mutate(META_BASE_DOC, ("base_model_ref",), META_CAL_DOC["base_model_ref"]))
    with pytest.raises(PackageSchemaError, match="obligatorio en un modelo base"):
        canonical_metadata_bytes(mutate(META_BASE_DOC, ("training",), DEL))
    with pytest.raises(PackageSchemaError, match="un calibrador no lo lleva"):
        canonical_metadata_bytes(mutate(META_CAL_DOC, ("training",), {"feature_columns": ["a"]}))
    for document in (mutate(META_CAL_DOC, ("base_model_ref",), DEL), mutate(META_BASE_DOC, ("training",), DEL)):
        data = rule(document)
        with pytest.raises(PackageSchemaError, match="obligatorio"):
            parse_metadata(data, expected_key=sha(data))


def test_a_calibrator_cannot_reference_itself_directly_but_other_formats_are_not_resolved():
    own = mutate(META_CAL_DOC, ("base_model_ref", "model_version"), "pkg_calibrator_v1")
    with pytest.raises(PackageSchemaError, match="a sí mismo"):
        canonical_metadata_bytes(own)
    parsed = parse_meta(META_CAL_DOC)
    assert parsed.base_model_ref.package_manifest_key == F1_KEY  # solo formato: nada se resuelve ni se lee


# =====================================================================
# Manifiesto de paquete: esquema
# =====================================================================


def _manifest_negatives():
    cases = {}

    def add(name, path, value, base=MANIFEST_BASE_DOC):
        cases[name] = mutate(base, path, value)

    for value in (2, 0, True, "1", None):
        add(f"schema_version={value!r}", ("schema_version",), value)
    for value in ("model_artifact_metadata", "", None):
        add(f"document_type={value!r}", ("document_type",), value)
    for value in ("", "a b", "a" * 129, 1, None):
        add(f"model_version={value!r}", ("model_version",), value)
    for value in K_BAD:
        add(f"artifact.key={value!r}", ("artifact", "key"), value)
        add(f"metadata.key={value!r}", ("metadata", "key"), value)
    for value in ("pickle", "joblib", "safe_json_b2", "", None, 1, "SAFE_JSON_B1"):
        add(f"artifact.format={value!r}", ("artifact", "format"), value)
    for value in (2, 0, True, "1", None):
        add(f"artifact.schema_version={value!r}", ("artifact", "schema_version"), value)
        add(f"metadata.schema_version={value!r}", ("metadata", "schema_version"), value)
    for value in ("pickle_v1", "", None, 1):
        add(f"artifact.model_type={value!r}", ("artifact", "model_type"), value)
    add("artifact_sin_formato", ("artifact", "format"), DEL)
    add("artifact_con_extra", ("artifact", "size_bytes"), 10)
    add("metadata_con_extra", ("metadata", "size_bytes"), 10)
    add("metadata_sin_clave", ("metadata", "key"), DEL)
    add("artifact_no_objeto", ("artifact",), "x")
    add("metadata_no_objeto", ("metadata",), [])
    add("raiz_con_extra", ("created_at",), "2026-11-21T20:00:00Z")
    add("raiz_sin_artifact", ("artifact",), DEL)
    add("raiz_sin_metadata", ("metadata",), DEL)
    add("claves_iguales", ("metadata", "key"), A1_KEY)
    return cases


MANIFEST_NEGATIVES = _manifest_negatives()


@pytest.mark.parametrize("name", list(MANIFEST_NEGATIVES), ids=_short_ids(MANIFEST_NEGATIVES))
def test_invalid_manifests_are_refused_by_the_builder_and_by_the_parser(name):
    document = MANIFEST_NEGATIVES[name]
    with pytest.raises(PackageSchemaError):
        canonical_package_manifest_bytes(document)
    data = rule(document)
    with pytest.raises(PackageSchemaError):
        parse_package_manifest(data, expected_key=sha(data))


@pytest.mark.parametrize("model_type", [BASE_TYPE, PLATT_TYPE])
def test_the_manifest_accepts_both_safe_model_types(model_type):
    document = mutate(MANIFEST_BASE_DOC, ("artifact", "model_type"), model_type)
    assert parse_manifest(document).artifact.model_type == model_type


@pytest.mark.parametrize("bad", K_BAD + [b"a" * 64, bytearray(b"a" * 64)])
def test_keys_inside_documents_are_validated_like_store_keys_and_the_internal_layout_is_rejected(bad):
    assert not (isinstance(bad, str) and re.fullmatch(r"[0-9a-f]{64}", bad))
    with pytest.raises(PackageSchemaError, match="clave del almacén"):
        canonical_package_manifest_bytes(mutate(MANIFEST_BASE_DOC, ("artifact", "key"), bad))
    with pytest.raises(PackageSchemaError, match="clave del almacén"):
        canonical_metadata_bytes(mutate(META_CAL_DOC, ("base_model_ref", "package_manifest_key"), bad))


# =====================================================================
# verify_package: ida y vuelta real con LocalFilesystemStore
# =====================================================================


def test_the_golden_base_package_verifies_from_the_store(store):
    publish_vectors(store, "A1", "M1", "F1")
    package = verify_package(store, F1_KEY, expected_model_version="pkg_example_v1")
    assert isinstance(package, VerifiedPackage) and package.manifest_key == F1_KEY
    assert package.manifest.artifact.key == A1_KEY and package.metadata.model_version == "pkg_example_v1"
    assert type(package.model).__name__ == "ImputedLogRegModel" and package.model.input_columns == tuple(COLUMNS)
    assert package.metadata.feature_columns == package.model.input_columns
    assert 0.0 < package.model.predict_proba_vector([3.0, float("nan"), 0.0]) < 1.0


def test_the_golden_calibrator_package_verifies_without_resolving_any_reference(store):
    publish_vectors(store, "A2", "M2", "F2")  # el modelo base (F1) y el manifiesto de instantánea NO están publicados
    assert store.exists(F1_KEY) is False and store.exists(DATASET_KEY) is False
    package = verify_package(store, F2_KEY, expected_model_version="pkg_calibrator_v1")
    assert type(package.model).__name__ == "PlattModel"
    assert package.metadata.base_model_ref.package_manifest_key == F1_KEY
    assert package.metadata.dataset_manifest_ref.key == DATASET_KEY
    assert 0.0 < package.model.calibrate(0.5) < 1.0


def test_verification_works_with_the_read_only_view_and_never_writes(store, root):
    publish_vectors(store, "A1", "M1", "F1")
    before = listing(root)
    reader = store.reader()
    assert not hasattr(reader, "put")
    verify_package(reader, F1_KEY, expected_model_version="pkg_example_v1")
    verify_package(store, F1_KEY, expected_model_version="pkg_example_v1")
    assert listing(root) == before


def test_a_verified_package_is_not_an_allowed_model_and_never_touches_the_registry(store):
    registry = REPO_ROOT / "config" / "model_registry.json"
    registry_before = registry.read_bytes()
    publish_vectors(store, "A1", "M1", "F1")
    package = verify_package(store, F1_KEY, expected_model_version="pkg_example_v1")
    assert {field.name for field in dataclasses.fields(package)} == {"manifest_key", "manifest", "metadata", "model"}
    assert not any(hasattr(package, name) for name in ("status", "allowed", "approved", "promoted"))
    assert registry.read_bytes() == registry_before


@pytest.mark.parametrize("missing", ["manifest", "artifact", "metadata"])
def test_a_missing_blob_propagates_the_store_error_unwrapped(store, root, missing):
    publish_vectors(store, "A1", "M1", "F1")
    key = {"manifest": F1_KEY, "artifact": A1_KEY, "metadata": M1_KEY}[missing]
    os.remove(blob_path(root, key))  # solo para fabricar la ausencia del blob
    with pytest.raises(ArtifactNotFoundError) as excinfo:
        verify_package(store, F1_KEY, expected_model_version="pkg_example_v1")
    assert not isinstance(excinfo.value, ArtifactPackageError)


@pytest.mark.parametrize("corrupted", ["manifest", "artifact", "metadata"])
def test_a_corrupted_blob_propagates_the_store_integrity_error(store, root, corrupted):
    publish_vectors(store, "A1", "M1", "F1")
    key = {"manifest": F1_KEY, "artifact": A1_KEY, "metadata": M1_KEY}[corrupted]
    path = blob_path(root, key)
    original = path.read_bytes()
    os.chmod(path, 0o644)
    path.write_bytes(original[:-2] + b"X\n")
    with pytest.raises(ArtifactIntegrityError) as excinfo:
        verify_package(store, F1_KEY, expected_model_version="pkg_example_v1")
    assert not isinstance(excinfo.value, ArtifactPackageError)


def test_metadata_of_another_model_is_a_consistency_error(store):
    other = publish_package(store, "base", "pkg_other_v1")
    mixed_artifact = canonical_bytes(artifact_doc("base", "pkg_mixed_v1"))
    # manifiesto que apunta al artefacto de un modelo y a los metadatos de OTRO
    manifest = canonical_package_manifest_bytes(manifest_doc("pkg_mixed_v1", mixed_artifact, BASE_TYPE, canonical_metadata_bytes(metadata_doc("base", "pkg_other_v1"))))
    store.put(mixed_artifact)
    key = store.put(manifest)
    with pytest.raises(PackageConsistencyError, match="otro model_version"):
        verify_package(store, key, expected_model_version="pkg_mixed_v1")
    assert other["manifest"] != key


def test_an_unexpected_model_version_is_refused_before_reading_anything_else():
    reader = FakeReader({F1_KEY: F1_BYTES, A1_KEY: A1_BYTES, M1_KEY: M1_BYTES})
    with pytest.raises(PackageConsistencyError, match="no es el esperado"):
        verify_package(reader, F1_KEY, expected_model_version="pkg_otro_v1")
    assert reader.calls == [F1_KEY]


@pytest.mark.parametrize("bad", ["", "a b", None, 1, "a" * 129, b"x"])
def test_an_invalid_expected_model_version_is_refused_before_any_read(bad):
    reader = FakeReader({F1_KEY: F1_BYTES})
    with pytest.raises(PackageSchemaError):
        verify_package(reader, F1_KEY, expected_model_version=bad)
    assert reader.calls == []


@pytest.mark.parametrize("bad", ["sha256/ab/" + "a" * 64, "A" * 64, "a" * 63, "", None, 5, b"a" * 64])
def test_an_invalid_manifest_key_raises_invalid_artifact_key_error_before_any_read(bad):
    reader = FakeReader()
    with pytest.raises(InvalidArtifactKeyError):
        verify_package(reader, bad, expected_model_version="pkg_example_v1")
    assert reader.calls == []


def test_the_reader_must_be_an_artifact_reader_and_the_version_is_keyword_only(store):
    publish_vectors(store, "A1", "M1", "F1")
    with pytest.raises(TypeError):
        verify_package(object(), F1_KEY, expected_model_version="pkg_example_v1")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        verify_package(store, F1_KEY, "pkg_example_v1")  # type: ignore[misc]
    with pytest.raises(TypeError):
        verify_package(store, F1_KEY)  # type: ignore[call-arg]


def test_the_manifest_type_must_match_the_loaded_artifact(store):
    artifact = canonical_bytes(artifact_doc("base", "pkg_x_v1"))
    metadata = canonical_metadata_bytes(metadata_doc("cal", "pkg_x_v1"))
    manifest = canonical_package_manifest_bytes(manifest_doc("pkg_x_v1", artifact, PLATT_TYPE, metadata))
    for blob in (artifact, metadata):
        store.put(blob)
    key = store.put(manifest)
    with pytest.raises(PackageConsistencyError, match="artifact.model_type"):
        verify_package(store, key, expected_model_version="pkg_x_v1")


def test_metadata_with_another_model_type_than_the_manifest_is_a_consistency_error(store):
    artifact = canonical_bytes(artifact_doc("base", "pkg_y_v1"))
    metadata = canonical_metadata_bytes(metadata_doc("cal", "pkg_y_v1"))
    manifest = canonical_package_manifest_bytes(manifest_doc("pkg_y_v1", artifact, BASE_TYPE, metadata))
    for blob in (artifact, metadata):
        store.put(blob)
    key = store.put(manifest)
    with pytest.raises(PackageConsistencyError, match="otro model_type"):
        verify_package(store, key, expected_model_version="pkg_y_v1")


def test_feature_columns_must_equal_the_artifact_input_columns_in_value_and_order(store):
    reordered = [COLUMNS[1], COLUMNS[0], COLUMNS[2]]
    keys = publish_package(store, "base", "pkg_z_v1", columns=COLUMNS, artifact_columns=reordered)
    with pytest.raises(PackageConsistencyError, match="feature_columns"):
        verify_package(store, keys["manifest"], expected_model_version="pkg_z_v1")
    other = publish_package(store, "base", "pkg_w_v1", columns=COLUMNS, artifact_columns=["a", "b", "c"])
    with pytest.raises(PackageConsistencyError, match="feature_columns"):
        verify_package(store, other["manifest"], expected_model_version="pkg_w_v1")


def test_an_artifact_that_b1_rejects_is_wrapped_as_package_artifact_error_keeping_the_cause(store):
    garbage = b"esto no es un artefacto B1\n"
    metadata = canonical_metadata_bytes(metadata_doc("base", "pkg_g_v1"))
    manifest = canonical_package_manifest_bytes(manifest_doc("pkg_g_v1", garbage, BASE_TYPE, metadata))
    for blob in (garbage, metadata):
        store.put(blob)
    key = store.put(manifest)
    with pytest.raises(PackageArtifactError) as excinfo:
        verify_package(store, key, expected_model_version="pkg_g_v1")
    assert isinstance(excinfo.value.__cause__, SafeArtifactError)
    assert not isinstance(excinfo.value, SafeArtifactError)


def test_an_artifact_with_another_model_version_than_the_manifest_is_rejected_through_b1(store):
    artifact = canonical_bytes(artifact_doc("base", "pkg_inner_v1"))
    metadata = canonical_metadata_bytes(metadata_doc("base", "pkg_outer_v1"))
    manifest = canonical_package_manifest_bytes(manifest_doc("pkg_outer_v1", artifact, BASE_TYPE, metadata))
    for blob in (artifact, metadata):
        store.put(blob)
    key = store.put(manifest)
    with pytest.raises(PackageArtifactError) as excinfo:
        verify_package(store, key, expected_model_version="pkg_outer_v1")
    assert isinstance(excinfo.value.__cause__, SafeArtifactError)


def test_store_errors_propagate_unchanged_and_are_never_disguised_as_package_errors():
    for error in (StoreConfigurationError("raíz no disponible"), ArtifactIntegrityError("hash"), ArtifactNotFoundError("k")):
        reader = FakeReader(error=error)
        with pytest.raises(type(error)) as excinfo:
            verify_package(reader, F1_KEY, expected_model_version="pkg_example_v1")
        assert excinfo.value is error and not isinstance(excinfo.value, ArtifactPackageError)


def test_the_package_layer_rechecks_each_hash_even_if_the_reader_misbehaves():
    wrong_manifest = FakeReader({F1_KEY: F2_BYTES})
    with pytest.raises(PackageFormatError, match="SHA-256 distinto"):
        verify_package(wrong_manifest, F1_KEY, expected_model_version="pkg_example_v1")
    wrong_artifact = FakeReader({F1_KEY: F1_BYTES, A1_KEY: A2_BYTES})
    with pytest.raises(PackageArtifactError) as excinfo:
        verify_package(wrong_artifact, F1_KEY, expected_model_version="pkg_example_v1")
    assert isinstance(excinfo.value.__cause__, SafeArtifactError)
    wrong_metadata = FakeReader({F1_KEY: F1_BYTES, A1_KEY: A1_BYTES, M1_KEY: M2_BYTES})
    with pytest.raises(PackageFormatError, match="SHA-256 distinto"):
        verify_package(wrong_metadata, F1_KEY, expected_model_version="pkg_example_v1")


def test_a_reader_returning_non_bytes_is_refused():
    for value in (bytearray(F1_BYTES), F1_BYTES.decode("ascii"), None):
        with pytest.raises(PackageFormatError):
            verify_package(FakeReader({F1_KEY: value}), F1_KEY, expected_model_version="pkg_example_v1")


def test_a_base_ref_equal_to_the_own_manifest_key_is_a_consistency_error_without_reading_the_base_package(monkeypatch):
    """Defensa en profundidad contra una autorreferencia por clave. Construirla exigiría encontrar un punto fijo de la
    composición de hashes, lo que se considera computacionalmente inviable. Por eso se simula sustituyendo
    `parse_metadata` por una versión que devuelve la referencia a la propia clave del manifiesto."""
    blobs = {F2_KEY: F2_BYTES, A2_KEY: A2_BYTES, M2_KEY: M2_BYTES}
    honest = FakeReader(blobs)
    package = verify_package(honest, F2_KEY, expected_model_version="pkg_calibrator_v1")
    assert package.metadata.base_model_ref.package_manifest_key == F1_KEY != F2_KEY  # control: sin la simulación verifica
    forged = dataclasses.replace(
        parse_metadata(M2_BYTES, expected_key=M2_KEY),
        base_model_ref=ap.BaseModelRef(model_version="pkg_example_v1", package_manifest_key=F2_KEY),
    )
    monkeypatch.setattr(ap, "parse_metadata", lambda data, *, expected_key: forged)
    reader = FakeReader(blobs)
    with pytest.raises(PackageConsistencyError, match="autorreferencia por clave"):
        verify_package(reader, F2_KEY, expected_model_version="pkg_calibrator_v1")
    assert reader.calls == [F2_KEY, A2_KEY, M2_KEY], "no se lee ni se resuelve ningún otro blob (ni el paquete base)"
    assert F1_KEY not in reader.calls and DATASET_KEY not in reader.calls


def test_the_three_blobs_are_read_in_order_and_each_exactly_once():
    reader = FakeReader({F1_KEY: F1_BYTES, A1_KEY: A1_BYTES, M1_KEY: M1_BYTES})
    verify_package(reader, F1_KEY, expected_model_version="pkg_example_v1")
    assert reader.calls == [F1_KEY, A1_KEY, M1_KEY]


def test_a_dynamic_consistent_package_of_each_kind_verifies(store):
    base = publish_package(store, "base", "pkg_dyn_base_v1")
    calibrator = publish_package(store, "cal", "pkg_dyn_cal_v1")
    assert verify_package(store, base["manifest"], expected_model_version="pkg_dyn_base_v1").model.input_columns == tuple(COLUMNS)
    assert verify_package(store, calibrator["manifest"], expected_model_version="pkg_dyn_cal_v1").metadata.base_model_ref is not None


# =====================================================================
# Aislamiento: el módulo está sin cablear y no ejecuta nada del entorno
# =====================================================================

ALLOWED_IMPORTS = {
    "__future__", "dataclasses", "datetime", "hashlib", "hmac", "json", "re", "typing",
    "src.models.safe_artifact_format", "src.storage.artifact_store",
}


def _imports_of(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_the_module_imports_only_the_allowed_modules_and_never_the_local_backend_or_the_project_config():
    imports = _imports_of(MODULE_PATH)
    assert imports == ALLOWED_IMPORTS
    forbidden = ("joblib", "pickle", "numpy", "sklearn", "scipy", "importlib", "os", "subprocess", "config", "src.evaluation",
                 "src.calibration", "src.orchestration", "src.storage.local_filesystem_store", "scripts")
    assert not [name for name in imports if name.startswith(forbidden)]


def test_the_module_never_opens_files_evaluates_code_or_writes_to_the_store():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "vars"}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & {"put", "environ", "getenv", "write", "write_bytes", "write_text", "dump", "dumps_to_file"}
    assert "src.storage.artifact_store" in _imports_of(MODULE_PATH)


ISOLATED_SCRIPT = """
import json, sys
from src.models import artifact_package as ap
from src.storage.artifact_store import ArtifactReader
blobs = {k: bytes.fromhex(v) for k, v in json.load(sys.stdin).items()}
class R(ArtifactReader):
    def get(self, key): return blobs[key]
    def exists(self, key): return key in blobs
    def verify(self, key): return None
manifest_key = sys.argv[1]
package = ap.verify_package(R(), manifest_key, expected_model_version="pkg_example_v1")
FORBIDDEN = ("joblib", "pickle", "cloudpickle", "dill", "shelve", "numpy", "scipy", "sklearn", "ctypes",
             "src.storage.local_filesystem_store", "config", "config.settings", "src.evaluation", "src.calibration",
             "src.orchestration", "src.models.registry", "src.models.model_registry_policy")
print(json.dumps({"model": type(package.model).__name__,
                  "forbidden": sorted(m for m in FORBIDDEN if m in sys.modules)}))
"""


def test_a_fresh_interpreter_verifies_a_package_without_loading_any_deserializer_numeric_or_project_module():
    blobs = {key: data.hex() for data, key in (VECTORS["A1"], VECTORS["M1"], VECTORS["F1"])}
    result = subprocess.run(
        [sys.executable, "-c", ISOLATED_SCRIPT, F1_KEY], input=json.dumps(blobs), capture_output=True, text=True,
        cwd=REPO_ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {"model": "ImputedLogRegModel", "forbidden": []}


def test_nothing_in_src_scripts_or_config_imports_the_package_module_automatically_and_the_package_inits_stay_empty():
    offenders = []
    for top in ("src", "scripts", "config"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            if path.resolve() == MODULE_PATH.resolve():
                continue
            if "artifact_package" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    for init in ("src/models/__init__.py", "src/storage/__init__.py"):
        assert (REPO_ROOT / init).read_text(encoding="utf-8") == ""


# =====================================================================
# Plantilla de model card (D20) y especificación
# =====================================================================

TEMPLATE_HEADINGS = (
    "## 1. Identificación", "## 2. Uso previsto y límites", "## 3. Procedencia", "## 4. Datos",
    "## 5. Entrenamiento", "## 6. Validación", "## 7. Resultado del test", "## 8. Riesgos y limitaciones",
    "## 9. Aprobación",
)


def test_the_model_card_template_exists_in_governance_models_and_is_a_template_not_a_model_card():
    assert TEMPLATE_PATH.is_file()
    assert (REPO_ROOT / "governance" / "calibration" / "preregistration_template.md").is_file()
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()
    text = " ".join(raw.split())  # las frases pueden estar partidas en varias líneas
    assert lines[0].startswith("# MODEL CARD")
    for heading in TEMPLATE_HEADINGS:
        assert any(line.startswith(heading) for line in lines), heading
    assert "**Estado**: PLANTILLA" in text and "no es una model card real" in text
    assert "no es una model card de producción" in text and "no aprueba nada" in text
    assert "Nunca" in text and "event_id" in text  # la prohibición está enunciada
    assert "métricas de test solo las registra el evaluador" in text
    assert "Un paquete verificado" in text and "no lo activa" in text


def test_the_model_card_template_contains_no_event_identifiers_absolute_paths_or_approval_claims():
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:espn|kalshi|mlb)_[a-z_]*[0-9]{3,}\b", text)
    assert not re.search(r"\bKX[A-Z]+-[0-9]{2}[A-Z]{3}[0-9]{2}", text)
    assert not re.search(r"(?:^|[\s(`])/(?:Users|home|private|var|tmp|Volumes|etc)/", text, re.M)
    assert not re.search(r"\b[0-9a-f]{64}\b", text), "la plantilla no lleva claves ni hashes reales"
    assert not re.search(r"Estado\*\*: *(?:ALLOWED|APROBAD)", text)


def test_the_specification_documents_the_constants_the_rules_and_every_fixed_vector():
    text = SPEC_PATH.read_text(encoding="utf-8")
    for fact in ("65536", "4096", "500", "300", "safe_json_b1", "model_artifact_metadata", "artifact_package_manifest",
                 "validate_key", "PackageArtifactError", "ALLOWED"):
        assert fact in text, fact
    for name, (data, key) in VECTORS.items():
        assert data.decode("ascii").rstrip("\n") in text, f"vector {name} ausente de la especificación"
        assert key in text, f"clave de {name} ausente de la especificación"
    assert DATASET_KEY in text
