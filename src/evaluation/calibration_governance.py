"""Gobernanza de la evaluación del calibrador de tenis: libro append-only con
cadena de hashes, manifiestos de snapshot, requisito de eventos nuevos entre
intentos y lectura ÚNICA del test (CONTINUITY.md §0.42; contrato en
`governance/calibration/README.md`).

Principios:
- Funciones deterministas: el "ahora" siempre llega como parámetro
  (`recorded_at`); ninguna llama a `datetime.now()` (TEMPORAL_REPRODUCIBILITY_SPEC §3).
- FAIL-CLOSED: cualquier inconsistencia (cadena rota, hash distinto, duplicados,
  solapamientos, no monotonía, firma posterior al entrenamiento) lanza
  `GovernanceError` o produce el veredicto ERROR; nunca se continúa.
- APPEND-ONLY: el libro solo se amplía; cada entrada lleva el hash de la anterior.
  Toda entrada del libro y todo preregistro firmado se incorpora por PR revisable.
  La cadena de hashes por sí sola NO detecta que se trunque el final del libro ni que se
  reescriba la cadena completa: ese ancla es el historial de Git en `main` (ver
  `verify_against_base`: el contenido ya aceptado debe coincidir byte a byte y solo se
  pueden añadir entradas). El anclaje depende de Git, de branch protection y de la revisión
  por PR; no es una protección criptográfica frente a quien pueda reescribir `main`.
- SIN DESERIALIZACIÓN: nada aquí (ni en el evaluador) deserializa joblib/pickle. SHA-256
  prueba identidad de bytes, no seguridad, procedencia, calidad ni validez estadística.
- Este módulo NO entrena, NO promueve ni cablea nada, y NO toca
  `config/model_registry.json`.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from config.settings import PROJECT_ROOT
from src.evaluation.calibration_verdict import (
    N_MIN_EVENTS,
    TAU,
    SplitMetrics,
    Verdict,
    VerdictResult,
    evaluate_test_veto,
    evaluate_validation,
)
from src.models.model_registry_policy import read_bytes_once, resolve_declared_path, resolve_in_dir

try:  # el bloqueo de archivo del libro requiere POSIX; en otras plataformas se falla cerrado al escribir
    import fcntl
except ImportError:  # pragma: no cover -- plataforma no POSIX
    fcntl = None  # type: ignore[assignment]

GOVERNANCE_DIR = PROJECT_ROOT / "governance" / "calibration"
DEFAULT_LEDGER_PATH = GOVERNANCE_DIR / "ledger.jsonl"
GENESIS_HASH = "0" * 64
MANIFEST_SCHEMA_VERSION = 1
ACCEPTED_BASE_REFS = ("main", "origin/main")  # única fuente de verdad aceptada para el anclaje

# Mínimos entre intentos (decisión del preregistro). "Nuevo" = evento que no
# figuró en el conjunto etiquetado de NINGÚN snapshot anterior, en ningún papel.
MIN_NEW_VALIDATION_EVENTS = 30
MIN_NEW_TOTAL_EVENTS = 150

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

ENTRY_TYPES: Dict[str, tuple] = {
    "PREREG_SIGNED": ("prereg_id", "prereg_sha256", "signer", "git_commit_base", "signed_at"),
    "SNAPSHOT_FROZEN": (
        "attempt_id", "snapshot_id", "prereg_id", "manifest_path", "manifest_sha256", "db_sha256", "cutoff_utc",
    ),
    "BASE_TRAINED": (
        "attempt_id", "snapshot_id", "prereg_id", "base_model_version", "base_artifact_sha256",
        "base_metadata_sha256", "trained_at",
    ),
    "CALIBRATOR_TRAINED": (
        "attempt_id", "calibrator_version", "calibrator_artifact_sha256", "calibrator_metadata_sha256",
        "base_model_version", "trained_at", "raw_ece", "raw_brier", "calibrated_ece_oof", "calibrated_brier_oof",
        "n_calibration_events",
    ),
    "PHASE1_VERDICT": ("attempt_id", "verdict", "reason"),
    "TEST_READ": ("attempt_id", "base_artifact_sha256", "test_event_ids_sha256"),
    "TEST_RESULT": ("attempt_id", "status"),
    "FINAL_VERDICT": ("attempt_id", "verdict", "reason"),
    # Estado terminal explícito alternativo a FINAL_VERDICT: sin métricas, nunca se convierte en ELEGIBLE.
    "ATTEMPT_ABANDONED": ("attempt_id", "reason", "author", "abandoned_at"),
}
_EXACT_KEYS_TYPES = ("ATTEMPT_ABANDONED",)  # el payload debe tener EXACTAMENTE esas claves (nada de métricas)
# Tipos que NO se pueden registrar a mano: solo los emite `evaluate_attempt`.
_EVALUATION_ONLY_TYPES = ("PHASE1_VERDICT", "TEST_READ", "TEST_RESULT", "FINAL_VERDICT")


class GovernanceError(Exception):
    """Violación de la gobernanza: se rechaza todo (fail-closed)."""


class LedgerIntegrityError(GovernanceError):
    """Libro ilegible, cadena rota o entrada alterada."""


class ManifestError(GovernanceError):
    """Manifiesto inválido o inconsistente."""


class AttemptNotAllowedError(GovernanceError):
    """No se permite iniciar o repetir el intento."""


class HeldOutReadError(GovernanceError):
    """Lectura del test no permitida o consumida (ya leída, sin preliminar, o interrumpida)."""


class HeldOutAlreadyReadError(HeldOutReadError):
    """El test de este modelo base ya fue leído: no se vuelve a leer."""


class SafeLoadRequiredError(GovernanceError):
    """La evaluación necesitaría deserializar joblib/pickle y no existe un mecanismo auditado de carga
    segura y almacenamiento duradero: se detiene sin escribir nada en el libro."""


# ---------------------------------------------------------------------
# Hashes y JSON canónico
# ---------------------------------------------------------------------


def canonical_json(obj: Any) -> bytes:
    """JSON canónico: claves ordenadas, sin espacios, ASCII, sin NaN/inf."""
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise GovernanceError(f"valor no serializable de forma canónica: {exc!r}") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
    except OSError as exc:
        raise GovernanceError(f"archivo ausente o ilegible: {path} ({exc!r})") from exc
    return digest.hexdigest()


def ids_sha256(event_ids: Sequence[str]) -> str:
    return sha256_hex(canonical_json(list(event_ids)))


def parse_utc(value: Any, name: str) -> datetime:
    """Marca de tiempo ISO-8601 con zona horaria (UTC). Naive o ilegible => error."""
    if not isinstance(value, str) or not value:
        raise GovernanceError(f"{name}: marca de tiempo ausente o no es texto: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GovernanceError(f"{name}: marca de tiempo ilegible: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GovernanceError(f"{name}: la marca de tiempo debe incluir zona horaria (UTC): {value!r}")
    if parsed.utcoffset() != timedelta(0):
        raise GovernanceError(f"{name}: la marca de tiempo debe estar en UTC: {value!r}")
    return parsed


def _require_hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise GovernanceError(f"{name}: no es un SHA-256 hexadecimal en minúsculas: {value!r}")
    return value


def _require_safe_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise GovernanceError(f"{name}: identificador no seguro o ausente: {value!r}")
    return value


def _json_safe(value: Any) -> Any:
    """Número finito tal cual; cualquier otra cosa (NaN, None, texto) como `repr`."""
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return repr(value)


# ---------------------------------------------------------------------
# Libro append-only con cadena de hashes
# ---------------------------------------------------------------------


def _entry_hash(seq: int, prev_sha256: str, entry_type: str, recorded_at: str, payload: Dict[str, Any]) -> str:
    return sha256_hex(
        canonical_json(
            {"seq": seq, "prev_sha256": prev_sha256, "type": entry_type, "recorded_at": recorded_at, "payload": payload}
        )
    )


def _parse_ledger_text(text: str, source: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    prev = GENESIS_HASH
    last_time: Optional[datetime] = None
    if text and not text.endswith("\n"):
        raise LedgerIntegrityError(f"{source}: el libro no termina en salto de línea (escritura incompleta o editada)")
    for line_no, line in enumerate(text.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise LedgerIntegrityError(f"{source}:{line_no}: línea no es JSON ({exc!r})") from exc
        required = ("seq", "prev_sha256", "type", "recorded_at", "payload", "entry_sha256")
        if not isinstance(entry, dict) or any(key not in entry for key in required) or set(entry) != set(required):
            raise LedgerIntegrityError(f"{source}:{line_no}: estructura de entrada inválida")
        if entry["seq"] != line_no or isinstance(entry["seq"], bool):
            raise LedgerIntegrityError(f"{source}:{line_no}: seq={entry['seq']!r} no es consecutivo")
        if entry["prev_sha256"] != prev:
            raise LedgerIntegrityError(f"{source}:{line_no}: cadena rota (prev_sha256 no coincide)")
        if entry["type"] not in ENTRY_TYPES:
            raise LedgerIntegrityError(f"{source}:{line_no}: tipo desconocido {entry['type']!r}")
        if not isinstance(entry["payload"], dict):
            raise LedgerIntegrityError(f"{source}:{line_no}: payload no es un objeto")
        try:
            recorded = parse_utc(entry["recorded_at"], "recorded_at")
        except GovernanceError as exc:
            raise LedgerIntegrityError(f"{source}:{line_no}: {exc}") from exc
        if last_time is not None and recorded < last_time:
            raise LedgerIntegrityError(f"{source}:{line_no}: recorded_at retrocede respecto de la entrada anterior")
        expected = _entry_hash(entry["seq"], entry["prev_sha256"], entry["type"], entry["recorded_at"], entry["payload"])
        if entry["entry_sha256"] != expected:
            raise LedgerIntegrityError(f"{source}:{line_no}: entrada alterada (entry_sha256 no coincide)")
        prev = entry["entry_sha256"]
        last_time = recorded
        entries.append(entry)
    return entries


def read_ledger(path: Path) -> List[Dict[str, Any]]:
    """Lee y VERIFICA el libro completo. Ausente => libro vacío (génesis)."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerIntegrityError(f"{path}: libro ilegible ({exc!r})") from exc
    return _parse_ledger_text(text, str(path))


