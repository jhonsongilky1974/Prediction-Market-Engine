"""`build_signal_inputs` (Fase 4, Paso 4.1). Ver `ORCHESTRATOR_SPEC.md`
§1.1/§4.2 -- primer código del proyecto en ensamblar `SignalInputs`
(Fase 2, `src/signals/signal_schema.py`) desde datos reales, reutilizando
exclusivamente funciones ya existentes de Fase 2 (`market_pricing.py`,
`edge.py`, `expected_value.py`) más `PModelOutput`/`QualityScoreOutput`
ya calculados por el llamador -- cero cálculo nuevo, solo composición.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional, Tuple

from src.calibration.schemas import CalibrationOutput
from src.models.base import PModelOutput
from src.models.schemas import NormalizedRecord
from src.pricing.market_pricing import market_price_no, market_price_yes
from src.signals.edge import compute_edge_no, compute_edge_yes
from src.signals.expected_value import (
    compute_ev_no_bruto,
    compute_ev_no_neto,
    compute_ev_yes_bruto,
    compute_ev_yes_neto,
)
from src.signals.signal_schema import Side, SignalInputs
from src.uncertainty.quality_score import QualityScoreOutput


def build_signal_inputs(
    record: NormalizedRecord,
    model_output: PModelOutput,
    quality_score_output: QualityScoreOutput,
    side: Side,
    now: datetime,
    calibration_output: Optional[CalibrationOutput] = None,
) -> Tuple[SignalInputs, bool]:
    """Devuelve `(signal_inputs, exchange_fee_populated_unexpectedly)`.

    El segundo valor es `True` únicamente en el caso, inexistente en
    producción hoy (D-3 sin resolver), en que `record.market.exchange_fee`
    está poblado y `compute_ev_*_neto` lanza `NotImplementedError`
    (Fase 2, sin tocar) -- se captura explícitamente (posible evidencia
    nueva para D-3, señal operacional relevante), nunca se silencia como
    un error genérico (`ORCHESTRATOR_SPEC.md` §5).

    `calibration_output` es opcional (`None` preserva el comportamiento
    previo a la calibración real, CALIBRATION_SPEC.md §4.2). Cuando
    `calibration_output.p_model_calibrated` existe, sustituye a
    `model_output.p_model_yes` para TODO cálculo dependiente de la
    probabilidad (`signal_inputs.p_model`, edge, EV bruto/neto) --
    resolución del invariante ya declarado en `CONTRACTS_FASE3.md` §2
    ("en cuanto exista calibration_version, el consumidor debe usar
    p_model_calibrated"), nunca ambos valores mezclados."""
    if calibration_output is not None and calibration_output.p_model_calibrated is not None:
        model_output = dataclasses.replace(model_output, p_model_yes=calibration_output.p_model_calibrated)

    if side == Side.YES:
        market_price = market_price_yes(record)
        edge = compute_edge_yes(model_output, record)
        ev_bruto = compute_ev_yes_bruto(model_output, record)
    else:
        market_price = market_price_no(record)
        edge = compute_edge_no(model_output, record)
        ev_bruto = compute_ev_no_bruto(model_output, record)

    ev_neto: Optional[float] = None
    exchange_fee_populated_unexpectedly = False
    try:
        if side == Side.YES:
            ev_neto = compute_ev_yes_neto(model_output, record, ev_bruto)
        else:
            ev_neto = compute_ev_no_neto(model_output, record, ev_bruto)
    except NotImplementedError:
        exchange_fee_populated_unexpectedly = True

    signal_inputs = SignalInputs(
        event_id=record.event_id,
        sport=record.sport,
        side=side,
        model_status=model_output.model_status,
        p_model=model_output.p_model_yes,
        market_price=market_price,
        edge=edge,
        ev_bruto=ev_bruto,
        ev_neto=ev_neto,
        confidence=quality_score_output.confidence,
        confidence_method=quality_score_output.confidence_method,
        generated_at=now,
    )
    return signal_inputs, exchange_fee_populated_unexpectedly
