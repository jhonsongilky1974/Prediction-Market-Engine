"""Almacén de artefactos local (`src/storage/local_filesystem_store.py`): direccionamiento por hash, publicación
atómica sin sobrescritura, verificación en cada lectura, raíz explícita fuera del repositorio y operaciones
ancladas al descriptor verificado. Solo bytes sintéticos y directorios temporales (`tmp_path`): ninguna prueba
crea archivos dentro del repositorio ni conecta el almacén a entrenadores, cargadores, registro ni evaluador.

Los nombres privados del módulo (`_REPO_ROOT`, `_resolve_root`, `_fcntl`) se usan solo como ganchos de prueba;
no forman parte del contrato público."""
from __future__ import annotations

import ast
import errno
import hashlib
import importlib.util
import inspect
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.storage import local_filesystem_store as lfs
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
)
from src.storage.local_filesystem_store import (
    ARTIFACT_STORE_ROOT_ENV_VAR,
    LocalFilesystemStore,
    resolve_store_root_from_environment,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="el almacén local solo soporta POSIX")

MAX = 1024
STORE_FILE_SUFFIX = "local_filesystem_store.py"
# Nombre de archivo EXACTO con el que Python compiló el backend: se captura una sola vez al cargar este módulo, antes
# de parchear nada, y se compara por igualdad de cadenas (sin llamar a funciones de `os` que pudieran estar parcheadas).
STORE_CODE_FILENAME = LocalFilesystemStore.put.__code__.co_filename
KEY_ABSENT = hashlib.sha256(b"clave-ausente").hexdigest()


# --- utilidades ----------------------------------------------------------------------------------------------


def blob_path(root, key) -> Path:
    return Path(root) / "sha256" / key[:2] / key


def mode_of(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def snapshot(root) -> list:
    """Listado completo (ruta relativa, tipo, modo) de `root`, sin seguir symlinks."""
    entries = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = os.path.join(current, name)
            info = os.lstat(path)
            entries.append((os.path.relpath(path, root), stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode)))
    return sorted(entries)


def make_root(base: Path, name: str = "store_root") -> Path:
    root = base / name
    root.mkdir()
    os.chmod(root, 0o700)
    return root


def intercept(monkeypatch, name: str, hook):
    """Sustituye `os.<name>` por una envoltura que solo invoca `hook(real, *args, **kwargs)` cuando la llamada
    viene EXACTAMENTE del archivo del backend (`STORE_CODE_FILENAME`); las demás llamadas, incluidas las de este
    archivo de pruebas o las de módulos ajenos con un nombre parecido, pasan al original. Construir el almacén
    ANTES de interceptar: el constructor comprueba que `os.open`, `os.link`, etc. admiten `dir_fd`."""
    real = getattr(os, name)

    def wrapper(*args, **kwargs):
        if sys._getframe(1).f_code.co_filename == STORE_CODE_FILENAME:
            return hook(real, *args, **kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(os, name, wrapper)


def overwrite_blob(root, key, payload: bytes) -> None:
    path = blob_path(root, key)
    os.chmod(path, 0o644)
    path.write_bytes(payload)


@pytest.fixture
def root(tmp_path) -> Path:
    return make_root(tmp_path)


@pytest.fixture
def store(root) -> LocalFilesystemStore:
    return LocalFilesystemStore(root, max_blob_bytes=MAX)


# --- configuración: límite de tamaño y raíz ------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, 0, -1, True, False, 1.0, 10.5, "10", b"10", [10]])
def test_max_blob_bytes_must_be_a_positive_exact_int(root, bad):
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore(root, max_blob_bytes=bad)


def test_max_blob_bytes_is_mandatory_and_keyword_only(root):
    with pytest.raises(TypeError):
        LocalFilesystemStore(root)
    with pytest.raises(TypeError):
        LocalFilesystemStore(root, 10)


def test_the_b1_limit_is_not_reused_as_the_store_limit(root):
    big = LocalFilesystemStore(root, max_blob_bytes=262_144 + 1)
    payload = b"z" * (262_144 + 1)
    assert big.get(big.put(payload)) == payload


@pytest.mark.parametrize("bad", ["", "relative/dir", "./x", "~", "~/store", "../x", "store"])
def test_relative_or_empty_roots_are_rejected(tmp_path, monkeypatch, bad):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "relative").mkdir()
    (tmp_path / "relative" / "dir").mkdir()
    (tmp_path / "store").mkdir()
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore(bad, max_blob_bytes=MAX)


def test_tilde_is_never_expanded(tmp_path, monkeypatch):
    home = make_root(tmp_path, "home")
    make_root(home, "store")
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore("~/store", max_blob_bytes=MAX)


class _BytesPath:
    def __fspath__(self):
        return b"/tmp"


@pytest.mark.parametrize("bad", [None, 123, object(), b"/tmp", _BytesPath(), "/tmp/with\x00nul"])
def test_roots_that_are_not_text_paths_are_rejected(bad):
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore(bad, max_blob_bytes=MAX)


