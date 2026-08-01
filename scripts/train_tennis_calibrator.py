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

Uso:
    source .venv/bin/activate
    python scripts/train_tennis_calibrator.py [--cv-folds 5] [--models-dir data/models]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_MODELS_DIR
from src.calibration.tennis_calibrator_training import DEFAULT_CV_FOLDS, train_tennis_calibrator
from src.models.base import ModelStatus
from src.storage.history_repository import HistoryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cv-folds", type=int, default=DEFAULT_CV_FOLDS)
    parser.add_argument("--models-dir", type=Path, default=DATA_MODELS_DIR)
    args = parser.parse_args()

    hist = HistoryRepository()
    print(f"History DB: {hist.db_path}")
    print(f"Ajustando calibrador Platt de tenis (cv_folds={args.cv_folds})...")

    status, artifact, warnings = train_tennis_calibrator(hist, models_dir=args.models_dir, cv_folds=args.cv_folds)

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

    if artifact.calibrated_ece_oof is not None and artifact.raw_ece is not None:
        if artifact.calibrated_ece_oof <= artifact.raw_ece:
            print("\nCriterio de aceptación (CALIBRATION_SPEC.md §6): calibrated_ece_oof <= raw_ece -- CUMPLIDO.")
        else:
            print(
                "\nCriterio de aceptación (CALIBRATION_SPEC.md §6): calibrated_ece_oof > raw_ece -- "
                "NO CUMPLIDO. El artefacto se persistió como evidencia, pero NO debe cablearse en "
                "producción sin instrucción explícita."
            )

    print(f"\nartifact_sha256: {artifact.artifact_sha256}")
    print(f"artefacto: {artifact.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
