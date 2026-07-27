#!/usr/bin/env python3
"""Sincroniza `event_results` de tenis contra `HistoryRepository` real
(Paso 11 -- mismo patrón que `scripts/sync_mlb_results.py`, Paso 5b
Bloque 3).

Invocación MANUAL únicamente -- no está conectado a ningún LaunchAgent ni
automatización todavía.

Uso:
    source .venv/bin/activate
    python scripts/sync_tennis_results.py --tour atp [--lookback-days 3]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connectors.espn_tennis import EspnTennisConnector
from src.pipelines.tennis_results_sync import default_lookback_dates, sync_tennis_event_results
from src.storage.history_repository import HistoryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tour", choices=["atp", "wta"], default="atp", help="Tour a sincronizar (default: atp).")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Cuántos días hacia atrás escanear, incluyendo hoy (default: 3).",
    )
    args = parser.parse_args()

    espn = EspnTennisConnector()
    hist = HistoryRepository()
    dates = default_lookback_dates(lookback_days=args.lookback_days)

    print(f"Sincronizando event_results de tenis ({args.tour.upper()}) para fechas: {dates}")
    summary = sync_tennis_event_results(espn, hist, args.tour, dates)

    print(f"\nRegistrados nuevos:                 {summary.recorded}")
    print(f"Ya registrados (sin duplicar):       {summary.already_recorded}")
    print(f"Aún no decididos:                    {summary.not_yet_decided}")
    print(f"Resultado ambiguo (omitido):         {summary.skipped_ambiguous}")
    if summary.fetch_errors:
        print(f"Errores de fetch: {summary.fetch_errors}")

    print(f"\nHistory DB: {hist.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
