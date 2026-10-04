"""Guardián FAIL-CLOSED del calibrador de tenis conectado al registro de
modelos (CONTINUITY.md §0.38). `load_latest_tennis_calibrator` solo carga un
calibrador si el modelo base Y el calibrador figuran `ALLOWED` en el
registro, la entrada del calibrador está atada al modelo base
(`base_model_version`) y protege su metadato (`metadata_sha256`), y todos los
SHA-256 coinciden con los bytes leídos. Cualquier duda sobre el artefacto
seleccionado => `None`, motivo en el log, y NUNCA fallback hacia otro
calibrador. Solo se consideran artefactos declarados en el registro."""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import io
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import joblib
import pytest

import src.calibration.tennis_calibrator_training as calibrator_module
from scripts.run_e2e import SPORT_ADAPTERS
from src.calibration.tennis_calibrator_training import (
    load_latest_tennis_calibrator,
    train_tennis_calibrator,
)
from src.features.tennis_features import TennisFeatureInputs
from src.models.base import ModelStatus
from src.models.model_registry_policy import (
    DEFAULT_MODEL_REGISTRY_PATH,
    ModelRegistryPolicy,
    RegistryEntry,
    RegistryStatus,
    load_model_registry,
)
from src.models.schemas import EventStatus, Sport
from src.models.tennis_baseline import load_latest_tennis_artifact, train_tennis_baseline_model
from src.orchestration.decision_pipeline import _build_record_context
from src.storage.history_repository import HistoryRepository
from tests.unit.tennis_preevent_factories import (
    T0,
    add_preevent_sample,
    make_tennis_record,
    promote_artifacts_for_test,
    promote_calibrators_for_test,
)

DEFECTIVE_MODEL = "tennis_baseline_logreg_v1_20260801T184245Z"
DEFECTIVE_CALIBRATOR = "tennis_calibrator_platt_v1_20260801T202949Z"


@dataclass
class World:
    models_dir: Path
    base_version: str
    calibrator_version: str
    registry: ModelRegistryPolicy  # base y calibrador ALLOWED (atado, con metadata_sha256)
    base_meta: Path
    base_file: Path
    cal_meta: Path
    cal_file: Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(version: str, status: RegistryStatus, sha: Optional[str], **extra) -> RegistryEntry:
    return RegistryEntry(version, status, "test", sha, **extra)


def _replace_entry(world: World, version: str, **changes) -> ModelRegistryPolicy:
    """Registro igual a `world.registry` con la entrada `version` modificada
    (`status=...`, `artifact_sha256=...`, `base_model_version=...`,
    `metadata_sha256=...`); `_DELETE` la elimina."""
    entries = dict(world.registry.entries)
    if changes.get("_delete"):
        entries.pop(version)
    else:
        entries[version] = dataclasses.replace(entries[version], **changes)
    return ModelRegistryPolicy(entries=entries)


@pytest.fixture
def world(tmp_path) -> World:
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    models_dir = tmp_path / "models"
    for i in range(40):
        a_wins = i % 2 == 0
        add_preevent_sample(
            hist, f"espn_tennis_atp_{i:03d}", T0 + timedelta(days=i),
            "PARTICIPANT_A_WON" if a_wins else "PARTICIPANT_B_WON",
            rest_a=8.0 if a_wins else 1.0, rest_b=1.0 if a_wins else 8.0,
            round_context="Final" if a_wins else "Qualifying 1st Round",
        )
    status, base, _ = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10, min_partition_events=3)
    assert status == ModelStatus.TRAINED
    base_registry = promote_artifacts_for_test(models_dir)
    status, cal, _ = train_tennis_calibrator(hist, models_dir=models_dir, cv_folds=5, registry=base_registry)
    assert status == ModelStatus.TRAINED
    return World(
        models_dir=models_dir,
        base_version=base.model_version,
        calibrator_version=cal.calibrator_version,
        registry=promote_calibrators_for_test(models_dir, base_registry),
        base_meta=models_dir / f"{base.model_version}.metadata.json",
        base_file=base.file_path,
        cal_meta=models_dir / f"{cal.calibrator_version}.metadata.json",
        cal_file=cal.file_path,
    )


def _load(world: World, registry: Optional[ModelRegistryPolicy] = None, base_version: Optional[str] = None):
    return load_latest_tennis_calibrator(
        base_version or world.base_version, models_dir=world.models_dir,
        registry=registry if registry is not None else world.registry,
    )


def _edit_json(path: Path, **changes) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")


