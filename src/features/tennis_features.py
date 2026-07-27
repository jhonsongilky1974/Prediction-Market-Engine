"""Cálculo del baseline v1 de features de tenis (Fase 2, Paso 11).

Implementa las dos funciones `compute_*` FULLY_SPECIFIED de tenis en el
Feature Registry (`src.features.registry`, Paso 1): `compute_rest_days` y
`compute_tournament_round_context` -- nombres anclados literalmente por
`FeatureDefinition.compute_function_name` en el registry, ya aprobado
desde el Paso 1.

DECISIÓN DE DISEÑO (mismo principio que `mlb_features.py`): este módulo
nunca hace llamadas de red NI consulta `HistoryRepository` directamente.
`rest_days` necesita el histórico de partidos previos de cada jugador,
pero esa consulta (buscar en `event_snapshots` por `participant_*_espn_id`)
es responsabilidad del llamador (`tennis_pipeline.py`, Paso 11) -- este
módulo solo recibe la lista YA obtenida de `start_time` de partidos
previos, y aplica el corte temporal él mismo (mismo patrón que
`RawDataPoint.usable()` en `mlb_features.py`: el control de leakage vive
en la función de cálculo, testeado ahí, no disperso en el llamador).

Doble bloqueo documentado en PLAN_PHASE2.md §6: SofaScore bloqueado (403)
más histórico propio aún pequeño hacen que, a diferencia de MLB, ambas
features de este baseline puedan resolver a `None` durante mucho tiempo
en la práctica -- resultado honesto, no un error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

CURRENT_FEATURE_SET_VERSION = "phase2_registry_v1"
"""Debe coincidir con src.features.registry.CURRENT_FEATURE_SET_VERSION --
verificado por test, no importado directamente (mismo patrón que
mlb_features.py) para no acoplar el valor a un futuro refactor silencioso
del registry."""

_REST_DAYS_VALIDATION_RANGE = (0.0, 30.0)


# =========================================================================
# rest_days
# =========================================================================


def compute_rest_days(
    match_start_time: Optional[datetime],
    prior_match_start_times: List[datetime],
    data_cutoff_timestamp: datetime,
) -> Optional[float]:
    """`start_time` del partido a predecir menos `start_time` del último
    partido ANTERIOR conocido del mismo jugador en nuestro histórico
    propio (registry, Paso 1). El corte de leakage es `data_cutoff_timestamp`
    -- no el `start_time` del propio partido -- porque representa el
    instante real de conocimiento: un partido previo ocurrido entre el
    cutoff y el partido a predecir no podía saberse todavía en ese
    instante. `None` si no hay ningún partido previo conocido antes del
    cutoff -- nunca se asume "descansado" con un valor por defecto."""
    if match_start_time is None:
        return None
    eligible = [t for t in prior_match_start_times if t < data_cutoff_timestamp]
    if not eligible:
        return None
    most_recent = max(eligible)
    return (match_start_time - most_recent).total_seconds() / 86400.0


# =========================================================================
# tournament_round_context
# =========================================================================


def compute_tournament_round_context(tournament_round: Optional[str]) -> Optional[str]:
    """Directo -- la ronda del torneo ya viene como texto en el payload de
    ESPN (`competition.round.displayName`, capturado por
    `tennis_normalizer.py` en `model_inputs.context.tournament_round`,
    verificado contra la API real antes de implementar esto). `None` si
    ESPN no lo estructuró para ese torneo -- nunca se infiere por
    heurística de texto del nombre del torneo (PLAN_PHASE2.md §16,
    prohibido explícitamente)."""
    return tournament_round


# =========================================================================
# Orquestador
# =========================================================================


@dataclass
class TennisFeatureInputs:
    """Bundle de datos YA obtenidos (histórico propio consultado por el
    llamador) necesarios para el baseline v1 de tenis, por lado
    (participant_a=home, participant_b=away, consistente con
    tennis_normalizer.py). Este módulo no consulta HistoryRepository ni
    hace fetch: es responsabilidad del llamador construir este bundle."""

    prior_match_start_times: Dict[str, List[datetime]] = field(
        default_factory=lambda: {"participant_a": [], "participant_b": []}
    )


def compute_tennis_features(
    record: NormalizedRecord,
    inputs: TennisFeatureInputs,
    data_cutoff_timestamp: datetime,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Calcula las 2 features FULLY_SPECIFIED de tenis para un
    NormalizedRecord. Devuelve (features, missing_features, warnings).

    `features["rest_days"]` es `{"participant_a": valor|None, "participant_b": valor|None}`;
    `features["tournament_round_context"]` es un valor único (no
    side-aware: la ronda es del partido, no de un jugador). Ningún valor
    faltante se convierte en 0/una ronda por defecto -- queda `None` y su
    nombre se añade a `missing_features`."""
    if record.sport != Sport.TENNIS:
        raise ValueError(f"compute_tennis_features solo aplica a NormalizedRecord de TENNIS, recibido: {record.sport}")
    if data_cutoff_timestamp.tzinfo is None or data_cutoff_timestamp.utcoffset() is None:
        raise ValueError(f"data_cutoff_timestamp debe ser tz-aware (UTC), recibido naive: {data_cutoff_timestamp!r}")

    features: Dict[str, Any] = {}
    missing: List[str] = []
    warnings: List[str] = []

    rest_days_value: Dict[str, Optional[float]] = {}
    for side in ("participant_a", "participant_b"):
        value = compute_rest_days(
            record.start_time, inputs.prior_match_start_times.get(side, []), data_cutoff_timestamp
        )
        rest_days_value[side] = value
        if value is None:
            missing.append(f"rest_days.{side}")
    features["rest_days"] = rest_days_value

    context = record.model_inputs.context or {}
    round_value = compute_tournament_round_context(context.get("tournament_round"))
    features["tournament_round_context"] = round_value
    if round_value is None:
        missing.append("tournament_round_context")

    lo, hi = _REST_DAYS_VALIDATION_RANGE
    for side in ("participant_a", "participant_b"):
        value = rest_days_value[side]
        if isinstance(value, (int, float)) and not (lo <= value <= hi):
            warnings.append(f"rest_days.{side}={value} fuera de rango plausible [{lo},{hi}]")

    return features, missing, warnings


def persist_tennis_feature_snapshot(
    history_repository: HistoryRepository,
    record: NormalizedRecord,
    event_snapshot_id: int,
    inputs: TennisFeatureInputs,
    data_cutoff_timestamp: datetime,
    computed_at: Optional[datetime] = None,
) -> Tuple[int, Dict[str, Any], List[str], List[str]]:
    """Calcula las features (`compute_tennis_features`) y las persiste en
    `feature_snapshots` (Paso 0, INSERT-only) en un solo paso -- mismo
    patrón que `persist_mlb_feature_snapshot` (Paso 5b, Bloque 2).
    `event_snapshot_id` debe ser el id devuelto por un
    `HistoryRepository.save_event_snapshot` previo del MISMO evento/instante."""
    features, missing, warnings = compute_tennis_features(record, inputs, data_cutoff_timestamp)
    feature_snapshot_id = history_repository.save_feature_snapshot(
        event_id=record.event_id,
        event_snapshot_id=event_snapshot_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=data_cutoff_timestamp,
        features=features,
        missing_features=missing,
        computed_at=computed_at,
    )
    return feature_snapshot_id, features, missing, warnings
