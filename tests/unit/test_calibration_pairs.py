"""Corrección metodológica YES/NO (CONTINUITY.md §0.38): un par por EVENTO,
lado NO = espejo exacto, n por bucket contado en eventos."""
from __future__ import annotations

import pytest

from src.backtesting.metrics import brier_score
from src.evaluation.calibration_pairs import (
    DuplicateEventPairError,
    EventCalibrationPair,
    build_event_pairs,
    compute_calibration_coverage,
    mirror_to_no_side,
)


def test_build_event_pairs_one_pair_per_event_maps_results_to_participant_a():
    pairs = build_event_pairs([("e1", 0.7, "PARTICIPANT_A_WON"), ("e2", 0.3, "PARTICIPANT_B_WON")])
    assert [(p.event_id, p.p_participant_a_wins, p.y_participant_a_won) for p in pairs] == [("e1", 0.7, 1), ("e2", 0.3, 0)]


def test_duplicate_event_id_raises_yes_and_no_are_not_independent_samples():
    with pytest.raises(DuplicateEventPairError):
        build_event_pairs([("e1", 0.7, "PARTICIPANT_A_WON"), ("e1", 0.7, "PARTICIPANT_A_WON")])


def test_rows_without_probability_are_skipped_never_fabricated():
    assert build_event_pairs([("e1", None, "PARTICIPANT_A_WON")]) == []


def test_non_binary_result_is_rejected():
    with pytest.raises(ValueError):
        build_event_pairs([("e1", 0.5, "CANCELLED")])


def test_pair_validates_ranges():
    with pytest.raises(ValueError):
        EventCalibrationPair("e", 1.2, 1)
    with pytest.raises(ValueError):
        EventCalibrationPair("e", 0.5, 2)


def test_no_side_is_the_exact_mirror_one_minus_p_and_one_minus_y():
    p, y = mirror_to_no_side(EventCalibrationPair("e1", 0.8, 1))
    assert (p, y) == (pytest.approx(0.2), 0)


def test_mirror_has_same_brier_so_it_is_not_independent_evidence():
    pairs = build_event_pairs([("a", 0.9, "PARTICIPANT_A_WON"), ("b", 0.2, "PARTICIPANT_A_WON"), ("c", 0.6, "PARTICIPANT_B_WON")])
    yes = brier_score([p.y_participant_a_won for p in pairs], [p.p_participant_a_wins for p in pairs])
    mirrored = [mirror_to_no_side(p) for p in pairs]
    no = brier_score([y for _, y in mirrored], [p for p, _ in mirrored])
    assert no == pytest.approx(yes)


def test_regression_unmirrored_no_side_pairs_collapse_to_artificial_observed_frequency_of_half():
    """Reproduce el defecto de los diagnósticos ad hoc: `signal_inputs.p_model`
    es p_model_yes en AMBAS oportunidades. Emparejarlo SIN invertir con `y`
    del lado NO (complementario) da una frecuencia observada de exactamente
    0.5 en cada bucket aunque el modelo sea perfecto."""
    events = [(f"e{i}", 0.9, "PARTICIPANT_A_WON") for i in range(10)]
    pairs = build_event_pairs(events)
    y_yes = [p.y_participant_a_won for p in pairs]
    p_yes = [p.p_participant_a_wins for p in pairs]
    # Defecto: filas YES (y) y NO (1-y) con la MISMA p sin invertir
    defective_y = y_yes + [1 - y for y in y_yes]
    defective_p = p_yes + p_yes
    assert sum(defective_y) / len(defective_y) == 0.5  # frecuencia artificial
    assert len(defective_y) == 2 * len(pairs)  # n duplicado
    # Correcto: un par por evento, frecuencia real 1.0
    assert sum(y_yes) / len(y_yes) == 1.0
    assert brier_score(y_yes, p_yes) < brier_score(defective_y, defective_p)


def test_coverage_counts_events_per_bucket_and_reports_empty_buckets_insufficient():
    pairs = [EventCalibrationPair(f"e{i}", 0.55, i % 2) for i in range(40)]
    cov = compute_calibration_coverage(pairs)

    assert cov.n_events == 40
    assert len(cov.buckets) == 10
    populated = [b for b in cov.buckets if b.n_events > 0]
    assert len(populated) == 1 and populated[0].n_events == 40 and populated[0].sufficient
    assert len(cov.insufficient_buckets) == 9  # vacíos = insuficientes
    assert cov.fully_covered is False  # no se puede afirmar calibración global


def test_coverage_fully_covered_only_when_every_bucket_has_30_events():
    pairs = [EventCalibrationPair(f"e{b}_{i}", b / 10 + 0.05, i % 2) for b in range(10) for i in range(30)]
    cov = compute_calibration_coverage(pairs)
    assert cov.fully_covered is True

    pairs.pop()  # un solo evento menos en un bucket
    assert compute_calibration_coverage(pairs).fully_covered is False


def test_coverage_rejects_duplicate_event_pairs():
    with pytest.raises(DuplicateEventPairError):
        compute_calibration_coverage([EventCalibrationPair("e", 0.5, 1), EventCalibrationPair("e", 0.5, 0)])


def test_concentrated_predictions_never_cover_all_buckets_even_with_many_events():
    """Un modelo cuyas probabilidades se concentran en pocos buckets (lo
    esperable con 2 features de descanso/ronda) no puede afirmarse calibrado
    en todo el rango por mucho `n` total: no se baja el umbral de 30."""
    pairs = [EventCalibrationPair(f"e{i}", 0.45 + 0.1 * (i % 3), i % 2) for i in range(372)]
    cov = compute_calibration_coverage(pairs)
    assert cov.n_events == 372
    assert cov.fully_covered is False
    assert len(cov.insufficient_buckets) >= 7
