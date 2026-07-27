"""Tests del cálculo de features de tenis (Fase 2, Paso 11).

`rest_days`/`tournament_round_context` son las dos únicas features
FULLY_SPECIFIED de tenis en el registry (Paso 1) -- verificadas contra la
API real de ESPN antes de implementar (ver Design Proposal del Paso 11):
`competition.round.displayName` existe y es estable; `competitor.id` es
un identificador numérico estable entre partidos del mismo jugador.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.features.registry import Sport as RegistrySport
from src.features.registry import list_computable_features
from src.features.tennis_features import (
    CURRENT_FEATURE_SET_VERSION,
    TennisFeatureInputs,
    compute_rest_days,
    compute_tennis_features,
    compute_tournament_round_context,
    persist_tennis_feature_snapshot,
)
from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

CUTOFF = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)


def _tennis_record(start_time=None, tournament_round="Qualifying 1st Round"):
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_183021",
        participant_a="Edas Butvilas",
        participant_b="Clement Tabur",
        start_time=start_time or datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc),
    )
    record.model_inputs.context = {
        "tournament_name": "Millennium Estoril Open",
        "tour": "ATP",
        "participant_a_espn_id": "11754",
        "participant_b_espn_id": "3512",
        "tournament_round": tournament_round,
    }
    return record


# ---------------------------------------------------------------------
# compute_rest_days
# ---------------------------------------------------------------------


def test_compute_rest_days_exact_value_with_known_prior_match():
    match_start = datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc)
    prior = [datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)]
    assert compute_rest_days(match_start, prior, CUTOFF) == pytest.approx(6.0)


def test_compute_rest_days_none_without_prior_match():
    match_start = datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc)
    assert compute_rest_days(match_start, [], CUTOFF) is None


def test_compute_rest_days_excludes_matches_not_yet_knowable_before_cutoff():
    """Un partido previo con start_time posterior al cutoff (aunque
    anterior al partido a predecir) no podía saberse todavía en ese
    instante -- se excluye, nunca contamina rest_days."""
    match_start = datetime(2026, 7, 28, 11, 0, tzinfo=timezone.utc)
    cutoff = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    known_prior = datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)
    leaked_prior = datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc)  # después del cutoff

    result = compute_rest_days(match_start, [known_prior, leaked_prior], cutoff)

    assert result == pytest.approx((match_start - known_prior).total_seconds() / 86400.0)


def test_compute_rest_days_uses_most_recent_prior_match():
    match_start = datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc)
    prior = [
        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc),  # el más reciente
    ]
    assert compute_rest_days(match_start, prior, CUTOFF) == pytest.approx(4.0)


def test_compute_rest_days_none_when_match_start_time_missing():
    assert compute_rest_days(None, [datetime(2026, 7, 20, tzinfo=timezone.utc)], CUTOFF) is None


# ---------------------------------------------------------------------
# compute_tournament_round_context
# ---------------------------------------------------------------------


def test_compute_tournament_round_context_direct_passthrough():
    assert compute_tournament_round_context("Qualifying 1st Round") == "Qualifying 1st Round"


def test_compute_tournament_round_context_none_when_absent():
    assert compute_tournament_round_context(None) is None


# ---------------------------------------------------------------------
# compute_tennis_features (orquestador)
# ---------------------------------------------------------------------


def test_orchestrator_computes_both_features_with_known_history():
    record = _tennis_record()
    inputs = TennisFeatureInputs(
        prior_match_start_times={
            "participant_a": [datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)],
            "participant_b": [],
        }
    )
    features, missing, warnings = compute_tennis_features(record, inputs, CUTOFF)

    assert features["rest_days"]["participant_a"] == pytest.approx(6.0)
    assert features["rest_days"]["participant_b"] is None
    assert features["tournament_round_context"] == "Qualifying 1st Round"
    assert "rest_days.participant_b" in missing
    assert "rest_days.participant_a" not in missing
    assert warnings == []


def test_orchestrator_reports_missing_when_nothing_known():
    record = _tennis_record(tournament_round=None)
    inputs = TennisFeatureInputs()
    features, missing, warnings = compute_tennis_features(record, inputs, CUTOFF)

    assert features["rest_days"]["participant_a"] is None
    assert features["rest_days"]["participant_b"] is None
    assert features["tournament_round_context"] is None
    assert set(missing) == {"rest_days.participant_a", "rest_days.participant_b", "tournament_round_context"}


def test_orchestrator_warns_on_out_of_range_rest_days():
    record = _tennis_record(start_time=datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc))
    inputs = TennisFeatureInputs(
        prior_match_start_times={"participant_a": [datetime(2026, 7, 1, tzinfo=timezone.utc)], "participant_b": []}
    )
    features, missing, warnings = compute_tennis_features(record, inputs, datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert any("rest_days.participant_a" in w for w in warnings)


def test_orchestrator_rejects_non_tennis_record():
    record = NormalizedRecord(sport=Sport.MLB, event_id="mlb_1", participant_a="A", participant_b="B")
    with pytest.raises(ValueError):
        compute_tennis_features(record, TennisFeatureInputs(), CUTOFF)


def test_orchestrator_rejects_naive_cutoff():
    record = _tennis_record()
    with pytest.raises(ValueError):
        compute_tennis_features(record, TennisFeatureInputs(), datetime(2026, 7, 26, 10, 0))


# ---------------------------------------------------------------------
# persist_tennis_feature_snapshot
# ---------------------------------------------------------------------


def test_persist_writes_feature_snapshot(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _tennis_record()
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=CUTOFF)
    inputs = TennisFeatureInputs(
        prior_match_start_times={"participant_a": [datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)], "participant_b": []}
    )

    feature_snapshot_id, features, missing, warnings = persist_tennis_feature_snapshot(
        hist, record, snap_id, inputs, CUTOFF
    )

    rows = hist.get_feature_snapshots_for_event(record.event_id)
    assert len(rows) == 1
    assert rows[0]["id"] == feature_snapshot_id
    assert rows[0]["feature_set_version"] == CURRENT_FEATURE_SET_VERSION


# ---------------------------------------------------------------------
# Compatibilidad exacta con el Feature Registry del Paso 1
# ---------------------------------------------------------------------


def test_every_computable_tennis_feature_has_a_matching_function_in_this_module():
    import src.features.tennis_features as module

    for feature in list_computable_features(sport=RegistrySport.TENNIS):
        assert hasattr(module, feature.compute_function_name), (
            f"'{feature.name}' declara compute_function_name="
            f"{feature.compute_function_name!r} pero no existe esa función en tennis_features.py"
        )


def test_no_stray_compute_function_without_registry_backing():
    import src.features.tennis_features as module

    registry_function_names = {
        f.compute_function_name for f in list_computable_features(sport=RegistrySport.TENNIS)
    }
    module_compute_functions = {
        name for name in dir(module) if name.startswith("compute_") and callable(getattr(module, name))
    }
    module_compute_functions.discard("compute_tennis_features")
    assert module_compute_functions == registry_function_names


def test_orchestrator_output_uses_exact_registry_feature_names():
    record = _tennis_record()
    features, _missing, _warnings = compute_tennis_features(record, TennisFeatureInputs(), CUTOFF)
    registry_names = {f.name for f in list_computable_features(sport=RegistrySport.TENNIS)}
    assert set(features.keys()) == registry_names


def test_feature_set_version_matches_registry():
    from src.features.registry import CURRENT_FEATURE_SET_VERSION as REGISTRY_VERSION

    assert CURRENT_FEATURE_SET_VERSION == REGISTRY_VERSION
