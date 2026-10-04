"""Tests del baseline de tenis (Paso 11) con la spec de dataset PRE-EVENTO v2
(CONTINUITY.md §0.38): vectorización, dataset builder (límites temporales,
un snapshot por evento), splits temporales, training pipeline (política de
mínimos, test fuera de muestra, candidato rechazado), contrato de
inferencia (puerta pre-evento) y persistencia independiente de
`registry.py` (Ambigüedad C del Design Proposal)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.features.tennis_features import TennisFeatureInputs, compute_tennis_features
from src.models import registry as mlb_registry
from src.models.base import ModelStatus
from src.models.mlb_baseline import MlbTrainedArtifact
from src.models.registry import save_artifact_metadata as save_mlb_artifact_metadata
from src.models.schemas import EventStatus, NormalizedRecord, Sport
from src.models.tennis_baseline import (
    CANDIDATE_PROMOTION_ELIGIBLE,
    CANDIDATE_REJECTED,
    MIN_EVENTS_FOR_RETRAIN,
    TRAINING_DATASET_SPEC_VERSION,
    _vectorize_features,
    build_tennis_training_dataset,
    load_latest_tennis_artifact,
    predict_tennis_baseline,
    predict_tennis_baseline_from_features,
    split_dataset_temporally,
    split_events_temporally,
    train_tennis_baseline_model,
)
from src.storage.history_repository import HistoryRepository
from tests.unit.tennis_preevent_factories import (
    T0,
    add_preevent_sample,
    make_tennis_record,
    promote_artifacts_for_test,
    synthetic_features,
)

# Alias histórico: otros tests importan `_add_sample` de este módulo.
_add_sample = add_preevent_sample
_synthetic_features = synthetic_features
SMALL = dict(min_samples=10, min_partition_events=2)  # NO cumple la política: solo para probar mecánica


def _seed_events(hist, n, t0=T0, start_index=0, invert=False, round_a="Final", round_b="Qualifying 1st Round"):
    """`n` eventos INTERCALADOS cronológicamente (1 por día). Par: A gana con
    descanso A alto; B gana con descanso B alto. `invert=True` invierte la
    relación features->resultado."""
    for k in range(n):
        i = start_index + k
        a_wins = (i % 2 == 0) != invert
        add_preevent_sample(
            hist,
            f"espn_tennis_atp_{i:04d}",
            t0 + timedelta(days=i),
            result="PARTICIPANT_A_WON" if a_wins else "PARTICIPANT_B_WON",
            rest_a=8.0 if i % 2 == 0 else 1.0,
            rest_b=1.0 if i % 2 == 0 else 8.0,
            round_context=round_a if i % 2 == 0 else round_b,
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
# Dataset builder -- reglas heredadas
# ---------------------------------------------------------------------


def test_dataset_builder_includes_valid_labeled_samples(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="PARTICIPANT_A_WON")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 1
    sample = dataset.samples[0]
    assert sample.label == 1
    assert sample.snapshot_lead_minutes == pytest.approx(300.0)
    assert sample.event_start_time == T0 + timedelta(minutes=300)


def test_dataset_builder_excludes_leakage_when_result_recorded_before_features(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="PARTICIPANT_A_WON", recorded_at=T0 - timedelta(minutes=1))

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("leakage" in w for w in dataset.warnings)
    assert dataset.exclusions["leakage"] == 1


def test_dataset_builder_excludes_non_tennis_event_ids(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    snap_id = hist.save_event_snapshot(
        NormalizedRecord(sport=Sport.MLB, event_id="mlb_1", participant_a="A", participant_b="B"),
        source="test",
        captured_at=T0,
    )
    hist.save_feature_snapshot(
        event_id="mlb_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=T0,
        features=_synthetic_features(),
        computed_at=T0,
    )
    hist.save_event_result(event_id="mlb_1", sport="MLB", result="PARTICIPANT_A_WON", source="test", recorded_at=T0 + timedelta(hours=3))

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("espn_tennis_" in w for w in dataset.warnings)
    assert dataset.exclusions["wrong_sport"] == 1


def test_dataset_builder_excludes_mismatched_feature_set_version(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="PARTICIPANT_A_WON", feature_set_version="other_v0")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("feature_set_version" in w for w in dataset.warnings)
    assert dataset.exclusions["wrong_version"] == 1


def test_dataset_builder_excludes_events_without_result(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result=None)

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("sin event_result" in w for w in dataset.warnings)
    assert dataset.exclusions["no_result"] == 1


def test_dataset_builder_excludes_non_binary_results(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="CANCELLED")

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert any("PARTICIPANT_A_WON/PARTICIPANT_B_WON" in w for w in dataset.warnings)
    assert dataset.exclusions["non_binary_result"] == 1


def test_dataset_builder_uses_latest_result_for_duplicated_event(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0 + timedelta(hours=5)
    _add_sample(hist, "espn_tennis_atp_1", T0, result=None, start_time=start)
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test",
        recorded_at=start + timedelta(hours=3),
    )
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_B_WON", source="test",
        recorded_at=start + timedelta(hours=5),
    )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 1
    assert dataset.samples[0].label == 0


# ---------------------------------------------------------------------
# Dataset builder -- límites temporales pre-evento (fix de la fuga)
# ---------------------------------------------------------------------


def test_dataset_builder_fails_closed_with_only_post_event_snapshots(tmp_path):
    """Regresión del defecto original: snapshots FINAL/posteriores al inicio
    con el resultado cargado después (backfill) pasaban el viejo filtro
    `computed_at < recorded_at`. Ahora NO producen ninguna muestra."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0
    for i in range(5):
        _add_sample(
            hist,
            f"espn_tennis_atp_{i}",
            computed_at=start + timedelta(hours=4, minutes=i),  # DESPUÉS del inicio
            result="PARTICIPANT_A_WON",
            start_time=start,
            status=EventStatus.FINAL,
            recorded_at=start + timedelta(days=2),  # backfill: el resultado se cargó mucho después
        )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["status_not_scheduled"] == 5
    assert any("FINAL" in w or "SCHEDULED" in w for w in dataset.warnings)