def test_root_must_exist_and_be_a_directory_and_is_never_created(tmp_path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore(missing, max_blob_bytes=MAX)
    assert not missing.exists()
    regular = tmp_path / "a_file"
    regular.write_bytes(b"x")
    with pytest.raises(StoreConfigurationError, match="directorio utilizable"):
        LocalFilesystemStore(regular, max_blob_bytes=MAX)
    with pytest.raises(StoreConfigurationError, match="directorio utilizable"):
        LocalFilesystemStore(regular / "debajo", max_blob_bytes=MAX)  # componente que no es directorio
    assert regular.read_bytes() == b"x"


def test_constructor_writes_nothing(root):
    before = (snapshot(root), os.stat(root).st_mtime_ns)
    LocalFilesystemStore(root, max_blob_bytes=MAX)
    LocalFilesystemStore(str(root), max_blob_bytes=MAX)
    assert (snapshot(root), os.stat(root).st_mtime_ns) == before
    assert os.listdir(root) == []


# --- exclusión física del repositorio ------------------------------------------------------------------------


def test_repo_root_hook_matches_the_project_root_and_points_at_this_checkout():
    from config.settings import PROJECT_ROOT

    assert lfs._REPO_ROOT == PROJECT_ROOT
    assert (lfs._REPO_ROOT / "src" / "storage" / STORE_FILE_SUFFIX).is_file()


def test_roots_equal_to_or_inside_the_repository_are_rejected_without_creating_anything():
    repo = lfs._REPO_ROOT
    never = repo / "data" / "__never_created_by_pr1_tests__"
    candidates = [repo, repo / "src", repo / "src" / "storage", never / "a" / "b", never]
    for candidate in candidates:
        with pytest.raises(StoreConfigurationError, match="repositorio"):
            LocalFilesystemStore(candidate, max_blob_bytes=MAX)
        with pytest.raises(StoreConfigurationError, match="repositorio"):
            LocalFilesystemStore(str(candidate), max_blob_bytes=MAX)
    assert not never.exists()


def test_a_symlink_to_the_repository_or_inside_it_cannot_elude_the_exclusion(tmp_path):
    repo = lfs._REPO_ROOT
    to_repo = tmp_path / "to_repo"
    to_src = tmp_path / "to_src"
    os.symlink(repo, to_repo)
    os.symlink(repo / "src", to_src)
    chain = tmp_path / "chain"
    os.symlink(to_src, chain)
    for candidate in (to_repo, to_src, chain, to_repo / "data" / "__never__", chain / "nuevo"):
        with pytest.raises(StoreConfigurationError, match="repositorio"):
            LocalFilesystemStore(candidate, max_blob_bytes=MAX)
    assert not (repo / "data" / "__never__").exists()


def test_a_root_outside_the_repository_its_ancestors_and_symlinks_to_outside_are_accepted(tmp_path, root):
    LocalFilesystemStore(root, max_blob_bytes=MAX)
    ancestor = lfs._REPO_ROOT.parent
    LocalFilesystemStore(ancestor, max_blob_bytes=MAX)  # ancestro del repo: se acepta (el constructor no escribe)
    link = tmp_path / "link_to_root"
    os.symlink(root, link)
    through_link = LocalFilesystemStore(link, max_blob_bytes=MAX)
    key = through_link.put(b"por el symlink")
    assert blob_path(root, key).read_bytes() == b"por el symlink"


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignora los permisos de directorio")
def test_an_inaccessible_ancestor_is_rejected_fail_closed(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inner").mkdir()
    os.chmod(locked, 0o000)
    try:
        with pytest.raises(StoreConfigurationError, match="no se pudo comprobar que la raíz esté fuera"):
            LocalFilesystemStore(locked / "inner", max_blob_bytes=MAX)
        with pytest.raises(StoreConfigurationError, match="no se pudo comprobar que la raíz esté fuera"):
            LocalFilesystemStore(locked / "inner" / "not_yet", max_blob_bytes=MAX)
    finally:
        os.chmod(locked, 0o700)


@pytest.mark.parametrize("variant", ["capitalizacion", "firmlink"])
def test_T33_real_alias_paths_of_the_repository_are_rejected_when_the_system_has_them(variant):
    """Rutas reales del equipo que son físicamente el repositorio pero que una comparación de TEXTO no reconoce:
    otra capitalización (volumen insensible a mayúsculas) y el firmlink de macOS. Se omite, con motivo, si el
    sistema no las tiene; la cobertura portátil de la misma regla es T33b."""
    repo = str(lfs._REPO_ROOT)
    alias = repo.swapcase() if variant == "capitalizacion" else "/System/Volumes/Data" + repo
    if alias == repo or not os.path.isdir(alias) or not os.path.samefile(alias, repo):
        pytest.skip(f"T33/{variant}: este sistema no ofrece esa ruta alternativa al repositorio")
    candidate = os.path.join(alias, "data", "__t33_never_created__")
    with pytest.raises(StoreConfigurationError, match="repositorio"):
        LocalFilesystemStore(candidate, max_blob_bytes=MAX)
    assert not os.path.exists(os.path.join(repo, "data", "__t33_never_created__"))


def test_T33b_exclusion_is_decided_by_physical_identity_not_by_path_text(tmp_path, monkeypatch):
    """Regresión portátil: con un resolvedor que NO colapsa el symlink, el texto de la ruta no empieza por el del
    repositorio, pero el ancestro `alias` ES físicamente el repositorio y debe rechazarse."""
    base = tmp_path.resolve()
    fake_repo = base / "repo"
    (fake_repo / "data").mkdir(parents=True)
    alias = base / "alias"
    os.symlink(fake_repo, alias)
    outside = make_root(base, "outside")
    monkeypatch.setattr(lfs, "_REPO_ROOT", fake_repo)
    monkeypatch.setattr(lfs, "_resolve_root", lambda path: Path(os.path.abspath(path)))
    candidate = alias / "data" / "almacen_nuevo"
    assert not str(candidate).startswith(str(fake_repo)), "premisa: una comparación de texto NO lo detectaría"
    with pytest.raises(StoreConfigurationError, match="repositorio"):
        LocalFilesystemStore(candidate, max_blob_bytes=MAX)
    LocalFilesystemStore(outside, max_blob_bytes=MAX)  # control positivo: lo externo se acepta
    assert os.listdir(fake_repo / "data") == []


# --- variable de entorno -------------------------------------------------------------------------------------


def test_environment_variable_name_and_resolution():
    assert ARTIFACT_STORE_ROOT_ENV_VAR == "PME_ARTIFACT_STORE_ROOT"
    assert resolve_store_root_from_environment({ARTIFACT_STORE_ROOT_ENV_VAR: "/algun/valor "}) == "/algun/valor "


@pytest.mark.parametrize("environ", [{}, {ARTIFACT_STORE_ROOT_ENV_VAR: ""}, {"OTRA": "/x"}])
def test_missing_or_empty_environment_variable_has_no_default_and_fails(environ):
    with pytest.raises(StoreConfigurationError):
        resolve_store_root_from_environment(environ)
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore.from_environment(max_blob_bytes=MAX, environ=environ)


def test_relative_environment_value_is_rejected_by_the_constructor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel").mkdir()
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore.from_environment(max_blob_bytes=MAX, environ={ARTIFACT_STORE_ROOT_ENV_VAR: "rel"})


def test_from_environment_uses_the_variable_each_time_and_still_requires_an_explicit_limit(tmp_path, monkeypatch):
    first = make_root(tmp_path, "first")
    second = make_root(tmp_path, "second")
    monkeypatch.setenv(ARTIFACT_STORE_ROOT_ENV_VAR, str(first))
    key = LocalFilesystemStore.from_environment(max_blob_bytes=MAX).put(b"uno")
    assert blob_path(first, key).is_file()
    monkeypatch.setenv(ARTIFACT_STORE_ROOT_ENV_VAR, str(second))
    key2 = LocalFilesystemStore.from_environment(max_blob_bytes=MAX).put(b"dos")
    assert blob_path(second, key2).is_file() and not blob_path(first, key2).exists()
    monkeypatch.delenv(ARTIFACT_STORE_ROOT_ENV_VAR)
    with pytest.raises(StoreConfigurationError):
        LocalFilesystemStore.from_environment(max_blob_bytes=MAX)
    with pytest.raises(TypeError):
        LocalFilesystemStore.from_environment()


def test_importing_the_module_does_not_read_the_environment_variable(tmp_path):
    env = dict(os.environ, **{ARTIFACT_STORE_ROOT_ENV_VAR: "valor/relativo/invalido", "PYTHONDONTWRITEBYTECODE": "1"})
    env["PYTHONPATH"] = str(lfs._REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", "import src.storage.local_filesystem_store"],
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )
    assert result.returncode == 0, result.stderr


# --- put / get ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"x", bytes(range(256)) * 3, "ñandú".encode("utf-8")])
def test_put_returns_the_sha256_key_and_get_returns_identical_bytes(store, data):
    key = store.put(data)
    assert type(key) is str and key == hashlib.sha256(data).hexdigest() == compute_key(data)
    assert store.get(key) == data
    assert store.exists(key) is True
    assert store.verify(key) is None


def test_layout_is_sha256_two_hex_then_the_full_key_without_extension(store, root):
    key = store.put(b"layout")
    path = root / "sha256" / key[:2] / key
    assert path.is_file() and path.suffix == ""
    assert sorted(os.listdir(root)) == ["sha256", "tmp"]
    assert os.listdir(root / "sha256") == [key[:2]]
    assert os.listdir(root / "sha256" / key[:2]) == [key]


@pytest.mark.parametrize("mask", [0o000, 0o027, 0o077, 0o277])
def test_directories_are_0700_and_blobs_0444_regardless_of_umask(tmp_path, mask):
    root = make_root(tmp_path)
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    previous = os.umask(mask)
    try:
        key = local.put(b"permisos")
    finally:
        os.umask(previous)
    for directory in (root / "sha256", root / "sha256" / key[:2], root / "tmp"):
        assert mode_of(directory) == 0o700
    assert mode_of(blob_path(root, key)) == 0o444


def test_a_second_identical_put_is_idempotent_and_never_rewrites_the_blob(store, root):
    key = store.put(b"idempotente")
    path = blob_path(root, key)
    before = (os.stat(path).st_ino, os.stat(path).st_mtime_ns, os.stat(path).st_nlink)
    assert store.put(b"idempotente") == key
    after = (os.stat(path).st_ino, os.stat(path).st_mtime_ns, os.stat(path).st_nlink)
    assert before == after and after[2] == 1
    assert os.listdir(root / "tmp") == []


def test_size_limit_is_enforced_on_put_before_touching_the_disk(root):
    local = LocalFilesystemStore(root, max_blob_bytes=64)
    assert local.get(local.put(b"x" * 64)) == b"x" * 64
    fresh = make_root(root.parent, "fresh")
    other = LocalFilesystemStore(fresh, max_blob_bytes=64)
    before = snapshot(fresh)
    with pytest.raises(ArtifactPublishError):
        other.put(b"x" * 65)
    assert snapshot(fresh) == before == []


class _BytesSubclass(bytes):
    pass


@pytest.mark.parametrize("data", [bytearray(b"x"), memoryview(b"x"), "x", None, 7, _BytesSubclass(b"x")])
def test_put_rejects_anything_that_is_not_exactly_bytes_without_touching_the_disk(root, data):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    with pytest.raises(ArtifactPublishError):
        local.put(data)
    assert os.listdir(root) == []


@pytest.mark.parametrize("operation", ["get", "exists", "verify"])
@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "../" + "a" * 61, "a" * 63, "a" * 65, None, b"a" * 64, 5])
def test_invalid_keys_are_rejected_by_every_read_operation(store, operation, bad):
    with pytest.raises(InvalidArtifactKeyError):
        getattr(store, operation)(bad)


