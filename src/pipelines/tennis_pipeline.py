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

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT, TENNIS_LATE_ROUND_TOLERANCE_MINUTES
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.sofascore import SofascoreConnector
from src.features.tennis_features import TennisFeatureInputs, persist_tennis_feature_snapshot
from src.matching.market_matcher import apply_kalshi_match, find_best_kalshi_event
from src.matching.tennis_pair_matcher import resolve_tennis_pair_by_structure
from src.models.schemas import NormalizedRecord, SourceStatus
from src.normalization.tennis_normalizer import normalize_espn_tennis_match
from src.observability.step_timer import log_step
from src.quality.completeness import compute_completeness_score, dedupe_missing_fields, subtract_filled_fields
from src.quality.validators import annotate_duplicate_markets, validate_record
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository
from src.pipelines.mlb_pipeline import PipelineStepResult

logger = logging.getLogger(__name__)


def _is_upcoming(match: Dict[str, Any]) -> bool:
    state = ((match.get("status") or {}).get("type") or {}).get("state")
    return state in ("pre", "in")


# Auditoria real 2026-08-10 (ver CONTINUITY.md): ronda -> tolerancia,
# leida del campo ESTRUCTURADO de ESPN (`match["round"]`), nunca del
# titulo de texto libre de Kalshi -- Kalshi no expone ronda en ningun
# campo estructurado (solo embebida en `market["title"]`/`rules_primary`).
# `round["id"]` es un enum pequeno y estable verificado contra datos
# reales (ATP+WTA, cuadros de distinto tamano): 5=Quarterfinal,
# 6=Semifinal, 7=Final. Las rondas de clasificacion se detectan por
# `displayName` (ids observados: 11, 14 -- podria haber mas sin
# confirmar, ej. cuadros de clasificacion mas grandes) en vez de una
# lista de ids no verificada contra datos reales.
_LATE_STAGE_ROUND_IDS = {"5", "6", "7"}
_LATE_STAGE_ROUND_NAMES = {"quarterfinal", "semifinal", "final"}


def _tennis_round_tolerance_minutes(espn_match: Dict[str, Any]) -> int:
    """Tolerancia de tiempo (minutos) para el matching Kalshi de ESTE
    partido, segun su ronda real. Cuartos de Final/Semifinal/Final/
    Clasificatorias -> TENNIS_LATE_ROUND_TOLERANCE_MINUTES (330, evidencia
    real: cubre 97-100% de esas rondas). Cualquier otra ronda (Round Of
    128/64/32/16) o ronda ausente/no reconocida -> el valor conservador
    actual (240) sin cambios -- ahi ampliar la tolerancia no ayuda
    (medido: <76% de cobertura incluso a 480min) y solo aumentaria el
    riesgo de cruzar partidos sin ganar nada."""
    round_info = espn_match.get("round") or {}
    round_id = str(round_info.get("id")) if round_info.get("id") is not None else None
    round_name = (round_info.get("displayName") or "").strip().lower()

    is_late_stage = round_id in _LATE_STAGE_ROUND_IDS or round_name in _LATE_STAGE_ROUND_NAMES
    is_qualifying = "qualif" in round_name

    if is_late_stage or is_qualifying:
        return TENNIS_LATE_ROUND_TOLERANCE_MINUTES
    return EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["TENNIS"]


# Tramo 1 del resolver estructural de pares (2026-08-15, ver
# src/matching/tennis_pair_matcher.py y CONTINUITY.md -- investigación real
# Faria vs Wu, 2026-08-12). SOLO Qualifying (misma detección real ya usada
# arriba, "qualif" en displayName) y el formato de grupos tipo round-robin.
#
# Verificacion real hecha antes de codificar esto (2026-08-15, consulta en
# vivo a la API real de ESPN Tennis, NO asumido): "Round Robin" no aparece
# NUNCA como valor real de round.displayName. El unico valor real
# encontrado para el formato de grupos es round.id="15",
# displayName="Group Stage" -- confirmado en DOS torneos reales distintos,
# ambos tours (Nitto ATP Finals, ej. Alcaraz vs de Minaur 2025-11-09; y WTA
# Finals, mismas fechas), unico formato round-robin real que existe en el
# calendario ATP/WTA. No se encontro ninguna otra variante de texto real.
# Round Of 128/64/32/16 y Cuartos/Semifinal/Final quedan explicitamente
# FUERA -- sin evidencia propia todavia -- y siguen exactamente su camino
# actual, sin ningun cambio de comportamiento.
_STRUCTURAL_PAIR_GROUP_STAGE_ROUND_IDS = {"15"}
_STRUCTURAL_PAIR_GROUP_STAGE_ROUND_NAMES = {"group stage"}