def _rewrite_calibrator_meta(world: World, **changes) -> ModelRegistryPolicy:
    """Edita el metadato del calibrador y devuelve el registro con
    `metadata_sha256` ACTUALIZADO, para que el cargador llegue a las
    comprobaciones de coherencia internas (no solo al hash)."""
    _edit_json(world.cal_meta, **changes)
    return _replace_entry(world, world.calibrator_version, metadata_sha256=_sha(world.cal_meta))


def _assert_rejected(caplog, fragment: str) -> None:
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("RECHAZADO" in m and fragment in m for m in messages), messages


def _clone_calibrator(world: World, new_version: str, registered: bool = True) -> ModelRegistryPolicy:
    """Copia el par calibrador como `new_version` (archivos coherentes) y, si
    `registered`, devuelve el registro con una entrada ALLOWED válida."""
    new_file = world.models_dir / f"{new_version}.joblib"
    shutil.copy(world.cal_file, new_file)
    meta = json.loads(world.cal_meta.read_text(encoding="utf-8"))
    meta.update(calibrator_version=new_version, file_path=str(new_file))
    new_meta = world.models_dir / f"{new_version}.metadata.json"
    new_meta.write_text(json.dumps(meta), encoding="utf-8")
    if not registered:
        return world.registry
    entries = dict(world.registry.entries)
    entries[new_version] = RegistryEntry(
        new_version, RegistryStatus.ALLOWED, "test", _sha(new_file),
        base_model_version=world.base_version, metadata_sha256=_sha(new_meta),
    )
    return ModelRegistryPolicy(entries=entries)


# --- único caso positivo ----------------------------------------------------


def test_loads_only_when_base_and_calibrator_are_allowed_bound_and_hashes_verified(world, caplog):
    with caplog.at_level(logging.INFO):
        calibrator = _load(world)

    assert calibrator is not None
    assert calibrator.calibration_method == "PLATT_V1"
    assert 0.0 <= calibrator.calibrate(0.7) <= 1.0
    assert any("ALLOWED, SHA-256 verificado" in r.getMessage() for r in caplog.records)


# --- modelo base: desconocido / inválido / no permitido / hash ---------------


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unknown", "no figura en el registro"),
        ("invalid", "INVALID"),
        ("rejected_candidate", "REJECTED_CANDIDATE"),
        ("wrong_sha", "SHA-256"),
        ("missing_sha", "artifact_sha256"),
    ],
)
def test_rejects_when_base_model_is_not_explicitly_allowed(world, caplog, case, expected):
    base = world.base_version
    registry = {
        "unknown": _replace_entry(world, base, _delete=True),
        "invalid": _replace_entry(world, base, status=RegistryStatus.INVALID),
        "rejected_candidate": _replace_entry(world, base, status=RegistryStatus.REJECTED_CANDIDATE),
        "wrong_sha": _replace_entry(world, base, artifact_sha256="0" * 64),
        "missing_sha": _replace_entry(world, base, artifact_sha256=None),
    }[case]

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, expected)


def test_rejects_when_base_model_file_was_altered_after_registration(world, caplog):
    world.base_file.write_bytes(world.base_file.read_bytes() + b"tampered")

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "SHA-256")


def test_rejects_when_base_model_file_is_missing(world, caplog):
    world.base_file.unlink()

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "file_path del modelo base")


def test_rejects_when_base_metadata_flags_rejected_candidate(world, caplog):
    _edit_json(world.base_meta, candidate_status="REJECTED_CANDIDATE")

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "REJECTED_CANDIDATE")


