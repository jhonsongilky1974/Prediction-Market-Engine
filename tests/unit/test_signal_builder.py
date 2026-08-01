"""Tests de `build_signal_inputs` (Fase 4, Paso 4.1). Ver
`ORCHESTRATOR_SPEC.md` §4.2/§11 y §1.1 (primer compositor real de
`SignalInputs` del proyecto). No re-testea `market_price_yes/no`,
`compute_edge_yes/no`, `compute_ev_yes/no_bruto` (Fase 2, ya cubiertos
en sus propios archivos de test) -- solo que este módulo los combina
correctamente, propaga `None` honestamente, y aísla el caso
`exchange_fee` poblado (D-3).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.calibration.schemas import CalibrationOutput
from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import MarketData, NormalizedRecord, Sport
from src.orchestration.signal_builder import build_signal_inputs
from src.signals.signal_schema import Side
from src.uncertainty.quality_score import QualityScoreOutput

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides) -> NormalizedRecord:
    base = dict(
        sport=Sport.MLB,
        event_id="mlb_1",
        market_id="KXMLBGAME-TEST",
        participant_a="A",
        participant_b="B",
        market=MarketData(yes_bid=0.40, yes_ask=0.45, no_bid=0.55, no_ask=0.60),
    )
    base.update(overrides)
    return NormalizedRecord(**base)


def _model_not_trained() -> PModelOutput:
    return PModelOutput(
        p_model_yes=None,
        model_version=None,
        model_status=ModelStatus.MODEL_NOT_TRAINED,
        feature_set_version="phase2_registry_v1",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )


def _model_trained(p_model_yes: float) -> PModelOutput:
    return PModelOutput(
        p_model_yes=p_model_yes,
        model_version="mlb_baseline_v1",
        model_status=ModelStatus.TRAINED,
        feature_set_version="phase2_registry_v1",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )


def _quality_score(confidence=0.8) -> QualityScoreOutput:
    return QualityScoreOutput(confidence=confidence, confidence_method="HEURISTIC_V1", confidence_config_version="quality_score_v1")


def test_model_not_trained_propagates_none_honestly():
    record = _record()
    model_output = _model_not_trained()

    signal_inputs, exchange_fee_unexpected = build_signal_inputs(
        record, model_output, _quality_score(), Side.YES, NOW
    )

    assert signal_inputs.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert signal_inputs.p_model is None
    assert signal_inputs.edge is None
    assert signal_inputs.ev_bruto is None
    assert signal_inputs.ev_neto is None
    assert exchange_fee_unexpected is False


def test_market_price_none_when_ask_missing():
    record = _record(market=MarketData())  # sin yes_ask/no_ask
    signal_inputs, _ = build_signal_inputs(record, _model_not_trained(), _quality_score(), Side.YES, NOW)
    assert signal_inputs.market_price is None


def test_side_yes_and_no_use_the_correct_market_price():
    record = _record()
    signal_yes, _ = build_signal_inputs(record, _model_not_trained(), _quality_score(), Side.YES, NOW)
    signal_no, _ = build_signal_inputs(record, _model_not_trained(), _quality_score(), Side.NO, NOW)
    assert signal_yes.market_price == 0.45  # yes_ask
    assert signal_no.market_price == 0.60  # no_ask
    assert signal_yes.side == Side.YES
    assert signal_no.side == Side.NO


def test_edge_and_ev_bruto_computed_when_model_trained():
    record = _record()
    model_output = _model_trained(0.60)
    signal_inputs, _ = build_signal_inputs(record, model_output, _quality_score(), Side.YES, NOW)
    assert signal_inputs.p_model == 0.60
    assert signal_inputs.edge is not None
    assert signal_inputs.ev_bruto is not None


def test_exchange_fee_populated_unexpectedly_is_captured_not_silenced():
    """D-3 sin resolver: exchange_fee nunca está poblado en producción hoy
    -- si alguna vez lo estuviera CON un modelo entrenado,
    compute_ev_yes_neto lanza NotImplementedError (Fase 2, sin tocar).
    Debe capturarse explícitamente (señal operacional, ORCHESTRATOR_SPEC.md
    §5), nunca silenciarse como cualquier otro error, y ev_neto debe
    quedar honestamente en None."""
    record = _record(market=MarketData(yes_bid=0.40, yes_ask=0.45, no_bid=0.55, no_ask=0.60, exchange_fee=0.02))
    model_output = _model_trained(0.60)

    signal_inputs, exchange_fee_unexpected = build_signal_inputs(
        record, model_output, _quality_score(), Side.YES, NOW
    )

    assert exchange_fee_unexpected is True
    assert signal_inputs.ev_neto is None


def test_confidence_and_method_propagate_from_quality_score_output():
    record = _record()
    signal_inputs, _ = build_signal_inputs(
        record, _model_not_trained(), _quality_score(confidence=0.55), Side.YES, NOW
    )
    assert signal_inputs.confidence == 0.55
    assert signal_inputs.confidence_method == "HEURISTIC_V1"


# ---------------------------------------------------------------------
# Calibración real (CALIBRATION_SPEC.md §4.2) -- p_model_calibrated
# sustituye a p_model_raw cuando existe, nunca al revés.
# ---------------------------------------------------------------------


def _calibration_output(p_model_raw, p_model_calibrated, calibration_version="tennis_calibrator_platt_v1_test"):
    return CalibrationOutput(
        p_model_raw=p_model_raw,
        p_model_calibrated=p_model_calibrated,
        model_version="mlb_baseline_v1",
        calibration_version=calibration_version if p_model_calibrated is not None else None,
        calibration_method="PLATT_V1" if p_model_calibrated is not None else None,
        calibrated_at=NOW if p_model_calibrated is not None else None,
        prediction_timestamp=NOW,
        data_cutoff_timestamp=NOW,
    )


def test_calibrated_probability_is_used_instead_of_raw_when_available():
    record = _record()
    model_output = _model_trained(0.60)
    calibration_output = _calibration_output(p_model_raw=0.60, p_model_calibrated=0.72)

    signal_inputs, _ = build_signal_inputs(
        record, model_output, _quality_score(), Side.YES, NOW, calibration_output
    )

    assert signal_inputs.p_model == 0.72
    # edge/ev_bruto deben derivar del valor CALIBRADO, no del crudo --
    # se recalculan por separado sin calibración para comparar.
    raw_signal_inputs, _ = build_signal_inputs(record, model_output, _quality_score(), Side.YES, NOW)
    assert signal_inputs.edge != raw_signal_inputs.edge
    assert signal_inputs.ev_bruto != raw_signal_inputs.ev_bruto


def test_no_calibration_output_preserves_raw_probability_unchanged():
    """Regresión: sin calibration_output (comportamiento previo a este
    paso), el resultado debe ser IDÉNTICO al de antes -- MLB hoy, y
    cualquier registro sin calibrador emparejado."""
    record = _record()
    model_output = _model_trained(0.60)

    with_none, _ = build_signal_inputs(record, model_output, _quality_score(), Side.YES, NOW, None)
    without_param, _ = build_signal_inputs(record, model_output, _quality_score(), Side.YES, NOW)

    assert with_none.p_model == without_param.p_model == 0.60


def test_calibration_output_with_p_model_calibrated_none_preserves_raw():
    """calibration_version=None (sin calibrador real, p.ej. MLB) --
    p_model_calibrated es None, debe usarse el crudo, nunca fabricar
    nada."""
    record = _record()
    model_output = _model_trained(0.60)
    calibration_output = _calibration_output(p_model_raw=0.60, p_model_calibrated=None)

    signal_inputs, _ = build_signal_inputs(
        record, model_output, _quality_score(), Side.YES, NOW, calibration_output
    )
    assert signal_inputs.p_model == 0.60


def test_calibrated_probability_used_for_model_not_trained_is_still_none():
    """Si el modelo no está entrenado, p_model_raw ya es None y
    CalibrationOutput.p_model_calibrated también lo es (invariante de
    CONTRACTS_FASE3.md §2) -- nada que sustituir."""
    record = _record()
    model_output = _model_not_trained()
    calibration_output = _calibration_output(p_model_raw=None, p_model_calibrated=None)

    signal_inputs, _ = build_signal_inputs(
        record, model_output, _quality_score(), Side.YES, NOW, calibration_output
    )
    assert signal_inputs.p_model is None
