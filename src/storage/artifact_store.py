"""Contrato del almacén de artefactos direccionado por contenido (PR-1; ver
`ARTIFACT_STORAGE_DECISION.md` §3 y §5).

Un almacén guarda bloques de bytes (blobs) cuya identidad es el SHA-256 de sus bytes: la CLAVE es ese hash en
hexadecimal minúsculo de 64 caracteres. Quien llama entrega siempre bytes o una clave, nunca una ruta (D4, P8).

Garantías del contrato:

* `put(data) -> str` publica los bytes una sola vez y devuelve su clave. Es idempotente: publicar bytes ya
  presentes devuelve la misma clave. Nunca sobrescribe contenido (D5, P3).
* `get(key)` entrega bytes cuyo SHA-256 coincide con la clave, o lanza un error tipado: nunca devuelve `None` ni
  bytes sin verificar (P2, P6).
* `exists(key)` informa solo de la PRESENCIA de un archivo regular; no verifica el hash. `verify(key)` re-calcula
  el hash completo.
* El código que carga modelos debe recibir un `ArtifactReader` (D9, escritor y lector separados): solo
  `ArtifactStore` tiene `put`.

Este módulo solo define el contrato, la validación de claves y los errores; no toca el sistema de archivos, no
lee configuración y no importa nada del proyecto. Publicar un blob NO es promover un modelo (P7): este módulo no
conecta entrenadores, cargadores, registro, libro ni evaluador.

Límites: el hash prueba identidad de bytes, no procedencia, calidad ni validez estadística (ver §6.3 de la
decisión).
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

_KEY_RE = re.compile(r"[0-9a-f]{64}")


class ArtifactStoreError(Exception):
    """Base de todos los errores del almacén (fail-closed)."""


class ArtifactNotFoundError(ArtifactStoreError):
    """El blob solicitado no existe."""


class ArtifactIntegrityError(ArtifactStoreError):
    """El blob o la estructura del almacén es inconsistente: hash o tamaño distintos, entrada que no es un
    archivo regular, symlink, o contenido distinto bajo la misma clave."""


class InvalidArtifactKeyError(ArtifactStoreError):
    """La clave no es un `str` de 64 caracteres hexadecimales en minúsculas."""


class StoreConfigurationError(ArtifactStoreError):
    """El almacén no puede operar por su configuración o su entorno, no por un blob concreto. Cualquier
    operación (`put`, `get`, `exists` y `verify`) puede lanzarla. Causas:

    * configuración inválida al construirlo: raíz no absoluta, inexistente, que no es un directorio o situada
      dentro del repositorio; `max_blob_bytes` ausente o no positivo; plataforma sin soporte;
    * raíz cambiada o no disponible: el directorio raíz ya no es el que se registró al construir el almacén
      (renombrado, sustituido por otro directorio o por un symlink) o ya no existe;
    * directorios internos preexistentes con permisos para grupo u otros: se rechazan SIN modificar sus
      permisos; corregirlos es responsabilidad manual de quien administra el almacén;
    * `sha256/` y `tmp/` en sistemas de archivos distintos, lo que impide publicar por enlace.

    Un fallo de configuración o de entorno nunca se disfraza de blob ausente: `exists` no lo convierte en `False`.
    """


class ArtifactPublishError(ArtifactStoreError):
    """La publicación se rechazó o falló. No queda ningún blob parcial visible."""


def compute_key(data: bytes) -> str:
    """Clave (SHA-256 hexadecimal en minúsculas) de `data`, que debe ser exactamente `bytes`."""
    if type(data) is not bytes:
        raise TypeError("los datos deben ser exactamente `bytes`")
    return hashlib.sha256(data).hexdigest()


def validate_key(key: object) -> str:
    """Devuelve `key` si es un `str` de exactamente 64 caracteres `[0-9a-f]`; si no, `InvalidArtifactKeyError`."""
    if type(key) is not str or _KEY_RE.fullmatch(key) is None:
        raise InvalidArtifactKeyError("la clave debe ser un str de 64 caracteres hexadecimales en minúsculas")
    return key


class ArtifactReader(ABC):
    """Interfaz de SOLO LECTURA: lo único que debe recibir el código que carga artefactos (D9)."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Bytes del blob, verificados contra la clave.

        Lanza `InvalidArtifactKeyError` (clave inválida), `ArtifactNotFoundError` (no existe),
        `ArtifactIntegrityError` (hash o tamaño distintos o entrada anómala) o `StoreConfigurationError`
        (raíz cambiada o no disponible, directorio interno con permisos abiertos; ver esa clase)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """`True` solo si hay un archivo regular para la clave; `False` si no existe o si lo que hay en su lugar
        (o en la estructura interna que lleva a él) no es utilizable: `get` y `verify` diagnostican esos casos.
        NO verifica el hash.

        Lanza `InvalidArtifactKeyError` si la clave no es válida y `StoreConfigurationError` si el almacén no
        puede operar (raíz cambiada o no disponible, directorio interno con permisos abiertos; ver esa clase):
        no devuelve siempre `bool` para una clave válida."""

    @abstractmethod
    def verify(self, key: str) -> None:
        """Re-calcula el hash completo. Devuelve `None` si el blob es íntegro; si no, lanza lo mismo que `get`,
        incluido `StoreConfigurationError`."""


class ArtifactStore(ArtifactReader):
    """Lector más publicación de blobs."""

    @abstractmethod
    def put(self, data: bytes) -> str:
        """Publica `data` (exactamente `bytes`) y devuelve su clave. Idempotente, sin sobrescrituras.

        Lanza `ArtifactPublishError` si se rechaza o falla, `ArtifactIntegrityError` si ya hay contenido distinto
        o corrupto bajo la misma clave o una entrada interna anómala, y `StoreConfigurationError` si el almacén
        no puede operar (raíz cambiada o no disponible, directorio interno con permisos abiertos; ver esa clase)."""
