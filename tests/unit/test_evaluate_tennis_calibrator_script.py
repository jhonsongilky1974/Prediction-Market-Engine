"""`scripts/evaluate_tennis_calibrator.py` de punta a punta en `tmp_path`: base de datos sintética congelada,
artefactos FALSOS (bytes que no son un pickle; el script no deserializa nada), libro append-only y un repositorio
git temporal con `main` (el ancla). No evalúa ningún candidato real, no produce artefactos fuera de tmp y no
toca `config/model_registry.json`. Las regresiones F1–F9 viven en `test_calibration_governance_regressions.py`."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.evaluate_tennis_calibrator as script
from src.evaluation.calibration_governance import entries_of, read_ledger
from src.evaluation.calibration_verdict import SplitMetrics, Verdict, evaluate_validation
from src.models.model_registry_policy import DEFAULT_MODEL_REGISTRY_PATH, sha256_hex
from tests.unit.calibration_governance_factories import DbAttempt, build_db_attempt, git, git_accept, git_init, make_repo

REAL_REGISTRY_SHA = hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest()
EVALUATED_AT = "2026-06-04T00:00:00+00:00"


def evaluate(w: DbAttempt, **overrides) -> int:
    kwargs = dict(
        ledger=w.ledger, attempt_id="attempt_001", db_copy=w.db_copy, models_dir=w.models_dir,
        recorded_at=EVALUATED_AT, repo_root=w.root, base_ref="main",
    )
    kwargs.update(overrides)
    return script.run_evaluate(**kwargs)


def types(w: DbAttempt):
    return [e["type"] for e in read_ledger(w.ledger)]


# --- veredicto sobre las métricas de validación aceptadas en main ---------------------------------------------------


def test_rejected_candidate_is_finalized_without_reading_the_test(tmp_path):
    w = build_db_attempt(tmp_path)  # por defecto: el calibrador deteriora
    code = evaluate(w)
    assert code == 0
    assert types(w)[-2:] == ["PHASE1_VERDICT", "FINAL_VERDICT"] and "TEST_READ" not in types(w)
    final = entries_of(read_ledger(w.ledger), "FINAL_VERDICT")[0]["payload"]
    cal = w.calibrator
    expected = evaluate_validation(
        SplitMetrics(cal["raw_ece"], cal["calibrated_ece_oof"], cal["raw_brier"], cal["calibrated_brier_oof"], cal["n_calibration_events"])
    )
    assert final["verdict"] == expected.verdict.value == Verdict.RECHAZADO.value


def test_inconclusive_candidate_is_finalized_without_reading_the_test(tmp_path):
    w = build_db_attempt(tmp_path, raw_ece=0.08, calibrated_ece=0.08, raw_brier=0.20, calibrated_brier=0.20)
    assert evaluate(w) == 0
    assert entries_of(read_ledger(w.ledger), "FINAL_VERDICT")[0]["payload"]["verdict"] == "INCONCLUSO"
    assert "TEST_READ" not in types(w)


def test_preliminary_eligible_candidate_stops_with_an_explicit_error_and_writes_nothing(tmp_path, capsys):
    w = build_db_attempt(tmp_path, raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19)
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2
    assert w.ledger.read_bytes() == before
    assert "deserializar" in capsys.readouterr().err


def test_a_second_evaluation_of_the_same_attempt_is_refused_and_writes_nothing(tmp_path):
    w = build_db_attempt(tmp_path)
    assert evaluate(w) == 0
    # el nuevo estado del libro (con su veredicto) aún NO está en main: se acepta y se reintenta
    git_accept(w.root, "veredicto por PR")
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2
    assert w.ledger.read_bytes() == before


# --- verificaciones previas: fallan cerrado SIN escribir en el libro ----------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    ["db_copy_modified", "base_artifact_altered", "calibrator_artifact_altered", "calibrator_metadata_altered",
     "wrong_db_path", "missing_sidecar", "models_dir_none", "ledger_truncated", "ledger_tampered"],
)
def test_preflight_inconsistencies_exit_2_without_touching_the_ledger(tmp_path, scenario):
    w = build_db_attempt(tmp_path)
    kwargs = {}
    cal_version = w.calibrator["calibrator_version"]
    if scenario == "db_copy_modified":
        w.db_copy.write_bytes(w.db_copy.read_bytes() + b"\0")
    elif scenario == "base_artifact_altered":
        w.base["artifact_path"].write_bytes(b"otro contenido")
    elif scenario == "calibrator_artifact_altered":
        path = w.models_dir / f"{cal_version}.joblib"
        path.write_bytes(path.read_bytes() + b"x")
    elif scenario == "calibrator_metadata_altered":
        path = w.models_dir / f"{cal_version}.metadata.json"
        path.write_text(path.read_text() + " ")
    elif scenario == "wrong_db_path":
        kwargs["db_copy"] = tmp_path / "otra_base.db"
        kwargs["db_copy"].write_bytes(b"no es la base")
    elif scenario == "missing_sidecar":
        w.base["metadata_path"].unlink()
    elif scenario == "models_dir_none":
        kwargs["models_dir"] = None
    elif scenario == "ledger_truncated":
        w.ledger.write_text("\n".join(w.ledger.read_text().splitlines()[:-1]) + "\n")
    elif scenario == "ledger_tampered":
        w.ledger.write_text(w.ledger.read_text().replace("Jhonson Gil", "Otra Persona", 1))
    before = w.ledger.read_bytes()

    assert evaluate(w, **kwargs) == 2
    assert w.ledger.read_bytes() == before
    text = w.ledger.read_text()
    assert "TEST_READ" not in text and "PHASE1_VERDICT" not in text


def test_evaluation_without_a_verifiable_base_fails_closed(tmp_path):
    w = build_db_attempt(tmp_path, accept=False)  # ni siquiera es un repositorio git
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2 and w.ledger.read_bytes() == before


def test_evaluation_with_a_local_only_ledger_not_accepted_in_main_fails_closed(tmp_path):
    w = build_db_attempt(tmp_path, accept=False)
    git_init(w.root)
    (w.root / "LEEME").write_text("x")
    git(w.root, "add", "LEEME")  # main NO contiene el libro
    git(w.root, "commit", "-q", "-m", "main sin el libro")
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2 and w.ledger.read_bytes() == before


# --- subcomandos verify-ledger / register / main -----------------------------------------------------------------


def test_verify_ledger_ok_and_tampered(tmp_path, capsys):
    w = build_db_attempt(tmp_path)
    assert script.run_verify_ledger(w.ledger, w.root, "main") == 0
    assert "libro íntegro" in capsys.readouterr().out
    lines = w.ledger.read_text().splitlines()
    w.ledger.write_text("\n".join(lines[:-1]) + "\n" + lines[-1].replace("CALIBRATOR_TRAINED", "PREREG_SIGNED") + "\n")
    assert script.run_verify_ledger(w.ledger, w.root, "main") == 2


def test_register_subcommand_validates_and_appends(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    doc = root / "governance" / "calibration" / "preregistrations" / "prereg_x.md"
    doc.write_text("documento")
    payload = {"prereg_id": "prereg_x", "prereg_sha256": sha256_hex(b"documento"), "signer": "Jhonson Gil",
               "git_commit_base": "b" * 40, "signed_at": "2026-01-02T00:00:00+00:00"}
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(payload))
    bad.write_text(json.dumps({**payload, "prereg_sha256": "0" * 64}))

    assert script.run_register(ledger, "PREREG_SIGNED", bad, "2026-01-02T00:00:00+00:00", root) == 2
    assert not ledger.exists() or read_ledger(ledger) == []
    assert script.run_register(ledger, "PREREG_SIGNED", good, "2026-01-02T00:00:00+00:00", root) == 0
    assert script.run_register(ledger, "PHASE1_VERDICT", good, "2026-01-03T00:00:00+00:00", root) == 2  # solo lo emite el evaluador
    assert script.run_register(ledger, "PREREG_SIGNED", tmp_path / "nope.json", "2026-01-03T00:00:00+00:00", root) == 2
    assert len(read_ledger(ledger)) == 1


def test_main_dispatches_subcommands_and_never_touches_the_real_registry(tmp_path, capsys):
    w = build_db_attempt(tmp_path)
    assert script.main(["verify-ledger", "--ledger", str(w.ledger), "--repo-root", str(w.root), "--base-ref", "main"]) == 0
    assert hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest() == REAL_REGISTRY_SHA


def test_main_requires_an_explicit_models_dir_for_evaluate(tmp_path):
    with pytest.raises(SystemExit):
        script.main(["evaluate", "--attempt-id", "a", "--db-copy", str(tmp_path / "x.db"), "--recorded-at", EVALUATED_AT])


def test_script_source_has_no_promotion_wiring_or_registry_writes():
    text = Path("scripts/evaluate_tennis_calibrator.py").read_text(encoding="utf-8")
    for forbidden in ("model_registry.json", "joblib.dump", "SPORT_ADAPTERS", "load_calibrator_fn"):
        assert forbidden not in text.replace("`config/model_registry.json`", "")