def test_rejects_when_base_metadata_missing_unreadable_or_inconsistent(world, caplog):
    world.base_meta.write_text("{corrupt", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "ilegible")

    world.base_meta.unlink()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "ausente o ilegible")

    caplog.clear()
    world.base_meta.write_text(json.dumps({"model_version": "other"}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "inconsistente")


def test_rejects_when_requested_base_model_has_no_registered_calibrator(world, caplog):
    other = "tennis_baseline_logreg_v1_other"
    shutil.copy(world.base_file, world.models_dir / f"{other}.joblib")
    (world.models_dir / f"{other}.metadata.json").write_text(
        json.dumps({"model_version": other, "file_path": str(world.models_dir / f"{other}.joblib")}), encoding="utf-8"
    )
    entries = dict(world.registry.entries)
    entries[other] = _entry(other, RegistryStatus.ALLOWED, _sha(world.base_file))

    with caplog.at_level(logging.WARNING):
        assert _load(world, ModelRegistryPolicy(entries=entries), base_version=other) is None
    _assert_rejected(caplog, "ningún calibrador ALLOWED atado")


# --- entrada del calibrador en el registro ------------------------------------


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unregistered", "ningún calibrador ALLOWED atado"),
        ("invalid", "ningún calibrador ALLOWED atado"),
        ("rejected_candidate", "ningún calibrador ALLOWED atado"),
        ("no_base_declared", "ningún calibrador ALLOWED atado"),
        ("other_base_declared", "ningún calibrador ALLOWED atado"),
        ("wrong_artifact_sha", "SHA-256"),
        ("missing_artifact_sha", "artifact_sha256"),
        ("missing_metadata_sha", "metadata_sha256"),
        ("wrong_metadata_sha", "metadato alterado"),
    ],
)
def test_rejects_when_calibrator_registry_entry_is_not_a_valid_bound_allowed_entry(world, caplog, case, expected):
    cal = world.calibrator_version
    registry = {
        "unregistered": _replace_entry(world, cal, _delete=True),
        "invalid": _replace_entry(world, cal, status=RegistryStatus.INVALID),
        "rejected_candidate": _replace_entry(world, cal, status=RegistryStatus.REJECTED_CANDIDATE),
        "no_base_declared": _replace_entry(world, cal, base_model_version=None),
        "other_base_declared": _replace_entry(world, cal, base_model_version="tennis_baseline_logreg_v1_other"),
        "wrong_artifact_sha": _replace_entry(world, cal, artifact_sha256="0" * 64),
        "missing_artifact_sha": _replace_entry(world, cal, artifact_sha256=None),
        "missing_metadata_sha": _replace_entry(world, cal, metadata_sha256=None),
        "wrong_metadata_sha": _replace_entry(world, cal, metadata_sha256="0" * 64),
    }[case]

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, expected)


def test_rejects_when_calibrator_registry_name_is_not_a_safe_file_name(world, caplog):
    entries = dict(world.registry.entries)
    entries["../evil"] = _entry(
        "../evil", RegistryStatus.ALLOWED, "0" * 64, base_model_version=world.base_version, metadata_sha256="0" * 64
    )
    entries.pop(world.calibrator_version)

    with caplog.at_level(logging.WARNING):
        assert _load(world, ModelRegistryPolicy(entries=entries)) is None
    _assert_rejected(caplog, "no seguro")


# --- artefacto y metadato del calibrador ---------------------------------------------


def test_rejects_when_calibrator_file_was_altered(world, caplog):
    world.cal_file.write_bytes(world.cal_file.read_bytes() + b"tampered")

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "SHA-256")


def test_rejects_when_calibrator_file_is_missing(world, caplog):
    world.cal_file.unlink()

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "file_path del calibrador")


def test_rejects_when_calibrator_file_matches_hash_but_cannot_be_deserialized(world, caplog):
    world.cal_file.write_bytes(b"not a joblib payload")
    sha = _sha(world.cal_file)
    _edit_json(world.cal_meta, artifact_sha256=sha)
    entries = dict(world.registry.entries)
    entries[world.calibrator_version] = dataclasses.replace(
        entries[world.calibrator_version], artifact_sha256=sha, metadata_sha256=_sha(world.cal_meta)
    )

    with caplog.at_level(logging.WARNING):
        assert _load(world, ModelRegistryPolicy(entries=entries)) is None
    _assert_rejected(caplog, "no pudo cargarse")


def test_rejects_when_calibrator_metadata_file_is_missing(world, caplog):
    world.cal_meta.unlink()

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "ausente o ilegible")


def test_rejects_when_calibrator_metadata_was_altered_after_registration(world, caplog):
    _edit_json(world.cal_meta, n_calibration_samples=999)  # cualquier cambio rompe metadata_sha256

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "metadato alterado")


def test_rejects_when_calibrator_metadata_is_unreadable_even_with_matching_hash(world, caplog):
    world.cal_meta.write_text("{corrupt", encoding="utf-8")
    registry = _replace_entry(world, world.calibrator_version, metadata_sha256=_sha(world.cal_meta))

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "ilegible")


@pytest.mark.parametrize("missing_key", ["artifact_sha256", "trained_at", "base_model_version", "calibrator_version"])
def test_rejects_when_calibrator_metadata_is_incomplete(world, caplog, missing_key):
    registry = _rewrite_calibrator_meta(world, **{missing_key: None})

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "incompleto")


def test_rejects_when_calibrator_metadata_trained_at_is_not_a_timestamp(world, caplog):
    registry = _rewrite_calibrator_meta(world, trained_at="not-a-date")

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "ilegible")


def test_rejects_when_calibrator_metadata_declares_another_calibrator_version(world, caplog):
    registry = _rewrite_calibrator_meta(world, calibrator_version="tennis_calibrator_platt_v1_19990101T000000Z")

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "inconsistente")


