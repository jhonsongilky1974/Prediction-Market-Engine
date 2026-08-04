"""Almacenamiento local reproducible: SQLite para registros normalizados y
metadatos de matching/calidad, archivos JSON para las respuestas RAW.

Diseño deliberadamente simple para Fase 1 (ver PLAN.md): sin infraestructura
cloud, sin ORM. `sqlite3` de la stdlib + JSON en disco es suficiente para
reproducibilidad y debug.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from config.settings import DATA_RAW_DIR, DB_PATH
from src.models.schemas import NormalizedRecord

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    capture_ts TEXT NOT NULL,
    file_path TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS normalized_records (
    event_id TEXT NOT NULL PRIMARY KEY,
    sport TEXT NOT NULL,
    market_id TEXT,
    last_updated TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    event_id TEXT NOT NULL,
    source_a TEXT NOT NULL,
    source_a_id TEXT NOT NULL,
    source_b TEXT NOT NULL,
    source_b_id TEXT NOT NULL,
    match_confidence REAL,
    match_method TEXT,
    match_warnings TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_ts TEXT NOT NULL
);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Punto único de acceso a SQLite + almacenamiento RAW en disco."""

    def __init__(self, db_path: Path = DB_PATH, raw_dir: Path = DATA_RAW_DIR):
        self.db_path = db_path
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # timeout=30s (default de sqlite3 es 5s): tolera una espera breve
        # si otra conexión tiene el archivo bloqueado, en vez de fallar con
        # "database is locked" ante una colisión ocasional y pasajera.
        # WAL no se activa: el patrón de un solo escritor a la vez ya está
        # garantizado a nivel de proceso por scripts/pipeline_lock.py.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # RAW capture (JSON en disco + índice en SQLite)
    # ---------------------------------------------------------------
    def save_raw_capture(
        self,
        source: str,
        endpoint: str,
        payload: Optional[Any],
        ok: bool,
        error: Optional[str] = None,
        capture_ts: Optional[datetime] = None,
    ) -> str:
        """Guarda la respuesta cruda de una fuente. Nunca sobrescribe: cada
        captura obtiene su propio archivo con timestamp, para reproducibilidad.

        El timestamp por sí solo tiene resolución de microsegundo: dos
        capturas de la MISMA fuente+endpoint en el mismo microsegundo (poco
        probable pero no imposible) colisionarían y una sobrescribiría a la
        otra en silencio, contradiciendo la garantía de "nunca sobrescribe".
        Se añade un sufijo incremental si el nombre ya existe en disco."""
        capture_ts = capture_ts or datetime.now(timezone.utc)
        ts_str = capture_ts.strftime("%Y%m%dT%H%M%S%fZ")
        source_dir = self.raw_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)
        safe_endpoint = "".join(c if c.isalnum() else "_" for c in endpoint)[:120]

        file_path = source_dir / f"{ts_str}_{safe_endpoint}.json"
        suffix = 1
        while file_path.exists():
            file_path = source_dir / f"{ts_str}_{safe_endpoint}_{suffix}.json"
            suffix += 1

        record = {
            "source": source,
            "endpoint": endpoint,
            "capture_ts": capture_ts.isoformat(),
            "ok": ok,
            "error": error,
            "payload": payload,
        }
        file_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO raw_captures (source, endpoint, capture_ts, file_path, ok, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source, endpoint, capture_ts.isoformat(), str(file_path), int(ok), error),
            )
        return str(file_path)

    # ---------------------------------------------------------------
    # Registros normalizados
    # ---------------------------------------------------------------
    def save_normalized_record(self, record: NormalizedRecord) -> None:
        save_started = time.monotonic()
        logger.info("-> save_normalized_record event_id=%r", record.event_id)
        payload = record.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO normalized_records (event_id, sport, market_id, last_updated, payload_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(event_id) DO UPDATE SET "
                "market_id=excluded.market_id, last_updated=excluded.last_updated, payload_json=excluded.payload_json",
                (
                    record.event_id,
                    record.sport.value,
                    record.market_id,
                    _utcnow_iso(),
                    payload,
                ),
            )
        logger.info(
            "<- save_normalized_record OK event_id=%r elapsed_ms=%.1f",
            record.event_id, (time.monotonic() - save_started) * 1000,
        )

    def get_normalized_records(self, sport: Optional[str] = None) -> list[Dict[str, Any]]:
        query = "SELECT payload_json FROM normalized_records"
        params: tuple = ()
        if sport:
            query += " WHERE sport = ?"
            params = (sport,)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [json.loads(r[0]) for r in rows]

    # ---------------------------------------------------------------
    # Event matches (auditoría de matching)
    # ---------------------------------------------------------------
    def save_event_match(
        self,
        sport: str,
        event_id: str,
        source_a: str,
        source_a_id: str,
        source_b: str,
        source_b_id: str,
        match_confidence: Optional[float],
        match_method: str,
        match_warnings: list[str],
        needs_review: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO event_matches (sport, event_id, source_a, source_a_id, source_b, "
                "source_b_id, match_confidence, match_method, match_warnings, needs_review, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sport,
                    event_id,
                    source_a,
                    source_a_id,
                    source_b,
                    source_b_id,
                    match_confidence,
                    match_method,
                    json.dumps(match_warnings),
                    int(needs_review),
                    _utcnow_iso(),
                ),
            )
