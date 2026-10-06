"""Contrato del almacén de artefactos (`src/storage/artifact_store.py`): claves, errores tipados y la
separación lector/escritor. Solo bytes sintéticos; no se toca el sistema de archivos ni el repositorio."""
from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path

import pytest

from src.storage import artifact_store
from src.storage.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPublishError,
    ArtifactReader,
    ArtifactStore,
    ArtifactStoreError,
    InvalidArtifactKeyError,
    StoreConfigurationError,
    compute_key,
    validate_key,
)

SRC_CONTRACT = Path(artifact_store.__file__)
VALID_KEY = hashlib.sha256(b"x").hexdigest()


# --- compute_key ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"x", b"\x00\xff" * 1000, "ñandú".encode("utf-8")])
def test_compute_key_matches_hashlib_sha256_hex_lowercase(data):
    key = compute_key(data)
    assert key == hashlib.sha256(data).hexdigest()
    assert len(key) == 64 and key == key.lower()


def test_compute_key_is_deterministic_and_content_sensitive():
    assert compute_key(b"a") == compute_key(b"a")
    assert compute_key(b"a") != compute_key(b"b")


class _BytesSubclass(bytes):
    pass


@pytest.mark.parametrize("data", [bytearray(b"x"), memoryview(b"x"), "x", None, 1, _BytesSubclass(b"x")])
def test_compute_key_rejects_anything_that_is_not_exactly_bytes(data):
    with pytest.raises(TypeError):
        compute_key(data)


# --- validate_key --------------------------------------------------------------------------------------------


def test_validate_key_accepts_exactly_64_lowercase_hex_and_returns_it():
    assert validate_key(VALID_KEY) == VALID_KEY


class _StrSubclass(str):
    pass


@pytest.mark.parametrize(
    "key",
    [
        VALID_KEY.upper(),
        VALID_KEY[:-1],
        VALID_KEY + "0",
        "g" * 64,
        "../" + VALID_KEY[3:],
        VALID_KEY[:2] + "/" + VALID_KEY[3:],
        VALID_KEY[:10] + "\x00" + VALID_KEY[11:],
        VALID_KEY + "\n",
        " " + VALID_KEY[1:],
        "٣" * 64,
        "",
        None,
        VALID_KEY.encode("ascii"),
        12345,
        _StrSubclass(VALID_KEY),
    ],
)
def test_validate_key_rejects_every_other_value(key):
    with pytest.raises(InvalidArtifactKeyError):
        validate_key(key)


# --- errores y clases abstractas -----------------------------------------------------------------------------


def test_the_five_typed_errors_all_derive_from_artifact_store_error_and_there_are_no_others():
    typed = (
        ArtifactNotFoundError,
        ArtifactIntegrityError,
        InvalidArtifactKeyError,
        StoreConfigurationError,
        ArtifactPublishError,
    )
    for error in typed:
        assert issubclass(error, ArtifactStoreError)
        assert error is not ArtifactStoreError
    public_errors = {
        name
        for name, value in vars(artifact_store).items()
        if inspect.isclass(value) and issubclass(value, Exception) and not name.startswith("_")
    }
    assert public_errors == {"ArtifactStoreError"} | {error.__name__ for error in typed}
    assert issubclass(ArtifactStoreError, Exception)


def test_abstract_interfaces_cannot_be_instantiated_and_the_reader_has_no_put():
    with pytest.raises(TypeError):
        ArtifactReader()
    with pytest.raises(TypeError):
        ArtifactStore()
    assert not hasattr(ArtifactReader, "put")
    assert hasattr(ArtifactStore, "put")
    assert issubclass(ArtifactStore, ArtifactReader)
    assert ArtifactReader.__abstractmethods__ == {"get", "exists", "verify"}
    assert ArtifactStore.__abstractmethods__ == {"get", "exists", "verify", "put"}


def test_the_public_api_has_no_put_result_and_put_is_annotated_as_returning_str():
    assert not hasattr(artifact_store, "PutResult")
    assert inspect.signature(ArtifactStore.put).return_annotation in (str, "str")
    assert list(inspect.signature(ArtifactStore.put).parameters) == ["self", "data"]


class _MinimalStore(ArtifactStore):
    def put(self, data):
        return compute_key(data)

    def get(self, key):
        raise ArtifactNotFoundError(key)

    def exists(self, key):
        return False

    def verify(self, key):
        raise ArtifactNotFoundError(key)


def test_a_concrete_subclass_is_a_store_and_a_reader():
    store = _MinimalStore()
    assert isinstance(store, ArtifactStore) and isinstance(store, ArtifactReader)
    assert store.put(b"x") == VALID_KEY


@pytest.mark.parametrize(
    "method",
    [ArtifactReader.get, ArtifactReader.exists, ArtifactReader.verify, ArtifactStore.put],
    ids=["get", "exists", "verify", "put"],
)
def test_every_interface_method_documents_that_it_can_raise_store_configuration_error(method):
    assert "StoreConfigurationError" in method.__doc__


def test_store_configuration_error_documents_its_causes_and_that_permissions_are_not_modified():
    doc = " ".join(StoreConfigurationError.__doc__.lower().split())
    for phrase in (
        "raíz cambiada o no disponible",
        "directorios internos preexistentes con permisos para grupo u otros",
        "sin modificar sus permisos",
        "`put`, `get`, `exists` y `verify`",
    ):
        assert phrase in doc, phrase


def test_exists_documents_that_it_does_not_always_return_bool():
    doc = " ".join(ArtifactReader.exists.__doc__.split())
    assert "no devuelve siempre `bool`" in doc and "`StoreConfigurationError`" in doc


# --- aislamiento del módulo de contrato ----------------------------------------------------------------------


def _imports_of(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_the_contract_module_imports_only_hashlib_re_abc_and_future_and_never_touches_the_filesystem():
    assert _imports_of(SRC_CONTRACT) == {"__future__", "hashlib", "re", "abc"}
    tree = ast.parse(SRC_CONTRACT.read_text(encoding="utf-8"), filename=str(SRC_CONTRACT))
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "open" not in called and "eval" not in called and "exec" not in called and "__import__" not in called
