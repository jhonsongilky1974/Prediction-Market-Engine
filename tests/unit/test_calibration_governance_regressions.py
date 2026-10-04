"""Regresiones de la auditoría adversarial F1–F9 (gobernanza del calibrador de tenis).

Numeración de la tabla de hallazgos: F1 ancla del libro en Git `main` · F2 manifiesto exacto en `evaluate_attempt`
· F3 `trained_at`, sidecar y preregistro editado tras la firma · F4 cierre de intentos y `ATTEMPT_ABANDONED` · F5 sustitución
normativa y garantías en la documentación · F6 sin deserialización de joblib/pickle · F7 bordes de τ (ver también
`test_calibration_verdict.py`) · F8 API pública sin atajos · F9 NumPy (ver verdict) y `fcntl`.
Todo en `tmp_path` con artefactos FALSOS (bytes que no son un pickle) y repositorios git temporales."""
from __future__ import annotations

import ast
import json
import os
import pickle
from pathlib import Path

import pytest

import scripts.evaluate_tennis_calibrator as script
import src.evaluation.calibration_governance as governance
from src.evaluation.calibration_governance import (
    AttemptNotAllowedError,
    GovernanceError,
    HeldOutReadError,
    LedgerIntegrityError,
    ManifestError,
    SafeLoadRequiredError,
    entries_of,
    evaluate_attempt,
    read_ledger,
    register_entry,
    require_attempt_accepted_in_base,
    verify_against_base,
    verify_attempt_artifacts,
)
from src.evaluation.calibration_verdict import SplitMetrics, Verdict
from tests.unit.calibration_governance_factories import (
    T_EVALUATED,
    T_PREREG,
    T_RECORDED,
    T_TRAINED,
    DbAttempt,
    build_attempt,
    build_db_attempt,
    event_ids,
    fake_base,
    freeze_snapshot,
    git,
    git_accept,
    git_init,
    h,
    make_manifest,
    make_repo,
    record_base,
    record_calibrator,
    sign_prereg,
    write_manifest,
)

README = Path("governance/calibration/README.md")
EVALUATED_AT = "2026-06-04T00:00:00+00:00"
ABANDON_PAYLOAD = {"attempt_id": "attempt_001", "reason": "datos congelados descartados", "author": "Jhonson Gil",
                   "abandoned_at": "2026-04-01T00:00:00+00:00"}


def types(ledger: Path):
    return [e["type"] for e in read_ledger(ledger)]


def validation_metrics(manifest: dict, **kw) -> SplitMetrics:
    values = dict(raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19)
    values.update(kw)
    return SplitMetrics(values["raw_ece"], values["calibrated_ece"], values["raw_brier"], values["calibrated_brier"],
                        len(manifest["validation_event_ids"]))


def rewrite_ledger(path: Path, mutate) -> None:
    """Reescribe el libro con una cadena de hashes VÁLIDA tras `mutate(lista de entradas)` (ataque sofisticado)."""
    entries = read_ledger(path)
    mutate(entries)
    prev = governance.GENESIS_HASH
    lines = []
    for seq, entry in enumerate(entries, start=1):
        entry = {**entry, "seq": seq, "prev_sha256": prev}
        entry["entry_sha256"] = governance._entry_hash(seq, prev, entry["type"], entry["recorded_at"], entry["payload"])
        prev = entry["entry_sha256"]
        lines.append(governance.canonical_json(entry).decode("ascii"))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# =====================================================================
# F1 — el ancla es el historial de Git en main (prefijo byte a byte)
# =====================================================================


