"""Tests de `src/backtesting/dataset.py` (Paso 9): construcción del
dataset de backtesting uniendo `event_snapshots` + `feature_snapshots` +
`event_results`, reconstrucción del `NormalizedRecord` histórico completo,
y recálculo de `P_market_YES`/`P_market_NO` (Paso 3) + `quality_score`
(Paso 7) sobre ese registro histórico."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from src.backtesting.dataset import build_backtest_dataset
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository


def _record(event_id, yes_ask=0.55, no_ask=0.42, needs_review=False, source_timestamps=None, data_completeness=0.9):
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id=event_id,
        participant_a="Away Team",
        participant_b="Home Team",
        market=MarketData(yes_ask=yes_ask, no_ask=no_ask),
        data_quality=DataQuality(
            needs_review=needs_review,
            data_completeness_score=data_completeness,
            source_timestamps=source_timestamps or {},
        ),
    )


def _features():
    return {"pitcher_era_season": {"participant_a": 3.5, "participant_b": 4.2}}


def _add_row(
    hist: HistoryRepository,
    event_id: str,
    computed_at: datetime,
    result: str = None,
    recorded_at: datetime = None,
    feature_set_version: str = CURRENT_FEATURE_SET_VERSION,
    record: NormalizedRecord = None,
) -> int:
    record = record or _record(event_id)
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=feature_set_version,
        data_cutoff_timestamp=computed_at,
        features=_features(),
        computed_at=computed_at,
    )
    if result is not None:
        hist.save_event_result(
            event_id=event_id,
            sport="MLB",
            result=result,
            source="test",
            recorded_at=recorded_at or (computed_at + timedelta(hours=3)),
        )
    return snap_id


T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def test_includes_valid_row_with_market_and_quality_score(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON")

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 1
    row = dataset.rows[0]
    assert row.event_id == "mlb_1"
    assert row.label == 1
    assert row.p_market_yes == 0.55
    assert row.p_market_no == 0.42
    assert row.quality_score.confidence_method == "HEURISTIC_V1"
    assert row.quality_score.components["missing_critical"] is not None


def test_reconstructed_record_matches_original_byte_for_byte(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    original = _record("mlb_1", yes_ask=0.61, no_ask=0.38)
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON", record=original)

    dataset = build_backtest_dataset(hist)

    assert dataset.rows[0].record.model_dump_json() == original.model_dump_json()


def test_quality_score_uses_snapshot_instant_as_now_not_wall_clock(tmp_path):
    """El `now` pasado a compute_quality_score debe ser el instante
    histórico de la captura (`captured_at`), nunca el reloj real -- de lo
    contrario un snapshot de 2026 con un timestamp "fresco" en ese momento
    se reportaría como completamente obsoleto (freshness=0) simplemente
    por ejecutarse el test hoy."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _record("mlb_1", source_timestamps={"kalshi": T0})
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON", record=record)

    dataset = build_backtest_dataset(hist)

    freshness = dataset.rows[0].quality_score.components["freshness"]
    assert freshness == 1.0  # captured_at == source_timestamp -> antigüedad 0


def test_excludes_wrong_feature_set_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON", feature_set_version="other_version_v0")

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 0
    assert any("feature_set_version" in w for w in dataset.warnings)


def test_excludes_feature_snapshot_without_matching_event_snapshot(tmp_path):
    """Caso defensivo: un feature_snapshot cuyo event_snapshot_id no
    corresponde a ningún event_snapshots.id existente. Estructuralmente
    imposible vía la API pública (FOREIGN KEY lo impide) -- se simula con
    SQL crudo y FK desactivado, igual que la auditoría del Paso 0 que
    encontró este mismo riesgo para UPDATE/DELETE."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")

    conn = sqlite3.connect(tmp_path / "hist.db")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        INSERT INTO feature_snapshots (
            event_id, event_snapshot_id, feature_set_version, data_cutoff_timestamp, computed_at,
            features_json, missing_features_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("mlb_orphan", 99999, CURRENT_FEATURE_SET_VERSION, T0.isoformat(), T0.isoformat(), "{}", "[]"),
    )
    conn.commit()
    conn.close()

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 0
    assert any("event_snapshot correspondiente" in w for w in dataset.warnings)


def test_excludes_events_without_result(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_row(hist, "mlb_1", T0, result=None)

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 0
    assert any("sin event_result" in w for w in dataset.warnings)


def test_excludes_leakage_when_result_recorded_before_features(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON", recorded_at=T0 - timedelta(minutes=1))

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 0
    assert any("leakage" in w for w in dataset.warnings)


def test_excludes_non_binary_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_row(hist, "mlb_1", T0, result="POSTPONED")

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 0
    assert any("PARTICIPANT_A_WON/PARTICIPANT_B_WON" in w for w in dataset.warnings)


def test_uses_latest_result_for_duplicated_event(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    snap_id = hist.save_event_snapshot(_record("mlb_1"), source="test", captured_at=T0)
    hist.save_feature_snapshot(
        event_id="mlb_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=T0,
        features=_features(),
        computed_at=T0,
    )
    hist.save_event_result(
        event_id="mlb_1", sport="MLB", result="PARTICIPANT_A_WON", source="test", recorded_at=T0 + timedelta(hours=3)
    )
    # Corrección posterior (append-only: nunca se sobrescribe, se agrega).
    hist.save_event_result(
        event_id="mlb_1", sport="MLB", result="PARTICIPANT_B_WON", source="test", recorded_at=T0 + timedelta(hours=5)
    )

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 1
    assert dataset.rows[0].label == 0  # el resultado MÁS RECIENTE, no el primero


def test_empty_dataset_has_no_rows_and_no_error(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    dataset = build_backtest_dataset(hist)
    assert dataset.size == 0
    assert dataset.rows == []


def test_needs_review_row_has_none_market_prices_but_is_still_included(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _record("mlb_1", needs_review=True)
    _add_row(hist, "mlb_1", T0, result="PARTICIPANT_A_WON", record=record)

    dataset = build_backtest_dataset(hist)

    assert dataset.size == 1
    assert dataset.rows[0].p_market_yes is None
    assert dataset.rows[0].p_market_no is None
