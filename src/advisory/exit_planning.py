"""TP1 / recuperación de capital / runner -- Tramo 5B. Reutiliza
LITERALMENTE `src.positions.capital_recovery.compute_recovery_plan` --
ninguna matemática de recuperación se duplica aquí. Este módulo solo
decide QUÉ fee_assumption pasarle y cómo etiquetar el resultado
(EXACT/CONSERVATIVE_ESTIMATE/UNAVAILABLE), y separa explícitamente los
tres runners distintos (Corrección G del precheck de Tramo 5, nunca se
reutiliza el nombre/semántica de `Position.runner_contracts` para nada
proyectado o pre-fill).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence

from src.advisory.enums import Tp1RecoveryKind
from src.advisory.schemas import TP1Advice
from src.positions import capital_recovery
from src.positions.enums import FeeStatus
from src.positions.schemas import Fee, OrderFill, Position


def derive_conservative_fee_from_history(fills: Sequence[OrderFill]) -> Optional[Fee]:
    """Cota conservadora EMPÍRICA: el mayor fee-por-contrato realmente
    observado (`FeeStatus.KNOWN`) entre los fills de ESTA misma posición
    -- nunca una fórmula inventada ni un número fijo de configuración.
    `None` si ningún fill de la posición tiene una fee KNOWN -- en ese
    caso no existe ninguna cota segura derivable (ver `build_tp1_advice`)."""
    known_fee_per_contract: List[Decimal] = [
        (fill.fee.cents / fill.qty)
        for fill in fills
        if fill.fee.status == FeeStatus.KNOWN and fill.fee.cents is not None and fill.qty > 0
    ]
    if not known_fee_per_contract:
        return None
    worst_observed = max(known_fee_per_contract)
    return Fee(status=FeeStatus.ESTIMATED, cents=worst_observed)


def build_tp1_advice(
    *,
    position: Position,
    fills: Sequence[OrderFill],
    target_exit_price_cents: Optional[Decimal],
    fee_assumption: Optional[Fee],
) -> TP1Advice:
    """`target_exit_price_cents=None` -> UNAVAILABLE incondicional (F6.D
    del precheck: "si no se proporciona target ... no fabricar
    recomendación de venta"). `fee_assumption=None` se trata como
    `Fee(status=UNKNOWN)` -- nunca se asume KNOWN por omisión."""
    if target_exit_price_cents is None:
        return TP1Advice(
            recovery_kind=Tp1RecoveryKind.UNAVAILABLE,
            contracts_to_sell=None,
            requires_recalculation=True,
            missing_data=["target_exit_price_cents no proporcionado -- no se calcula TP1"],
        )

    effective_fee = fee_assumption if fee_assumption is not None else Fee(status=FeeStatus.UNKNOWN, cents=None)

    if effective_fee.status == FeeStatus.UNKNOWN:
        derived = derive_conservative_fee_from_history(fills)
        if derived is None:
            return TP1Advice(
                recovery_kind=Tp1RecoveryKind.UNAVAILABLE,
                contracts_to_sell=None,
                requires_recalculation=True,
                missing_data=[
                    "fee_assumption es UNKNOWN y esta posición no tiene ningún fill con fee KNOWN "
                    "del que derivar una cota conservadora -- proporcione fee_assumption explícita "
                    "o espere a que exista un fill con fee confirmada"
                ],
            )
        effective_fee = derived

    capital_remaining = position.capital_remaining_computed
    capital_remaining_fee_status = capital_recovery.aggregate_fee_status(
        [position.capital_invested_fee_status, position.capital_recovered_fee_status]
    )

    result = capital_recovery.compute_recovery_plan(
        capital_remaining_cents=capital_remaining,
        capital_remaining_fee_status=capital_remaining_fee_status,
        open_contracts=position.open_contracts,
        planned_target_price_cents=target_exit_price_cents,
        fee_assumption=effective_fee,
    )

    is_exact = effective_fee.status == FeeStatus.KNOWN and capital_remaining_fee_status == FeeStatus.KNOWN
    recovery_kind = Tp1RecoveryKind.EXACT if is_exact else Tp1RecoveryKind.CONSERVATIVE_ESTIMATE

    return TP1Advice(
        recovery_kind=recovery_kind,
        contracts_to_sell=result.contracts_to_sell,
        evaluated_price_cents=target_exit_price_cents,
        gross_proceeds_cents=result.gross_proceeds_cents,
        expected_fees_cents=result.expected_fees_cents,
        net_proceeds_cents=result.net_proceeds_cents,
        capital_recovery_runner_contracts=result.contracts_remaining_after,
        achievability=result.achievability,
        requires_recalculation=not is_exact,
        missing_data=[],
    )
