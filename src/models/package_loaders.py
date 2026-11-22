"""Cargadores seguros de tenis desde el almacén de paquetes, PR-4 de la serie de gobernanza de artefactos.

Implementan solo lo decidido en D14 (`ARTIFACT_STORAGE_DECISION.md`, §2), con la selección de D8 y el registro v2 de D16:

* `load_base(reader, registry)` y `load_calibrator(reader, registry, base)` devuelven el `VerifiedPackage` de la
  verificación de paquetes (modelo y metadatos verificados, sin adaptar la interfaz de inferencia ni añadir campos) o
  `None` ("sin modelo").
* Reciben el registro v2 YA ANALIZADO (`PackageRegistry`) y un lector YA CONSTRUIDO: importar este módulo y llamar a los
  cargadores no consulta el entorno ni abre ningún almacén. Solo `open_store_reader_from_environment` lo hace, de forma
  explícita.
* El calibrador recibe un paquete base previamente verificado. Se selecciona por la versión de esa base y su referencia
  (`base_model_ref`) debe coincidir tanto en versión como en clave del manifiesto. No se exige que la base figure en el
  registro v2 ni se le atribuye un estado: ese punto de D8 sigue pendiente.
* Fallos ESPERADOS (selección vacía o ambigua, configuración, lectura, validación o concordancia con el registro)
  devuelven `None` y dejan un único motivo en el log, sin rutas ni contenido del paquete, y sin recurrir al formato
  heredado. Solo se captura una lista cerrada de excepciones: los errores inesperados y de uso se propagan.

No está conectado a ningún flujo de producción, no lee el registro de producción, no toca los cargadores heredados, no
trata MLB y no decide D22.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional

from src.models.artifact_package import (
    MAX_METADATA_BYTES,
    MAX_PACKAGE_MANIFEST_BYTES,
    ArtifactPackageError,
    VerifiedPackage,
    verify_package,
)
from src.models.model_registry_v2 import PackageEntry, PackageRegistry, SelectionOutcome, select_base, select_calibrator
from src.models.safe_artifact_format import MAX_ARTIFACT_BYTES, MODEL_TYPE_IMPUTED_LOGREG, MODEL_TYPE_PLATT
from src.storage.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactReader,
    StoreConfigurationError,
)

logger = logging.getLogger(__name__)

MAX_BLOB_BYTES = max(MAX_ARTIFACT_BYTES, MAX_METADATA_BYTES, MAX_PACKAGE_MANIFEST_BYTES)

# Lista CERRADA de fallos esperados al verificar un paquete. Nada de `ArtifactStoreError` en bloque ni de `Exception`:
# una clave inválida, un `TypeError` o cualquier error de programación deben seguir siendo visibles.
_EXPECTED_FAILURES = (ArtifactNotFoundError, ArtifactIntegrityError, StoreConfigurationError, ArtifactPackageError)


def _stage(exc: BaseException) -> str:
    if isinstance(exc, StoreConfigurationError):
        return "configuración"
    if isinstance(exc, (ArtifactNotFoundError, ArtifactIntegrityError)):
        return "lectura"
    return "validación"


def _refuse(label: str, reason: str, model_version: Optional[str] = None) -> None:
    """Único punto de registro de un fallo esperado: un solo aviso, con un motivo fijo y sin rutas ni contenido."""
    suffix = "" if model_version is None else f" ({model_version})"
    logger.warning("paquete seguro de tenis RECHAZADO [%s]%s: %s -- sin modelo", label, suffix, reason)
    return None


def _check_common_arguments(reader: object, registry: object) -> None:
    if not isinstance(reader, ArtifactReader):
        raise TypeError("reader debe ser un ArtifactReader")
    if not isinstance(registry, PackageRegistry):
        raise TypeError("registry debe ser un PackageRegistry ya analizado")


def _verify_entry(reader: ArtifactReader, entry: PackageEntry, label: str) -> Optional[VerifiedPackage]:
    try:
        return verify_package(reader, entry.package_manifest_key, expected_model_version=entry.model_version)
    except _EXPECTED_FAILURES as exc:
        _refuse(label, f"{_stage(exc)}: {type(exc).__name__}", entry.model_version)
        return None


def _selected_entry(selection, label: str) -> Optional[PackageEntry]:
    if selection.outcome is not SelectionOutcome.SELECTED:
        _refuse(label, f"selección: {selection.outcome.value}")
        return None
    return selection.entry


# ---------------------------------------------------------------------
# Cargadores
# ---------------------------------------------------------------------


def load_base(reader: ArtifactReader, registry: PackageRegistry) -> Optional[VerifiedPackage]:
    """Paquete verificado del único modelo base `ALLOWED` del registro v2, o `None` ("sin modelo")."""
    _check_common_arguments(reader, registry)
    entry = _selected_entry(select_base(registry), "base")
    if entry is None:
        return None
    package = _verify_entry(reader, entry, "base")
    if package is None:
        return None
    if package.manifest.artifact.model_type != MODEL_TYPE_IMPUTED_LOGREG:
        return _refuse("base", "concordancia: el paquete no es un modelo base", entry.model_version)
    return package


def load_calibrator(
    reader: ArtifactReader, registry: PackageRegistry, base: VerifiedPackage
) -> Optional[VerifiedPackage]:
    """Paquete verificado del único calibrador `ALLOWED` atado a la versión de `base`, o `None` ("sin modelo").

    `base` es un paquete base ya verificado. Se comprueba que la referencia de los metadatos del calibrador coincide con
    él en versión y en clave del manifiesto. No se comprueba que `base` figure en el registro v2 ni en qué estado."""
    _check_common_arguments(reader, registry)
    if not isinstance(base, VerifiedPackage):
        raise TypeError("base debe ser un VerifiedPackage")
    if base.manifest.artifact.model_type != MODEL_TYPE_IMPUTED_LOGREG:
        raise ValueError("base debe ser un paquete de modelo base")
    base_version = base.manifest.model_version

    entry = _selected_entry(select_calibrator(registry, base_version), "calibrador")
    if entry is None:
        return None
    package = _verify_entry(reader, entry, "calibrador")
    if package is None:
        return None
    if package.manifest.artifact.model_type != MODEL_TYPE_PLATT:
        return _refuse("calibrador", "concordancia: el paquete no es un calibrador", entry.model_version)
    reference = package.metadata.base_model_ref
    if reference is None:
        return _refuse("calibrador", "concordancia: los metadatos no referencian ninguna base", entry.model_version)
    # La entrada del registro ya está atada a `base_version` por la propia selección (`entry.base_model_version`).
    if reference.model_version != base_version:
        return _refuse("calibrador", "concordancia: la versión de la base referenciada no coincide", entry.model_version)
    if reference.package_manifest_key != base.manifest_key:
        return _refuse(
            "calibrador", "concordancia: la clave del manifiesto de la base referenciada no coincide", entry.model_version
        )
    return package


# ---------------------------------------------------------------------
# Ayudante explícito de configuración
# ---------------------------------------------------------------------


def open_store_reader_from_environment(environ: Optional[Mapping[str, str]] = None) -> Optional[ArtifactReader]:
    """Vista de solo lectura del almacén local de `PME_ARTIFACT_STORE_ROOT`, o `None` si la configuración no permite
    abrirlo (motivo en el log, sin rutas). Es el único punto de este módulo que consulta el entorno; los cargadores
    reciben siempre un lector inyectado."""
    from src.storage.local_filesystem_store import LocalFilesystemStore  # perezoso: importar el módulo no abre nada

    try:
        store = LocalFilesystemStore.from_environment(max_blob_bytes=MAX_BLOB_BYTES, environ=environ)
    except StoreConfigurationError as exc:
        logger.warning(
            "lector del almacén de paquetes NO disponible: configuración: %s -- sin modelo", type(exc).__name__
        )
        return None
    return store.reader()
