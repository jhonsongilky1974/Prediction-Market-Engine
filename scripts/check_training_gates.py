#!/usr/bin/env python3
"""Chequeo repetible de GATE-0 + Coverage Gate + Auditoría de calidad de
labels (Fase 4, Pasos 4.2 y 4.2.1). Ver `FASE4_EXECUTION_PLAN.md` §6 y
`src/evaluation/gate_report.py`/`label_quality_audit.py`.

Un solo comando para la pregunta completa de "¿hay suficiente histórico
entrenable, y es confiable?" -- la auditoría de labels (Paso 4.2.1)
reutiliza literalmente el `SportGateReport` ya calculado aquí (campo
`exclusions["no_result"]`), nunca lo recalcula por separado.

Invocación MANUAL, en cualquier momento -- de solo lectura, no
desbloquea ni activa nada por sí solo. Sin lock de instancia única: no
escribe nada, seguro de ejecutar en paralelo con cualquier otro script.

Uso:
    source .venv/bin/activate
    python scripts/check_training_gates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.gate_report import SportGateReport, build_sport_gate_report
from src.evaluation.label_quality_audit import SportLabelQualityReport, build_label_quality_report
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.mlb_baseline import DEFAULT_MIN_TRAINING_SAMPLES, build_mlb_training_dataset
from src.models.mlb_elo import DEFAULT_MIN_GAMES, build_mlb_elo_game_sequence
from src.models.schemas import Sport
from src.models.tennis_baseline import DEFAULT_MIN_TRAINING_SAMPLES_TENNIS, build_tennis_training_dataset
from src.storage.history_repository import HistoryRepository


def _print_label_quality_report(report: SportLabelQualityReport) -> None:
    print(f"\n=== Auditoría de calidad de labels: {report.sport.value} ===")
    print(f"  event_results totales:              {report.total_event_results}")
    print(f"  Sin resolución todavía (reutilizado de Coverage Gate): {report.unresolved_count}")
    print(f"  Resultados en conflicto por event_id: {len(report.conflicting_results)}")
    for conflict in report.conflicting_results[:10]:
        print(f"    - {conflict.event_id}: {conflict.distinct_results} ({conflict.row_count} filas)")
    print(f"  Duplicados exactos (misma fila repetida): {report.exact_duplicate_count}")
    print("  Resultados no binarios (CANCELLED/POSTPONED/otros):")
    if report.non_binary_result_counts:
        for value, count in sorted(report.non_binary_result_counts.items()):
            print(f"    {value}: {count}")
    else:
        print("    (ninguno)")
    print(f"  event_id con sport inconsistente vs. event_snapshots: {len(report.sport_mismatches)}")
    for event_id in report.sport_mismatches[:10]:
        print(f"    - {event_id}")
    veredicto = "ANOMALÍAS ENCONTRADAS -- requieren revisión antes de entrenar" if report.has_anomalies else "sin anomalías"
    print(f"  Veredicto: {veredicto}")


def _print_report(report: SportGateReport) -> None:
    print(f"\n=== GATE-0 / Coverage Gate: {report.sport.value} ===")
    print(f"  feature_snapshots (versión actual): {report.feature_snapshots_total}")
    print(f"  event_results:                      {report.event_results_total}")
    for name, n_min in report.thresholds.items():
        estado = "CUMPLIDO" if report.gate_0_met[name] else "no cumplido"
        print(f"  GATE-0[{name}] (N_min={n_min}): {estado}")
    print(f"  Coverage -- etiquetados utilizables: {report.coverage_labeled_count}")
    if report.coverage_ratio is not None:
        print(f"  Coverage ratio: {report.coverage_ratio:.2%}  (sin umbral fijado todavía -- FASE4_EXECUTION_PLAN.md §6 Paso 4.2)")
    else:
        print("  Coverage ratio: N/A (0 feature_snapshots de la versión actual todavía)")
    print("  Desglose de exclusiones (build_*_training_dataset):")
    for name, count in report.exclusions.items():
        print(f"    {name}: {count}")
    if report.warnings:
        print("  Advertencias:")
        for w in report.warnings:
            print(f"    - {w}")


def main() -> int:
    hist = HistoryRepository()

    mlb_report = build_sport_gate_report(
        hist,
        Sport.MLB,
        event_id_prefix="mlb_",
        thresholds={"mlb_classifier": DEFAULT_MIN_TRAINING_SAMPLES, "mlb_elo": DEFAULT_MIN_GAMES},
        build_dataset_fn=build_mlb_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        # mlb_elo NO usa feature_snapshots -- tiene su propia función de
        # elegibilidad (Fase 4, Paso 4.3, MODEL_TRAINING_SPEC.md §0.4).
        eligible_count_fn={"mlb_elo": lambda h: build_mlb_elo_game_sequence(h).size},
    )
    _print_report(mlb_report)
    _print_label_quality_report(build_label_quality_report(hist, Sport.MLB, mlb_report))

    tennis_report = build_sport_gate_report(
        hist,
        Sport.TENNIS,
        event_id_prefix="espn_tennis_",
        thresholds={"tennis_classifier": DEFAULT_MIN_TRAINING_SAMPLES_TENNIS},
        build_dataset_fn=build_tennis_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
    )
    _print_report(tennis_report)
    _print_label_quality_report(build_label_quality_report(hist, Sport.TENNIS, tennis_report))

    print(f"\nHistory DB: {hist.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
