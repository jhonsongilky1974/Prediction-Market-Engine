"""Fábricas de prueba para la gobernanza del calibrador (CONTINUITY.md §0.42).
No es un módulo de tests (sin `test_*`). Todo vive en `tmp_path`: ningún archivo del
repositorio real ni de `data/` se toca, no se entrena nada con datos reales."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from src.evaluation.calibration_governance import (
    build_snapshot_manifest,
    manifest_bytes,
    register_entry,
    sha256_hex,
)

T_PREREG = "2026-01-02T00:00:00+00:00"
T_SNAPSHOT = "2026-02-01T00:00:00+00:00"
T_TRAINED = "2026-03-01T00:00:00+00:00"
T_RECORDED = "2026-03-02T00:00:00+00:00"
T_EVALUATED = "2026-03-03T00:00:00+00:00"
CUTOFF = "2026-02-01T00:00:00+00:00"
COMMIT = "a" * 40


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for sub in ("preregistrations", "snapshots", "candidates"):
        (root / "governance" / "calibration" / sub).mkdir(parents=True)
    return root


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def git_init(root: Path) -> None:
    """Repositorio git temporal con rama `main` (la base verificable del anclaje)."""
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)


def git_accept(root: Path, message: str = "aceptado en main") -> str:
    """Commit en `main` de todo lo que haya (equivale a "aceptado por PR")."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


def fake_base(models_dir: Path, tag: str = "base1", trained_at: str = T_TRAINED) -> dict:
    """Artefacto y sidecar FALSOS (bytes que NO son un pickle; nunca se deserializan)."""
    models_dir.mkdir(parents=True, exist_ok=True)
    version = f"tennis_baseline_logreg_v1_{tag}"
    artifact = models_dir / f"{version}.joblib"
    artifact.write_bytes(f"NOT-A-PICKLE::{tag}".encode())
    meta = models_dir / f"{version}.metadata.json"
    meta.write_text(
        json.dumps({"model_version": version, "trained_at": trained_at, "file_path": str(artifact), "sport": "TENNIS"}),
        encoding="utf-8",
    )
    return {
        "version": version, "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(meta.read_bytes()).hexdigest(), "trained_at": trained_at,
        "artifact_path": artifact, "metadata_path": meta,
    }


def fake_calibrator(models_dir: Path, tag: str, base_version: str, trained_at: str = T_TRAINED, *,
                    raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19, n_events=32) -> dict:
    models_dir.mkdir(parents=True, exist_ok=True)
    version = f"tennis_calibrator_platt_v1_{tag}"
    artifact = models_dir / f"{version}.joblib"
    artifact.write_bytes(f"NOT-A-PICKLE::{tag}".encode())
    meta_dict = {
        "calibrator_version": version, "base_model_version": base_version, "trained_at": trained_at,
        "file_path": str(artifact), "raw_ece": raw_ece, "raw_brier": raw_brier, "calibrated_ece_oof": calibrated_ece,
        "calibrated_brier_oof": calibrated_brier, "n_calibration_events": n_events,
    }
    meta = models_dir / f"{version}.metadata.json"
    meta.write_text(json.dumps(meta_dict), encoding="utf-8")
    return {
        "version": version, "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(meta.read_bytes()).hexdigest(), "trained_at": trained_at,
        "metrics": meta_dict, "artifact_path": artifact, "metadata_path": meta,
    }


def event_ids(start: int, count: int) -> List[str]:
    return [f"ev_{i:06d}" for i in range(start, start + count)]


def split_ids(first: int, n: int) -> Dict[str, List[str]]:
    """`n` eventos consecutivos desde `first`: train 60 %, validación 20 %, test el resto (cronológico)."""
    ids = event_ids(first, n)
    n_train, n_val = int(n * 0.6), int(n * 0.2)
    return {"train": ids[:n_train], "validation": ids[n_train:n_train + n_val], "test": ids[n_train + n_val:]}


