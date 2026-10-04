#!/usr/bin/env python3
"""Evaluación gobernada del calibrador de tenis (CONTINUITY.md §0.42; contrato en
`governance/calibration/README.md`). NO entrena, NO promueve, NO cablea y NO toca
`config/model_registry.json` ni el registro de producción.

SEGURIDAD: este script NO deserializa joblib/pickle. Un SHA-256 confirma la identidad de los
bytes, no su seguridad, procedencia, calidad ni validez estadística. Si la evaluación requiriera
deserializar un artefacto (el veto del test de un candidato ELEGIBLE_PRELIMINAR), se DETIENE con
un error explícito y no escribe nada en el libro: no existe todavía un mecanismo separado y
auditado de carga segura ni almacenamiento duradero. El entrenamiento y la evaluación real
siguen BLOQUEADOS.

Subcomandos:
    verify-ledger  verifica la cadena de hashes, los archivos registrados y el ANCLA: el libro
                   propuesto debe extender byte a byte el aceptado en `main`/`origin/main`
    register       añade al libro una entrada PREREG_SIGNED / SNAPSHOT_FROZEN / BASE_TRAINED /
                   CALIBRATOR_TRAINED / ATTEMPT_ABANDONED tras verificar sus invariantes
                   (BASE_TRAINED y CALIBRATOR_TRAINED exigen --models-dir explícito)
    evaluate       evalúa UN intento solo si verify-ledger valida la cadena y el prefijo contra la
                   base y el preregistro, snapshot, modelo base y calibrador del intento YA están
                   aceptados en `main`; sin base verificable falla cerrado

Toda entrada del libro (y todo preregistro firmado) se incorpora a `main` mediante PR revisable.

Códigos de salida: 0 veredicto emitido (ELEGIBLE/INCONCLUSO/RECHAZADO) o verificación correcta;
1 veredicto ERROR; 2 violación de la gobernanza o argumento/archivo inválido (fail-closed).

Uso (manual, nunca desde un LaunchAgent):
    source .venv/bin/activate
    python scripts/evaluate_tennis_calibrator.py verify-ledger [--base-ref origin/main]
    python scripts/evaluate_tennis_calibrator.py register --type TYPE --payload FILE.json --recorded-at ISO [--models-dir DIR]
    python scripts/evaluate_tennis_calibrator.py evaluate --attempt-id ID --db-copy PATH --models-dir DIR --recorded-at ISO
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT
from src.evaluation.calibration_governance import (
    ACCEPTED_BASE_REFS,
    DEFAULT_LEDGER_PATH,
    AttemptNotAllowedError,
    GovernanceError,
    ids_sha256,
    entries_of,
    evaluate_attempt,
    load_registered_manifest,
    register_entry,
    require_attempt_accepted_in_base,
    sha256_file,
    verify_attempt_artifacts,
    verify_against_base,
)
from src.evaluation.calibration_verdict import SplitMetrics, Verdict
from src.models.tennis_baseline import build_tennis_training_dataset, split_events_temporally
from src.storage.history_repository import HistoryRepository

NEEDS_MODELS_DIR = ("BASE_TRAINED", "CALIBRATOR_TRAINED")


def run_verify_ledger(
    ledger: Path, repo_root: Path, base_ref: str = "origin/main", allowed_refs: Sequence[str] = ACCEPTED_BASE_REFS
) -> int:
    try:
        verification = verify_against_base(ledger, repo_root, base_ref, allowed_refs)
    except GovernanceError as exc:
        print(f"ERROR (fail-closed): {exc}", file=sys.stderr)
        return 2
    print(
        f"libro íntegro: {verification.total_entries} entrada(s); {verification.base_entries} aceptada(s) en "
        f"{verification.base_ref} ({verification.base_commit[:12]}), {verification.total_entries - verification.base_entries} nueva(s)"
    )
    print(f"cabecera aceptada: seq={verification.base_head_seq} entry_sha256={verification.base_head_sha256}")
    print(f"cabecera propuesta: seq={verification.head_seq} entry_sha256={verification.head_sha256}")
    return 0


def run_register(
    ledger: Path, entry_type: str, payload_file: Path, recorded_at: str, repo_root: Path, models_dir: Optional[Path] = None
) -> int:
    try:
        if entry_type in NEEDS_MODELS_DIR and models_dir is None:
            raise GovernanceError(f"{entry_type} exige --models-dir explícito")
        payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        entry = register_entry(ledger, entry_type, payload, recorded_at, repo_root, models_dir)
    except (OSError, ValueError, GovernanceError) as exc:
        print(f"ERROR (fail-closed): {exc}", file=sys.stderr)
        return 2
    print(f"registrada seq={entry['seq']} type={entry['type']} entry_sha256={entry['entry_sha256']}")
    return 0


def run_evaluate(
    ledger: Path,
    attempt_id: str,
    db_copy: Path,
    models_dir: Optional[Path],
    recorded_at: str,
    repo_root: Path,
    base_ref: str = "origin/main",
    allowed_refs: Sequence[str] = ACCEPTED_BASE_REFS,
) -> int:
    try:
        # --- verificaciones previas: ninguna escribe en el libro ---
        verification = verify_against_base(ledger, repo_root, base_ref, allowed_refs)
        accepted = require_attempt_accepted_in_base(verification, attempt_id)
        entries = list(verification.entries)
        if entries_of(entries, "ATTEMPT_ABANDONED", attempt_id=attempt_id) or entries_of(entries, "FINAL_VERDICT", attempt_id=attempt_id):
            raise AttemptNotAllowedError("el intento ya terminó (FINAL_VERDICT o ATTEMPT_ABANDONED)")
        manifest = load_registered_manifest(repo_root, accepted["snapshot"])
        verify_attempt_artifacts(entries, manifest, models_dir, attempt_id)  # hashes + trained_at + métricas (sin deserializar)
        if sha256_file(db_copy) != manifest["db_sha256"]:
            raise GovernanceError("el SHA-256 de la copia de la base no coincide con el manifiesto")
        dataset = build_tennis_training_dataset(HistoryRepository(db_path=db_copy))
        if sha256_file(db_copy) != manifest["db_sha256"]:
            raise GovernanceError("la copia congelada de la base se modificó durante la lectura")
        if ids_sha256(sorted({s.event_id for s in dataset.samples})) != manifest["labeled_event_ids_sha256"]:
            raise GovernanceError("los event_ids reconstruidos desde la copia no coinciden con el manifiesto")
        _, validation, test = split_events_temporally(dataset)
        if ids_sha256(sorted(s.event_id for s in validation.samples)) != manifest["validation_event_ids_sha256"]:
            raise GovernanceError("la partición de validación reconstruida no coincide con el manifiesto")
        if ids_sha256(sorted(s.event_id for s in test.samples)) != manifest["test_event_ids_sha256"]:
            raise GovernanceError("la partición de test reconstruida no coincide con el manifiesto")
        cal = accepted["calibrator"]["payload"]
        validation_metrics = SplitMetrics(
            raw_ece=cal["raw_ece"], calibrated_ece=cal["calibrated_ece_oof"], raw_brier=cal["raw_brier"],
            calibrated_brier=cal["calibrated_brier_oof"], n_events=cal["n_calibration_events"],
        )
        # Sin proveedor de test: si la fase 1 diera ELEGIBLE_PRELIMINAR, evaluate_attempt lanza
        # SafeLoadRequiredError ANTES de escribir nada (no se deserializa ningún artefacto).
        result = evaluate_attempt(
            ledger, attempt_id, manifest, validation_metrics, None, recorded_at, allow_test_read=False
        )
    except (OSError, ValueError, GovernanceError) as exc:
        print(f"ERROR (fail-closed; nada se escribió en el libro por esta causa): {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"attempt_id": attempt_id, "verdict": result.verdict.value, "reason": result.reason}, ensure_ascii=False))
    print(
        "El veredicto no promueve ni cablea nada. Recordatorio: SHA-256 confirma identidad de bytes, no seguridad, "
        "procedencia, calidad ni validez estadística."
    )
    return 1 if result.verdict == Verdict.ERROR else 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify-ledger", "register", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
        p.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
        if name in ("verify-ledger", "evaluate"):
            p.add_argument("--base-ref", default="origin/main", choices=list(ACCEPTED_BASE_REFS))
        if name == "register":
            p.add_argument("--type", required=True, dest="entry_type")
            p.add_argument("--payload", required=True, type=Path)
            p.add_argument("--recorded-at", required=True)
            p.add_argument("--models-dir", type=Path, default=None)
        if name == "evaluate":
            p.add_argument("--attempt-id", required=True)
            p.add_argument("--db-copy", required=True, type=Path)
            p.add_argument("--models-dir", type=Path, required=True)
            p.add_argument("--recorded-at", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-ledger":
        return run_verify_ledger(args.ledger, args.repo_root, args.base_ref)
    if args.command == "register":
        return run_register(args.ledger, args.entry_type, args.payload, args.recorded_at, args.repo_root, args.models_dir)
    return run_evaluate(
        args.ledger, args.attempt_id, args.db_copy, args.models_dir, args.recorded_at, args.repo_root, args.base_ref
    )


if __name__ == "__main__":
    sys.exit(main())
