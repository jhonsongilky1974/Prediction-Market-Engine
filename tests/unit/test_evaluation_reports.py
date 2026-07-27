"""Tests de `src/evaluation/reports.py` (Paso 10): comparación Baseline 0
(mercado) vs Baseline 1 (logreg, Paso 5a/5b) vs Baseline 2 (Elo, Paso 6)
sobre el mismo universo de filas, más segmentación por edge/confianza/
liquidez."""
from __future__ import annotations

import functools
from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.dataset import BacktestRow, build_backtest_dataset
from src.backtesting.splitter import walk_forward_splits
from src.evaluation.reports import (
    compare_baselines,
    segment_by_confidence,
    segment_by_edge,
    segment_by_liquidity,
)
from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models import registry as model_registry
from src.models.base import ModelStatus
from src.models.mlb_baseline import predict_mlb_baseline_from_features, train_mlb_baseline_model
from src.models.mlb_elo import predict_mlb_elo, train_mlb_elo_model
from src.models.schemas import DataQuality, MarketData, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository
from src.uncertainty.quality_score import QualityScoreOutput

T0 = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# Helpers de fixture (dataset sintético con market data + team identity,
# suficiente para que logreg Y Elo puedan entrenar sobre el mismo evento).
# ---------------------------------------------------------------------


def _record(event_id, away_team_id, home_team_id, start_time, yes_ask=0.50):
    record = NormalizedRecord(
        sport=Sport.MLB,
        event_id=event_id,
        participant_a="Away Team",
        participant_b="Home Team",
        start_time=start_time,  # requerido por build_mlb_elo_game_sequence (Paso 6)
        market=MarketData(yes_ask=yes_ask, no_ask=round(1.0 - yes_ask, 2)),
    )
    record.model_inputs.context = {"away_team_id": away_team_id, "home_team_id": home_team_id}
    return record


def _synthetic_features(era_a, era_b):
    """Feature set completo (mismo estilo que test_mlb_baseline.py) --
    evita que SimpleImputer reciba columnas enteramente NaN (todas las
    filas del fixture comparten el resto de valores, solo era_a/era_b
    varía según el resultado)."""
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


def _add_row(hist, event_id, computed_at, away_team_id, home_team_id, result, era_a=3.5, era_b=4.2, yes_ask=0.50):
    record = _record(event_id, away_team_id, home_team_id, start_time=computed_at, yes_ask=yes_ask)
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=computed_at)
    hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=computed_at,
        features=_synthetic_features(era_a, era_b),
        computed_at=computed_at,
    )
    hist.save_event_result(
        event_id=event_id, sport="MLB", result=result, source="test", recorded_at=computed_at + timedelta(hours=3)
    )


