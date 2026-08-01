"""GATE-0 + Coverage Gate (Fase 4, Paso 4.2). Ver `FASE4_EXECUTION_PLAN.md`
§6 Paso 4.2 y `SHADOW_MODE_AND_PROMOTION_GATES.md` §2.

Chequeo repetible, invocable manualmente en cualquier momento
(`scripts/check_training_gates.py`) -- NUNCA desbloquea nada por sí
solo, solo informa (mismo espíritu que el resto de los chequeos ya
existentes en el proyecto, p.ej. `data_maintenance.py`). Sin efectos
secundarios (solo lecturas de `HistoryRepository`) -- "función pura" en
el sentido usado en todo el proyecto (determinística, sin mutación,
`HistoryRepository` inyectable), no en el sentido de "sin I/O".

Reutiliza LITERALMENTE la lógica de exclusión ya escrita en
`build_mlb_training_dataset`/`build_tennis_training_dataset` (Fase 2,
`src/models/mlb_baseline.py`/`tennis_baseline.py`) vía su campo aditivo
`exclusions` (§8 de este paso) -- no la reimplementa.

GATE-0 (`feature_snapshots.count() >= N_min AND event_results.count() >=
N_min`) usa los conteos CRUDOS por deporte -- no el tamaño del dataset ya
filtrado. El Coverage Gate es el chequeo complementario: qué fracción de
esos `feature_snapshots` termina teniendo un resultado etiquetado
utilizable (`dataset.size`, ya sin fuga temporal ni resultados no
binarios). Ningún umbral de Coverage Gate se fija aquí -- decisión
explícita del usuario, `FASE4_EXECUTION_PLAN.md` §9.2/§6 Paso 4.2: se
decide con evidencia real cuando GATE-0 esté cerca de cumplirse.

Fase 4, Paso 4.3 (`MODEL_TRAINING_SPEC.md` §0.4): los conteos crudos de
arriba son correctos para los clasificadores (`build_*_training_dataset`
los usa tal cual), pero NO para Elo -- `train_mlb_elo_model` no usa
`feature_snapshots` en absoluto, tiene su propia función de
elegibilidad (`build_mlb_elo_game_sequence`, basada en
`event_snapshots`+`event_results`). Verificado en producción: los
conteos crudos daban `GATE-0[mlb_elo]=CUMPLIDO` cuando la elegibilidad
real de Elo era 41 < 50 -- falso positivo. `eligible_count_fn` permite
inyectar, por umbral, una función de elegibilidad real distinta de los
conteos crudos, sin tocar la lógica de los clasificadores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.models.schemas import Sport
from src.storage.history_repository import HistoryRepository


@dataclass
class SportGateReport:
    sport: Sport
    feature_snapshots_total: int
    """`feature_snapshots` cuyo `event_id` tiene el prefijo de este
    deporte Y `feature_set_version` coincide con la versión actual --
    una versión desactualizada nunca es entrenable bajo el esquema de
    hoy, contarla infla el número de forma engañosa."""
    event_results_total: int
    """`event_results` con `sport` == este deporte -- conteo crudo, sin
    filtrar por validez del resultado (incluye CANCELLED/POSTPONED),
    exactamente lo que GATE-0 define."""
    thresholds: Dict[str, int]
    gate_0_met: Dict[str, bool]
    coverage_labeled_count: int
    """= `dataset.size` -- filas con resultado binario utilizable, sin
    fuga temporal, ya filtradas por el dataset builder correspondiente."""
    coverage_ratio: Optional[float]
    """`coverage_labeled_count / feature_snapshots_total` -- `None` si
    `feature_snapshots_total == 0` (nunca se divide por cero ni se
    fabrica un 0%/100% sin base)."""
    exclusions: Dict[str, int]
    warnings: List[str] = field(default_factory=list)


def build_sport_gate_report(
    history_repository: HistoryRepository,
    sport: Sport,
    event_id_prefix: str,
    thresholds: Dict[str, int],
    build_dataset_fn: Callable[[HistoryRepository], Any],
    feature_set_version: str,
    eligible_count_fn: Optional[Dict[str, Callable[[HistoryRepository], int]]] = None,
) -> SportGateReport:
    """`build_dataset_fn` es `build_mlb_training_dataset`/
    `build_tennis_training_dataset` (inyectado, no importado aquí --
    este módulo no decide qué deportes existen, mismo principio de
    extensibilidad que `SportAdapter`, Paso 4.1).

    `eligible_count_fn` (opcional, Paso 4.3): `{nombre_de_umbral:
    función(history_repository) -> int}` -- para el/los umbral(es)
    presentes en este dict, GATE-0 compara contra
    `eligible_count_fn[nombre](history_repository)` en vez de los
    conteos crudos (`feature_snapshots_total`/`event_results_total`).
    Omitir un nombre (o el parámetro entero) preserva el comportamiento
    exacto ya existente para ese umbral -- retrocompatible, ningún
    llamador existente se ve afectado."""
    eligible_count_fn = eligible_count_fn or {}
    feature_rows = history_repository.get_all_feature_snapshots()
    feature_snapshots_total = sum(
        1
        for row in feature_rows
        if row["event_id"].startswith(event_id_prefix) and row["feature_set_version"] == feature_set_version
    )

    result_rows = history_repository.get_all_event_results()
    event_results_total = sum(1 for row in result_rows if row["sport"] == sport.value)

    dataset = build_dataset_fn(history_repository)

    gate_0_met = {}
    for name, n_min in thresholds.items():
        if name in eligible_count_fn:
            gate_0_met[name] = eligible_count_fn[name](history_repository) >= n_min
        else:
            gate_0_met[name] = feature_snapshots_total >= n_min and event_results_total >= n_min
    coverage_ratio = dataset.size / feature_snapshots_total if feature_snapshots_total > 0 else None

    return SportGateReport(
        sport=sport,
        feature_snapshots_total=feature_snapshots_total,
        event_results_total=event_results_total,
        thresholds=dict(thresholds),
        gate_0_met=gate_0_met,
        coverage_labeled_count=dataset.size,
        coverage_ratio=coverage_ratio,
        exclusions=dict(dataset.exclusions),
        warnings=list(dataset.warnings),
    )
