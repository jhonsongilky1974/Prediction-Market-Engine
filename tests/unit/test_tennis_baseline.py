"""Tests del baseline de tenis (Paso 11): vectorización, dataset builder,
split temporal, training pipeline, contrato de inferencia, y persistencia
independiente de `registry.py` (Ambigüedad C del Design Proposal)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.features.tennis_features import TennisFeatureInputs
from src.models import registry as mlb_registry
from src.models.base import ModelStatus
from src.models.mlb_baseline import MlbTrainedArtifact
from src.models.registry import save_artifact_metadata as save_mlb_artifact_metadata
from src.models.schemas import NormalizedRecord, Sport
from src.models.tennis_baseline import (
    TennisTrainedArtifact,
    _vectorize_features,
    build_tennis_training_dataset,
    load_latest_tennis_artifact,
    predict_tennis_baseline,
    predict_tennis_baseline_from_features,
    split_dataset_temporally,
    train_tennis_baseline_model,
)
from src.storage.history_repository import HistoryRepository

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _record(event_id, sport=Sport.TENNIS):
    return NormalizedRecord(sport=sport, event_id=event_id, participant_a="Player A", participant_b="Player B")


def _synthetic_features(rest_a=5.0, rest_b=3.0, round_context="Qualifying 1st Round"):
    return {
        "rest_days": {"participant_a": rest_a, "participant_b": rest_b},
        "tournament_round_context": round_context,
    }


def _add_sample(
    hist: HistoryRepository,
    event_id: str,
    computed_at: datetime,
    result: str = None,
    recorded_at: datetime = None,
    feature_set_version: str = CURRENT_FEATURE_SET_VERSION,
    rest_a: float = 5.0,
    rest_b: float = 3.0,
    round_context: str = "Qualifying 1st Round",
):
    snap_id = hist.save_event_snapshot(_record(event_id), source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=feature_set_version,
        data_cutoff_timestamp=computed_at,
        features=_synthetic_features(rest_a, rest_b, round_context),
        computed_at=computed_at,
    )
    if result is not None:
        hist.save_event_result(
            event_id=event_id,
            sport="TENNIS",
            result=result,
            source="test",
            recorded_at=recorded_at or (computed_at + timedelta(hours=3)),
        )


# ---------------------------------------------------------------------
# Vectorización
# ---------------------------------------------------------------------


def test_vectorize_features_is_deterministic():
    row1 = _vectorize_features(_synthetic_features(), round_categories=["Qualifying 1st Round", "Final"])
    row2 = _vectorize_features(_synthetic_features(), round_categories=["Qualifying 1st Round", "Final"])
    assert row1 == row2


def test_vectorize_features_missing_rest_days_becomes_nan():
    features = {"rest_days": {"participant_a": None, "participant_b": 3.0}, "tournament_round_context": None}
    row = _vectorize_features(features, round_categories=["Final"])
    import math

    assert math.isnan(row["rest_days.participant_a"])
    assert row["rest_days.participant_b"] == 3.0


def test_vectorize_features_one_hot_encodes_known_round_only():
    features = _synthetic_features(round_context="Final")
    row = _vectorize_features(features, round_categories=["Qualifying 1st Round", "Final"])
    assert row["tournament_round.Final"] == 1.0
    assert row["tournament_round.Qualifying 1st Round"] == 0.0


def test_vectorize_features_unknown_round_produces_all_zero_row_never_fabricated():
    features = _synthetic_features(round_context="Semifinal")  # no está en round_categories
    row = _vectorize_features(features, round_categories=["Qualifying 1st Round", "Final"])
    assert row["tournament_round.Qualifying 1st Round"] == 0.0
    assert row["tournament_round.Final"] == 0.0


# ---------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------


def test_dataset_builder_includes_valid_labeled_samples(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="PARTICIPANT_A_WON")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 1
    assert dataset.samples[0].label == 1


def test_dataset_builder_excludes_leakage_when_result_recorded_before_features(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="PARTICIPANT_A_WON", recorded_at=t0 - timedelta(minutes=1))

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("leakage" in w for w in dataset.warnings)
    assert dataset.exclusions["leakage"] == 1


def test_dataset_builder_excludes_non_tennis_event_ids(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    snap_id = hist.save_event_snapshot(
        NormalizedRecord(sport=Sport.MLB, event_id="mlb_1", participant_a="A", participant_b="B"),
        source="test",
        captured_at=t0,
    )
    hist.save_feature_snapshot(
        event_id="mlb_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=t0,
        features=_synthetic_features(),
        computed_at=t0,
    )
    hist.save_event_result(event_id="mlb_1", sport="MLB", result="PARTICIPANT_A_WON", source="test", recorded_at=t0 + timedelta(hours=3))

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("espn_tennis_" in w for w in dataset.warnings)
    assert dataset.exclusions["wrong_sport"] == 1


def test_dataset_builder_excludes_mismatched_feature_set_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="PARTICIPANT_A_WON", feature_set_version="other_v0")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("feature_set_version" in w for w in dataset.warnings)
    assert dataset.exclusions["wrong_version"] == 1


def test_dataset_builder_excludes_events_without_result(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result=None)

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("sin event_result" in w for w in dataset.warnings)
    assert dataset.exclusions["no_result"] == 1


def test_dataset_builder_excludes_non_binary_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="CANCELLED")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("PARTICIPANT_A_WON/PARTICIPANT_B_WON" in w for w in dataset.warnings)
    assert dataset.exclusions["non_binary_result"] == 1


def test_dataset_builder_uses_latest_result_for_duplicated_event(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    snap_id = hist.save_event_snapshot(_record("espn_tennis_atp_1"), source="test", captured_at=t0)
    hist.save_feature_snapshot(
        event_id="espn_tennis_atp_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=t0,
        features=_synthetic_features(),
        computed_at=t0,
    )
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test",
        recorded_at=t0 + timedelta(hours=3),
    )
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_B_WON", source="test",
        recorded_at=t0 + timedelta(hours=5),
    )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 1
    assert dataset.samples[0].label == 0


# ---------------------------------------------------------------------
# Split temporal
# ---------------------------------------------------------------------


def test_split_dataset_temporally_validation_is_most_recent_and_never_random(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    order = list(range(10))
    import random

    shuffled = order[:]
    random.Random(42).shuffle(shuffled)
    for i in shuffled:
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(minutes=i), result=result)

    dataset = build_tennis_training_dataset(hist)
    train, validation = split_dataset_temporally(dataset, validation_fraction=0.2)

    assert train.size + validation.size == 10
    assert max(s.data_cutoff_timestamp for s in train.samples) < min(s.data_cutoff_timestamp for s in validation.samples)


def test_split_dataset_temporally_is_deterministic_across_calls(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(minutes=i), result=result)
    dataset = build_tennis_training_dataset(hist)

    train1, val1 = split_dataset_temporally(dataset)
    train2, val2 = split_dataset_temporally(dataset)

    assert [s.event_id for s in train1.samples] == [s.event_id for s in train2.samples]
    assert [s.event_id for s in val1.samples] == [s.event_id for s in val2.samples]


# ---------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------


def test_train_below_threshold_returns_insufficient_history(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _add_sample(hist, "espn_tennis_atp_1", t0, result="PARTICIPANT_A_WON")
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=30)

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("umbral" in w for w in warnings)
    assert not models_dir.exists() or list(models_dir.glob("*.joblib")) == []


def test_train_at_threshold_produces_trained_artifact(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(6):
        _add_sample(
            hist, f"espn_tennis_atp_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON",
            rest_a=8.0, rest_b=1.0, round_context="Final",
        )
    for i in range(6):
        _add_sample(
            hist, f"espn_tennis_atp_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON",
            rest_a=1.0, rest_b=8.0, round_context="Qualifying 1st Round",
        )
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)

    assert status == ModelStatus.TRAINED
    assert artifact is not None
    assert artifact.n_training_samples == 12
    assert artifact.model_version.startswith("tennis_baseline_logreg_v1_")
    assert artifact.file_path.exists()
    assert set(artifact.round_categories) == {"Final", "Qualifying 1st Round"}
    metadata_path = models_dir / f"{artifact.model_version}.metadata.json"
    assert metadata_path.exists()


def test_train_discovers_round_categories_only_from_train_split(tmp_path):
    """La ronda 'Semifinal' solo aparece en la muestra MÁS RECIENTE
    (que cae en validación con validation_fraction=0.5) -- no debe
    aparecer en round_categories, descubiertas únicamente del split de
    train."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"espn_tennis_atp_{i}", t0 + timedelta(minutes=i), result=result, round_context="Final")
    _add_sample(
        hist, "espn_tennis_atp_last", t0 + timedelta(minutes=1000), result="PARTICIPANT_A_WON",
        round_context="Semifinal",
    )
    models_dir = tmp_path / "models"

    status, artifact, _ = train_tennis_baseline_model(
        hist, models_dir=models_dir, min_samples=10, validation_fraction=0.1
    )

    assert status == ModelStatus.TRAINED
    assert "Semifinal" not in artifact.round_categories