def test_rejects_when_calibrator_metadata_base_differs_from_registry_and_request(world, caplog):
    """Vínculo calibrador-modelo verificable: metadato (autenticado por
    metadata_sha256) debe coincidir con la entrada del registro y con el
    modelo base solicitado."""
    registry = _rewrite_calibrator_meta(world, base_model_version="tennis_baseline_logreg_v1_other")

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "vínculo calibrador-modelo inconsistente")


def test_rejects_when_metadata_artifact_sha_claim_differs_from_the_file(world, caplog):
    registry = _rewrite_calibrator_meta(world, artifact_sha256="f" * 64)

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    _assert_rejected(caplog, "artifact_sha256 del metadato")


# --- registro ausente / ilegible / malformado --------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{not json",
        "[]",
        '{"models": [{"model_version": "x", "status": "WHATEVER"}]}',
        '{"models": [{"model_version": "x", "status": "ALLOWED", "base_model_version": 7}]}',
        '{"models": [{"model_version": "x", "status": "ALLOWED", "metadata_sha256": ["a"]}]}',
    ],
)
def test_rejects_when_registry_is_absent_unreadable_or_malformed(world, tmp_path, caplog, content):
    path = tmp_path / "registry.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    broken = load_model_registry(path)
    assert broken.load_error is not None

    with caplog.at_level(logging.WARNING):
        assert _load(world, broken) is None
    _assert_rejected(caplog, "registro de modelos no utilizable")


# --- solo artefactos declarados en el registro; sin fallback -----------------------------


def test_irrelevant_unregistered_or_corrupt_files_never_block_a_valid_registered_candidate(world, caplog):
    models = world.models_dir
    # metadatos corruptos con nombre de calibrador: más antiguo, más reciente y basura
    (models / "tennis_calibrator_platt_v1_19990101T000000Z.metadata.json").write_text("{x", encoding="utf-8")
    (models / "tennis_calibrator_platt_v1_29990101T000000Z.metadata.json").write_text("{x", encoding="utf-8")
    (models / "tennis_calibrator_platt_v1_garbage.metadata.json").write_bytes(b"\xff\xfe\x00")
    (models / "tennis_calibrator_platt_v1_orphan.joblib").write_bytes(b"junk")
    (models / "tennis_baseline_logreg_v1_garbage.metadata.json").write_text("{x", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        assert _load(world) is not None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_an_unregistered_newer_calibrator_is_ignored_and_the_registered_one_loads(world, caplog):
    newer = "tennis_calibrator_platt_v1_29990101T000000Z"
    _clone_calibrator(world, newer, registered=False)

    with caplog.at_level(logging.INFO):
        assert _load(world) is not None
    assert any(world.calibrator_version in r.getMessage() and "cargado" in r.getMessage() for r in caplog.records)
    assert not any(newer in r.getMessage() for r in caplog.records)


def test_registered_calibrators_of_other_bases_do_not_interfere(world):
    entries = dict(world.registry.entries)
    entries["tennis_calibrator_platt_v1_29990101T000000Z"] = _entry(
        "tennis_calibrator_platt_v1_29990101T000000Z", RegistryStatus.ALLOWED, "0" * 64,
        base_model_version="tennis_baseline_logreg_v1_other", metadata_sha256="0" * 64,
    )

    assert _load(world, ModelRegistryPolicy(entries=entries)) is not None


def test_non_allowed_newer_entry_is_ignored_the_registry_state_is_explicit(world, caplog):
    newer = "tennis_calibrator_platt_v1_29990101T000000Z"
    registry = _clone_calibrator(world, newer)
    entries = dict(registry.entries)
    entries[newer] = dataclasses.replace(entries[newer], status=RegistryStatus.INVALID)

    with caplog.at_level(logging.INFO):
        assert _load(world, ModelRegistryPolicy(entries=entries)) is not None
    assert any(world.calibrator_version in r.getMessage() and "cargado" in r.getMessage() for r in caplog.records)


def test_newest_registered_allowed_calibrator_is_selected_when_several_are_valid(world, caplog):
    older = "tennis_calibrator_platt_v1_20000101T000000Z"
    registry = _clone_calibrator(world, older)

    with caplog.at_level(logging.INFO):
        assert _load(world, registry) is not None
    assert any(world.calibrator_version in r.getMessage() and "cargado" in r.getMessage() for r in caplog.records)
    assert not any(older in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("corruption", ["artifact_altered", "metadata_altered", "artifact_missing", "metadata_missing"])
def test_selected_registered_candidate_that_is_corrupt_fails_closed_without_falling_back(world, caplog, corruption):
    """Hay un calibrador más antiguo VÁLIDO y ALLOWED, pero el seleccionado
    (el más reciente registrado) está corrupto: `None`, sin retroceder."""
    older = "tennis_calibrator_platt_v1_20000101T000000Z"
    registry = _clone_calibrator(world, older)
    assert _load(world, registry) is not None  # sanity: antes de corromper carga el seleccionado
    if corruption == "artifact_altered":
        world.cal_file.write_bytes(world.cal_file.read_bytes() + b"x")
    elif corruption == "metadata_altered":
        _edit_json(world.cal_meta, n_calibration_samples=1)
    elif corruption == "artifact_missing":
        world.cal_file.unlink()
    else:
        world.cal_meta.unlink()

    with caplog.at_level(logging.INFO):
        assert _load(world, registry) is None
    _assert_rejected(caplog, world.calibrator_version)
    assert not any(older in r.getMessage() and "cargado" in r.getMessage() for r in caplog.records)


def test_default_registry_rejects_unregistered_pair_no_fallback_to_latest(world, caplog):
    """`registry=None` usa el registro REAL del repositorio: el par entrenado
    en tmp no figura ahí -> `None`."""
    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_calibrator(world.base_version, models_dir=world.models_dir) is None
    _assert_rejected(caplog, "no figura en el registro")


def test_missing_models_dir_returns_none_with_observable_reason(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_calibrator("any", models_dir=tmp_path / "nope", registry=ModelRegistryPolicy()) is None
    _assert_rejected(caplog, "no existe")


def test_real_registry_rejects_the_defective_model_and_its_calibrator_even_if_files_are_present(tmp_path, caplog):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / f"{DEFECTIVE_MODEL}.joblib").write_bytes(b"x")
    (models_dir / f"{DEFECTIVE_MODEL}.metadata.json").write_text(
        json.dumps({"model_version": DEFECTIVE_MODEL, "file_path": str(models_dir / f"{DEFECTIVE_MODEL}.joblib")}),
        encoding="utf-8",
    )
    cal_file = models_dir / f"{DEFECTIVE_CALIBRATOR}.joblib"
    cal_file.write_bytes(b"y")
    (models_dir / f"{DEFECTIVE_CALIBRATOR}.metadata.json").write_text(
        json.dumps({
            "calibrator_version": DEFECTIVE_CALIBRATOR, "base_model_version": DEFECTIVE_MODEL,
            "trained_at": "2026-08-01T20:29:49+00:00", "artifact_sha256": _sha(cal_file), "file_path": str(cal_file),
        }), encoding="utf-8",
    )
    real = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)

    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_calibrator(DEFECTIVE_MODEL, models_dir=models_dir, registry=real) is None
        assert load_latest_tennis_calibrator(DEFECTIVE_MODEL, models_dir=models_dir) is None
    _assert_rejected(caplog, "INVALID")


def test_real_registry_enables_no_calibrator_today():
    """`config/model_registry.json` no declara ningún calibrador ALLOWED ni
    atado a un modelo base: hoy ninguno es cargable."""
    real = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)
    assert real.load_error is None
    assert real.allowed_calibrators_for_base(DEFECTIVE_MODEL) == []
    assert all(e.base_model_version is None and e.metadata_sha256 is None for e in real.entries.values())
    assert [e for e in real.entries.values() if e.status == RegistryStatus.ALLOWED] == []