def test_put_is_a_store_and_returns_str_in_its_annotation(store):
    assert isinstance(store, ArtifactStore) and isinstance(store, ArtifactReader)
    assert inspect.signature(LocalFilesystemStore.put).return_annotation in (str, "str")
    assert not hasattr(lfs, "PutResult")


def test_a_corrupt_existing_blob_makes_put_fail_and_is_neither_overwritten_nor_repaired(store, root):
    key = store.put(b"original")
    overwrite_blob(root, key, b"alterado")  # contenido distinto bajo la misma clave
    path = blob_path(root, key)
    before = (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino)
    with pytest.raises(ArtifactIntegrityError):
        store.put(b"original")
    assert (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino) == before
    assert os.listdir(root / "tmp") == []


@pytest.mark.parametrize("kind", ["flip", "truncate", "empty", "append"])
def test_every_kind_of_corruption_of_an_existing_blob_is_rejected_by_put_untouched(store, root, kind):
    payload = b"contenido de prueba" * 4
    key = store.put(payload)
    path = blob_path(root, key)
    corrupted = {
        "flip": bytes([payload[0] ^ 1]) + payload[1:],
        "truncate": payload[:-3],
        "empty": b"",
        "append": payload + b"!",
    }[kind]
    overwrite_blob(root, key, corrupted)
    with pytest.raises(ArtifactIntegrityError):
        store.put(payload)
    assert path.read_bytes() == corrupted


def test_an_orphan_temporary_file_does_not_prevent_publishing_and_is_left_alone(root):
    os.mkdir(root / "tmp", 0o700)
    orphan = root / "tmp" / "orfano.part"
    orphan.write_bytes(b"resto de una caida")
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    key = local.put(b"nuevo")
    assert local.get(key) == b"nuevo"
    assert os.listdir(root / "tmp") == ["orfano.part"] and orphan.read_bytes() == b"resto de una caida"


