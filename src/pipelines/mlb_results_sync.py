"""Sincronización de `event_results` MLB (Paso 5b, Bloque 3 -- prerrequisito
del entrenamiento real, ver PLAN_PHASE2.md §5-B).

Reutiliza `MlbConnector.get_schedule()` (ya existente, sin cambios) mirando
hacia fechas PASADAS -- no requiere ningún endpoint nuevo: el propio
payload de `schedule` ya incluye `teams.{away,home}.isWinner`/`score` para
juegos `Final` (verificado contra la API real antes de implementar esto).

READ-ONLY salvo por `HistoryRepository.save_event_result` -- nunca toca
`normalized_records`, `event_snapshots` ni `feature_snapshots`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.connectors.mlb import MlbConnector
from src.storage.history_repository import HistoryRepository

_VALID_MLB_A_WON = "PARTICIPANT_A_WON"
_VALID_MLB_B_WON = "PARTICIPANT_B_WON"


@dataclass
class MlbResultsSyncSummary:
    dates_scanned: List[str] = field(default_factory=list)
    recorded: int = 0
    already_recorded: int = 0
    not_yet_decided: int = 0
    postponed: int = 0
    cancelled: int = 0
    skipped_ambiguous: int = 0
    fetch_errors: List[str] = field(default_factory=list)


def default_lookback_dates(today: Optional[date] = None, lookback_days: int = 3) -> List[str]:
    """`lookback_days=3` (hoy + 2 anteriores) por defecto: suficiente para
    capturar la resolución de la mayoría de postergaciones sin escanear
    histórico ilimitado (decisión explícita, ver informe del Bloque 3)."""
    today = today or date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(lookback_days)]


def _map_game_result(game: Dict[str, Any]) -> Optional[str]:
    """Devuelve `PARTICIPANT_A_WON`/`PARTICIPANT_B_WON`/`POSTPONED`/
    `CANCELLED`, o `None` si el juego aún no está decidido o el resultado
    es ambiguo (nunca se fabrica un ganador)."""
    status = (game.get("status") or {}).get("detailedState")
    if status == "Postponed":
        return "POSTPONED"
    if status == "Cancelled":
        return "CANCELLED"
    if status != "Final":
        return None

    teams = game.get("teams") or {}
    away_winner = (teams.get("away") or {}).get("isWinner")
    home_winner = (teams.get("home") or {}).get("isWinner")
    if away_winner is True and home_winner is not True:
        return _VALID_MLB_A_WON
    if home_winner is True and away_winner is not True:
        return _VALID_MLB_B_WON
    return None  # ambiguo (ambos True/False/ausentes) -- no se fabrica


def sync_mlb_event_results(
    mlb: MlbConnector,
    history_repository: HistoryRepository,
    dates: List[str],
) -> MlbResultsSyncSummary:
    """Por cada fecha en `dates` (YYYY-MM-DD), obtiene el schedule y
    registra en `HistoryRepository` el resultado de cada juego ya decidido
    (`Final`/`Postponed`/`Cancelled`). Idempotente A NIVEL DE LLAMADOR:
    antes de insertar, consulta `get_results_for_event` -- si el evento ya
    tiene un resultado registrado, no vuelve a insertar. Esto NO cambia el
    contrato append-only de `HistoryRepository` (que sigue sin deduplicar
    nada por sí mismo, ver `test_registering_same_result_twice_is_allowed...`);
    es una optimización de la capa llamadora para no generar una fila
    nueva cada vez que este sync se re-ejecute sobre el mismo juego ya
    concluido."""
    summary = MlbResultsSyncSummary(dates_scanned=list(dates))

    for d in dates:
        result = mlb.get_schedule(d)
        if not result.ok:
            summary.fetch_errors.append(f"{d}: {result.error}")
            continue

        games = MlbConnector.extract_games(result.data)
        for game in games:
            game_pk = game.get("gamePk")
            if game_pk is None:
                continue
            event_id = f"mlb_{game_pk}"

            mapped_result = _map_game_result(game)
            if mapped_result is None:
                status = (game.get("status") or {}).get("detailedState")
                if status == "Final":
                    summary.skipped_ambiguous += 1
                else:
                    summary.not_yet_decided += 1
                continue

            if history_repository.get_results_for_event(event_id):
                summary.already_recorded += 1
                continue

            history_repository.save_event_result(
                event_id=event_id,
                sport="MLB",
                result=mapped_result,
                source="mlb_results_sync",
                recorded_at=datetime.now(timezone.utc),
            )
            summary.recorded += 1
            if mapped_result == "POSTPONED":
                summary.postponed += 1
            elif mapped_result == "CANCELLED":
                summary.cancelled += 1

    return summary
