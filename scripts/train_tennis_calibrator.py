#!/usr/bin/env python3
"""Ajusta (Platt scaling) y persiste un calibrador real para el modelo
base de tenis ya entrenado (calibración real, ver `CALIBRATION_SPEC.md`).
Mismo patrón exacto que `scripts/train_tennis_model.py` (Fase 4, Paso
4.3).

Invocación MANUAL únicamente -- no está conectado a ningún LaunchAgent.
Sin lock de instancia única: solo LEE `HistoryRepository` y
`data/models/`, y escribe un artefacto nuevo con nombre único
(`tennis_calibrator_platt_v1_<timestamp>`) -- dos corridas simultáneas no
colisionan en el mismo archivo.

Comportamiento honesto por diseño: si no hay modelo base entrenado, si
la validación no se puede verificar como libre de fuga respecto al
entrenamiento del modelo base, o si no hay suficientes eventos/clases
para la validación cruzada agrupada, el script termina con éxito
(exit 0) reportando el motivo -- nunca fabrica un calibrador.

Registro candidato (opcional, CONTINUITY.md §0.42): `--candidate-registry PATH`
permite calibrar un modelo base AÚN NO promovido, sin tocar
`config/model_registry.json`. El archivo debe vivir en
`governance/calibration/candidates/`, usar la clave `candidate_models` y declarar los
SHA-256 del modelo base, que se verifican contra los archivos y contra el libro
(`--ledger`). Cualquier discrepancia termina con código 2 (fail-closed). Sin la
opción, el script usa el registro real (hoy sin ningún modelo `ALLOWED`, por lo que
no ajusta nada). Este script NUNCA emite un veredicto ni promueve: el veredicto lo
emite `scripts/evaluate_tennis_calibrator.py`.

Uso:
    source .venv/bin/activate
    python scripts/train_tennis_calibrator.py [--cv-folds 5] [--models-dir data/models] \\
        [--candidate-registry governance/calibration/candidates/<id>.json] [--ledger governance/calibration/ledger.jsonl]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_MODELS_DIR
from src.calibration.tennis_calibrator_training import DEFAULT_CV_FOLDS, train_tennis_calibrator
from src.evaluation.calibration_governance import DEFAULT_LEDGER_PATH, GovernanceError
from src.evaluation.candidate_registry import load_candidate_registry
from src.models.base import ModelStatus
from src.storage.history_repository import HistoryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cv-folds", type=int, default=DEFAULT_CV_FOLDS)
    parser.add_argument("--models-dir", type=Path, default=DATA_MODELS_DIR)
    parser.add_argument(
        "--candidate-registry", type=Path, default=None,
        help="registro candidato explícito (clave candidate_models); sin él se usa el registro real de producción",
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    args = parser.parse_args()

    registry = None
    if args.candidate_registry is not None:
        try:
            registry = load_candidate_registry(args.candidate_registry, models_dir=args.models_dir, ledger_path=args.ledger)
        except GovernanceError as exc:
            print(f"ERROR (fail-closed): registro candidato rechazado -- {exc}", file=sys.stderr)
            return 2
        print(f"Registro candidato verificado: {args.candidate_registry}")

    hist = HistoryRepository()
    print(f"History DB: {hist.db_path}")
    print(f"Ajustando calibrador Platt de tenis (cv_folds={args.cv_folds})...")

    status, artifact, warnings = train_tennis_calibrator(
        hist, models_dir=args.models_dir, cv_folds=args.cv_folds, registry=registry
    )

    print(f"\nstatus: {status.value}")
    for w in warnings:
        print(f"  aviso: {w}")

    if status != ModelStatus.TRAINED or artifact is None:
        print("\nNingún calibrador ajustado.")
        return 0

    print(f"\ncalibrator_version: {artifact.calibrator_version}")
    print(f"calibration_method: {artifact.calibration_method}")
    print(f"base_model_version: {artifact.base_model_version}")
    print(f"n_calibration_samples: {artifact.n_calibration_samples} / n_calibration_events: {artifact.n_calibration_events}")
    print(f"cv_folds: {artifact.cv_folds}")
    print(f"\n--- Comparación honesta (misma validación, GroupKFold out-of-fold) ---")
    print(f"raw_ece (modelo SIN calibrar):        {artifact.raw_ece}")
    print(f"calibrated_ece_oof (Platt, OOF):       {artifact.calibrated_ece_oof}")
    print(f"raw_brier (modelo SIN calibrar):      {artifact.raw_brier}")
    print(f"calibrated_brier_oof (Platt, OOF):      {artifact.calibrated_brier_oof}")

    print(
        "\nEste script NO declara cumplido ni incumplido el criterio de aceptación: el veredicto "
        "(ERROR/INCONCLUSO/RECHAZADO/ELEGIBLE_PRELIMINAR/ELEGIBLE, tau=1e-4, test como veto único) "
        "lo emite scripts/evaluate_tennis_calibrator.py según governance/calibration/README.md. "
        "El artefacto se persiste solo como evidencia; no queda promovido ni cableado."
    )

    print(f"\nartifact_sha256: {artifact.artifact_sha256}")
    print(f"artefacto: {artifact.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