def test_preexisting_private_internal_directories_are_used_and_their_mode_is_not_altered(root):
    for name in ("sha256", "tmp"):
        os.mkdir(root / name, 0o700)
        os.chmod(root / name, 0o700)
    before = {name: mode_of(root / name) for name in ("sha256", "tmp")}
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    key = local.put(b"preexistente")
    assert local.get(key) == b"preexistente"
    assert {name: mode_of(root / name) for name in ("sha256", "tmp")} == before


@pytest.mark.parametrize("name", ["sha256", "tmp"])
def test_a_preexisting_internal_directory_open_to_group_or_others_is_rejected_and_not_modified(root, name):
    os.mkdir(root / name, 0o700)
    os.chmod(root / name, 0o755)
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    with pytest.raises(StoreConfigurationError, match="permisos"):
        local.put(b"x")
    assert mode_of(root / name) == 0o755


@pytest.mark.parametrize("operation", ["get", "exists", "verify"])
def test_a_permissive_preexisting_internal_directory_makes_every_read_operation_raise_and_is_not_changed(
    root, operation
):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    key = local.put(b"antes de abrir los permisos")
    os.chmod(root / "sha256", 0o755)
    with pytest.raises(StoreConfigurationError, match="permisos"):
        getattr(local, operation)(key)
    assert mode_of(root / "sha256") == 0o755  # se rechaza sin modificar sus permisos


@pytest.mark.parametrize("where", ["sha256", "tmp", "shard"])
def test_a_symlink_in_place_of_an_internal_directory_is_rejected_and_nothing_is_written_through_it(
    tmp_path, root, where
):
    outside = make_root(tmp_path, "outside")
    payload = b"por el symlink interno"
    key = compute_key(payload)
    if where == "sha256":
        os.symlink(outside, root / "sha256")
    elif where == "tmp":
        os.mkdir(root / "sha256", 0o700)
        os.symlink(outside, root / "tmp")
    else:
        os.mkdir(root / "sha256", 0o700)
        os.symlink(outside, root / "sha256" / key[:2])
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    with pytest.raises(ArtifactIntegrityError):
        local.put(payload)
    assert os.listdir(outside) == []


def test_sha256_and_tmp_on_different_filesystems_are_rejected(store, root, monkeypatch):
    store.put(b"crea los directorios")
    tmp_inode = os.stat(root / "tmp").st_ino
    real_fstat = os.fstat

    def fake_fstat(fd):
        info = real_fstat(fd)
        if info.st_ino == tmp_inode and stat.S_ISDIR(info.st_mode):
            fields = list(info)[:10]
            fields[2] += 1  # st_dev distinto
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(os, "fstat", fake_fstat)
    with pytest.raises(StoreConfigurationError, match="sistemas de archivos"):
        store.put(b"otro contenido")
    monkeypatch.undo()
    assert os.listdir(root / "tmp") == []


# --- atomicidad y fallos de publicación -----------------------------------------------------------------------


def _assert_nothing_visible(root, key):
    assert not blob_path(root, key).exists()
    assert os.listdir(root / "tmp") == []


def test_a_write_failure_leaves_no_visible_blob_and_no_temporary_file(store, root, monkeypatch):
    def failing(real, fd, data):
        raise OSError(errno.ENOSPC, "sin espacio")

    intercept(monkeypatch, "write", failing)
    with pytest.raises(ArtifactPublishError):
        store.put(b"no se escribe")
    monkeypatch.undo()
    _assert_nothing_visible(root, compute_key(b"no se escribe"))


def test_a_failure_before_publication_leaves_no_visible_blob_and_no_temporary_file(store, root, monkeypatch):
    def failing(real, *args, **kwargs):
        raise OSError(errno.EXDEV, "enlace entre dispositivos")

    intercept(monkeypatch, "link", failing)
    with pytest.raises(ArtifactPublishError):
        store.put(b"no se publica")
    monkeypatch.undo()
    _assert_nothing_visible(root, compute_key(b"no se publica"))


def test_a_temporary_file_sync_failure_leaves_nothing_visible(store, root, monkeypatch):
    monkeypatch.setattr(lfs, "_fcntl", None)

    def failing(real, fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "error de E/S")
        return real(fd)

    intercept(monkeypatch, "fsync", failing)
    with pytest.raises(ArtifactPublishError):
        store.put(b"no se sincroniza")
    monkeypatch.undo()
    _assert_nothing_visible(root, compute_key(b"no se sincroniza"))


def test_a_directory_sync_failure_after_publication_is_reported_and_a_retry_succeeds(store, root, monkeypatch):
    payload = b"directorio sin sincronizar"
    key = compute_key(payload)
    for name in ("sha256", "tmp"):
        os.mkdir(root / name, 0o700)
    os.mkdir(root / "sha256" / key[:2], 0o700)  # sin creaciones: el único fsync de directorio es el posterior al enlace
    state = {"fail": True}

    def maybe_fail(real, fd):
        if state["fail"] and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "error de E/S")
        return real(fd)

    intercept(monkeypatch, "fsync", maybe_fail)
    with pytest.raises(ArtifactPublishError):
        store.put(payload)
    assert store.verify(key) is None and store.get(key) == payload  # el blob publicado es íntegro y no se borra
    assert os.listdir(root / "tmp") == []
    state["fail"] = False
    assert store.put(payload) == key


# --- lectura: integridad y entradas anómalas ------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["flip", "truncate", "empty", "append"])
def test_get_and_verify_reject_any_modified_blob(store, root, kind):
    payload = b"datos que se verifican" * 3
    key = store.put(payload)
    corrupted = {
        "flip": payload[:-1] + bytes([payload[-1] ^ 0x80]),
        "truncate": payload[:-1],
        "empty": b"",
        "append": payload + b"\n",
    }[kind]
    overwrite_blob(root, key, corrupted)
    with pytest.raises(ArtifactIntegrityError):
        store.get(key)
    with pytest.raises(ArtifactIntegrityError):
        store.verify(key)
    assert store.exists(key) is True  # exists solo informa de la presencia: no verifica el hash


