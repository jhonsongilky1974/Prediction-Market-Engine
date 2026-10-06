"""Almacén de artefactos en el sistema de archivos local (PR-1; ver `ARTIFACT_STORAGE_DECISION.md` §2, §3 y §5).

Guarda cada blob en `<raíz>/sha256/<2 hex>/<64 hex>` (D4), sin extensión, y lo publica una sola vez de forma
atómica y sin sobrescribir (D5, D7). Implementa `ArtifactStore`; `reader()` entrega una vista de solo lectura (D9).

Garantías:

* RAÍZ EXPLÍCITA Y FUERA DEL REPOSITORIO (D3, D2). La raíz debe ser una ruta ABSOLUTA, preexistente y un
  directorio; no se expande `~`, no se aceptan rutas relativas y el almacén nunca la crea. Se rechaza una raíz
  igual al repositorio o situada dentro de él decidiendo por la IDENTIDAD FÍSICA `(st_dev, st_ino)` de ella y de
  sus ancestros, no por el texto de la ruta (la capitalización o los firmlinks de macOS eluden esa comparación).
  Una raíz o un ancestro inaccesible se rechaza (fail-closed). No se examinan otros worktrees o clones.
* LÍMITE DE TAMAÑO EXPLÍCITO. `max_blob_bytes` es obligatorio, entero positivo y no tiene valor por defecto; el
  límite de B1 (`MAX_ARTIFACT_BYTES`) es propio de ese formato y no se usa aquí.
* OPERACIONES ANCLADAS A UN DESCRIPTOR VERIFICADO. Cada operación abre la raíz, comprueba con `fstat` que
  conserva la identidad registrada al construir y a partir de ahí SOLO usa operaciones relativas a ese
  descriptor (`dir_fd`) con `O_NOFOLLOW`: no se vuelve a usar una ruta textual, de modo que sustituir la raíz
  después de verificarla no desvía la operación. El constructor no escribe nada.
* PUBLICACIÓN ATÓMICA SIN SOBRESCRITURA (D7). Temporal en `tmp/` (mismo sistema de archivos, comprobado), `fsync`
  del archivo, `link` al destino (falla si existe: nunca se reemplaza), `fsync` del directorio, directorios
  `0700` y blobs `0444`. Un blob existente se verifica antes de aceptar; si está corrupto o es distinto se
  rechaza sin repararlo ni sobrescribirlo.
* VERIFICACIÓN EN CADA LECTURA (P2). `get` hashea exactamente los bytes que devuelve y los compara con la clave.
* SIN DESERIALIZACIÓN: este módulo solo mueve bytes; no importa joblib, pickle ni sklearn y no lee
  configuración al importarse.

Límites: `0444` y `0700` evitan errores, no frenan al dueño del proceso (que podría cambiar permisos o
reemplazar archivos); lo que detecta una mutación es el re-hash de cada lectura. Un atacante con los mismos
privilegios que mueva el directorio raíz dejando un symlink en un ancestro no se detecta (§6.3 de la decisión).
Tras una caída pueden quedar temporales huérfanos en `tmp/`: no se limpian (D10 está aplazada). No hay réplica,
auditoría periódica, retención ni backend remoto (PR-1b y posteriores). El almacén local no es almacenamiento
duradero suficiente para producción (D1) y no se conecta a entrenadores, cargadores, registro, libro ni
evaluador. Solo POSIX: en otras plataformas el constructor falla cerrado.
"""
from __future__ import annotations

import errno
import hashlib
import hmac
import os
import secrets
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Mapping, Optional, Union

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - sin POSIX el constructor falla cerrado
    _fcntl = None  # type: ignore[assignment]

from src.storage.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPublishError,
    ArtifactReader,
    ArtifactStore,
    StoreConfigurationError,
    validate_key,
)

ARTIFACT_STORE_ROOT_ENV_VAR = "PME_ARTIFACT_STORE_ROOT"