def _build_synthetic_history(tmp_path, n_rows=20):
    """Filas espaciadas por DÍAS (no minutos): el resultado de cada evento
    se registra 3h después de sus propias features (`_add_row`), y el
    corte de cada fold del walk-forward es el `data_cutoff_timestamp` de
    la ÚLTIMA fila de train de ESE fold -- con eventos separados por
    minutos, ese corte nunca alcanza el resultado de ningún evento
    anterior (siempre a 3h de distancia) y el `HistoryRepository` temporal
    del fold quedaría sin ninguna muestra etiquetada. Con espaciado de
    días, los resultados de eventos anteriores sí caen dentro del corte de
    folds posteriores -- igual que en producción real."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    # Equipos rotando entre unos pocos IDs para que Elo tenga partidos
    # repetidos por equipo (mismo estilo que test_mlb_elo.py).
    for i in range(n_rows):
        away, home = (i % 4) + 1, (i % 4) + 5
        result = "PARTICIPANT_A_WON" if i % 2 == 0 else "PARTICIPANT_B_WON"
        era_a, era_b = (2.5, 5.0) if result == "PARTICIPANT_A_WON" else (5.0, 2.5)
        _add_row(hist, f"mlb_{i}", T0 + timedelta(days=i), away, home, result, era_a=era_a, era_b=era_b)
    return hist


def _fit_fn_baseline_1(history_repository, models_dir):
    """`train_mlb_baseline_model` devuelve metadata del artefacto
    (`MlbTrainedArtifact`), no el modelo cargado -- igual que en
    producción (`scripts/train_mlb_model.py`), hay que recargarlo vía
    `load_latest_mlb_artifact` para obtener la tupla `(model, artifact)`
    que `predict_mlb_baseline_from_features` espera. Este glue vive en el
    adaptador (provisto por quien invoca), no en `reports.py`, que
    permanece agnóstico."""
    status, artifact, warnings = train_mlb_baseline_model(history_repository, models_dir=models_dir, min_samples=8)
    if status != ModelStatus.TRAINED:
        return status, None, warnings
    loaded = model_registry.load_latest_mlb_artifact(models_dir=models_dir)
    return status, loaded, warnings


def _adapters():
    fit_fn_1 = _fit_fn_baseline_1
    predict_fn_1 = lambda row, artifact: predict_mlb_baseline_from_features(row.features, artifact)
    fit_fn_2 = functools.partial(train_mlb_elo_model, min_games=5)
    predict_fn_2 = lambda row, artifact: predict_mlb_elo(row.record, artifact).p_model_yes
    return fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2


# ---------------------------------------------------------------------
# compare_baselines -- end to end sobre fixtures sintéticas
# ---------------------------------------------------------------------


def test_compare_baselines_evaluates_on_same_universe_of_test_rows(tmp_path):
    hist = _build_synthetic_history(tmp_path, n_rows=20)
    dataset = build_backtest_dataset(hist)
    assert dataset.size == 20
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    expected_test_rows = sum(
        len(fold.test_rows) for fold in walk_forward_splits(hist, dataset, min_train_size=8, test_block_size=4)
    )
    assert expected_test_rows > 0

    report = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=8, test_block_size=4
    )

    # Baseline 0 nunca excluye filas por estado de entrenamiento -- con
    # yes_ask siempre poblado en el fixture, debe cubrir EXACTAMENTE el
    # universo de test rows del walk-forward.
    assert report.baseline_reports["baseline_0_market"].n_predictions == expected_test_rows
    # Baseline 1/2 no pueden evaluar MÁS filas que las de test disponibles.
    assert report.baseline_reports["baseline_1_logreg"].n_predictions <= expected_test_rows
    assert report.baseline_reports["baseline_2_elo"].n_predictions <= expected_test_rows
    assert report.baseline_reports["baseline_1_logreg"].n_predictions > 0
    assert report.baseline_reports["baseline_2_elo"].n_predictions > 0


def test_baseline_0_report_uses_market_price_directly(tmp_path):
    hist = _build_synthetic_history(tmp_path, n_rows=20)
    dataset = build_backtest_dataset(hist)
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    report = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=8, test_block_size=4
    )

    baseline_0 = report.baseline_reports["baseline_0_market"]
    assert baseline_0.n_predictions > 0
    assert baseline_0.brier is not None
    # yes_ask=0.50 constante en el fixture -- Brier de una predicción
    # constante 0.5 contra etiquetas binarias es exactamente 0.25.
    assert baseline_0.brier == pytest.approx(0.25)


def test_edge_segments_excludes_baseline_0(tmp_path):
    hist = _build_synthetic_history(tmp_path, n_rows=20)
    dataset = build_backtest_dataset(hist)
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    report = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=8, test_block_size=4
    )

    assert "baseline_0_market" not in report.edge_segments
    assert "baseline_1_logreg" in report.edge_segments
    assert "baseline_2_elo" in report.edge_segments


def test_confidence_and_liquidity_segments_present_for_all_three(tmp_path):
    hist = _build_synthetic_history(tmp_path, n_rows=20)
    dataset = build_backtest_dataset(hist)
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    report = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=8, test_block_size=4
    )

    for name in ("baseline_0_market", "baseline_1_logreg", "baseline_2_elo"):
        assert name in report.confidence_segments
        assert name in report.liquidity_segments


def test_min_train_size_and_test_block_size_are_configurable(tmp_path):
    """Distintos valores producen resultados distintos -- confirma que no
    hay un valor fijo oculto, son parámetros reales (no solo los defaults
    documentados)."""
    hist = _build_synthetic_history(tmp_path, n_rows=20)
    dataset = build_backtest_dataset(hist)
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    # min_train_size distinto -> Baseline 0 evalúa un total de filas de
    # test distinto (siempre n_rows - min_train_size, sin importar
    # test_block_size).
    report_min_8 = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=8, test_block_size=4
    )
    report_min_14 = compare_baselines(
        hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2, min_train_size=14, test_block_size=4
    )
    n_min_8 = report_min_8.baseline_reports["baseline_0_market"].n_predictions
    n_min_14 = report_min_14.baseline_reports["baseline_0_market"].n_predictions
    assert n_min_8 != n_min_14

    # test_block_size distinto -> mismo total de filas de test, pero
    # distinta cantidad de folds (distinta frecuencia de reentrenamiento).
    folds_small_block = list(walk_forward_splits(hist, dataset, min_train_size=8, test_block_size=2))
    folds_large_block = list(walk_forward_splits(hist, dataset, min_train_size=8, test_block_size=10))
    assert len(folds_small_block) != len(folds_large_block)


def test_empty_dataset_produces_honest_empty_report(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    dataset = build_backtest_dataset(hist)
    assert dataset.size == 0
    fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2 = _adapters()

    report = compare_baselines(hist, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2)

    for name in ("baseline_0_market", "baseline_1_logreg", "baseline_2_elo"):
        baseline_report = report.baseline_reports[name]
        assert baseline_report.n_predictions == 0
        assert baseline_report.brier is None
        assert baseline_report.calibration == []
    assert any("0 predicciones" in w for w in report.warnings)


def test_defaults_use_documented_values():
    from src.evaluation.reports import (
        DEFAULT_MIN_TRAIN_SIZE_FOR_COMPARISON,
        DEFAULT_TEST_BLOCK_SIZE_FOR_COMPARISON,
    )

    assert DEFAULT_MIN_TRAIN_SIZE_FOR_COMPARISON == 300
    assert DEFAULT_TEST_BLOCK_SIZE_FOR_COMPARISON == 30


# ---------------------------------------------------------------------
# Segmentación -- tests directos, sin pasar por walk-forward completo.
# ---------------------------------------------------------------------


def _quality_score(confidence, market_liquidity):
    return QualityScoreOutput(
        confidence=confidence,
        confidence_method="HEURISTIC_V1",
        confidence_config_version="quality_score_v1",
        components={"market_liquidity": market_liquidity},
        weights={},
    )


def _fake_row(label, confidence=0.5, market_liquidity=0.5, yes_ask=0.50):
    record = NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_fake",
        participant_a="Away",
        participant_b="Home",
        market=MarketData(yes_ask=yes_ask),
        data_quality=DataQuality(needs_review=False),
    )
    return BacktestRow(
        event_id="mlb_fake",
        data_cutoff_timestamp=T0,
        result_recorded_at=T0 + timedelta(hours=3),
        label=label,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        features={},
        record=record,
        p_market_yes=yes_ask,
        p_market_no=round(1.0 - yes_ask, 2),
        quality_score=_quality_score(confidence, market_liquidity),
    )


def test_segment_by_edge_bucket_assignment_exact():
    row_mid = _fake_row(label=1, yes_ask=0.50)  # p_model=0.62 -> edge=0.12 -> bucket [0.10, 0.15)
    row_neg = _fake_row(label=0, yes_ask=0.50)  # p_model=0.40 -> edge=-0.10 -> bucket [-0.10, -0.05)
    row_low_extreme = _fake_row(label=0, yes_ask=0.50)  # p_model=0.05 -> edge=-0.45 -> < -0.25 (clamp)
    row_high_extreme = _fake_row(label=1, yes_ask=0.50)  # p_model=0.95 -> edge=0.45 -> >= 0.25 (clamp)

    pairs = [(row_mid, 0.62), (row_neg, 0.40), (row_low_extreme, 0.05), (row_high_extreme, 0.95)]

    segments = segment_by_edge(pairs)
    labels = {s.segment_label for s in segments}

    assert "[0.10, 0.15)" in labels
    assert "[-0.10, -0.05)" in labels
    assert "< -0.25" in labels
    assert ">= 0.25" in labels
    assert all(s.n_samples == 1 for s in segments)


def test_segment_by_confidence_bucket_assignment_exact():
    row_a = _fake_row(label=1, confidence=0.55)
    row_b = _fake_row(label=0, confidence=0.55)
    row_c = _fake_row(label=1, confidence=0.05)

    pairs = [(row_a, 0.6), (row_b, 0.4), (row_c, 0.6)]
    segments = segment_by_confidence(pairs)
    by_label = {s.segment_label: s for s in segments}

    assert "[0.50, 0.60)" in by_label
    assert by_label["[0.50, 0.60)"].n_samples == 2
    assert "< 0.10" in by_label
    assert by_label["< 0.10"].n_samples == 1


def test_segment_by_liquidity_bucket_assignment_exact():
    row_a = _fake_row(label=1, market_liquidity=0.95)
    pairs = [(row_a, 0.6)]

    segments = segment_by_liquidity(pairs)

    assert len(segments) == 1
    assert segments[0].segment_label == ">= 0.90"
    assert segments[0].n_samples == 1


def test_segment_functions_omit_rows_with_no_component_available():
    row_no_confidence = _fake_row(label=1, confidence=None)
    pairs = [(row_no_confidence, 0.6)]

    assert segment_by_confidence(pairs) == []
