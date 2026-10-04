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
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config.settings import DB_PATH
from src.models.schemas import NormalizedRecord

logger = logging.getLogger(__name__)

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

    @contextmanager
    def batch_write(self) -> Iterator[sqlite3.Connection]:
        """Auditoría Tramo 4 (latencia real de tenis, ~62s en
        `persist_records` -- ver informe de diagnóstico): UNA sola
        conexión/transacción reutilizada para un LOTE de escrituras, en
        vez de abrir+commitear+cerrar una conexión por fila. El llamador
        pasa el `conn` producido aquí a `save_event_snapshot(...,
        conn=conn)`/`save_feature_snapshot(..., conn=conn)` en cada
        iteración; el commit ocurre UNA sola vez al salir de este bloque
        sin excepción. Rollback explícito del lote COMPLETO si cualquier
        escritura falla -- nunca persistencia parcial, la excepción se
        relanza intacta."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
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
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Inserta una NUEVA fila de snapshot. Nunca actualiza una fila
        existente: dos llamadas para el mismo `event_id` producen dos
        filas distintas, cada una con su propio `captured_at`.

        `conn` opcional (auditoría Tramo 4): si se provee (típicamente el
        yielded por `batch_write()`), se reutiliza esa conexión/
        transacción SIN commitear aquí. Si se omite (default,
        comportamiento preexistente sin cambios), abre+commitea+cierra su
        propia conexión como siempre."""
        save_started = time.monotonic()
        logger.info("-> save_event_snapshot event_id=%r source=%r", record.event_id, source)
        captured_at = captured_at or datetime.now(timezone.utc)
        _require_utc_aware(captured_at, "captured_at")

        market = record.market
        dq = record.data_quality

        sql = """
            INSERT INTO event_snapshots (
                event_id, sport, source, captured_at, event_start_time, market_id,
                yes_bid, yes_ask, no_bid, no_ask, last_price,
                spread_yes, spread_no, volume, volume_24h, open_interest, liquidity,
                source_timestamps_json, data_quality_json, normalized_record_json, raw_refs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        params = (
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
            json.dumps({src: _iso(ts) for src, ts in dq.source_timestamps.items()}),
            dq.model_dump_json(),
            record.model_dump_json(),
            json.dumps(record.raw_refs),
        )
        if conn is not None:
            cursor = conn.execute(sql, params)
            snapshot_id = cursor.lastrowid
        else:
            with self._connect() as owned_conn:
                cursor = owned_conn.execute(sql, params)
                snapshot_id = cursor.lastrowid
        logger.info(
            "<- save_event_snapshot OK event_id=%r snapshot_id=%d elapsed_ms=%.1f",
            record.event_id, snapshot_id, (time.monotonic() - save_started) * 1000,
        )
        return snapshot_id

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

    def get_all_event_snapshots(self) -> List[Dict[str, Any]]:
        """Todos los event_snapshots existentes, sin filtrar por evento --
        mismo motivo que `get_all_feature_snapshots`/`get_all_event_results`
        (Paso 5b): el dataset builder de Elo (Paso 6) necesita recorrer
        identidad de equipos/`event_start_time` de TODOS los eventos, no de
        uno a la vez."""
        query_started = time.monotonic()
        logger.info("-> get_all_event_snapshots")
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_snapshots ORDER BY captured_at ASC, id ASC"
            ).fetchall()
        result = [dict(r) for r in rows]
        logger.info(
            "<- get_all_event_snapshots OK rows=%d elapsed_ms=%.1f",
            len(result), (time.monotonic() - query_started) * 1000,
        )
        return result

    def get_event_snapshot_contexts(self, event_snapshot_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Contexto temporal mínimo de `event_snapshots` por id (lectura
        pura, aditiva -- fix de fuga temporal de tenis, CONTINUITY.md
        §0.38): `captured_at`, `event_start_time` y el `status` del
        `NormalizedRecord` persistido (`json_extract`, sin deserializar el
        registro completo). Los features de un snapshot solo son
        pre-evento si ESTE contexto lo confirma; `feature_snapshots` por
        sí sola no trae ni hora de inicio ni estado. Consulta en bloques
        para respetar el límite de variables de SQLite."""
        contexts: Dict[int, Dict[str, Any]] = {}
        ids = list(dict.fromkeys(event_snapshot_ids))
        if not ids:
            return contexts
        chunk_size = 500
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            for start in range(0, len(ids), chunk_size):
                chunk = ids[start : start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT id, captured_at, event_start_time, "
                    "json_extract(normalized_record_json, '$.status') AS event_status "
                    f"FROM event_snapshots WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    contexts[row["id"]] = {
                        "captured_at": row["captured_at"],
                        "event_start_time": row["event_start_time"],
                        "event_status": row["event_status"],
                    }
        return contexts

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
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """`conn` opcional (auditoría Tramo 4): mismo contrato que
        `save_event_snapshot` -- si se provee, reutiliza esa conexión/
        transacción sin commitear aquí; si se omite, comportamiento
        preexistente sin cambios."""
        _require_utc_aware(data_cutoff_timestamp, "data_cutoff_timestamp")
        computed_at = computed_at or datetime.now(timezone.utc)
        _require_utc_aware(computed_at, "computed_at")

        sql = """
            INSERT INTO feature_snapshots (
                event_id, event_snapshot_id, feature_set_version,
                data_cutoff_timestamp, computed_at, features_json, missing_features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
        params = (
            event_id,
            event_snapshot_id,
            feature_set_version,
            data_cutoff_timestamp.isoformat(),
            computed_at.isoformat(),
            json.dumps(features),
            json.dumps(missing_features or []),
        )
        if conn is not None:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid
        with self._connect() as owned_conn:
            cursor = owned_conn.execute(sql, params)
            return cursor.lastrowid

    def get_feature_snapshots_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM feature_snapshots WHERE event_id = ? ORDER BY computed_at ASC, id ASC",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_feature_snapshots(self) -> List[Dict[str, Any]]:
        """Todos los feature_snapshots existentes, sin filtrar por evento --
        a diferencia de `get_feature_snapshots_for_event` (pensado para
        inspección de UN evento), este método es para quien necesita
        recorrer TODO el histórico (p.ej. el dataset builder de Paso 5a/9,
        que no sabe de antemano qué event_ids existen)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM feature_snapshots ORDER BY computed_at ASC, id ASC"
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

    def get_all_event_results(self) -> List[Dict[str, Any]]:
        """Todos los event_results existentes, sin filtrar por evento --
        ver docstring de `get_all_feature_snapshots`, mismo motivo."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_results ORDER BY recorded_at ASC, id ASC"
            ).fetchall()
        return [dict(r) for r in rows]
