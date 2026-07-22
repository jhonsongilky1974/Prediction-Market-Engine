"""Cálculo de completeness score y manejo de `missing_fields`.

Regla dura: MISSING nunca se convierte en 0 ni en ningún valor por defecto.
El completeness score es puramente informativo (cuántos de los campos
relevantes para el deporte están poblados), nunca se usa para imputar datos.
"""
from __future__ import annotations

from typing import Iterable, List

# Campos "core" cuya ausencia importa para cualquier deporte.
CORE_FIELDS = [
    "start_time",
    "status",
    "participant_a",
    "participant_b",
    "market.yes_bid",
    "market.yes_ask",
    "market.no_bid",
    "market.no_ask",
    "market_close_time",
    "expected_settlement_time",
]

TENNIS_EXTRA_FIELDS = [
    "tennis_variables.ranking_a",
    "tennis_variables.ranking_b",
    "tennis_variables.surface",
    "tennis_variables.last_5",
    "tennis_variables.h2h",
    "tennis_variables.aces",
    "tennis_variables.first_serve_pct",
]

MLB_EXTRA_FIELDS = [
    "mlb.teams.away.probablePitcher",
    "mlb.teams.home.probablePitcher",
    "mlb.boxscore.battingOrder",
    "mlb.probable_pitcher_stats",
    "mlb.injuries",
]


def dedupe_missing_fields(missing_fields: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for field in missing_fields:
        if field not in seen:
            seen.add(field)
            result.append(field)
    return result


def subtract_filled_fields(missing_fields: Iterable[str], filled_fields: Iterable[str]) -> List[str]:
    filled_set = set(filled_fields)
    return [f for f in missing_fields if f not in filled_set]


def compute_completeness_score(missing_fields: Iterable[str], sport: str) -> float:
    """Score en [0,1] = 1 - (missing relevantes / total relevantes).
    No es una medida exacta de todos los campos del esquema; se centra en
    los campos "core" + los específicos del deporte, que son los más
    accionables para decidir si un registro es utilizable."""
    expected = list(CORE_FIELDS)
    if sport == "TENNIS":
        expected += TENNIS_EXTRA_FIELDS
    elif sport == "MLB":
        expected += MLB_EXTRA_FIELDS

    missing_set = set(missing_fields)
    missing_relevant = sum(1 for f in expected if f in missing_set)
    total = len(expected)
    if total == 0:
        return 1.0
    return round(1.0 - (missing_relevant / total), 4)
