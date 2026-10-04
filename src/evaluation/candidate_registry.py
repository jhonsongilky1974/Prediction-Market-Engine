"""Registro CANDIDATO explícito y aislado (CONTINUITY.md §0.42).

Permite entrenar/evaluar el calibrador de un modelo base que AÚN NO está
promovido, sin tocar `config/model_registry.json` y sin que nada de producción
lo vea. Aislamiento por construcción:

- clave principal `candidate_models` (NO `models`): si alguien copia este archivo
  a `config/`, `load_model_registry` exige `raw["models"]`, falla y rechaza TODO
  (fail-closed); promover exige renombrar clave y estados a propósito, vía PR;
- estado propio `CANDIDATE_EVALUATION`, distinto de `ALLOWED`;
- este cargador rechaza la ruta real del registro, cualquier ruta bajo `config/`,
  cualquier archivo fuera de `governance/calibration/candidates/`, symlinks y
  cualquier archivo que contenga la clave `models`;
- declara exactamente UN modelo base (nunca un calibrador): una política candidata
  jamás permite cargar un calibrador;
- verifica los SHA-256 declarados contra los archivos reales (lectura única) y
  contra la entrada `BASE_TRAINED` del libro append-only.

La `ModelRegistryPolicy` que devuelve vive solo en memoria de quien la pidió
(el script de entrenamiento); los artefactos que se produzcan siguen sin figurar
en el registro real, así que producción los rechaza.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import PROJECT_ROOT
from src.evaluation.calibration_governance import (
    DEFAULT_LEDGER_PATH,
    GOVERNANCE_DIR,
    GovernanceError,
    entries_of,
    read_ledger,
    sha256_hex,
)
from src.models.model_registry_policy import (
    DEFAULT_MODEL_REGISTRY_PATH,
    ModelRegistryPolicy,
    RegistryEntry,
    RegistryStatus,
    read_bytes_once,
    resolve_declared_path,
    resolve_in_dir,
)

CANDIDATE_REGISTRY_KEY = "candidate_models"
CANDIDATE_STATUS = "CANDIDATE_EVALUATION"
CANDIDATE_PURPOSE = "candidate_evaluation_only"
CANDIDATE_SCHEMA_VERSION = 1
DEFAULT_CANDIDATES_DIR = GOVERNANCE_DIR / "candidates"

_ALLOWED_TOP_KEYS = {"schema_version", "purpose", "prereg_id", "snapshot_id", "attempt_id", CANDIDATE_REGISTRY_KEY}
_ALLOWED_ENTRY_KEYS = {"model_version", "status", "artifact_sha256", "metadata_sha256", "reason"}


class CandidateRegistryError(GovernanceError):
    """Registro candidato ausente, mal formado, fuera de lugar o inconsistente."""


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def load_candidate_registry(
    path: Path,
    *,
    models_dir: Path,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    allowed_dir: Optional[Path] = None,
    production_path: Path = DEFAULT_MODEL_REGISTRY_PATH,
    config_dir: Path = PROJECT_ROOT / "config",
) -> ModelRegistryPolicy:
    """Política candidata en memoria, construida desde el archivo explícito y verificada contra
    el libro y los artefactos. Cualquier problema lanza `CandidateRegistryError` (fail-closed)."""
    allowed_dir = DEFAULT_CANDIDATES_DIR if allowed_dir is None else allowed_dir  # se lee en cada llamada
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise CandidateRegistryError(f"registro candidato ausente, no regular o symlink: {path}")
    resolved = candidate.resolve()
    if resolved == Path(production_path).resolve():
        raise CandidateRegistryError("se rechaza el registro real de producción como registro candidato")
    config_root = Path(config_dir).resolve()
    if resolved == config_root or config_root in resolved.parents:
        raise CandidateRegistryError("el registro candidato no puede estar bajo config/")
    if resolved.parent != Path(allowed_dir).resolve():
        raise CandidateRegistryError(f"el registro candidato debe estar directamente en {allowed_dir}")

    data = read_bytes_once(resolved)
    if data is None:
        raise CandidateRegistryError(f"registro candidato ilegible: {path}")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CandidateRegistryError(f"registro candidato no es JSON válido: {exc!r}") from exc
    if not isinstance(raw, dict):
        raise CandidateRegistryError("el registro candidato debe ser un objeto JSON")
    if "models" in raw:
        raise CandidateRegistryError("el registro candidato no puede contener la clave 'models' (reservada a producción)")
    unknown = set(raw) - _ALLOWED_TOP_KEYS
    if unknown or CANDIDATE_REGISTRY_KEY not in raw:
        raise CandidateRegistryError(f"claves de nivel superior inválidas: desconocidas={sorted(unknown)}, falta {CANDIDATE_REGISTRY_KEY!r}")
    if raw.get("schema_version") != CANDIDATE_SCHEMA_VERSION or raw.get("purpose") != CANDIDATE_PURPOSE:
        raise CandidateRegistryError("schema_version o purpose inválidos")
    for key in ("prereg_id", "snapshot_id", "attempt_id"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise CandidateRegistryError(f"falta {key}")

    models = raw[CANDIDATE_REGISTRY_KEY]
    if not isinstance(models, list) or len(models) != 1 or not isinstance(models[0], dict):
        raise CandidateRegistryError("el registro candidato debe declarar exactamente UN modelo base")
    entry = models[0]
    if set(entry) - _ALLOWED_ENTRY_KEYS:
        raise CandidateRegistryError(f"campos desconocidos en la entrada: {sorted(set(entry) - _ALLOWED_ENTRY_KEYS)}")
    version = entry.get("model_version")
    if not isinstance(version, str) or not version.startswith("tennis_baseline_"):
        raise CandidateRegistryError("solo se admite un modelo base de tenis (prefijo tennis_baseline_)")
    if entry.get("status") != CANDIDATE_STATUS:
        raise CandidateRegistryError(f"status debe ser exactamente {CANDIDATE_STATUS!r}")
    artifact_sha, metadata_sha = entry.get("artifact_sha256"), entry.get("metadata_sha256")
    if not _is_hex64(artifact_sha) or not _is_hex64(metadata_sha):
        raise CandidateRegistryError("artifact_sha256 y metadata_sha256 son obligatorios (SHA-256 hexadecimal)")

    try:
        entries = read_ledger(ledger_path)
    except GovernanceError as exc:
        raise CandidateRegistryError(f"libro ilegible o alterado: {exc}") from exc
    matches = entries_of(
        entries, "BASE_TRAINED", attempt_id=raw["attempt_id"], snapshot_id=raw["snapshot_id"], prereg_id=raw["prereg_id"],
        base_model_version=version, base_artifact_sha256=artifact_sha, base_metadata_sha256=metadata_sha,
    )
    if len(matches) != 1:
        raise CandidateRegistryError("el libro no contiene un BASE_TRAINED que coincida con el registro candidato (hash o ids)")

    meta_path = resolve_in_dir(Path(models_dir), f"{version}.metadata.json", require_regular_file=True)
    if meta_path is None:
        raise CandidateRegistryError(f"metadato del modelo base ausente o ruta no segura: {version}")
    meta_bytes = read_bytes_once(meta_path)
    if meta_bytes is None or sha256_hex(meta_bytes) != metadata_sha:
        raise CandidateRegistryError("SHA-256 del metadato del modelo base no coincide con el declarado")
    try:
        meta: Dict[str, Any] = json.loads(meta_bytes.decode("utf-8"))
        declared_version = meta["model_version"]
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise CandidateRegistryError(f"metadato del modelo base ilegible: {exc!r}") from exc
    if declared_version != version:
        raise CandidateRegistryError("el metadato declara otra model_version")
    artifact_path = resolve_declared_path(Path(models_dir), meta.get("file_path"))
    if artifact_path is None:
        raise CandidateRegistryError("file_path del modelo base inválido o fuera de models_dir")
    artifact_bytes = read_bytes_once(artifact_path)
    if artifact_bytes is None or sha256_hex(artifact_bytes) != artifact_sha:
        raise CandidateRegistryError("SHA-256 del modelo base no coincide con el declarado")

    return ModelRegistryPolicy(
        entries={
            version: RegistryEntry(
                model_version=version,
                status=RegistryStatus.ALLOWED,  # solo en memoria, solo para entrenar el calibrador candidato
                reason="candidato de evaluación (nunca promoción)",
                artifact_sha256=artifact_sha,
            )
        }
    )
