"""Auditoría de calidad de labels (Fase 4, Paso 4.2.1). Ver
`FASE4_EXECUTION_PLAN.md` §6 Paso 4.2.1 y `ORCHESTRATOR_SPEC.md` §1.8
(hallazgo original: `event_results` no tiene restricción `UNIQUE` sobre
`event_id` a nivel de base de datos -- duplicados/conflictos son
posibles de verdad, no hipotéticos).

Función de solo lectura (sin efectos secundarios) que DETECTA y
REPORTA -- nunca corrige automáticamente. Cualquier corrección de dato
es una decisión humana, no una heurística (Regla 3 de la metodología).

Corre antes de cualquier entrenamiento real, incluso si GATE-0 y el
Coverage Gate (Paso 4.2) ya pasaron: volumen suficiente con labels
corruptos sigue sin ser entrenable, y ninguno de los dos gates lo
detecta por sí solo.

Reutiliza el conteo `no_result` ya calculado por
`src/evaluation/gate_report.py::build_sport_gate_report` (vía el
`SportGateReport` ya construido, inyectado -- nunca se recalcula por
separado, mismo principio ya establecido en el propio Paso 4.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.evaluation.gate_report import SportGateReport
from src.models.schemas import Sport
from src.storage.history_repository import HistoryRepository

# Único catálogo cerrado de resultados binarios válidos en todo el
# proyecto (idéntico, literal, a `_VALID_RESULTS` en
# src/models/mlb_baseline.py/tennis_baseline.py y a
# `_VALID_MLB_A_WON`/`_VALID_MLB_B_WON`/`_VALID_TENNIS_A_WON`/
# `_VALID_TENNIS_B_WON` en `mlb_results_sync.py`/`tennis_results_sync.py`
# -- no se define una constante compartida nueva para no tocar esos
# archivos ya cerrados solo por esto; el valor es el mismo en los 5
# lugares, verificado directamente contra el código.
_VALID_BINARY_RESULTS = frozenset({"PARTICIPANT_A_WON", "PARTICIPANT_B_WON"})


@dataclass
class ResultConflict:
    event_id: str
    distinct_results: List[str]
    row_count: int


@dataclass
class SportLabelQualityReport:
    sport: Sport
    total_event_results: int
    conflicting_results: List[ResultConflict] = field(default_factory=list)
    """Mismo `event_id` con más de un valor DISTINTO de `result` --
    `build_mlb_training_dataset`/`build_tennis_training_dataset` los
    resuelve en silencio tomando el más reciente por `recorded_at`; esta
    auditoría hace visible el conflicto sin cambiar esa resolución."""
    exact_duplicate_count: int = 0
    """Filas con `(event_id, result)` idéntico repetido -- inocuas para
    el dataset builder (mismo valor), pero indicativas de un bug en el
    llamador de `save_event_result` si aparecen."""
    non_binary_result_counts: Dict[str, int] = field(default_factory=dict)
    """Distribución de valores de `result` fuera del catálogo binario
    (`CANCELLED`/`POSTPONED`/cualquier otro) -- ya excluidos del dataset
    de entrenamiento por diseño, se cuentan aquí como proporción del
    total para detectar un problema sistemático de fuente."""
    sport_mismatches: List[str] = field(default_factory=list)
    """`event_id` cuyo `sport` en `event_results` no coincide con el
    `sport` observado en `event_snapshots` para el mismo evento."""
    unresolved_count: int = 0
    """= `gate_report.exclusions["no_result"]`, reutilizado literalmente
    (Coverage Gate, Paso 4.2) -- no se recalcula por separado."""

    @property
    def has_anomalies(self) -> bool:
        """Cualquier resultado en conflicto o duplicado exacto es una
        anomalía real de integridad -- CANCELLED/POSTPONED y
        unresolved_count NO cuentan como anomalía por sí solos (son
        estados esperados del dominio, no indicios de un bug)."""
        return bool(self.conflicting_results) or self.exact_duplicate_count > 0 or bool(self.sport_mismatches)


def build_label_quality_report(
    history_repository: HistoryRepository,
    sport: Sport,
    gate_report: SportGateReport,
) -> SportLabelQualityReport:
    if gate_report.sport != sport:
        raise ValueError(f"gate_report.sport={gate_report.sport} no coincide con sport={sport}")

    result_rows = [row for row in history_repository.get_all_event_results() if row["sport"] == sport.value]

    rows_by_event: Dict[str, List[dict]] = {}
    for row in result_rows:
        rows_by_event.setdefault(row["event_id"], []).append(row)

    conflicting_results: List[ResultConflict] = []
    exact_duplicate_count = 0
    for event_id, rows in rows_by_event.items():
        distinct_results = sorted({row["result"] for row in rows})
        if len(distinct_results) > 1:
            conflicting_results.append(
                ResultConflict(event_id=event_id, distinct_results=distinct_results, row_count=len(rows))
            )
        elif len(rows) > 1:
            exact_duplicate_count += len(rows) - 1

    non_binary_result_counts: Dict[str, int] = {}
    for row in result_rows:
        if row["result"] not in _VALID_BINARY_RESULTS:
            non_binary_result_counts[row["result"]] = non_binary_result_counts.get(row["result"], 0) + 1

    # Deliberadamente NO se reutiliza `result_rows` (ya filtrado por
    # sport==este deporte) -- un event_id cuyo event_result reclama OTRO
    # deporte es exactamente el caso a detectar, y ese filtro lo
    # excluiría antes de poder compararlo. Se parte de los event_id que
    # event_snapshots ya identifica como este deporte, y se compara
    # contra el sport real (sin filtrar) de sus event_results.
    snapshot_event_ids_for_sport = {
        row["event_id"] for row in history_repository.get_all_event_snapshots() if row["sport"] == sport.value
    }
    result_sports_by_event: Dict[str, set] = {}
    for row in history_repository.get_all_event_results():
        result_sports_by_event.setdefault(row["event_id"], set()).add(row["sport"])
    sport_mismatches = sorted(
        event_id
        for event_id in snapshot_event_ids_for_sport
        if event_id in result_sports_by_event and result_sports_by_event[event_id] != {sport.value}
    )

    return SportLabelQualityReport(
        sport=sport,
        total_event_results=len(result_rows),
        conflicting_results=conflicting_results,
        exact_duplicate_count=exact_duplicate_count,
        non_binary_result_counts=non_binary_result_counts,
        sport_mismatches=sport_mismatches,
        unresolved_count=gate_report.exclusions.get("no_result", 0),
    )
