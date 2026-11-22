"""Fábrica de paquetes SINTÉTICOS vinculados (base y calibrador) para las pruebas de los cargadores seguros (PR-4).

Cada paquete son tres blobs reales (artefacto B1, metadatos y manifiesto) publicados en un almacén temporal con las
funciones públicas de PR-2. A diferencia de las fábricas de PR-2, el calibrador referencia el manifiesto de la base que se
publicó de verdad (`base_model_ref`), y se pueden fabricar paquetes deliberadamente incoherentes. Ningún dato es real.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from src.models.artifact_package import canonical_metadata_bytes, canonical_package_manifest_bytes
from src.models.model_registry_v2 import PackageRegistry, parse_package_registry
from src.models.safe_artifact_format import MODEL_TYPE_IMPUTED_LOGREG, MODEL_TYPE_PLATT, canonical_bytes

COLUMNS = ["rest_days.participant_a", "rest_days.participant_b", "tournament_round.Final"]
GIT_COMMIT = "1234567890abcdef1234567890abcdef12345678"
DATASET_KEY = "42bfde88e81ad8ced32b32f43087d23f63196149b7b15c08fc0e1b8bf8f6f067"  # solo formato: nunca se resuelve


@dataclass(frozen=True)
class Package:
    model_version: str
    manifest_key: str
    artifact_key: str
    metadata_key: str


def _artifact_doc(kind: str, version: str, variant: int) -> Dict[str, Any]:
    if kind == "base":
        return {
            "schema_version": 1, "model_type": MODEL_TYPE_IMPUTED_LOGREG, "model_version": version,
            "parameters": {
                "input_columns": list(COLUMNS), "imputer_statistics": [3.0, None, 0.0], "scaler_mean": [2.5, 0.2],
                "scaler_scale": [1.5, 0.4], "coef": [0.5, -0.25], "intercept": 0.1 + 0.01 * variant, "classes": [0, 1],
            },
        }
    return {
        "schema_version": 1, "model_type": MODEL_TYPE_PLATT, "model_version": version,
        "parameters": {"coef": 1.2 + 0.01 * variant, "intercept": -0.6, "classes": [0, 1]},
    }


def _metadata_doc(kind: str, version: str, *, columns, ref_version: Optional[str], ref_key: Optional[str]) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "schema_version": 1, "document_type": "model_artifact_metadata", "model_version": version,
        "model_type": MODEL_TYPE_IMPUTED_LOGREG if kind == "base" else MODEL_TYPE_PLATT,
        "trained_at": "2026-11-21T20:00:00Z",
        "provenance": {
            "git_commit": GIT_COMMIT, "git_tree_clean": True, "entrypoint": "scripts/synthetic_trainer.py",
            "environment": {"python": "3.9.6", "scikit_learn": "1.6.1"},
        },
        "data": {"dataset_manifest_ref": {"key": DATASET_KEY, "schema_version": 1}},
        "limits": {"intended_use": "Paquete sintetico de pruebas: no es un modelo real.",
                   "known_limitations": ["Datos sinteticos."]},
    }
    if kind == "base":
        document["training"] = {"feature_columns": list(columns)}
    else:
        document["base_model_ref"] = {"model_version": ref_version, "package_manifest_key": ref_key}
    return document


def publish(store, kind: str, version: str, *, variant: int = 0, ref_version: Optional[str] = None,
            ref_key: Optional[str] = None, metadata_columns=None, manifest_type: Optional[str] = None,
            artifact_bytes: Optional[bytes] = None) -> Package:
    """Publica un paquete `kind` ("base" o "calibrator"). Con los argumentos opcionales fabrica uno incoherente:
    `metadata_columns` (columnas de los metadatos distintas de las del artefacto), `manifest_type` (tipo del manifiesto
    distinto del real) y `artifact_bytes` (bytes de artefacto que B1 rechazaría)."""
    artifact = artifact_bytes if artifact_bytes is not None else canonical_bytes(_artifact_doc(kind, version, variant))
    metadata = canonical_metadata_bytes(
        _metadata_doc(kind, version, columns=metadata_columns or COLUMNS, ref_version=ref_version, ref_key=ref_key)
    )
    artifact_key, metadata_key = store.put(artifact), store.put(metadata)
    real_type = MODEL_TYPE_IMPUTED_LOGREG if kind == "base" else MODEL_TYPE_PLATT
    manifest = canonical_package_manifest_bytes({
        "schema_version": 1, "document_type": "artifact_package_manifest", "model_version": version,
        "artifact": {"key": artifact_key, "format": "safe_json_b1", "schema_version": 1,
                     "model_type": manifest_type or real_type},
        "metadata": {"key": metadata_key, "schema_version": 1},
    })
    return Package(version, store.put(manifest), artifact_key, metadata_key)


def publish_base(store, version: str, **options) -> Package:
    return publish(store, "base", version, **options)


def publish_calibrator(store, version: str, base: Package, **options) -> Package:
    """Calibrador cuya `base_model_ref` apunta (por defecto) al manifiesto REAL de `base`."""
    options.setdefault("ref_version", base.model_version)
    options.setdefault("ref_key", base.manifest_key)
    return publish(store, "calibrator", version, **options)


def base_entry(package: Package, *, version: Optional[str] = None, status: str = "ALLOWED",
               key: Optional[str] = None) -> Dict[str, Any]:
    return {"model_version": version or package.model_version, "status": status, "reason": "entrada sintetica",
            "package_manifest_key": key or package.manifest_key, "role": "base"}


def calibrator_entry(package: Package, base_version: str, *, version: Optional[str] = None, status: str = "ALLOWED",
                     key: Optional[str] = None) -> Dict[str, Any]:
    return {"model_version": version or package.model_version, "status": status, "reason": "entrada sintetica",
            "package_manifest_key": key or package.manifest_key, "role": "calibrator",
            "base_model_version": base_version}


def registry(*entries: Mapping[str, Any]) -> PackageRegistry:
    return parse_package_registry({"models": [], "package_models": [copy.deepcopy(dict(e)) for e in entries]})
