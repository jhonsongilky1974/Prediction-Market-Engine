"""Configuración validada de servidor para Trading Advisory -- Tramo 5B.
Nunca enviable por request (solo overridable explícitamente en tests o en
la construcción del servicio) -- evita que un cliente controle límites de
riesgo/staleness silenciosamente. Valor ausente o inválido en cualquier
campo obligatorio falla al construirse (fail-closed), nunca un default
silencioso en tiempo de request.

Valores piloto conservadores (aprobados explícitamente para Tramo 5B, ver
CONTINUITY.md): sujetos a recalibración futura, nunca a expansión
silenciosa dentro de este módulo.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import ConfigDict, model_validator

from src.models.schemas import StrictModel
from src.positions.money import require_non_negative


class AdvisoryConfig(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_adverse_move_cents: Decimal = Decimal(10)
    """Distancia (en centavos) desde `avg_entry_price_cents` hasta el
    stop informativo -- nunca ejecutado, ver `src.advisory.invalidation`."""

    max_allowed_staleness_seconds: float = 15.0
    """Antigüedad máxima admitida de `prices_timestamp` en
    `AdvisoryPositionsEvaluateRequest` -- excederla rechaza la
    evaluación completa (fail-closed), ver `src.api.advisory_service`."""

    contract_price_min_cents: int = 1
    contract_price_max_cents: int = 99
    """Dominio real de un precio de contrato Kalshi (centavos enteros
    1-99, ver `src.positions.money`) -- `stop_price_cents` se clampa
    SIEMPRE a este rango, nunca puede salir de él."""

    @model_validator(mode="after")
    def _validate_invariants(self) -> "AdvisoryConfig":
        require_non_negative(self.max_adverse_move_cents, "max_adverse_move_cents")
        if self.max_allowed_staleness_seconds <= 0:
            raise ValueError(
                f"max_allowed_staleness_seconds debe ser > 0: {self.max_allowed_staleness_seconds}"
            )
        if not (0 < self.contract_price_min_cents < self.contract_price_max_cents <= 99):
            raise ValueError(
                "contract_price_min_cents/contract_price_max_cents fuera del dominio válido "
                f"de un contrato Kalshi: [{self.contract_price_min_cents}, {self.contract_price_max_cents}]"
            )
        return self


DEFAULT_ADVISORY_CONFIG = AdvisoryConfig()
