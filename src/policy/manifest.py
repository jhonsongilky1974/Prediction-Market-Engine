"""Manifest loading (Fase 3, Paso 3.4.5). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.4.5.

`load_policy_manifest()`/`save_policy_manifest()` -- I/O de archivo JSON
únicamente (nunca red, nunca base de datos). `config/policy/` (creado en
este paso, sin contenido todavía -- el primer manifiesto real se publica
en un paso posterior, cuando exista un deporte listo para shadow mode,
ver `SHADOW_MODE_AND_PROMOTION_GATES.md`) es el directorio destinado a
guardarlos, mismo patrón sencillo que `src/models/registry.py` usa para
metadata de modelos (Fase 2, JSON legible sin dependencias extra).

Todo manifiesto se valida (Corrección H, `src/policy/validation.py`)
antes de aceptarse -- un `PolicyManifest` inválido nunca se carga ni se
guarda con éxito.
"""
from __future__ import annotations

from pathlib import Path

from src.policy.schemas import PolicyManifest
from src.policy.validation import validate_policy_manifest


def load_policy_manifest(path: Path) -> PolicyManifest:
    """Lee, deserializa (schema validation automática vía
    model_validate_json) y valida (Corrección H) un PolicyManifest desde
    un archivo JSON. Levanta si el archivo no existe, si el JSON no es
    un PolicyManifest válido, o si pasa el schema pero falla la
    validación cruzada de src/policy/validation.py."""
    raw = path.read_text(encoding="utf-8")
    manifest = PolicyManifest.model_validate_json(raw)
    validate_policy_manifest(manifest)
    return manifest


def save_policy_manifest(manifest: PolicyManifest, path: Path) -> None:
    """Valida (Corrección H) antes de escribir -- nunca persiste un
    manifiesto inválido."""
    validate_policy_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