def _tennis_uses_structural_pair_resolver(espn_match: Dict[str, Any]) -> bool:
    round_info = espn_match.get("round") or {}
    round_id = str(round_info.get("id")) if round_info.get("id") is not None else None
    round_name = (round_info.get("displayName") or "").strip().lower()
    is_qualifying = "qualif" in round_name
    is_group_stage = (
        round_id in _STRUCTURAL_PAIR_GROUP_STAGE_ROUND_IDS
        or round_name in _STRUCTURAL_PAIR_GROUP_STAGE_ROUND_NAMES
    )
    return is_qualifying or is_group_stage


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
    pipeline_started = time.monotonic()
    logger.info("-> run_tennis_pipeline tour=%r date=%r enrich_sofascore=%r fetch_features=%r limit=%r",
                tour, date, enrich_sofascore, fetch_features, limit)
    tour = tour.upper()
    steps: List[PipelineStepResult] = []
    espn = EspnTennisConnector(repository=repository)
    kalshi = KalshiConnector(repository=repository)
    sofascore = SofascoreConnector(repository=repository)

    with log_step(logger, "run_tennis_pipeline.espn_get_scoreboard", tour=tour, date=date):
        scoreboard_result = espn.get_scoreboard(tour.lower(), date)
    if not scoreboard_result.ok:
        steps.append(PipelineStepResult("espn_tennis", "scoreboard", False, error=scoreboard_result.error))
        logger.info("<- run_tennis_pipeline FAILED (scoreboard) elapsed_ms=%.1f", (time.monotonic() - pipeline_started) * 1000)
        return TennisPipelineResult(records=[], steps=steps)

    matches = EspnTennisConnector.extract_matches(scoreboard_result.data)
    steps.append(PipelineStepResult("espn_tennis", "scoreboard", True, count=len(matches)))
    logger.info("run_tennis_pipeline: matches from scoreboard count=%d", len(matches))
    # El scoreboard de un torneo trae todos sus partidos (jugados y por
    # jugar). Priorizamos los "próximos disponibles" (status pre/in) sobre
    # los ya finalizados antes de aplicar `limit`, ya que el objetivo del
    # pipeline es evaluar valor en partidos que aún se pueden operar.
    matches = sorted(matches, key=lambda m: 0 if _is_upcoming(m) else 1)
    if limit is not None:
        matches = matches[:limit]
    logger.info("run_tennis_pipeline: matches after limit count=%d", len(matches))

    with log_step(logger, "run_tennis_pipeline.kalshi_get_all_events_for_sport", tour=tour):
        kalshi_events_result = kalshi.get_all_events_for_sport(tour)
    kalshi_events = []
    if kalshi_events_result.ok:
        kalshi_events = KalshiConnector.extract_events(kalshi_events_result.data)
        steps.append(PipelineStepResult("kalshi", f"events_KX{tour}MATCH", True, count=len(kalshi_events)))
    else:
        steps.append(PipelineStepResult("kalshi", f"events_KX{tour}MATCH", False, error=kalshi_events_result.error))
    logger.info("run_tennis_pipeline: kalshi_events count=%d", len(kalshi_events))

    records = []
    # Paso 11: features (rest_days/tournament_round_context) calculadas
    # junto al resto del lote, alineadas 1:1 por índice con `records`
    # (mismo patrón que el Bloque 2 del Paso 5b en mlb_pipeline.py).
    feature_inputs_list: List[Optional[TennisFeatureInputs]] = []
    feature_cutoffs: List[Optional[datetime]] = []

    # Fix de rendimiento (diagnóstico real de /analyze en tenis, ver
    # informe de instrumentación): antes, `_fetch_tennis_feature_inputs`
    # llamaba `history_repository.get_all_event_snapshots()` -- un
    # recorrido lineal + parseo JSON de TODA la tabla `event_snapshots`
    # (12k+ filas reales) -- UNA VEZ POR CADA PARTIDO del scoreboard del
    # día (349 partidos reales medidos), no solo por el partido pedido.
    # Medido contra datos reales: 94.5s solo en este bucle. El índice es
    # seguro construirlo una única vez ANTES del bucle porque nada escribe
    # en `event_snapshots` durante el bucle -- la persistencia ocurre
    # DESPUÉS, en el bloque `if repository is not None` de más abajo --
    # así que el resultado es idéntico al de volver a consultar
    # `get_all_event_snapshots()` en cada iteración (misma foto de la
    # tabla en todo momento). Mismo resultado funcional exacto que antes,
    # solo evita repetir 349 veces el mismo trabajo.
    history_index: Optional[Dict[str, List[Tuple[str, datetime]]]] = None
    if fetch_features and history_repository is not None:
        with log_step(logger, "run_tennis_pipeline.build_tennis_history_index"):
            history_index = _build_tennis_history_index(history_repository)

    for match_index, match in enumerate(matches):
        match_started = time.monotonic()
        match_label = f"{match_index + 1}/{len(matches)}"
        logger.info("-> run_tennis_pipeline.match_loop match=%s espn_match_id=%r", match_label, match.get("id"))

        with log_step(logger, "run_tennis_pipeline.normalize_espn_tennis_match", match=match_label):
            record, missing = normalize_espn_tennis_match(match, tour)

        if fetch_features and history_repository is not None:
            with log_step(
                logger, "run_tennis_pipeline._fetch_tennis_feature_inputs", match=match_label, event_id=record.event_id
            ):
                feature_inputs = _fetch_tennis_feature_inputs(history_index, record)
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
            with log_step(logger, "run_tennis_pipeline._try_enrich_sofascore", match=match_label):
                filled = _try_enrich_sofascore(sofascore, record, steps)
            if filled is not None:
                source_status["sofascore"] = SourceStatus.OK if filled else SourceStatus.PARTIAL
                missing = subtract_filled_fields(missing, filled)
            else:
                source_status["sofascore"] = SourceStatus.FAILED
        else:
            logger.info("run_tennis_pipeline: sofascore enrichment disabled, skipping match=%s", match_label)

        if kalshi_events:
            if _tennis_uses_structural_pair_resolver(match):
                with log_step(
                    logger, "run_tennis_pipeline.resolve_tennis_pair_by_structure", match=match_label,
                    candidates=len(kalshi_events),
                ):
                    best, pair_diagnostics = resolve_tennis_pair_by_structure(
                        record.participant_a, record.participant_b, kalshi_events,
                    )
                logger.info(
                    "run_tennis_pipeline: tennis_pair_matcher match=%s outcome=%s examined=%d passed=%d",
                    match_label, pair_diagnostics.outcome, pair_diagnostics.candidates_examined,
                    pair_diagnostics.candidates_passed_pair_match,
                )
            else:
                tolerance_minutes = _tennis_round_tolerance_minutes(match)
                with log_step(
                    logger, "run_tennis_pipeline.find_best_kalshi_event", match=match_label,
                    candidates=len(kalshi_events), tolerance_minutes=tolerance_minutes,
                ):
                    best = find_best_kalshi_event(
                        record.participant_a,
                        record.participant_b,
                        record.start_time,
                        kalshi_events,
                        tolerance_minutes=tolerance_minutes,
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
        logger.info(
            "<- run_tennis_pipeline.match_loop match=%s elapsed_ms=%.1f",
            match_label,
            (time.monotonic() - match_started) * 1000,
        )

    # Ver comentario equivalente en mlb_pipeline.py: la detección de
    # duplicados solo puede evaluarse sobre el lote completo, así que corre
    # después del bucle y antes de persistir.
    with log_step(logger, "run_tennis_pipeline.annotate_duplicate_markets", records=len(records)):
        annotate_duplicate_markets(records)

    if repository is not None:
        with log_step(logger, "run_tennis_pipeline.persist_records", records=len(records)):
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
    logger.info(
        "<- run_tennis_pipeline OK tour=%r date=%r records=%d elapsed_ms=%.1f",
        tour, date, len(records), (time.monotonic() - pipeline_started) * 1000,
    )
    return TennisPipelineResult(
        records=records, steps=steps, feature_inputs_list=feature_inputs_list, feature_cutoffs=feature_cutoffs
    )


def _build_tennis_history_index(history_repository: HistoryRepository) -> Dict[str, List[Tuple[str, datetime]]]:
    """Índice en memoria `espn_id -> [(event_id, start_time), ...]` de TODO
    `event_snapshots`, construido UNA SOLA VEZ por corrida de
    `run_tennis_pipeline` (fix de rendimiento -- ver informe de
    instrumentación de /analyze en tenis: `_fetch_tennis_feature_inputs`
    volvía a recorrer y parsear TODA la tabla -- 12k+ filas reales -- por
    CADA partido del scoreboard del día, 349 partidos reales medidos ->
    94.5s solo en ese bucle). Construirlo una única vez antes del bucle de
    partidos es seguro: nada escribe en `event_snapshots` durante ese
    bucle -- la persistencia ocurre DESPUÉS, en el bloque
    `if repository is not None` de `run_tennis_pipeline` -- así que
    `get_all_event_snapshots()` ve exactamente la misma foto de la tabla
    en cualquier punto del bucle, igual que antes cuando se llamaba una
    vez por partido.

    Para cada snapshot de tenis (`event_id` con prefijo `espn_tennis_`)
    con `start_time` conocido, registra `(event_id, start_time)` bajo la
    clave de CADA `espn_id` que participó en ese partido (a/b, sin
    duplicar si coinciden) -- exactamente el mismo criterio de membership
    que antes evaluaba `espn_id in {a_id, b_id}` por fila y por lado."""
    index: Dict[str, List[Tuple[str, datetime]]] = {}
    for row in history_repository.get_all_event_snapshots():
        if not row["event_id"].startswith("espn_tennis_"):
            continue
        other_record = NormalizedRecord.model_validate_json(row["normalized_record_json"])
        if other_record.start_time is None:
            continue
        other_context = other_record.model_inputs.context or {}
        other_ids = {other_context.get("participant_a_espn_id"), other_context.get("participant_b_espn_id")}
        other_ids.discard(None)
        for other_id in other_ids:
            index.setdefault(other_id, []).append((row["event_id"], other_record.start_time))
    return index


def _fetch_tennis_feature_inputs(
    history_index: Dict[str, List[Tuple[str, datetime]]], record: NormalizedRecord
) -> TennisFeatureInputs:
    """Construye `TennisFeatureInputs` (Paso 11) a partir del índice YA
    construido por `_build_tennis_history_index` -- busca, para cada
    participante (emparejado por `espn_id`, nunca por nombre de texto, ver
    tennis_normalizer.py), los `start_time` de partidos previos ya
    vistos. Mismo resultado exacto que el recorrido lineal anterior
    (excluye el propio evento, solo snapshots de tenis, solo con
    `start_time` conocido) -- ahora en O(1) lookups por partido en vez de
    recorrer toda la tabla de nuevo. No hace ninguna llamada de red ni de
    base de datos."""
    context = record.model_inputs.context or {}
    espn_ids = {
        "participant_a": context.get("participant_a_espn_id"),
        "participant_b": context.get("participant_b_espn_id"),
    }
    prior_start_times: Dict[str, List[datetime]] = {"participant_a": [], "participant_b": []}

    for side, espn_id in espn_ids.items():
        if espn_id is None:
            continue
        for other_event_id, start_time in history_index.get(espn_id, []):
            if other_event_id == record.event_id:
                continue  # nunca el propio evento
            prior_start_times[side].append(start_time)

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
