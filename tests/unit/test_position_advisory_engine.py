"""Tests de Phase 6 -- Tramo 5B: `src.advisory.position_advisory_engine`.
Orquestador puro -- verifica que una Position existente se gestiona de
forma independiente de cualquier señal deportiva (Tramo 5B no las
consume en absoluto), que ambos lados reciben tratamiento simétrico, y
que invertir side_a/side_b produce resultados espejo."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.advisory.config import AdvisoryConfig
from src.advisory.enums import PositionManagementAction
from src.advisory.position_advisory_engine import (
    PositionData,
    PositionEvaluationInput,
    build_position_management_advice,
    build_position_management_advisory_result,
)
from src.positions.enums import FeeStatus
from tests.unit.advisory_factories import make_event_identity
from tests.unit.positions_factories import make_fee, make_order, make_position

NOW = datetime(2026, 8, 15, 12, 0, 5, tzinfo=timezone.utc)
CONFIG = AdvisoryConfig()


def test_single_side_position_advice():
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    data = PositionData(position=position, orders=[], fills=[])
    advice = build_position_management_advice(
        data=data,
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=None,
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.position_id == "pos-a"
    assert advice.current_price_cents == Decimal(55)
    assert advice.management_action == PositionManagementAction.HOLD_NO_ACTION_NEEDED
    assert advice.tp1.contracts_to_sell is None
    assert advice.expires_at > advice.generated_at


def test_both_sides_positions_receive_independent_advice():
    identity = make_event_identity()
    pos_a = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=5, capital_invested_cents=Decimal(250),
    )
    pos_b = make_position(
        position_id="pos-b", kalshi_ticker=identity.kalshi_ticker_side_b, side=identity.side_b,
        open_contracts=8, capital_invested_cents=Decimal(400),
    )
    result = build_position_management_advisory_result(
        event_identity=identity,
        positions_data=[PositionData(pos_a, [], []), PositionData(pos_b, [], [])],
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_inputs_by_position_id={},
        config=CONFIG,
        generated_at=NOW,
    )
    assert {a.position_id for a in result.advices} == {"pos-a", "pos-b"}
    assert len(result.exposure.positions) == 2


def test_position_management_independent_of_sport_signal_never_consumed():
    """Tramo 5B no importa src.policy/src.orchestration -- este test
    documenta en tiempo de ejecución que la asesoría de UNA posición no
    cambia si "en teoría" existiera una señal deportiva ENTER/WATCH/PASS
    para el lado contrario: el engine ni siquiera acepta ese input."""
    import inspect

    sig = inspect.signature(build_position_management_advice)
    assert "signal_type" not in sig.parameters
    assert "policy_decision" not in sig.parameters


def test_target_price_produces_actionable_tp1_and_final_exit():
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    evaluation_input = PositionEvaluationInput(
        position_id="pos-a",
        target_exit_price_cents=Decimal(60),
        fee_assumption=make_fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    advice = build_position_management_advice(
        data=PositionData(position, [], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=evaluation_input,
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.tp1.contracts_to_sell is not None
    assert advice.final_exit is not None
    assert advice.final_exit.contracts == position.open_contracts
    assert advice.management_action == PositionManagementAction.MANAGE_ACTION_AVAILABLE


def test_pending_order_forces_manage_attention_required():
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    pending = make_order(position_id="pos-a", status="PLANNED")
    advice = build_position_management_advice(
        data=PositionData(position, [pending], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=None,
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.management_action == PositionManagementAction.MANAGE_ATTENTION_REQUIRED
    assert advice.order_conflicts


def test_strategic_runner_projected_none_when_tp1_unavailable():
    """Corrección de auditoría: si TP1 es UNAVAILABLE (sin target, o fee
    UNKNOWN sin cota segura), el runner estratégico proyectado debe ser
    `None` -- NUNCA `0` (0 significaría "se vende todo legítimamente",
    que es una afirmación distinta y falsa cuando ni siquiera se pudo
    calcular TP1)."""
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    advice = build_position_management_advice(
        data=PositionData(position, [], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=None,  # sin target_exit_price_cents -> TP1 UNAVAILABLE
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.tp1.recovery_kind.value == "UNAVAILABLE"
    assert advice.capital_recovery_runner_contracts is None
    assert advice.strategic_runner_contracts_projected is None


def test_strategic_runner_projected_matches_remaining_after_tp1_by_default():
    """Regla aprobada: por defecto, el runner proyectado coincide
    EXACTAMENTE con los contratos restantes tras TP1
    (`capital_recovery_runner_contracts`) -- nunca 0 salvo que TP1
    legítimamente venda todos los contratos."""
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    evaluation_input = PositionEvaluationInput(
        position_id="pos-a",
        target_exit_price_cents=Decimal(60),
        fee_assumption=make_fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    advice = build_position_management_advice(
        data=PositionData(position, [], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=evaluation_input,
        config=CONFIG,
        generated_at=NOW,
    )
    # 500 / (60-0) = 8.33 -> 9 contratos necesarios, remanente = 1.
    assert advice.tp1.contracts_to_sell == 9
    assert advice.capital_recovery_runner_contracts == 1
    assert advice.strategic_runner_contracts_projected == 1


def test_strategic_runner_projected_can_be_legitimately_zero_on_full_liquidation():
    """Si TP1 vende TODOS los contratos legítimamente (capital
    insuficiente incluso vendiendo todo, o exactamente todo se necesita),
    el runner proyectado puede ser 0 -- distinto de `None`."""
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=5, capital_invested_cents=Decimal(10_000),  # capital muy por encima de lo recuperable
    )
    evaluation_input = PositionEvaluationInput(
        position_id="pos-a",
        target_exit_price_cents=Decimal(60),
        fee_assumption=make_fee(status=FeeStatus.KNOWN, cents=Decimal(0)),
    )
    advice = build_position_management_advice(
        data=PositionData(position, [], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=evaluation_input,
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.tp1.contracts_to_sell == 5  # vende todo lo disponible
    assert advice.capital_recovery_runner_contracts == 0
    assert advice.strategic_runner_contracts_projected == 0


def test_strategic_runner_confirmed_always_none_in_tramo5b():
    identity = make_event_identity()
    position = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=10, capital_invested_cents=Decimal(500),
    )
    advice = build_position_management_advice(
        data=PositionData(position, [], []),
        event_identity=identity,
        current_price_side_a_cents=Decimal(55),
        current_price_side_b_cents=Decimal(45),
        evaluation_input=PositionEvaluationInput(
            position_id="pos-a", target_exit_price_cents=Decimal(60), fee_assumption=make_fee(status=FeeStatus.KNOWN, cents=Decimal(0))
        ),
        config=CONFIG,
        generated_at=NOW,
    )
    assert advice.strategic_runner_contracts_confirmed is None
    assert advice.strategic_runner_contracts_projected == advice.capital_recovery_runner_contracts


def test_inverting_sides_produces_mirror_result():
    identity = make_event_identity()
    identity_swapped = make_event_identity(
        side_a=identity.side_b, side_b=identity.side_a,
        kalshi_ticker_side_a=identity.kalshi_ticker_side_b, kalshi_ticker_side_b=identity.kalshi_ticker_side_a,
        participant_a_canonical=identity.participant_b_canonical, participant_b_canonical=identity.participant_a_canonical,
        participant_a_display=identity.participant_b_display, participant_b_display=identity.participant_a_display,
    )
    pos_a = make_position(
        position_id="pos-a", kalshi_ticker=identity.kalshi_ticker_side_a, side=identity.side_a,
        open_contracts=5, capital_invested_cents=Decimal(250),
    )
    pos_b = make_position(
        position_id="pos-b", kalshi_ticker=identity.kalshi_ticker_side_b, side=identity.side_b,
        open_contracts=8, capital_invested_cents=Decimal(400),
    )
    positions_data = [PositionData(pos_a, [], []), PositionData(pos_b, [], [])]

    original = build_position_management_advisory_result(
        event_identity=identity, positions_data=positions_data,
        current_price_side_a_cents=Decimal(55), current_price_side_b_cents=Decimal(45),
        evaluation_inputs_by_position_id={}, config=CONFIG, generated_at=NOW,
    )
    swapped = build_position_management_advisory_result(
        event_identity=identity_swapped, positions_data=positions_data,
        current_price_side_a_cents=Decimal(45), current_price_side_b_cents=Decimal(55),
        evaluation_inputs_by_position_id={}, config=CONFIG, generated_at=NOW,
    )

    original_by_id = {a.position_id: a for a in original.advices}
    swapped_by_id = {a.position_id: a for a in swapped.advices}
    assert original_by_id["pos-a"].current_price_cents == swapped_by_id["pos-a"].current_price_cents
    assert original_by_id["pos-b"].current_price_cents == swapped_by_id["pos-b"].current_price_cents
    assert original.exposure.exposure_side_a_cents == swapped.exposure.exposure_side_b_cents
    assert original.exposure.exposure_side_b_cents == swapped.exposure.exposure_side_a_cents