# ---------------------------------------------------------------------
# Inference contract
# ---------------------------------------------------------------------


def test_predict_without_trained_artifact_is_honest_and_never_fabricates():
    record = _record("espn_tennis_atp_live_1")
    inputs = TennisFeatureInputs()
    cutoff = datetime.now(timezone.utc)

    output = predict_tennis_baseline(record, inputs, cutoff, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert output.model_version is None
    assert isinstance(output.missing_features, list) and len(output.missing_features) > 0


def test_predict_with_trained_artifact_returns_valid_probability(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON", rest_a=8.0, rest_b=1.0)
    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", rest_a=1.0, rest_b=8.0)
    models_dir = tmp_path / "models"
    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)
    assert status == ModelStatus.TRAINED

    loaded = load_latest_tennis_artifact(models_dir=models_dir)
    assert loaded is not None

    record = _record("espn_tennis_atp_live_1")
    inputs = TennisFeatureInputs()
    cutoff = datetime.now(timezone.utc)
    output = predict_tennis_baseline(record, inputs, cutoff, loaded_artifact=loaded)

    assert output.model_status == ModelStatus.TRAINED
    assert output.p_model_yes is not None
    assert 0.0 <= output.p_model_yes <= 1.0
    assert output.model_version == artifact.model_version


def test_predict_from_features_matches_predict_tennis_baseline_exactly(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_a{i}", t0 + timedelta(minutes=i), result="PARTICIPANT_A_WON", rest_a=8.0, rest_b=1.0)
    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_b{i}", t0 + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", rest_a=1.0, rest_b=8.0)
    models_dir = tmp_path / "models"
    train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)
    loaded = load_latest_tennis_artifact(models_dir=models_dir)

    record = _record("espn_tennis_atp_live_1")
    inputs = TennisFeatureInputs()
    cutoff = datetime.now(timezone.utc)
    live_output = predict_tennis_baseline(record, inputs, cutoff, loaded_artifact=loaded)

    from src.features.tennis_features import compute_tennis_features

    features, _missing, _warnings = compute_tennis_features(record, inputs, cutoff)
    p_from_features = predict_tennis_baseline_from_features(features, loaded_artifact=loaded)

    assert p_from_features == pytest.approx(live_output.p_model_yes)


