"""Contención FAIL-CLOSED del modelo de tenis con fuga temporal (CONTINUITY.md
§0.38): lista explícita de modelos permitidos, SHA-256 verificado."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pytest

from src.models.model_registry_policy import (
    DEFAULT_MODEL_REGISTRY_PATH,
    ModelRegistryPolicy,
    RegistryEntry,
    RegistryStatus,
    load_model_registry,
)
from src.models.tennis_baseline import load_latest_tennis_artifact

DEFECTIVE_MODEL = "tennis_baseline_logreg_v1_20260801T184245Z"
DEFECTIVE_CALIBRATOR = "tennis_calibrator_platt_v1_20260801T202949Z"


def _write_tennis_artifact(models_dir: Path, model_version: str, trained_at: datetime, **extra) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib_path = models_dir / f"{model_version}.joblib"
    joblib.dump({"fake": model_version}, joblib_path)
    meta = {
        "model_version": model_version,
        "sport": "TENNIS",
        "algorithm": "logistic_regression_v1",
        "trained_at": trained_at.isoformat(),
        "feature_set_version": "v1",
        "n_training_samples": 1,
        "feature_columns": ["rest_days.participant_a"],
        "round_categories": [],
        "file_path": str(joblib_path),
        **extra,
    }
    (models_dir / f"{model_version}.metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return joblib_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _allowed(model_version: str, sha: str) -> RegistryEntry:
    return RegistryEntry(model_version, RegistryStatus.ALLOWED, "test", sha)


# --- política ---------------------------------------------------------


def test_policy_allows_only_allowed_entry_with_matching_sha():
    policy = ModelRegistryPolicy(entries={"m": _allowed("m", "abc")})
    assert policy.check("m", "abc") == (True, "ALLOWED y SHA-256 verificado")


@pytest.mark.parametrize("actual_sha", [None, "different"])
def test_policy_rejects_allowed_entry_when_sha_missing_or_different(actual_sha):
    policy = ModelRegistryPolicy(entries={"m": _allowed("m", "abc")})
    ok, reason = policy.check("m", actual_sha)
    assert ok is False
    assert "SHA-256" in reason


def test_policy_rejects_allowed_entry_without_registered_sha():
    policy = ModelRegistryPolicy(entries={"m": RegistryEntry("m", RegistryStatus.ALLOWED, "x", None)})
    assert policy.check("m", "abc")[0] is False


def test_policy_rejects_unknown_model():
    ok, reason = ModelRegistryPolicy().check("never_listed", "abc")
    assert ok is False
    assert "no figura" in reason


@pytest.mark.parametrize("status", [RegistryStatus.INVALID, RegistryStatus.REJECTED_CANDIDATE])
def test_policy_rejects_non_allowed_status_even_with_matching_sha(status):
    policy = ModelRegistryPolicy(entries={"m": RegistryEntry("m", status, "motivo", "abc")})
    ok, reason = policy.check("m", "abc")
    assert ok is False
    assert status.value in reason


# --- carga del registro (fail-closed ante cualquier fallo) -----------------


@pytest.mark.parametrize(
    "content",
    [None, "{not json", "[]", '{"models": [{"model_version": "m", "status": "WHATEVER"}]}',
     '{"models": [{"model_version": "m", "status": "ALLOWED"}, {"model_version": "m", "status": "INVALID"}]}'],
)
def test_load_registry_never_raises_and_rejects_everything_on_bad_file(tmp_path, content):
    path = tmp_path / "registry.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    policy = load_model_registry(path)

    assert policy.load_error is not None
    assert policy.check("m", "abc")[0] is False


# --- registro REAL del repositorio ----------------------------------------------


def test_real_registry_marks_defective_tennis_model_and_calibrator_invalid():
    policy = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)

    assert policy.load_error is None
    for version in (DEFECTIVE_MODEL, DEFECTIVE_CALIBRATOR):
        entry = policy.entries[version]
        assert entry.status == RegistryStatus.INVALID
        assert entry.reason  # motivo de auditoría documentado
        ok, _ = policy.check(version, entry.artifact_sha256)
        assert ok is False  # ni con el SHA correcto


def test_real_registry_has_no_allowed_model_today():
    policy = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)
    assert [e for e in policy.entries.values() if e.status == RegistryStatus.ALLOWED] == []


def test_real_registry_sha_of_defective_model_matches_file_when_present_for_audit():
    """Si el artefacto defectuoso sigue en data/models (conservado para
    auditoría), el SHA documentado en el registro debe coincidir con el real."""
    path = Path(__file__).resolve().parents[2] / "data" / "models" / f"{DEFECTIVE_MODEL}.joblib"
    if not path.exists():
        pytest.skip("artefacto defectuoso no presente en este checkout (data/ no versionado)")
    assert load_model_registry().entries[DEFECTIVE_MODEL].artifact_sha256 == _sha(path)


# --- el cargador: el modelo defectuoso NO puede activarse ----------------------


def test_defective_model_cannot_be_activated_even_if_file_is_present(tmp_path, caplog):
    """Un artefacto con el nombre EXACTO del modelo defectuoso, con
    metadata válida y el registro REAL del repo: el cargador lo rechaza."""
    models_dir = tmp_path / "models"
    joblib_path = _write_tennis_artifact(models_dir, DEFECTIVE_MODEL, datetime(2026, 8, 1, tzinfo=timezone.utc))
    registry = load_model_registry(DEFAULT_MODEL_REGISTRY_PATH)

    with caplog.at_level(logging.WARNING):
        assert load_latest_tennis_artifact(models_dir, registry=registry) is None
        assert load_latest_tennis_artifact(models_dir) is None  # registro por defecto (el real)

    assert joblib_path.exists()  # no se mueve ni se borra
    assert any(DEFECTIVE_MODEL in r.message and "RECHAZADO" in r.message for r in caplog.records)


def test_defective_model_stays_rejected_even_if_registry_listed_it_allowed_with_wrong_sha(tmp_path):
    models_dir = tmp_path / "models"
    _write_tennis_artifact(models_dir, DEFECTIVE_MODEL, datetime(2026, 8, 1, tzinfo=timezone.utc))
    forged = ModelRegistryPolicy(entries={DEFECTIVE_MODEL: _allowed(DEFECTIVE_MODEL, "0" * 64)})

    assert load_latest_tennis_artifact(models_dir, registry=forged) is None


def test_default_loader_on_real_models_dir_never_returns_the_defective_model():
    """Contra el directorio real de modelos (si existe): nunca devuelve el
    modelo defectuoso -- hoy no hay ningún modelo ALLOWED, así que `None`."""
    loaded = load_latest_tennis_artifact()
    assert loaded is None or loaded[1].model_version != DEFECTIVE_MODEL


def test_loader_unknown_model_is_rejected_and_listed_one_is_loaded(tmp_path):
    models_dir = tmp_path / "models"
    t = datetime(2026, 9, 1, tzinfo=timezone.utc)
    _write_tennis_artifact(models_dir, "tennis_baseline_logreg_v1_unknown", t + timedelta(days=5))  # más reciente, no listado
    good = _write_tennis_artifact(models_dir, "tennis_baseline_logreg_v1_good", t)
    registry = ModelRegistryPolicy(entries={"tennis_baseline_logreg_v1_good": _allowed("tennis_baseline_logreg_v1_good", _sha(good))})

    loaded = load_latest_tennis_artifact(models_dir, registry=registry)

    assert loaded is not None
    assert loaded[1].model_version == "tennis_baseline_logreg_v1_good"


def test_loader_rejects_tampered_artifact_file(tmp_path):
    models_dir = tmp_path / "models"
    path = _write_tennis_artifact(models_dir, "tennis_baseline_logreg_v1_x", datetime(2026, 9, 1, tzinfo=timezone.utc))
    registry = ModelRegistryPolicy(entries={"tennis_baseline_logreg_v1_x": _allowed("tennis_baseline_logreg_v1_x", _sha(path))})
    assert load_latest_tennis_artifact(models_dir, registry=registry) is not None

    joblib.dump({"tampered": True}, path)  # el archivo cambia después de registrarse

    assert load_latest_tennis_artifact(models_dir, registry=registry) is None


def test_loader_fails_closed_when_registry_is_corrupt(tmp_path):
    models_dir = tmp_path / "models"
    _write_tennis_artifact(models_dir, "tennis_baseline_logreg_v1_x", datetime(2026, 9, 1, tzinfo=timezone.utc))
    bad = tmp_path / "registry.json"
    bad.write_text("{corrupt", encoding="utf-8")

    assert load_latest_tennis_artifact(models_dir, registry=load_model_registry(bad)) is None


def test_loader_rejects_allowed_model_flagged_rejected_candidate_in_metadata(tmp_path):
    models_dir = tmp_path / "models"
    path = _write_tennis_artifact(
        models_dir, "tennis_baseline_logreg_v1_r", datetime(2026, 9, 1, tzinfo=timezone.utc),
        candidate_status="REJECTED_CANDIDATE",
    )
    registry = ModelRegistryPolicy(entries={"tennis_baseline_logreg_v1_r": _allowed("tennis_baseline_logreg_v1_r", _sha(path))})

    assert load_latest_tennis_artifact(models_dir, registry=registry) is None


def test_loader_tolerates_unreadable_metadata_without_raising(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "tennis_baseline_broken.metadata.json").write_text("{nope", encoding="utf-8")

    assert load_latest_tennis_artifact(models_dir, registry=ModelRegistryPolicy()) is None


def test_production_adapter_uses_the_fail_closed_loader():
    """El cableado de producción (hourly job y /analyze) usa el mismo
    cargador protegido -- sin un ALLOWED en el registro, no hay modelo."""
    from scripts.run_e2e import SPORT_ADAPTERS
    from src.models.schemas import Sport

    assert SPORT_ADAPTERS[Sport.TENNIS].load_artifact_fn is load_latest_tennis_artifact
