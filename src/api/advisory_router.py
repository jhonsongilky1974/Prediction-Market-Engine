"""Router HTTP de Trading Advisory -- Tramo 5B (Position Management
Advisory). Capa de transporte pura -- traduce `AdvisoryApiError`
(`src.api.advisory_service`) a `HTTPException`. Ningún cálculo
financiero vive aquí.

Ambos endpoints son de SOLO LECTURA: `POST /advisory/positions/evaluate`
nunca crea Position/Order, nunca registra fills, nunca cambia estados,
nunca escribe eventos, nunca invoca Robinhood, nunca persiste su propio
resultado (Tramo 5B es stateless por diseño). `GET /positions/exposure`
es una lectura agregada pura, mismo principio.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from src.api import advisory_service as service
from src.api.advisory_schemas import (
    AdvisoryPositionsEvaluateRequest,
    EventIdentityRequest,
    PositionExposureSnapshotResponse,
    PositionManagementAdvisoryResponse,
)
from src.api.positions_router import get_positions_repository
from src.api.rate_limiter import enforce_rate_limit
from src.models.schemas import Sport
from src.positions.positions_repository import PositionsRepository
from src.signals.signal_schema import Side

logger = logging.getLogger(__name__)

router = APIRouter(tags=["advisory"])

# Reutiliza LITERALMENTE la misma dependencia inyectable de
# `positions_router` (no una copia con otro nombre) -- así un test que
# sobreescribe `get_positions_repository` una sola vez cubre tanto los
# endpoints de Tramo 1-4 como los de Tramo 5B contra el MISMO
# `PositionsRepository`/`tmp_path`, sin riesgo de que ambos routers
# terminen apuntando a bases de datos distintas por accidente.


@router.post("/advisory/positions/evaluate", response_model=PositionManagementAdvisoryResponse)
def evaluate_positions(
    request: AdvisoryPositionsEvaluateRequest,
    repo: PositionsRepository = Depends(get_positions_repository),
    _rate_limit: None = Depends(enforce_rate_limit),
) -> PositionManagementAdvisoryResponse:
    try:
        return service.evaluate_positions(request, repository=repo)
    except service.AdvisoryApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001 -- nunca un 200 fabricado ante un fallo real
        logger.exception("fallo inesperado evaluando Position Management Advisory")
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.get("/positions/exposure", response_model=PositionExposureSnapshotResponse)
def get_exposure(
    event_id: str = Query(..., min_length=1),
    sport: Sport = Query(...),
    kalshi_ticker_side_a: str = Query(..., min_length=1),
    kalshi_ticker_side_b: str = Query(..., min_length=1),
    side_a: Side = Query(...),
    side_b: Side = Query(...),
    market_profile: str = Query(..., min_length=1),
    scheduled_start_time: datetime = Query(...),
    participant_a_canonical: Optional[str] = Query(default=None),
    participant_b_canonical: Optional[str] = Query(default=None),
    participant_a_display: Optional[str] = Query(default=None),
    participant_b_display: Optional[str] = Query(default=None),
    repo: PositionsRepository = Depends(get_positions_repository),
) -> PositionExposureSnapshotResponse:
    try:
        identity_request = EventIdentityRequest(
            event_id=event_id,
            sport=sport,
            kalshi_ticker_side_a=kalshi_ticker_side_a,
            kalshi_ticker_side_b=kalshi_ticker_side_b,
            side_a=side_a,
            side_b=side_b,
            participant_a_canonical=participant_a_canonical,
            participant_b_canonical=participant_b_canonical,
            participant_a_display=participant_a_display,
            participant_b_display=participant_b_display,
            scheduled_start_time=scheduled_start_time,
            market_profile=market_profile,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"parámetros de identidad de evento inválidos: {exc}") from exc

    try:
        return service.get_exposure(identity_request, repository=repo)
    except service.AdvisoryApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado calculando exposición event_id=%s", event_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc
