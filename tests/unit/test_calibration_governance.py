"""Gobernanza: libro append-only con cadena de hashes, manifiestos, eventos nuevos entre
intentos (no cherry-picking), preregistro firmado antes del entrenamiento, y lectura ÚNICA
del test (veto que nunca eleva). Todo en `tmp_path`; sin datos reales ni entrenamiento."""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

import src.evaluation.calibration_governance as governance
import src.evaluation.calibration_verdict as verdict_module
from src.evaluation.calibration_governance import (
    AttemptNotAllowedError,
    GENESIS_HASH,
    GovernanceError,
    HeldOutAlreadyReadError,
    HeldOutReadError,
    LedgerIntegrityError,
    ManifestError,
    check_attempt_allowed,
    compute_novelty,
    entries_of,
    evaluate_attempt,
    ids_sha256,
    load_manifest,
    read_held_out_once,
    read_ledger,
    register_entry,
    validate_snapshot_manifest,
    verify_prereg_precedes_training,
)
from src.evaluation.calibration_verdict import SplitMetrics, Verdict
from tests.unit.calibration_governance_factories import (
    CUTOFF,
    T_EVALUATED,
    T_PREREG,
    T_RECORDED,
    T_SNAPSHOT,
    T_TRAINED,
    build_attempt,
    fake_base,
    freeze_snapshot,
    h,
    make_manifest,
    make_repo,
    record_base,
    record_calibrator,
    sign_prereg,
    split_ids,
    write_manifest,
)

_append_entry = governance._append_entry
PAYLOAD_TEST_READ = {"attempt_id": "a", "base_artifact_sha256": h("b"), "test_event_ids_sha256": h("t")}


def ledger_in(tmp_path: Path) -> Path:
    return tmp_path / "ledger.jsonl"


# =====================================================================
# Libro append-only
# =====================================================================


def test_append_builds_a_hash_chain_and_read_verifies_it(tmp_path):
    ledger = ledger_in(tmp_path)
    first = governance._append_entry(ledger, "TEST_READ", PAYLOAD_TEST_READ, T_PREREG)
    second = governance._append_entry(ledger, "TEST_READ", {**PAYLOAD_TEST_READ, "attempt_id": "b"}, T_SNAPSHOT)

    assert first["prev_sha256"] == GENESIS_HASH and first["seq"] == 1
    assert second["prev_sha256"] == first["entry_sha256"] and second["seq"] == 2
    assert [e["seq"] for e in read_ledger(ledger)] == [1, 2]
    assert ledger.read_text(encoding="ascii").endswith("\n")  # JSON canónico ASCII, una línea por entrada


def test_missing_ledger_is_an_empty_genesis_ledger(tmp_path):
    assert read_ledger(tmp_path / "nope.jsonl") == []


def test_append_never_rewrites_existing_lines(tmp_path):
    ledger = ledger_in(tmp_path)
    governance._append_entry(ledger, "TEST_READ", PAYLOAD_TEST_READ, T_PREREG)
    before = ledger.read_bytes()
    governance._append_entry(ledger, "TEST_READ", {**PAYLOAD_TEST_READ, "attempt_id": "b"}, T_SNAPSHOT)
    assert ledger.read_bytes().startswith(before)  # lo previo queda byte a byte intacto


def _three_entries(tmp_path):
    ledger = ledger_in(tmp_path)
    for i, t in enumerate((T_PREREG, T_SNAPSHOT, T_TRAINED)):
        governance._append_entry(ledger, "TEST_READ", {**PAYLOAD_TEST_READ, "attempt_id": f"a{i}"}, t)
    return ledger


def test_editing_an_earlier_payload_is_detected_by_read_and_by_append(tmp_path):
    ledger = _three_entries(tmp_path)
    lines = ledger.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["payload"]["attempt_id"] = "tampered"
    lines[0] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n")

    with pytest.raises(LedgerIntegrityError):
        read_ledger(ledger)
    with pytest.raises(LedgerIntegrityError):
        governance._append_entry(ledger, "TEST_READ", PAYLOAD_TEST_READ, "2026-12-01T00:00:00+00:00")


def test_editing_an_earlier_entry_even_with_a_recomputed_own_hash_breaks_the_next_link(tmp_path):
    ledger = _three_entries(tmp_path)
    lines = ledger.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["payload"]["attempt_id"] = "tampered"
    entry["entry_sha256"] = governance._entry_hash(
        entry["seq"], entry["prev_sha256"], entry["type"], entry["recorded_at"], entry["payload"]
    )
    lines[0] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n")

    with pytest.raises(LedgerIntegrityError, match="cadena rota"):
        read_ledger(ledger)


