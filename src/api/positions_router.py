"""Router HTTP de Phase 6 -- Tramo 2. Capa de transporte pura -- traduce
`PositionsApiError` (`src.api.positions_service`) a `HTTPException`.
Ningún cálculo financiero vive aquí (capital recovery sigue en
`src.positions.capital_recovery`, función pura ya auditada) ni ninguna
escritura SQL directa (todo pasa por `PositionsRepository` inyectado vía
`Depends`).

Frontera obligatoria: browser-extension -> FastAPI -> service/repository
-> SQLite. Este router NUNCA llama a Robinhood, Selenium/Playwright, ni
ejecuta ninguna orden real -- solo prepara/registra/calcula lo que el
usuario ya decidió o ejecutó manualmente.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api import positions_service as service
from src.api.positions_schemas import (
    ComputePlanRequest,
    CreateOrderRequest,
    CreatePositionRequest,
    FillRegistrationResponse,
    OrderListResponse,
    OrderResponse,
    PositionEventListResponse,
    PositionListResponse,
    PositionPlanResponse,
    PositionResponse,
    RegisterFillRequest,
    UpdateOrderRequest,
)
from src.positions.positions_repository import PositionsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/positions", tags=["positions"])


def get_positions_repository() -> PositionsRepository:
    """Dependencia inyectable -- los tests la sobreescriben vía
    `app.dependency_overrides` apuntando a un `tmp_path` (nunca
    `data/engine.db` en tests, mismo principio que
    `tmp_repository`/`tmp_history_repository` en `tests/conftest.py`)."""
    return PositionsRepository()


@router.post("", response_model=PositionResponse)
def create_position(
    request: CreatePositionRequest, repo: PositionsRepository = Depends(get_positions_repository)
) -> PositionResponse:
    try:
        return service.create_position(request, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001 -- nunca un 200 fabricado ante un fallo real
        logger.exception("fallo inesperado creando Position")
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.get("/{position_id}", response_model=PositionResponse)
def get_position(
    position_id: str, repo: PositionsRepository = Depends(get_positions_repository)
) -> PositionResponse:
    try:
        return service.get_position(position_id, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado leyendo Position position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.get("", response_model=PositionListResponse)
def list_positions(
    status: str = Query(default="open", pattern="^(open|all)$"),
    repo: PositionsRepository = Depends(get_positions_repository),
) -> PositionListResponse:
    try:
        positions = service.list_positions(status, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado listando Positions")
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc
    return PositionListResponse(positions=positions)


@router.post("/{position_id}/fills", response_model=FillRegistrationResponse)
def register_fill(
    position_id: str,
    request: RegisterFillRequest,
    repo: PositionsRepository = Depends(get_positions_repository),
) -> FillRegistrationResponse:
    try:
        return service.register_fill(position_id, request, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado registrando fill position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.post("/{position_id}/plan", response_model=PositionPlanResponse)
def compute_plan(
    position_id: str,
    request: ComputePlanRequest,
    repo: PositionsRepository = Depends(get_positions_repository),
) -> PositionPlanResponse:
    try:
        return service.compute_plan(position_id, request, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado calculando plan position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.post("/{position_id}/orders", response_model=OrderResponse)
def create_order(
    position_id: str,
    request: CreateOrderRequest,
    repo: PositionsRepository = Depends(get_positions_repository),
) -> OrderResponse:
    try:
        return service.create_order(position_id, request, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado creando Order position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.patch("/{position_id}/orders/{order_id}", response_model=OrderResponse)
def update_order(
    position_id: str,
    order_id: str,
    request: UpdateOrderRequest,
    repo: PositionsRepository = Depends(get_positions_repository),
) -> OrderResponse:
    try:
        return service.update_order(position_id, order_id, request, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado actualizando Order order_id=%s", order_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc


@router.get("/{position_id}/orders", response_model=OrderListResponse)
def list_orders(
    position_id: str, repo: PositionsRepository = Depends(get_positions_repository)
) -> OrderListResponse:
    try:
        orders = service.list_orders(position_id, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado listando Orders position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc
    return OrderListResponse(orders=orders)


@router.get("/{position_id}/events", response_model=PositionEventListResponse)
def list_events(
    position_id: str, repo: PositionsRepository = Depends(get_positions_repository)
) -> PositionEventListResponse:
    try:
        events = service.list_events(position_id, repository=repo)
    except service.PositionsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("fallo inesperado listando events position_id=%s", position_id)
        raise HTTPException(status_code=500, detail=f"fallo interno inesperado: {exc!r}") from exc
    return PositionEventListResponse(events=events)
