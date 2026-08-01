#!/usr/bin/env python3
"""Entrena (o intenta entrenar) el modelo baseline de tenis contra el
histórico real de `HistoryRepository` (Fase 4, Paso 4.3 -- primer
modelo real del proyecto, ver `MODEL_TRAINING_SPEC.md`). Mismo patrón
exacto que `scripts/train_mlb_model.py` (Fase 2, Paso 5b, Bloque 5).

Invocación MANUAL únicamente -- no está conectado a ningún LaunchAgent ni
automatización todavía (misma disciplina ya aplicada a
`scripts/run_e2e.py`/`scripts/sync_mlb_results.py`).

Sin lock de instancia única: este script solo LEE `HistoryRepository`
(nunca escribe en `data/engine.db`) y escribe artefactos nuevos con
`model_version` único (con timestamp) en `data/models/` -- dos corridas
simultáneas no colisionan en el mismo archivo.

Comportamiento honesto por diseño: si el histórico etiquetado no alcanza
`min_samples`, el script termina con éxito (exit 0) reportando
`INSUFFICIENT_HISTORY` -- nunca fabrica un modelo.

Uso:
    source .venv/bin/activate
    python scripts/train_tennis_model.py [--min-samples 30] [--validation-fraction 0.2] [--models-dir data/models]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_MODELS_DIR
from src.models.base import ModelStatus
from src.models.tennis_baseline import (
    DEFAULT_MIN_TRAINING_SAMPLES_TENNIS,
    DEFAULT_VALIDATION_FRACTION,
    train_tennis_baseline_model,
)
from src.storage.history_repository import HistoryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_TRAINING_SAMPLES_TENNIS)
    parser.add_argument("--validation-fraction", type=float, default=DEFAULT_VALIDATION_FRACTION)
    parser.add_argument("--models-dir", type=Path, default=DATA_MODELS_DIR)
    args = parser.parse_args()

    hist = HistoryRepository()
    print(f"History DB: {hist.db_path}")
    print(f"Entrenando baseline de tenis (min_samples={args.min_samples}, validation_fraction={args.validation_fraction})...")

    status, artifact, warnings = train_tennis_baseline_model(
        hist, models_dir=args.models_dir, min_samples=args.min_samples, validation_fraction=args.validation_fraction
    )

    print(f"\nmodel_status: {status.value}")
    for w in warnings:
        print(f"  aviso: {w}")

    if status != ModelStatus.TRAINED or artifact is None:
        print("\nNingún modelo entrenado -- histórico etiquetado insuficiente todavía.")
        return 0

    print(f"\nmodel_version: {artifact.model_version}")
    print(f"feature_set_version: {artifact.feature_set_version}")
    print(f"muestras totales etiquetadas: {artifact.n_training_samples}")
    print(f"  train: {artifact.n_train_samples} muestras / {artifact.n_train_events} eventos distintos")
    print(f"  validation: {artifact.n_validation_samples} muestras / {artifact.n_validation_events} eventos distintos")
    print(f"accuracy (validation): {artifact.accuracy}")
    print(f"precision (validation): {artifact.precision}")
    print(f"recall (validation): {artifact.recall}")
    print(f"f1 (validation): {artifact.f1}")
    print(f"log_loss (validation): {artifact.log_loss}")
    print(f"brier_score (validation): {artifact.brier_score}")
    print(f"ece (validation, modelo SIN calibrar): {artifact.ece}")
    print(f"reliability_diagram: {artifact.reliability_diagram}")
    print(f"calibration_version: {artifact.calibration_version}  (None -- ningún Calibrator real existe todavía)")
    print(f"artifact_sha256: {artifact.artifact_sha256}")
    print(f"artefacto: {artifact.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
