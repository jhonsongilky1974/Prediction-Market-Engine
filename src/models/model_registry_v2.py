"""Analizador y selección del registro v2 (`package_models`), PR-3 de la serie de gobernanza de artefactos.

Implementa solo lo aprobado en `ARTIFACT_STORAGE_DECISION.md` (D8 y D16, §2) para el alcance de PR-3:

* **Forma (D16, opción B).** El registro v2 es una lista OPCIONAL `package_models` del mismo documento que
  `config/model_registry.json`, separada de `models`. Si la clave falta, el registro v2 está vacío. Cada entrada lleva
  exactamente `model_version`, `status`, `reason`, `package_manifest_key` y `role` (`base` o `calibrator`); una entrada
  `calibrator` exige además `base_model_version` y una `base` lo prohíbe. Un rol ausente o inválido, o una combinación
  incorrecta, es un error de validación: nunca se reclasifica una entrada.
* **Todo o nada (D16).** Si `package_models` está presente pero no es una lista válida, o si una sola entrada incumple el
  esquema, los estados permitidos o la unicidad de `model_version`, `parse_package_registry` lanza
  `PackageRegistryError`. No descarta entradas sueltas ni devuelve resultados parciales.
* **Selección v2 (D8, alcance actual de tenis).** Como máximo un modelo base `ALLOWED` en total y un calibrador
  `ALLOWED` por cada `base_model_version`. Varios candidatos `ALLOWED` bien formados en un grupo dejan "sin modelo"
  (`entry=None`) solo a ese grupo: es un resultado de la selección (`AMBIGUOUS`), no un error de formato.

Lo que este módulo NO hace, a propósito: no lee archivos ni el almacén de blobs, no consulta ni modifica el registro
heredado (el lector heredado ignora `package_models`), no resuelve ni comprueba la existencia o el estado del modelo base
al que apunta un calibrador, no compara manifiestos de paquete, no promueve nada y no está conectado a ningún cargador,
entrenador ni script. Un `ALLOWED` v2 bien formado no activa ningún modelo por sí mismo.

Las reglas de `model_version` y de clave se escriben aquí, sin importar el verificador de paquetes ni el almacén; las
pruebas comprueban su concordancia por comportamiento.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from src.models.model_registry_policy import RegistryStatus

PACKAGE_MODELS_KEY = "package_models"
LEGACY_MODELS_KEY = "models"
MAX_REASON_CHARS = 500

_MODEL_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", re.ASCII)
_MANIFEST_KEY_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)

_COMMON_KEYS: FrozenSet[str] = frozenset({"model_version", "status", "reason", "package_manifest_key", "role"})
_CALIBRATOR_KEYS: FrozenSet[str] = _COMMON_KEYS | {"base_model_version"}
# Los tres estados admitidos (D6/D16), enumerados a propósito: si el enum heredado ganara un cuarto miembro, el registro
# v2 seguiría rechazándolo hasta que una decisión lo admita.
_STATUS_BY_VALUE: Dict[str, RegistryStatus] = {
    "ALLOWED": RegistryStatus.ALLOWED,
    "INVALID": RegistryStatus.INVALID,
    "REJECTED_CANDIDATE": RegistryStatus.REJECTED_CANDIDATE,
}


class PackageRegistryError(ValueError):
    """Un documento o una entrada del registro v2 incumple el esquema, o un argumento de selección es inválido."""


class PackageRole(str, Enum):
    BASE = "base"
    CALIBRATOR = "calibrator"


_ROLE_BY_VALUE: Dict[str, PackageRole] = {role.value: role for role in PackageRole}


@dataclass(frozen=True)
class PackageEntry:
    model_version: str
    status: RegistryStatus
    reason: str
    package_manifest_key: str
    role: PackageRole
    base_model_version: Optional[str] = None


@dataclass(frozen=True)
class PackageRegistry:
    entries: Tuple[PackageEntry, ...] = ()


class SelectionOutcome(str, Enum):
    SELECTED = "SELECTED"
    NO_CANDIDATE = "NO_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class Selection:
    """`entry` solo está presente con `SELECTED`; `NO_CANDIDATE` y `AMBIGUOUS` son ambos "sin modelo" (`entry=None`)."""

    outcome: SelectionOutcome
    entry: Optional[PackageEntry] = None


# ---------------------------------------------------------------------
# Análisis y validación
# ---------------------------------------------------------------------


def _fail(message: str) -> None:
    raise PackageRegistryError(message)


def _expect_model_version(value: Any, where: str) -> str:
    if type(value) is not str or _MODEL_VERSION_RE.fullmatch(value) is None:
        _fail(f"{where}: model_version inválido")
    return value


def _expect_reason(value: Any, where: str) -> str:
    if type(value) is not str:
        _fail(f"{where}: reason debe ser texto")
    if value.strip() == "":
        _fail(f"{where}: reason vacío o compuesto solo por espacios")
    if len(value) > MAX_REASON_CHARS:
        _fail(f"{where}: reason supera {MAX_REASON_CHARS} caracteres")
    if any(unicodedata.category(char) == "Cc" for char in value):
        _fail(f"{where}: reason contiene caracteres de control")
    return value


def _parse_entry(item: Any, index: int) -> PackageEntry:
    where = f"{PACKAGE_MODELS_KEY}[{index}]"
    if type(item) is not dict:
        _fail(f"{where}: la entrada debe ser un objeto")
    raw_role = item.get("role")
    if type(raw_role) is not str or raw_role not in _ROLE_BY_VALUE:
        _fail(f"{where}: role ausente o inválido (solo 'base' o 'calibrator')")
    role = _ROLE_BY_VALUE[raw_role]
    expected = _CALIBRATOR_KEYS if role is PackageRole.CALIBRATOR else _COMMON_KEYS
    present = set(item)
    if present != expected:
        missing, extra = sorted(map(str, expected - present)), sorted(map(str, present - expected))
        _fail(f"{where}: claves inexactas para role={raw_role} (faltan {missing}, sobran {extra})")

    model_version = _expect_model_version(item["model_version"], f"{where}.model_version")
    raw_status = item["status"]
    if type(raw_status) is not str or raw_status not in _STATUS_BY_VALUE:
        _fail(f"{where}: status fuera de los estados permitidos")
    reason = _expect_reason(item["reason"], where)
    key = item["package_manifest_key"]
    if type(key) is not str or _MANIFEST_KEY_RE.fullmatch(key) is None:
        _fail(f"{where}: package_manifest_key inválida (64 hexadecimales en minúsculas)")

    base_model_version: Optional[str] = None
    if role is PackageRole.CALIBRATOR:
        base_model_version = _expect_model_version(item["base_model_version"], f"{where}.base_model_version")
        if base_model_version == model_version:
            _fail(f"{where}: un calibrador no puede referenciarse a sí mismo (base_model_version == model_version)")
    return PackageEntry(
        model_version=model_version,
        status=_STATUS_BY_VALUE[raw_status],
        reason=reason,
        package_manifest_key=key,
        role=role,
        base_model_version=base_model_version,
    )


def _legacy_model_versions(document: dict) -> FrozenSet[str]:
    """Solo la estructura y los `model_version` de `models` que hacen falta para comparar la unicidad entre listas.
    No valida estados, hashes ni duplicados internos de `models`: eso es del lector heredado."""
    if LEGACY_MODELS_KEY not in document:
        _fail(f"falta la lista '{LEGACY_MODELS_KEY}': no se puede comprobar la unicidad de model_version entre listas")
    models = document[LEGACY_MODELS_KEY]
    if type(models) is not list:
        _fail(f"'{LEGACY_MODELS_KEY}' no es una lista: no se puede comprobar la unicidad de model_version entre listas")
    versions: List[str] = []
    for index, item in enumerate(models):
        if type(item) is not dict or type(item.get("model_version")) is not str:
            _fail(f"{LEGACY_MODELS_KEY}[{index}] sin model_version de texto: no se puede comprobar la unicidad entre listas")
        versions.append(item["model_version"])
    return frozenset(versions)


def parse_package_registry(document: object) -> PackageRegistry:
    """Analiza la lista `package_models` del objeto JSON de nivel superior ya decodificado (sin E/S).

    Clave ausente (o lista vacía) -> registro v2 vacío. Cualquier defecto -> `PackageRegistryError` y ningún resultado
    parcial. El documento de entrada no se modifica. Solo si hay al menos una entrada v2 se examina `models`, y solo para
    comparar los `model_version`."""
    if type(document) is not dict:
        _fail("el documento del registro debe ser un objeto JSON")
    if PACKAGE_MODELS_KEY not in document:
        return PackageRegistry(entries=())
    raw = document[PACKAGE_MODELS_KEY]
    if type(raw) is not list:
        _fail(f"'{PACKAGE_MODELS_KEY}' debe ser una lista")
    entries = tuple(_parse_entry(item, index) for index, item in enumerate(raw))
    if not entries:
        return PackageRegistry(entries=())

    seen = set()
    for entry in entries:
        if entry.model_version in seen:
            _fail(f"model_version repetido dentro de '{PACKAGE_MODELS_KEY}'")
        seen.add(entry.model_version)
    if seen & _legacy_model_versions(document):
        _fail(f"un model_version de '{PACKAGE_MODELS_KEY}' ya figura en '{LEGACY_MODELS_KEY}'")
    return PackageRegistry(entries=entries)


# ---------------------------------------------------------------------
# Selección v2 (alcance actual de tenis)
# ---------------------------------------------------------------------


def _select(candidates: List[PackageEntry]) -> Selection:
    if not candidates:
        return Selection(SelectionOutcome.NO_CANDIDATE, None)
    if len(candidates) > 1:
        return Selection(SelectionOutcome.AMBIGUOUS, None)
    return Selection(SelectionOutcome.SELECTED, candidates[0])


def _allowed(registry: PackageRegistry, role: PackageRole) -> List[PackageEntry]:
    if not isinstance(registry, PackageRegistry):
        _fail("el registro debe ser un PackageRegistry")
    return [e for e in registry.entries if e.role is role and e.status is RegistryStatus.ALLOWED]


def select_base(registry: PackageRegistry) -> Selection:
    """Grupo de los modelos base: como máximo uno `ALLOWED` en total."""
    return _select(_allowed(registry, PackageRole.BASE))


def select_calibrator(registry: PackageRegistry, base_model_version: str) -> Selection:
    """Grupo de calibradores de una versión de modelo base: como máximo uno `ALLOWED`. No comprueba que ese modelo base
    exista ni en qué estado está."""
    base_model_version = _expect_model_version(base_model_version, "base_model_version")
    return _select([e for e in _allowed(registry, PackageRole.CALIBRATOR) if e.base_model_version == base_model_version])