def test_dataset_builder_excludes_snapshot_computed_at_or_after_event_start(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0 + timedelta(hours=5)
    _add_sample(hist, "espn_tennis_atp_1", computed_at=start, result="PARTICIPANT_A_WON", start_time=start)  # igual
    _add_sample(
        hist, "espn_tennis_atp_2", computed_at=start + timedelta(minutes=1), result="PARTICIPANT_A_WON", start_time=start
    )  # posterior (status SCHEDULED a propósito)

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["not_before_event_start"] == 2


@pytest.mark.parametrize("status", [EventStatus.LIVE, EventStatus.FINAL, EventStatus.POSTPONED, EventStatus.UNKNOWN])
def test_dataset_builder_excludes_non_scheduled_status(tmp_path, status):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="PARTICIPANT_A_WON", status=status)

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["status_not_scheduled"] == 1


def test_dataset_builder_enforces_minimum_lead_of_60_minutes_exactly(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_59", T0, result="PARTICIPANT_A_WON", lead_minutes=59)
    _add_sample(hist, "espn_tennis_atp_60", T0, result="PARTICIPANT_A_WON", lead_minutes=60)

    dataset = build_tennis_training_dataset(hist)

    assert [s.event_id for s in dataset.samples] == ["espn_tennis_atp_60"]
    assert dataset.exclusions["insufficient_lead"] == 1


def test_dataset_builder_excludes_missing_event_start_time(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    snap_id = hist.save_event_snapshot(
        make_tennis_record("espn_tennis_atp_1", start_time=None), source="test", captured_at=T0
    )
    hist.save_feature_snapshot(
        event_id="espn_tennis_atp_1",
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=T0,
        features=_synthetic_features(),
        computed_at=T0,
    )
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test", recorded_at=T0 + timedelta(hours=9)
    )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["missing_start_time"] == 1


def test_dataset_builder_excludes_cutoff_not_before_start_even_if_computed_before(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0 + timedelta(hours=5)
    _add_sample(
        hist, "espn_tennis_atp_1", computed_at=T0, result="PARTICIPANT_A_WON", start_time=start,
        cutoff=start + timedelta(minutes=1),
    )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["not_before_event_start"] == 1


def test_dataset_builder_excludes_negative_rest_days(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _add_sample(hist, "espn_tennis_atp_1", T0, result="PARTICIPANT_A_WON", rest_a=-1.5)

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 0
    assert dataset.exclusions["negative_rest_days"] == 1


def test_dataset_builder_keeps_exactly_one_snapshot_per_event_the_latest_valid(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0 + timedelta(days=1)
    for k, rest_a in enumerate([2.0, 3.0, 4.0]):
        _add_sample(
            hist, "espn_tennis_atp_1", computed_at=T0 + timedelta(hours=k), result=None, start_time=start, rest_a=rest_a
        )
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test", recorded_at=start + timedelta(hours=3)
    )

    dataset = build_tennis_training_dataset(hist)

    assert dataset.size == 1
    assert dataset.samples[0].features["rest_days"]["participant_a"] == 4.0  # el snapshot más reciente
    assert dataset.exclusions["superseded_same_event"] == 2
    assert len({s.event_id for s in dataset.samples}) == dataset.size  # sin duplicados


def test_dataset_builder_selection_is_deterministic_on_ties(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    start = T0 + timedelta(days=1)
    for rest_a in (2.0, 9.0):  # mismo computed_at -> desempata el id mayor (el último insertado)
        _add_sample(hist, "espn_tennis_atp_1", computed_at=T0, result=None, start_time=start, rest_a=rest_a)
    hist.save_event_result(
        event_id="espn_tennis_atp_1", sport="TENNIS", result="PARTICIPANT_A_WON", source="test", recorded_at=start + timedelta(hours=3)
    )

    first = build_tennis_training_dataset(hist)
    second = build_tennis_training_dataset(hist)

    assert first.samples[0].features == second.samples[0].features
    assert first.samples[0].features["rest_days"]["participant_a"] == 9.0


# ---------------------------------------------------------------------
# Split temporal (legado, 2 particiones)
# ---------------------------------------------------------------------


def test_split_dataset_temporally_validation_is_most_recent_and_never_random(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    import random

    order = list(range(10))
    random.Random(42).shuffle(order)
    for i in order:
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        _add_sample(hist, f"espn_tennis_atp_{i}", T0 + timedelta(minutes=i), result=result)

    dataset = build_tennis_training_dataset(hist)
    train, validation = split_dataset_temporally(dataset, validation_fraction=0.2)

    assert train.size + validation.size == 10
    assert max(s.data_cutoff_timestamp for s in train.samples) < min(s.data_cutoff_timestamp for s in validation.samples)


def test_split_dataset_temporally_no_event_id_appears_in_both_partitions(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    for i in range(10):
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        start = T0 + timedelta(days=i, hours=8)
        for snapshot_offset in range(3):
            _add_sample(
                hist,
                f"espn_tennis_atp_{i}",
                T0 + timedelta(days=i, hours=snapshot_offset),
                result=result if snapshot_offset == 2 else None,
                recorded_at=start + timedelta(hours=3),
                start_time=start,
            )

    dataset = build_tennis_training_dataset(hist)
    assert dataset.size == 10  # un snapshot por evento, ya no 30 filas
    assert dataset.exclusions["superseded_same_event"] == 20

    train, validation = split_dataset_temporally(dataset, validation_fraction=0.2)

    assert {s.event_id for s in train.samples}.isdisjoint({s.event_id for s in validation.samples})


# ---------------------------------------------------------------------
# Split temporal de 3 particiones (train / validación / test)
# ---------------------------------------------------------------------


def _dataset_of(tmp_path, n):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, n)
    return build_tennis_training_dataset(hist)


def test_split_events_temporally_is_chronological_disjoint_and_covers_everything(tmp_path):
    dataset = _dataset_of(tmp_path, 20)

    train, validation, test = split_events_temporally(dataset)

    assert (train.size, validation.size, test.size) == (12, 4, 4)  # 60/20/20
    ids = [{s.event_id for s in part.samples} for part in (train, validation, test)]
    assert ids[0].isdisjoint(ids[1]) and ids[0].isdisjoint(ids[2]) and ids[1].isdisjoint(ids[2])
    assert sum(len(i) for i in ids) == 20
    assert max(s.event_start_time for s in train.samples) < min(s.event_start_time for s in validation.samples)
    assert max(s.event_start_time for s in validation.samples) < min(s.event_start_time for s in test.samples)


def test_split_events_temporally_is_deterministic_and_never_random(tmp_path):
    dataset = _dataset_of(tmp_path, 20)

    first = split_events_temporally(dataset)
    second = split_events_temporally(dataset)

    for a, b in zip(first, second):
        assert [s.event_id for s in a.samples] == [s.event_id for s in b.samples]


def test_split_events_temporally_rejects_samples_without_start_time(tmp_path):
    dataset = _dataset_of(tmp_path, 10)
    dataset.samples[0].event_start_time = None

    with pytest.raises(ValueError):
        split_events_temporally(dataset)


def test_split_events_temporally_rejects_invalid_fractions_and_too_few_events(tmp_path):
    dataset = _dataset_of(tmp_path, 10)
    with pytest.raises(ValueError):
        split_events_temporally(dataset, train_fraction=0.9, validation_fraction=0.2)
    with pytest.raises(ValueError):
        split_events_temporally(_dataset_of_n(tmp_path, 2))


def _dataset_of_n(tmp_path, n):
    hist = HistoryRepository(db_path=tmp_path / f"hist_{n}.db")
    _seed_events(hist, n)
    return build_tennis_training_dataset(hist)


# ---------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------


def test_train_below_policy_minimum_returns_insufficient_history(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, MIN_EVENTS_FOR_RETRAIN - 1)
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir)  # mínimo por defecto = 150

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("mínimo" in w for w in warnings)
    assert not models_dir.exists() or list(models_dir.glob("*.joblib")) == []


def test_train_refuses_when_any_partition_is_below_30_events(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 60)  # 36/12/12 -> validación y test < 30 eventos
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir, min_samples=10)

    assert status == ModelStatus.INSUFFICIENT_HISTORY
    assert artifact is None
    assert any("particiones" in w for w in warnings)


def test_train_produces_spec_v2_artifact_with_provenance(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 40)
    models_dir = tmp_path / "models"

    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, **SMALL)

    assert status == ModelStatus.TRAINED
    assert artifact.training_dataset_spec_version == TRAINING_DATASET_SPEC_VERSION
    assert artifact.min_snapshot_lead_minutes == 60
    assert artifact.n_training_samples == 40
    assert (artifact.n_train_events, artifact.n_validation_events, artifact.n_test_events) == (24, 8, 8)
    all_ids = set(artifact.train_event_ids) | set(artifact.validation_event_ids) | set(artifact.test_event_ids)
    assert len(all_ids) == 40  # particiones disjuntas que cubren todo
    assert set(artifact.train_event_ids).isdisjoint(artifact.validation_event_ids)
    assert set(artifact.train_event_ids).isdisjoint(artifact.test_event_ids)
    assert set(artifact.validation_event_ids).isdisjoint(artifact.test_event_ids)
    assert artifact.model_version.startswith("tennis_baseline_logreg_v1_")
    assert artifact.file_path.exists()
    assert artifact.calibration_version is None
    assert artifact.artifact_sha256 == hashlib.sha256(artifact.file_path.read_bytes()).hexdigest()
    metadata = json.loads((models_dir / f"{artifact.model_version}.metadata.json").read_text(encoding="utf-8"))
    assert metadata["training_dataset_spec_version"] == TRAINING_DATASET_SPEC_VERSION
    assert metadata["test_event_ids"] == artifact.test_event_ids


def test_train_with_relaxed_minimums_is_always_a_rejected_candidate(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 40)

    _, artifact, warnings = train_tennis_baseline_model(hist, models_dir=tmp_path / "models", **SMALL)

    assert artifact.candidate_status == CANDIDATE_REJECTED
    assert artifact.min_events_policy == 10
    assert any("mínimos por debajo de la política" in w for w in warnings)


def test_train_metrics_match_direct_computation_on_validation(tmp_path):
    """precision/recall/f1/ece deben coincidir EXACTAMENTE con llamar
    sklearn/src.backtesting.metrics directamente sobre la misma partición
    de validación -- confirma reutilización literal, no una fórmula
    reimplementada."""
    from sklearn.metrics import f1_score, precision_score, recall_score

    from src.backtesting.metrics import ece as compute_ece

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 40)
    models_dir = tmp_path / "models"

    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, **SMALL)
    assert status == ModelStatus.TRAINED

    dataset = build_tennis_training_dataset(hist)
    _, validation_dataset, _ = split_events_temporally(dataset)
    loaded = load_latest_tennis_artifact(models_dir, registry=promote_artifacts_for_test(models_dir))
    assert loaded is not None
    pipeline, loaded_artifact = loaded

    X_val = [
        [_vectorize_features(s.features, loaded_artifact.round_categories).get(c, float("nan")) for c in loaded_artifact.feature_columns]
        for s in validation_dataset.samples
    ]
    y_val = [s.label for s in validation_dataset.samples]
    val_proba = pipeline.predict_proba(X_val)[:, 1]
    val_pred = (val_proba >= 0.5).astype(int)

    assert artifact.precision == pytest.approx(precision_score(y_val, val_pred, zero_division=0))
    assert artifact.recall == pytest.approx(recall_score(y_val, val_pred, zero_division=0))
    assert artifact.f1 == pytest.approx(f1_score(y_val, val_pred, zero_division=0))
    assert artifact.ece == pytest.approx(compute_ece(list(y_val), list(val_proba)))


