"""Walk-forward split temporal (Paso 9). Ver PLAN_PHASE2.md §10 y el
Design Proposal explícitamente aprobado antes de esta implementación.

Invariante no negociable, confirmado explícitamente por el usuario antes
de implementar: **cero leakage por construcción**. Cada fold entrena
únicamente con datos disponibles hasta ese instante y predice únicamente
el siguiente bloque temporal -- bajo ninguna circunstancia un modelo puede
ver datos futuros. Esto se garantiza construyendo, por cada fold, un
`HistoryRepository` TEMPORAL y aislado que contiene físicamente solo las
filas (`event_snapshots`/`feature_snapshots`/`event_results`) cuyo
timestamp es anterior o igual al corte del fold: no importa qué lea
internamente la función de entrenamiento que el llamador invoque después
(`train_mlb_baseline_model`/`train_mlb_elo_model`, sin modificarlas) --
los datos futuros simplemente no existen en el objeto que se le entrega.
Este módulo es agnóstico al modelo: no importa `mlb_baseline` ni
`mlb_elo`, solo produce el repositorio aislado y las filas de test; quién
entrena y predice con eso es responsabilidad del llamador (ver Ambigüedad
B del Design Proposal, aprobada como interfaz genérica).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List

from src.backtesting.dataset import BacktestDataset, BacktestRow
from src.models.schemas import NormalizedRecord
from src.storage.history_repository import HistoryRepository


@dataclass
class Fold:
    fold_index: int
    train_repository: HistoryRepository  # temporal, aislado, se descarta al pasar al siguiente fold
    train_size: int
    test_rows: List[BacktestRow]


def _populate_scoped_repository(source: HistoryRepository, target: HistoryRepository, boundary: datetime) -> None:
    """Copia a `target` únicamente las filas de `source` cuyo timestamp
    relevante es <= `boundary`, usando exclusivamente los métodos públicos
    de `HistoryRepository` (INSERT-only, sin SQL crudo). Esta es la pieza
    que hace el no-leakage estructural, no una convención de código."""
    old_id_to_new_id: Dict[int, int] = {}

    for row in source.get_all_event_snapshots():
        captured_at = datetime.fromisoformat(row["captured_at"])
        if captured_at > boundary:
            continue
        record = NormalizedRecord.model_validate_json(row["normalized_record_json"])
        new_id = target.save_event_snapshot(record=record, source=row["source"], captured_at=captured_at)
        old_id_to_new_id[row["id"]] = new_id

    for row in source.get_all_feature_snapshots():
        computed_at = datetime.fromisoformat(row["computed_at"])
        if computed_at > boundary:
            continue
        new_event_snapshot_id = old_id_to_new_id.get(row["event_snapshot_id"])
        if new_event_snapshot_id is None:
            # El event_snapshot padre no calificó dentro del corte --
            # estado imposible en la práctica (una feature nunca se
            # calcula antes de que exista su snapshot), pero se omite
            # honestamente en vez de fallar con un error de FK.
            continue
        target.save_feature_snapshot(
            event_id=row["event_id"],
            event_snapshot_id=new_event_snapshot_id,
            feature_set_version=row["feature_set_version"],
            data_cutoff_timestamp=datetime.fromisoformat(row["data_cutoff_timestamp"]),
            features=json.loads(row["features_json"]),
            missing_features=json.loads(row["missing_features_json"]) if row["missing_features_json"] else None,
            computed_at=computed_at,
        )

    for row in source.get_all_event_results():
        recorded_at = datetime.fromisoformat(row["recorded_at"])
        if recorded_at > boundary:
            continue
        target.save_event_result(
            event_id=row["event_id"],
            sport=row["sport"],
            result=row["result"],
            source=row["source"],
            settled_at=datetime.fromisoformat(row["settled_at"]) if row["settled_at"] else None,
            recorded_at=recorded_at,
            source_payload_ref=row["source_payload_ref"],
        )


def walk_forward_splits(
    history_repository: HistoryRepository,
    dataset: BacktestDataset,
    min_train_size: int,
    test_block_size: int,
) -> Iterator[Fold]:
    """Genera TODOS los folds walk-forward posibles (ventana de train
    expansiva, ventana de test = siguiente bloque de tamaño
    `test_block_size`), ordenando por `data_cutoff_timestamp` -- NUNCA
    aleatorio.

    `min_train_size`/`test_block_size` no tienen default embebido a
    propósito: PLAN_PHASE2.md §10 no especifica un tamaño de fold, así que
    el llamador debe decidirlo explícitamente. Para el baseline logreg
    (Paso 5b) usar `DEFAULT_MIN_TRAINING_SAMPLES` (300); para Elo (Paso 6)
    usar `DEFAULT_MIN_GAMES` (50) -- mismos umbrales ya aprobados, nunca un
    número nuevo inventado aquí (Ambigüedad D del Design Proposal).

    Sin volumen suficiente para al menos un fold completo (train >=
    min_train_size y test >= 1 fila) -> iterador vacío, nunca un error.

    Nunca se parte un grupo de filas con el mismo `data_cutoff_timestamp`
    entre train y test -- evita que dos filas "simultáneas" queden
    arbitrariamente una en cada lado.

    CONTRATO DE USO IMPORTANTE: `Fold.train_repository` es un directorio
    temporal que se elimina automáticamente en cuanto el generador avanza
    al siguiente fold (o se cierra/recolecta). El llamador debe entrenar y
    predecir con ese repositorio DENTRO de la misma iteración del `for`
    (antes de pedir el siguiente fold) -- materializar todos los folds con
    `list(...)` primero y usar `train_repository` después ya no es válido,
    su archivo SQLite habrá sido borrado."""
    ordered = sorted(dataset.rows, key=lambda r: (r.data_cutoff_timestamp, r.event_id))
    n = len(ordered)

    fold_index = 0
    train_end = min_train_size
    while train_end < n:
        while (
            train_end < n
            and train_end > 0
            and ordered[train_end].data_cutoff_timestamp == ordered[train_end - 1].data_cutoff_timestamp
        ):
            train_end += 1
        if train_end >= n:
            break

        test_end = min(train_end + test_block_size, n)
        while (
            test_end < n
            and test_end > 0
            and ordered[test_end].data_cutoff_timestamp == ordered[test_end - 1].data_cutoff_timestamp
        ):
            test_end += 1

        train_rows = ordered[:train_end]
        test_rows = ordered[train_end:test_end]
        if not train_rows or not test_rows:
            break

        boundary = train_rows[-1].data_cutoff_timestamp
        tmp_dir = tempfile.mkdtemp(prefix="pme_backtest_fold_")
        try:
            train_repo = HistoryRepository(db_path=Path(tmp_dir) / "history.db")
            _populate_scoped_repository(history_repository, train_repo, boundary=boundary)
            yield Fold(
                fold_index=fold_index,
                train_repository=train_repo,
                train_size=len(train_rows),
                test_rows=test_rows,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        fold_index += 1
        train_end = test_end
