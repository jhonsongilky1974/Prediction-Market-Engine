"""Fábricas de snapshots PRE-EVENTO para pruebas de tenis (CONTINUITY.md
§0.38). No es un módulo de tests en sí (sin funciones `test_*`) -- lo
importan los tests del dataset v2, del entrenamiento y del calibrador.

Un "sample" válido reproduce el esquema real: `event_snapshot` con
`start_time`/`status` del `NormalizedRecord`, un `feature_snapshot`
computado ANTES del inicio, y el resultado registrado DESPUÉS."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.model_registry_policy import ModelRegistryPolicy, RegistryEntry, RegistryStatus
from src.models.schemas import EventStatus, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
DEFAULT_LEAD_MINUTES = 300


def make_tennis_record(
    event_id: str,
    start_time: Optional[datetime] = None,
    status: EventStatus = EventStatus.SCHEDULED,
    sport: Sport = Sport.TENNIS,
) -> NormalizedRecord:
    return NormalizedRecord(
        sport=sport,
        event_id=event_id,
        participant_a="Player A",
        participant_b="Player B",
        start_time=start_time,
        status=status,
    )


def synthetic_features(rest_a=5.0, rest_b=3.0, round_context="Qualifying 1st Round"):
    return {
        "rest_days": {"participant_a": rest_a, "participant_b": rest_b},
        "tournament_round_context": round_context,
    }


def add_preevent_sample(
    hist: HistoryRepository,
    event_id: str,
    computed_at: datetime,
    result: Optional[str] = None,
    recorded_at: Optional[datetime] = None,
    feature_set_version: str = CURRENT_FEATURE_SET_VERSION,
    rest_a: float = 5.0,
    rest_b: float = 3.0,
    round_context: str = "Qualifying 1st Round",
    start_time: Optional[datetime] = None,
    status: EventStatus = EventStatus.SCHEDULED,
    cutoff: Optional[datetime] = None,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
) -> int:
    """Inserta un event_snapshot + feature_snapshot (y un resultado si
    `result` no es None). Por defecto `start_time = computed_at +
    lead_minutes` (snapshot pre-evento con anticipación de 5 h) y el
    resultado se registra 3 h DESPUÉS del inicio."""
    start = start_time if start_time is not None else computed_at + timedelta(minutes=lead_minutes)
    snap_id = hist.save_event_snapshot(make_tennis_record(event_id, start, status), source="test", captured_at=computed_at)
    feature_snapshot_id = hist.save_feature_snapshot(
        event_id=event_id,
        event_snapshot_id=snap_id,
        feature_set_version=feature_set_version,
        data_cutoff_timestamp=cutoff if cutoff is not None else computed_at,
        features=synthetic_features(rest_a, rest_b, round_context),
        computed_at=computed_at,
    )
    if result is not None:
        hist.save_event_result(
            event_id=event_id,
            sport="TENNIS",
            result=result,
            source="test",
            recorded_at=recorded_at or (start + timedelta(hours=3)),
        )
    return feature_snapshot_id


def promote_artifacts_for_test(models_dir: Path) -> ModelRegistryPolicy:
    """Simula la PROMOCIÓN explícita de TODOS los artefactos de tenis de
    `models_dir` (solo en tmp_path de tests): marca `candidate_status` como
    elegible y devuelve una política en memoria con una entrada `ALLOWED`
    por cada artefacto, con su SHA-256 real. En producción esto exige
    editar `config/model_registry.json` a mano."""
    entries = {}
    for meta_path in sorted(Path(models_dir).glob("tennis_baseline_*.metadata.json")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["candidate_status"] = "PROMOTION_ELIGIBLE"
        meta_path.write_text(json.dumps(data), encoding="utf-8")
        sha = hashlib.sha256(Path(data["file_path"]).read_bytes()).hexdigest()
        entries[data["model_version"]] = RegistryEntry(
            model_version=data["model_version"], status=RegistryStatus.ALLOWED, reason="test", artifact_sha256=sha
        )
    return ModelRegistryPolicy(entries=entries)
