"""Contrato de Payoff (Fase 3, Paso 3.0). Ver CONTRACTS_FASE3.md §3 y
Corrección C (PLAN_MASTER_FASE3.md §2).

`PayoffEstimate` sustituye, como punto de entrada de EV neto, el
`NotImplementedError` deliberado de `compute_ev_yes_neto`/
`compute_ev_no_neto` (Fase 2, `src/signals/expected_value.py`, sin
cambios). `net_ev_status=UNKNOWN` es el estado correcto mientras no
exista evidencia real de costos -- nunca se inventa un costo para forzar
`COMPUTED`.

Este módulo define únicamente el contrato de datos. La función que lo
produce vive en `src/payoff/payoff_model.py` (Paso 3.2, no implementado
todavía).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from src.models.schemas import StrictModel
from src.signals.signal_schema import Side


class NetEvStatus(str, Enum):
    COMPUTED = "COMPUTED"
    UNKNOWN = "UNKNOWN"


def _require_utc_aware(value: Optional[datetime], field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {value!r}")


class PayoffEstimate(StrictModel):
    """Ver CONTRACTS_FASE3.md §3 para el detalle campo por campo."""

    opportunity_id: str
    side: Side
    platform: str
    entry_price: Optional[float] = None
    payout: Optional[float] = None
    loss: Optional[float] = None
    entry_fee: Optional[float] = None
    estimated_exit_fee: Optional[float] = None
    spread: Optional[float] = None
    slippage_estimate: Optional[float] = None
    ev_to_settlement: Optional[float] = None
    ev_to_planned_exit: Optional[float] = None
    breakeven_probability: Optional[float] = None
    max_acceptable_entry_price: Optional[float] = None
    net_ev_status: NetEvStatus
    cost_evidence_refs: List[str] = Field(default_factory=list)
    computed_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PayoffEstimate":
        _require_utc_aware(self.computed_at, "computed_at")

        if self.net_ev_status == NetEvStatus.COMPUTED:
            if self.ev_to_settlement is None:
                raise ValueError(
                    "net_ev_status=COMPUTED exige ev_to_settlement no nulo "
                    "(CONTRACTS_FASE3.md §3, invariante 1)"
                )
            if not self.cost_evidence_refs:
                raise ValueError(
                    "net_ev_status=COMPUTED exige cost_evidence_refs no vacío "
                    "(CONTRACTS_FASE3.md §3, invariante 1)"
                )
        elif self.net_ev_status == NetEvStatus.UNKNOWN:
            if self.ev_to_settlement is not None or self.ev_to_planned_exit is not None:
                raise ValueError(
                    "net_ev_status=UNKNOWN exige ev_to_settlement y ev_to_planned_exit "
                    "en None (CONTRACTS_FASE3.md §3, invariante 2)"
                )
        return self
