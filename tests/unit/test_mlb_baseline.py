"""Tests del baseline MLB (Paso 5a): vectorización, dataset builder,
training pipeline y contrato de inferencia. Todo contra `HistoryRepository`
en `tmp_path` -- nunca `data/engine.db`.

Nota de alcance (decisión arquitectónica ya aprobada, Ambigüedad A del
Paso 5): `feature_snapshots` no tiene todavía ninguna tubería real de
alimentación (nada en `mlb_pipeline.py` llama a
`persist_mlb_feature_snapshot`) -- por eso estos tests construyen el
histórico directamente vía `HistoryRepository`, igual que ya hacen los
tests de `test_history_repository.py`, en vez de depender de una corrida
real del pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.features.mlb_features import MlbFeatureInputs
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models import registry as model_registry
from src.models.base import ModelStatus
from src.models.mlb_baseline import (
    MLB_FEATURE_COLUMNS,
    _vectorize_features,
    build_mlb_training_dataset,
    predict_mlb_baseline,
    train_mlb_baseline_model,
)
from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _record(event_id, sport=Sport.MLB):
    return NormalizedRecord(sport=sport, event_id=event_id, participant_a="Away Team", participant_b="Home Team")


def _synthetic_features(era_a=3.5, era_b=4.2):
    return {
        "pitcher_era_season": {"participant_a": era_a, "participant_b": era_b},
        "pitcher_whip_season": {"participant_a": 1.1, "participant_b": 1.3},
        "pitcher_k_pct": {"participant_a": 0.25, "participant_b": 0.20},
        "pitcher_bb_pct": {"participant_a": 0.07, "participant_b": 0.08},
        "pitcher_ip_season": {"participant_a": 120.0, "participant_b": 110.0},
        "pitcher_form_last5": {
            "participant_a": {"era": era_a, "whip": 1.1},
            "participant_b": {"era": era_b, "whip": 1.3},
        },
        "pitcher_vs_opponent_handedness_ops": {"participant_a": 0.700, "participant_b": 0.750},
        "bullpen_era_recent": {"participant_a": 3.8, "participant_b": 4.0},
        "team_ops_season": {"participant_a": 0.740, "participant_b": 0.720},
        "il_flag_key_players": {"participant_a": False, "participant_b": True},
        "team_record_pct": {"participant_a": 0.55, "participant_b": 0.45},
        "home_away": {"participant_a": "away", "participant_b": "home"},
    }


def _add_sample(
    hist: HistoryRepository,
    event_id: str,
    computed_at: datetime,
    result: str = None,
    recorded_at: datetime = None,
    feature_set_version: str = CURRENT_FEATURE_SET_VERSION,
    era_a: float = 3.5,
    era_b: float = 4.2,
):
    snap_id = hist.save_event_snapshot(_record(event_id), source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=feature_set_version,
        data_cutoff_timestamp=computed_at,
        features=_synthetic_features(era_a, era_b),
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


# ---------------------------------------------------------------------
# Vectorización
# ---------------------------------------------------------------------


def test_vectorize_features_is_deterministic_and_covers_all_columns():
    row1 = _vectorize_features(_synthetic_features())
    row2 = _vectorize_features(_synthetic_features())
    assert row1 == row2
    assert set(row1.keys()) == set(MLB_FEATURE_COLUMNS)


def test_vectorize_features_missing_dict_becomes_all_nan():
    row = _vectorize_features({})
    assert all(v != v for v in row.values())  # NaN != NaN


def test_vectorize_features_home_away_encoding():
    row = _vectorize_features({"home_away": {"participant_a": "away", "participant_b": "home"}})
    assert row["home_away.participant_a"] == 0.0
    assert row["home_away.participant_b"] == 1.0


def test_vectorize_features_bool_encoding():
    row = _vectorize_features({"il_flag_key_players": {"participant_a": False, "participant_b": True}})
    assert row["il_flag_key_players.participant_a"] == 0.0
    assert row["il_flag_key_players.participant_b"] == 1.0


# ---------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------


def test_dataset_builder_includes_valid_labeled_samples(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result="PARTICIPANT_A_WON")
    _add_sample(hist, "mlb_2", t0, result="PARTICIPANT_B_WON")

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 2
    labels = {s.event_id: s.label for s in dataset.samples}
    assert labels == {"mlb_1": 1, "mlb_2": 0}
    assert dataset.feature_set_version == CURRENT_FEATURE_SET_VERSION


def test_dataset_builder_excludes_leakage_when_result_recorded_before_features(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    # el resultado se registra ANTES de que existan las features -> leakage
    _add_sample(hist, "mlb_1", computed_at=t0, result="PARTICIPANT_A_WON", recorded_at=t0 - timedelta(hours=1))

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 0
    assert any("leakage" in w for w in dataset.warnings)


def test_dataset_builder_excludes_non_mlb_event_ids(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_999", t0, result="PARTICIPANT_A_WON")

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 0
    assert any("mlb_" in w for w in dataset.warnings)


def test_dataset_builder_excludes_mismatched_feature_set_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result="PARTICIPANT_A_WON", feature_set_version="stale_version")

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 0
    assert any("feature_set_version" in w for w in dataset.warnings)


def test_dataset_builder_excludes_events_without_result(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result=None)  # sin resultado todavía

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 0


def test_dataset_builder_excludes_non_binary_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result="CANCELLED")

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 0
    assert any("binaria" in w or "binary" in w.lower() for w in dataset.warnings)


def test_dataset_builder_uses_latest_result_for_duplicated_event(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    snap_id = hist.save_event_snapshot(_record("mlb_1"), source="test", captured_at=t0)
    hist.save_feature_snapshot(
        event_id="mlb_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=t0,
        features=_synthetic_features(),
        computed_at=t0,
    )
    hist.save_event_result(
        event_id="mlb_1", sport="MLB", result="PARTICIPANT_A_WON", source="test", recorded_at=t0 + timedelta(hours=2)
    )
    # corrección posterior, append-only -- debe prevalecer por ser la más reciente
    hist.save_event_result(
        event_id="mlb_1", sport="MLB", result="PARTICIPANT_B_WON", source="test", recorded_at=t0 + timedelta(hours=5)
    )

    dataset = build_mlb_training_dataset(hist)

    assert dataset.size == 1
    assert dataset.samples[0].label == 0


# ---------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------


def test_train_below_threshold_returns_insufficient_history(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "mlb_1", t0, result="PARTICIPANT_A_WON")
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_mlb_baseline_model(hist, models_dir=models_dir, min_samples=300)

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("umbral" in w for w in warnings)
    assert not models_dir.exists() or list(models_dir.glob("*.joblib")) == []


def test_train_at_threshold_produces_trained_artifact(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _add_sample(hist, f"mlb_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON", era_a=2.5, era_b=5.0)
    for i in range(5):
        _add_sample(hist, f"mlb_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", era_a=5.0, era_b=2.5)
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_mlb_baseline_model(
        hist, models_dir=models_dir, min_samples=10, now=datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
    )

    assert status == ModelStatus.TRAINED
    assert artifact is not None
    assert artifact.n_training_samples == 10
    assert artifact.model_version.startswith("mlb_baseline_logreg_v1_")
    assert artifact.file_path.exists()
    metadata_path = models_dir / f"{artifact.model_version}.metadata.json"
    assert metadata_path.exists()


# ---------------------------------------------------------------------
# Inference contract
# ---------------------------------------------------------------------


def test_predict_without_trained_artifact_is_honest_and_never_fabricates():
    record = _record("mlb_live_1")
    inputs = MlbFeatureInputs()
    cutoff = datetime.now(timezone.utc)

    output = predict_mlb_baseline(record, inputs, cutoff, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert output.model_version is None
    assert isinstance(output.missing_features, list) and len(output.missing_features) > 0


def test_predict_with_trained_artifact_returns_valid_probability(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _add_sample(hist, f"mlb_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON", era_a=2.5, era_b=5.0)
    for i in range(5):
        _add_sample(hist, f"mlb_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", era_a=5.0, era_b=2.5)
    models_dir = tmp_path / "models"
    status, artifact, _ = train_mlb_baseline_model(hist, models_dir=models_dir, min_samples=10)
    assert status == ModelStatus.TRAINED

    loaded = model_registry.load_latest_mlb_artifact(models_dir=models_dir)
    assert loaded is not None

    record = _record("mlb_live_1")
    inputs = MlbFeatureInputs()
    cutoff = datetime.now(timezone.utc)
    output = predict_mlb_baseline(record, inputs, cutoff, loaded_artifact=loaded)

    assert output.model_status == ModelStatus.TRAINED
    assert output.p_model_yes is not None
    assert 0.0 <= output.p_model_yes <= 1.0
    assert output.model_version == artifact.model_version
