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
from src.matching.market_matcher import apply_kalshi_match, find_best_kalshi_event
from src.models.schemas import SourceStatus
from src.normalization.mlb_normalizer import normalize_mlb_game
from src.quality.completeness import compute_completeness_score, dedupe_missing_fields
from src.quality.validators import annotate_duplicate_markets, validate_record
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
    limit: Optional[int] = None,
    fetch_boxscore: bool = True,
    fetch_pitcher_stats: bool = True,
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
    for game in games:
        game_pk = game.get("gamePk")

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
        for record in records:
            repository.save_normalized_record(record)

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
