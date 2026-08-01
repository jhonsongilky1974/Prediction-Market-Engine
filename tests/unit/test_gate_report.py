"""Tests de `build_sport_gate_report` (Fase 4, Paso 4.2). Ver
`FASE4_EXECUTION_PLAN.md` §6 Paso 4.2. Usa las funciones REALES
`build_mlb_training_dataset`/`build_tennis_training_dataset` (Fase 2,
sin mocks) para confirmar reutilización literal, no reimplementación --
no re-testea sus reglas de exclusión (ya cubiertas en
`test_mlb_baseline.py`/`test_tennis_baseline.py`), solo que este módulo
las combina en un reporte correcto. Todo contra `tmp_path`, nunca
`data/engine.db`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.evaluation.gate_report import build_sport_gate_report
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.mlb_baseline import build_mlb_training_dataset
from src.models.schemas import NormalizedRecord, Sport
from src.models.tennis_baseline import build_tennis_training_dataset
from src.storage.history_repository import HistoryRepository

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _add_mlb_sample(hist, event_id, result=None, feature_set_version=CURRENT_FEATURE_SET_VERSION):
    record = NormalizedRecord(sport=Sport.MLB, event_id=event_id, participant_a="A", participant_b="B")
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=NOW)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=feature_set_version,
        data_cutoff_timestamp=NOW,
        features={"pitcher_era_season": {"participant_a": 3.5, "participant_b": 4.0}},
        computed_at=NOW,
    )
    if result is not None:
        hist.save_event_result(
            event_id=event_id, sport="MLB", result=result, source="test", recorded_at=NOW + timedelta(hours=3)
        )


def _mlb_report(hist, thresholds):
    return build_sport_gate_report(
        hist,
        Sport.MLB,
        event_id_prefix="mlb_",
        thresholds=thresholds,
        build_dataset_fn=build_mlb_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
    )


def test_feature_snapshots_total_counts_only_matching_prefix_and_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_mlb_sample(hist, "mlb_1", result="PARTICIPANT_A_WON")
    _add_mlb_sample(hist, "mlb_2", result="PARTICIPANT_A_WON")
    _add_mlb_sample(hist, "mlb_3", feature_set_version="old_version_v0")  # excluida por versión
    _add_mlb_sample(hist, "espn_tennis_atp_1", feature_set_version=CURRENT_FEATURE_SET_VERSION)  # otro deporte

    report = _mlb_report(hist, thresholds={"mlb_classifier": 300})

    assert report.feature_snapshots_total == 2  # solo mlb_1/mlb_2: prefijo + versión correctos


def test_event_results_total_counts_only_matching_sport(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_mlb_sample(hist, "mlb_1", result="PARTICIPANT_A_WON")
    hist.save_event_result(event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test")

    report = _mlb_report(hist, thresholds={"mlb_classifier": 300})

    assert report.event_results_total == 1  # solo el de sport=MLB


def test_gate_0_met_true_only_when_both_counts_meet_threshold(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(5):
        _add_mlb_sample(hist, f"mlb_{i}", result="PARTICIPANT_A_WON")

    report = _mlb_report(hist, thresholds={"low": 5, "high": 6})

    assert report.gate_0_met["low"] is True
    assert report.gate_0_met["high"] is False


def test_coverage_labeled_count_matches_real_dataset_builder_size(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_mlb_sample(hist, "mlb_1", result="PARTICIPANT_A_WON")
    _add_mlb_sample(hist, "mlb_2", result="PARTICIPANT_A_WON")
    _add_mlb_sample(hist, "mlb_3")  # sin resultado todavía

    report = _mlb_report(hist, thresholds={"mlb_classifier": 300})
    real_dataset = build_mlb_training_dataset(hist)

    assert report.coverage_labeled_count == real_dataset.size == 2
    assert report.feature_snapshots_total == 3
    assert report.coverage_ratio == 2 / 3


def test_coverage_ratio_none_when_zero_feature_snapshots(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    report = _mlb_report(hist, thresholds={"mlb_classifier": 300})
    assert report.feature_snapshots_total == 0
    assert report.coverage_ratio is None
    assert report.coverage_labeled_count == 0


def test_exclusions_passthrough_matches_real_dataset_builder(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_mlb_sample(hist, "mlb_1", result="PARTICIPANT_A_WON")
    _add_mlb_sample(hist, "mlb_2")  # excluida: no_result
    _add_mlb_sample(hist, "mlb_3", feature_set_version="old_v0")  # excluida: wrong_version

    report = _mlb_report(hist, thresholds={"mlb_classifier": 300})
    real_dataset = build_mlb_training_dataset(hist)

    assert report.exclusions == real_dataset.exclusions
    assert report.exclusions["no_result"] == 1
    assert report.exclusions["wrong_version"] == 1
    assert report.warnings == real_dataset.warnings


def test_tennis_uses_espn_tennis_prefix(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = NormalizedRecord(sport=Sport.TENNIS, event_id="espn_tennis_atp_1", participant_a="A", participant_b="B")
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=NOW)
    hist.save_feature_snapshot(
        event_id="espn_tennis_atp_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=NOW,
        features={},
        computed_at=NOW,
    )

    report = build_sport_gate_report(
        hist,
        Sport.TENNIS,
        event_id_prefix="espn_tennis_",
        thresholds={"tennis_classifier": 30},
        build_dataset_fn=build_tennis_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
    )

    assert report.feature_snapshots_total == 1
    assert report.sport == Sport.TENNIS


def test_report_is_read_only_no_side_effects_on_history_repository(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_mlb_sample(hist, "mlb_1", result="PARTICIPANT_A_WON")

    before = hist.get_all_feature_snapshots()
    _mlb_report(hist, thresholds={"mlb_classifier": 300})
    after = hist.get_all_feature_snapshots()

    assert before == after
