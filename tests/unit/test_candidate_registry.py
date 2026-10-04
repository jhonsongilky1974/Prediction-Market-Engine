"""Registro candidato aislado (`candidate_models`): no puede saltarse el guardián fail-closed ni
promover artefactos. Todo en `tmp_path` con un modelo base sintético; el registro real no se toca."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from src.calibration.tennis_calibrator_training import load_latest_tennis_calibrator
from src.evaluation.calibration_governance import GovernanceError
from src.evaluation.candidate_registry import (
    CANDIDATE_REGISTRY_KEY,
    CANDIDATE_STATUS,
    CandidateRegistryError,
    load_candidate_registry,
)
from src.models.model_registry_policy import (
    DEFAULT_MODEL_REGISTRY_PATH,
    RegistryStatus,
    load_model_registry,
    sha256_hex,
)
from src.models.tennis_baseline import load_latest_tennis_artifact
from tests.unit.calibration_governance_factories import (
    TrainedWorld,
    build_trained_world,
    candidate_document,
    candidate_policy,
    train_and_record_calibrator,
    write_candidate_file,
)

REAL_REGISTRY_SHA = hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path) -> TrainedWorld:
    return build_trained_world(tmp_path)


def load(world: TrainedWorld, path: Path = None, **overrides):
    kwargs = dict(models_dir=world.models_dir, ledger_path=world.ledger, allowed_dir=world.candidate_path.parent)
    kwargs.update(overrides)
    return load_candidate_registry(path or world.candidate_path, **kwargs)


def rewrite(world: TrainedWorld, mutate) -> None:
    document = json.loads(world.candidate_path.read_text(encoding="utf-8"))
    mutate(document)
    world.candidate_path.write_text(json.dumps(document), encoding="utf-8")


# --- caso positivo ---------------------------------------------------------------------------------


def test_valid_candidate_file_yields_an_in_memory_policy_for_exactly_one_base_model(world):
    policy = load(world)

    assert list(policy.entries) == [world.base.model_version]
    entry = policy.entries[world.base.model_version]
    assert entry.status == RegistryStatus.ALLOWED  # solo en memoria; el archivo dice CANDIDATE_EVALUATION
    assert policy.check_bytes(world.base.model_version, world.base.file_path.read_bytes())[0] is True
    assert policy.allowed_calibrators_for_base(world.base.model_version) == []  # nunca incluye calibradores
    assert json.loads(world.candidate_path.read_text())[CANDIDATE_REGISTRY_KEY][0]["status"] == CANDIDATE_STATUS


# --- aislamiento: no permite saltarse el guardián ni promover ---------------------------------------------


def test_a_production_loader_rejects_the_candidate_file_everything_fails_closed(world):
    production_view = load_model_registry(world.candidate_path)  # si se copiara a config/
    assert production_view.load_error is not None
    assert production_view.entries == {}
    assert production_view.check(world.base.model_version, sha256_hex(world.base.file_path.read_bytes()))[0] is False


def test_the_candidate_policy_cannot_load_any_calibrator(world, caplog):
    train_and_record_calibrator(world)
    policy = candidate_policy(world)
    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_calibrator(world.base.model_version, models_dir=world.models_dir, registry=policy) is None
    assert any("ningún calibrador ALLOWED atado" in r.getMessage() for r in caplog.records)


def test_candidate_artifacts_remain_unpromoted_for_production(world):
    candidate_policy(world)
    train_and_record_calibrator(world)
    # la producción (registro real, sin registry=) sigue sin ver ningún modelo ni calibrador de este directorio
    assert load_latest_tennis_artifact(world.models_dir) is None
    assert load_latest_tennis_calibrator(world.base.model_version, models_dir=world.models_dir) is None
    assert hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest() == REAL_REGISTRY_SHA  # registro real intacto


def test_real_registry_has_no_allowed_entry_before_and_after():
    real = load_model_registry()
    assert [v for v, e in real.entries.items() if e.status == RegistryStatus.ALLOWED] == []
    assert hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest() == REAL_REGISTRY_SHA


# --- ubicación y forma del archivo --------------------------------------------------------------------------


def test_production_registry_path_and_config_paths_are_rejected(world, tmp_path):
    with pytest.raises(CandidateRegistryError, match="producción"):
        load(world, DEFAULT_MODEL_REGISTRY_PATH, allowed_dir=DEFAULT_MODEL_REGISTRY_PATH.parent)
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    inside = fake_config / "candidate.json"
    inside.write_text(world.candidate_path.read_text())
    with pytest.raises(CandidateRegistryError, match="config/"):
        load(world, inside, allowed_dir=fake_config, config_dir=fake_config)


def test_file_outside_the_candidates_directory_symlinks_and_missing_files_are_rejected(world, tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(world.candidate_path.read_text())
    with pytest.raises(CandidateRegistryError, match="directamente en"):
        load(world, elsewhere)
    link = world.candidate_path.parent / "link.json"
    link.symlink_to(world.candidate_path)
    with pytest.raises(CandidateRegistryError, match="symlink"):
        load(world, link)
    with pytest.raises(CandidateRegistryError, match="ausente"):
        load(world, world.candidate_path.parent / "nope.json")


def test_default_candidates_directory_is_the_governance_one_so_a_tmp_file_is_rejected():
    from src.evaluation.candidate_registry import DEFAULT_CANDIDATES_DIR

    assert DEFAULT_CANDIDATES_DIR.parts[-3:] == ("governance", "calibration", "candidates")


@pytest.mark.parametrize("content", ["{not json", "[]", "5", ""])
def test_malformed_json_is_rejected(world, content):
    world.candidate_path.write_text(content, encoding="utf-8")
    with pytest.raises(CandidateRegistryError):
        load(world)


def _drop(key):
    return lambda d: d.pop(key)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d.update(models=d.pop(CANDIDATE_REGISTRY_KEY)), "models"),               # clave reservada a producción
        (lambda d: d.update(models=[]), "models"),                                           # ambas claves
        (_drop(CANDIDATE_REGISTRY_KEY), "claves de nivel superior"),
        (lambda d: d.update(extra=1), "claves de nivel superior"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(purpose="production"), "purpose"),
        (_drop("prereg_id"), "prereg_id"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY].append(dict(d[CANDIDATE_REGISTRY_KEY][0])), "exactamente UN"),
        (lambda d: d.update({CANDIDATE_REGISTRY_KEY: []}), "exactamente UN"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY][0].update(status="ALLOWED"), "status"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY][0].update(model_version="tennis_calibrator_platt_v1_x"), "modelo base de tenis"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY][0].update(extra=1), "campos desconocidos"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY][0].pop("artifact_sha256"), "obligatorios"),
        (lambda d: d[CANDIDATE_REGISTRY_KEY][0].update(metadata_sha256="zz"), "obligatorios"),
    ],
)
def test_schema_violations_are_rejected(world, mutation, match):
    rewrite(world, mutation)
    with pytest.raises(CandidateRegistryError, match=match):
        load(world)


# --- hashes y libro ------------------------------------------------------------------------------------------


def test_artifact_hash_mismatch_with_the_file_declared_in_the_registry_is_rejected(world):
    rewrite(world, lambda d: d[CANDIDATE_REGISTRY_KEY][0].update(artifact_sha256="0" * 64))
    with pytest.raises(CandidateRegistryError):  # tampoco coincide con BASE_TRAINED
        load(world)


def test_altered_artifact_or_metadata_after_the_ledger_was_written_is_rejected(world):
    world.base.file_path.write_bytes(world.base.file_path.read_bytes() + b"x")
    with pytest.raises(CandidateRegistryError, match="SHA-256 del modelo base"):
        load(world)


def test_altered_metadata_is_rejected(world):
    meta = world.models_dir / f"{world.base.model_version}.metadata.json"
    meta.write_text(meta.read_text() + " ")
    with pytest.raises(CandidateRegistryError, match="metadato"):
        load(world)


def test_missing_metadata_is_rejected(world):
    (world.models_dir / f"{world.base.model_version}.metadata.json").unlink()
    with pytest.raises(CandidateRegistryError, match="metadato"):
        load(world)


def test_registry_that_disagrees_with_the_ledger_is_rejected(world):
    rewrite(world, lambda d: d.update(attempt_id="attempt_999"))
    with pytest.raises(CandidateRegistryError, match="libro"):
        load(world)
    rewrite(world, lambda d: d.update(attempt_id="attempt_001", snapshot_id="snap_otro"))
    with pytest.raises(CandidateRegistryError, match="libro"):
        load(world)


def test_missing_empty_or_tampered_ledger_is_rejected(world, tmp_path):
    with pytest.raises(CandidateRegistryError, match="libro"):
        load(world, ledger_path=tmp_path / "no_existe.jsonl")  # libro vacío: sin BASE_TRAINED
    lines = world.ledger.read_text().splitlines()
    lines[0] = lines[0].replace("Jhonson Gil", "Alguien Más")
    world.ledger.write_text("\n".join(lines) + "\n")
    with pytest.raises(CandidateRegistryError, match="libro"):
        load(world)


def test_a_rejected_candidate_base_cannot_be_calibrated_through_the_candidate_policy(world):
    meta_path = world.models_dir / f"{world.base.model_version}.metadata.json"
    data = json.loads(meta_path.read_text())
    data["candidate_status"] = "REJECTED_CANDIDATE"
    meta_path.write_text(json.dumps(data))
    # el metadato cambió: el candidato (y el libro) quedan inconsistentes y se rechaza antes de cargar nada
    with pytest.raises(GovernanceError):
        candidate_policy(world)