def test_train_discovers_round_categories_only_from_train_split(tmp_path):
    """Una ronda que solo aparece en los eventos MÁS RECIENTES (validación/
    test) no debe aparecer en round_categories."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 36)
    for k in range(4):  # los 4 eventos más recientes -> test
        i = 36 + k
        add_preevent_sample(
            hist, f"espn_tennis_atp_{i:04d}", T0 + timedelta(days=i),
            result="PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON",
            round_context="Semifinal", rest_a=8.0 if i % 2 == 0 else 1.0, rest_b=1.0 if i % 2 == 0 else 8.0,
        )

    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=tmp_path / "models", **SMALL)

    assert status == ModelStatus.TRAINED
    assert "Semifinal" not in artifact.round_categories


def test_train_is_promotion_eligible_when_policy_met_and_beats_baseline_out_of_sample(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 160)  # política real: >=150 eventos, particiones >=30 (96/32/32)

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=tmp_path / "models")

    assert status == ModelStatus.TRAINED
    assert artifact.n_test_events >= 30
    assert artifact.test_brier < artifact.baseline_test_brier
    assert artifact.test_log_loss < artifact.baseline_test_log_loss
    assert artifact.candidate_status == CANDIDATE_PROMOTION_ELIGIBLE
    assert not any("CANDIDATO RECHAZADO" in w for w in warnings)


def test_train_registers_rejected_candidate_when_not_beating_baseline_on_temporal_test(tmp_path):
    """Entrenamiento+validación con la relación features->resultado
    original, test temporal INVERTIDO: el modelo queda peor que la baseline
    (tasa base) fuera de muestra -> candidato rechazado, nunca activable."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 128)  # primeros 128 eventos: relación normal
    _seed_events(hist, 32, start_index=128, invert=True)  # 32 eventos más recientes: invertidos
    models_dir = tmp_path / "models"

    status, artifact, warnings = train_tennis_baseline_model(hist, models_dir=models_dir)

    assert status == ModelStatus.TRAINED
    assert artifact.test_brier > artifact.baseline_test_brier
    assert artifact.candidate_status == CANDIDATE_REJECTED
    assert any("no supera la baseline" in w for w in warnings)
    # Aunque se promoviera por error en el registro, el cargador rechaza a un REJECTED_CANDIDATE:
    meta_path = models_dir / f"{artifact.model_version}.metadata.json"
    policy = promote_artifacts_for_test(models_dir)  # (reescribe candidate_status)
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["candidate_status"] = CANDIDATE_REJECTED
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    assert load_latest_tennis_artifact(models_dir, registry=policy) is None


