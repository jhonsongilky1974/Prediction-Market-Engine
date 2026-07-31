"""Opportunity Lifecycle -- persistencia (Fase 3, Paso 3.5). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.5.

Dos tablas nuevas, aditivas, en el MISMO archivo SQLite (`data/engine.db`)
que ya usan `Repository`/`HistoryRepository` (Fase 1/2) -- conviven sin
alterar en absoluto ninguna tabla existente, mismo patrón exacto que
`HISTORY_SCHEMA_SQL` (`src/storage/history_repository.py`, Paso 0 de
Fase 2): `CREATE TABLE IF NOT EXISTS`, triggers `RAISE(ABORT, ...)` que
rechazan `UPDATE`/`DELETE` incluso con SQL crudo fuera de esta clase,
`PRAGMA foreign_keys = ON` por conexión.

- `opportunities`           -- una fila por CADA `state_version` de una
  `Opportunity` (Principio 10: identidad estable, evaluaciones
  inmutables). NUNCA se actualiza una fila existente -- una
  re-evaluación inserta una fila NUEVA con `state_version` incrementado,
  exactamente como `Opportunity.previous_signal_id` ya lo describe.
- `opportunity_evaluations` -- una fila por `OpportunityEvaluation`
  (ya `frozen=True` a nivel de contrato, Paso 3.0). INSERT-only.

Ninguna FK dura entre ambas tablas (mismo motivo que `event_snapshots`/
`event_results` en Fase 2: el enlace es lógico por `opportunity_id`, no
un FK de fila -- `opportunities` no tiene una fila "canónica" única por
`opportunity_id`, tiene una por `state_version`, así que un FK de fila
no aplicaría limpiamente).

Validación de secuencia (aditiva, no exigida por ningún contrato de
Paso 3.0, pero consistente con "rechazar antes de persistir" ya usado en
`validate_policy_manifest`): `save_opportunity()`/
`save_opportunity_evaluation()` exigen `state_version == último + 1` (o
`1` si es la primera fila para ese `opportunity_id`) -- nunca aceptan un
salto ni un duplicado. `save_opportunity()` también exige que
`previous_signal_id` sea `None` únicamente en `state_version == 1` y no
sea `None` en cualquier `state_version` posterior -- una validación de
presencia, no de igualdad exacta contra un `evaluation_id` concreto (esa
correlación exacta depende de cómo un futuro orquestador de punta a
punta -- todavía no construido en ningún paso del roadmap -- decida
encadenar Policy Engine -> Opportunity; inventar esa regla exacta aquí
sería una decisión de diseño no pedida por este paso).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from config.settings import DB_PATH
from src.opportunity.schemas import Opportunity, OpportunityEvaluation

OPPORTUNITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    market_id TEXT,
    selection_id TEXT NOT NULL,
    side TEXT NOT NULL,
    sport TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_evaluated_at TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    previous_signal_id TEXT,
    opportunity_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opportunities_opportunity_id
    ON opportunities(opportunity_id, state_version);

CREATE TABLE IF NOT EXISTS opportunity_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    signal_type TEXT NOT NULL,
    decision_timestamp TEXT NOT NULL,
    data_cutoff_timestamp TEXT NOT NULL,
    model_version TEXT,
    calibration_version TEXT,
    policy_version TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    evaluation_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opportunity_evaluations_opportunity_id
    ON opportunity_evaluations(opportunity_id, state_version);

-- Append-only reforzado a nivel de motor, mismo patrón que
-- HISTORY_SCHEMA_SQL (Fase 2, Paso 0): rechaza UPDATE/DELETE incluso
-- con SQL crudo fuera de esta clase.
CREATE TRIGGER IF NOT EXISTS trg_opportunities_no_update
BEFORE UPDATE ON opportunities
BEGIN
    SELECT RAISE(ABORT, 'opportunities es append-only: UPDATE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_opportunities_no_delete
BEFORE DELETE ON opportunities
BEGIN
    SELECT RAISE(ABORT, 'opportunities es append-only: DELETE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_opportunity_evaluations_no_update
BEFORE UPDATE ON opportunity_evaluations
BEGIN
    SELECT RAISE(ABORT, 'opportunity_evaluations es append-only: UPDATE no permitido');
END;

CREATE TRIGGER IF NOT EXISTS trg_opportunity_evaluations_no_delete
BEFORE DELETE ON opportunity_evaluations
BEGIN
    SELECT RAISE(ABORT, 'opportunity_evaluations es append-only: DELETE no permitido');
END;
"""


