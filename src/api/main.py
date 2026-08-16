"""Servicio HTTP local del motor (Fase 5). Ver `HTTP_SERVICE_SPEC.md`.

Capa de transporte pura -- traduce `ResolverError`/excepciones de
conector a códigos HTTP. Ningún cálculo de predicción/policy/edge/EV
vive aquí.

Arrancar con:
    source .venv/bin/activate
    uvicorn src.api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from src.api.analysis_service import analyze_ticker
from src.api.event_resolver import ResolverError
from src.api.positions_router import router as positions_router
from src.api.robinhood_mapper import MappingError, map_robinhood_symbol_to_kalshi_ticker
from src.api.schemas import AnalyzeResponse, RobinhoodMapRequest, RobinhoodMapResponse

# Diagnóstico temporal (localizar el bloqueo de /analyze en tenis): sin esto
# los logger.info(...) de entrada/salida/tiempo añadidos en toda la cadena
# de /analyze nunca se ven -- uvicorn configura sus propios loggers
# (uvicorn/uvicorn.access/uvicorn.error), pero no toca el root logger del
# que cuelgan los loggers de este proyecto (logging.getLogger(__name__)),
# que por defecto queda en WARNING sin ningún handler.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prediction Market Engine — servicio HTTP local",
    description=(
        "Expone el motor de análisis (Fase 1-4) vía HTTP. Analiza únicamente eventos de Kalshi "
        "(MLB/tenis) -- Robinhood no es una fuente de datos del motor, `POST /map/robinhood` solo "
        "traduce un symbol de Robinhood al ticker Kalshi correspondiente. Ver HTTP_SERVICE_SPEC.md "
        "y ROBINHOOD_KALSHI_MAPPER_SPEC.md."
    ),
    version="5.0.0",
)

# Phase 6 Tramo 2: API read/register/prepare sobre Position Management
# (src.positions, ya auditado). Aditivo -- no toca /analyze ni
# /map/robinhood. Cero ejecución de órdenes reales: browser-extension ->
# FastAPI -> service/repository -> SQLite, nunca al revés.
app.include_router(positions_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/analyze/{ticker}", response_model=AnalyzeResponse)
def analyze(ticker: str) -> AnalyzeResponse:
    try:
        return analyze_ticker(ticker)
    except ResolverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001 -- nunca un 200 fabricado ante un fallo real de conector
        logger.exception("fallo inesperado analizando ticker=%s", ticker)
        raise HTTPException(status_code=502, detail=f"fallo real al analizar {ticker!r}: {exc!r}") from exc


@app.post("/map/robinhood", response_model=RobinhoodMapResponse)
def map_robinhood(request: RobinhoodMapRequest) -> RobinhoodMapResponse:
    """Resuelve ÚNICAMENTE `symbol` de Robinhood -> ticker de mercado
    Kalshi -- no invoca el motor de análisis. `GET /analyze/{ticker}` con
    el `kalshi_ticker` resultante es un paso HTTP independiente (ver
    `ROBINHOOD_KALSHI_MAPPER_SPEC.md` §5). Toda la lógica de mapeo vive en
    `map_robinhood_symbol_to_kalshi_ticker` (incluida su propia
    observabilidad -- symbol/candidato/estrategia/ticker quedan
    registrados por ese módulo en cada intento, éxito o fallo); esta
    capa solo traduce `MappingError` a `HTTPException`, igual que
    `analyze()` hace con `ResolverError`.
    """
    try:
        result = map_robinhood_symbol_to_kalshi_ticker(request.symbol, robinhood_start_time=request.game_start)
    except MappingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:  # noqa: BLE001 -- nunca un 200 fabricado ante un fallo real de conector
        logger.exception("fallo inesperado mapeando symbol=%s", request.symbol)
        raise HTTPException(status_code=502, detail=f"fallo real al mapear {request.symbol!r}: {exc!r}") from exc

    return RobinhoodMapResponse(
        kalshi_ticker=result.kalshi_ticker,
        strategy=result.strategy,
        candidate=result.candidate,
        sport=result.sport.value,
        sport_key=result.sport_key,
    )
