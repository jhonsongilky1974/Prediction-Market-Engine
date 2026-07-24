#!/usr/bin/env python3
"""Test end-to-end REAL, read-only, para Fase 1: MLB + tenis (ATP/WTA).

Ejecuta ambos pipelines contra las APIs reales (sin mocks), guarda RAW +
normalizado en `data/`, y muestra la tabla resumen pedida en las
instrucciones de Fase 1:

    SOURCE | DATA FETCHED | NORMALIZED | MATCHED | MISSING | WARNINGS

Nota de arquitectura: este script vive en `scripts/` (no en `tests/`)
porque su propósito es producir un reporte legible por humanos, no un
pass/fail de pytest. El equivalente automatizado (pass/fail) está en
`tests/integration/test_e2e_real.py`.

Uso:
    source .venv/bin/activate
    python scripts/run_e2e.py [--mlb-date YYYY-MM-DD] [--tennis-date YYYYMMDD] [--tour atp|wta]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.mlb_pipeline import PipelineStepResult, run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository


def _print_table(rows: List[dict]) -> None:
    headers = ["SOURCE", "DATA FETCHED", "NORMALIZED", "MATCHED", "MISSING", "WARNINGS"]
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row.get(h, ""))))

    def fmt_row(values):
        return " | ".join(str(values.get(h, "")).ljust(widths[h]) for h in headers)

    print(fmt_row({h: h for h in headers}))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print(fmt_row(row))


def _steps_to_rows(steps: List[PipelineStepResult]) -> List[dict]:
    by_source = {}
    for s in steps:
        entry = by_source.setdefault(s.source, {"fetched": 0, "failed": 0, "errors": []})
        if s.ok:
            entry["fetched"] += 1
        else:
            entry["failed"] += 1
            entry["errors"].append(f"{s.step}: {s.error}")
    rows = []
    for source, info in by_source.items():
        rows.append(
            {
                "SOURCE": source,
                "DATA FETCHED": f"{info['fetched']} ok / {info['failed']} fail",
                "NORMALIZED": "-",
                "MATCHED": "-",
                "MISSING": "-",
                "WARNINGS": "; ".join(info["errors"][:2]) if info["errors"] else "",
            }
        )
    return rows


def _find_next_mlb_date_with_games() -> str:
    from src.connectors.mlb import MlbConnector

    mlb = MlbConnector()
    d = date.today()
    for i in range(10):
        candidate = (d + timedelta(days=i)).isoformat()
        result = mlb.get_schedule(candidate)
        if result.ok and MlbConnector.extract_games(result.data):
            return candidate
    return date.today().isoformat()


def _find_next_tennis_date_with_matches(tour: str) -> str:
    from src.connectors.espn_tennis import EspnTennisConnector

    espn = EspnTennisConnector()
    d = date.today()
    for i in range(10):
        candidate = (d + timedelta(days=i)).strftime("%Y%m%d")
        result = espn.get_scoreboard(tour.lower(), candidate)
        if result.ok and EspnTennisConnector.extract_matches(result.data):
            return candidate
    return date.today().strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlb-date", default=None, help="YYYY-MM-DD (default: próximo día con juegos)")
    parser.add_argument("--tennis-date", default=None, help="YYYYMMDD (default: próximo día con partidos)")
    parser.add_argument("--tour", default="atp", choices=["atp", "wta"])
    args = parser.parse_args()

    repo = Repository()
    # Paso 0d: mismo archivo SQLite que `repo` (ver PLAN_PHASE2.md §11) --
    # cada corrida real de este script pasa a dejar snapshot histórico,
    # además del estado actual que ya guardaba `repo`.
    hist_repo = HistoryRepository()

    mlb_date = args.mlb_date or _find_next_mlb_date_with_games()
    print(f"\n=== MLB end-to-end: date={mlb_date} ===")
    mlb_result = run_mlb_pipeline(mlb_date, repository=repo, history_repository=hist_repo, limit=1)
    for step in mlb_result.steps:
        status = "OK" if step.ok else f"FAIL ({step.error})"
        print(f"  [{step.source}] {step.step}: {status}" + (f" count={step.count}" if step.ok else ""))

    print("\n  Registro(s) normalizado(s):")
    for r in mlb_result.records:
        print(f"    {r.participant_a} vs {r.participant_b} | status={r.status.value} | start={r.start_time}")
        print(f"    market_id={r.market_id} yes_bid={r.market.yes_bid} yes_ask={r.market.yes_ask}")
        print(
            f"    match_confidence={r.data_quality.match_confidence} "
            f"method={r.data_quality.match_method} needs_review={r.data_quality.needs_review}"
        )
        print(f"    completeness={r.data_quality.data_completeness_score}")
        print(f"    missing_fields ({len(r.data_quality.missing_fields)}): {r.data_quality.missing_fields}")
        print(f"    match_warnings: {r.data_quality.match_warnings}")
        print(f"    validation_errors: {r.data_quality.validation_errors}")

    tennis_date = args.tennis_date or _find_next_tennis_date_with_matches(args.tour)
    print(f"\n=== TENIS end-to-end: tour={args.tour.upper()} date={tennis_date} ===")
    tennis_result = run_tennis_pipeline(args.tour, tennis_date, repository=repo, history_repository=hist_repo, limit=5)
    for step in tennis_result.steps:
        status = "OK" if step.ok else f"FAIL ({step.error})"
        print(f"  [{step.source}] {step.step}: {status}" + (f" count={step.count}" if step.ok else ""))

    print("\n  Registro(s) normalizado(s) (hasta 5):")
    for r in tennis_result.records:
        print(f"    {r.participant_a} vs {r.participant_b} | status={r.status.value} | start={r.start_time}")
        print(f"    market_id={r.market_id} yes_bid={r.market.yes_bid} yes_ask={r.market.yes_ask}")
        print(
            f"    match_confidence={r.data_quality.match_confidence} "
            f"method={r.data_quality.match_method} needs_review={r.data_quality.needs_review}"
        )
        print(f"    completeness={r.data_quality.data_completeness_score}")
        print(f"    missing_fields ({len(r.data_quality.missing_fields)}): (omitido, ver DB/raw)")
        print(f"    match_warnings: {r.data_quality.match_warnings}")

    print("\n=== TABLA RESUMEN ===\n")

    def summarize(sport_label, steps, records):
        rows = _steps_to_rows(steps)
        for row in rows:
            row["SOURCE"] = f"{sport_label}:{row['SOURCE']}"
        normalized = len(records)
        matched = sum(1 for r in records if r.market_id is not None)
        missing_total = sum(len(r.data_quality.missing_fields) for r in records)
        warnings_sample = []
        for r in records:
            warnings_sample.extend(r.data_quality.match_warnings)
        for row in rows:
            row["NORMALIZED"] = normalized
            row["MATCHED"] = matched
            row["MISSING"] = missing_total
            if warnings_sample and not row["WARNINGS"]:
                row["WARNINGS"] = warnings_sample[0][:60]
        return rows

    summary_rows = summarize("MLB", mlb_result.steps, mlb_result.records) + summarize(
        "TENNIS", tennis_result.steps, tennis_result.records
    )
    _print_table(summary_rows)

    print(f"\nDB: {repo.db_path}")
    print(f"RAW dir: {repo.raw_dir}")
    print(f"History DB (event_snapshots): {hist_repo.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