def _require_posix_lock() -> None:
    if fcntl is None:
        raise GovernanceError(
            "el libro requiere un sistema POSIX (fcntl) para añadir entradas con bloqueo de archivo; "
            "en esta plataforma no se escribe nada"
        )


def _append_entry(path: Path, entry_type: str, payload: Dict[str, Any], recorded_at: str) -> Dict[str, Any]:
    """INTERNO (no es API pública: `register_entry` y el evaluador son las únicas vías gobernadas).
    Añade UNA entrada al final del libro (bajo bloqueo de archivo), tras verificar toda la cadena.
    Nunca reescribe ni borra líneas existentes."""
    _require_posix_lock()  # antes de crear ningún archivo
    if entry_type not in ENTRY_TYPES:
        raise GovernanceError(f"tipo de entrada desconocido: {entry_type!r}")
    if not isinstance(payload, dict):
        raise GovernanceError("el payload debe ser un objeto JSON")
    missing = [key for key in ENTRY_TYPES[entry_type] if key not in payload]
    if missing:
        raise GovernanceError(f"{entry_type}: faltan campos obligatorios {missing}")
    if entry_type in _EXACT_KEYS_TYPES and set(payload) != set(ENTRY_TYPES[entry_type]):
        raise GovernanceError(f"{entry_type}: claves no permitidas {sorted(set(payload) - set(ENTRY_TYPES[entry_type]))}")
    new_time = parse_utc(recorded_at, "recorded_at")
    canonical_json(payload)  # rechaza NaN/inf/tipos no serializables antes de escribir nada

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            entries = _parse_ledger_text(handle.read(), str(path))
            if entries and new_time < parse_utc(entries[-1]["recorded_at"], "recorded_at"):
                raise GovernanceError("recorded_at retrocede respecto de la última entrada del libro")
            seq = len(entries) + 1
            prev = entries[-1]["entry_sha256"] if entries else GENESIS_HASH
            entry = {
                "seq": seq,
                "prev_sha256": prev,
                "type": entry_type,
                "recorded_at": recorded_at,
                "payload": payload,
                "entry_sha256": _entry_hash(seq, prev, entry_type, recorded_at, payload),
            }
            handle.seek(0, 2)
            handle.write(canonical_json(entry).decode("ascii") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return entry


def entries_of(entries: Sequence[Dict[str, Any]], entry_type: str, **match: Any) -> List[Dict[str, Any]]:
    return [
        e for e in entries if e["type"] == entry_type and all(e["payload"].get(k) == v for k, v in match.items())
    ]


# ---------------------------------------------------------------------
# Manifiesto de snapshot
# ---------------------------------------------------------------------


def _check_id_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ManifestError(f"{name}: debe ser una lista de event_id (texto no vacío)")
    if len(value) != len(set(value)):
        raise ManifestError(f"{name}: contiene event_id duplicados")
    if value != sorted(value):
        raise ManifestError(f"{name}: debe estar ordenada")
    return value


def snapshot_id_for(db_sha256: str, cutoff_utc: str) -> str:
    cutoff = parse_utc(cutoff_utc, "cutoff_utc")
    return f"snap_{cutoff:%Y%m%dT%H%M%SZ}_{db_sha256[:12]}"


def build_snapshot_manifest(
    *,
    prereg_id: str,
    db_sha256: str,
    cutoff_utc: str,
    train_event_ids: Sequence[str],
    validation_event_ids: Sequence[str],
    test_event_ids: Sequence[str],
    base_model_version: str,
    base_artifact_sha256: str,
    base_metadata_sha256: str,
    base_trained_at: str,
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    train, validation, test = sorted(train_event_ids), sorted(validation_event_ids), sorted(test_event_ids)
    labeled = sorted(set(train) | set(validation) | set(test))
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "snapshot_id": snapshot_id_for(db_sha256, cutoff_utc),
        "prereg_id": prereg_id,
        "db_sha256": db_sha256,
        "cutoff_utc": cutoff_utc,
        "labeled_event_ids": labeled,
        "labeled_event_ids_sha256": ids_sha256(labeled),
        "train_event_ids": train,
        "train_event_ids_sha256": ids_sha256(train),
        "validation_event_ids": validation,
        "validation_event_ids_sha256": ids_sha256(validation),
        "test_event_ids": test,
        "test_event_ids_sha256": ids_sha256(test),
        "base_model_version": base_model_version,
        "base_artifact_sha256": base_artifact_sha256,
        "base_metadata_sha256": base_metadata_sha256,
        "base_trained_at": base_trained_at,
        "environment": dict(environment or {}),
    }
    validate_snapshot_manifest(manifest)
    return manifest


def manifest_bytes(manifest: Dict[str, Any]) -> bytes:
    """Representación en archivo (la que se hashea y se versiona)."""
    try:
        return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"manifiesto no serializable: {exc!r}") from exc


