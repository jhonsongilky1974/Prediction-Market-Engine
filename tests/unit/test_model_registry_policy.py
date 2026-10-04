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
    read_bytes_once,
    resolve_declared_path,
    resolve_in_dir,
    sha256_hex,
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


# --- helpers genéricos públicos y esquema de calibradores (CONTINUITY.md §0.38) ---


def test_sha256_hex_matches_hashlib_and_read_bytes_once_returns_none_when_unreadable(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"payload")
    assert sha256_hex(b"payload") == hashlib.sha256(b"payload").hexdigest()
    assert read_bytes_once(f) == b"payload"
    assert read_bytes_once(tmp_path / "missing.bin") is None
    assert read_bytes_once(tmp_path) is None  # un directorio no es legible como archivo


def test_check_bytes_hashes_the_given_payload_and_rejects_missing_or_different_bytes():
    policy = ModelRegistryPolicy(entries={"m": _allowed("m", sha256_hex(b"good"))})
    assert policy.check_bytes("m", b"good")[0] is True
    assert policy.check_bytes("m", b"other")[0] is False
    ok, reason = policy.check_bytes("m", None)
    assert ok is False and "SHA-256" in reason


@pytest.mark.parametrize("name", ["", ".", "..", "../x", "a/b", "a\\b", "x\x00y", "/etc/passwd", "sub/../x.joblib"])
def test_resolve_in_dir_rejects_unsafe_names(tmp_path, name):
    assert resolve_in_dir(tmp_path, name) is None


def test_resolve_in_dir_accepts_plain_file_names_and_rejects_symlinks_escaping_the_directory(tmp_path):
    assert resolve_in_dir(tmp_path, "model.joblib") == tmp_path.resolve() / "model.joblib"
    outside = tmp_path.parent / "outside.joblib"
    outside.write_bytes(b"x")
    (tmp_path / "link.joblib").symlink_to(outside)
    assert resolve_in_dir(tmp_path, "link.joblib") is None


def test_allowed_calibrators_for_base_returns_only_allowed_entries_bound_to_that_base():
    def cal(version, status, base):
        return RegistryEntry(version, status, "t", "s", base_model_version=base, metadata_sha256="m")

    policy = ModelRegistryPolicy(entries={
        "c_ok": cal("c_ok", RegistryStatus.ALLOWED, "base"),
        "c_invalid": cal("c_invalid", RegistryStatus.INVALID, "base"),
        "c_other": cal("c_other", RegistryStatus.ALLOWED, "other"),
        "c_unbound": cal("c_unbound", RegistryStatus.ALLOWED, None),
    })
    assert [e.model_version for e in policy.allowed_calibrators_for_base("base")] == ["c_ok"]


def test_registry_file_parses_calibrator_binding_and_metadata_hash(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"models": [{
        "model_version": "tennis_calibrator_platt_v1_x", "status": "ALLOWED", "artifact_sha256": "a",
        "base_model_version": "tennis_baseline_logreg_v1_y", "metadata_sha256": "b",
    }, {"model_version": "tennis_baseline_logreg_v1_y", "status": "ALLOWED", "artifact_sha256": "c"}]}), encoding="utf-8")

    policy = load_model_registry(path)

    assert policy.load_error is None
    entry = policy.entries["tennis_calibrator_platt_v1_x"]
    assert (entry.base_model_version, entry.metadata_sha256) == ("tennis_baseline_logreg_v1_y", "b")
    assert policy.entries["tennis_baseline_logreg_v1_y"].base_model_version is None  # campos opcionales


def test_resolve_in_dir_require_regular_file_and_rejects_every_symlink(tmp_path):
    (tmp_path / "real.joblib").write_bytes(b"x")
    (tmp_path / "adir.joblib").mkdir()
    (tmp_path / "link.joblib").symlink_to(tmp_path / "real.joblib")  # symlink interno hacia un archivo interno

    assert resolve_in_dir(tmp_path, "real.joblib", require_regular_file=True) == tmp_path.resolve() / "real.joblib"
    assert resolve_in_dir(tmp_path, "missing.joblib") == tmp_path.resolve() / "missing.joblib"  # sin exigir existencia
    assert resolve_in_dir(tmp_path, "missing.joblib", require_regular_file=True) is None
    assert resolve_in_dir(tmp_path, "adir.joblib", require_regular_file=True) is None
    assert resolve_in_dir(tmp_path, "link.joblib") is None
    assert resolve_in_dir(tmp_path, 7) is None  # type: ignore[arg-type]


def test_resolve_declared_path_accepts_absolute_bare_and_relative_forms_inside_the_directory(tmp_path, monkeypatch):
    (tmp_path / "m.joblib").write_bytes(b"x")
    expected = tmp_path.resolve() / "m.joblib"

    assert resolve_declared_path(tmp_path, str(tmp_path / "m.joblib")) == expected  # absoluta (formato real)
    assert resolve_declared_path(tmp_path, "m.joblib") == expected  # solo el nombre
    monkeypatch.chdir(tmp_path.parent)
    assert resolve_declared_path(Path(tmp_path.name), f"{tmp_path.name}/m.joblib") == expected  # relativa al cwd


@pytest.mark.parametrize("declared", ["", None, 5, "x\x00.joblib", "../m.joblib", "sub/../m.joblib", "/etc/passwd", "other/m.joblib"])
def test_resolve_declared_path_rejects_unsafe_values(tmp_path, declared):
    (tmp_path / "m.joblib").write_bytes(b"x")
    assert resolve_declared_path(tmp_path, declared) is None


def test_resolve_declared_path_rejects_files_outside_symlinks_and_other_directories(tmp_path):
    inside = tmp_path / "models"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "m.joblib").write_bytes(b"x")
    (inside / "link.joblib").symlink_to(outside / "m.joblib")

    assert resolve_declared_path(inside, str(outside / "m.joblib")) is None
    assert resolve_declared_path(inside, str(inside / "link.joblib")) is None
