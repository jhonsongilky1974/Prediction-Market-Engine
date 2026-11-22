"""PR-4: cargadores seguros de tenis desde el almacén de paquetes (`src/models/package_loaders.py`).

Bloques: A (modelo base), B (calibrador y su correspondencia con la base), C (ayudante de configuración), D (errores
inesperados y de uso, que deben seguir siendo visibles), E (sin fallback al formato heredado, solo lectura y sin
consultar el entorno) y F (aislamiento). Todos los paquetes son sintéticos, en un almacén temporal.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.models import package_loaders as loaders
from src.models.artifact_package import VerifiedPackage, verify_package
from src.models.model_registry_v2 import PackageRegistryError
from src.models.package_loaders import load_base, load_calibrator, open_store_reader_from_environment
from src.models.safe_artifact_format import ImputedLogRegModel, PlattModel
from src.storage import local_filesystem_store as lfs
from src.storage.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPublishError,
    ArtifactReader,
    InvalidArtifactKeyError,
    StoreConfigurationError,
)
from src.storage.local_filesystem_store import LocalFilesystemStore
from tests.unit.package_loader_factories import (
    Package,
    base_entry,
    calibrator_entry,
    publish,
    publish_base,
    publish_calibrator,
    registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "models" / "package_loaders.py"
LOGGER = "src.models.package_loaders"
VALIDATION = re.compile(r"validación: Package(Format|Schema|Consistency|Artifact)Error")


@pytest.fixture
def root(tmp_path) -> Path:
    path = tmp_path / "store_root"
    path.mkdir()
    os.chmod(path, 0o700)
    return path


@pytest.fixture
def store(root) -> LocalFilesystemStore:
    return LocalFilesystemStore(root, max_blob_bytes=loaders.MAX_BLOB_BYTES)


@pytest.fixture
def reader(store) -> ArtifactReader:
    return store.reader()


class SpyReader(ArtifactReader):
    """Registra cada llamada y delega en un lector real."""

    def __init__(self, inner: ArtifactReader) -> None:
        self.inner, self.calls = inner, []

    def get(self, key):
        self.calls.append(("get", key))
        return self.inner.get(key)

    def exists(self, key):
        self.calls.append(("exists", key))
        return self.inner.exists(key)

    def verify(self, key):
        self.calls.append(("verify", key))
        return self.inner.verify(key)


class RaisingReader(ArtifactReader):
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def get(self, key):
        raise self.error

    def exists(self, key):
        raise self.error

    def verify(self, key):
        raise self.error


def warnings_of(caplog) -> list:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]


@pytest.fixture(autouse=True)
def _capture(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)


def blob(root: Path, key: str) -> Path:
    return Path(root) / "sha256" / key[:2] / key


def snapshot(root: Path) -> list:
    return sorted(os.path.relpath(os.path.join(c, n), root) for c, d, f in os.walk(root) for n in d + f)


def assert_refused(result, caplog, *fragments) -> str:
    assert result is None
    records = warnings_of(caplog)
    assert len(records) == 1, [r.getMessage() for r in records]  # un solo motivo por fallo
    message = records[0].getMessage()
    for fragment in fragments:
        assert fragment in message, message
    return message


# =====================================================================
# A. Modelo base
# =====================================================================


def test_load_base_returns_exactly_the_verified_package_without_adapting_or_adding_anything(store, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    result = load_base(reader, registry(base_entry(package)))

    assert type(result) is VerifiedPackage
    assert result == verify_package(reader, package.manifest_key, expected_model_version="tennis_base_v2_a")
    assert isinstance(result.model, ImputedLogRegModel)
    assert result.manifest_key == package.manifest_key
    assert not hasattr(result, "predict_proba") and not hasattr(result.model, "predict_proba")  # sin adaptar la inferencia
    assert warnings_of(caplog) == []


def test_load_base_reads_only_the_three_blobs_of_the_selected_package(store, reader):
    package = publish_base(store, "tennis_base_v2_a")
    other = publish_base(store, "tennis_base_v2_b")
    spy = SpyReader(reader)
    load_base(spy, registry(base_entry(package), base_entry(other, status="INVALID")))
    assert [kind for kind, _ in spy.calls] == ["get", "get", "get"]
    assert {key for _, key in spy.calls} == {package.manifest_key, package.artifact_key, package.metadata_key}


@pytest.mark.parametrize("entries", ["empty", "only-invalid", "only-rejected", "only-calibrator"])
def test_no_candidate_is_no_model_with_one_reason_and_no_reads(store, reader, caplog, entries):
    package = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", package)
    chosen = {
        "empty": [], "only-invalid": [base_entry(package, status="INVALID")],
        "only-rejected": [base_entry(package, status="REJECTED_CANDIDATE")],
        "only-calibrator": [calibrator_entry(calibrator, package.model_version)],
    }[entries]
    spy = SpyReader(reader)
    assert_refused(load_base(spy, registry(*chosen)), caplog, "selección: NO_CANDIDATE")
    assert spy.calls == []


def test_an_ambiguous_selection_is_no_model_without_reading_anything_even_if_both_packages_are_valid(store, reader, caplog):
    first, second = publish_base(store, "tennis_base_v2_a"), publish_base(store, "tennis_base_v2_b", variant=1)
    spy = SpyReader(reader)
    assert_refused(load_base(spy, registry(base_entry(first), base_entry(second))), caplog, "selección: AMBIGUOUS")
    assert spy.calls == []  # no elige ninguno: ni siquiera lee


@pytest.mark.parametrize("missing", ["manifest", "artifact", "metadata"])
def test_an_absent_blob_is_no_model_with_a_read_reason(store, root, reader, caplog, missing):
    package = publish_base(store, "tennis_base_v2_a")
    blob(root, {"manifest": package.manifest_key, "artifact": package.artifact_key,
                "metadata": package.metadata_key}[missing]).unlink()
    assert_refused(load_base(reader, registry(base_entry(package))), caplog, "lectura: ArtifactNotFoundError",
                   "tennis_base_v2_a")


def test_a_corrupted_blob_is_no_model_with_a_read_reason(store, root, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    path = blob(root, package.artifact_key)
    os.chmod(path, 0o644)
    path.write_bytes(path.read_bytes()[:-5] + b"XXXXX")
    assert_refused(load_base(reader, registry(base_entry(package))), caplog, "lectura: ArtifactIntegrityError")


@pytest.mark.parametrize("variant", ["manifest-type", "metadata-columns", "b1-rejected", "non-canonical-manifest"])
def test_an_invalid_package_is_no_model_with_a_validation_reason(store, reader, caplog, variant):
    if variant == "non-canonical-manifest":
        valid = publish_base(store, "tennis_base_v2_a")
        key = store.put(b'{"schema_version": 1}\n')  # JSON válido, pero ni canónico ni un manifiesto
        entry = base_entry(valid, key=key)
    else:
        options = {
            "manifest-type": {"manifest_type": "platt_logreg_1d_v1"},
            "metadata-columns": {"metadata_columns": ["otra.columna", "mas.columnas", "y.otra"]},
            "b1-rejected": {"artifact_bytes": b'{"schema_version": 1}\n'},
        }[variant]
        entry = base_entry(publish_base(store, "tennis_base_v2_a", **options))
    message = assert_refused(load_base(reader, registry(entry)), caplog)
    assert VALIDATION.search(message), message


def test_a_package_whose_version_differs_from_the_registry_entry_is_no_model(store, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    entry = base_entry(package, version="tennis_base_v2_other")  # el registro declara otra versión para esa clave
    message = assert_refused(load_base(reader, registry(entry)), caplog)
    assert "PackageConsistencyError" in message


def test_a_calibrator_package_under_a_base_entry_is_a_role_mismatch(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    entry = {**base_entry(calibrator), "role": "base"}
    assert_refused(load_base(reader, registry(entry)), caplog, "concordancia: el paquete no es un modelo base",
                   "tennis_cal_v2_a")


def test_a_store_that_became_unavailable_mid_flight_is_a_configuration_no_model(store, root, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    root.rename(root.parent / "moved_root")  # la raíz registrada ya no existe
    assert_refused(load_base(reader, registry(base_entry(package))), caplog, "configuración: StoreConfigurationError")


def test_a_failure_logs_no_path_and_no_package_content(store, root, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    blob(root, package.artifact_key).unlink()
    message = assert_refused(load_base(reader, registry(base_entry(package))), caplog)
    for forbidden in (str(root), str(root.parent), "sha256/", "rest_days", "tournament_round", "coef", "intercept",
                      package.artifact_key, package.metadata_key):
        assert forbidden not in message, forbidden


# =====================================================================
# B. Calibrador y su correspondencia con la base
# =====================================================================


def test_load_calibrator_returns_exactly_the_verified_package_linked_to_the_given_base(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    reg = registry(base_entry(base), calibrator_entry(calibrator, base.model_version))
    verified_base = load_base(reader, reg)

    result = load_calibrator(reader, reg, verified_base)

    assert type(result) is VerifiedPackage and isinstance(result.model, PlattModel)
    assert result == verify_package(reader, calibrator.manifest_key, expected_model_version="tennis_cal_v2_a")
    assert result.metadata.base_model_ref.package_manifest_key == verified_base.manifest_key
    assert result.metadata.base_model_ref.model_version == verified_base.manifest.model_version
    assert warnings_of(caplog) == []


def test_the_calibrator_is_selected_by_the_version_of_the_base_it_receives(store, reader):
    base_a, base_b = publish_base(store, "tennis_base_v2_a"), publish_base(store, "tennis_base_v2_b", variant=1)
    cal_a, cal_b = publish_calibrator(store, "tennis_cal_v2_a", base_a), publish_calibrator(store, "tennis_cal_v2_b", base_b)
    reg = registry(calibrator_entry(cal_a, base_a.model_version), calibrator_entry(cal_b, base_b.model_version))
    got_a = load_calibrator(reader, reg, verify_package(reader, base_a.manifest_key, expected_model_version="tennis_base_v2_a"))
    got_b = load_calibrator(reader, reg, verify_package(reader, base_b.manifest_key, expected_model_version="tennis_base_v2_b"))
    assert (got_a.manifest.model_version, got_b.manifest.model_version) == ("tennis_cal_v2_a", "tennis_cal_v2_b")


def test_same_base_version_with_a_different_manifest_key_is_rejected_by_the_reference(store, reader, caplog):
    original = publish_base(store, "tennis_base_v2_a")
    impostor = publish_base(store, "tennis_base_v2_a", variant=5)  # misma versión, otro contenido, otra clave
    assert impostor.manifest_key != original.manifest_key
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", original)  # ajustado contra `original`
    reg = registry(calibrator_entry(calibrator, "tennis_base_v2_a"))
    verified = lambda package: verify_package(reader, package.manifest_key, expected_model_version="tennis_base_v2_a")

    assert load_calibrator(reader, reg, verified(original)) is not None  # control positivo
    caplog.clear()
    assert_refused(load_calibrator(reader, reg, verified(impostor)), caplog,
                   "concordancia: la clave del manifiesto de la base referenciada no coincide", "tennis_cal_v2_a")


def test_a_reference_with_another_base_version_than_the_registry_entry_is_rejected(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base, ref_version="tennis_base_v2_zzz")
    reg = registry(calibrator_entry(calibrator, base.model_version))
    verified = verify_package(reader, base.manifest_key, expected_model_version="tennis_base_v2_a")
    assert_refused(load_calibrator(reader, reg, verified), caplog, "la versión de la base referenciada no coincide")


def test_an_entry_declared_for_another_base_is_no_candidate_and_reads_nothing(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    reg = registry(calibrator_entry(calibrator, "tennis_base_v2_other"))
    verified = verify_package(reader, base.manifest_key, expected_model_version="tennis_base_v2_a")
    spy = SpyReader(reader)
    assert_refused(load_calibrator(spy, reg, verified), caplog, "selección: NO_CANDIDATE")
    assert spy.calls == []


def test_ambiguous_calibrators_of_one_base_leave_only_that_group_without_model(store, reader, caplog):
    base_a, base_b = publish_base(store, "tennis_base_v2_a"), publish_base(store, "tennis_base_v2_b", variant=1)
    first, second = publish_calibrator(store, "tennis_cal_v2_a", base_a), publish_calibrator(store, "tennis_cal_v2_c", base_a, variant=2)
    other = publish_calibrator(store, "tennis_cal_v2_b", base_b)
    reg = registry(calibrator_entry(first, base_a.model_version), calibrator_entry(second, base_a.model_version),
                   calibrator_entry(other, base_b.model_version))
    verified_a = verify_package(reader, base_a.manifest_key, expected_model_version="tennis_base_v2_a")
    verified_b = verify_package(reader, base_b.manifest_key, expected_model_version="tennis_base_v2_b")
    spy = SpyReader(reader)

    assert_refused(load_calibrator(spy, reg, verified_a), caplog, "selección: AMBIGUOUS")
    assert spy.calls == []
    assert load_calibrator(reader, reg, verified_b).manifest.model_version == "tennis_cal_v2_b"  # otro grupo: intacto


def test_a_base_package_under_a_calibrator_entry_is_a_role_mismatch(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    wrong = publish_base(store, "tennis_base_v2_wrong", variant=3)
    reg = registry(calibrator_entry(wrong, base.model_version))
    verified = verify_package(reader, base.manifest_key, expected_model_version="tennis_base_v2_a")
    assert_refused(load_calibrator(reader, reg, verified), caplog, "concordancia: el paquete no es un calibrador")


@pytest.mark.parametrize("failure", ["absent", "corrupt", "invalid"])
def test_an_absent_corrupt_or_invalid_calibrator_package_is_no_model(store, root, reader, caplog, failure):
    base = publish_base(store, "tennis_base_v2_a")
    options = {"invalid": {"manifest_type": "imputed_standardized_logreg_v1"}}.get(failure, {})
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base, **options)
    if failure == "absent":
        blob(root, calibrator.metadata_key).unlink()
    if failure == "corrupt":
        path = blob(root, calibrator.artifact_key)
        os.chmod(path, 0o644)
        path.write_bytes(b"x" * path.stat().st_size)
    verified = verify_package(reader, base.manifest_key, expected_model_version="tennis_base_v2_a")
    message = assert_refused(load_calibrator(reader, registry(calibrator_entry(calibrator, base.model_version)),
                                             verified), caplog, "tennis_cal_v2_a")
    if failure == "invalid":
        assert VALIDATION.search(message), message
    else:
        assert {"absent": "lectura: ArtifactNotFoundError", "corrupt": "lectura: ArtifactIntegrityError"}[failure] in message


def test_the_base_does_not_have_to_be_a_registry_entry_nor_have_a_state_pending_decision_of_d8(store, reader):
    # Documenta que PR-4 NO decide el requisito (c) de D8: la base la aporta el llamador ya verificada.
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    verified = verify_package(reader, base.manifest_key, expected_model_version="tennis_base_v2_a")
    only_calibrator = registry(calibrator_entry(calibrator, base.model_version))
    with_invalid_base = registry(base_entry(base, status="INVALID"), calibrator_entry(calibrator, base.model_version))
    assert load_calibrator(reader, only_calibrator, verified) is not None
    assert load_calibrator(reader, with_invalid_base, verified) is not None


def test_a_misused_base_argument_is_visible_and_logs_no_refusal(store, reader, caplog):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    reg = registry(calibrator_entry(calibrator, base.model_version))
    verified_calibrator = verify_package(reader, calibrator.manifest_key, expected_model_version="tennis_cal_v2_a")
    for bad in (None, {}, "base", base):
        with pytest.raises(TypeError):
            load_calibrator(reader, reg, bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        load_calibrator(reader, reg, verified_calibrator)  # un calibrador no es una base
    assert warnings_of(caplog) == []


# =====================================================================
# C. Ayudante de configuración
# =====================================================================


def test_the_helper_returns_a_read_only_view_of_the_configured_store(store, root):
    key = store.put(b"datos de prueba\n")
    view = open_store_reader_from_environment({lfs.ARTIFACT_STORE_ROOT_ENV_VAR: str(root)})
    assert isinstance(view, ArtifactReader) and not hasattr(view, "put")
    assert view.get(key) == b"datos de prueba\n"


def test_the_helper_store_can_read_a_blob_of_the_largest_legal_size(tmp_path):
    from src.models.artifact_package import MAX_METADATA_BYTES, MAX_PACKAGE_MANIFEST_BYTES
    from src.models.safe_artifact_format import MAX_ARTIFACT_BYTES

    assert loaders.MAX_BLOB_BYTES >= max(MAX_ARTIFACT_BYTES, MAX_METADATA_BYTES, MAX_PACKAGE_MANIFEST_BYTES)
    root = tmp_path / "grande"
    root.mkdir()
    os.chmod(root, 0o700)
    key = LocalFilesystemStore(root, max_blob_bytes=loaders.MAX_BLOB_BYTES * 2).put(b"x" * MAX_ARTIFACT_BYTES)
    view = open_store_reader_from_environment({lfs.ARTIFACT_STORE_ROOT_ENV_VAR: str(root)})
    assert len(view.get(key)) == MAX_ARTIFACT_BYTES


@pytest.mark.parametrize("case", ["missing", "empty", "nonexistent", "relative", "a-file", "inside-repository"])
def test_a_configuration_failure_in_the_helper_is_no_reader_with_one_reason_and_no_path(tmp_path, caplog, case):
    file_path = tmp_path / "a_file"
    file_path.write_text("x")
    value = {"missing": None, "empty": "", "nonexistent": str(tmp_path / "does_not_exist"), "relative": "relative/store",
             "a-file": str(file_path), "inside-repository": str(REPO_ROOT / "tests")}[case]
    environ = {} if value is None else {lfs.ARTIFACT_STORE_ROOT_ENV_VAR: value}

    message = assert_refused(open_store_reader_from_environment(environ), caplog, "configuración: StoreConfigurationError")

    for secret in (str(tmp_path), str(REPO_ROOT), "relative/store"):
        assert secret not in message


def test_the_helper_reads_the_process_environment_only_when_no_mapping_is_given(store, root, monkeypatch):
    monkeypatch.setenv(lfs.ARTIFACT_STORE_ROOT_ENV_VAR, str(root))
    assert isinstance(open_store_reader_from_environment(), ArtifactReader)
    monkeypatch.delenv(lfs.ARTIFACT_STORE_ROOT_ENV_VAR)
    assert open_store_reader_from_environment() is None


# =====================================================================
# D. Errores inesperados y de uso: siguen siendo visibles
# =====================================================================


@pytest.mark.parametrize("error", [
    RuntimeError("fallo inesperado"), KeyError("k"), AttributeError("a"), ValueError("v"),
    InvalidArtifactKeyError("clave inválida: error de programación"), ArtifactPublishError("un lector no publica"),
    OSError("error del sistema sin envolver"), MemoryError(),
], ids=lambda e: type(e).__name__)
def test_unexpected_errors_from_the_reader_propagate_and_are_not_logged_as_a_refusal(store, caplog, error):
    package = publish_base(store, "tennis_base_v2_a")
    with pytest.raises(type(error)):
        load_base(RaisingReader(error), registry(base_entry(package)))
    assert warnings_of(caplog) == []


@pytest.mark.parametrize("error", [TypeError("t"), KeyError("k"), AttributeError("a"), AssertionError("x")],
                         ids=lambda e: type(e).__name__)
def test_programming_errors_raised_while_verifying_propagate(store, reader, caplog, monkeypatch, error):
    package = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", package)
    verified_base = verify_package(reader, package.manifest_key, expected_model_version="tennis_base_v2_a")

    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(loaders, "verify_package", boom)
    with pytest.raises(type(error)):
        load_base(reader, registry(base_entry(package)))
    with pytest.raises(type(error)):
        load_calibrator(reader, registry(calibrator_entry(calibrator, package.model_version)), verified_base)
    assert warnings_of(caplog) == []


@pytest.mark.parametrize("registry_case", ["with-candidate", "empty", "ambiguous"])
def test_a_bad_reader_is_visible_even_when_no_blob_would_have_been_read(store, caplog, registry_case):
    first, second = publish_base(store, "tennis_base_v2_a"), publish_base(store, "tennis_base_v2_b", variant=1)
    reg = {"with-candidate": registry(base_entry(first)), "empty": registry(),
           "ambiguous": registry(base_entry(first), base_entry(second))}[registry_case]
    for bad_reader in (None, object(), {}, "lector"):
        with pytest.raises(TypeError):
            load_base(bad_reader, reg)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            load_calibrator(bad_reader, reg, verify_package(store.reader(), first.manifest_key,
                                                            expected_model_version="tennis_base_v2_a"))  # type: ignore[arg-type]
    assert warnings_of(caplog) == []


def test_argument_misuse_is_visible(store, reader, caplog):
    package = publish_base(store, "tennis_base_v2_a")
    reg = registry(base_entry(package))
    for bad_reader in (None, object(), {}, "lector"):
        with pytest.raises(TypeError):
            load_base(bad_reader, reg)  # type: ignore[arg-type]
    for bad_registry in (None, {}, [], {"package_models": []}, "registro", reg.entries):
        with pytest.raises(TypeError):
            load_base(reader, bad_registry)  # type: ignore[arg-type]
    assert warnings_of(caplog) == []


# =====================================================================
# E. Sin fallback, solo lectura y sin consultar el entorno
# =====================================================================


def test_there_is_no_fallback_to_the_legacy_format_when_the_safe_package_cannot_be_used(store, root, reader, caplog, monkeypatch):
    import joblib
    import pickle

    from src.models import model_registry_policy, tennis_baseline

    def forbidden(*args, **kwargs):
        raise AssertionError("se recurrió al formato heredado")

    for owner, name in ((joblib, "load"), (pickle, "load"), (pickle, "loads"),
                        (model_registry_policy, "load_model_registry"), (tennis_baseline, "load_latest_tennis_artifact")):
        monkeypatch.setattr(owner, name, forbidden)

    package = publish_base(store, "tennis_base_v2_a")
    blob(root, package.manifest_key).unlink()
    assert load_base(reader, registry(base_entry(package))) is None  # paquete ausente
    assert load_base(reader, registry()) is None  # sin candidato
    assert load_base(reader, registry(base_entry(package), base_entry(publish_base(store, "tennis_base_v2_b", variant=1)))) is None
    assert len(warnings_of(caplog)) == 3


def test_loading_is_read_only_the_store_listing_is_identical_after_success_and_failure(store, root, reader):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    reg = registry(base_entry(base), calibrator_entry(calibrator, base.model_version))
    before = snapshot(root)
    spy = SpyReader(reader)

    verified = load_base(spy, reg)
    load_calibrator(spy, reg, verified)
    load_base(spy, registry())
    blob(root, calibrator.metadata_key).unlink()
    after_unlink = snapshot(root)
    load_calibrator(spy, reg, verified)

    assert after_unlink == [p for p in before if not p.endswith(calibrator.metadata_key)]
    assert snapshot(root) == after_unlink  # los fallos tampoco escriben
    assert {kind for kind, _ in spy.calls} <= {"get"}  # nunca `put`: ni siquiera existe en un lector


def test_the_loaders_never_consult_the_environment_nor_open_another_store(store, root, reader, monkeypatch, tmp_path):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    reg = registry(base_entry(base), calibrator_entry(calibrator, base.model_version))
    monkeypatch.setenv(lfs.ARTIFACT_STORE_ROOT_ENV_VAR, str(tmp_path / "otro_almacen_que_no_existe"))

    def forbidden(*args, **kwargs):
        raise AssertionError("se consultó el entorno o se abrió un almacén")

    monkeypatch.setattr(LocalFilesystemStore, "from_environment", classmethod(forbidden))
    monkeypatch.setattr(LocalFilesystemStore, "__init__", forbidden)
    monkeypatch.setattr(lfs, "resolve_store_root_from_environment", forbidden)

    verified = load_base(reader, reg)  # camino de éxito
    assert load_calibrator(reader, reg, verified) is not None
    assert load_base(reader, registry()) is None  # camino de fallo


def test_importing_the_module_does_not_consult_the_environment_or_open_a_store(tmp_path):
    script = (
        "import sys\n"
        "import src.models.package_loaders as m\n"
        "assert 'src.storage.local_filesystem_store' not in sys.modules, 'el almacén local no debe cargarse al importar'\n"
        "assert not hasattr(m, 'LocalFilesystemStore')\n"
        "print('ok')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1",
               **{lfs.ARTIFACT_STORE_ROOT_ENV_VAR: str(tmp_path / "no_existe")})
    done = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"
    assert not (tmp_path / "no_existe").exists()


# =====================================================================
# F. Aislamiento
# =====================================================================

ALLOWED_IMPORT_MODULES = {
    "__future__", "logging", "typing", "src.models.artifact_package", "src.models.model_registry_v2",
    "src.models.safe_artifact_format", "src.storage.artifact_store", "src.storage.local_filesystem_store",
}
FORBIDDEN_TEXT = ("joblib", "pickle", "sklearn", "numpy", "model_registry_policy", "tennis_baseline",
                  "tennis_calibrator_training", "src.models.registry", "load_latest", "DATA_MODELS_DIR", "config.settings",
                  "model_registry.json")
FORBIDDEN_ATTRIBUTES = {"put", "open", "read_text", "read_bytes", "write_text", "write_bytes", "unlink", "mkdir", "getenv",
                        "environ", "glob", "rglob", "listdir", "walk"}
EXPECTED_FAILURES = {"ArtifactNotFoundError", "ArtifactIntegrityError", "StoreConfigurationError", "ArtifactPackageError"}


def _tree() -> ast.AST:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def test_the_module_imports_only_what_it_needs_and_nothing_from_the_legacy_format():
    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= ALLOWED_IMPORT_MODULES, imported - ALLOWED_IMPORT_MODULES
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert [word for word in FORBIDDEN_TEXT if word in text] == []


def test_the_module_never_writes_never_reads_files_and_touches_the_environment_only_through_the_helper():
    tree = _tree()
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert attributes & FORBIDDEN_ATTRIBUTES == set()
    owners = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Attribute(self, node):
            if node.attr == "from_environment":
                owners.append(self.stack[-1] if self.stack else None)
            self.generic_visit(node)

    Visitor().visit(tree)
    assert owners == ["open_store_reader_from_environment"]


def test_the_closed_list_of_expected_failures_is_exactly_the_planned_one_and_no_handler_is_broad():
    tree = _tree()
    closed = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_EXPECTED_FAILURES" for t in node.targets):
            closed = {element.id for element in node.value.elts}
    assert closed == EXPECTED_FAILURES
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    assert handlers and all(isinstance(h.type, ast.Name) and h.type.id in {"_EXPECTED_FAILURES", "StoreConfigurationError"}
                            for h in handlers)


def test_nothing_in_src_scripts_or_config_references_the_loaders_and_the_package_init_stays_empty():
    offenders = []
    for top in ("src", "scripts", "config"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            if path.resolve() == MODULE_PATH.resolve():
                continue
            if "package_loaders" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    assert (REPO_ROOT / "src" / "models" / "__init__.py").read_text(encoding="utf-8") == ""


def test_the_helpers_of_the_factories_build_what_the_tests_claim(store, reader):
    base = publish_base(store, "tennis_base_v2_a")
    calibrator = publish_calibrator(store, "tennis_cal_v2_a", base)
    assert isinstance(base, Package) and len({base.manifest_key, base.artifact_key, base.metadata_key}) == 3
    assert verify_package(reader, calibrator.manifest_key, expected_model_version="tennis_cal_v2_a").metadata.base_model_ref \
        .package_manifest_key == base.manifest_key
    with pytest.raises(PackageRegistryError):
        registry(base_entry(base), base_entry(base))  # duplicado: las fábricas heredan la validación de PR-3
