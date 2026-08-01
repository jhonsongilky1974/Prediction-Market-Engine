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

from config.settings import PROJECT_ROOT
from scripts.pipeline_lock import LockAcquisitionError, single_instance_lock
from src.models.mlb_baseline import predict_mlb_baseline
from src.models.registry import load_latest_mlb_artifact
from src.models.schemas import Sport
from src.models.tennis_baseline import load_latest_tennis_artifact, predict_tennis_baseline
from src.opportunity.opportunity_repository import OpportunityRepository
from src.orchestration.decision_pipeline import DecisionPipelineSummary, run_decision_pipeline
from src.orchestration.sport_adapter import SportAdapter
from src.pipelines.mlb_pipeline import PipelineStepResult, run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline
from src.policy.manifest import load_policy_manifest
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

# Fase 4, Paso 4.1 (orquestador): registro de deportes soportados --
# incorporar un deporte nuevo requiere únicamente añadir su propio
# SportAdapter aquí, cero cambios en src/orchestration/decision_pipeline.py
# (ORCHESTRATOR_SPEC.md §2.3).
# `load_calibrator_fn` (calibración real, CALIBRATION_SPEC.md §4.3/§6):
# NO cableado hoy -- el primer calibrador real entrenado
# (tennis_calibrator_platt_v1_20260801T202949Z) no cumplió el criterio
# de aceptación (calibrated_ece_oof=0.137 > raw_ece=0.068, evidencia
# real contra data/engine.db, ver CONTINUITY.md) -- calibrar empeora el
# modelo con el volumen de datos actual. La infraestructura
# (SportAdapter.load_calibrator_fn, load_latest_tennis_calibrator)
# queda lista y probada para cuando exista evidencia que sí lo
# justifique -- no se activa mientras la propia evidencia lo contradiga.
SPORT_ADAPTERS = {
    Sport.MLB: SportAdapter(Sport.MLB, predict_mlb_baseline, load_latest_mlb_artifact),
    Sport.TENNIS: SportAdapter(Sport.TENNIS, predict_tennis_baseline, load_latest_tennis_artifact),
}
CONFIG_POLICY_DIR = PROJECT_ROOT / "config" / "policy"

# Paso 0d (subfase de preparación): un único lock de archivo evita que dos
# corridas de este script se solapen y escriban a la vez -- ver
# scripts/pipeline_lock.py. No es un scheduler: solo protege contra
# ejecuciones simultáneas cuando SÍ exista automatización.
LOCK_PATH = PROJECT_ROOT / "data" / ".run_e2e.lock"
# sysexits.h EX_TEMPFAIL: fallo temporal, con sentido reintentar más tarde
# -- distingue "no corrió porque otra instancia ya estaba activa" de un
# fallo real (exit 1) o de éxito (exit 0).
EXIT_ALREADY_RUNNING = 75


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


def _print_decision_summary(summary: DecisionPipelineSummary) -> None:
    print(f"\n=== Policy Engine / Opportunity Lifecycle: {summary.sport.value} ===")
    print(f"  Registros evaluados:            {summary.records_evaluated}")
    print(f"  Sin market_id (sin evaluar):     {summary.skipped_no_market_id}")
    print(f"  Opportunities creadas:           {summary.opportunities_created}")
    print(f"  Evaluaciones creadas:            {summary.evaluations_created}")
    for signal_type, count in sorted(summary.signal_type_counts.items()):
        print(f"  signal_type={signal_type}: {count}")
    print(f"  Errores (aislados, no abortan):  {len(summary.skipped_errors)}")
    for event_id, side, error in summary.skipped_errors[:5]:
        print(f"    - {event_id} [{side}]: {error}")
    print(f"  exchange_fee poblado inesperadamente: {summary.exchange_fee_populated_unexpectedly}")


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


