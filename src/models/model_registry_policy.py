"""Registro explícito de modelos ACTIVABLES (lista de permitidos,
fail-closed) -- contención del modelo de tenis con fuga temporal (ver
CONTINUITY.md §0.38).

Regla única: un artefacto de modelo solo se carga en producción si su
`model_version` figura en `config/model_registry.json` con
`status="ALLOWED"` Y su `artifact_sha256` coincide con el SHA-256 real del
archivo `.joblib`. Cualquier otro caso -- modelo desconocido, estado
`INVALID`/`REJECTED_CANDIDATE`, SHA ausente o distinto, registro ausente
o corrupto -- se rechaza (el cargador devuelve "sin modelo", el mismo
estado `MODEL_NOT_TRAINED` ya soportado por todo el pipeline: nunca se
fabrica una probabilidad). Los archivos de artefactos inválidos NO se
mueven, sobrescriben ni borran: se conservan para auditoría, marcados
`INVALID` aquí.

Calibradores: una entrada de calibrador declara además
`base_model_version` (modelo base `ALLOWED` al que está atado) y
`metadata_sha256` (SHA-256 de su `.metadata.json`), de modo que el vínculo
calibrador-modelo y la integridad del metadato son verificables contra el
registro, no contra archivos que cualquiera puede editar.

Helpers genéricos públicos (`sha256_hex`, `resolve_in_dir`,
`resolve_declared_path`, `read_bytes_once`, `ModelRegistryPolicy.check_bytes`,
`ModelRegistryPolicy.allowed_calibrators_for_base`) reutilizados por todos
los cargadores: el SHA-256 se calcula sobre los MISMOS bytes que luego se
deserializan (sin reabrir el archivo tras verificarlo).

Sin lógica de negocio ni acceso a base de datos: lectura de un JSON
versionado en el repositorio.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_MODEL_REGISTRY_PATH = PROJECT_ROOT / "config" / "model_registry.json"


class RegistryStatus(str, Enum):
    ALLOWED = "ALLOWED"
    INVALID = "INVALID"
    REJECTED_CANDIDATE = "REJECTED_CANDIDATE"


@dataclass(frozen=True)
class RegistryEntry:
    model_version: str
    status: RegistryStatus
    reason: str = ""
    artifact_sha256: Optional[str] = None
    # Solo entradas de calibrador: modelo base al que está atado y SHA-256
    # de su `.metadata.json` (integridad del metadato).
    base_model_version: Optional[str] = None
    metadata_sha256: Optional[str] = None


@dataclass(frozen=True)
class ModelRegistryPolicy:
    entries: Dict[str, RegistryEntry] = field(default_factory=dict)
    load_error: Optional[str] = None

    def check(self, model_version: str, actual_artifact_sha256: Optional[str]) -> Tuple[bool, str]:
        """`(activable, motivo)`. Fail-closed: solo `ALLOWED` + SHA
        verificado devuelve `True`."""
        if self.load_error is not None:
            return False, f"registro de modelos no utilizable ({self.load_error}) -- se rechaza todo"
        entry = self.entries.get(model_version)
        if entry is None:
            return False, "modelo no figura en el registro de modelos permitidos"
        if entry.status != RegistryStatus.ALLOWED:
            return False, f"estado {entry.status.value} en el registro: {entry.reason or 'sin motivo documentado'}"
        if not entry.artifact_sha256:
            return False, "entrada ALLOWED sin artifact_sha256 -- no se puede verificar la integridad del archivo"
        if actual_artifact_sha256 is None or actual_artifact_sha256 != entry.artifact_sha256:
            return False, "el SHA-256 del archivo no coincide con el registrado -- artefacto alterado o distinto"
        return True, "ALLOWED y SHA-256 verificado"

    def check_bytes(self, model_version: str, payload: Optional[bytes]) -> Tuple[bool, str]:
        """Como `check`, pero el SHA-256 se calcula sobre `payload`: los
        mismos bytes que el llamador deserializará después (sin ventana
        TOCTOU entre verificar y cargar). `payload=None` (archivo ausente o
        ilegible) se rechaza."""
        if payload is None:
            return self.check(model_version, None)
        return self.check(model_version, sha256_hex(payload))

    def allowed_calibrators_for_base(self, base_model_version: str) -> List[RegistryEntry]:
        """Entradas `ALLOWED` que declaran estar atadas a `base_model_version`.
        Solo artefactos declarados en el registro son candidatos: un archivo
        no registrado, antiguo o ajeno nunca interviene."""
        return [
            e
            for e in self.entries.values()
            if e.status == RegistryStatus.ALLOWED and e.base_model_version == base_model_version
        ]


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_bytes_once(path: Path) -> Optional[bytes]:
    """Lee un archivo completo UNA vez; `None` si no existe o es ilegible.
    El llamador debe verificar y deserializar estos mismos bytes."""
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def resolve_in_dir(directory: Path, filename: str, require_regular_file: bool = False) -> Optional[Path]:
    """Ruta de `filename` DENTRO de `directory`, o `None` si el nombre es
    vacío, contiene separadores/`..`/NUL, es un symlink, resolvería fuera
    del directorio, o (con `require_regular_file`) no es un archivo regular
    existente (p. ej. un `model_version` o `file_path` malicioso del
    registro o de un metadato)."""
    if not isinstance(filename, str) or not filename or filename in (".", "..") or any(
        c in filename for c in ("/", "\\", "\x00")
    ):
        return None
    base = Path(directory).resolve()
    path = base / filename
    if path.is_symlink():
        return None
    if path.resolve().parent != base:
        return None
    if require_regular_file and not path.is_file():
        return None
    return path


def resolve_declared_path(directory: Path, declared: object) -> Optional[Path]:
    """Valida un `file_path` DECLARADO en un metadato (preserva el contrato
    previo: el artefacto se localiza por `metadata.file_path`, que puede
    ser absoluto -- el formato que escribe el entrenamiento -- o relativo).
    Se acepta SOLO si apunta a un archivo regular que está directamente
    dentro de `directory`: se rechazan valores vacíos o que no sean texto,
    NUL, componentes `..`, un directorio distinto de `directory`, nombres
    con separadores, symlinks y cualquier resolución fuera del directorio.
    Delega la validación del nombre en `resolve_in_dir`."""
    if not isinstance(declared, str) or not declared or "\x00" in declared:
        return None
    path = Path(declared)
    if any(part == ".." for part in path.parts):
        return None
    if path.parent != Path("."):
        try:
            if path.parent.resolve() != Path(directory).resolve():
                return None
        except (OSError, RuntimeError):
            return None
    return resolve_in_dir(directory, path.name, require_regular_file=True)


def load_model_registry(path: Path = DEFAULT_MODEL_REGISTRY_PATH) -> ModelRegistryPolicy:
    """Nunca lanza: registro ausente, ilegible o mal formado produce una
    política con `load_error` (rechaza todo modelo)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries: Dict[str, RegistryEntry] = {}
        for item in raw["models"]:
            entry = RegistryEntry(
                model_version=item["model_version"],
                status=RegistryStatus(item["status"]),
                reason=item.get("reason", ""),
                artifact_sha256=item.get("artifact_sha256"),
                base_model_version=item.get("base_model_version"),
                metadata_sha256=item.get("metadata_sha256"),
            )
            for optional_text in (entry.artifact_sha256, entry.base_model_version, entry.metadata_sha256):
                if optional_text is not None and not isinstance(optional_text, str):
                    raise ValueError(f"campo de texto mal formado en la entrada {entry.model_version!r}")
            if entry.model_version in entries:
                raise ValueError(f"model_version duplicado en el registro: {entry.model_version!r}")
            entries[entry.model_version] = entry
        return ModelRegistryPolicy(entries=entries)
    except Exception as exc:  # noqa: BLE001 -- fail-closed: cualquier fallo rechaza todo
        logger.error("registro de modelos inutilizable en %s: %r -- se rechazan todos los modelos", path, exc)
        return ModelRegistryPolicy(entries={}, load_error=repr(exc))
