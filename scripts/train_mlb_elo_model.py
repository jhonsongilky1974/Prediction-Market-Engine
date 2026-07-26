#!/usr/bin/env python3
"""Calcula (o intenta calcular) los ratings Elo del baseline MLB contra el
histórico real de `HistoryRepository` (Paso 6).

Invocación MANUAL únicamente -- no está conectada a ningún LaunchAgent ni
automatización (misma disciplina ya aplicada a
`scripts/train_mlb_model.py`/`scripts/sync_mlb_results.py`).

Sin lock de instancia única: solo LEE `HistoryRepository` y escribe un
artefacto nuevo con `model_version` único (con timestamp) en
`data/models/` -- dos corridas simultáneas no colisionan en el mismo
archivo.

Comportamiento honesto por diseño: si la secuencia de partidos no alcanza
`min_games`, el script termina con éxito (exit 0) reportando
`INSUFFICIENT_HISTORY` -- nunca fabrica ratings.

Uso:
    source .venv/bin/activate
    python scripts/train_mlb_elo_model.py [--min-games 50] [--k 20] [--home-advantage 25]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.base import ModelStatus
from src.models.mlb_elo import (
    DEFAULT_HOME_ADVANTAGE,
    DEFAULT_INITIAL_RATING,
    DEFAULT_K,
    DEFAULT_MIN_GAMES,
    train_mlb_elo_model,
)
from src.storage.history_repository import HistoryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--k", type=float, default=DEFAULT_K)
    parser.add_argument("--home-advantage", type=float, default=DEFAULT_HOME_ADVANTAGE)
    parser.add_argument("--initial-rating", type=float, default=DEFAULT_INITIAL_RATING)
    args = parser.parse_args()

    hist = HistoryRepository()
    print(f"History DB: {hist.db_path}")
    print(
        f"Calculando ratings Elo MLB (min_games={args.min_games}, k={args.k}, "
        f"home_advantage={args.home_advantage}, initial_rating={args.initial_rating})..."
    )

    status, artifact, warnings = train_mlb_elo_model(
        hist,
        min_games=args.min_games,
        k=args.k,
        home_advantage=args.home_advantage,
        initial_rating=args.initial_rating,
    )

    print(f"\nmodel_status: {status.value}")
    for w in warnings:
        print(f"  aviso: {w}")

    if status != ModelStatus.TRAINED or artifact is None:
        print("\nNingún rating calculado -- histórico de partidos insuficiente todavía.")
        return 0

    print(f"\nmodel_version: {artifact.model_version}")
    print(f"partidos usados: {artifact.n_games}")
    print(f"equipos con rating: {len(artifact.team_ratings)}")
    top5 = sorted(artifact.team_ratings.items(), key=lambda kv: kv[1], reverse=True)[:5]
    print("top 5 ratings:", top5)
    print(f"artefacto: {artifact.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
