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

Sin lógica de negocio ni acceso a base de datos: lectura de un JSON
versionado en el repositorio.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

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
            )
            if entry.model_version in entries:
                raise ValueError(f"model_version duplicado en el registro: {entry.model_version!r}")
            entries[entry.model_version] = entry
        return ModelRegistryPolicy(entries=entries)
    except Exception as exc:  # noqa: BLE001 -- fail-closed: cualquier fallo rechaza todo
        logger.error("registro de modelos inutilizable en %s: %r -- se rechazan todos los modelos", path, exc)
        return ModelRegistryPolicy(entries={}, load_error=repr(exc))
