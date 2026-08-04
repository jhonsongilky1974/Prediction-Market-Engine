"""Instrumentación diagnóstica temporal para localizar el punto exacto
donde /analyze deja de avanzar en tenis. Sin efecto funcional: `log_step`
únicamente escribe logs de entrada/salida y tiempo transcurrido alrededor
de un bloque -- nunca cambia su resultado ni absorbe excepciones (la
excepción original se relanza intacta tras loguearla).
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def log_step(logger: logging.Logger, step_name: str, **context: object) -> Iterator[None]:
    ctx = " ".join(f"{key}={value!r}" for key, value in context.items())
    logger.info("-> %s %s", step_name, ctx)
    started_at = time.monotonic()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 -- solo loguea, siempre relanza
        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.info("<- %s FAILED elapsed_ms=%.1f error=%r", step_name, elapsed_ms, exc)
        raise
    else:
        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.info("<- %s OK elapsed_ms=%.1f", step_name, elapsed_ms)
