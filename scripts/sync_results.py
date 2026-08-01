#!/usr/bin/env python3
"""Sincronización continua de `event_results` (Fase 4, Paso 4.0B -- D-4B).

Combina `sync_mlb_event_results`/`sync_tennis_event_results`
(`src/pipelines/mlb_results_sync.py`/`tennis_results_sync.py`, Fase 2,
sin cambios) en una sola invocación diaria, mismo patrón que
`scripts/data_maintenance.py`: lock de instancia única propio
(`data/.sync-results.lock`, `scripts/pipeline_lock.py`), sin compartir
lock con `run_e2e.py` ni con `data_maintenance.py` -- no requiere
coordinación con ninguno de los dos (mismas garantías de concurrencia
SQLite ya probadas en producción entre esos dos).

`--lookback-days=3` por defecto para ambos deportes -- el mismo default
ya usado y testeado en `sync_mlb_results.py`/`sync_tennis_results.py`
desde Fase 2 ("suficiente para capturar la resolución de la mayoría de
postergaciones sin escanear histórico ilimitado"), no un umbral nuevo
inventado para este paso. Tenis solo sincroniza ATP -- WTA nunca se
captura en producción (`run_e2e.py --tour` default `atp`, sin flag en el
`.plist` de captura), sincronizar WTA no tendría ningún `feature_snapshot`
con el que emparejarse.

READ-mostly, igual que los dos scripts que combina: el único efecto
secundario es `HistoryRepository.save_event_result` (append-only).

Uso:
    source .venv/bin/activate
    python scripts/sync_results.py [--mlb-lookback-days 3] [--tennis-lookback-days 3] [--tour atp]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROJECT_ROOT
from scripts.pipeline_lock import LockAcquisitionError, single_instance_lock
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.mlb import MlbConnector
from src.pipelines.mlb_results_sync import (
    MlbResultsSyncSummary,
    default_lookback_dates as mlb_default_lookback_dates,
    sync_mlb_event_results,
)
from src.pipelines.tennis_results_sync import (
    TennisResultsSyncSummary,
    default_lookback_dates as tennis_default_lookback_dates,
    sync_tennis_event_results,
)
from src.storage.history_repository import HistoryRepository

LOCK_PATH = PROJECT_ROOT / "data" / ".sync-results.lock"
# sysexits.h EX_TEMPFAIL -- mismo convenio que scripts/run_e2e.py y
# scripts/data_maintenance.py.
EXIT_ALREADY_RUNNING = 75

DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_TENNIS_TOUR = "atp"


def run_results_sync(
    hist: HistoryRepository,
    mlb: MlbConnector,
    espn: EspnTennisConnector,
    today: Optional[date] = None,
    mlb_lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tennis_lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tennis_tour: str = DEFAULT_TENNIS_TOUR,
) -> Dict[str, object]:
    """Orquestación pura salvo por las llamadas de red/DB que hacen
    `sync_mlb_event_results`/`sync_tennis_event_results` -- ninguna
    lógica nueva de negocio, solo secuenciar las dos funciones ya
    probadas de Fase 2 con dependencias inyectables (mismo patrón que
    `data_maintenance.run_maintenance`). `today` inyectable para
    reproducibilidad en tests -- si es `None`, cada función de lookback
    cae a `date.today()` real (igual que los dos scripts manuales que
    reemplaza)."""
    mlb_dates = mlb_default_lookback_dates(today=today, lookback_days=mlb_lookback_days)
    mlb_summary = sync_mlb_event_results(mlb, hist, mlb_dates)

    tennis_dates = tennis_default_lookback_dates(today=today, lookback_days=tennis_lookback_days)
    tennis_summary = sync_tennis_event_results(espn, hist, tennis_tour, tennis_dates)

    return {"mlb": mlb_summary, "tennis": tennis_summary}


def _print_mlb_summary(summary: MlbResultsSyncSummary) -> None:
    print(
        f"MLB -- registrados: {summary.recorded} (postergados: {summary.postponed}, "
        f"cancelados: {summary.cancelled}), ya registrados: {summary.already_recorded}, "
        f"aún no decididos: {summary.not_yet_decided}, ambiguos: {summary.skipped_ambiguous}"
    )
    if summary.fetch_errors:
        print(f"  Errores de fetch MLB: {summary.fetch_errors}")


def _print_tennis_summary(summary: TennisResultsSyncSummary) -> None:
    print(
        f"Tenis ({summary.tour}) -- registrados: {summary.recorded}, "
        f"ya registrados: {summary.already_recorded}, "
        f"aún no decididos: {summary.not_yet_decided}, ambiguos: {summary.skipped_ambiguous}"
    )
    if summary.fetch_errors:
        print(f"  Errores de fetch tenis: {summary.fetch_errors}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlb-lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--tennis-lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--tour", choices=["atp", "wta"], default=DEFAULT_TENNIS_TOUR)
    args = parser.parse_args()

    try:
        with single_instance_lock(LOCK_PATH):
            hist = HistoryRepository()
            summary = run_results_sync(
                hist=hist,
                mlb=MlbConnector(),
                espn=EspnTennisConnector(),
                mlb_lookback_days=args.mlb_lookback_days,
                tennis_lookback_days=args.tennis_lookback_days,
                tennis_tour=args.tour,
            )
    except LockAcquisitionError as exc:
        print(f"\n{exc}")
        print("Saliendo sin ejecutar sincronización de resultados.")
        return EXIT_ALREADY_RUNNING

    print(f"=== Sincronización de event_results completada ({datetime.now(timezone.utc).isoformat()}) ===")
    _print_mlb_summary(summary["mlb"])
    _print_tennis_summary(summary["tennis"])
    print(f"\nHistory DB: {hist.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
