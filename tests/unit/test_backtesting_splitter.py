"""Tests de `src/backtesting/splitter.py` (Paso 9): walk-forward
estrictamente temporal, con `HistoryRepository` aislado por fold. Invariante
central, confirmado explícitamente por el usuario antes de implementar:
cero leakage por construcción -- cada fold entrena únicamente con datos
disponibles hasta ese instante y predice únicamente el siguiente bloque
temporal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.dataset import build_backtest_dataset
from src.backtesting.splitter import walk_forward_splits
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _record(event_id):
    return NormalizedRecord(sport=Sport.MLB, event_id=event_id, participant_a="Away Team", participant_b="Home Team")


def _add_row(hist: HistoryRepository, event_id: str, computed_at: datetime, result: str = "PARTICIPANT_A_WON"):
    snap_id = hist.save_event_snapshot(_record(event_id), source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=computed_at,
        features={"pitcher_era_season": {"participant_a": 3.5, "participant_b": 4.2}},
        computed_at=computed_at,
    )
    hist.save_event_result(
        event_id=event_id, sport="MLB", result=result, source="test", recorded_at=computed_at + timedelta(hours=3)
    )


def _build_hist(tmp_path, n_rows: int, spacing=timedelta(minutes=1)):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(n_rows):
        _add_row(hist, f"mlb_{i}", T0 + i * spacing)
    return hist


def test_empty_when_insufficient_volume(tmp_path):
    hist = _build_hist(tmp_path, n_rows=5)
    dataset = build_backtest_dataset(hist)

    folds = list(walk_forward_splits(hist, dataset, min_train_size=300, test_block_size=50))

    assert folds == []


def test_produces_expanding_train_and_next_block_test(tmp_path):
    hist = _build_hist(tmp_path, n_rows=7)
    dataset = build_backtest_dataset(hist)
    assert dataset.size == 7

    folds = list(walk_forward_splits(hist, dataset, min_train_size=3, test_block_size=2))

    assert len(folds) == 2
    assert folds[0].fold_index == 0
    assert folds[0].train_size == 3
    assert len(folds[0].test_rows) == 2
    assert [r.event_id for r in folds[0].test_rows] == ["mlb_3", "mlb_4"]

    assert folds[1].fold_index == 1
    assert folds[1].train_size == 5  # ventana de train EXPANSIVA (3 + 2 del fold anterior)
    assert len(folds[1].test_rows) == 2
    assert [r.event_id for r in folds[1].test_rows] == ["mlb_5", "mlb_6"]


def test_train_repository_never_contains_future_rows(tmp_path):
    hist = _build_hist(tmp_path, n_rows=7)
    dataset = build_backtest_dataset(hist)

    for fold in walk_forward_splits(hist, dataset, min_train_size=3, test_block_size=2):
        test_event_ids = {r.event_id for r in fold.test_rows}

        snapshot_event_ids = {row["event_id"] for row in fold.train_repository.get_all_event_snapshots()}
        feature_event_ids = {row["event_id"] for row in fold.train_repository.get_all_feature_snapshots()}
        result_event_ids = {row["event_id"] for row in fold.train_repository.get_all_event_results()}

        assert snapshot_event_ids.isdisjoint(test_event_ids)
        assert feature_event_ids.isdisjoint(test_event_ids)
        assert result_event_ids.isdisjoint(test_event_ids)
        assert len(snapshot_event_ids) == fold.train_size


def test_does_not_split_equal_timestamp_group(tmp_path):
    """Dos eventos con EXACTAMENTE el mismo data_cutoff_timestamp nunca
    deben quedar uno en train y otro en test del mismo fold."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(3):
        _add_row(hist, f"mlb_pad{i}", T0 + timedelta(minutes=i))
    tie_time = T0 + timedelta(minutes=10)
    _add_row(hist, "mlb_tie_a", tie_time)
    _add_row(hist, "mlb_tie_b", tie_time)
    for i in range(3):
        _add_row(hist, f"mlb_tail{i}", T0 + timedelta(minutes=20 + i))

    dataset = build_backtest_dataset(hist)
    assert dataset.size == 8

    # min_train_size=4 caería justo entre mlb_tie_a y mlb_tie_b si no se
    # protegiera el corte -- se verifica que ambos terminan del mismo lado.
    # Se inspecciona cada fold DENTRO del propio bucle: el HistoryRepository
    # temporal se descarta apenas el generador avanza al siguiente fold.
    for fold in walk_forward_splits(hist, dataset, min_train_size=4, test_block_size=2):
        train_event_ids = {row["event_id"] for row in fold.train_repository.get_all_event_snapshots()}
        test_event_ids = {r.event_id for r in fold.test_rows}
        tie_in_train = {"mlb_tie_a", "mlb_tie_b"} & train_event_ids
        tie_in_test = {"mlb_tie_a", "mlb_tie_b"} & test_event_ids
        assert not (tie_in_train and tie_in_test), "el par con timestamp idéntico quedó partido entre train y test"


def test_temp_repositories_isolated_across_folds(tmp_path):
    hist = _build_hist(tmp_path, n_rows=7)
    dataset = build_backtest_dataset(hist)

    folds = list(walk_forward_splits(hist, dataset, min_train_size=3, test_block_size=2))

    assert folds[0].train_repository.db_path != folds[1].train_repository.db_path


def test_cleans_up_temp_directory_after_consuming_fold(tmp_path):
    hist = _build_hist(tmp_path, n_rows=7)
    dataset = build_backtest_dataset(hist)

    gen = walk_forward_splits(hist, dataset, min_train_size=3, test_block_size=2)
    fold0 = next(gen)
    fold0_dir = fold0.train_repository.db_path.parent
    assert fold0_dir.exists()

    next(gen)  # avanzar al fold 1 -- dispara el `finally` del fold 0

    assert not fold0_dir.exists()