@pytest.mark.parametrize("mutation", ["delete_middle", "reorder", "drop_trailing_newline", "garbage_line", "extra_key"])
def test_structural_tampering_is_detected(tmp_path, mutation):
    ledger = _three_entries(tmp_path)
    lines = ledger.read_text().splitlines()
    if mutation == "delete_middle":
        text = "\n".join([lines[0], lines[2]]) + "\n"
    elif mutation == "reorder":
        text = "\n".join([lines[1], lines[0], lines[2]]) + "\n"
    elif mutation == "drop_trailing_newline":
        text = "\n".join(lines)
    elif mutation == "garbage_line":
        text = "\n".join(lines + ["{not json"]) + "\n"
    else:
        entry = json.loads(lines[1])
        entry["extra"] = 1
        text = "\n".join([lines[0], json.dumps(entry), lines[2]]) + "\n"
    ledger.write_text(text)

    with pytest.raises(LedgerIntegrityError):
        read_ledger(ledger)


def test_recorded_at_cannot_go_backwards_or_be_naive_or_non_utc(tmp_path):
    ledger = ledger_in(tmp_path)
    governance._append_entry(ledger, "TEST_READ", PAYLOAD_TEST_READ, T_TRAINED)
    for bad in ("2026-01-01T00:00:00+00:00", "2026-12-01T00:00:00", "2026-12-01T00:00:00+02:00", "", None, 5):
        with pytest.raises(GovernanceError):
            governance._append_entry(ledger, "TEST_READ", PAYLOAD_TEST_READ, bad)
    assert len(read_ledger(ledger)) == 1  # nada se escribió


def test_unknown_type_missing_fields_and_nan_are_rejected_without_writing(tmp_path):
    ledger = ledger_in(tmp_path)
    with pytest.raises(GovernanceError):
        governance._append_entry(ledger, "APROBADO", {}, T_PREREG)
    with pytest.raises(GovernanceError):
        governance._append_entry(ledger, "TEST_READ", {"attempt_id": "a"}, T_PREREG)
    with pytest.raises(GovernanceError):
        governance._append_entry(ledger, "TEST_RESULT", {"attempt_id": "a", "status": "OK", "x": math.nan}, T_PREREG)
    assert not ledger.exists() or read_ledger(ledger) == []


# =====================================================================
# Manifiesto
# =====================================================================


def test_valid_manifest_roundtrips_and_load_verifies_the_file_hash(tmp_path):
    root = make_repo(tmp_path)
    manifest = make_manifest()
    rel, sha = write_manifest(root, manifest)
    path = root / rel
    assert load_manifest(path, sha) == manifest
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ManifestError, match="alterado"):
        load_manifest(path, sha)


def _bad(manifest, **changes):
    broken = json.loads(json.dumps(manifest))
    broken.update(changes)
    return broken


def test_manifest_rejects_duplicates_overlaps_unsorted_hash_mismatch_and_bad_fields():
    manifest = make_manifest()
    parts = split_ids(0, 160)
    cases = {
        "duplicados": _bad(manifest, validation_event_ids=sorted(parts["validation"] + [parts["validation"][0]])),
        "desordenada": _bad(manifest, test_event_ids=list(reversed(parts["test"]))),
        "hash de lista distinto": _bad(manifest, test_event_ids_sha256=h("otro")),
        "solapamiento": _bad(
            manifest,
            train_event_ids=sorted(parts["train"] + [parts["test"][0]]),
            train_event_ids_sha256=ids_sha256(sorted(parts["train"] + [parts["test"][0]])),
        ),
        "labeled no es la unión": _bad(manifest, labeled_event_ids=parts["train"], labeled_event_ids_sha256=ids_sha256(parts["train"])),
        "snapshot_id falso": _bad(manifest, snapshot_id="snap_falso"),
        "cutoff naive": _bad(manifest, cutoff_utc="2026-02-01T00:00:00"),
        "sha inválido": _bad(manifest, db_sha256="XYZ"),
        "campo faltante": {k: v for k, v in manifest.items() if k != "test_event_ids"},
        "no es objeto": [],
    }
    for name, broken in cases.items():
        with pytest.raises(ManifestError):
            validate_snapshot_manifest(broken)