class OpportunityRepository:
    """Punto único de acceso a `opportunities`/`opportunity_evaluations`.
    No reemplaza ni envuelve `Repository`/`HistoryRepository` (Fase 1/2)
    -- es un componente hermano, aditivo, mismo `db_path` (default
    `DB_PATH`, inyectable para tests -- SIEMPRE `tmp_path` en tests,
    nunca la ruta de producción)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(OPPORTUNITY_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # opportunities (INSERT-only, una fila por state_version)
    # ------------------------------------------------------------------

    def save_opportunity(self, opportunity: Opportunity) -> int:
        """Inserta una NUEVA fila -- nunca actualiza una existente.
        Valida secuencia de state_version (== último + 1, o 1 si es la
        primera) y presencia de previous_signal_id (None solo en
        state_version==1) antes de insertar."""
        with self._connect() as conn:
            latest = self._get_latest_opportunity_row(conn, opportunity.opportunity_id)
            expected_state_version = 1 if latest is None else latest["state_version"] + 1
            if opportunity.state_version != expected_state_version:
                raise ValueError(
                    f"state_version={opportunity.state_version} inválido para "
                    f"opportunity_id={opportunity.opportunity_id!r}: se esperaba "
                    f"{expected_state_version} (secuencia append-only)"
                )
            if opportunity.state_version == 1 and opportunity.previous_signal_id is not None:
                raise ValueError("previous_signal_id debe ser None en state_version==1 (primera evaluación)")
            if opportunity.state_version > 1 and opportunity.previous_signal_id is None:
                raise ValueError(
                    f"previous_signal_id no puede ser None en state_version={opportunity.state_version} "
                    "(debe referenciar la evaluación anterior)"
                )

            cursor = conn.execute(
                """
                INSERT INTO opportunities (
                    opportunity_id, event_id, market_id, selection_id, side, sport,
                    first_seen_at, last_evaluated_at, state_version, previous_signal_id, opportunity_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.opportunity_id,
                    opportunity.event_id,
                    opportunity.market_id,
                    opportunity.selection_id,
                    opportunity.side.value,
                    opportunity.sport.value,
                    opportunity.first_seen_at.isoformat(),
                    opportunity.last_evaluated_at.isoformat(),
                    opportunity.state_version,
                    opportunity.previous_signal_id,
                    opportunity.model_dump_json(),
                ),
            )
            return cursor.lastrowid

    def _get_latest_opportunity_row(self, conn: sqlite3.Connection, opportunity_id: str) -> Optional[sqlite3.Row]:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM opportunities WHERE opportunity_id = ? ORDER BY state_version DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()

    def get_latest_opportunity(self, opportunity_id: str) -> Optional[Opportunity]:
        with self._connect() as conn:
            row = self._get_latest_opportunity_row(conn, opportunity_id)
        return Opportunity.model_validate_json(row["opportunity_json"]) if row is not None else None

    def get_opportunity_history(self, opportunity_id: str) -> List[Opportunity]:
        """Todas las versiones de una Opportunity, ordenadas por
        state_version ascendente -- para inspección/auditoría, no para
        producción (mismo motivo que get_snapshots_for_event, Fase 2)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM opportunities WHERE opportunity_id = ? ORDER BY state_version ASC, id ASC",
                (opportunity_id,),
            ).fetchall()
        return [Opportunity.model_validate_json(row["opportunity_json"]) for row in rows]

    # ------------------------------------------------------------------
    # opportunity_evaluations (INSERT-only)
    # ------------------------------------------------------------------

    def save_opportunity_evaluation(self, evaluation: OpportunityEvaluation) -> int:
        """Inserta una NUEVA fila -- OpportunityEvaluation ya es
        frozen=True a nivel de contrato (Paso 3.0), esta capa refuerza
        además que la secuencia de state_version sea consecutiva."""
        with self._connect() as conn:
            latest = self._get_latest_evaluation_row(conn, evaluation.opportunity_id)
            expected_state_version = 1 if latest is None else latest["state_version"] + 1
            if evaluation.state_version != expected_state_version:
                raise ValueError(
                    f"state_version={evaluation.state_version} inválido para "
                    f"opportunity_id={evaluation.opportunity_id!r}: se esperaba "
                    f"{expected_state_version} (secuencia append-only)"
                )

            cursor = conn.execute(
                """
                INSERT INTO opportunity_evaluations (
                    evaluation_id, opportunity_id, state_version, signal_type,
                    decision_timestamp, data_cutoff_timestamp, model_version,
                    calibration_version, policy_version, feature_schema_version, evaluation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.evaluation_id,
                    evaluation.opportunity_id,
                    evaluation.state_version,
                    evaluation.policy_decision.signal_type.value,
                    evaluation.decision_timestamp.isoformat(),
                    evaluation.data_cutoff_timestamp.isoformat(),
                    evaluation.model_version,
                    evaluation.calibration_version,
                    evaluation.policy_version,
                    evaluation.feature_schema_version,
                    evaluation.model_dump_json(),
                ),
            )
            return cursor.lastrowid

    def _get_latest_evaluation_row(self, conn: sqlite3.Connection, opportunity_id: str) -> Optional[sqlite3.Row]:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM opportunity_evaluations WHERE opportunity_id = ? ORDER BY state_version DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()

    def get_latest_evaluation(self, opportunity_id: str) -> Optional[OpportunityEvaluation]:
        with self._connect() as conn:
            row = self._get_latest_evaluation_row(conn, opportunity_id)
        return OpportunityEvaluation.model_validate_json(row["evaluation_json"]) if row is not None else None

    def get_evaluations_for_opportunity(self, opportunity_id: str) -> List[OpportunityEvaluation]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM opportunity_evaluations WHERE opportunity_id = ? ORDER BY state_version ASC, id ASC",
                (opportunity_id,),
            ).fetchall()
        return [OpportunityEvaluation.model_validate_json(row["evaluation_json"]) for row in rows]