def test_f1_accepted_ledger_verifies_and_new_entries_appended_after_acceptance_are_new(tmp_path):
    w = build_db_attempt(tmp_path)
    ok = verify_against_base(w.ledger, w.root, "main")
    assert ok.base_entries == ok.total_entries == 4 and ok.head_seq == ok.base_head_seq
    register_entry(w.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-01T00:00:00+00:00", w.root)
    grown = verify_against_base(w.ledger, w.root, "main")
    assert grown.base_entries == 4 and grown.total_entries == 5  # solo se añadió
    assert grown.base_head_sha256 == ok.head_sha256 and grown.head_sha256 != ok.head_sha256


def test_f1_tail_truncation_is_detected_although_the_truncated_chain_is_internally_valid(tmp_path):
    w = build_db_attempt(tmp_path)
    lines = w.ledger.read_text().splitlines()
    w.ledger.write_text("\n".join(lines[:-1]) + "\n")
    assert len(read_ledger(w.ledger)) == 3  # la cadena sola no lo detecta: es válida
    with pytest.raises(LedgerIntegrityError, match="byte a byte|menos entradas"):
        verify_against_base(w.ledger, w.root, "main")


def test_f1_full_chain_rewrite_with_valid_hashes_is_detected(tmp_path):
    w = build_db_attempt(tmp_path)

    def swap_signer(entries):
        entries[0] = {**entries[0], "payload": {**entries[0]["payload"], "signer": "Otra Persona"}}

    rewrite_ledger(w.ledger, swap_signer)
    assert len(read_ledger(w.ledger)) == 4  # cadena regenerada y válida
    with pytest.raises(LedgerIntegrityError, match="byte a byte"):
        verify_against_base(w.ledger, w.root, "main")


def test_f1_replacing_the_ledger_by_an_empty_or_different_file_is_detected(tmp_path):
    w = build_db_attempt(tmp_path)
    w.ledger.write_text("")
    with pytest.raises(LedgerIntegrityError):
        verify_against_base(w.ledger, w.root, "main")
    w.ledger.unlink()
    with pytest.raises(LedgerIntegrityError):
        verify_against_base(w.ledger, w.root, "main")


def test_f1_no_verifiable_base_fails_closed(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    sign_prereg(ledger, root)
    with pytest.raises(GovernanceError, match="no hay base verificable"):  # ni siquiera es un repositorio git
        verify_against_base(ledger, root, "main")
    git_init(root)  # repositorio sin commits: `main` no existe
    with pytest.raises(GovernanceError, match="no hay base verificable"):
        verify_against_base(ledger, root, "main")
    with pytest.raises(GovernanceError, match="no permitida"):  # solo main/origin/main son fuente de verdad
        verify_against_base(ledger, root, "HEAD")
    with pytest.raises(GovernanceError, match="no permitida"):
        verify_against_base(ledger, root, "mi-rama-local")


def test_f1_ledger_outside_the_repository_is_refused(tmp_path):
    w = build_db_attempt(tmp_path)
    outside = tmp_path / "otro_libro.jsonl"
    outside.write_bytes(w.ledger.read_bytes())
    with pytest.raises(GovernanceError, match="dentro del repositorio"):
        verify_against_base(outside, w.root, "main")


def test_f1_a_base_without_ledger_accepts_genesis_but_nothing_is_accepted_yet(tmp_path):
    w = build_db_attempt(tmp_path, accept=False)
    git_init(w.root)
    (w.root / "LEEME").write_text("x")
    git(w.root, "add", "LEEME")
    git(w.root, "commit", "-q", "-m", "base sin libro")
    ok = verify_against_base(w.ledger, w.root, "main")
    assert ok.base_entries == 0 and ok.total_entries == 4
    with pytest.raises(GovernanceError, match="no está aceptado en main"):
        require_attempt_accepted_in_base(ok, "attempt_001")


def test_f1_evaluation_requires_every_entry_of_the_attempt_already_accepted_in_main(tmp_path):
    w = build_db_attempt(tmp_path, accept=False)
    git_init(w.root)
    # solo el preregistro y el snapshot aceptados en main; base y calibrador solo en la rama de trabajo
    keep = w.ledger.read_text().splitlines()[:2]
    full = w.ledger.read_bytes()
    w.ledger.write_text("\n".join(keep) + "\n")
    git_accept(w.root, "preregistro y snapshot por PR")
    w.ledger.write_bytes(full)
    ok = verify_against_base(w.ledger, w.root, "main")
    assert ok.base_entries == 2
    with pytest.raises(GovernanceError, match=r"BASE_TRAINED .*no está aceptado en main"):
        require_attempt_accepted_in_base(ok, "attempt_001")
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2 and w.ledger.read_bytes() == before


def test_f1_file_edits_after_acceptance_are_detected_preregistration_and_manifest(tmp_path):
    w = build_db_attempt(tmp_path)
    prereg = w.root / "governance" / "calibration" / "preregistrations" / "prereg_001.md"
    original = prereg.read_bytes()
    prereg.write_bytes(original + b"\nenmienda posterior a la firma\n")
    with pytest.raises(GovernanceError, match="modificado tras la firma"):
        verify_against_base(w.ledger, w.root, "main")
    assert evaluate(w) == 2
    prereg.write_bytes(original)
    manifest_file = next((w.root / "governance" / "calibration" / "snapshots").glob("*.json"))
    manifest_file.write_bytes(manifest_file.read_bytes() + b" ")
    with pytest.raises(ManifestError):
        verify_against_base(w.ledger, w.root, "main")
    assert evaluate(w) == 2


def evaluate(w: DbAttempt, **overrides) -> int:
    kwargs = dict(ledger=w.ledger, attempt_id="attempt_001", db_copy=w.db_copy, models_dir=w.models_dir,
                  recorded_at=EVALUATED_AT, repo_root=w.root, base_ref="main")
    kwargs.update(overrides)
    return script.run_evaluate(**kwargs)


def test_f1_script_verify_ledger_exit_codes(tmp_path, capsys):
    w = build_db_attempt(tmp_path)
    assert script.run_verify_ledger(w.ledger, w.root, "main") == 0
    out = capsys.readouterr().out
    assert "cabecera aceptada: seq=4" in out and "entry_sha256=" in out
    w.ledger.write_text(w.ledger.read_text().splitlines()[0] + "\n")
    assert script.run_verify_ledger(w.ledger, w.root, "main") == 2
    assert script.run_verify_ledger(w.ledger, w.root, "origin/main") == 2  # sin remoto: sin base verificable => fail-closed


# =====================================================================
# F4 — ATTEMPT_ABANDONED y cierre obligatorio de un intento abierto
# =====================================================================


def test_f4_an_open_attempt_blocks_a_new_one_until_final_verdict_or_abandonment(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, make_manifest(364, cutoff="2026-02-01T00:00:00+00:00", db_tag="db1"), "attempt_001")
    big = make_manifest(520, cutoff="2026-03-01T00:00:00+00:00", db_tag="db2")  # cumpliría la novedad
    with pytest.raises(AttemptNotAllowedError, match="sigue abierto"):
        freeze_snapshot(ledger, root, big, "attempt_002", recorded_at="2026-04-10T00:00:00+00:00")
    register_entry(ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-01T00:00:00+00:00", root)
    freeze_snapshot(ledger, root, big, "attempt_002", recorded_at="2026-04-10T00:00:00+00:00")
    assert types(ledger)[-1] == "SNAPSHOT_FROZEN"


def test_f4_a_final_verdict_also_closes_the_attempt(tmp_path):
    w = build_db_attempt(tmp_path)
    assert evaluate(w) == 0 and types(w.ledger)[-1] == "FINAL_VERDICT"
    prior = sorted(w.manifest["labeled_event_ids"])
    fresh = event_ids(900000, 230)
    later = make_manifest(
        parts={"train": prior, "validation": fresh[:200], "test": fresh[200:]},
        cutoff="2026-07-01T00:00:00+00:00", db_tag="db_later", prereg_id="prereg_001",
    )
    freeze_snapshot(w.ledger, w.root, later, "attempt_002", recorded_at="2026-07-02T00:00:00+00:00")  # no lanza


@pytest.mark.parametrize(
    "patch,match",
    [
        ({"reason": ""}, "reason"),
        ({"reason": "   "}, "reason"),
        ({"author": ""}, "author"),
        ({"abandoned_at": "2026-04-01"}, "abandoned_at"),
        ({"abandoned_at": "2099-01-01T00:00:00+00:00"}, "posterior a recorded_at"),
        ({"attempt_id": "no_existe"}, "no existe"),
        ({"verdict": "ELEGIBLE"}, "claves no permitidas"),
        ({"raw_ece": 0.1}, "claves no permitidas"),
        ({"metrics": {"delta_ece": 1}}, "claves no permitidas"),
    ],
)
def test_f4_abandonment_requires_reason_author_date_and_carries_no_metrics(tmp_path, patch, match):
    a = build_attempt(tmp_path)
    before = a.ledger.read_bytes()
    with pytest.raises(GovernanceError, match=match):
        register_entry(a.ledger, "ATTEMPT_ABANDONED", {**ABANDON_PAYLOAD, **patch}, "2026-04-01T00:00:00+00:00", a.root)
    assert a.ledger.read_bytes() == before


def test_f4_missing_fields_and_double_abandonment_are_refused(tmp_path):
    a = build_attempt(tmp_path)
    payload = {k: v for k, v in ABANDON_PAYLOAD.items() if k != "author"}
    with pytest.raises(GovernanceError, match="faltan campos"):
        register_entry(a.ledger, "ATTEMPT_ABANDONED", payload, "2026-04-01T00:00:00+00:00", a.root)
    register_entry(a.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-01T00:00:00+00:00", a.root)
    with pytest.raises(GovernanceError, match="ya terminó"):
        register_entry(a.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-02T00:00:00+00:00", a.root)


def test_f4_an_abandoned_attempt_can_never_be_evaluated_nor_read_the_test_nor_become_eligible(tmp_path):
    a = build_attempt(tmp_path)
    register_entry(a.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-01T00:00:00+00:00", a.root)
    calls = []
    with pytest.raises(AttemptNotAllowedError, match="abandonado"):
        evaluate_attempt(a.ledger, "attempt_001", a.manifest, validation_metrics(a.manifest),
                         lambda: calls.append(1), EVALUATED_AT)
    with pytest.raises(HeldOutReadError, match="abandonado"):
        governance.read_held_out_once(a.ledger, "attempt_001", a.manifest["base_artifact_sha256"],
                                      a.manifest["test_event_ids_sha256"], lambda: calls.append(1), EVALUATED_AT)
    assert calls == [] and not entries_of(read_ledger(a.ledger), "FINAL_VERDICT")
    assert types(a.ledger)[-1] == "ATTEMPT_ABANDONED"


def test_f4_abandoning_after_a_final_verdict_is_refused(tmp_path):
    w = build_db_attempt(tmp_path)
    assert evaluate(w) == 0
    with pytest.raises(GovernanceError, match="ya terminó"):
        register_entry(w.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-08-01T00:00:00+00:00", w.root)


def test_f4_script_evaluate_refuses_an_abandoned_attempt_without_writing(tmp_path):
    w = build_db_attempt(tmp_path, accept=False)
    git_init(w.root)
    register_entry(w.ledger, "ATTEMPT_ABANDONED", ABANDON_PAYLOAD, "2026-04-01T00:00:00+00:00", w.root)
    git_accept(w.root)
    before = w.ledger.read_bytes()
    assert evaluate(w) == 2 and w.ledger.read_bytes() == before


# =====================================================================
# F2/F3 — manifiesto exacto (F2); sidecar estructurado y trained_at coherente (F3)
# =====================================================================


def test_f2_evaluation_is_bound_to_the_exact_registered_manifest(tmp_path):
    a = build_attempt(tmp_path)
    altered = json.loads(json.dumps(a.manifest))
    altered["environment"] = {"python": "otra-version"}  # válido pero NO es el manifiesto registrado
    provider_calls = []
    result = evaluate_attempt(a.ledger, "attempt_001", altered, validation_metrics(a.manifest),
                              lambda: provider_calls.append(1), EVALUATED_AT)
    assert result.verdict == Verdict.ERROR and "EXACTAMENTE el registrado" in result.reason
    assert provider_calls == [] and "TEST_READ" not in types(a.ledger)


def test_f2_manifest_base_trained_at_must_match_the_ledger(tmp_path):
    a = build_attempt(tmp_path)
    altered = json.loads(json.dumps(a.manifest))
    altered["base_trained_at"] = "2026-03-02T00:00:00+00:00"
    result = evaluate_attempt(a.ledger, "attempt_001", altered, validation_metrics(a.manifest), None, EVALUATED_AT)
    assert result.verdict == Verdict.ERROR


def test_f3_registering_base_or_calibrator_requires_an_explicit_models_dir(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = make_manifest(base=base)
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    payload = {"attempt_id": "attempt_001", "snapshot_id": manifest["snapshot_id"], "prereg_id": manifest["prereg_id"],
               "base_model_version": base["version"], "base_artifact_sha256": base["artifact_sha256"],
               "base_metadata_sha256": base["metadata_sha256"], "trained_at": base["trained_at"]}
    with pytest.raises(GovernanceError, match="models_dir"):
        register_entry(ledger, "BASE_TRAINED", payload, T_RECORDED, root)
    assert types(ledger) == ["PREREG_SIGNED", "SNAPSHOT_FROZEN"]
    assert script.run_register(ledger, "BASE_TRAINED", _write(tmp_path / "p.json", payload), T_RECORDED, root) == 2


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _attempt_files(a):
    base = entries_of(read_ledger(a.ledger), "BASE_TRAINED")[0]["payload"]
    cal = entries_of(read_ledger(a.ledger), "CALIBRATOR_TRAINED")[0]["payload"]
    return base, cal


@pytest.mark.parametrize(
    "scenario",
    [
        "no_models_dir", "base_sidecar_missing", "base_sidecar_altered", "base_artifact_altered", "base_artifact_missing",
        "cal_sidecar_altered", "cal_artifact_altered", "base_trained_at_differs_in_sidecar", "file_path_outside_models_dir",
        "base_sidecar_without_trained_at", "cal_sidecar_other_base", "cal_trained_at_differs_in_sidecar",
    ],
)
def test_f3_any_absence_or_discrepancy_in_sidecars_or_artifacts_fails_closed(tmp_path, scenario):
    a = build_attempt(tmp_path)
    base, cal = _attempt_files(a)
    models_dir = a.models_dir
    base_meta = models_dir / f"{base['base_model_version']}.metadata.json"
    cal_meta = models_dir / f"{cal['calibrator_version']}.metadata.json"

    def edit(path: Path, **changes):
        data = json.loads(path.read_text())
        data.update(changes)
        path.write_text(json.dumps(data))

    if scenario == "no_models_dir":
        models_dir = None
    elif scenario == "base_sidecar_missing":
        base_meta.unlink()
    elif scenario == "base_sidecar_altered":
        base_meta.write_text(base_meta.read_text() + " ")
    elif scenario == "base_artifact_altered":
        (models_dir / f"{base['base_model_version']}.joblib").write_bytes(b"otra cosa")
    elif scenario == "base_artifact_missing":
        (models_dir / f"{base['base_model_version']}.joblib").unlink()
    elif scenario == "cal_sidecar_altered":
        cal_meta.write_text(cal_meta.read_text() + " ")
    elif scenario == "cal_artifact_altered":
        (models_dir / f"{cal['calibrator_version']}.joblib").write_bytes(b"otra cosa")
    elif scenario == "base_trained_at_differs_in_sidecar":
        edit(base_meta, trained_at="2026-03-05T00:00:00+00:00")
    elif scenario == "file_path_outside_models_dir":
        outside = tmp_path / "fuera.joblib"
        outside.write_bytes((models_dir / f"{base['base_model_version']}.joblib").read_bytes())
        edit(base_meta, file_path=str(outside))
    elif scenario == "base_sidecar_without_trained_at":
        data = json.loads(base_meta.read_text())
        data.pop("trained_at")
        base_meta.write_text(json.dumps(data))
    elif scenario == "cal_sidecar_other_base":
        edit(cal_meta, base_model_version="tennis_baseline_logreg_v1_otro")
    elif scenario == "cal_trained_at_differs_in_sidecar":
        edit(cal_meta, trained_at="2026-03-06T00:00:00+00:00")
    # los cambios en sidecars cambian su SHA-256: se comprueba el error explícito de hash o de coherencia
    with pytest.raises(GovernanceError):
        verify_attempt_artifacts(read_ledger(a.ledger), a.manifest, models_dir, "attempt_001")


def test_f3_sidecar_verification_never_uses_the_filesystem_mtime(tmp_path):
    a = build_attempt(tmp_path)
    base, cal = _attempt_files(a)
    for name in (f"{base['base_model_version']}.joblib", f"{base['base_model_version']}.metadata.json",
                 f"{cal['calibrator_version']}.joblib", f"{cal['calibrator_version']}.metadata.json"):
        os.utime(a.models_dir / name, (4102444800, 4102444800))  # año 2100
    verify_attempt_artifacts(read_ledger(a.ledger), a.manifest, a.models_dir, "attempt_001")  # no lanza
    source = Path(governance.__file__).read_text(encoding="utf-8")
    assert "st_mtime" not in source and "getmtime" not in source and ".stat()" not in source


@pytest.mark.parametrize("tamper", ["calibrated_ece_oof", "raw_brier", "n_calibration_events"])
def test_f3_calibrator_metrics_in_the_ledger_must_equal_those_of_its_sidecar(tmp_path, tamper):
    a = build_attempt(tmp_path)
    base, cal = _attempt_files(a)
    meta = a.models_dir / f"{cal['calibrator_version']}.metadata.json"
    data = json.loads(meta.read_text())
    data[tamper] = data[tamper] + (1 if tamper == "n_calibration_events" else 0.01)
    meta.write_text(json.dumps(data))
    with pytest.raises(GovernanceError):  # el hash del sidecar ya no es el registrado
        verify_attempt_artifacts(read_ledger(a.ledger), a.manifest, a.models_dir, "attempt_001")


def test_f3_calibrator_registered_with_metrics_that_differ_from_its_sidecar_is_refused(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = make_manifest(base=base)
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    record_base(ledger, root, manifest, models_dir)
    from tests.unit.calibration_governance_factories import fake_calibrator
    cal = fake_calibrator(models_dir, "cal1", base["version"], calibrated_ece=0.05, n_events=32)
    payload = {"attempt_id": "attempt_001", "calibrator_version": cal["version"],
               "calibrator_artifact_sha256": cal["artifact_sha256"], "calibrator_metadata_sha256": cal["metadata_sha256"],
               "base_model_version": base["version"], "trained_at": T_TRAINED, "raw_ece": 0.08, "raw_brier": 0.20,
               "calibrated_ece_oof": 0.0001, "calibrated_brier_oof": 0.19, "n_calibration_events": 32}  # ECE "mejor" que el sidecar
    with pytest.raises(GovernanceError, match="discrepa del sidecar"):
        register_entry(ledger, "CALIBRATOR_TRAINED", payload, T_RECORDED, root, models_dir)


def test_f3_trained_at_must_match_between_manifest_ledger_and_sidecar_when_registering_the_base(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = make_manifest(base=base)
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    with pytest.raises(GovernanceError, match="trained_at del manifiesto"):
        record_base(ledger, root, manifest, models_dir, trained_at="2026-03-01T01:00:00+00:00")
    other = fake_base(models_dir, tag="base1", trained_at="2026-03-01T00:00:00+00:00")  # mismo archivo, mismo instante
    assert other["artifact_sha256"] == base["artifact_sha256"]
    record_base(ledger, root, manifest, models_dir)  # coherente: se registra
    assert types(ledger)[-1] == "BASE_TRAINED"


# =====================================================================
# F6 — nada deserializa joblib/pickle
# =====================================================================


def _imports_and_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    imported_names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)} | {
        n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    return imported, imported_names, called


@pytest.mark.parametrize(
    "path", ["src/evaluation/calibration_governance.py", "src/evaluation/calibration_verdict.py", "scripts/evaluate_tennis_calibrator.py"]
)
def test_f6_evaluation_code_cannot_import_or_call_a_deserializer(path):
    imported, imported_names, called = _imports_and_calls(Path(path))
    assert not {m.split(".")[0] for m in imported if m} & {"joblib", "pickle", "cloudpickle", "dill", "shelve", "marshal"}
    loaders = {"load_latest_tennis_artifact", "load_latest_tennis_calibrator", "load_model_registry", "joblib_load"}
    assert not (called | imported_names) & loaders
    assert "joblib.load" not in Path(path).read_text(encoding="utf-8").replace("joblib/pickle", "")


def test_f6_a_malicious_artifact_is_hashed_but_never_executed_and_a_preliminary_candidate_stops_with_an_error(tmp_path):
    marker = tmp_path / "EJECUTADO"

    class Bomb:
        def __reduce__(self):
            return (Path(marker).write_text, ("pwned",))

    # candidato ELEGIBLE_PRELIMINAR con un artefacto que ejecutaría código si alguien lo deserializara
    w = build_db_attempt(tmp_path, accept=False, raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19)
    base_artifact = w.base["artifact_path"]
    base_artifact.write_bytes(pickle.dumps(Bomb()))
    # re-registrar hashes coherentes del nuevo artefacto y del sidecar (el atacante controla ambos)
    _rebuild_with_artifact(w, tmp_path)
    git_init(w.root)
    git_accept(w.root)
    before = w.ledger.read_bytes()

    code = evaluate(w)

    assert code == 2 and w.ledger.read_bytes() == before  # SafeLoadRequiredError: nada escrito
    assert not marker.exists()  # no se deserializó nada


def _rebuild_with_artifact(w: DbAttempt, tmp_path: Path) -> None:
    """Reconstruye el libro del intento con los bytes actuales del artefacto base (para la prueba de F4)."""
    from tests.unit.calibration_governance_factories import (
        build_snapshot_manifest, fake_calibrator, sha256_hex, sign_prereg as sign,
    )
    import shutil
    shutil.rmtree(w.root)
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    artifact = w.base["artifact_path"]
    meta_path = w.base["metadata_path"]
    sha_art = sha256_hex(artifact.read_bytes())
    manifest = build_snapshot_manifest(
        prereg_id="prereg_001", db_sha256=w.manifest["db_sha256"], cutoff_utc=w.manifest["cutoff_utc"],
        train_event_ids=w.manifest["train_event_ids"], validation_event_ids=w.manifest["validation_event_ids"],
        test_event_ids=w.manifest["test_event_ids"], base_model_version=w.base["version"],
        base_artifact_sha256=sha_art, base_metadata_sha256=sha256_hex(meta_path.read_bytes()),
        base_trained_at=w.base["trained_at"],
    )
    sign(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    record_base(ledger, root, manifest, w.models_dir)
    for f in w.models_dir.glob("tennis_calibrator_platt_v1_*"):
        f.unlink()
    record_calibrator(ledger, root, manifest, w.models_dir, raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19)
    w.root, w.ledger, w.manifest = root, ledger, manifest


def test_f6_evaluate_attempt_without_a_loader_stops_before_writing_anything(tmp_path):
    a = build_attempt(tmp_path)  # métricas por defecto: ELEGIBLE_PRELIMINAR
    before = a.ledger.read_bytes()
    with pytest.raises(SafeLoadRequiredError, match="deserializar"):
        evaluate_attempt(a.ledger, "attempt_001", a.manifest, validation_metrics(a.manifest), None, EVALUATED_AT)
    with pytest.raises(SafeLoadRequiredError):
        evaluate_attempt(a.ledger, "attempt_001", a.manifest, validation_metrics(a.manifest), lambda: None, EVALUATED_AT,
                         allow_test_read=False)
    assert a.ledger.read_bytes() == before and not entries_of(read_ledger(a.ledger), "PHASE1_VERDICT")


def test_f6_non_preliminary_outcomes_finalize_without_any_deserialization(tmp_path):
    w = build_db_attempt(tmp_path)  # por defecto el calibrador deteriora => RECHAZADO sin tocar el test
    assert evaluate(w) == 0
    final = entries_of(read_ledger(w.ledger), "FINAL_VERDICT")[0]["payload"]
    assert final["verdict"] == "RECHAZADO" and "TEST_READ" not in types(w.ledger)


def test_f6_documentation_states_sha256_proves_identity_only_and_records_the_inherited_debt():
    text = " ".join(README.read_text(encoding="utf-8").split())
    assert "SHA-256" in text and "identidad" in text
    assert "no demuestra seguridad" in text or "no prueba seguridad" in text or "no confirma seguridad" in text
    assert "PR #7" in text and "PR #8" in text and "deuda" in text.lower()


# =====================================================================
# F5 — la documentación distingue garantías técnicas de las que dependen de Git/PR
# =====================================================================


def test_f5_readme_separates_technical_guarantees_from_those_that_depend_on_git_and_review():
    text = " ".join(README.read_text(encoding="utf-8").split())
    for needle in ("Ancla del libro", "branch protection", "revisión", "ATTEMPT_ABANDONED", "no es un ancla criptográfica independiente"):
        assert needle in text, needle
    lowered = text.lower()
    assert "garantías técnicas" in lowered and "dependen de git" in lowered


def test_f5_normative_substitution_is_declared_consistently_in_readme_and_calibration_spec():
    def flat(path: Path) -> str:  # sin el prefijo `>` de los blockquotes ni saltos de línea
        return " ".join(line.lstrip("> ").strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    readme, spec = flat(README), flat(Path("CALIBRATION_SPEC.md"))
    for needle in ("Sustitución normativa", "CALIBRATION_SPEC.md` §6", "amplía su §2", "prevalece este documento",
                   "un empate, o una diferencia dentro de τ = 1e-4, es `INCONCLUSO`", "no lo cablea ni lo autoriza"):
        assert needle in readme, needle
    for needle in ("sustituye el criterio de aceptación de este §6", "amplía §2", "prevalece el README",
                   "ELEGIBLE` solo permite *proponer*"):
        assert needle in spec, needle
    assert "se conserva como precondición" not in spec  # la versión anterior contradecía la sustitución
    assert "salvo que quien escriba el archivo recalcule todos los hashes posteriores" in readme


# =====================================================================
# F8 — la API pública no permite saltarse el flujo gobernado
# =====================================================================


def test_f8_there_is_no_public_append_entry_and_evaluation_entries_cannot_be_registered(tmp_path):
    assert not hasattr(governance, "append_entry") and hasattr(governance, "_append_entry")
    assert "append_entry" not in governance.__all__ if hasattr(governance, "__all__") else True
    ledger = tmp_path / "ledger.jsonl"
    for entry_type in ("PHASE1_VERDICT", "TEST_READ", "TEST_RESULT", "FINAL_VERDICT"):
        with pytest.raises(GovernanceError, match="solo puede emitirlo"):
            register_entry(ledger, entry_type, {"attempt_id": "a"}, T_PREREG, tmp_path)
    assert not ledger.exists()


def test_f8_the_internal_append_keeps_its_own_fail_closed_validations(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(GovernanceError):
        governance._append_entry(ledger, "FINAL_VERDICT", {"attempt_id": "a"}, T_PREREG)  # faltan campos
    with pytest.raises(GovernanceError):
        governance._append_entry(ledger, "ATTEMPT_ABANDONED", {**ABANDON_PAYLOAD, "verdict": "ELEGIBLE"}, T_PREREG)
    assert not ledger.exists()


def test_f8_a_forged_phase1_in_an_unevaluated_attempt_does_not_let_the_veto_be_bypassed_by_register_entry(tmp_path):
    a = build_attempt(tmp_path)
    with pytest.raises(GovernanceError):
        register_entry(a.ledger, "PHASE1_VERDICT", {"attempt_id": "attempt_001", "verdict": "ELEGIBLE_PRELIMINAR", "reason": "x"},
                       EVALUATED_AT, a.root)
    with pytest.raises(HeldOutReadError):
        governance.read_held_out_once(a.ledger, "attempt_001", a.manifest["base_artifact_sha256"],
                                      a.manifest["test_event_ids_sha256"], lambda: SplitMetrics(0.1, 0.05, 0.2, 0.19, 40), EVALUATED_AT)


# =====================================================================
# F9 — fcntl encapsulado: plataformas no POSIX fallan de forma clara y segura
# =====================================================================


def test_f9_without_fcntl_nothing_is_written_and_the_error_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(governance, "fcntl", None)
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    with pytest.raises(GovernanceError, match="POSIX"):
        sign_prereg(ledger, root)
    assert not ledger.exists()
    assert read_ledger(ledger) == []  # leer (verificar) no necesita fcntl


def test_f9_the_module_imports_without_fcntl_available(tmp_path):
    import subprocess
    import sys
    code = (
        "import sys; sys.modules['fcntl'] = None\n"
        "import src.evaluation.calibration_governance as g\n"
        "assert g.fcntl is None\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path.cwd())
    assert result.returncode == 0, result.stderr


# =====================================================================
# F10 (descartado como defecto): las claves desconocidas siguen rechazadas sin ampliar el esquema
# =====================================================================


def test_f10_unknown_candidate_keys_are_still_rejected(tmp_path):
    from src.evaluation.candidate_registry import CandidateRegistryError, load_candidate_registry
    registry = tmp_path / "candidate.json"
    registry.write_text(json.dumps({"candidate_models": {}, "models": {}}), encoding="utf-8")
    with pytest.raises((CandidateRegistryError, GovernanceError)):
        load_candidate_registry(registry, models_dir=tmp_path, ledger_path=tmp_path / "ledger.jsonl", allowed_dir=tmp_path)


def test_f3_registering_the_base_is_refused_when_only_the_sidecar_trained_at_differs(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir, trained_at="2026-03-05T00:00:00+00:00")  # el sidecar dice 03-05
    manifest = make_manifest(base=base, base_trained_at=T_TRAINED)  # manifiesto y libro dirán 03-01
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    with pytest.raises(GovernanceError, match="trained_at del sidecar del modelo base"):
        record_base(ledger, root, manifest, models_dir)
    assert "BASE_TRAINED" not in types(ledger)
