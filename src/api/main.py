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
from src.api.schemas import AnalyzeResponse

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prediction Market Engine — servicio HTTP local",
    description=(
        "Expone el motor de análisis (Fase 1-4) vía HTTP. Solo eventos de Kalshi (MLB/tenis) -- "
        "Robinhood no está integrado en el proyecto. Ver HTTP_SERVICE_SPEC.md."
    ),
    version="5.0.0",
)


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