def test_train_never_fits_on_test_period_labels(tmp_path):
    """Cambiar SOLO las etiquetas del periodo de test no puede alterar el
    modelo ajustado (coeficientes idénticos): el test no participa del ajuste."""
    import joblib

    def _train(invert_test, name):
        hist = HistoryRepository(db_path=tmp_path / f"hist_{name}.db")
        _seed_events(hist, 128)
        _seed_events(hist, 32, start_index=128, invert=invert_test)
        _, artifact, _ = train_tennis_baseline_model(hist, models_dir=tmp_path / f"models_{name}")
        return joblib.load(artifact.file_path).named_steps["logreg"].coef_.copy()

    assert (_train(False, "a") == _train(True, "b")).all()


# ---------------------------------------------------------------------
# Inference contract
# ---------------------------------------------------------------------


def _preevent_record(cutoff, event_id="espn_tennis_atp_live_1"):
    return make_tennis_record(event_id, start_time=cutoff + timedelta(hours=3), status=EventStatus.SCHEDULED)


def _train_loadable(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    _seed_events(hist, 40)
    models_dir = tmp_path / "models"
    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, **SMALL)
    assert status == ModelStatus.TRAINED
    loaded = load_latest_tennis_artifact(models_dir, registry=promote_artifacts_for_test(models_dir))
    assert loaded is not None
    return loaded, artifact


