"""Sincronización de `event_results` de tenis (Paso 11 -- mismo patrón
que `mlb_results_sync.py`, Paso 5b Bloque 3).

Reutiliza `EspnTennisConnector.get_scoreboard()`/`extract_matches()` (ya
existentes, sin cambios) mirando hacia fechas PASADAS -- no requiere
ningún endpoint nuevo: el propio payload de scoreboard ya incluye
`competitors[].winner` (booleano) para partidos finalizados, verificado
contra la API real de ESPN antes de implementar esto (ver Design Proposal
del Paso 11).

A diferencia de MLB, este módulo NO distingue estados de
POSTPONED/CANCELLED explícitos: no se ha verificado contra datos reales
cómo (ni si) ESPN Tennis los representa -- a diferencia de MLB, donde
`detailedState` "Postponed"/"Cancelled" está confirmado. Un partido en
cualquier estado distinto de "finalizado con ganador inequívoco"
simplemente no se sincroniza todavía y se cuenta como `not_yet_decided` --
honesto, nunca fabricado.

READ-ONLY salvo por `HistoryRepository.save_event_result` -- nunca toca
`normalized_records`, `event_snapshots` ni `feature_snapshots`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.connectors.espn_tennis import EspnTennisConnector
from src.storage.history_repository import HistoryRepository

_VALID_TENNIS_A_WON = "PARTICIPANT_A_WON"
_VALID_TENNIS_B_WON = "PARTICIPANT_B_WON"


@dataclass
class TennisResultsSyncSummary:
    tour: str
    dates_scanned: List[str] = field(default_factory=list)
    recorded: int = 0
    already_recorded: int = 0
    not_yet_decided: int = 0
    skipped_ambiguous: int = 0
    fetch_errors: List[str] = field(default_factory=list)


def default_lookback_dates(today: Optional[date] = None, lookback_days: int = 3) -> List[str]:
    """`lookback_days=3` (hoy + 2 anteriores) por defecto, mismo default
    que `mlb_results_sync.py`. Formato `YYYYMMDD` -- el que espera
    `EspnTennisConnector.get_scoreboard` (distinto del `YYYY-MM-DD` de
    MLB, no se copia el formato a ciegas)."""
    today = today or date.today()
    return [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(lookback_days)]


def _map_match_result(match: Dict[str, Any]) -> Optional[str]:
    """Devuelve `PARTICIPANT_A_WON`/`PARTICIPANT_B_WON`, o `None` si el
    partido aún no está decidido o el resultado es ambiguo (nunca se
    fabrica un ganador). `participant_a`=home, `participant_b`=away --
    mismo orden que `tennis_normalizer.py`."""
    status_type = (match.get("status") or {}).get("type") or {}
    if status_type.get("state") != "post" or not status_type.get("completed"):
        return None

    winners: Dict[str, Optional[bool]] = {"home": None, "away": None}
    for competitor in match.get("competitors", []) or []:
        side = competitor.get("homeAway")
        if side in winners:
            winners[side] = competitor.get("winner")

    if winners["home"] is True and winners["away"] is not True:
        return _VALID_TENNIS_A_WON
    if winners["away"] is True and winners["home"] is not True:
        return _VALID_TENNIS_B_WON
    return None  # ambiguo (ambos True/False/ausentes) -- no se fabrica


def sync_tennis_event_results(
    espn: EspnTennisConnector,
    history_repository: HistoryRepository,
    tour: str,
    dates: List[str],
) -> TennisResultsSyncSummary:
    """Por cada fecha en `dates` (YYYYMMDD), obtiene el scoreboard de
    `tour` y registra en `HistoryRepository` el resultado de cada partido
    ya finalizado con ganador inequívoco. Idempotente A NIVEL DE LLAMADOR:
    antes de insertar, consulta `get_results_for_event` -- si el evento ya
    tiene un resultado registrado, no vuelve a insertar (mismo patrón que
    `sync_mlb_event_results`, no cambia el contrato append-only de
    `HistoryRepository`)."""
    tour = tour.upper()
    summary = TennisResultsSyncSummary(tour=tour, dates_scanned=list(dates))

    for d in dates:
        result = espn.get_scoreboard(tour.lower(), d)
        if not result.ok:
            summary.fetch_errors.append(f"{d}: {result.error}")
            continue

        matches = EspnTennisConnector.extract_matches(result.data)
        for match in matches:
            match_id = match.get("id")
            if match_id is None:
                continue
            event_id = f"espn_tennis_{tour.lower()}_{match_id}"

            mapped_result = _map_match_result(match)
            if mapped_result is None:
                status_type = (match.get("status") or {}).get("type") or {}
                if status_type.get("state") == "post":
                    summary.skipped_ambiguous += 1
                else:
                    summary.not_yet_decided += 1
                continue

            if history_repository.get_results_for_event(event_id):
                summary.already_recorded += 1
                continue

            history_repository.save_event_result(
                event_id=event_id,
                sport="TENNIS",
                result=mapped_result,
                source="tennis_results_sync",
                recorded_at=datetime.now(timezone.utc),
            )
            summary.recorded += 1

    return summary
