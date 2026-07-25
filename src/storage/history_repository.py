"""Histórico append-only para Fase 2 (Paso 0).

`normalized_records` (Fase 1, `src/storage/repository.py`) hace UPSERT por
`event_id`: es una vista del estado ACTUAL, no conserva evolución
histórica. Este módulo es la pieza que sí la conserva.

Tres tablas nuevas, aditivas, en el mismo archivo SQLite (`data/engine.db`)
que ya usa `Repository` — conviven con `raw_captures`/`normalized_records`/
`event_matches` de Fase 1 sin alterarlas en absoluto (ni su schema, ni su
comportamiento, ni sus datos):

- `event_snapshots`  — una fila por captura. INSERT-only. Nunca se
  actualiza ni se sobrescribe una fila existente. `normalized_record_json`
  es la fuente de verdad completa de "qué sabíamos en ese instante"; las
  columnas de precio/calidad aplanadas son conveniencia de consulta
  derivada de ese mismo JSON en el momento de insertar.
- `feature_snapshots` — vector de features calculado en un instante dado,
  referenciando el snapshot del que se derivó. Aditiva, se empieza a
  poblar desde el Paso 2 (no en el Paso 0).
- `event_results`     — resultado final de un evento. Tabla SEPARADA,
  también append-only. NUNCA se une a `event_snapshots` al escribir: el
  enlace es solo lógico (mismo `event_id`) y se materializa exclusivamente
  al construir el dataset de backtesting (Paso 9), filtrando
  estrictamente por fecha (`captured_at` del snapshot anterior a
  `recorded_at` del resultado). Un snapshot pre-evento nunca lleva su
  propio resultado embebido.

Ver PLAN_PHASE2.md §11 para el diseño completo aprobado.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config.settings import DB_PATH
from src.models.schemas import NormalizedRecord

HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS event_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    event_start_time TEXT,
    market_id TEXT,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    last_price REAL,
    spread_yes REAL,
    spread_no REAL,
    volume REAL,
    volume_24h REAL,
    open_interest REAL,
    liquidity REAL,
    source_timestamps_json TEXT,
    data_quality_json TEXT NOT NULL,
    normalized_record_json TEXT NOT NULL,
    raw_refs_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_snapshots_event_captured
    ON event_snapshots(event_id, captured_at);

CREATE TABLE IF NOT EXISTS feature_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    event_snapshot_id INTEGER NOT NULL,
    feature_set_version TEXT NOT NULL,
    data_cutoff_timestamp TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    features_json TEXT NOT NULL,
    missing_features_json TEXT,
    FOREIGN KEY (event_snapshot_id) REFERENCES event_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_event
    ON feature_snapshots(event_id, computed_at);

CREATE TABLE IF NOT EXISTS event_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    result TEXT NOT NULL,
    settled_at TEXT,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_payload_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_results_event
    ON event_results(event_id);

-- Append-only reforzado a nivel de motor, no solo por convención de API:
-- estos triggers rechazan cualquier UPDATE/DELETE sobre las tres tablas,
-- incluso si alguien las toca con SQL crudo fuera de HistoryRepository.
-- (Hallazgo de auditoría: un UPDATE crudo mutaba yes_bid sin error antes
-- de este trigger -- ver PLAN_PHASE2.md / auditoría del Paso 0.)
CREATE TRIGGER IF NOT EXISTS trg_event_snapshots_no_update
BEFORE UPDATE ON event_snapshots
BEGIN
    SELECT RAISE(ABORT, 'event_snapshots es append-only: UPDATE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_snapshots_no_delete
BEFORE DELETE ON event_snapshots
BEGIN
    SELECT RAISE(ABORT, 'event_snapshots es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_feature_snapshots_no_update
BEFORE UPDATE ON feature_snapshots
BEGIN
    SELECT RAISE(ABORT, 'feature_snapshots es append-only: UPDATE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_feature_snapshots_no_delete
BEFORE DELETE ON feature_snapshots
BEGIN
    SELECT RAISE(ABORT, 'feature_snapshots es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_results_no_update
BEFORE UPDATE ON event_results
BEGIN
    SELECT RAISE(ABORT, 'event_results es append-only: UPDATE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_results_no_delete
BEFORE DELETE ON event_results
BEGIN
    SELECT RAISE(ABORT, 'event_results es append-only: DELETE no permitido');
END;
"""


