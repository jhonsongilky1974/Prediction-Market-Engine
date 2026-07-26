"""Dataset de backtesting (Paso 9). Ver PLAN_PHASE2.md §10/§11 y el Design
Proposal explícitamente aprobado antes de esta implementación.

A diferencia de `build_mlb_training_dataset` (Paso 5b, que solo lee
`feature_snapshots` + `event_results`), este dataset también reconstruye,
por fila, el `NormalizedRecord` histórico COMPLETO desde
`event_snapshots.normalized_record_json` -- la columna diseñada
explícitamente en el Paso 0 para esto ("ancla de reproducibilidad total").
Sobre ese registro histórico se recalculan, con las funciones ya cerradas
y SIN modificarlas, `P_market_YES`/`P_market_NO` (Paso 3) y
`compute_quality_score` (Paso 7) -- reproduciendo con fidelidad "qué
sabíamos en ese instante", nunca el estado actual.

Mismo corte temporal no negociable que en Paso 5b/6 (PLAN_PHASE2.md §10:
"el join con event_results ocurre únicamente en este paso, filtrando
estrictamente event_snapshots.captured_at < event_results.recorded_at"):
una fila de features solo se etiqueta con un resultado si ese resultado se
registró DESPUÉS de que las features fueran calculadas.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.features.registry import CURRENT_FEATURE_SET_VERSION
from src.models.schemas import NormalizedRecord
from src.pricing.market_pricing import market_price_no, market_price_yes
from src.storage.history_repository import HistoryRepository
from src.uncertainty.quality_score import QualityScoreOutput, compute_quality_score

_VALID_RESULTS = {"PARTICIPANT_A_WON": 1, "PARTICIPANT_B_WON": 0}


@dataclass
class BacktestRow:
    event_id: str
    data_cutoff_timestamp: datetime  # computed_at del feature_snapshot -- "qué se sabía en ese instante"
    result_recorded_at: datetime
    label: int  # 1 = participant_a ganó, 0 = participant_b ganó
    feature_set_version: str
    features: Dict[str, Any]
    record: NormalizedRecord  # reconstruido byte-a-byte desde normalized_record_json
    p_market_yes: Optional[float]
    p_market_no: Optional[float]
    quality_score: QualityScoreOutput


@dataclass
class BacktestDataset:
    rows: List[BacktestRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.rows)


def build_backtest_dataset(history_repository: HistoryRepository) -> BacktestDataset:
    """Construye el dataset de backtesting uniendo `event_snapshots` +
    `feature_snapshots` + `event_results` (HistoryRepository, Paso 0),
    NUNCA `normalized_records` (solo tiene el estado actual). El enlace
    `feature_snapshots.event_snapshot_id -> event_snapshots.id` es exacto
    (no una heurística de "snapshot más cercano en el tiempo")."""
    warnings: List[str] = []

    snapshot_by_id: Dict[int, Dict[str, Any]] = {
        row["id"]: row for row in history_repository.get_all_event_snapshots()
    }
    feature_rows = history_repository.get_all_feature_snapshots()
    result_rows = history_repository.get_all_event_results()

    latest_result_by_event: Dict[str, Dict[str, Any]] = {}
    for row in result_rows:
        event_id = row["event_id"]
        existing = latest_result_by_event.get(event_id)
        if existing is None or row["recorded_at"] > existing["recorded_at"]:
            latest_result_by_event[event_id] = row

    rows: List[BacktestRow] = []
    excluded_wrong_version = 0
    excluded_no_snapshot = 0
    excluded_no_result = 0
    excluded_leakage = 0
    excluded_non_binary_result = 0

    for frow in feature_rows:
        event_id = frow["event_id"]

        if frow["feature_set_version"] != CURRENT_FEATURE_SET_VERSION:
            excluded_wrong_version += 1
            continue

        snapshot = snapshot_by_id.get(frow["event_snapshot_id"])
        if snapshot is None:
            excluded_no_snapshot += 1
            continue

        result = latest_result_by_event.get(event_id)
        if result is None:
            excluded_no_result += 1
            continue

        computed_at = datetime.fromisoformat(frow["computed_at"])
        recorded_at = datetime.fromisoformat(result["recorded_at"])
        if not (computed_at < recorded_at):
            excluded_leakage += 1
            continue

        result_value = result["result"]
        if result_value not in _VALID_RESULTS:
            excluded_non_binary_result += 1
            continue

        record = NormalizedRecord.model_validate_json(snapshot["normalized_record_json"])
        captured_at = datetime.fromisoformat(snapshot["captured_at"])

        rows.append(
            BacktestRow(
                event_id=event_id,
                data_cutoff_timestamp=computed_at,
                result_recorded_at=recorded_at,
                label=_VALID_RESULTS[result_value],
                feature_set_version=frow["feature_set_version"],
                features=json.loads(frow["features_json"]),
                record=record,
                p_market_yes=market_price_yes(record),
                p_market_no=market_price_no(record),
                quality_score=compute_quality_score(record, consensus=None, now=captured_at),
            )
        )

    if excluded_wrong_version:
        warnings.append(
            f"{excluded_wrong_version} feature_snapshots excluidos: feature_set_version distinto de "
            f"{CURRENT_FEATURE_SET_VERSION!r}"
        )
    if excluded_no_snapshot:
        warnings.append(
            f"{excluded_no_snapshot} feature_snapshots excluidos: sin event_snapshot correspondiente "
            f"(event_snapshot_id no encontrado)"
        )
    if excluded_no_result:
        warnings.append(f"{excluded_no_result} feature_snapshots excluidos: sin event_result todavía")
    if excluded_leakage:
        warnings.append(
            f"{excluded_leakage} feature_snapshots excluidos: el resultado se registró antes o al mismo "
            f"tiempo que las features (leakage temporal, nunca se etiqueta con esa fila)"
        )
    if excluded_non_binary_result:
        warnings.append(
            f"{excluded_non_binary_result} feature_snapshots excluidos: resultado no es "
            f"PARTICIPANT_A_WON/PARTICIPANT_B_WON (CANCELLED/POSTPONED/NO_CONTEST no son etiqueta binaria válida)"
        )

    return BacktestDataset(rows=rows, warnings=warnings)