def make_manifest(
    n: int = 160,
    *,
    first: int = 0,
    cutoff: str = CUTOFF,
    db_tag: str = "db1",
    prereg_id: str = "prereg_001",
    base_tag: str = "base1",
    base: Optional[dict] = None,
    parts: Optional[Dict[str, List[str]]] = None,
    base_trained_at: Optional[str] = None,
):
    """Manifiesto sintético. Con `base=fake_base(...)` los hashes del modelo base son los de archivos reales
    de prueba; sin él son hashes ficticios (sirve para manifiestos que no se registran con BASE_TRAINED)."""
    parts = parts or split_ids(first, n)
    if base is not None:
        version, art, meta, trained = base["version"], base["artifact_sha256"], base["metadata_sha256"], base["trained_at"]
    else:
        version, art, meta, trained = f"tennis_baseline_logreg_v1_{base_tag}", h(f"{base_tag}-artifact"), h(f"{base_tag}-metadata"), T_TRAINED
    return build_snapshot_manifest(
        prereg_id=prereg_id,
        db_sha256=h(db_tag),
        cutoff_utc=cutoff,
        train_event_ids=parts["train"],
        validation_event_ids=parts["validation"],
        test_event_ids=parts["test"],
        base_model_version=version,
        base_artifact_sha256=art,
        base_metadata_sha256=meta,
        base_trained_at=base_trained_at or trained,
        environment={"python": "3.9.6"},
    )


def write_manifest(root: Path, manifest: dict) -> tuple:
    name = f"{manifest['snapshot_id']}.json"
    data = manifest_bytes(manifest)
    (root / "governance" / "calibration" / "snapshots" / name).write_bytes(data)
    return f"governance/calibration/snapshots/{name}", sha256_hex(data)


def sign_prereg(ledger: Path, root: Path, prereg_id: str = "prereg_001", recorded_at: str = T_PREREG, signed_at: str = T_PREREG):
    doc = root / "governance" / "calibration" / "preregistrations" / f"{prereg_id}.md"
    doc.write_text(f"# PREREGISTRO {prereg_id}\nfirmado por Jhonson Gil\n", encoding="utf-8")
    return register_entry(
        ledger, "PREREG_SIGNED",
        {"prereg_id": prereg_id, "prereg_sha256": sha256_hex(doc.read_bytes()), "signer": "Jhonson Gil",
         "git_commit_base": COMMIT, "signed_at": signed_at},
        recorded_at, root,
    )


def freeze_snapshot(ledger: Path, root: Path, manifest: dict, attempt_id: str = "attempt_001", recorded_at: str = T_SNAPSHOT):
    rel, sha = write_manifest(root, manifest)
    return register_entry(
        ledger, "SNAPSHOT_FROZEN",
        {"attempt_id": attempt_id, "snapshot_id": manifest["snapshot_id"], "prereg_id": manifest["prereg_id"],
         "manifest_path": rel, "manifest_sha256": sha, "db_sha256": manifest["db_sha256"], "cutoff_utc": manifest["cutoff_utc"]},
        recorded_at, root,
    )


def record_base(ledger: Path, root: Path, manifest: dict, models_dir: Path, attempt_id: str = "attempt_001",
                trained_at: Optional[str] = None, recorded_at: str = T_RECORDED):
    return register_entry(
        ledger, "BASE_TRAINED",
        {"attempt_id": attempt_id, "snapshot_id": manifest["snapshot_id"], "prereg_id": manifest["prereg_id"],
         "base_model_version": manifest["base_model_version"], "base_artifact_sha256": manifest["base_artifact_sha256"],
         "base_metadata_sha256": manifest["base_metadata_sha256"], "trained_at": trained_at or manifest["base_trained_at"]},
        recorded_at, root, models_dir,
    )


def record_calibrator(ledger: Path, root: Path, manifest: dict, models_dir: Path, *, attempt_id: str = "attempt_001",
                      raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19, n_events=None,
                      trained_at: str = T_TRAINED, recorded_at: str = T_RECORDED, cal_tag: str = "cal1"):
    n = len(manifest["validation_event_ids"]) if n_events is None else n_events
    cal = fake_calibrator(
        models_dir, cal_tag, manifest["base_model_version"], trained_at, raw_ece=raw_ece, calibrated_ece=calibrated_ece,
        raw_brier=raw_brier, calibrated_brier=calibrated_brier, n_events=n,
    )
    return register_entry(
        ledger, "CALIBRATOR_TRAINED",
        {"attempt_id": attempt_id, "calibrator_version": cal["version"],
         "calibrator_artifact_sha256": cal["artifact_sha256"], "calibrator_metadata_sha256": cal["metadata_sha256"],
         "base_model_version": manifest["base_model_version"], "trained_at": trained_at,
         "raw_ece": raw_ece, "raw_brier": raw_brier, "calibrated_ece_oof": calibrated_ece,
         "calibrated_brier_oof": calibrated_brier, "n_calibration_events": n},
        recorded_at, root, models_dir,
    )


class Attempt(NamedTuple):
    root: Path
    ledger: Path
    manifest: dict
    models_dir: Path