def test_default_loader_against_real_models_dir_never_returns_the_defective_calibrator():
    assert load_latest_tennis_calibrator(DEFECTIVE_MODEL) is None


# --- TOCTOU: se verifica y se deserializa exactamente el mismo contenido ------------------


def _spy_joblib_load(monkeypatch):
    seen = []
    original = joblib.load

    def spy(source, *args, **kwargs):
        seen.append(source)
        return original(source, *args, **kwargs)

    monkeypatch.setattr(joblib, "load", spy)
    return seen


def test_calibrator_is_deserialized_from_the_verified_in_memory_bytes_never_from_a_path(world, monkeypatch):
    seen = _spy_joblib_load(monkeypatch)

    assert _load(world) is not None

    assert len(seen) == 1
    assert isinstance(seen[0], io.BytesIO)  # nunca una ruta: el archivo no se vuelve a abrir
    registered_sha = world.registry.entries[world.calibrator_version].artifact_sha256
    assert hashlib.sha256(seen[0].getvalue()).hexdigest() == registered_sha


def test_each_file_is_read_exactly_once_per_load(world, monkeypatch):
    reads = []
    original = calibrator_module.read_bytes_once

    def counting(path):
        reads.append(Path(path).name)
        return original(path)

    monkeypatch.setattr(calibrator_module, "read_bytes_once", counting)

    assert _load(world) is not None

    expected = sorted([
        world.base_meta.name, world.base_file.name, world.cal_meta.name, world.cal_file.name,
    ])
    assert sorted(reads) == expected  # cada archivo exactamente una vez