# Raíz del repositorio actual, derivada de la ubicación de este módulo (config/settings.py no se importa: crea
# directorios al importarse). Se lee en cada comprobación, nunca se copia a otro nombre.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_BLOB_DIR = "sha256"
_TMP_DIR = "tmp"
_TEMP_SUFFIX = ".part"
_DIR_MODE = 0o700
_BLOB_MODE = 0o444
_READ_CHUNK = 1 << 20
_FULLSYNC_FALLBACK_ERRNOS = frozenset(
    getattr(errno, name) for name in ("EINVAL", "ENOTSUP", "EOPNOTSUPP") if hasattr(errno, name)
)

_DIR_FLAGS = (
    getattr(os, "O_RDONLY", 0) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_BLOB_READ_FLAGS = (
    getattr(os, "O_RDONLY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
)
_TEMP_CREATE_FLAGS = (
    getattr(os, "O_WRONLY", 0)
    | getattr(os, "O_CREAT", 0)
    | getattr(os, "O_EXCL", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _errno_name(exc: OSError) -> str:
    return errno.errorcode.get(exc.errno, "desconocido") if exc.errno is not None else "desconocido"


# ---------------------------------------------------------------------
# Configuración: plataforma, raíz y exclusión del repositorio
# ---------------------------------------------------------------------


def _require_platform_support() -> None:
    missing = [n for n in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK") if not hasattr(os, n)]
    if os.name != "posix" or missing or not hasattr(os, "fchmod"):
        raise StoreConfigurationError("el almacén local requiere un sistema POSIX con O_NOFOLLOW y O_DIRECTORY")
    for function in (os.open, os.mkdir, os.stat, os.unlink, os.link):
        if function not in os.supports_dir_fd:
            raise StoreConfigurationError("el almacén local requiere operaciones relativas a un descriptor (dir_fd)")
    if os.link not in os.supports_follow_symlinks or os.stat not in os.supports_follow_symlinks:
        raise StoreConfigurationError("el almacén local requiere follow_symlinks=False en link y stat")


def _root_text(root: object) -> str:
    if not isinstance(root, (str, os.PathLike)):
        raise StoreConfigurationError("la raíz debe ser un str o un os.PathLike")
    try:
        text = os.fspath(root)
    except TypeError:
        raise StoreConfigurationError("la raíz no es una ruta válida") from None
    if not isinstance(text, str):
        raise StoreConfigurationError("la raíz debe ser texto, no bytes")
    if text == "" or "\x00" in text:
        raise StoreConfigurationError("la raíz está vacía o contiene NUL")
    if not os.path.isabs(text):
        raise StoreConfigurationError(
            "la raíz debe ser una ruta absoluta explícita (no se expande `~` ni se aceptan rutas relativas)"
        )
    return text


def _resolve_root(path: Path) -> Path:
    """Ruta con symlinks y `..` colapsados. La exclusión del repositorio NO depende solo de esto."""
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        raise StoreConfigurationError("no se pudo resolver la raíz del almacén") from None


def _assert_outside_repository(candidate: Path) -> None:
    """Rechaza `candidate` si él o cualquiera de sus ancestros ES físicamente el directorio del repositorio
    (mismo `(st_dev, st_ino)`). Los componentes inexistentes se saltan; un error de acceso rechaza (fail-closed)."""
    try:
        repo_stat = os.stat(_REPO_ROOT)
    except OSError:
        raise StoreConfigurationError("no se pudo comprobar el directorio del repositorio") from None
    repo_identity = (repo_stat.st_dev, repo_stat.st_ino)
    current = Path(candidate)
    while True:
        try:
            current_stat = os.stat(current)
        except (FileNotFoundError, NotADirectoryError):
            pass
        except OSError:
            raise StoreConfigurationError(
                "no se pudo comprobar que la raíz esté fuera del repositorio (acceso denegado o ruta inválida)"
            ) from None
        else:
            if (current_stat.st_dev, current_stat.st_ino) == repo_identity:
                raise StoreConfigurationError("la raíz del almacén no puede ser el repositorio ni estar dentro de él")
        parent = current.parent
        if parent == current:
            return
        current = parent


def resolve_store_root_from_environment(environ: Optional[Mapping[str, str]] = None) -> str:
    """Valor de `PME_ARTIFACT_STORE_ROOT`, leído en cada llamada y sin valor por defecto. No lo valida más:
    eso lo hace el constructor del almacén."""
    source = os.environ if environ is None else environ
    value = source.get(ARTIFACT_STORE_ROOT_ENV_VAR)
    if not isinstance(value, str) or value == "":
        raise StoreConfigurationError(f"{ARTIFACT_STORE_ROOT_ENV_VAR} no está definida o está vacía")
    return value


# ---------------------------------------------------------------------
# Operaciones relativas a un descriptor de directorio
# ---------------------------------------------------------------------


def _open_dir_at(parent_fd: int, name: str, *, create: bool) -> Optional[int]:
    """Abre `name` dentro de `parent_fd` (sin seguir symlinks). Con `create`, lo crea con `0700` si falta.
    Un directorio PREEXISTENTE nunca se modifica: si concede permisos a grupo u otros se rechaza."""
    created = False
    for _ in range(3):
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                return None
            try:
                os.mkdir(name, _DIR_MODE, dir_fd=parent_fd)
            except FileExistsError:
                continue  # otro proceso lo creó entre medias
            created = True
            continue
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise ArtifactIntegrityError(
                    "una entrada interna del almacén no es un directorio real (symlink o archivo)"
                ) from None
            raise
        try:
            if created:
                os.fchmod(fd, _DIR_MODE)  # solo el directorio que acabamos de crear: no depende del umask
                os.fsync(parent_fd)
            elif stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                raise StoreConfigurationError(
                    "un directorio interno preexistente concede permisos a grupo u otros; no se modifica: "
                    "corrígelo manualmente (0700)"
                )
        except BaseException:
            os.close(fd)
            raise
        return fd
    raise ArtifactIntegrityError("un directorio interno cambió de forma inestable durante la operación")


def _enter_dir(stack: ExitStack, parent_fd: int, name: str, *, create: bool) -> Optional[int]:
    fd = _open_dir_at(parent_fd, name, create=create)
    if fd is not None:
        stack.callback(os.close, fd)
    return fd


def _read_blob(shard_fd: int, key: str, max_bytes: int) -> Optional[bytes]:
    """Bytes del blob verificados contra `key`, o `None` si no existe. Hashea exactamente los bytes que devuelve."""
    try:
        fd = os.open(key, _BLOB_READ_FLAGS, dir_fd=shard_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ArtifactIntegrityError(f"no se pudo abrir el blob ({_errno_name(exc)})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactIntegrityError("el blob no es un archivo regular")
        if info.st_size > max_bytes:
            raise ArtifactIntegrityError("el blob excede max_blob_bytes")
        chunks = []
        remaining = info.st_size
        while remaining > 0:
            chunk = os.read(fd, min(remaining, _READ_CHUNK))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != info.st_size or os.read(fd, 1):
            raise ArtifactIntegrityError("el tamaño del blob cambió durante la lectura (truncado o ampliado)")
    except OSError as exc:
        raise ArtifactIntegrityError(f"no se pudo leer el blob ({_errno_name(exc)})") from None
    finally:
        os.close(fd)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), key):
        raise ArtifactIntegrityError("el SHA-256 del blob no coincide con su clave")
    return data


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(data):
        written += os.write(fd, view[written:])


def _flush_file(fd: int) -> None:
    """Sincroniza el ARCHIVO TEMPORAL regular: `F_FULLFSYNC` cuando existe y, si no está disponible o devuelve
    EINVAL/ENOTSUP/EOPNOTSUPP, `os.fsync`. Cualquier otro error es `ArtifactPublishError`. Los directorios usan
    siempre `os.fsync` directamente (no pasan por aquí)."""
    full_fsync = getattr(_fcntl, "F_FULLFSYNC", None) if _fcntl is not None else None
    if full_fsync is not None:
        try:
            _fcntl.fcntl(fd, full_fsync)
            return
        except OSError as exc:
            if exc.errno not in _FULLSYNC_FALLBACK_ERRNOS:
                raise ArtifactPublishError(f"fallo al sincronizar el archivo temporal ({_errno_name(exc)})") from None
    try:
        os.fsync(fd)
    except OSError as exc:
        raise ArtifactPublishError(f"fallo al sincronizar el archivo temporal ({_errno_name(exc)})") from None


# ---------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------


class LocalFilesystemStore(ArtifactStore):
    """Almacén direccionado por hash en un directorio local fuera del repositorio. Sin estado mutable ni
    descriptores abiertos entre operaciones: puede usarse desde varios hilos o procesos.

    Cualquier operación puede lanzar `StoreConfigurationError` (ver su documentación): raíz cambiada o no
    disponible, o un directorio interno preexistente con permisos para grupo u otros, que se rechaza sin
    modificar sus permisos."""

    def __init__(self, root: Union[str, "os.PathLike[str]"], *, max_blob_bytes: int) -> None:
        _require_platform_support()
        if type(max_blob_bytes) is not int or max_blob_bytes <= 0:
            raise StoreConfigurationError("max_blob_bytes es obligatorio y debe ser un entero positivo")
        resolved = _resolve_root(Path(_root_text(root)))
        _assert_outside_repository(resolved)
        try:
            fd = os.open(str(resolved), _DIR_FLAGS)
        except FileNotFoundError:
            raise StoreConfigurationError("la raíz del almacén no existe (el almacén no la crea)") from None
        except OSError as exc:
            raise StoreConfigurationError(
                f"la raíz del almacén no es un directorio utilizable ({_errno_name(exc)})"
            ) from None
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        self._root_path = str(resolved)
        self._root_identity = (info.st_dev, info.st_ino)
        self._max_blob_bytes = max_blob_bytes

    @classmethod
    def from_environment(
        cls, *, max_blob_bytes: int, environ: Optional[Mapping[str, str]] = None
    ) -> "LocalFilesystemStore":
        """Construye el almacén con la raíz de `PME_ARTIFACT_STORE_ROOT`; el límite sigue siendo explícito."""
        return cls(resolve_store_root_from_environment(environ), max_blob_bytes=max_blob_bytes)

    def reader(self) -> ArtifactReader:
        """Vista de SOLO LECTURA (`get`, `exists`, `verify`): sin `put` y sin exponer la ruta de la raíz."""
        return _LocalReader(self)

    # -- anclaje ------------------------------------------------------

    def _open_root(self) -> int:
        """Único uso de la ruta textual de la raíz: abre, comprueba con `fstat` que es el directorio registrado
        y devuelve el descriptor, que ancla el resto de la operación."""
        try:
            fd = os.open(self._root_path, _DIR_FLAGS)
        except OSError:
            raise StoreConfigurationError("la raíz del almacén ya no está disponible") from None
        try:
            info = os.fstat(fd)
        except OSError:
            os.close(fd)
            raise StoreConfigurationError("no se pudo comprobar la raíz del almacén") from None
        if (info.st_dev, info.st_ino) != self._root_identity:
            os.close(fd)
            raise StoreConfigurationError("la raíz del almacén cambió respecto de la registrada")
        return fd

    # -- operaciones --------------------------------------------------

    def put(self, data: bytes) -> str:
        if type(data) is not bytes:
            raise ArtifactPublishError("los datos deben ser exactamente `bytes`")
        if len(data) > self._max_blob_bytes:
            raise ArtifactPublishError("los datos exceden max_blob_bytes")
        key = hashlib.sha256(data).hexdigest()
        try:
            with ExitStack() as stack:
                root_fd = self._open_root()
                stack.callback(os.close, root_fd)
                sha_fd = _enter_dir(stack, root_fd, _BLOB_DIR, create=True)
                tmp_fd = _enter_dir(stack, root_fd, _TMP_DIR, create=True)
                shard_fd = _enter_dir(stack, sha_fd, key[:2], create=True)
                if os.fstat(sha_fd).st_dev != os.fstat(tmp_fd).st_dev:
                    raise StoreConfigurationError("sha256/ y tmp/ están en sistemas de archivos distintos")
                if self._matches_existing(shard_fd, key, data):
                    return key
                self._publish(tmp_fd, shard_fd, key, data)
                return key
        except OSError as exc:
            raise ArtifactPublishError(f"fallo de E/S al publicar ({_errno_name(exc)})") from None

    def _matches_existing(self, shard_fd: int, key: str, data: bytes) -> bool:
        existing = _read_blob(shard_fd, key, self._max_blob_bytes)
        if existing is None:
            return False
        if existing != data:
            raise ArtifactIntegrityError("ya hay contenido distinto bajo la misma clave")
        return True

    def _publish(self, tmp_fd: int, shard_fd: int, key: str, data: bytes) -> None:
        name = secrets.token_hex(16) + _TEMP_SUFFIX
        fd = os.open(name, _TEMP_CREATE_FLAGS, _BLOB_MODE, dir_fd=tmp_fd)
        try:
            try:
                os.fchmod(fd, _BLOB_MODE)
                _write_all(fd, data)
                if os.fstat(fd).st_size != len(data):
                    raise ArtifactPublishError("el archivo temporal no tiene el tamaño esperado")
                _flush_file(fd)
            finally:
                os.close(fd)
            try:
                os.link(name, key, src_dir_fd=tmp_fd, dst_dir_fd=shard_fd, follow_symlinks=False)
            except FileExistsError:
                if self._matches_existing(shard_fd, key, data):
                    return  # otro publicador ganó con los mismos bytes
                raise ArtifactPublishError("el blob desapareció durante la publicación") from None
            os.fsync(shard_fd)
        finally:
            try:
                os.unlink(name, dir_fd=tmp_fd)
            except OSError:
                pass  # el blob publicado (si lo hay) ya es independiente del temporal

    def _read(self, key: str) -> bytes:
        try:
            with ExitStack() as stack:
                root_fd = self._open_root()
                stack.callback(os.close, root_fd)
                sha_fd = _enter_dir(stack, root_fd, _BLOB_DIR, create=False)
                shard_fd = None if sha_fd is None else _enter_dir(stack, sha_fd, key[:2], create=False)
                data = None if shard_fd is None else _read_blob(shard_fd, key, self._max_blob_bytes)
        except OSError as exc:
            raise ArtifactIntegrityError(f"no se pudo acceder al almacén ({_errno_name(exc)})") from None
        if data is None:
            raise ArtifactNotFoundError(f"blob no encontrado: {key}")
        return data

    def get(self, key: str) -> bytes:
        return self._read(validate_key(key))

    def verify(self, key: str) -> None:
        self._read(validate_key(key))

    def exists(self, key: str) -> bool:
        key = validate_key(key)
        try:
            with ExitStack() as stack:
                root_fd = self._open_root()
                stack.callback(os.close, root_fd)
                sha_fd = _enter_dir(stack, root_fd, _BLOB_DIR, create=False)
                if sha_fd is None:
                    return False
                shard_fd = _enter_dir(stack, sha_fd, key[:2], create=False)
                if shard_fd is None:
                    return False
                try:
                    info = os.stat(key, dir_fd=shard_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                return stat.S_ISREG(info.st_mode)
        except (ArtifactIntegrityError, OSError):
            return False  # una entrada anómala no es un blob utilizable; `get`/`verify` la diagnostican


class _LocalReader(ArtifactReader):
    """Vista de solo lectura sobre un `LocalFilesystemStore`. Python no impide alcanzar el almacén por
    introspección; el contrato es que quien carga artefactos solo reciba esta interfaz."""

    def __init__(self, store: LocalFilesystemStore) -> None:
        self._store = store

    def get(self, key: str) -> bytes:
        return self._store.get(key)

    def exists(self, key: str) -> bool:
        return self._store.exists(key)

    def verify(self, key: str) -> None:
        self._store.verify(key)