def test_predict_from_features_returns_none_without_trained_artifact():
    assert predict_tennis_baseline_from_features(_synthetic_features(), loaded_artifact=None) is None


# ---------------------------------------------------------------------
# Persistencia independiente de registry.py (Ambigüedad C)
# ---------------------------------------------------------------------


def test_tennis_and_mlb_artifacts_coexist_in_same_models_dir_without_collision(tmp_path):
    models_dir = tmp_path / "models"
    hist = HistoryRepository(db_path=tmp_path / "hist.db")

    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_a{i}", datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(minutes=i), result="PARTICIPANT_A_WON", rest_a=8.0, rest_b=1.0)
    for i in range(6):
        _add_sample(hist, f"espn_tennis_atp_b{i}", datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(minutes=100 + i), result="PARTICIPANT_B_WON", rest_a=1.0, rest_b=8.0)
    status, tennis_artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)
    assert status == ModelStatus.TRAINED

    # Un artefacto MLB REAL (mismo joblib/metadata que registry.py escribe
    # de verdad, sin modificar esa función) persistido en el MISMO
    # directorio -- ninguno de los dos debe confundirse con el otro al
    # cargar "el más reciente" de su propio deporte.
    import joblib

    fake_mlb_model_object = {"not_a_real_sklearn_pipeline": True}
    mlb_file_path = models_dir / "mlb_baseline_logreg_v1_20260101T000000Z.joblib"
    joblib.dump(fake_mlb_model_object, mlb_file_path)
    fake_mlb_artifact = MlbTrainedArtifact(
        model_version="mlb_baseline_logreg_v1_20260101T000000Z",
        sport="MLB",
        algorithm="logistic_regression_v1",
        trained_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        n_training_samples=500,
        feature_columns=["dummy"],
        file_path=mlb_file_path,
    )
    save_mlb_artifact_metadata(fake_mlb_artifact, models_dir=models_dir)

    loaded_tennis = load_latest_tennis_artifact(models_dir=models_dir)
    assert loaded_tennis is not None
    assert loaded_tennis[1].model_version == tennis_artifact.model_version

    loaded_mlb = mlb_registry.load_latest_mlb_artifact(models_dir=models_dir)
    assert loaded_mlb is not None
    assert loaded_mlb[1].model_version == fake_mlb_artifact.model_version
    assert loaded_mlb[0] == fake_mlb_model_object  # el "modelo" MLB cargado no es el pipeline de tenis