def _run(args: argparse.Namespace) -> int:
    repo = Repository()
    # Paso 0d: mismo archivo SQLite que `repo` (ver PLAN_PHASE2.md §11) --
    # cada corrida real de este script pasa a dejar snapshot histórico,
    # además del estado actual que ya guardaba `repo`.
    hist_repo = HistoryRepository()

    # `sample` (default): comportamiento ORIGINAL sin cambios, 1 juego MLB +
    # 5 partidos de tenis, pensado para el reporte legible rápido de
    # siempre. `historical`: TODOS los juegos/partidos de la MISMA fecha
    # objetivo ya seleccionada abajo -- no cambia qué fecha se elige, solo
    # cuántos eventos de esa fecha se procesan (Paso 0d, cobertura amplia
    # para acumulación real de histórico). `run_mlb_pipeline`/
    # `run_tennis_pipeline` ya soportaban `limit=None` desde antes de esta
    # subfase -- no fue necesario tocar `src/pipelines/`.
    mlb_limit = None if args.mode == "historical" else 1
    tennis_limit = None if args.mode == "historical" else 5

    mlb_date = args.mlb_date or _find_next_mlb_date_with_games()
    print(f"\n=== MLB end-to-end: date={mlb_date} mode={args.mode} ===")
    mlb_result = run_mlb_pipeline(mlb_date, repository=repo, history_repository=hist_repo, limit=mlb_limit)
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
    print(f"\n=== TENIS end-to-end: tour={args.tour.upper()} date={tennis_date} mode={args.mode} ===")
    tennis_result = run_tennis_pipeline(
        args.tour, tennis_date, repository=repo, history_repository=hist_repo, limit=tennis_limit
    )
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

    # Fase 4, Paso 4.1: tercer bloque, orquestador captura -> Policy Engine
    # -> OpportunityRepository (ORCHESTRATOR_SPEC.md §4.1). Opera sobre los
    # NormalizedRecord ya en memoria de esta misma corrida -- sin volver a
    # leer la base de datos. Reutiliza hist_repo (ya construido arriba) y
    # abre OpportunityRepository sobre el mismo archivo que repo/hist_repo.
    now = datetime.now(timezone.utc)
    opp_repo = OpportunityRepository(db_path=repo.db_path)

    mlb_manifest = load_policy_manifest(CONFIG_POLICY_DIR / "mlb_v1.json")
    mlb_decision_summary = run_decision_pipeline(
        records=mlb_result.records,
        feature_inputs_list=mlb_result.feature_inputs_list,
        feature_cutoffs=mlb_result.feature_cutoffs,
        sport=Sport.MLB,
        adapter=SPORT_ADAPTERS[Sport.MLB],
        history_repository=hist_repo,
        opportunity_repository=opp_repo,
        policy_manifest=mlb_manifest,
        now=now,
    )
    _print_decision_summary(mlb_decision_summary)

    tennis_manifest = load_policy_manifest(CONFIG_POLICY_DIR / "tennis_v1.json")
    tennis_decision_summary = run_decision_pipeline(
        records=tennis_result.records,
        feature_inputs_list=tennis_result.feature_inputs_list,
        feature_cutoffs=tennis_result.feature_cutoffs,
        sport=Sport.TENNIS,
        adapter=SPORT_ADAPTERS[Sport.TENNIS],
        history_repository=hist_repo,
        opportunity_repository=opp_repo,
        policy_manifest=tennis_manifest,
        now=now,
    )
    _print_decision_summary(tennis_decision_summary)

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlb-date", default=None, help="YYYY-MM-DD (default: próximo día con juegos)")
    parser.add_argument("--tennis-date", default=None, help="YYYYMMDD (default: próximo día con partidos)")
    parser.add_argument("--tour", default="atp", choices=["atp", "wta"])
    parser.add_argument(
        "--mode",
        default="sample",
        choices=["sample", "historical"],
        help=(
            "sample (default, compatibilidad hacia atrás): 1 juego MLB + 5 partidos "
            "de tenis. historical: TODOS los juegos/partidos de la fecha objetivo ya "
            "seleccionada (Paso 0d, cobertura amplia para acumulación real de histórico)."
        ),
    )
    args = parser.parse_args()

    try:
        with single_instance_lock(LOCK_PATH):
            return _run(args)
    except LockAcquisitionError as exc:
        print(f"\n{exc}")
        print("Saliendo sin ejecutar pipelines ni tocar Repository/HistoryRepository.")
        return EXIT_ALREADY_RUNNING


if __name__ == "__main__":
    raise SystemExit(main())