def test_predict_without_trained_artifact_is_honest_and_never_fabricates():
    cutoff = datetime.now(timezone.utc)

    output = predict_tennis_baseline(_preevent_record(cutoff), TennisFeatureInputs(), cutoff, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert output.model_version is None
    assert isinstance(output.missing_features, list) and len(output.missing_features) > 0


def test_predict_with_trained_artifact_returns_valid_probability_for_preevent_record(tmp_path):
    loaded, artifact = _train_loadable(tmp_path)
    cutoff = datetime.now(timezone.utc)

    output = predict_tennis_baseline(_preevent_record(cutoff), TennisFeatureInputs(), cutoff, loaded_artifact=loaded)

    assert output.model_status == ModelStatus.TRAINED
    assert 0.0 <= output.p_model_yes <= 1.0
    assert output.model_version == artifact.model_version


@pytest.mark.parametrize(
    "start_offset_hours,status",
    [
        (-1, EventStatus.SCHEDULED),  # el corte de datos es POSTERIOR al inicio
        (0, EventStatus.SCHEDULED),  # corte == inicio (no estrictamente anterior)
        (3, EventStatus.LIVE),
        (3, EventStatus.FINAL),
        (3, EventStatus.UNKNOWN),
    ],
)
def test_predict_refuses_probability_for_non_preevent_context(tmp_path, start_offset_hours, status):
    loaded, _ = _train_loadable(tmp_path)
    cutoff = datetime.now(timezone.utc)
    record = make_tennis_record("espn_tennis_atp_x", start_time=cutoff + timedelta(hours=start_offset_hours), status=status)

    output = predict_tennis_baseline(record, TennisFeatureInputs(), cutoff, loaded_artifact=loaded)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None
    assert output.model_version is None


def test_predict_refuses_probability_without_event_start_time(tmp_path):
    loaded, _ = _train_loadable(tmp_path)
    cutoff = datetime.now(timezone.utc)

    output = predict_tennis_baseline(
        make_tennis_record("espn_tennis_atp_x", start_time=None), TennisFeatureInputs(), cutoff, loaded_artifact=loaded
    )

    assert output.p_model_yes is None


def test_predict_from_features_matches_predict_tennis_baseline_exactly(tmp_path):
    loaded, _ = _train_loadable(tmp_path)
    cutoff = datetime.now(timezone.utc)
    record = _preevent_record(cutoff)
    inputs = TennisFeatureInputs()
    live_output = predict_tennis_baseline(record, inputs, cutoff, loaded_artifact=loaded)

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
    _seed_events(hist, 40)
    status, tennis_artifact, _ = train_tennis_baseline_model(hist, models_dir=models_dir, **SMALL)
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

    loaded_tennis = load_latest_tennis_artifact(models_dir=models_dir, registry=promote_artifacts_for_test(models_dir))
    assert loaded_tennis is not None
    assert loaded_tennis[1].model_version == tennis_artifact.model_version

    loaded_mlb = mlb_registry.load_latest_mlb_artifact(models_dir=models_dir)
    assert loaded_mlb is not None
    assert loaded_mlb[1].model_version == fake_mlb_artifact.model_version
    assert loaded_mlb[0] == fake_mlb_model_object  # el "modelo" MLB cargado no es el pipeline de tenis
