"""Tests de `build_label_quality_report` (Fase 4, Paso 4.2.1). Ver
`FASE4_EXECUTION_PLAN.md` §6 Paso 4.2.1 y `ORCHESTRATOR_SPEC.md` §1.8.
Todo contra `tmp_path`, nunca `data/engine.db`. Usa el `SportGateReport`
REAL (`build_sport_gate_report`, sin mocks) para confirmar reutilización
literal de `exclusions["no_result"]`, no recálculo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.evaluation.gate_report import build_sport_gate_report
from src.evaluation.label_quality_audit import build_label_quality_report
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.mlb_baseline import build_mlb_training_dataset
from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _add_feature_snapshot(hist, event_id, sport=Sport.MLB, computed_at=NOW):
    record = NormalizedRecord(sport=sport, event_id=event_id, participant_a="A", participant_b="B")
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=computed_at,
        features={},
        computed_at=computed_at,
    )


def _add_result(hist, event_id, result, sport="MLB", recorded_at=None):
    hist.save_event_result(
        event_id=event_id, sport=sport, result=result, source="test", recorded_at=recorded_at or NOW
    )


def _gate_report(hist):
    return build_sport_gate_report(
        hist,
        Sport.MLB,
        event_id_prefix="mlb_",
        thresholds={"mlb_classifier": 300},
        build_dataset_fn=build_mlb_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
    )


def test_no_anomalies_on_clean_data(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1")
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON")

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.has_anomalies is False
    assert report.conflicting_results == []
    assert report.exact_duplicate_count == 0
    assert report.sport_mismatches == []


def test_conflicting_results_detected(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1")
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON", recorded_at=NOW)
    _add_result(hist, "mlb_1", "PARTICIPANT_B_WON", recorded_at=NOW + timedelta(hours=1))

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.has_anomalies is True
    assert len(report.conflicting_results) == 1
    conflict = report.conflicting_results[0]
    assert conflict.event_id == "mlb_1"
    assert conflict.distinct_results == ["PARTICIPANT_A_WON", "PARTICIPANT_B_WON"]
    assert conflict.row_count == 2


def test_exact_duplicates_detected_and_not_counted_as_conflict(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1")
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON", recorded_at=NOW)
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON", recorded_at=NOW + timedelta(hours=1))

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.exact_duplicate_count == 1
    assert report.conflicting_results == []  # mismo valor -> no es un conflicto
    assert report.has_anomalies is True  # pero SÍ es una anomalía (duplicado)


def test_non_binary_result_counts_cancelled_and_postponed(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_result(hist, "mlb_1", "CANCELLED")
    _add_result(hist, "mlb_2", "POSTPONED")
    _add_result(hist, "mlb_3", "POSTPONED")

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.non_binary_result_counts == {"CANCELLED": 1, "POSTPONED": 2}
    # CANCELLED/POSTPONED son estados esperados del dominio, no un bug:
    assert report.has_anomalies is False


def test_unresolved_count_reused_literally_from_gate_report_not_recomputed(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1")  # sin event_result -> no_result
    _add_feature_snapshot(hist, "mlb_2")  # sin event_result -> no_result
    _add_feature_snapshot(hist, "mlb_3")
    _add_result(hist, "mlb_3", "PARTICIPANT_A_WON")

    gate_report = _gate_report(hist)
    report = build_label_quality_report(hist, Sport.MLB, gate_report)

    assert report.unresolved_count == gate_report.exclusions["no_result"] == 2


def test_sport_mismatch_detected_between_event_snapshots_and_event_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1", sport=Sport.MLB)  # event_snapshots.sport = MLB
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON", sport="TENNIS")  # event_results.sport = TENNIS

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.sport_mismatches == ["mlb_1"]
    assert report.has_anomalies is True


def test_no_mismatch_flagged_when_event_result_has_no_matching_snapshot(tmp_path):
    """Un event_result sin ningún event_snapshot correspondiente no es un
    "mismatch" -- no hay nada con qué comparar, no se fabrica una
    anomalía sin evidencia."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_result(hist, "mlb_orphan", "PARTICIPANT_A_WON")

    report = build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert report.sport_mismatches == []


def test_raises_when_gate_report_sport_does_not_match(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    gate_report = _gate_report(hist)  # sport=MLB
    with pytest.raises(ValueError, match="no coincide"):
        build_label_quality_report(hist, Sport.TENNIS, gate_report)


def test_report_is_read_only_no_side_effects(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_feature_snapshot(hist, "mlb_1")
    _add_result(hist, "mlb_1", "PARTICIPANT_A_WON")

    before_results = hist.get_all_event_results()
    before_snapshots = hist.get_all_event_snapshots()
    build_label_quality_report(hist, Sport.MLB, _gate_report(hist))

    assert hist.get_all_event_results() == before_results
    assert hist.get_all_event_snapshots() == before_snapshots
