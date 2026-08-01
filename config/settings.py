"""Configuración central de Fase 1: timeouts, reintentos, rate limits, rutas.

No contiene secretos. Las API keys se leen únicamente desde variables de
entorno en el propio conector que las necesita (ver `src/connectors/odds_api.py`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = PROJECT_ROOT / "data" / "engine.db"
# Paso 5a: artefactos de modelo entrenado (joblib + metadata JSON sidecar).
DATA_MODELS_DIR = PROJECT_ROOT / "data" / "models"
# Fase 3: respaldos comprimidos de data/engine.db -- ver DATA_RETENTION_POLICY.md.
DATA_BACKUPS_DIR = PROJECT_ROOT / "data" / "backups"


@dataclass(frozen=True)
class HttpPolicy:
    """Política de red por fuente: timeouts cortos, reintentos limitados,
    backoff exponencial y un mínimo espaciado entre requests (rate limit)."""

    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 8.0
    min_seconds_between_requests: float = 0.0
    user_agent: str = "prediction-market-engine/0.1 (read-only research client)"


# MLB Stats API: pública, sin key, tolera un ritmo normal.
MLB_POLICY = HttpPolicy(
    timeout_seconds=10.0,
    max_retries=2,
    backoff_base_seconds=0.5,
    min_seconds_between_requests=0.2,
)

# SofaScore: API interna no documentada. Ser muy conservador.
SOFASCORE_POLICY = HttpPolicy(
    timeout_seconds=10.0,
    max_retries=2,
    backoff_base_seconds=1.0,
    backoff_max_seconds=10.0,
    min_seconds_between_requests=1.0,
)

# ESPN: fuente complementaria/fallback, pública.
ESPN_TENNIS_POLICY = HttpPolicy(
    timeout_seconds=10.0,
    max_retries=2,
    backoff_base_seconds=0.5,
    min_seconds_between_requests=0.3,
)

# Kalshi API pública (read-only, sin auth para market data de series abiertas).
KALSHI_POLICY = HttpPolicy(
    timeout_seconds=10.0,
    max_retries=2,
    backoff_base_seconds=0.5,
    min_seconds_between_requests=0.3,
)

# The Odds API: cuota limitada por key. Nunca hacer polling agresivo.
ODDS_API_POLICY = HttpPolicy(
    timeout_seconds=10.0,
    max_retries=1,
    backoff_base_seconds=1.0,
    min_seconds_between_requests=1.0,
)

MLB_BASE_URL = "https://statsapi.mlb.com"
SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"
ESPN_TENNIS_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis"
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

KALSHI_SPORT_SERIES = {
    "MLB": "KXMLBGAME",
    "ATP": "KXATPMATCH",
    "WTA": "KXWTAMATCH",
}

ODDS_API_KEY_ENV_VAR = "ODDS_API_KEY"


def get_odds_api_key() -> str | None:
    return os.environ.get(ODDS_API_KEY_ENV_VAR) or None


# Tolerancia de tiempo (minutos) para considerar dos eventos como el mismo
# instante al hacer event matching (relojes/fuentes distintas).
# MLB: los horarios de primer lanzamiento son fijos entre fuentes -> tolerancia
#   ajustada, alcanza para cubrir pequeños desfases de reloj/redondeo.
# TENNIS: los partidos juegan "por orden de salida a pista", no a hora fija;
#   es normal y esperado que el horario nominal se desplace varias horas
#   respecto al horario efectivo -> tolerancia mucho más amplia.
EVENT_TIME_MATCH_TOLERANCE_MINUTES = 90
EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT = {
    "MLB": 90,
    "TENNIS": 240,
}

# Umbral de confianza de nombre (0-1) por debajo del cual el matching de
# evento se marca NEEDS_REVIEW en vez de forzarse.
EVENT_NAME_MATCH_MIN_CONFIDENCE = 0.72

for _dir in (DATA_RAW_DIR, DATA_NORMALIZED_DIR, LOGS_DIR, DATA_MODELS_DIR, DATA_BACKUPS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
