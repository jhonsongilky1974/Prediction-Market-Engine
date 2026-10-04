"""`scripts/train_tennis_calibrator.py`: opción explícita `--candidate-registry` (fail-closed) y
mensaje corregido (el script jamás declara "cumplido"; el veredicto lo emite el evaluador).
Todo en `tmp_path`; HistoryRepository monkeypatcheada; nunca toca `data/` ni el registro real."""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

import scripts.train_tennis_calibrator as script
from src.evaluation import candidate_registry
from src.models.model_registry_policy import DEFAULT_MODEL_REGISTRY_PATH
from tests.unit.calibration_governance_factories import TrainedWorld, build_trained_world

REAL_REGISTRY_SHA = hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch) -> TrainedWorld:
    w = build_trained_world(tmp_path)
    monkeypatch.setattr(script, "HistoryRepository", lambda: w.hist)
    monkeypatch.setattr(candidate_registry, "DEFAULT_CANDIDATES_DIR", w.candidate_path.parent)
    return w


def run(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["train_tennis_calibrator.py", *map(str, args)])
    code = script.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def calibrator_files(world):
    return sorted(world.models_dir.glob("tennis_calibrator_platt_v1_*"))


def test_without_the_option_the_script_uses_the_real_registry_and_fits_nothing(world, monkeypatch, capsys):
    code, out, err = run(monkeypatch, capsys, "--models-dir", world.models_dir)

    assert code == 0 and "Ningún calibrador ajustado" in out
    assert calibrator_files(world) == []  # el registro real no tiene ningún modelo ALLOWED


def test_with_a_valid_candidate_registry_it_fits_and_never_declares_the_criterion_met(world, monkeypatch, capsys):
    code, out, err = run(
        monkeypatch, capsys, "--models-dir", world.models_dir, "--candidate-registry", world.candidate_path, "--ledger", world.ledger
    )

    assert code == 0 and "status: TRAINED" in out and "Registro candidato verificado" in out
    assert len(calibrator_files(world)) == 2  # .joblib + .metadata.json
    assert "CUMPLIDO" not in out and "NO CUMPLIDO" not in out
    assert "NO declara cumplido ni incumplido" in out and "scripts/evaluate_tennis_calibrator.py" in out
    assert "no queda promovido ni cableado" in out
    assert hashlib.sha256(DEFAULT_MODEL_REGISTRY_PATH.read_bytes()).hexdigest() == REAL_REGISTRY_SHA  # registro real intacto


@pytest.mark.parametrize("scenario", ["missing_file", "tampered_artifact", "empty_ledger", "production_registry", "outside_dir"])
def test_any_problem_with_the_candidate_registry_exits_2_and_fits_nothing(world, monkeypatch, capsys, tmp_path, scenario):
    args = ["--models-dir", world.models_dir, "--candidate-registry", world.candidate_path, "--ledger", world.ledger]
    if scenario == "missing_file":
        args[3] = world.candidate_path.parent / "no_existe.json"
    elif scenario == "tampered_artifact":
        world.base.file_path.write_bytes(world.base.file_path.read_bytes() + b"x")
    elif scenario == "empty_ledger":
        args[5] = tmp_path / "vacio.jsonl"
    elif scenario == "production_registry":
        args[3] = DEFAULT_MODEL_REGISTRY_PATH
    elif scenario == "outside_dir":
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(world.candidate_path.read_text())
        args[3] = elsewhere

    code, out, err = run(monkeypatch, capsys, *args)

    assert code == 2 and "fail-closed" in err
    assert calibrator_files(world) == []
    assert "status:" not in out  # ni siquiera se intentó entrenar


def test_a_candidate_file_placed_outside_the_default_directory_is_rejected(world, monkeypatch, capsys):
    monkeypatch.undo()  # restablece el directorio candidato REAL del repositorio y la HistoryRepository real
    monkeypatch.setattr(script, "HistoryRepository", lambda: world.hist)
    code, out, err = run(
        monkeypatch, capsys, "--models-dir", world.models_dir, "--candidate-registry", world.candidate_path, "--ledger", world.ledger
    )
    assert code == 2 and "directamente en" in err
    assert calibrator_files(world) == []


def test_source_message_does_not_contain_the_old_cumplido_claims():
    text = open("scripts/train_tennis_calibrator.py", encoding="utf-8").read()
    assert "CUMPLIDO" not in text.replace("NO declara cumplido", "")