def test_swapping_files_after_they_are_read_cannot_change_what_is_loaded(world, monkeypatch):
    """Simula un atacante que reemplaza los archivos justo después de que se
    leen (ventana TOCTOU): se carga el contenido ya verificado, no el nuevo."""
    expected = _load(world).calibrate(0.7)
    garbage = b"swapped after verification"
    original = calibrator_module.read_bytes_once

    def read_then_swap(path):
        data = original(path)
        if Path(path).resolve() in (world.cal_file.resolve(), world.cal_meta.resolve()):
            Path(path).write_bytes(garbage)
        return data

    monkeypatch.setattr(calibrator_module, "read_bytes_once", read_then_swap)

    calibrator = _load(world)

    assert calibrator is not None
    assert calibrator.calibrate(0.7) == pytest.approx(expected)
    assert world.cal_file.read_bytes() == garbage  # el archivo en disco sí cambió
    assert world.cal_meta.read_bytes() == garbage


def test_base_model_loader_also_deserializes_the_verified_bytes_only(world, monkeypatch):
    seen = _spy_joblib_load(monkeypatch)

    loaded = load_latest_tennis_artifact(world.models_dir, registry=world.registry)

    assert loaded is not None
    assert len(seen) == 1 and isinstance(seen[0], io.BytesIO)
    assert hashlib.sha256(seen[0].getvalue()).hexdigest() == world.registry.entries[world.base_version].artifact_sha256


def test_base_model_loader_is_immune_to_a_swap_after_the_read(world, monkeypatch):
    import src.models.tennis_baseline as baseline_module

    original = baseline_module.read_bytes_once

    def read_then_swap(path):
        data = original(path)
        if Path(path).resolve() == world.base_file.resolve():
            Path(path).write_bytes(b"swapped")
        return data

    monkeypatch.setattr(baseline_module, "read_bytes_once", read_then_swap)

    loaded = load_latest_tennis_artifact(world.models_dir, registry=world.registry)

    assert loaded is not None  # se cargó el contenido verificado
    assert hasattr(loaded[0], "predict_proba")


# --- `metadata.file_path`: contrato previo preservado, validado con resolve_in_dir -------------


def _set_base_file_path(world: World, value) -> None:
    _edit_json(world.base_meta, file_path=value)


def _set_calibrator_file_path(world: World, value) -> ModelRegistryPolicy:
    return _rewrite_calibrator_meta(world, file_path=value)


