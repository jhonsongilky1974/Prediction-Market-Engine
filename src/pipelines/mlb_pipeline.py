"""Pipeline MLB: ingestión (MLB Stats API + Kalshi) -> normalización ->
event/market matching -> validación de calidad -> almacenamiento local.

READ-ONLY. No calcula P_model/EDGE/EV/CONFIDENCE/señales.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT
from src.connectors.kalshi import KalshiConnector
from src.connectors.mlb import MlbConnector
from src.features.mlb_features import MlbFeatureInputs, RawDataPoint, persist_mlb_feature_snapshot
from src.matching.market_matcher import apply_kalshi_match, find_best_kalshi_event
from src.models.schemas import SourceStatus
from src.normalization.mlb_normalizer import normalize_mlb_game
from src.quality.completeness import compute_completeness_score, dedupe_missing_fields
from src.quality.validators import annotate_duplicate_markets, validate_record
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository


@dataclass
class PipelineStepResult:
    source: str
    step: str
    ok: bool
    count: int = 0
    error: Optional[str] = None


@dataclass
class MlbPipelineResult:
    records: List[Any] = field(default_factory=list)
    steps: List[PipelineStepResult] = field(default_factory=list)


def run_mlb_pipeline(
    date: str,
    repository: Optional[Repository] = None,
    history_repository: Optional[HistoryRepository] = None,
    limit: Optional[int] = None,
    fetch_boxscore: bool = True,
    fetch_pitcher_stats: bool = True,
    fetch_features: bool = True,
) -> MlbPipelineResult:
    steps: List[PipelineStepResult] = []
    mlb = MlbConnector(repository=repository)
    kalshi = KalshiConnector(repository=repository)

    schedule_result = mlb.get_schedule(date)
    if not schedule_result.ok:
        steps.append(PipelineStepResult("mlb", "schedule", False, error=schedule_result.error))
        return MlbPipelineResult(records=[], steps=steps)

    games = MlbConnector.extract_games(schedule_result.data)
    steps.append(PipelineStepResult("mlb", "schedule", True, count=len(games)))
    if limit is not None:
        games = games[:limit]

    kalshi_events_result = kalshi.get_all_events_for_sport("MLB")
    kalshi_events = []
    if kalshi_events_result.ok:
        kalshi_events = KalshiConnector.extract_events(kalshi_events_result.data)
        steps.append(PipelineStepResult("kalshi", "events_KXMLBGAME", True, count=len(kalshi_events)))
    else:
        steps.append(PipelineStepResult("kalshi", "events_KXMLBGAME", False, error=kalshi_events_result.error))

    records = []
    # Paso 5b, Bloque 2: features (Paso 2) calculadas EN VIVO junto al resto
    # del lote, alineadas 1:1 por índice con `records` (ningún filtrado
    # ocurre entre este bucle y el de persistencia -- ver más abajo).
    feature_inputs_list: List[Optional[MlbFeatureInputs]] = []
    feature_cutoffs: List[Optional[datetime]] = []

    for game in games:
        game_pk = game.get("gamePk")
        # Captura ANTES de cualquier fetch de este juego -- se usa como
        # `captured_at` del stat de temporada REUTILIZADO (ver más abajo),
        # nunca como data_cutoff_timestamp (ese se captura DESPUÉS, al
        # terminar los fetches de features, para que la desigualdad
        # estricta de RawDataPoint.usable() se cumpla siempre por
        # construcción, no por casualidad de reloj).
        game_started_at = datetime.now(timezone.utc)

        boxscore_raw = None
        if fetch_boxscore and game_pk is not None:
            bx = mlb.get_boxscore(game_pk)
            if bx.ok:
                boxscore_raw = bx.data
                steps.append(PipelineStepResult("mlb", f"boxscore_{game_pk}", True))
            else:
                steps.append(PipelineStepResult("mlb", f"boxscore_{game_pk}", False, error=bx.error))

        pitcher_stats = None
        if fetch_pitcher_stats:
            pitcher_stats = _fetch_probable_pitcher_stats(mlb, game, steps)

        if fetch_features and history_repository is not None:
            feature_inputs = _fetch_mlb_feature_inputs(mlb, game, pitcher_stats, game_started_at, steps)
            feature_cutoff = datetime.now(timezone.utc)
            feature_inputs_list.append(feature_inputs)
            feature_cutoffs.append(feature_cutoff)
        else:
            feature_inputs_list.append(None)
            feature_cutoffs.append(None)

        record, missing = normalize_mlb_game(game, boxscore_raw, pitcher_stats)
        source_status = {
            "mlb": SourceStatus.OK,
            "kalshi": SourceStatus.OK if kalshi_events_result.ok else SourceStatus.FAILED,
        }

        if kalshi_events:
            match = find_best_kalshi_event(
                record.participant_a,
                record.participant_b,
                record.start_time,
                kalshi_events,
                tolerance_minutes=EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["MLB"],
            )
            apply_kalshi_match(record, match, missing)
        else:
            record.data_quality.match_method = None
            record.data_quality.needs_review = True
            record.data_quality.match_warnings = ["no se pudieron obtener eventos de Kalshi para matching"]
            missing.append("market_id")

        record.data_quality.missing_fields = dedupe_missing_fields(missing)
        record.data_quality.source_status = source_status
        record.data_quality.source_timestamps = {
            "mlb": schedule_result.capture_ts,
            "kalshi": kalshi_events_result.capture_ts,
        }
        record.data_quality.last_updated = datetime.now(timezone.utc)
        record.data_quality.data_completeness_score = compute_completeness_score(
            record.data_quality.missing_fields, "MLB"
        )
        record.data_quality.validation_errors = validate_record(record)

        records.append(record)

    # Detección de mercados duplicados: solo se puede evaluar sobre el LOTE
    # completo, por eso corre después del bucle y antes de persistir (si se
    # guardara dentro del bucle, el registro ya estaría serializado en
    # SQLite antes de que el resto del lote revelara el duplicado). Antes de
    # este fix `find_duplicate_markets` existía pero ningún pipeline lo
    # invocaba nunca.
    annotate_duplicate_markets(records)

    if repository is not None:
        for record, feature_inputs, feature_cutoff in zip(records, feature_inputs_list, feature_cutoffs):
            repository.save_normalized_record(record)
            # Paso 0c: snapshot histórico append-only del MISMO record ya
            # persistido -- nunca antes, nunca en su lugar (ver PLAN_PHASE2.md §11).
            if history_repository is not None:
                snapshot_id = history_repository.save_event_snapshot(record, source="mlb_pipeline_run")
                # Paso 5b, Bloque 2: feature_snapshot del MISMO snapshot ya
                # guardado -- solo si se pidieron features para este record.
                if feature_inputs is not None:
                    persist_mlb_feature_snapshot(
                        history_repository=history_repository,
                        record=record,
                        event_snapshot_id=snapshot_id,
                        inputs=feature_inputs,
                        data_cutoff_timestamp=feature_cutoff,
                    )

    steps.append(PipelineStepResult("pipeline", "normalized_records", True, count=len(records)))
    return MlbPipelineResult(records=records, steps=steps)


def _fetch_probable_pitcher_stats(
    mlb: MlbConnector, game: Dict[str, Any], steps: List[PipelineStepResult]
) -> Optional[Dict[str, Dict[str, Any]]]:
    stats: Dict[str, Dict[str, Any]] = {}
    teams = game.get("teams", {}) or {}
    for side in ("away", "home"):
        pitcher = (teams.get(side, {}) or {}).get("probablePitcher")
        if not pitcher or "id" not in pitcher:
            continue
        result = mlb.get_person_stats(pitcher["id"], group="pitching", stats_type="season")
        if result.ok:
            stats[side] = result.data
            steps.append(PipelineStepResult("mlb", f"people_stats_{pitcher['id']}", True))
        else:
            steps.append(PipelineStepResult("mlb", f"people_stats_{pitcher['id']}", False, error=result.error))
    return stats or None


def _fetch_mlb_feature_inputs(
    mlb: MlbConnector,
    game: Dict[str, Any],
    pitcher_season_stats: Optional[Dict[str, Dict[str, Any]]],
    capture_ts: datetime,
    steps: List[PipelineStepResult],
) -> MlbFeatureInputs:
    """Construye `MlbFeatureInputs` (Paso 2) para UN juego -- Paso 5b,
    Bloque 2. Limitaciones deliberadas, documentadas, no bugs:

    - `reliever_game_logs` queda vacío en todos los lados -> `bullpen_era_recent`
      resuelve honestamente a `None`. Deshabilitado a propósito por costo de
      llamadas (roster + stats de temporada por pitcher + gameLog por
      reliever, ~20+ llamadas extra por equipo) -- preparado para una
      mejora posterior, no implementado ahora (decisión explícita).
    - `opponent_dominant_hand` queda `None` en todos los lados -- requiere
      lineup confirmado con `batSide`, ya documentado en PLAN_PHASE2.md §1.1
      como "a menudo MISSING con antelación"; no se deriva aquí.
    - `key_player_ids` queda vacío -- el plan no define qué hace a un
      jugador "clave"; `il_flag_key_players` resuelve honestamente a `None`
      en vez de inventar esa definición."""
    inputs = MlbFeatureInputs()
    teams = game.get("teams", {}) or {}

    for side, side_key in (("participant_a", "away"), ("participant_b", "home")):
        team_id = (teams.get(side_key, {}) or {}).get("team", {}).get("id")
        pitcher = (teams.get(side_key, {}) or {}).get("probablePitcher") or {}
        pitcher_id = pitcher.get("id")

        # pitcher_season_stat reutiliza el payload YA obtenido por
        # _fetch_probable_pitcher_stats -- ninguna llamada nueva aquí.
        season_payload = (pitcher_season_stats or {}).get(side_key)
        if season_payload is not None:
            inputs.pitcher_season_stat[side] = RawDataPoint(payload=season_payload, captured_at=capture_ts)

        if pitcher_id is not None:
            game_log = mlb.get_person_stats(pitcher_id, group="pitching", stats_type="gameLog")
            if game_log.ok:
                inputs.pitcher_game_log[side] = RawDataPoint(payload=game_log.data, captured_at=game_log.capture_ts)
                steps.append(PipelineStepResult("mlb", f"pitcher_game_log_{pitcher_id}", True))
            else:
                steps.append(PipelineStepResult("mlb", f"pitcher_game_log_{pitcher_id}", False, error=game_log.error))

            splits = mlb.get_person_handedness_splits(pitcher_id, group="pitching")
            if splits.ok:
                inputs.pitcher_handedness_splits[side] = RawDataPoint(payload=splits.data, captured_at=splits.capture_ts)
                steps.append(PipelineStepResult("mlb", f"pitcher_handedness_splits_{pitcher_id}", True))
            else:
                steps.append(
                    PipelineStepResult("mlb", f"pitcher_handedness_splits_{pitcher_id}", False, error=splits.error)
                )

        if team_id is not None:
            il = mlb.get_injured_list_roster(team_id)
            if il.ok:
                inputs.il_roster[side] = RawDataPoint(payload=il.data, captured_at=il.capture_ts)
                steps.append(PipelineStepResult("mlb", f"il_roster_{team_id}", True))
            else:
                steps.append(PipelineStepResult("mlb", f"il_roster_{team_id}", False, error=il.error))

            team_hitting = mlb.get_team_stats(team_id, group="hitting", stats_type="season")
            if team_hitting.ok:
                inputs.team_hitting_stat[side] = RawDataPoint(payload=team_hitting.data, captured_at=team_hitting.capture_ts)
                steps.append(PipelineStepResult("mlb", f"team_hitting_stat_{team_id}", True))
            else:
                steps.append(PipelineStepResult("mlb", f"team_hitting_stat_{team_id}", False, error=team_hitting.error))

    return inputs
