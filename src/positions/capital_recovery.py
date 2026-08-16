"""Capital recovery -- lógica pura y testeable (Phase 6, Tramo 1, sección
B del alcance autorizado). Ningún import de I/O, SQLite, FastAPI ni de
`src.matching`/`src.payoff`/`src.pricing`: funciones puras sobre
`OrderFill`/`Fee`, testeables sin base de datos.

Regla principal (decisión 2 -- SIN tolerancia configurable en v1):
encontrar la cantidad ENTERA MÍNIMA de contratos cuya venta a
`planned_target_price_cents` produzca

    net_proceeds >= capital_remaining_cents

Fees: mientras la recuperación dependa de fees ESTIMATED o UNKNOWN, el
resultado queda marcado `provisional=True` (decisión 1) -- fee=0 solo se
usa provisionalmente y siempre etiquetado, nunca como si fuera KNOWN.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Optional, Sequence

from src.models.schemas import StrictModel
from src.positions.enums import Achievability, FeeStatus, OrderAction
from src.positions.money import require_exact_cents, require_non_negative, round_half_up_cents
from src.positions.schemas import Fee, OrderFill

_FEE_STATUS_SEVERITY = {FeeStatus.KNOWN: 0, FeeStatus.ESTIMATED: 1, FeeStatus.UNKNOWN: 2}


def aggregate_fee_status(statuses: Sequence[FeeStatus]) -> FeeStatus:
    """Peor-caso (F2, Design Proposal): UNKNOWN si alguno es UNKNOWN;
    si no, ESTIMATED si alguno es ESTIMATED; si no, KNOWN. Una secuencia
    vacía agrega a KNOWN (verdad vacua: no hay ningún fee sin confirmar
    porque no hay ningún fee)."""
    if not statuses:
        return FeeStatus.KNOWN
    return max(statuses, key=lambda s: _FEE_STATUS_SEVERITY[s])


def _fee_cents_used(fee: Fee) -> Decimal:
    """Monto numérico a usar en una suma: el monto real si status !=
    UNKNOWN, 0 si status == UNKNOWN. El status agregado (nunca este
    número por sí solo) es lo que indica si el monto es fiable -- ver
    `aggregate_fee_status`."""
    if fee.status == FeeStatus.UNKNOWN:
        return Decimal(0)
    assert fee.cents is not None  # garantizado por Fee._validate_invariants
    return fee.cents


class CapitalMetrics(StrictModel):
    """Salida de `compute_capital_metrics`. Nombres literales pedidos en
    el alcance autorizado (B): total_capital_at_risk, realized_net_proceeds,
    capital_remaining, open_contracts, average entry/fill values."""

    open_contracts: int
    total_buy_qty: int
    total_sell_qty: int
    total_capital_at_risk_cents: Decimal
    total_capital_at_risk_fee_status: FeeStatus
    realized_net_proceeds_cents: Decimal
    realized_net_proceeds_fee_status: FeeStatus
    capital_remaining_cents: Decimal
    avg_entry_price_cents: Optional[Decimal] = None
    avg_exit_price_cents: Optional[Decimal] = None


def weighted_average_price_cents(fills: Sequence[OrderFill]) -> Optional[Decimal]:
    """Promedio ponderado por qty -- EXCLUSIVAMENTE para campos de
    display (avg_fill_price_cents en `PositionsRepository.apply_fill`,
    avg_entry_price_cents/avg_exit_price_cents en `CapitalMetrics`).
    `None` si `fills` está vacío. El resultado NUNCA debe usarse como
    input de un cálculo de capital -- ver `money.round_half_up_cents`."""
    total_qty = sum(f.qty for f in fills)
    if total_qty == 0:
        return None
    total_notional = sum((f.qty * f.price_cents for f in fills), Decimal(0))
    return round_half_up_cents(total_notional / total_qty)


def compute_capital_metrics(fills: Sequence[OrderFill]) -> CapitalMetrics:
    """Agrega TODOS los fills confirmados de una Position (BUY y SELL,
    de cualquier Order) en las métricas de capital. Suma exacta de
    fills -- el precio promedio (avg_entry_price_cents/avg_exit_price_cents)
    es puramente derivado para DISPLAY, nunca se usa para recomputar
    capital (regla del Caso B del Design Proposal: evita drift de
    redondeo)."""
    buy_qty = 0
    capital_invested = Decimal(0)
    invested_fee_statuses = []

    sell_qty = 0
    capital_recovered = Decimal(0)
    recovered_fee_statuses = []

    for fill in fills:
        require_exact_cents(fill.price_cents, "fill.price_cents")
        fee_used = _fee_cents_used(fill.fee)
        if fill.action == OrderAction.BUY:
            buy_qty += fill.qty
            capital_invested += fill.qty * fill.price_cents + fee_used
            invested_fee_statuses.append(fill.fee.status)
        else:
            sell_qty += fill.qty
            capital_recovered += fill.qty * fill.price_cents - fee_used
            recovered_fee_statuses.append(fill.fee.status)

    open_contracts = buy_qty - sell_qty
    if open_contracts < 0:
        raise ValueError(
            f"open_contracts negativo ({open_contracts}): más contratos SELL ({sell_qty}) "
            f"que BUY ({buy_qty}) entre los fills provistos -- estado incoherente"
        )

    capital_remaining = capital_invested - capital_recovered
    if capital_remaining < 0:
        capital_remaining = Decimal(0)

    avg_entry = weighted_average_price_cents([f for f in fills if f.action == OrderAction.BUY])
    avg_exit = weighted_average_price_cents([f for f in fills if f.action == OrderAction.SELL])

    return CapitalMetrics(
        open_contracts=open_contracts,
        total_buy_qty=buy_qty,
        total_sell_qty=sell_qty,
        total_capital_at_risk_cents=capital_invested,
        total_capital_at_risk_fee_status=aggregate_fee_status(invested_fee_statuses),
        realized_net_proceeds_cents=capital_recovered,
        realized_net_proceeds_fee_status=aggregate_fee_status(recovered_fee_statuses),
        capital_remaining_cents=capital_remaining,
        avg_entry_price_cents=avg_entry,
        avg_exit_price_cents=avg_exit,
    )


class RecoveryPlanResult(StrictModel):
    """Salida de `compute_recovery_plan`. `contracts_to_sell` es
    literalmente `minimum_additional_qty_needed` del alcance autorizado;
    `contracts_remaining_after` es `projected_runner`."""

    contracts_to_sell: int
    gross_proceeds_cents: Decimal
    expected_fees_cents: Decimal
    net_proceeds_cents: Decimal
    contracts_remaining_after: int
    achievability: Achievability
    provisional: bool


def _ceil_div_decimal(numerator: Decimal, denominator: Decimal) -> int:
    return int((numerator / denominator).to_integral_value(rounding=ROUND_CEILING))


def compute_recovery_plan(
    *,
    capital_remaining_cents: Decimal,
    capital_remaining_fee_status: FeeStatus,
    open_contracts: int,
    planned_target_price_cents: Decimal,
    fee_assumption: Fee,
) -> RecoveryPlanResult:
    """Regla principal (decisión 2, SIN tolerancia): mínimo entero `k`
    tal que `net_proceeds(k) >= capital_remaining_cents`, clamped a
    `[0, open_contracts]` (nunca recomienda vender más de lo que hay
    abierto -- test obligatorio #16).

    `provisional=True` si el capital remanente en sí depende de fees no
    confirmados en fills pasados (`capital_remaining_fee_status`) O si
    la venta futura asume un fee no confirmado (`fee_assumption.status`)
    -- dos fuentes de incertidumbre distintas, ambas relevantes."""
    require_exact_cents(planned_target_price_cents, "planned_target_price_cents")
    require_non_negative(capital_remaining_cents, "capital_remaining_cents")
    if open_contracts < 0:
        raise ValueError(f"open_contracts no puede ser negativo: {open_contracts}")

    provisional = (
        capital_remaining_fee_status != FeeStatus.KNOWN
        or fee_assumption.status != FeeStatus.KNOWN
    )

    # Test obligatorio #17: capital ya recuperado -> recovery_qty debe ser 0.
    if capital_remaining_cents <= 0:
        return RecoveryPlanResult(
            contracts_to_sell=0,
            gross_proceeds_cents=Decimal(0),
            expected_fees_cents=Decimal(0),
            net_proceeds_cents=Decimal(0),
            contracts_remaining_after=open_contracts,
            achievability=Achievability.ALREADY_RECOVERED,
            provisional=provisional,
        )

    fee_per_contract = _fee_cents_used(fee_assumption)
    net_per_contract = planned_target_price_cents - fee_per_contract

    if net_per_contract <= 0:
        # Ningún número de contratos vendidos a este precio recupera
        # capital -- la fee (asumida) iguala o supera el precio de venta.
        return RecoveryPlanResult(
            contracts_to_sell=0,
            gross_proceeds_cents=Decimal(0),
            expected_fees_cents=Decimal(0),
            net_proceeds_cents=Decimal(0),
            contracts_remaining_after=open_contracts,
            achievability=Achievability.NOT_RECOVERABLE_AT_THIS_PRICE,
            provisional=provisional,
        )

    k_min = _ceil_div_decimal(capital_remaining_cents, net_per_contract)

    if k_min > open_contracts:
        # Ni vendiendo todo se recupera el capital a este precio (test #16:
        # nunca se recomienda vender más de lo que hay abierto).
        contracts_to_sell = open_contracts
        achievability = Achievability.RECOVERABLE_SELLING_ALL
    else:
        contracts_to_sell = k_min
        achievability = Achievability.FULLY_RECOVERABLE

    gross = contracts_to_sell * planned_target_price_cents
    fees = contracts_to_sell * fee_per_contract
    net = contracts_to_sell * net_per_contract

    return RecoveryPlanResult(
        contracts_to_sell=contracts_to_sell,
        gross_proceeds_cents=gross,
        expected_fees_cents=fees,
        net_proceeds_cents=net,
        contracts_remaining_after=open_contracts - contracts_to_sell,
        achievability=achievability,
        provisional=provisional,
    )


def is_capital_recovery_confirmed(
    *,
    status_is_capital_recovered: bool,
    capital_invested_fee_status: FeeStatus,
    capital_recovered_fee_status: FeeStatus,
) -> bool:
    """Helper explícito para que un futuro consumidor (API/UI) nunca
    tenga que re-derivar esta regla: CAPITAL_RECOVERED solo está
    CONFIRMADO (no provisional) cuando AMBOS lados del cálculo son
    KNOWN -- el fee agregado de los fills de ENTRADA (de otro modo
    `capital_invested_cents` en sí es provisional) Y el de los fills de
    SALIDA (F3 del Design Proposal). Un fee de entrada solo ESTIMATED
    deja el capital objetivo mismo en duda, aunque toda la salida ya
    tenga fees KNOWN."""
    if not status_is_capital_recovered:
        return False
    aggregate = aggregate_fee_status([capital_invested_fee_status, capital_recovered_fee_status])
    return aggregate == FeeStatus.KNOWN