def _unsafe_path_cases(world: World, tmp_path: Path, artifact: Path):
    """Valores de `file_path` inválidos; todos apuntan (o parecen apuntar) a bytes
    con el SHA correcto, de modo que SOLO la validación de ruta puede rechazarlos."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside = outside_dir / artifact.name
    shutil.copy(artifact, outside)
    link_out = world.models_dir / "link_out.joblib"
    link_out.symlink_to(outside)
    link_in = world.models_dir / "link_in.joblib"
    link_in.symlink_to(artifact)
    a_dir = world.models_dir / "adir.joblib"
    a_dir.mkdir()
    return {
        "absolute_outside_models_dir": str(outside),
        "traversal_absolute": f"{world.models_dir}/../models/{artifact.name}",
        "traversal_relative": f"../models/{artifact.name}",
        "traversal_in_subdir": f"sub/../{artifact.name}",
        "nul_byte": f"{artifact}\x00",
        "empty": "",
        "not_text": 123,
        "symlink_leaving_models_dir": str(link_out),
        "symlink_inside_models_dir": str(link_in),
        "directory_not_regular_file": str(a_dir),
        "nonexistent": str(world.models_dir / "nope.joblib"),
        "backslash_separator": f"sub\\{artifact.name}",
    }


UNSAFE_PATH_CASES = [
    "absolute_outside_models_dir", "traversal_absolute", "traversal_relative", "traversal_in_subdir", "nul_byte",
    "empty", "not_text", "symlink_leaving_models_dir", "symlink_inside_models_dir", "directory_not_regular_file",
    "nonexistent", "backslash_separator",
]


@pytest.mark.parametrize("case", UNSAFE_PATH_CASES)
def test_calibrator_loader_rejects_unsafe_calibrator_file_path(world, tmp_path, caplog, case):
    value = _unsafe_path_cases(world, tmp_path, world.cal_file)[case]
    registry = _set_calibrator_file_path(world, value)

    with caplog.at_level(logging.WARNING):
        assert _load(world, registry) is None
    # (un `file_path` vacío se rechaza antes como metadato incompleto: el motivo también nombra file_path)
    _assert_rejected(caplog, "file_path")


@pytest.mark.parametrize("case", UNSAFE_PATH_CASES)
def test_calibrator_loader_rejects_unsafe_base_model_file_path(world, tmp_path, caplog, case):
    _set_base_file_path(world, _unsafe_path_cases(world, tmp_path, world.base_file)[case])

    with caplog.at_level(logging.WARNING):
        assert _load(world) is None
    _assert_rejected(caplog, "file_path del modelo base")


@pytest.mark.parametrize("case", UNSAFE_PATH_CASES)
def test_base_model_loader_rejects_unsafe_file_path(world, tmp_path, caplog, case):
    _set_base_file_path(world, _unsafe_path_cases(world, tmp_path, world.base_file)[case])

    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_artifact(world.models_dir, registry=world.registry) is None
    _assert_rejected(caplog, "file_path")


def test_valid_non_canonical_file_name_inside_models_dir_is_accepted_for_calibrator_and_base(world):
    base_custom = world.models_dir / "renamed_base_model.joblib"
    world.base_file.rename(base_custom)
    _set_base_file_path(world, str(base_custom))
    cal_custom = world.models_dir / "renamed_calibrator.joblib"
    world.cal_file.rename(cal_custom)
    registry = _set_calibrator_file_path(world, str(cal_custom))

    assert _load(world, registry) is not None
    loaded = load_latest_tennis_artifact(world.models_dir, registry=registry)
    assert loaded is not None
    assert loaded[1].file_path == base_custom  # el artefacto conserva la file_path declarada


def test_bare_file_name_and_cwd_relative_paths_inside_models_dir_are_accepted(world, monkeypatch):
    custom = world.models_dir / "bare_name.joblib"
    world.cal_file.rename(custom)
    registry = _set_calibrator_file_path(world, "bare_name.joblib")  # solo el nombre
    assert _load(world, registry) is not None

    monkeypatch.chdir(world.models_dir.parent)
    registry = _set_calibrator_file_path(world, "models/bare_name.joblib")  # relativa al cwd, dentro de models_dir
    assert load_latest_tennis_calibrator(world.base_version, models_dir=Path("models"), registry=registry) is not None


def test_real_current_metadata_file_paths_remain_valid_for_real_artifacts():
    """Compatibilidad con las `file_path` REALES actuales (absolutas, escritas por
    el entrenamiento): resuelven al archivo real dentro de `data/models/`."""
    from config.settings import DATA_MODELS_DIR
    from src.models.model_registry_policy import resolve_declared_path

    metas = sorted(DATA_MODELS_DIR.glob("tennis_*.metadata.json"))
    if not metas:
        pytest.skip("sin artefactos reales en data/models de este checkout")
    for meta in metas:
        declared = json.loads(meta.read_text(encoding="utf-8"))["file_path"]
        assert resolve_declared_path(DATA_MODELS_DIR, declared) == DATA_MODELS_DIR.resolve() / Path(declared).name
        assert Path(declared).is_absolute()


def test_real_defective_model_file_path_resolves_and_its_registered_sha_still_matches():
    """Con la `file_path` real del modelo defectuoso: la ruta es válida y el SHA-256 de
    sus bytes coincide con el registro (conservado para auditoría); sigue INVALID."""
    from config.settings import DATA_MODELS_DIR
    from src.models.model_registry_policy import resolve_declared_path, sha256_hex

    meta = DATA_MODELS_DIR / f"{DEFECTIVE_MODEL}.metadata.json"
    if not meta.exists():
        pytest.skip("modelo defectuoso no presente en este checkout")
    path = resolve_declared_path(DATA_MODELS_DIR, json.loads(meta.read_text(encoding="utf-8"))["file_path"])
    real = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)

    assert path is not None
    assert sha256_hex(path.read_bytes()) == real.entries[DEFECTIVE_MODEL].artifact_sha256
    assert real.check(DEFECTIVE_MODEL, sha256_hex(path.read_bytes()))[0] is False  # INVALID: no activable


def test_file_replaced_after_the_read_is_not_what_gets_deserialized_via_declared_file_path(world, monkeypatch):
    custom = world.models_dir / "custom_calibrator.joblib"
    world.cal_file.rename(custom)
    registry = _set_calibrator_file_path(world, str(custom))
    expected = _load(world, registry).calibrate(0.7)
    seen = _spy_joblib_load(monkeypatch)
    original = calibrator_module.read_bytes_once

    def read_then_swap(path):
        data = original(path)
        if Path(path).resolve() == custom.resolve():
            Path(path).write_bytes(b"swapped after verification")
        return data

    monkeypatch.setattr(calibrator_module, "read_bytes_once", read_then_swap)

    calibrator = _load(world, registry)

    assert calibrator is not None and calibrator.calibrate(0.7) == pytest.approx(expected)
    assert isinstance(seen[-1], io.BytesIO)
    assert hashlib.sha256(seen[-1].getvalue()).hexdigest() == registry.entries[world.calibrator_version].artifact_sha256
    assert custom.read_bytes() == b"swapped after verification"


# --- integración con la ruta de run_e2e (SportAdapter -> decision_pipeline) -------------


def test_production_adapter_has_no_calibrator_wired_today():
    """Estado de producción hoy: `SPORT_ADAPTERS[TENNIS]` no cablea calibrador;
    este PR no lo activa (no cambia el comportamiento ni los umbrales)."""
    assert SPORT_ADAPTERS[Sport.TENNIS].load_calibrator_fn is None


def _run_e2e_style_adapter(world: World, artifact_registry: ModelRegistryPolicy, calibrator_registry: ModelRegistryPolicy):
    """El `SportAdapter` REAL de tenis de `scripts/run_e2e.py`, con el
    calibrador cableado como lo haría producción
    (`load_latest_tennis_calibrator`, invocado con `model_version` como único
    argumento) y los directorios/registro redirigidos a tmp."""
    base = SPORT_ADAPTERS[Sport.TENNIS]
    return dataclasses.replace(
        base,
        load_artifact_fn=functools.partial(load_latest_tennis_artifact, world.models_dir, artifact_registry),
        load_calibrator_fn=functools.partial(
            load_latest_tennis_calibrator, models_dir=world.models_dir, registry=calibrator_registry
        ),
    )


def _calibration_for(adapter):
    now = datetime.now(timezone.utc)
    record = make_tennis_record("espn_tennis_atp_e2e", start_time=now + timedelta(hours=3), status=EventStatus.SCHEDULED)
    loaded = adapter.load_artifact_fn()
    assert loaded is not None  # el modelo base SÍ está permitido en estos casos
    ctx = _build_record_context(record, TennisFeatureInputs(), now, adapter, loaded, now)
    assert ctx.model_output.p_model_yes is not None
    return ctx.calibration_output


def test_e2e_path_applies_calibration_only_for_the_valid_registered_pair(world):
    out = _calibration_for(_run_e2e_style_adapter(world, world.registry, world.registry))

    assert out.p_model_calibrated is not None
    assert out.calibration_version is not None
    assert out.p_model_raw is not None


@pytest.mark.parametrize(
    "case",
    [
        "calibrator_unregistered", "calibrator_invalid", "calibrator_wrong_sha", "calibrator_file_altered",
        "calibrator_metadata_altered", "calibrator_metadata_sha_missing", "calibrator_base_binding_wrong",
        "base_invalid_in_calibrator_registry",
    ],
)
def test_e2e_path_never_applies_calibration_on_any_failure(world, case):
    cal, base = world.calibrator_version, world.base_version
    calibrator_registry = world.registry
    if case == "calibrator_unregistered":
        calibrator_registry = _replace_entry(world, cal, _delete=True)
    elif case == "calibrator_invalid":
        calibrator_registry = _replace_entry(world, cal, status=RegistryStatus.INVALID)
    elif case == "calibrator_wrong_sha":
        calibrator_registry = _replace_entry(world, cal, artifact_sha256="0" * 64)
    elif case == "calibrator_file_altered":
        world.cal_file.write_bytes(world.cal_file.read_bytes() + b"tampered")
    elif case == "calibrator_metadata_altered":
        _edit_json(world.cal_meta, n_calibration_samples=1)
    elif case == "calibrator_metadata_sha_missing":
        calibrator_registry = _replace_entry(world, cal, metadata_sha256=None)
    elif case == "calibrator_base_binding_wrong":
        calibrator_registry = _replace_entry(world, cal, base_model_version="tennis_baseline_logreg_v1_other")
    elif case == "base_invalid_in_calibrator_registry":
        calibrator_registry = _replace_entry(world, base, status=RegistryStatus.INVALID)

    out = _calibration_for(_run_e2e_style_adapter(world, world.registry, calibrator_registry))

    assert out.p_model_calibrated is None
    assert out.calibration_version is None
    assert out.calibration_method is None
    assert out.calibrated_at is None
    assert out.p_model_raw is not None  # la probabilidad cruda se conserva intacta


def test_e2e_path_with_default_loader_and_real_registry_never_calibrates(world):
    """Cableado idéntico a producción (función sin redirigir: models_dir real y
    registro real): el calibrador defectuoso `INVALID` jamás se aplica."""
    adapter = dataclasses.replace(SPORT_ADAPTERS[Sport.TENNIS], load_calibrator_fn=load_latest_tennis_calibrator)

    assert adapter.load_calibrator_fn(DEFECTIVE_MODEL) is None
    assert adapter.load_calibrator_fn(world.base_version) is None  # un par fuera del registro real tampoco