def build_attempt(tmp_path: Path, **calibrator_metrics) -> Attempt:
    """Libro completo de un intento (preregistro, snapshot, base, calibrador) con artefactos FALSOS y métricas sintéticas."""
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = make_manifest(base=base)
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    record_base(ledger, root, manifest, models_dir)
    record_calibrator(ledger, root, manifest, models_dir, **calibrator_metrics)
    return Attempt(root, ledger, manifest, models_dir)


@dataclass
class DbAttempt:
    root: Path
    ledger: Path
    models_dir: Path
    db_copy: Path
    manifest: dict
    base: dict
    calibrator: dict


def build_db_attempt(tmp_path: Path, *, accept: bool = True, n_events: int = 160, **calibrator_metrics) -> DbAttempt:
    """Intento completo con una base de datos REAL temporal (eventos sintéticos y manifiesto reconstruible por el
    evaluador), artefactos FALSOS (sin entrenar ni deserializar nada) y un repositorio git con `main`. Con `accept`
    el estado se commitea en `main` ("aceptado por PR")."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    seed_events(hist, n_events)
    dataset = build_tennis_training_dataset(hist)
    train, validation, test = split_events_temporally(dataset)
    db_copy = tmp_path / "frozen.db"
    shutil.copyfile(tmp_path / "hist.db", db_copy)
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = build_snapshot_manifest(
        prereg_id="prereg_001", db_sha256=hashlib.sha256(db_copy.read_bytes()).hexdigest(), cutoff_utc=CUTOFF,
        train_event_ids=[s.event_id for s in train.samples], validation_event_ids=[s.event_id for s in validation.samples],
        test_event_ids=[s.event_id for s in test.samples], base_model_version=base["version"],
        base_artifact_sha256=base["artifact_sha256"], base_metadata_sha256=base["metadata_sha256"],
        base_trained_at=base["trained_at"],
    )
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    record_base(ledger, root, manifest, models_dir)
    metrics = dict(raw_ece=0.08, calibrated_ece=0.20, raw_brier=0.20, calibrated_brier=0.30)  # por defecto: deterioro
    metrics.update(calibrator_metrics)
    record_calibrator(ledger, root, manifest, models_dir, **metrics)
    calibrator = json.loads(next(models_dir.glob("tennis_calibrator_platt_v1_*.metadata.json")).read_text())
    if accept:
        git_init(root)
        git_accept(root)
    return DbAttempt(root, ledger, models_dir, db_copy, manifest, base, calibrator)


# ---------------------------------------------------------------------
# Mundo entrenado en tmp_path (datos sintéticos; jamás datos reales)
# ---------------------------------------------------------------------

from datetime import datetime, timedelta, timezone

from src.calibration.tennis_calibrator_training import train_tennis_calibrator
from src.evaluation.candidate_registry import (
    CANDIDATE_PURPOSE,
    CANDIDATE_REGISTRY_KEY,
    CANDIDATE_SCHEMA_VERSION,
    CANDIDATE_STATUS,
    load_candidate_registry,
)
from src.models.base import ModelStatus
from src.models.tennis_baseline import (
    build_tennis_training_dataset,
    split_events_temporally,
    train_tennis_baseline_model,
)
from src.storage.history_repository import HistoryRepository
from tests.unit.tennis_preevent_factories import add_preevent_sample

T0_WORLD = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
BASE_TRAINED_AT = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


@dataclass
class TrainedWorld:
    root: Path
    ledger: Path
    models_dir: Path
    hist: HistoryRepository
    db_copy: Path
    base: object
    manifest: dict
    candidate_path: Path


def seed_events(hist: HistoryRepository, n: int = 160, noisy: bool = True) -> None:
    """`n` eventos pre-evento, un día entre sí. Con `noisy` algunas etiquetas contradicen el patrón de
    descanso para que las probabilidades del modelo no sean degeneradas."""
    for i in range(n):
        a_wins = i % 2 == 0
        if noisy and i % 7 == 0:
            a_wins = not a_wins
        add_preevent_sample(
            hist, f"espn_tennis_atp_{i:04d}", T0_WORLD + timedelta(days=i),
            "PARTICIPANT_A_WON" if a_wins else "PARTICIPANT_B_WON",
            rest_a=8.0 if i % 2 == 0 else 1.0, rest_b=1.0 if i % 2 == 0 else 8.0,
            round_context="Final" if i % 2 == 0 else "Qualifying 1st Round",
        )


def write_candidate_file(path: Path, root_info: dict) -> Path:
    path.write_text(json.dumps(root_info, indent=2), encoding="utf-8")
    return path


def candidate_document(manifest: dict, base, attempt_id: str = "attempt_001", **entry_overrides) -> dict:
    entry = {
        "model_version": base.model_version,
        "status": CANDIDATE_STATUS,
        "artifact_sha256": sha256_hex(base.file_path.read_bytes()),
        "metadata_sha256": sha256_hex((base.file_path.parent / f"{base.model_version}.metadata.json").read_bytes()),
        "reason": "candidato de prueba",
    }
    entry.update(entry_overrides)
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION, "purpose": CANDIDATE_PURPOSE, "prereg_id": manifest["prereg_id"],
        "snapshot_id": manifest["snapshot_id"], "attempt_id": attempt_id, CANDIDATE_REGISTRY_KEY: [entry],
    }


def build_trained_world(tmp_path: Path, n_events: int = 160, noisy: bool = True) -> TrainedWorld:
    """Base entrenado con la política real (≥150 eventos, particiones ≥30), snapshot, preregistro y
    libro hasta BASE_TRAINED, y archivo de registro candidato. NO entrena el calibrador."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    seed_events(hist, n_events, noisy)
    models_dir = tmp_path / "models"
    status, base, _ = train_tennis_baseline_model(hist, models_dir=models_dir, now=BASE_TRAINED_AT)
    assert status == ModelStatus.TRAINED and base.candidate_status == "PROMOTION_ELIGIBLE"
    db_copy = tmp_path / "frozen.db"
    shutil.copyfile(tmp_path / "hist.db", db_copy)

    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    manifest = build_snapshot_manifest(
        prereg_id="prereg_001", db_sha256=sha256_hex(db_copy.read_bytes()), cutoff_utc=CUTOFF,
        train_event_ids=base.train_event_ids, validation_event_ids=base.validation_event_ids,
        test_event_ids=base.test_event_ids, base_model_version=base.model_version,
        base_artifact_sha256=sha256_hex(base.file_path.read_bytes()),
        base_metadata_sha256=sha256_hex((models_dir / f"{base.model_version}.metadata.json").read_bytes()),
        base_trained_at=base.trained_at.isoformat(),
    )
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    record_base(ledger, root, manifest, models_dir, trained_at=base.trained_at.isoformat(), recorded_at="2026-06-02T00:00:00+00:00")
    candidate_path = root / "governance" / "calibration" / "candidates" / "candidate_001.json"
    write_candidate_file(candidate_path, candidate_document(manifest, base))
    return TrainedWorld(root, ledger, models_dir, hist, db_copy, base, manifest, candidate_path)