# =====================================================================
# Eventos nuevos entre intentos
# =====================================================================


def _later(first_new_n_total, prior_n=364, **kwargs):
    """Manifiesto posterior: los `prior_n` eventos previos + `first_new_n_total` nuevos (cronológico)."""
    prior = make_manifest(prior_n, cutoff="2026-02-01T00:00:00+00:00", db_tag="db1")
    later = make_manifest(prior_n + first_new_n_total, cutoff="2026-03-01T00:00:00+00:00", db_tag="db2", **kwargs)
    return prior, later


def test_first_attempt_has_no_novelty_requirement():
    manifest = make_manifest()
    novelty = check_attempt_allowed(manifest, [])
    assert novelty.prior_events == 0 and novelty.new_total == 160


def test_enough_genuinely_new_events_allow_a_new_attempt():
    prior, later = _later(150)  # N=364, M=150
    novelty = check_attempt_allowed(later, [prior])
    assert novelty.new_total == 150 and novelty.new_validation >= 30 and novelty.prior_events == 364
    assert novelty.new_validation == len(set(later["validation_event_ids"]) - set(prior["labeled_event_ids"]))


@pytest.mark.parametrize("n_new", [100, 140, 149])
def test_fewer_than_150_new_events_in_total_do_not_allow_repeating(n_new):
    # con un conjunto previo pequeño la validación nueva sí llega a 30: la regla de los 150 totales es la que falla
    prior, later = _later(n_new, prior_n=100)
    assert compute_novelty(later, [prior]).new_validation >= 30
    with pytest.raises(AttemptNotAllowedError, match="en total"):
        check_attempt_allowed(later, [prior])


def test_too_few_new_events_also_fail_the_validation_rule_with_a_large_prior_set():
    prior, later = _later(100)
    with pytest.raises(AttemptNotAllowedError, match="no se permite repetir"):
        check_attempt_allowed(later, [prior])


def test_150_total_new_events_are_not_enough_if_they_do_not_reach_validation():
    """Con un conjunto previo grande, los 150 nuevos caen casi todos en train/test cronológicos y
    la validación queda sin eventos nuevos: la regla de validación es la que manda."""
    prior, later = _later(150, prior_n=600)
    novelty = compute_novelty(later, [prior])
    assert novelty.new_total == 150 and novelty.new_validation < 30
    with pytest.raises(AttemptNotAllowedError, match="en validación"):
        check_attempt_allowed(later, [prior])


def test_reused_events_do_not_count_as_new_even_when_they_move_into_validation():
    prior, later = _later(150)
    reused_in_validation = set(later["validation_event_ids"]) & set(prior["labeled_event_ids"])
    assert reused_in_validation  # hay eventos viejos reutilizados en la nueva validación
    novelty = compute_novelty(later, [prior])
    assert novelty.new_validation == len(later["validation_event_ids"]) - len(reused_in_validation)


def test_repeated_snapshot_same_db_earlier_cutoff_and_retroactive_changes_are_refused():
    prior = make_manifest(364, cutoff="2026-02-01T00:00:00+00:00", db_tag="db1")
    with pytest.raises(AttemptNotAllowedError, match="ya fue usado"):
        check_attempt_allowed(prior, [prior])
    same_db = make_manifest(520, cutoff="2026-03-01T00:00:00+00:00", db_tag="db1")
    with pytest.raises(AttemptNotAllowedError, match="idéntica"):
        check_attempt_allowed(same_db, [prior])
    earlier = make_manifest(520, cutoff="2026-01-15T00:00:00+00:00", db_tag="db2")
    with pytest.raises(AttemptNotAllowedError, match="posterior"):
        check_attempt_allowed(earlier, [prior])
    dropped = make_manifest(parts=split_ids(10, 520), cutoff="2026-03-01T00:00:00+00:00", db_tag="db3")  # no incluye ev_000000..9
    with pytest.raises(ManifestError, match="retroactivos"):
        check_attempt_allowed(dropped, [prior])


def test_equivalent_snapshots_cannot_be_used_to_retry_until_approved():
    """Cuatro snapshots 'equivalentes' (mismos datos, cortes y copias distintos) no habilitan nuevos intentos."""
    base = make_manifest(364, cutoff="2026-02-01T00:00:00+00:00", db_tag="db1")
    for day, tag in ((2, "dbA"), (3, "dbB"), (4, "dbC"), (5, "dbD")):
        clone = make_manifest(364, cutoff=f"2026-02-0{day}T00:00:00+00:00", db_tag=tag)
        with pytest.raises(AttemptNotAllowedError):
            check_attempt_allowed(clone, [base])