def test_missing_blob_or_missing_directories_raise_not_found_and_exists_is_false(store, root):
    assert store.exists(KEY_ABSENT) is False
    with pytest.raises(ArtifactNotFoundError):
        store.get(KEY_ABSENT)
    with pytest.raises(ArtifactNotFoundError):
        store.verify(KEY_ABSENT)
    store.put(b"crea sha256/ y un shard")
    assert store.exists(KEY_ABSENT) is False
    with pytest.raises(ArtifactNotFoundError):
        store.get(KEY_ABSENT)


def _replace_blob_with(root, key, kind, tmp_path, payload):
    path = blob_path(root, key)
    os.unlink(path)
    if kind == "symlink":
        target = tmp_path / "copia_exacta"
        target.write_bytes(payload)  # el destino tiene los bytes correctos: aun así un symlink no es un blob
        os.symlink(target, path)
    elif kind == "directory":
        os.mkdir(path, 0o700)
    else:
        os.mkfifo(path)


@pytest.mark.parametrize(
    "kind, message", [("symlink", "no se pudo abrir"), ("directory", "archivo regular"), ("fifo", "archivo regular")]
)
def test_a_symlink_directory_or_fifo_in_place_of_a_blob_is_rejected_without_hanging(
    store, root, tmp_path, kind, message
):
    payload = b"sera reemplazado"
    key = store.put(payload)
    _replace_blob_with(root, key, kind, tmp_path, payload)
    outcomes = {}

    def attempt(operation):
        try:
            getattr(store, operation)(key)
            outcomes[operation] = "ok"
        except Exception as exc:  # noqa: BLE001 -- se inspecciona el tipo
            outcomes[operation] = type(exc)
            outcomes[operation + "_message"] = str(exc)

    for operation in ("get", "verify"):
        worker = threading.Thread(target=attempt, args=(operation,), daemon=True)
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), f"{operation} se colgó con {kind}"
        assert outcomes[operation] is ArtifactIntegrityError
        assert message in outcomes[operation + "_message"]
    assert store.exists(key) is False


def test_exists_is_false_when_an_intermediate_directory_is_a_symlink_and_get_rejects_it(store, root, tmp_path):
    payload = b"detras de un symlink"
    key = store.put(payload)
    shard = root / "sha256" / key[:2]
    moved = tmp_path / "shard_movido"
    os.rename(shard, moved)
    os.symlink(moved, shard)
    assert store.exists(key) is False
    with pytest.raises(ArtifactIntegrityError):
        store.get(key)


def test_a_blob_larger_than_the_configured_limit_is_rejected_without_reading_it(root, monkeypatch):
    wide = LocalFilesystemStore(root, max_blob_bytes=1024)
    key = wide.put(b"y" * 500)
    narrow = LocalFilesystemStore(root, max_blob_bytes=100)
    reads = []

    def counting(real, *args, **kwargs):
        reads.append(args)
        return real(*args, **kwargs)

    intercept(monkeypatch, "read", counting)
    with pytest.raises(ArtifactIntegrityError, match="max_blob_bytes"):
        narrow.get(key)
    with pytest.raises(ArtifactIntegrityError, match="max_blob_bytes"):
        narrow.verify(key)
    assert reads == []
    monkeypatch.undo()
    assert wide.get(key) == b"y" * 500


def test_a_blob_exactly_at_the_limit_is_accepted(root):
    local = LocalFilesystemStore(root, max_blob_bytes=32)
    assert local.get(local.put(b"q" * 32)) == b"q" * 32


def test_error_messages_never_contain_the_absolute_root_path(store, root, tmp_path):
    key = store.put(b"mensajes")
    messages = []
    attempts = [
        lambda: store.get(KEY_ABSENT),
        lambda: store.put(b"x" * (MAX + 1)),
        lambda: store.get("no-es-clave"),
    ]
    overwrite_blob(root, key, b"otra cosa")
    attempts.append(lambda: store.get(key))
    attempts.append(lambda: store.put(b"mensajes"))
    for attempt in attempts:
        with pytest.raises(ArtifactStoreError) as info:
            attempt()
        messages.append(str(info.value))
    moved = tmp_path / "moved"
    os.rename(root, moved)
    with pytest.raises(StoreConfigurationError) as info:
        store.get(key)
    messages.append(str(info.value))
    with pytest.raises(StoreConfigurationError) as info:
        LocalFilesystemStore(tmp_path / "no_existe", max_blob_bytes=MAX)
    messages.append(str(info.value))
    for text in messages:
        assert str(root) not in text and str(tmp_path) not in text and str(moved) not in text


@pytest.mark.parametrize("delta", [-1, +1], ids=["tamano-reducido", "tamano-ampliado"])
def test_a_blob_whose_size_changes_while_it_is_read_is_rejected(store, monkeypatch, delta):
    payload = b"tamano inestable" * 4
    key = store.put(payload)
    real_fstat = os.fstat

    def lying_fstat(fd):
        info = real_fstat(fd)
        if stat.S_ISREG(info.st_mode):
            fields = list(info)[:10]
            fields[6] = info.st_size + delta
            return os.stat_result(fields)
        return info

    intercept(monkeypatch, "fstat", lambda real, fd: lying_fstat(fd))
    with pytest.raises(ArtifactIntegrityError, match="tamaño"):
        store.get(key)
    monkeypatch.undo()
    assert store.get(key) == payload


def test_a_temporary_file_with_an_unexpected_size_is_never_published(store, root, monkeypatch):
    real_fstat = os.fstat

    def lying_fstat(real, fd):
        info = real_fstat(fd)
        if stat.S_ISREG(info.st_mode):
            fields = list(info)[:10]
            fields[6] = info.st_size - 1
            return os.stat_result(fields)
        return info

    intercept(monkeypatch, "fstat", lying_fstat)
    with pytest.raises(ArtifactPublishError, match="tamaño"):
        store.put(b"tamano inesperado")
    monkeypatch.undo()
    _assert_nothing_visible(root, compute_key(b"tamano inesperado"))


def test_short_writes_are_completed_until_every_byte_is_written(store, monkeypatch):
    payload = bytes(range(200))

    def three_bytes_at_a_time(real, fd, data):
        return real(fd, bytes(data)[:3])

    intercept(monkeypatch, "write", three_bytes_at_a_time)
    key = store.put(payload)
    monkeypatch.undo()
    assert store.get(key) == payload