def candidate_policy(world: TrainedWorld):
    return load_candidate_registry(
        world.candidate_path, models_dir=world.models_dir, ledger_path=world.ledger,
        allowed_dir=world.candidate_path.parent,
    )


def train_and_record_calibrator(world: TrainedWorld, recorded_at: str = "2026-06-03T00:00:00+00:00", metadata_overrides=None):
    """Entrena el calibrador con la política candidata y lo registra en el libro. `metadata_overrides`
    (SOLO PARA PRUEBAS, para forzar una rama del veredicto) reescribe métricas del metadato ANTES de
    calcular los hashes que se registran: el libro y el metadato siguen siendo consistentes."""
    status, cal, _ = train_tennis_calibrator(
        world.hist, models_dir=world.models_dir, cv_folds=5, now=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        registry=candidate_policy(world),
    )
    assert status == ModelStatus.TRAINED
    meta = world.models_dir / f"{cal.calibrator_version}.metadata.json"
    if metadata_overrides:
        data = json.loads(meta.read_text(encoding="utf-8"))
        data.update(metadata_overrides)
        meta.write_text(json.dumps(data, indent=2), encoding="utf-8")
        for key, value in metadata_overrides.items():
            setattr(cal, key, value)
    register_entry(
        world.ledger, "CALIBRATOR_TRAINED",
        {"attempt_id": "attempt_001", "calibrator_version": cal.calibrator_version,
         "calibrator_artifact_sha256": sha256_hex(cal.file_path.read_bytes()),
         "calibrator_metadata_sha256": sha256_hex(meta.read_bytes()), "base_model_version": cal.base_model_version,
         "trained_at": cal.trained_at.isoformat(), "raw_ece": cal.raw_ece, "raw_brier": cal.raw_brier,
         "calibrated_ece_oof": cal.calibrated_ece_oof, "calibrated_brier_oof": cal.calibrated_brier_oof,
         "n_calibration_events": cal.n_calibration_events},
        recorded_at, world.root, world.models_dir,
    )
    return cal