# =====================================================================
# Preregistro antes del entrenamiento
# =====================================================================


def test_preregistration_must_be_signed_before_training(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    sign_prereg(ledger, root, recorded_at=T_PREREG, signed_at=T_PREREG)
    entries = read_ledger(ledger)
    verify_prereg_precedes_training(entries, "prereg_001", T_TRAINED)  # firmado antes: ok
    with pytest.raises(GovernanceError, match="no fue firmado antes"):
        verify_prereg_precedes_training(entries, "prereg_001", "2026-01-01T00:00:00+00:00")
    with pytest.raises(GovernanceError, match="no existe PREREG_SIGNED"):
        verify_prereg_precedes_training(entries, "otro", T_TRAINED)


def test_base_training_before_the_signature_is_refused_by_the_ledger(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    early = "2026-01-01T00:00:00+00:00"
    base = fake_base(models_dir, trained_at=early)
    manifest = make_manifest(base=base)
    sign_prereg(ledger, root, recorded_at=T_PREREG, signed_at=T_PREREG)
    freeze_snapshot(ledger, root, manifest)
    with pytest.raises(GovernanceError, match="no fue firmado antes"):
        record_base(ledger, root, manifest, models_dir)
    assert not entries_of(read_ledger(ledger), "BASE_TRAINED")


# =====================================================================
# register_entry: invariantes por tipo
# =====================================================================


def test_register_prereg_requires_matching_document_hash_commit_signer_and_no_duplicates(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    doc = root / "governance" / "calibration" / "preregistrations" / "prereg_001.md"
    doc.write_text("documento", encoding="utf-8")
    good = {"prereg_id": "prereg_001", "prereg_sha256": governance.sha256_hex(b"documento"), "signer": "Jhonson Gil",
            "git_commit_base": "a" * 40, "signed_at": T_PREREG}
    for patch in ({"prereg_sha256": h("otro")}, {"signer": " "}, {"git_commit_base": "abc"}, {"signed_at": "2026-01-02"},
                  {"prereg_id": "../evil"}, {"prereg_id": "no_existe"}):
        with pytest.raises(GovernanceError):
            register_entry(ledger, "PREREG_SIGNED", {**good, **patch}, T_PREREG, root)
    register_entry(ledger, "PREREG_SIGNED", good, T_PREREG, root)
    with pytest.raises(GovernanceError, match="ya está firmado"):
        register_entry(ledger, "PREREG_SIGNED", good, T_SNAPSHOT, root)


def test_snapshot_and_base_and_calibrator_require_their_predecessors_and_matching_hashes(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    models_dir = tmp_path / "models"
    base = fake_base(models_dir)
    manifest = make_manifest(base=base)
    with pytest.raises(GovernanceError, match="preregistro firmado"):
        freeze_snapshot(ledger, root, manifest)  # sin preregistro
    sign_prereg(ledger, root)
    with pytest.raises(GovernanceError, match="SNAPSHOT_FROZEN coincidente"):
        record_base(ledger, root, manifest, models_dir)  # sin snapshot
    freeze_snapshot(ledger, root, manifest)
    with pytest.raises(GovernanceError, match="ya tiene un snapshot"):
        freeze_snapshot(ledger, root, manifest)
    with pytest.raises(GovernanceError, match="base registrado"):
        record_calibrator(ledger, root, manifest, models_dir)  # sin modelo base

    wrong = {
        "attempt_id": "attempt_001", "snapshot_id": manifest["snapshot_id"], "prereg_id": manifest["prereg_id"],
        "base_model_version": manifest["base_model_version"], "base_artifact_sha256": h("otro"),
        "base_metadata_sha256": manifest["base_metadata_sha256"], "trained_at": T_TRAINED,
    }
    with pytest.raises(ManifestError, match="discrepan"):
        register_entry(ledger, "BASE_TRAINED", wrong, T_RECORDED, root, models_dir)
    record_base(ledger, root, manifest, models_dir)
    with pytest.raises(GovernanceError, match="ya tiene un modelo base"):
        record_base(ledger, root, manifest, models_dir)
    record_calibrator(ledger, root, manifest, models_dir)
    with pytest.raises(GovernanceError, match="ya tiene un calibrador"):
        record_calibrator(ledger, root, manifest, models_dir, cal_tag="cal2")


def test_snapshot_registration_enforces_manifest_hash_location_and_novelty(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    sign_prereg(ledger, root)
    first = make_manifest(364, cutoff="2026-02-01T00:00:00+00:00", db_tag="db1")
    freeze_snapshot(ledger, root, first, "attempt_001")
    register_entry(
        ledger, "ATTEMPT_ABANDONED",
        {"attempt_id": "attempt_001", "reason": "cierre de prueba", "author": "Jhonson Gil", "abandoned_at": "2026-02-10T00:00:00+00:00"},
        "2026-02-10T00:00:00+00:00", root,
    )
    later = "2026-03-10T00:00:00+00:00"

    poor = make_manifest(400, cutoff="2026-03-01T00:00:00+00:00", db_tag="db2")  # solo 36 nuevos
    with pytest.raises(AttemptNotAllowedError, match="no se permite repetir"):
        freeze_snapshot(ledger, root, poor, "attempt_002", recorded_at=later)
    good = make_manifest(520, cutoff="2026-03-01T00:00:00+00:00", db_tag="db3")  # 156 nuevos
    rel, sha = write_manifest(root, good)
    base_payload = {"attempt_id": "attempt_003", "snapshot_id": good["snapshot_id"], "prereg_id": good["prereg_id"],
                    "manifest_path": rel, "manifest_sha256": sha, "db_sha256": good["db_sha256"], "cutoff_utc": good["cutoff_utc"]}
    for patch in ({"manifest_sha256": h("otro")}, {"manifest_path": "../../etc/passwd"}, {"db_sha256": h("falso")},
                  {"manifest_path": "governance/calibration/snapshots/../ledger.jsonl"}):
        with pytest.raises(GovernanceError):
            register_entry(ledger, "SNAPSHOT_FROZEN", {**base_payload, **patch}, later, root)
    register_entry(ledger, "SNAPSHOT_FROZEN", base_payload, later, root)


def test_verdict_and_test_entries_cannot_be_registered_by_hand(tmp_path):
    ledger = ledger_in(tmp_path)
    for entry_type in ("PHASE1_VERDICT", "TEST_READ", "TEST_RESULT", "FINAL_VERDICT"):
        with pytest.raises(GovernanceError, match="solo puede emitirlo"):
            register_entry(ledger, entry_type, {"attempt_id": "a"}, T_PREREG, tmp_path)


# =====================================================================
# Lectura única del test y veredicto completo
# =====================================================================


def _provider(metrics, ledger=None, record=None):
    calls = []

    def provider():
        if ledger is not None:
            record.append([e["type"] for e in read_ledger(ledger)])  # qué hay en el libro al LEER el test
        calls.append(1)
        return metrics

    provider.calls = calls
    return provider


GOOD_TEST = SplitMetrics(0.08, 0.05, 0.20, 0.19, 40)


def _types(ledger):
    return [e["type"] for e in read_ledger(ledger)]


def test_eligible_candidate_reads_the_test_once_and_ends_eligible(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    seen: list = []
    provider = _provider(GOOD_TEST, ledger, seen)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))

    result = evaluate_attempt(ledger, "attempt_001", manifest, metrics, provider, T_EVALUATED)

    assert result.verdict == Verdict.ELEGIBLE and len(provider.calls) == 1
    assert _types(ledger)[-4:] == ["PHASE1_VERDICT", "TEST_READ", "TEST_RESULT", "FINAL_VERDICT"]
    assert "TEST_READ" in seen[0]  # escritura previa: TEST_READ ya estaba en el libro al leer el test
    assert entries_of(read_ledger(ledger), "PHASE1_VERDICT")[0]["payload"]["verdict"] == "ELEGIBLE_PRELIMINAR"
    assert entries_of(read_ledger(ledger), "FINAL_VERDICT")[0]["payload"]["verdict"] == "ELEGIBLE"


@pytest.mark.parametrize(
    "calibrator_metrics,expected",
    [
        (dict(raw_ece=0.08, calibrated_ece=0.08, raw_brier=0.20, calibrated_brier=0.20), Verdict.INCONCLUSO),  # efecto nulo
        (dict(raw_ece=0.08, calibrated_ece=0.09, raw_brier=0.20, calibrated_brier=0.19), Verdict.RECHAZADO),   # deterioro
        (dict(raw_ece=0.08, calibrated_ece=0.05, raw_brier=0.20, calibrated_brier=0.19, n_events=29), None),   # n inconsistente
    ],
)
def test_test_is_never_read_when_phase1_is_not_preliminary_eligible(tmp_path, calibrator_metrics, expected):
    root, ledger, manifest, models_dir = build_attempt(tmp_path, **calibrator_metrics)
    entry = entries_of(read_ledger(ledger), "CALIBRATOR_TRAINED")[0]["payload"]
    metrics = SplitMetrics(entry["raw_ece"], entry["calibrated_ece_oof"], entry["raw_brier"], entry["calibrated_brier_oof"],
                           entry["n_calibration_events"])
    provider = _provider(GOOD_TEST)  # un test espléndido que NO debe rescatar nada

    result = evaluate_attempt(ledger, "attempt_001", manifest, metrics, provider, T_EVALUATED)

    assert provider.calls == []
    assert "TEST_READ" not in _types(ledger)
    final = entries_of(read_ledger(ledger), "FINAL_VERDICT")[0]["payload"]["verdict"]
    assert final == result.verdict.value
    if expected is not None:
        assert result.verdict == expected
    else:
        assert result.verdict == Verdict.ERROR  # n_validation distinto de los validation_event_ids del manifiesto


def test_veto_can_downgrade_but_never_elevate(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    bad_test = SplitMetrics(0.08, 0.10, 0.20, 0.19, 40)  # el test empeora el ECE más que tau
    result = evaluate_attempt(ledger, "attempt_001", manifest, metrics, _provider(bad_test), T_EVALUATED)
    assert result.verdict == Verdict.RECHAZADO


def test_test_with_fewer_than_30_events_is_inconclusive(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    result = evaluate_attempt(ledger, "attempt_001", manifest, metrics, _provider(SplitMetrics(0.08, 0.05, 0.20, 0.19, 29)), T_EVALUATED)
    assert result.verdict == Verdict.INCONCLUSO


def test_an_attempt_cannot_be_evaluated_twice(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    provider = _provider(GOOD_TEST)
    evaluate_attempt(ledger, "attempt_001", manifest, metrics, provider, T_EVALUATED)
    with pytest.raises(AttemptNotAllowedError, match="ya fue evaluado"):
        evaluate_attempt(ledger, "attempt_001", manifest, metrics, provider, T_EVALUATED)
    assert len(provider.calls) == 1  # el test no se vuelve a leer


def test_the_test_of_the_same_base_cannot_be_read_again_even_from_another_path(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    evaluate_attempt(ledger, "attempt_001", manifest, metrics, _provider(GOOD_TEST), T_EVALUATED)
    base_sha = manifest["base_artifact_sha256"]
    # un segundo PHASE1 elegible fabricado para otro intento NO reabre el test de ese modelo base
    governance._append_entry(ledger, "PHASE1_VERDICT", {"attempt_id": "attempt_002", "verdict": "ELEGIBLE_PRELIMINAR", "reason": "x"}, T_EVALUATED)
    with pytest.raises(HeldOutAlreadyReadError):
        read_held_out_once(ledger, "attempt_002", base_sha, manifest["test_event_ids_sha256"], _provider(GOOD_TEST), T_EVALUATED)


def test_direct_read_is_refused_without_an_eligible_preliminary(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    provider = _provider(GOOD_TEST)
    with pytest.raises(HeldOutReadError):  # ni siquiera hay PHASE1
        read_held_out_once(ledger, "attempt_001", manifest["base_artifact_sha256"], manifest["test_event_ids_sha256"], provider, T_EVALUATED)
    governance._append_entry(ledger, "PHASE1_VERDICT", {"attempt_id": "attempt_001", "verdict": "INCONCLUSO", "reason": "x"}, T_EVALUATED)
    with pytest.raises(HeldOutReadError):
        read_held_out_once(ledger, "attempt_001", manifest["base_artifact_sha256"], manifest["test_event_ids_sha256"], provider, T_EVALUATED)
    assert provider.calls == []


def test_an_interrupted_read_is_consumed_and_cannot_be_repeated(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))

    def exploding():
        raise RuntimeError("fallo a mitad de la lectura")

    result = evaluate_attempt(ledger, "attempt_001", manifest, metrics, exploding, T_EVALUATED)

    assert result.verdict == Verdict.ERROR
    types = _types(ledger)
    assert types[-4:] == ["PHASE1_VERDICT", "TEST_READ", "TEST_RESULT", "FINAL_VERDICT"]
    assert entries_of(read_ledger(ledger), "TEST_RESULT")[0]["payload"]["status"] == "ERROR"
    with pytest.raises(HeldOutAlreadyReadError):
        read_held_out_once(ledger, "attempt_001", manifest["base_artifact_sha256"], manifest["test_event_ids_sha256"], _provider(GOOD_TEST), T_EVALUATED)


def test_a_crash_between_test_read_and_test_result_still_blocks_a_second_read(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    governance._append_entry(ledger, "PHASE1_VERDICT", {"attempt_id": "attempt_001", "verdict": "ELEGIBLE_PRELIMINAR", "reason": "x"}, T_EVALUATED)
    governance._append_entry(ledger, "TEST_READ", {"attempt_id": "attempt_001", "base_artifact_sha256": manifest["base_artifact_sha256"],
                                       "test_event_ids_sha256": manifest["test_event_ids_sha256"]}, T_EVALUATED)
    # (proceso interrumpido: no hay TEST_RESULT)
    provider = _provider(GOOD_TEST)
    with pytest.raises(HeldOutAlreadyReadError):
        read_held_out_once(ledger, "attempt_001", manifest["base_artifact_sha256"], manifest["test_event_ids_sha256"], provider, T_EVALUATED)
    assert provider.calls == []


def test_inconsistencies_produce_the_error_verdict_and_never_read_the_test(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    provider = _provider(GOOD_TEST)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    other = make_manifest(base_tag="otro_modelo")  # hashes del modelo base distintos a los del libro
    result = evaluate_attempt(ledger, "attempt_001", other, metrics, provider, T_EVALUATED)
    assert result.verdict == Verdict.ERROR and provider.calls == []
    assert "TEST_READ" not in _types(ledger)


def test_metrics_that_do_not_match_the_ledger_are_error(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    provider = _provider(GOOD_TEST)
    tampered = SplitMetrics(0.08, 0.001, 0.20, 0.001, len(manifest["validation_event_ids"]))  # "mejores" que lo registrado
    result = evaluate_attempt(ledger, "attempt_001", manifest, tampered, provider, T_EVALUATED)
    assert result.verdict == Verdict.ERROR and provider.calls == []


def test_a_tampered_ledger_blocks_evaluation_without_writing(tmp_path):
    root, ledger, manifest, models_dir = build_attempt(tmp_path)
    lines = ledger.read_text().splitlines()
    lines[0] = lines[0].replace("Jhonson Gil", "Otra Persona")
    ledger.write_text("\n".join(lines) + "\n")
    before = ledger.read_bytes()
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    with pytest.raises(LedgerIntegrityError):
        evaluate_attempt(ledger, "attempt_001", manifest, metrics, _provider(GOOD_TEST), T_EVALUATED)
    assert ledger.read_bytes() == before


def test_attempt_without_complete_ledger_entries_is_refused(tmp_path):
    root = make_repo(tmp_path)
    ledger = root / "governance" / "calibration" / "ledger.jsonl"
    manifest = make_manifest()
    sign_prereg(ledger, root)
    freeze_snapshot(ledger, root, manifest)
    metrics = SplitMetrics(0.08, 0.05, 0.20, 0.19, len(manifest["validation_event_ids"]))
    with pytest.raises(GovernanceError, match="exactamente un SNAPSHOT_FROZEN"):
        evaluate_attempt(ledger, "attempt_001", manifest, metrics, _provider(GOOD_TEST), T_EVALUATED)


# =====================================================================
# Propiedades estructurales
# =====================================================================


def test_calibrator_training_never_touches_the_test_partition():
    source = Path("src/calibration/tennis_calibrator_training.py").read_text(encoding="utf-8")
    assert "test_event_ids" not in source and "test_samples" not in source and "split_events_temporally" not in source


def test_governance_and_verdict_modules_do_not_read_the_clock():
    for module in (governance, verdict_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not called & {"now", "utcnow", "today"}


def test_governance_module_never_imports_the_production_registry_or_dumps_artifacts():
    tree = ast.parse(Path(governance.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not imported & {"load_model_registry", "DEFAULT_MODEL_REGISTRY_PATH", "RegistryStatus", "ModelRegistryPolicy"}
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"dump", "dumps_to_registry"}
