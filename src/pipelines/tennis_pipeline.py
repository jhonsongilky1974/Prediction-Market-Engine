"""Pipeline de tenis: ingestión (ESPN Tennis + SofaScore best-effort + Kalshi)
-> normalización -> event/market matching -> validación de calidad ->
almacenamiento local.

SofaScore es best-effort: si falla (API no documentada, puede bloquear por
IP/WAF — ver src/connectors/sofascore.py), el pipeline continúa con los
campos de TENNIS_VARIABLES en None + MISSING_FIELDS, usando únicamente ESPN
+ Kalshi. Nunca se inventa un valor de reemplazo.

READ-ONLY. No calcula P_model/EDGE/EV/CONFIDENCE/señales.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.sofascore import SofascoreConnector
from src.features.tennis_features import TennisFeatureInputs, persist_tennis_feature_snapshot
from src.matching.market_matcher import apply_kalshi_match, find_best_kalshi_event
from src.models.schemas import NormalizedRecord, SourceStatus
from src.normalization.tennis_normalizer import normalize_espn_tennis_match
from src.quality.completeness import compute_completeness_score, dedupe_missing_fields, subtract_filled_fields
from src.quality.validators import annotate_duplicate_markets, validate_record
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository
from src.pipelines.mlb_pipeline import PipelineStepResult


def _is_upcoming(match: Dict[str, Any]) -> bool:
    state = ((match.get("status") or {}).get("type") or {}).get("state")
    return state in ("pre", "in")


@dataclass
class TennisPipelineResult:
    records: List[Any] = field(default_factory=list)
    steps: List[PipelineStepResult] = field(default_factory=list)
    # Fase 4, Paso 4.1 (orquestador) -- aditivo, cero cálculo nuevo, mismo
    # motivo que MlbPipelineResult (src/pipelines/mlb_pipeline.py).
    feature_inputs_list: List[Optional[TennisFeatureInputs]] = field(default_factory=list)
    feature_cutoffs: List[Optional[datetime]] = field(default_factory=list)


def run_tennis_pipeline(
    tour: str,
    date: str,
    repository: Optional[Repository] = None,
    history_repository: Optional[HistoryRepository] = None,
    limit: Optional[int] = None,
    enrich_sofascore: bool = True,
    fetch_features: bool = True,
) -> TennisPipelineResult:
    tour = tour.upper()
    steps: List[PipelineStepResult] = []
    espn = EspnTennisConnector(repository=repository)
    kalshi = KalshiConnector(repository=repository)
    sofascore = SofascoreConnector(repository=repository)

    scoreboard_result = espn.get_scoreboard(tour.lower(), date)
    if not scoreboard_result.ok:
        steps.append(PipelineStepResult("espn_tennis", "scoreboard", False, error=scoreboard_result.error))
        return TennisPipelineResult(records=[], steps=steps)

    matches = EspnTennisConnector.extract_matches(scoreboard_result.data)
    steps.append(PipelineStepResult("espn_tennis", "scoreboard", True, count=len(matches)))
    # El scoreboard de un torneo trae todos sus partidos (jugados y por
    # jugar). Priorizamos los "próximos disponibles" (status pre/in) sobre
    # los ya finalizados antes de aplicar `limit`, ya que el objetivo del
    # pipeline es evaluar valor en partidos que aún se pueden operar.
    matches = sorted(matches, key=lambda m: 0 if _is_upcoming(m) else 1)
    if limit is not None:
        matches = matches[:limit]

    kalshi_events_result = kalshi.get_all_events_for_sport(tour)
    kalshi_events = []
    if kalshi_events_result.ok:
        kalshi_events = KalshiConnector.extract_events(kalshi_events_result.data)
        steps.append(PipelineStepResult("kalshi", f"events_KX{tour}MATCH", True, count=len(kalshi_events)))
    else:
        steps.append(PipelineStepResult("kalshi", f"events_KX{tour}MATCH", False, error=kalshi_events_result.error))

    records = []
    # Paso 11: features (rest_days/tournament_round_context) calculadas
    # junto al resto del lote, alineadas 1:1 por índice con `records`
    # (mismo patrón que el Bloque 2 del Paso 5b en mlb_pipeline.py).
    feature_inputs_list: List[Optional[TennisFeatureInputs]] = []
    feature_cutoffs: List[Optional[datetime]] = []

    for match in matches:
        record, missing = normalize_espn_tennis_match(match, tour)

        if fetch_features and history_repository is not None:
            feature_inputs = _fetch_tennis_feature_inputs(history_repository, record)
            feature_cutoffs.append(datetime.now(timezone.utc))
            feature_inputs_list.append(feature_inputs)
        else:
            feature_inputs_list.append(None)
            feature_cutoffs.append(None)

        source_status = {
            "espn_tennis": SourceStatus.OK,
            "kalshi": SourceStatus.OK if kalshi_events_result.ok else SourceStatus.FAILED,
            "sofascore": SourceStatus.NOT_ATTEMPTED,
        }

        if enrich_sofascore:
            filled = _try_enrich_sofascore(sofascore, record, steps)
            if filled is not None:
                source_status["sofascore"] = SourceStatus.OK if filled else SourceStatus.PARTIAL
                missing = subtract_filled_fields(missing, filled)
            else:
                source_status["sofascore"] = SourceStatus.FAILED

        if kalshi_events:
            best = find_best_kalshi_event(
                record.participant_a,
                record.participant_b,
                record.start_time,
                kalshi_events,
                tolerance_minutes=EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["TENNIS"],
            )
            apply_kalshi_match(record, best, missing)
        else:
            record.data_quality.needs_review = True
            record.data_quality.match_warnings = ["no se pudieron obtener eventos de Kalshi para matching"]
            missing.append("market_id")

        record.data_quality.missing_fields = dedupe_missing_fields(missing)
        record.data_quality.source_status = source_status
        record.data_quality.source_timestamps = {
            "espn_tennis": scoreboard_result.capture_ts,
            "kalshi": kalshi_events_result.capture_ts,
        }
        record.data_quality.last_updated = datetime.now(timezone.utc)
        record.data_quality.data_completeness_score = compute_completeness_score(
            record.data_quality.missing_fields, "TENNIS"
        )
        record.data_quality.validation_errors = validate_record(record)

        records.append(record)

    # Ver comentario equivalente en mlb_pipeline.py: la detección de
    # duplicados solo puede evaluarse sobre el lote completo, así que corre
    # después del bucle y antes de persistir.
    annotate_duplicate_markets(records)

    if repository is not None:
        for record, feature_inputs, feature_cutoff in zip(records, feature_inputs_list, feature_cutoffs):
            repository.save_normalized_record(record)
            # Paso 0c: snapshot histórico append-only del MISMO record ya
            # persistido -- nunca antes, nunca en su lugar (ver PLAN_PHASE2.md §11).
            if history_repository is not None:
                snapshot_id = history_repository.save_event_snapshot(record, source="tennis_pipeline_run")
                # Paso 11: feature_snapshot del MISMO snapshot ya guardado --
                # solo si se pidieron features para este record (mismo
                # patrón que el Bloque 2 del Paso 5b para MLB).
                if feature_inputs is not None:
                    persist_tennis_feature_snapshot(
                        history_repository=history_repository,
                        record=record,
                        event_snapshot_id=snapshot_id,
                        inputs=feature_inputs,
                        data_cutoff_timestamp=feature_cutoff,
                    )

    steps.append(PipelineStepResult("pipeline", "normalized_records", True, count=len(records)))
    return TennisPipelineResult(
        records=records, steps=steps, feature_inputs_list=feature_inputs_list, feature_cutoffs=feature_cutoffs
    )


def _fetch_tennis_feature_inputs(history_repository: HistoryRepository, record: NormalizedRecord) -> TennisFeatureInputs:
    """Construye `TennisFeatureInputs` (Paso 11) consultando el histórico
    YA acumulado en `event_snapshots` -- busca, para cada participante
    (emparejado por `espn_id`, nunca por nombre de texto, ver
    tennis_normalizer.py), los `start_time` de partidos previos ya
    vistos. Recorrido lineal sobre TODO `event_snapshots` -- mismo patrón
    ya usado por `build_backtest_dataset`/`build_mlb_elo_game_sequence`;
    deuda de escalabilidad ya documentada en Fase 2, aceptable dado el
    volumen real actual. No hace ninguna llamada de red."""
    context = record.model_inputs.context or {}
    espn_ids = {
        "participant_a": context.get("participant_a_espn_id"),
        "participant_b": context.get("participant_b_espn_id"),
    }
    prior_start_times: Dict[str, List[datetime]] = {"participant_a": [], "participant_b": []}

    target_ids = {v for v in espn_ids.values() if v is not None}
    if not target_ids:
        return TennisFeatureInputs(prior_match_start_times=prior_start_times)

    for row in history_repository.get_all_event_snapshots():
        if row["event_id"] == record.event_id:
            continue  # nunca el propio evento
        if not row["event_id"].startswith("espn_tennis_"):
            continue
        other_record = NormalizedRecord.model_validate_json(row["normalized_record_json"])
        if other_record.start_time is None:
            continue
        other_context = other_record.model_inputs.context or {}
        other_ids = {other_context.get("participant_a_espn_id"), other_context.get("participant_b_espn_id")}
        for side, espn_id in espn_ids.items():
            if espn_id is not None and espn_id in other_ids:
                prior_start_times[side].append(other_record.start_time)

    return TennisFeatureInputs(prior_match_start_times=prior_start_times)


def _try_enrich_sofascore(
    sofascore: SofascoreConnector, record: Any, steps: List[PipelineStepResult]
) -> Optional[List[str]]:
    """Intenta enriquecer con SofaScore (ranking/forma/estadísticas). Devuelve
    la lista de campos rellenados (puede ser vacía) o None si la fuente
    falló por completo (para poder marcar SourceStatus.FAILED)."""
    if not record.participant_a:
        return []

    search_result = sofascore.search(record.participant_a)
    if not search_result.ok:
        steps.append(PipelineStepResult("sofascore", f"search_{record.participant_a}", False, error=search_result.error))
        return None
    steps.append(PipelineStepResult("sofascore", f"search_{record.participant_a}", True))

    player_id = SofascoreConnector.find_player_or_team_id(search_result.data, record.participant_a, "player")
    if player_id is None:
        return []

    events_result = sofascore.get_team_last_events(player_id)
    filled: List[str] = []
    if events_result.ok:
        steps.append(PipelineStepResult("sofascore", f"events_last_{player_id}", True))
        # NOTA (bug corregido, ver auditoría de Fase 1): aquí antes se
        # escribía tennis_variables.last_5 = {"raw_event_count": N}, un
        # RECUENTO de eventos devueltos por la API, no la forma real
        # (victorias/derrotas) del jugador. Eso violaba la regla de "nunca
        # inventar" -- quedaba marcado como campo "lleno"/OK cuando en
        # realidad no había ningún dato de forma real. Derivar win/loss real
        # requiere parsear `winnerCode`/marcador de cada evento contra el
        # `player_id`, algo que no se puede verificar de forma fiable contra
        # el schema real de SofaScore mientras la fuente esté bloqueada
        # (403) desde este entorno (ver sofascore.py). Hasta implementarlo y
        # verificarlo con datos reales, last_5/last_10 quedan NULL +
        # MISSING intencionalmente en vez de rellenarse con un placeholder.
    else:
        steps.append(PipelineStepResult("sofascore", f"events_last_{player_id}", False, error=events_result.error))

    return filled