def validate_snapshot_manifest(manifest: Any) -> Dict[str, Any]:
    """Valida estructura, hashes, ausencia de duplicados y de solapamientos."""
    if not isinstance(manifest, dict):
        raise ManifestError("el manifiesto debe ser un objeto JSON")
    required = (
        "schema_version", "snapshot_id", "prereg_id", "db_sha256", "cutoff_utc", "labeled_event_ids",
        "labeled_event_ids_sha256", "train_event_ids", "train_event_ids_sha256", "validation_event_ids",
        "validation_event_ids_sha256", "test_event_ids", "test_event_ids_sha256", "base_model_version",
        "base_artifact_sha256", "base_metadata_sha256", "base_trained_at",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ManifestError(f"faltan campos del manifiesto: {missing}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"schema_version no soportada: {manifest['schema_version']!r}")
    try:
        _require_safe_id(manifest["prereg_id"], "prereg_id")
        for key in ("db_sha256", "base_artifact_sha256", "base_metadata_sha256"):
            _require_hex64(manifest[key], key)
        parse_utc(manifest["cutoff_utc"], "cutoff_utc")
        parse_utc(manifest["base_trained_at"], "base_trained_at")
    except GovernanceError as exc:
        raise ManifestError(str(exc)) from exc
    if not isinstance(manifest["base_model_version"], str) or not manifest["base_model_version"]:
        raise ManifestError("base_model_version ausente")
    if manifest["snapshot_id"] != snapshot_id_for(manifest["db_sha256"], manifest["cutoff_utc"]):
        raise ManifestError("snapshot_id no coincide con db_sha256 y cutoff_utc")

    lists = {
        name: _check_id_list(manifest[f"{name}_event_ids"], f"{name}_event_ids")
        for name in ("labeled", "train", "validation", "test")
    }
    for name, ids in lists.items():
        if manifest[f"{name}_event_ids_sha256"] != ids_sha256(ids):
            raise ManifestError(f"{name}_event_ids_sha256 no coincide con la lista (hash inconsistente)")
    train, validation, test = (set(lists[n]) for n in ("train", "validation", "test"))
    if train & validation or train & test or validation & test:
        raise ManifestError("las particiones train/validation/test se solapan")
    if train | validation | test != set(lists["labeled"]):
        raise ManifestError("labeled_event_ids no es la unión exacta de train, validation y test")
    return manifest


def load_manifest(path: Path, expected_sha256: str) -> Dict[str, Any]:
    """Carga un manifiesto verificando PRIMERO el hash del archivo (bytes leídos una vez)."""
    _require_hex64(expected_sha256, "expected_sha256")
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ManifestError(f"manifiesto ausente o ilegible: {path} ({exc!r})") from exc
    if sha256_hex(data) != expected_sha256:
        raise ManifestError(f"SHA-256 del manifiesto {path} no coincide con el registrado (manifiesto alterado)")
    try:
        manifest = json.loads(data.decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError(f"manifiesto ilegible: {exc!r}") from exc
    return validate_snapshot_manifest(manifest)


# ---------------------------------------------------------------------
# Eventos nuevos entre intentos (sin reutilización encubierta)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class Novelty:
    new_total: int
    new_validation: int
    prior_events: int


def compute_novelty(manifest: Dict[str, Any], prior_manifests: Sequence[Dict[str, Any]]) -> Novelty:
    """Un evento es NUEVO si no figuró en el conjunto etiquetado de ningún
    snapshot anterior, en ningún papel (train/validation/test)."""
    prior_union = set()
    for prior in prior_manifests:
        prior_union |= set(prior["labeled_event_ids"])
    return Novelty(
        new_total=len(set(manifest["labeled_event_ids"]) - prior_union),
        new_validation=len(set(manifest["validation_event_ids"]) - prior_union),
        prior_events=len(prior_union),
    )


def check_attempt_allowed(
    manifest: Dict[str, Any],
    prior_manifests: Sequence[Dict[str, Any]],
    min_new_validation: int = MIN_NEW_VALIDATION_EVENTS,
    min_new_total: int = MIN_NEW_TOTAL_EVENTS,
) -> Novelty:
    """Primer intento: sin requisito de novedad (rigen los mínimos de política del
    entrenamiento). Intentos posteriores: snapshot genuinamente nuevo, o no se permite repetir."""
    validate_snapshot_manifest(manifest)
    for prior in prior_manifests:
        validate_snapshot_manifest(prior)
    novelty = compute_novelty(manifest, prior_manifests)
    if not prior_manifests:
        return novelty
    if any(prior["snapshot_id"] == manifest["snapshot_id"] for prior in prior_manifests):
        raise AttemptNotAllowedError("el snapshot ya fue usado en un intento anterior")
    if any(prior["db_sha256"] == manifest["db_sha256"] for prior in prior_manifests):
        raise AttemptNotAllowedError("la copia de la base es idéntica a la de un intento anterior")
    latest_cutoff = max(parse_utc(prior["cutoff_utc"], "cutoff_utc") for prior in prior_manifests)
    if parse_utc(manifest["cutoff_utc"], "cutoff_utc") <= latest_cutoff:
        raise AttemptNotAllowedError("cutoff_utc debe ser posterior al de todos los intentos anteriores")
    prior_union = set()
    for prior in prior_manifests:
        prior_union |= set(prior["labeled_event_ids"])
    if not prior_union <= set(manifest["labeled_event_ids"]):
        raise ManifestError("cambios retroactivos: faltan eventos etiquetados de snapshots anteriores")
    if novelty.new_validation < min_new_validation:
        raise AttemptNotAllowedError(
            f"eventos nuevos en validación: {novelty.new_validation} < {min_new_validation}; no se permite repetir"
        )
    if novelty.new_total < min_new_total:
        raise AttemptNotAllowedError(
            f"eventos nuevos en total: {novelty.new_total} < {min_new_total}; no se permite repetir"
        )
    return novelty


# ---------------------------------------------------------------------
# Preregistro firmado ANTES del entrenamiento
# ---------------------------------------------------------------------


def verify_prereg_precedes_training(entries: Sequence[Dict[str, Any]], prereg_id: str, trained_at: str) -> None:
    signed = entries_of(entries, "PREREG_SIGNED", prereg_id=prereg_id)
    if not signed:
        raise GovernanceError(f"no existe PREREG_SIGNED para {prereg_id!r}: no se entrena sin preregistro firmado")
    trained = parse_utc(trained_at, "trained_at")
    entry = signed[0]
    if parse_utc(entry["recorded_at"], "recorded_at") >= trained or parse_utc(entry["payload"]["signed_at"], "signed_at") >= trained:
        raise GovernanceError(
            f"el preregistro {prereg_id!r} no fue firmado antes del entrenamiento (trained_at={trained_at})"
        )


# ---------------------------------------------------------------------
# Sidecar estructurado de un artefacto (SHA-256 y metadatos; NUNCA se deserializa)
# ---------------------------------------------------------------------


def verify_artifact_sidecar(
    models_dir: Optional[Path], version: str, metadata_sha256: str, artifact_sha256: str
) -> Dict[str, Any]:
    """Devuelve el metadato (`.metadata.json`, el sidecar estructurado) de `version` tras verificar el
    SHA-256 del sidecar y del artefacto. Exige `models_dir` explícito. Los bytes del artefacto se leen
    una vez SOLO para calcular su hash y se descartan: aquí NO se deserializa joblib/pickle. Ausencia
    o discrepancia => `GovernanceError` (fail-closed). El mtime del sistema de archivos no se usa."""
    if models_dir is None:
        raise GovernanceError("models_dir (ruta explícita) es obligatorio para verificar artefactos")
    meta_path = resolve_in_dir(Path(models_dir), f"{version}.metadata.json", require_regular_file=True)
    meta_bytes = read_bytes_once(meta_path) if meta_path is not None else None
    if meta_bytes is None:
        raise GovernanceError(f"sidecar de metadatos de {version} ausente o ruta no segura")
    if sha256_hex(meta_bytes) != metadata_sha256:
        raise GovernanceError(f"SHA-256 del sidecar de {version} no coincide con el registrado")
    try:
        metadata = json.loads(meta_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GovernanceError(f"sidecar de {version} ilegible: {exc!r}") from exc
    if not isinstance(metadata, dict):
        raise GovernanceError(f"sidecar de {version} no es un objeto JSON")
    artifact_path = resolve_declared_path(Path(models_dir), metadata.get("file_path"))
    data = read_bytes_once(artifact_path) if artifact_path is not None else None
    if data is None:
        raise GovernanceError(f"artefacto de {version} ausente o file_path fuera de models_dir")
    if sha256_hex(data) != artifact_sha256:
        raise GovernanceError(f"SHA-256 del artefacto de {version} no coincide con el registrado")
    return metadata


def _same_instant(left: Any, right: Any, name: str) -> bool:
    return parse_utc(left, name) == parse_utc(right, name)


def verify_attempt_artifacts(
    entries: Sequence[Dict[str, Any]], manifest: Dict[str, Any], models_dir: Optional[Path], attempt_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Comprueba, contra los archivos reales, que BASE_TRAINED y CALIBRATOR_TRAINED del intento coinciden con
    sus sidecars: hashes, versión, `trained_at` (el mismo instante en manifiesto, libro y metadato) y
    métricas del calibrador. Cualquier ausencia o discrepancia lanza `GovernanceError`."""
    bases = entries_of(entries, "BASE_TRAINED", attempt_id=attempt_id)
    cals = entries_of(entries, "CALIBRATOR_TRAINED", attempt_id=attempt_id)
    if len(bases) != 1 or len(cals) != 1:
        raise GovernanceError("el intento necesita exactamente un BASE_TRAINED y un CALIBRATOR_TRAINED")
    base, cal = bases[0]["payload"], cals[0]["payload"]
    base_meta = verify_artifact_sidecar(models_dir, base["base_model_version"], base["base_metadata_sha256"], base["base_artifact_sha256"])
    if base_meta.get("model_version") != base["base_model_version"]:
        raise GovernanceError("el sidecar del modelo base declara otra model_version")
    for label, other in (("BASE_TRAINED", base["trained_at"]), ("manifiesto", manifest["base_trained_at"])):
        if "trained_at" not in base_meta or not _same_instant(base_meta["trained_at"], other, "trained_at"):
            raise GovernanceError(f"trained_at del sidecar del modelo base no coincide con {label}")
    cal_meta = verify_artifact_sidecar(
        models_dir, cal["calibrator_version"], cal["calibrator_metadata_sha256"], cal["calibrator_artifact_sha256"]
    )
    if cal_meta.get("calibrator_version") != cal["calibrator_version"] or cal_meta.get("base_model_version") != base["base_model_version"]:
        raise GovernanceError("el sidecar del calibrador declara otra versión o pertenece a otro modelo base")
    if "trained_at" not in cal_meta or not _same_instant(cal_meta["trained_at"], cal["trained_at"], "trained_at"):
        raise GovernanceError("trained_at del sidecar del calibrador no coincide con CALIBRATOR_TRAINED")
    for key_ledger, key_meta in (
        ("raw_ece", "raw_ece"), ("raw_brier", "raw_brier"), ("calibrated_ece_oof", "calibrated_ece_oof"),
        ("calibrated_brier_oof", "calibrated_brier_oof"), ("n_calibration_events", "n_calibration_events"),
    ):
        if cal[key_ledger] != cal_meta.get(key_meta):
            raise GovernanceError(f"CALIBRATOR_TRAINED discrepa del sidecar del calibrador en {key_ledger}")
    return base_meta, cal_meta


# ---------------------------------------------------------------------
# Registro de entradas con verificación específica por tipo
# ---------------------------------------------------------------------


def _snapshot_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "governance" / "calibration" / "snapshots"


def _prereg_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "governance" / "calibration" / "preregistrations"


def load_registered_manifest(repo_root: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = entry["payload"]
    expected_prefix = "governance/calibration/snapshots/"
    manifest_path = payload["manifest_path"]
    if not isinstance(manifest_path, str) or not manifest_path.startswith(expected_prefix):
        raise ManifestError(f"manifest_path fuera de {expected_prefix}: {manifest_path!r}")
    name = manifest_path[len(expected_prefix):]
    resolved = resolve_in_dir(_snapshot_dir(repo_root), name, require_regular_file=True)
    if resolved is None:
        raise ManifestError(f"manifest_path no seguro o inexistente: {manifest_path!r}")
    return load_manifest(resolved, payload["manifest_sha256"])


def _attempt_is_closed(entries: Sequence[Dict[str, Any]], attempt_id: str) -> bool:
    return bool(entries_of(entries, "FINAL_VERDICT", attempt_id=attempt_id)) or bool(
        entries_of(entries, "ATTEMPT_ABANDONED", attempt_id=attempt_id)
    )


def register_entry(
    ledger_path: Path,
    entry_type: str,
    payload: Dict[str, Any],
    recorded_at: str,
    repo_root: Path = PROJECT_ROOT,
    models_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Añade al libro una entrada de tipo PREREG_SIGNED, SNAPSHOT_FROZEN, BASE_TRAINED,
    CALIBRATOR_TRAINED o ATTEMPT_ABANDONED tras verificar sus invariantes. BASE_TRAINED y
    CALIBRATOR_TRAINED exigen `models_dir` explícito y verifican sidecar y artefacto (sin
    deserializar). Los veredictos y las lecturas del test solo los emite `evaluate_attempt`."""
    if entry_type in _EVALUATION_ONLY_TYPES:
        raise GovernanceError(f"{entry_type} solo puede emitirlo evaluate_attempt, no registrarse a mano")
    if entry_type not in ENTRY_TYPES:
        raise GovernanceError(f"tipo de entrada desconocido: {entry_type!r}")
    if not isinstance(payload, dict):
        raise GovernanceError("el payload debe ser un objeto JSON")
    missing = [key for key in ENTRY_TYPES[entry_type] if key not in payload]
    if missing:
        raise GovernanceError(f"{entry_type}: faltan campos obligatorios {missing}")
    entries = read_ledger(ledger_path)
    for key in ("prereg_id", "attempt_id", "snapshot_id"):
        if key in payload:
            _require_safe_id(payload[key], key)

    if entry_type == "PREREG_SIGNED":
        prereg_id = payload["prereg_id"]
        if entries_of(entries, "PREREG_SIGNED", prereg_id=prereg_id):
            raise GovernanceError(f"el preregistro {prereg_id!r} ya está firmado")
        _require_hex64(payload["prereg_sha256"], "prereg_sha256")
        if not isinstance(payload["signer"], str) or not payload["signer"].strip():
            raise GovernanceError("signer obligatorio")
        if not isinstance(payload["git_commit_base"], str) or not _HEX40.match(payload["git_commit_base"]):
            raise GovernanceError("git_commit_base debe ser un commit completo de 40 caracteres hexadecimales")
        parse_utc(payload["signed_at"], "signed_at")
        document = resolve_in_dir(_prereg_dir(repo_root), f"{prereg_id}.md", require_regular_file=True)
        if document is None:
            raise GovernanceError(f"no existe el documento de preregistro {prereg_id}.md")
        if sha256_file(document) != payload["prereg_sha256"]:
            raise GovernanceError("SHA-256 del documento de preregistro no coincide con el declarado")

    elif entry_type == "SNAPSHOT_FROZEN":
        if not entries_of(entries, "PREREG_SIGNED", prereg_id=payload["prereg_id"]):
            raise GovernanceError(f"no hay preregistro firmado para {payload['prereg_id']!r}")
        if entries_of(entries, "SNAPSHOT_FROZEN", attempt_id=payload["attempt_id"]):
            raise GovernanceError(f"el intento {payload['attempt_id']!r} ya tiene un snapshot")
        candidate = {"payload": payload}
        manifest = load_registered_manifest(repo_root, candidate)
        for key in ("snapshot_id", "prereg_id", "db_sha256", "cutoff_utc"):
            if manifest[key] != payload[key]:
                raise ManifestError(f"el manifiesto y la entrada discrepan en {key}")
        for earlier in entries_of(entries, "SNAPSHOT_FROZEN"):
            earlier_id = earlier["payload"]["attempt_id"]
            if not _attempt_is_closed(entries, earlier_id):
                raise AttemptNotAllowedError(
                    f"el intento {earlier_id!r} sigue abierto: debe terminar en FINAL_VERDICT o ATTEMPT_ABANDONED "
                    "antes de abrir otro"
                )
        priors = [load_registered_manifest(repo_root, e) for e in entries_of(entries, "SNAPSHOT_FROZEN")]
        check_attempt_allowed(manifest, priors)

    elif entry_type == "BASE_TRAINED":
        snapshots = entries_of(
            entries, "SNAPSHOT_FROZEN", attempt_id=payload["attempt_id"], snapshot_id=payload["snapshot_id"],
            prereg_id=payload["prereg_id"],
        )
        if len(snapshots) != 1:
            raise GovernanceError("no existe un SNAPSHOT_FROZEN coincidente (intento, snapshot y preregistro)")
        if entries_of(entries, "BASE_TRAINED", attempt_id=payload["attempt_id"]):
            raise GovernanceError("el intento ya tiene un modelo base registrado")
        manifest = load_registered_manifest(repo_root, snapshots[0])
        for key in ("base_model_version", "base_artifact_sha256", "base_metadata_sha256"):
            if manifest[key] != payload[key]:
                raise ManifestError(f"el manifiesto y la entrada discrepan en {key} (hash inconsistente)")
        verify_prereg_precedes_training(entries, payload["prereg_id"], payload["trained_at"])
        if not _same_instant(manifest["base_trained_at"], payload["trained_at"], "trained_at"):
            raise GovernanceError("trained_at del manifiesto no coincide con el de BASE_TRAINED")
        base_meta = verify_artifact_sidecar(
            models_dir, payload["base_model_version"], payload["base_metadata_sha256"], payload["base_artifact_sha256"]
        )
        if base_meta.get("model_version") != payload["base_model_version"]:
            raise GovernanceError("el sidecar del modelo base declara otra model_version")
        if "trained_at" not in base_meta or not _same_instant(base_meta["trained_at"], payload["trained_at"], "trained_at"):
            raise GovernanceError("trained_at del sidecar del modelo base no coincide con BASE_TRAINED ni con el manifiesto")

    elif entry_type == "CALIBRATOR_TRAINED":
        bases = entries_of(entries, "BASE_TRAINED", attempt_id=payload["attempt_id"])
        if len(bases) != 1:
            raise GovernanceError("el intento no tiene un modelo base registrado")
        if bases[0]["payload"]["base_model_version"] != payload["base_model_version"]:
            raise GovernanceError("base_model_version del calibrador no coincide con el del modelo base registrado")
        if entries_of(entries, "CALIBRATOR_TRAINED", attempt_id=payload["attempt_id"]):
            raise GovernanceError("el intento ya tiene un calibrador registrado")
        _require_hex64(payload["calibrator_artifact_sha256"], "calibrator_artifact_sha256")
        _require_hex64(payload["calibrator_metadata_sha256"], "calibrator_metadata_sha256")
        if parse_utc(payload["trained_at"], "trained_at") < parse_utc(bases[0]["payload"]["trained_at"], "trained_at"):
            raise GovernanceError("el calibrador no puede entrenarse antes que su modelo base")
        cal_meta = verify_artifact_sidecar(
            models_dir, payload["calibrator_version"], payload["calibrator_metadata_sha256"],
            payload["calibrator_artifact_sha256"],
        )
        if cal_meta.get("calibrator_version") != payload["calibrator_version"] or cal_meta.get("base_model_version") != payload["base_model_version"]:
            raise GovernanceError("el sidecar del calibrador declara otra versión o pertenece a otro modelo base")
        if "trained_at" not in cal_meta or not _same_instant(cal_meta["trained_at"], payload["trained_at"], "trained_at"):
            raise GovernanceError("trained_at del sidecar del calibrador no coincide con CALIBRATOR_TRAINED")
        for key in ("raw_ece", "raw_brier", "calibrated_ece_oof", "calibrated_brier_oof", "n_calibration_events"):
            if payload[key] != cal_meta.get(key):
                raise GovernanceError(f"CALIBRATOR_TRAINED discrepa del sidecar del calibrador en {key}")

    elif entry_type == "ATTEMPT_ABANDONED":
        attempt_id = payload["attempt_id"]
        if not entries_of(entries, "SNAPSHOT_FROZEN", attempt_id=attempt_id):
            raise GovernanceError(f"el intento {attempt_id!r} no existe: no se puede abandonar")
        if _attempt_is_closed(entries, attempt_id):
            raise GovernanceError(f"el intento {attempt_id!r} ya terminó (FINAL_VERDICT o ATTEMPT_ABANDONED)")
        for key in ("reason", "author"):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise GovernanceError(f"{key} obligatorio y no vacío")
        if parse_utc(payload["abandoned_at"], "abandoned_at") > parse_utc(recorded_at, "recorded_at"):
            raise GovernanceError("abandoned_at no puede ser posterior a recorded_at")

    return _append_entry(ledger_path, entry_type, payload, recorded_at)


# ---------------------------------------------------------------------
# Lectura ÚNICA del test (escritura previa en el libro)
# ---------------------------------------------------------------------


def read_held_out_once(
    ledger_path: Path,
    attempt_id: str,
    base_artifact_sha256: str,
    test_event_ids_sha256: str,
    provider: Callable[[], Any],
    recorded_at: str,
) -> Any:
    """Único punto de entrada al test. Exige un PHASE1_VERDICT = ELEGIBLE_PRELIMINAR; rechaza
    si el test de ese modelo base ya fue leído (`TEST_READ` con la misma clave, con o sin
    resultado); escribe `TEST_READ` ANTES de invocar `provider`; escribe `TEST_RESULT` después.
    Si `provider` falla, la lectura queda consumida y se lanza `HeldOutReadError`."""
    entries = read_ledger(ledger_path)
    if entries_of(entries, "ATTEMPT_ABANDONED", attempt_id=attempt_id):
        raise HeldOutReadError("el intento fue abandonado: el test no puede leerse")
    phase1 = entries_of(entries, "PHASE1_VERDICT", attempt_id=attempt_id)
    if not phase1 or phase1[-1]["payload"]["verdict"] != Verdict.ELEGIBLE_PRELIMINAR.value:
        raise HeldOutReadError("el test solo puede leerse con un PHASE1_VERDICT = ELEGIBLE_PRELIMINAR")
    if entries_of(
        entries, "TEST_READ", base_artifact_sha256=base_artifact_sha256, test_event_ids_sha256=test_event_ids_sha256
    ):
        raise HeldOutAlreadyReadError("el test de este modelo base ya fue leído: no se vuelve a leer")
    _append_entry(
        ledger_path, "TEST_READ",
        {"attempt_id": attempt_id, "base_artifact_sha256": base_artifact_sha256, "test_event_ids_sha256": test_event_ids_sha256},
        recorded_at,
    )
    try:
        metrics = provider()
    except Exception as exc:  # noqa: BLE001 -- la lectura ya está consumida: se registra y se falla cerrado
        _append_entry(ledger_path, "TEST_RESULT", {"attempt_id": attempt_id, "status": "ERROR", "error": repr(exc)}, recorded_at)
        raise HeldOutReadError(f"la lectura del test falló y quedó consumida: {exc!r}") from exc
    payload: Dict[str, Any] = {"attempt_id": attempt_id, "status": "OK"}
    if isinstance(metrics, SplitMetrics):
        payload.update(
            raw_ece=_json_safe(metrics.raw_ece), calibrated_ece=_json_safe(metrics.calibrated_ece),
            raw_brier=_json_safe(metrics.raw_brier), calibrated_brier=_json_safe(metrics.calibrated_brier),
            n_events=_json_safe(metrics.n_events),
        )
    else:
        payload["status"] = "INVALID"
    _append_entry(ledger_path, "TEST_RESULT", payload, recorded_at)
    return metrics


# ---------------------------------------------------------------------
# Evaluación completa de un intento
# ---------------------------------------------------------------------


def _metrics_payload(metrics: Any) -> Dict[str, Any]:
    if not isinstance(metrics, SplitMetrics):
        return {}
    return {
        "raw_ece": _json_safe(metrics.raw_ece), "calibrated_ece": _json_safe(metrics.calibrated_ece),
        "raw_brier": _json_safe(metrics.raw_brier), "calibrated_brier": _json_safe(metrics.calibrated_brier),
        "n_events": _json_safe(metrics.n_events),
    }


def evaluate_attempt(
    ledger_path: Path,
    attempt_id: str,
    manifest: Dict[str, Any],
    validation_metrics: SplitMetrics,
    test_metrics_provider: Optional[Callable[[], SplitMetrics]],
    recorded_at: str,
    training_status: Optional[str] = None,
    tau: float = TAU,
    n_min: int = N_MIN_EVENTS,
    allow_test_read: bool = True,
) -> VerdictResult:
    """Evalúa UN intento: fase 1 sobre validación, y SOLO si da ELEGIBLE_PRELIMINAR, una
    lectura única del test como veto. Escribe PHASE1_VERDICT, (TEST_READ, TEST_RESULT) y
    FINAL_VERDICT en el libro. Un intento no se evalúa dos veces. Inconsistencias de
    hashes o del manifiesto producen el veredicto ERROR (queda registrado). El manifiesto debe ser
    EXACTAMENTE el registrado (su SHA-256 se compara con `manifest_sha256` de SNAPSHOT_FROZEN).
    Un intento abandonado no se evalúa. Si la fase 1 da ELEGIBLE_PRELIMINAR y `allow_test_read` es
    False (o no hay proveedor), se lanza `SafeLoadRequiredError` SIN escribir nada en el libro."""
    entries = read_ledger(ledger_path)  # cadena rota => LedgerIntegrityError (nada se escribe)
    snaps = entries_of(entries, "SNAPSHOT_FROZEN", attempt_id=attempt_id)
    bases = entries_of(entries, "BASE_TRAINED", attempt_id=attempt_id)
    cals = entries_of(entries, "CALIBRATOR_TRAINED", attempt_id=attempt_id)
    if len(snaps) != 1 or len(bases) != 1 or len(cals) != 1:
        raise GovernanceError(
            "el intento necesita exactamente un SNAPSHOT_FROZEN, un BASE_TRAINED y un CALIBRATOR_TRAINED en el libro"
        )
    if entries_of(entries, "ATTEMPT_ABANDONED", attempt_id=attempt_id):
        raise AttemptNotAllowedError("el intento fue abandonado (ATTEMPT_ABANDONED): no se evalúa")
    if entries_of(entries, "FINAL_VERDICT", attempt_id=attempt_id):
        raise AttemptNotAllowedError("el intento ya fue evaluado: un intento por snapshot")

    problem = _consistency_problem(manifest, snaps[0]["payload"], bases[0]["payload"], cals[0]["payload"], validation_metrics)
    if problem is not None:
        result = VerdictResult(Verdict.ERROR, problem)
        _append_entry(ledger_path, "FINAL_VERDICT", {"attempt_id": attempt_id, "verdict": result.verdict.value, "reason": result.reason}, recorded_at)
        return result

    phase1 = evaluate_validation(validation_metrics, training_status, tau, n_min)
    if phase1.verdict == Verdict.ELEGIBLE_PRELIMINAR and (not allow_test_read or test_metrics_provider is None):
        raise SafeLoadRequiredError(
            "el candidato es ELEGIBLE_PRELIMINAR y el veto del test requeriría deserializar joblib/pickle; no existe "
            "un mecanismo separado y auditado de carga segura ni almacenamiento duradero: evaluación detenida, "
            "nada se escribió en el libro"
        )
    _append_entry(
        ledger_path, "PHASE1_VERDICT",
        {"attempt_id": attempt_id, "verdict": phase1.verdict.value, "reason": phase1.reason,
         "metrics": _metrics_payload(validation_metrics)},
        recorded_at,
    )

    def provider() -> Any:
        return read_held_out_once(
            ledger_path, attempt_id, bases[0]["payload"]["base_artifact_sha256"],
            manifest["test_event_ids_sha256"], test_metrics_provider, recorded_at,
        )

    try:
        final = evaluate_test_veto(phase1, provider, tau, n_min)
    except HeldOutReadError as exc:
        final = VerdictResult(Verdict.ERROR, str(exc))
    _append_entry(ledger_path, "FINAL_VERDICT", {"attempt_id": attempt_id, "verdict": final.verdict.value, "reason": final.reason}, recorded_at)
    return final


def _consistency_problem(
    manifest: Dict[str, Any], snapshot: Dict[str, Any], base: Dict[str, Any], calibrator: Dict[str, Any], metrics: Any
) -> Optional[str]:
    try:
        validate_snapshot_manifest(manifest)
    except ManifestError as exc:
        return f"manifiesto inválido: {exc}"
    for key in ("snapshot_id", "prereg_id", "db_sha256", "cutoff_utc"):
        if manifest[key] != snapshot[key]:
            return f"el manifiesto discrepa del libro en {key} (hash o dato inconsistente)"
    if sha256_hex(manifest_bytes(manifest)) != snapshot["manifest_sha256"]:
        return "el manifiesto no es EXACTAMENTE el registrado (SHA-256 distinto de manifest_sha256)"
    if not _same_instant(manifest["base_trained_at"], base["trained_at"], "trained_at"):
        return "trained_at del manifiesto no coincide con BASE_TRAINED"
    for key in ("base_model_version", "base_artifact_sha256", "base_metadata_sha256"):
        if manifest[key] != base[key]:
            return f"el manifiesto discrepa de BASE_TRAINED en {key} (hash inconsistente)"
    if calibrator["base_model_version"] != base["base_model_version"]:
        return "el calibrador registrado no pertenece al modelo base registrado"
    if not isinstance(metrics, SplitMetrics):
        return "métricas de validación ausentes"
    expected = SplitMetrics(
        raw_ece=calibrator["raw_ece"], calibrated_ece=calibrator["calibrated_ece_oof"],
        raw_brier=calibrator["raw_brier"], calibrated_brier=calibrator["calibrated_brier_oof"],
        n_events=calibrator["n_calibration_events"],
    )
    if metrics != expected:
        return "las métricas de validación no coinciden con las registradas en CALIBRATOR_TRAINED"
    if metrics.n_events != len(manifest["validation_event_ids"]):
        return "n_validation no coincide con los validation_event_ids del manifiesto"
    return None


# ---------------------------------------------------------------------
# Archivos versionados registrados y anclaje contra la base (Git en main)
# ---------------------------------------------------------------------


def verify_registered_files(entries: Sequence[Dict[str, Any]], repo_root: Path) -> None:
    """Cada preregistro firmado y cada manifiesto registrado deben seguir existiendo y coincidir con el
    hash registrado (un preregistro editado tras la firma o un manifiesto sustituido se rechaza)."""
    for entry in entries_of(entries, "PREREG_SIGNED"):
        prereg_id = entry["payload"]["prereg_id"]
        document = resolve_in_dir(_prereg_dir(repo_root), f"{prereg_id}.md", require_regular_file=True)
        if document is None or sha256_file(document) != entry["payload"]["prereg_sha256"]:
            raise GovernanceError(f"el preregistro {prereg_id!r} falta o fue modificado tras la firma")
    for entry in entries_of(entries, "SNAPSHOT_FROZEN"):
        load_registered_manifest(repo_root, entry)  # ManifestError si falta, se alteró o es inválido


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, check=False)
    except OSError as exc:
        raise GovernanceError(f"git no disponible: {exc!r}") from exc


@dataclass(frozen=True)
class BaseVerification:
    base_ref: str
    base_commit: str
    base_entries: int
    total_entries: int
    base_head_seq: int
    base_head_sha256: str
    head_seq: int
    head_sha256: str
    entries: tuple


def read_base_ledger_bytes(
    repo_root: Path, ledger_path: Path, base_ref: str, allowed_refs: Sequence[str] = ACCEPTED_BASE_REFS
) -> Tuple[str, bytes]:
    """`(commit, bytes)` del libro en `base_ref` (solo `main`/`origin/main`). Si la referencia no se
    puede verificar, falla cerrado. Si el libro no existe en esa base, devuelve bytes vacíos (génesis
    aceptado: la base verificable existe y simplemente aún no contiene libro)."""
    if base_ref not in allowed_refs:
        raise GovernanceError(f"base_ref {base_ref!r} no permitida: solo {list(allowed_refs)}")
    commit = _git(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    if commit.returncode != 0 or not commit.stdout.strip():
        raise GovernanceError(f"no hay base verificable: la referencia {base_ref!r} no existe en el repositorio")
    commit_sha = commit.stdout.decode("ascii").strip()
    try:
        relative = Path(ledger_path).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError as exc:
        raise GovernanceError("el libro debe estar dentro del repositorio") from exc
    listed = _git(repo_root, "ls-tree", commit_sha, "--", relative)
    if listed.returncode != 0:
        raise GovernanceError(f"no se pudo consultar la base: {listed.stderr.decode(errors='replace')[:120]}")
    if not listed.stdout.strip():
        return commit_sha, b""
    shown = _git(repo_root, "show", f"{commit_sha}:{relative}")
    if shown.returncode != 0:
        raise GovernanceError(f"no se pudo leer el libro de la base: {shown.stderr.decode(errors='replace')[:120]}")
    return commit_sha, shown.stdout


def verify_against_base(
    ledger_path: Path,
    repo_root: Path,
    base_ref: str = "origin/main",
    allowed_refs: Sequence[str] = ACCEPTED_BASE_REFS,
) -> BaseVerification:
    """Ancla principal: el libro propuesto debe EXTENDER el aceptado en `main`: el contenido de la base
    coincide byte a byte con el inicio del libro propuesto y solo se añaden entradas. Además valida la
    cadena de hashes de la base y de la propuesta, y que los archivos versionados registrados sigan íntegros.
    Cualquier fallo (sin base verificable, referencia inexistente, truncamiento, sustitución, reescritura)
    lanza `GovernanceError`."""
    commit, base_bytes = read_base_ledger_bytes(repo_root, ledger_path, base_ref, allowed_refs)
    try:
        base_entries = _parse_ledger_text(base_bytes.decode("utf-8"), f"{base_ref}:ledger")
    except UnicodeDecodeError as exc:
        raise LedgerIntegrityError(f"libro de la base ilegible: {exc!r}") from exc
    try:
        local_bytes = Path(ledger_path).read_bytes() if Path(ledger_path).exists() else b""
        entries = _parse_ledger_text(local_bytes.decode("utf-8"), str(ledger_path))
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerIntegrityError(f"libro propuesto ilegible: {exc!r}") from exc
    if not local_bytes.startswith(base_bytes):
        raise LedgerIntegrityError(
            "el contenido ya aceptado en la base no coincide byte a byte con el libro propuesto "
            "(truncamiento, sustitución o reescritura): solo se pueden añadir entradas"
        )
    if len(entries) < len(base_entries):
        raise LedgerIntegrityError("el libro propuesto tiene menos entradas que el aceptado en la base")
    verify_registered_files(entries, repo_root)
    return BaseVerification(
        base_ref=base_ref, base_commit=commit, base_entries=len(base_entries), total_entries=len(entries),
        base_head_seq=len(base_entries), base_head_sha256=base_entries[-1]["entry_sha256"] if base_entries else GENESIS_HASH,
        head_seq=len(entries), head_sha256=entries[-1]["entry_sha256"] if entries else GENESIS_HASH, entries=tuple(entries),
    )


def require_attempt_accepted_in_base(verification: BaseVerification, attempt_id: str) -> Dict[str, Any]:
    """Para evaluar: el preregistro, el snapshot, el modelo base y el calibrador del intento deben estar YA
    aceptados en `main` (dentro del prefijo de la base). Devuelve las entradas del intento."""
    entries = list(verification.entries)
    snaps = entries_of(entries, "SNAPSHOT_FROZEN", attempt_id=attempt_id)
    bases = entries_of(entries, "BASE_TRAINED", attempt_id=attempt_id)
    cals = entries_of(entries, "CALIBRATOR_TRAINED", attempt_id=attempt_id)
    if len(snaps) != 1 or len(bases) != 1 or len(cals) != 1:
        raise GovernanceError("el intento no tiene exactamente un SNAPSHOT_FROZEN, BASE_TRAINED y CALIBRATOR_TRAINED")
    preregs = entries_of(entries, "PREREG_SIGNED", prereg_id=snaps[0]["payload"]["prereg_id"])
    if len(preregs) != 1:
        raise GovernanceError("el preregistro del intento no está firmado en el libro")
    for label, entry in (("PREREG_SIGNED", preregs[0]), ("SNAPSHOT_FROZEN", snaps[0]), ("BASE_TRAINED", bases[0]), ("CALIBRATOR_TRAINED", cals[0])):
        if entry["seq"] > verification.base_entries:
            raise GovernanceError(
                f"{label} (seq={entry['seq']}) no está aceptado en {verification.base_ref}: "
                "debe incorporarse por PR antes de evaluar"
            )
    return {"prereg": preregs[0], "snapshot": snaps[0], "base": bases[0], "calibrator": cals[0]}