def _require_utc_aware(dt: datetime, field_name: str) -> None:
    """Rechaza timestamps naive: el histórico exige UTC-aware siempre
    (principio no-negociable #10 de Fase 2), nunca se asume una zona."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} debe ser tz-aware (UTC), recibido naive: {dt!r}")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


class HistoryRepository:
    """Punto único de acceso al histórico append-only. No reemplaza ni
    envuelve `Repository` (Fase 1) — es un componente hermano, aditivo."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(HISTORY_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # timeout=30s (default de sqlite3 es 5s): tolera una espera breve
        # si otra conexión tiene el archivo bloqueado, en vez de fallar con
        # "database is locked" ante una colisión ocasional y pasajera.
        # WAL no se activa: el patrón de un solo escritor a la vez ya está
        # garantizado a nivel de proceso por scripts/pipeline_lock.py.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # SQLite desactiva la aplicación de FOREIGN KEY por defecto en cada
        # conexión nueva -- sin esto, feature_snapshots.event_snapshot_id
        # podía apuntar a un event_snapshots.id inexistente sin error
        # (hallazgo de auditoría del Paso 0).
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # event_snapshots (INSERT-only)
    # ------------------------------------------------------------------
    def save_event_snapshot(
        self,
        record: NormalizedRecord,
        source: str,
        captured_at: Optional[datetime] = None,
    ) -> int:
        """Inserta una NUEVA fila de snapshot. Nunca actualiza una fila
        existente: dos llamadas para el mismo `event_id` producen dos
        filas distintas, cada una con su propio `captured_at`."""
        captured_at = captured_at or datetime.now(timezone.utc)
        _require_utc_aware(captured_at, "captured_at")

        market = record.market
        dq = record.data_quality

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO event_snapshots (
                    event_id, sport, source, captured_at, event_start_time, market_id,
                    yes_bid, yes_ask, no_bid, no_ask, last_price,
                    spread_yes, spread_no, volume, volume_24h, open_interest, liquidity,
                    source_timestamps_json, data_quality_json, normalized_record_json, raw_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.sport.value,
                    source,
                    captured_at.isoformat(),
                    _iso(record.start_time),
                    record.market_id,
                    market.yes_bid,
                    market.yes_ask,
                    market.no_bid,
                    market.no_ask,
                    market.last_price,
                    market.spread_yes,
                    market.spread_no,
                    market.volume,
                    market.volume_24h,
                    market.open_interest,
                    market.liquidity,
                    json.dumps(
                        {src: _iso(ts) for src, ts in dq.source_timestamps.items()}
                    ),
                    dq.model_dump_json(),
                    record.model_dump_json(),
                    json.dumps(record.raw_refs),
                ),
            )
            return cursor.lastrowid

    def get_snapshots_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        """Devuelve todos los snapshots de un evento, ordenados por
        `captured_at` ascendente (para inspección/tests, no para
        producción de dataset — eso es el Paso 9)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_snapshots WHERE event_id = ? ORDER BY captured_at ASC, id ASC",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # feature_snapshots (INSERT-only, aditiva, se activa desde el Paso 2)
    # ------------------------------------------------------------------
    def save_feature_snapshot(
        self,
        event_id: str,
        event_snapshot_id: int,
        feature_set_version: str,
        data_cutoff_timestamp: datetime,
        features: Dict[str, Any],
        missing_features: Optional[List[str]] = None,
        computed_at: Optional[datetime] = None,
    ) -> int:
        _require_utc_aware(data_cutoff_timestamp, "data_cutoff_timestamp")
        computed_at = computed_at or datetime.now(timezone.utc)
        _require_utc_aware(computed_at, "computed_at")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feature_snapshots (
                    event_id, event_snapshot_id, feature_set_version,
                    data_cutoff_timestamp, computed_at, features_json, missing_features_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_snapshot_id,
                    feature_set_version,
                    data_cutoff_timestamp.isoformat(),
                    computed_at.isoformat(),
                    json.dumps(features),
                    json.dumps(missing_features or []),
                ),
            )
            return cursor.lastrowid

    def get_feature_snapshots_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM feature_snapshots WHERE event_id = ? ORDER BY computed_at ASC, id ASC",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # event_results (INSERT-only, tabla separada, nunca unida al escribir)
    # ------------------------------------------------------------------
    def save_event_result(
        self,
        event_id: str,
        sport: str,
        result: str,
        source: str,
        settled_at: Optional[datetime] = None,
        recorded_at: Optional[datetime] = None,
        source_payload_ref: Optional[str] = None,
    ) -> int:
        if settled_at is not None:
            _require_utc_aware(settled_at, "settled_at")
        recorded_at = recorded_at or datetime.now(timezone.utc)
        _require_utc_aware(recorded_at, "recorded_at")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO event_results (
                    event_id, sport, result, settled_at, recorded_at, source, source_payload_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    sport,
                    result,
                    _iso(settled_at),
                    recorded_at.isoformat(),
                    source,
                    source_payload_ref,
                ),
            )
            return cursor.lastrowid

    def get_results_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_results WHERE event_id = ? ORDER BY recorded_at ASC, id ASC",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]