def test_losing_the_publication_race_to_a_foreign_blob_with_other_bytes_is_an_integrity_error(store, root, monkeypatch):
    payload = b"carrera con un blob ajeno"
    key = compute_key(payload)

    def foreign_blob_appears_first(real, src, dst, **kwargs):
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444, dir_fd=kwargs["dst_dir_fd"])
        os.write(fd, b"basura que no corresponde a la clave")
        os.close(fd)
        return real(src, dst, **kwargs)  # ahora falla con FileExistsError

    intercept(monkeypatch, "link", foreign_blob_appears_first)
    with pytest.raises(ArtifactIntegrityError):
        store.put(payload)
    monkeypatch.undo()
    assert blob_path(root, key).read_bytes() == b"basura que no corresponde a la clave"  # sin sobrescribir
    assert os.listdir(root / "tmp") == []


def test_a_repeated_put_of_existing_bytes_never_attempts_a_new_publication(store, monkeypatch):
    store.put(b"ya publicado")
    attempts = []

    def spy(real, *args, **kwargs):
        attempts.append(args)
        return real(*args, **kwargs)

    intercept(monkeypatch, "link", spy)
    store.put(b"ya publicado")
    assert attempts == []


def test_a_platform_without_o_nofollow_fails_closed_at_construction(root, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW")
    with pytest.raises(StoreConfigurationError, match="POSIX"):
        LocalFilesystemStore(root, max_blob_bytes=MAX)


def test_the_interception_filename_is_the_exact_file_of_the_backend_and_not_this_test_file():
    assert STORE_CODE_FILENAME == lfs._write_all.__code__.co_filename == LocalFilesystemStore.put.__code__.co_filename
    assert os.path.realpath(STORE_CODE_FILENAME) == os.path.realpath(lfs.__file__)
    assert os.path.realpath(STORE_CODE_FILENAME) != os.path.realpath(__file__)
    assert __file__.endswith(STORE_FILE_SUFFIX), "este archivo termina igual que el backend: el sufijo no sirve"


def test_intercept_only_affects_calls_made_from_the_exact_backend_file_not_from_look_alike_modules(
    tmp_path, monkeypatch
):
    look_alike = tmp_path / "otro_local_filesystem_store.py"  # mismo sufijo que usaba el predicado anterior
    look_alike.write_text(
        "import os\n\n\ndef cwd():\n    return os.getcwd()\n\n\ndef write(fd, data):\n    return os.write(fd, data)\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("otro_local_filesystem_store", look_alike)
    foreign = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foreign)
    assert foreign.cwd.__code__.co_filename.endswith(STORE_FILE_SUFFIX)  # el módulo ajeno SÍ termina igual
    real_cwd = os.getcwd()
    read_end, write_end = os.pipe()
    seen = []
    try:
        intercept(monkeypatch, "getcwd", lambda real: "INTERCEPTADO")
        intercept(monkeypatch, "write", lambda real, fd, data: seen.append(bytes(data)) or real(fd, data))
        assert foreign.cwd() == real_cwd  # módulo ajeno con nombre parecido: no se intercepta
        assert os.getcwd() == real_cwd  # tampoco este archivo de pruebas
        foreign.write(write_end, b"a")
        os.write(write_end, b"b")
        assert seen == []
        lfs._write_all(write_end, b"c")  # control positivo: el backend sí se intercepta
        assert seen == [b"c"]
    finally:
        monkeypatch.undo()
        os.close(read_end)
        os.close(write_end)


# --- reader ---------------------------------------------------------------------------------------------------


def test_reader_exposes_only_get_exists_and_verify_and_delegates_to_the_store(store):
    key = store.put(b"para el lector")
    reader = store.reader()
    assert isinstance(reader, ArtifactReader) and not isinstance(reader, ArtifactStore)
    assert [n for n in dir(reader) if not n.startswith("_")] == ["exists", "get", "verify"]
    assert not hasattr(reader, "put")
    assert reader.get(key) == b"para el lector" and reader.exists(key) and reader.verify(key) is None
    with pytest.raises(ArtifactNotFoundError):
        reader.get(KEY_ABSENT)
    with pytest.raises(InvalidArtifactKeyError):
        reader.exists("mala")


# --- anclaje al descriptor de la raíz -------------------------------------------------------------------------


@pytest.mark.parametrize("replacement", ["empty_dir", "symlink_to_original", "deleted"])
def test_a_root_replaced_after_construction_fails_closed_on_every_operation(tmp_path, root, replacement):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    key = local.put(b"antes del cambio")
    moved = tmp_path / "moved_root"
    os.rename(root, moved)
    if replacement == "empty_dir":
        os.mkdir(root, 0o700)
    elif replacement == "symlink_to_original":
        os.symlink(moved, root)
    reader = local.reader()
    for operation in (
        lambda: local.put(b"x"),
        lambda: local.get(key),
        lambda: local.exists(key),
        lambda: local.verify(key),
        lambda: reader.get(key),
    ):
        with pytest.raises(StoreConfigurationError):
            operation()
    assert blob_path(moved, key).read_bytes() == b"antes del cambio"
    if replacement == "empty_dir":
        assert os.listdir(root) == []


def test_swapping_the_root_in_flight_cannot_redirect_the_operation(tmp_path, root, monkeypatch):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    root_text = str(root.resolve())
    moved = tmp_path / "moved_root"
    state = {"swapped": False}

    def swap_after_root_is_opened(real, path, flags, *rest, **kwargs):
        fd = real(path, flags, *rest, **kwargs)
        if not state["swapped"] and kwargs.get("dir_fd") is None and os.fspath(path) == root_text:
            state["swapped"] = True
            os.rename(root_text, moved)
            os.mkdir(root_text, 0o700)
        return fd

    intercept(monkeypatch, "open", swap_after_root_is_opened)
    key = local.put(b"anclado al descriptor")
    monkeypatch.undo()
    assert state["swapped"]
    assert blob_path(moved, key).read_bytes() == b"anclado al descriptor"
    assert os.listdir(root_text) == []  # el sustituto no recibió nada
    with pytest.raises(StoreConfigurationError):
        local.get(key)  # y la siguiente operación detecta el cambio


def test_after_opening_the_root_no_operation_uses_a_textual_path(tmp_path, root, monkeypatch):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    root_text = str(root.resolve())
    calls = []

    def recorder(name):
        def hook(real, *args, **kwargs):
            calls.append((name, args, kwargs))
            return real(*args, **kwargs)

        return hook

    for name in ("open", "mkdir", "stat", "unlink", "link"):
        intercept(monkeypatch, name, recorder(name))
    key = local.put(b"sin rutas textuales")
    local.put(b"sin rutas textuales")
    assert local.get(key) == b"sin rutas textuales"
    assert local.exists(key) and not local.exists(KEY_ABSENT)
    assert local.verify(key) is None
    with pytest.raises(ArtifactNotFoundError):
        local.get(KEY_ABSENT)
    monkeypatch.undo()
    seen = {name for name, _, _ in calls}
    assert seen == {"open", "mkdir", "stat", "unlink", "link"}
    root_opens = 0
    for name, args, kwargs in calls:
        if name == "link":
            assert kwargs.get("src_dir_fd") is not None and kwargs.get("dst_dir_fd") is not None
            assert os.sep not in os.fspath(args[0]) and os.sep not in os.fspath(args[1])
        elif kwargs.get("dir_fd") is None:
            assert name == "open" and os.fspath(args[0]) == root_text  # el único uso textual: abrir y verificar la raíz
            root_opens += 1
        else:
            assert os.sep not in os.fspath(args[0])
    assert root_opens == 7  # una apertura por operación: put, put, get, exists, exists, verify, get


@pytest.mark.skipif(not os.path.isdir("/dev/fd"), reason="no hay /dev/fd para contar descriptores")
def test_no_file_descriptors_leak_on_success_or_on_any_error(tmp_path, root):
    local = LocalFilesystemStore(root, max_blob_bytes=64)
    key = local.put(b"fugas")
    count_before = len(os.listdir("/dev/fd"))
    for _ in range(3):
        local.get(key)
        local.exists(key)
        local.verify(key)
        local.put(b"fugas")
        for failing in (
            lambda: local.get(KEY_ABSENT),
            lambda: local.get("mala"),
            lambda: local.put(b"x" * 65),
            lambda: local.put("no bytes"),
        ):
            with pytest.raises(ArtifactStoreError):
                failing()
    overwrite_blob(root, key, b"alterado")
    with pytest.raises(ArtifactIntegrityError):
        local.get(key)
    with pytest.raises(ArtifactIntegrityError):
        local.put(b"fugas")
    moved = tmp_path / "moved"
    os.rename(root, moved)
    with pytest.raises(StoreConfigurationError):
        local.get(key)
    os.rename(moved, root)
    assert len(os.listdir("/dev/fd")) == count_before


# --- sincronización del temporal (F_FULLFSYNC) sin depender de macOS ---------------------------------------


class FakeFcntl:
    F_FULLFSYNC = 51

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def fcntl(self, fd, command, *rest):
        self.calls.append((fd, command, stat.S_ISREG(os.fstat(fd).st_mode)))
        if self.error is not None:
            raise OSError(self.error, os.strerror(self.error))
        return 0


class FcntlWithoutFullFsync:
    def fcntl(self, fd, command, *rest):
        raise AssertionError("no debe llamarse sin F_FULLFSYNC")


def spy_on_fsync(monkeypatch):
    seen = {"regular": 0, "directory": 0}

    def hook(real, fd):
        kind = os.fstat(fd).st_mode
        seen["regular" if stat.S_ISREG(kind) else "directory"] += 1
        return real(fd)

    intercept(monkeypatch, "fsync", hook)
    return seen


@pytest.mark.parametrize("stub", [None, FcntlWithoutFullFsync()], ids=["sin-fcntl", "fcntl-sin-F_FULLFSYNC"])
def test_without_full_fsync_the_temporary_file_is_synced_with_os_fsync(store, monkeypatch, stub):
    monkeypatch.setattr(lfs, "_fcntl", stub)
    seen = spy_on_fsync(monkeypatch)
    key = store.put(b"sin F_FULLFSYNC")
    assert seen["regular"] == 1 and seen["directory"] >= 1
    assert store.get(key) == b"sin F_FULLFSYNC"


def test_with_full_fsync_only_the_regular_temporary_file_uses_it_and_not_os_fsync(store, monkeypatch):
    fake = FakeFcntl()
    monkeypatch.setattr(lfs, "_fcntl", fake)
    seen = spy_on_fsync(monkeypatch)
    key = store.put(b"con F_FULLFSYNC")
    assert [(command, regular) for _, command, regular in fake.calls] == [(FakeFcntl.F_FULLFSYNC, True)]
    assert seen["regular"] == 0 and seen["directory"] >= 1
    assert store.get(key) == b"con F_FULLFSYNC"


_FALLBACK = sorted({getattr(errno, name) for name in ("EINVAL", "ENOTSUP", "EOPNOTSUPP") if hasattr(errno, name)})


@pytest.mark.parametrize("code", _FALLBACK, ids=[errno.errorcode[c] for c in _FALLBACK])
def test_full_fsync_einval_enotsup_eopnotsupp_fall_back_to_os_fsync(store, monkeypatch, code):
    fake = FakeFcntl(error=code)
    monkeypatch.setattr(lfs, "_fcntl", fake)
    seen = spy_on_fsync(monkeypatch)
    key = store.put(b"retorno a fsync")
    assert len(fake.calls) == 1 and seen["regular"] == 1
    assert store.get(key) == b"retorno a fsync"


def test_any_other_full_fsync_error_is_a_publish_error_without_fallback_and_nothing_is_visible(store, root, monkeypatch):
    fake = FakeFcntl(error=errno.EIO)
    monkeypatch.setattr(lfs, "_fcntl", fake)
    seen = spy_on_fsync(monkeypatch)
    with pytest.raises(ArtifactPublishError):
        store.put(b"error de E/S")
    monkeypatch.undo()
    assert seen["regular"] == 0
    _assert_nothing_visible(root, compute_key(b"error de E/S"))


def test_directories_are_always_synced_with_os_fsync_and_never_through_full_fsync(store, monkeypatch):
    fake = FakeFcntl()
    monkeypatch.setattr(lfs, "_fcntl", fake)
    seen = spy_on_fsync(monkeypatch)
    store.put(b"directorios")
    assert fake.calls and all(regular for _, _, regular in fake.calls)
    assert seen["directory"] >= 4  # raíz (sha256, tmp creados), sha256 (shard creado) y el shard tras el enlace


# --- concurrencia ---------------------------------------------------------------------------------------------


def test_concurrent_publishers_of_the_same_bytes_get_the_same_key_one_blob_and_no_garbage(root, monkeypatch):
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    for round_ in range(10):
        payload = (f"payload-{round_}-".encode()) * 40
        key = compute_key(payload)
        workers = 8
        barrier = threading.Barrier(workers)
        keys, errors = [], []
        links = {"ok": 0, "exists": 0}
        lock = threading.Lock()

        def counting_link(real, *args, **kwargs):
            try:
                result = real(*args, **kwargs)
            except FileExistsError:
                with lock:
                    links["exists"] += 1
                raise
            with lock:
                links["ok"] += 1
            return result

        def work():
            barrier.wait()
            try:
                keys.append(local.put(payload))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with monkeypatch.context() as scoped:
            intercept(scoped, "link", counting_link)
            threads = [threading.Thread(target=work) for _ in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
        assert errors == [] and keys == [key] * workers
        assert links["ok"] == 1  # un único publicador gana; la API pública no lo expone
        assert local.get(key) == payload and local.verify(key) is None
        path = blob_path(root, key)
        assert os.listdir(root / "tmp") == [] and os.stat(path).st_nlink == 1
        before = (os.stat(path).st_ino, os.stat(path).st_mtime_ns)
        assert local.put(payload) == key
        assert (os.stat(path).st_ino, os.stat(path).st_mtime_ns) == before


def test_concurrent_publishers_of_different_bytes_all_succeed_and_verify(store, root):
    payloads = [f"distinto-{i}".encode() * 10 for i in range(16)]
    barrier = threading.Barrier(len(payloads))
    keys, errors = {}, []

    def work(payload):
        barrier.wait()
        try:
            keys[payload] = store.put(payload)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == [] and len(keys) == len(payloads)
    for payload, key in keys.items():
        assert key == compute_key(payload) and store.get(key) == payload
    assert os.listdir(root / "tmp") == []


def test_readers_concurrent_with_a_publisher_only_see_not_found_or_the_complete_bytes(store):
    payload = b"lectura concurrente" * 40
    assert len(payload) <= MAX
    key = compute_key(payload)
    done = threading.Event()
    seen_bad, seen_ok = [], []

    def read_loop():
        while not done.is_set():
            try:
                data = store.get(key)
            except ArtifactNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                seen_bad.append(exc)
                return
            seen_ok.append(data == payload)
            if data != payload:
                return

    readers = [threading.Thread(target=read_loop, daemon=True) for _ in range(4)]
    try:
        for thread in readers:
            thread.start()
        assert store.put(payload) == key
        for _ in range(50):
            store.get(key)
    finally:
        done.set()
        for thread in readers:
            thread.join(60)
    assert seen_bad == [] and all(seen_ok)


def test_several_processes_publishing_the_same_bytes_agree_on_the_key_and_leave_one_clean_blob(tmp_path, root):
    payload = b"entre procesos" * 30
    script = (
        "import sys\n"
        "from src.storage.local_filesystem_store import LocalFilesystemStore\n"
        "store = LocalFilesystemStore(sys.argv[1], max_blob_bytes=int(sys.argv[2]))\n"
        "print(store.put(bytes.fromhex(sys.argv[3])))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(lfs._REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(root), str(MAX), payload.hex()],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=tmp_path,
        )
        for _ in range(4)
    ]
    outputs = [process.communicate(timeout=60) for process in processes]
    assert [process.returncode for process in processes] == [0, 0, 0, 0], outputs
    key = compute_key(payload)
    assert [out.strip() for out, _ in outputs] == [key] * 4
    local = LocalFilesystemStore(root, max_blob_bytes=MAX)
    assert local.get(key) == payload and os.listdir(root / "tmp") == []
    assert os.stat(blob_path(root, key)).st_nlink == 1


# --- aislamiento y compatibilidad con B1 ----------------------------------------------------------------------


def _imports_of(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_the_new_modules_import_nothing_forbidden_and_in_particular_no_settings_registry_or_models():
    contract = Path(inspect.getsourcefile(sys.modules["src.storage.artifact_store"]))
    backend = Path(lfs.__file__)
    allowed = {
        "__future__", "errno", "hashlib", "hmac", "os", "secrets", "stat", "contextlib", "pathlib", "typing", "fcntl",
        "src.storage.artifact_store", "abc", "re",
    }
    forbidden_prefixes = (
        "joblib", "pickle", "cloudpickle", "dill", "shelve", "marshal", "numpy", "sklearn", "scipy", "importlib",
        "config", "src.models", "src.evaluation", "src.calibration", "src.orchestration", "scripts", "subprocess",
    )
    for path in (contract, backend):
        imports = _imports_of(path)
        assert imports <= allowed, imports - allowed
        assert not [name for name in imports if name.startswith(forbidden_prefixes)]


def test_nothing_in_src_scripts_or_config_imports_the_store_automatically_and_the_package_init_stays_empty():
    own = {Path(lfs.__file__).resolve(), Path(inspect.getsourcefile(sys.modules["src.storage.artifact_store"])).resolve()}
    offenders = []
    for top in ("src", "scripts", "config"):
        for path in (lfs._REPO_ROOT / top).rglob("*.py"):
            if path.resolve() in own:
                continue
            text = path.read_text(encoding="utf-8")
            if "artifact_store" in text or "local_filesystem_store" in text or "LocalFilesystemStore" in text:
                offenders.append(str(path))
    assert offenders == []
    assert (lfs._REPO_ROOT / "src" / "storage" / "__init__.py").read_text(encoding="utf-8") == ""


def test_a_canonical_b1_artifact_is_stored_under_its_artifact_sha256_and_loads_back_from_the_store(store):
    from src.models.safe_artifact_format import artifact_sha256, canonical_bytes, load_artifact

    document = {
        "schema_version": 1,
        "model_type": "platt_logreg_1d_v1",
        "model_version": "platt_demo_v1",
        "parameters": {"coef": 0.5, "intercept": -0.25, "classes": [0, 1]},
    }
    data = canonical_bytes(document)
    key = store.put(data)
    assert key == artifact_sha256(data)
    loaded = load_artifact(store.get(key), expected_sha256=key, expected_model_version="platt_demo_v1")
    assert loaded is not None
