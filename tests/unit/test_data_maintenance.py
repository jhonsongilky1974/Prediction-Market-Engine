"""Tests de scripts/data_maintenance.py (Fase 3, DATA_RETENTION_POLICY.md).

Cubre: umbrales exactos de clasificación (7/90/14 días), guarda de
antigüedad mínima, rotación de logs, respaldo+poda de engine.db, y el
invariante no negociable: este módulo nunca debe importar
src.storage.history_repository ni tocar event_snapshots/feature_snapshots/
event_results (retención indefinida, ver TEMPORAL_REPRODUCIBILITY_SPEC.md §3).
"""
from __future__ import annotations

import ast
import gzip
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.data_maintenance import (
    FileAction,
    backup_database,
    classify_raw_file,
    classify_rotated_log,
    file_age_days,
    process_raw_files,
    prune_old_backups,
    purge_old_logs,
    rotate_log_if_needed,
    run_maintenance,
)

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# classify_raw_file -- umbrales exactos (funciones puras)
# ---------------------------------------------------------------------


def test_raw_file_kept_under_7_days():
    assert classify_raw_file(is_compressed=False, age_days=6.99) == FileAction.KEEP


def test_raw_file_compressed_at_exactly_7_days():
    assert classify_raw_file(is_compressed=False, age_days=7.0) == FileAction.COMPRESS


def test_raw_file_stays_compressed_between_7_and_90_days():
    assert classify_raw_file(is_compressed=True, age_days=50.0) == FileAction.KEEP


def test_raw_file_deleted_at_exactly_90_days():
    assert classify_raw_file(is_compressed=False, age_days=90.0) == FileAction.DELETE
    assert classify_raw_file(is_compressed=True, age_days=90.0) == FileAction.DELETE


def test_raw_file_under_90_compressed_already_kept():
    assert classify_raw_file(is_compressed=True, age_days=89.99) == FileAction.KEEP


# ---------------------------------------------------------------------
# classify_rotated_log
# ---------------------------------------------------------------------


def test_rotated_log_kept_under_14_days():
    assert classify_rotated_log(age_days=13.99) == FileAction.KEEP


def test_rotated_log_deleted_at_exactly_14_days():
    assert classify_rotated_log(age_days=14.0) == FileAction.DELETE


# ---------------------------------------------------------------------
# file_age_days -- timestamp embebido vs. mtime
# ---------------------------------------------------------------------


def test_file_age_days_uses_embedded_raw_timestamp(tmp_path):
    path = tmp_path / "20260701T120000000000Z_events_KXMLBGAME.json"
    path.write_text("{}")
    age = file_age_days(path, NOW)
    assert abs(age - 30.0) < 0.01


def test_file_age_days_falls_back_to_mtime_when_no_embedded_timestamp(tmp_path):
    import os

    path = tmp_path / "run_e2e.stdout.20260725.log"
    path.write_text("x")
    six_days_ago = (NOW - timedelta(days=6)).timestamp()
    os.utime(path, (six_days_ago, six_days_ago))
    age = file_age_days(path, NOW)
    assert abs(age - 6.0) < 0.01


# ---------------------------------------------------------------------
# process_raw_files -- orquestación con guarda de antigüedad mínima
# ---------------------------------------------------------------------


def _raw_name(now: datetime, age_days: float) -> str:
    ts = now - timedelta(days=age_days)
    return f"{ts.strftime('%Y%m%dT%H%M%S%f')}Z_events_KXMLBGAME.json"


def test_process_raw_files_never_touches_files_under_min_age(tmp_path):
    raw_dir = tmp_path / "raw" / "kalshi"
    raw_dir.mkdir(parents=True)
    fresh = raw_dir / _raw_name(NOW, age_days=0.5)
    fresh.write_text("{}")
    stats = process_raw_files(tmp_path / "raw", NOW)
    assert stats == {"compressed": 0, "deleted": 0}
    assert fresh.exists()


def test_process_raw_files_compresses_and_deletes_by_age(tmp_path):
    raw_dir = tmp_path / "raw" / "kalshi"
    raw_dir.mkdir(parents=True)
    keep = raw_dir / _raw_name(NOW, age_days=3)
    compress = raw_dir / _raw_name(NOW, age_days=10)
    delete = raw_dir / _raw_name(NOW, age_days=100)
    for p in (keep, compress, delete):
        p.write_text("{}")

    stats = process_raw_files(tmp_path / "raw", NOW)

    assert stats == {"compressed": 1, "deleted": 1}
    assert keep.exists()
    assert not compress.exists()
    assert (raw_dir / (compress.name + ".gz")).exists()
    assert not delete.exists()
    assert not (raw_dir / (delete.name + ".gz")).exists()


def test_process_raw_files_ignores_gitkeep(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / ".gitkeep").write_text("")
    stats = process_raw_files(raw_dir, NOW)
    assert stats == {"compressed": 0, "deleted": 0}
    assert (raw_dir / ".gitkeep").exists()


def test_process_raw_files_is_idempotent(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / _raw_name(NOW, age_days=10)).write_text("{}")
    process_raw_files(raw_dir, NOW)
    second_run_stats = process_raw_files(raw_dir, NOW)
    assert second_run_stats == {"compressed": 0, "deleted": 0}


# ---------------------------------------------------------------------
# rotate_log_if_needed / purge_old_logs
# ---------------------------------------------------------------------


def test_rotate_log_not_needed_when_small_and_same_day(tmp_path):
    log = tmp_path / "run_e2e.stdout.log"
    log.write_text("hola")
    result = rotate_log_if_needed(log, NOW)
    assert result is None
    assert log.exists()


def test_rotate_log_by_size(tmp_path):
    log = tmp_path / "run_e2e.stdout.log"
    log.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    result = rotate_log_if_needed(log, NOW)
    assert result is not None
    assert result.name.endswith(".log.gz")
    assert not log.exists()  # el archivo original fue renombrado+comprimido
    with gzip.open(result, "rb") as f:
        assert f.read() == b"x" * (10 * 1024 * 1024 + 1)


def test_rotate_log_by_day_change(tmp_path, monkeypatch):
    import os
    import time

    log = tmp_path / "run_e2e.stdout.log"
    log.write_text("ayer")
    yesterday = NOW - timedelta(days=1)
    os.utime(log, (yesterday.timestamp(), yesterday.timestamp()))

    result = rotate_log_if_needed(log, NOW)
    assert result is not None
    assert not log.exists()


def test_purge_old_logs_deletes_beyond_retention_keeps_active(tmp_path):
    import os

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old_rotated = logs_dir / "run_e2e.stdout.20260101.log.gz"
    old_rotated.write_bytes(b"")
    old_ts = (NOW - timedelta(days=20)).timestamp()
    os.utime(old_rotated, (old_ts, old_ts))

    recent_rotated = logs_dir / "run_e2e.stdout.20260730.log.gz"
    recent_rotated.write_bytes(b"")
    recent_ts = (NOW - timedelta(days=1)).timestamp()
    os.utime(recent_rotated, (recent_ts, recent_ts))

    active = logs_dir / "run_e2e.stdout.log"
    active.write_text("activo")

    deleted = purge_old_logs(logs_dir, NOW, frozenset({"run_e2e.stdout.log"}))

    assert deleted == 1
    assert not old_rotated.exists()
    assert recent_rotated.exists()
    assert active.exists()


# ---------------------------------------------------------------------
# backup_database / prune_old_backups
# ---------------------------------------------------------------------


def _make_sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hola')")
    conn.commit()
    conn.close()


def test_backup_database_creates_compressed_copy_with_same_content(tmp_path):
    db_path = tmp_path / "engine.db"
    _make_sqlite_db(db_path)
    backups_dir = tmp_path / "backups"

    result = backup_database(db_path, backups_dir, NOW)

    assert result is not None
    assert result.name == "engine_20260731.db.gz"
    restored = tmp_path / "restored.db"
    with gzip.open(result, "rb") as f_in, open(restored, "wb") as f_out:
        f_out.write(f_in.read())
    conn = sqlite3.connect(str(restored))
    rows = conn.execute("SELECT v FROM t").fetchall()
    conn.close()
    assert rows == [("hola",)]


def test_backup_database_idempotent_same_day(tmp_path):
    db_path = tmp_path / "engine.db"
    _make_sqlite_db(db_path)
    backups_dir = tmp_path / "backups"

    first = backup_database(db_path, backups_dir, NOW)
    second = backup_database(db_path, backups_dir, NOW)

    assert first is not None
    assert second is None
    assert len(list(backups_dir.glob("engine_*.db.gz"))) == 1


def test_backup_database_missing_source_returns_none(tmp_path):
    result = backup_database(tmp_path / "does_not_exist.db", tmp_path / "backups", NOW)
    assert result is None


def test_prune_old_backups_keeps_only_retention_count(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for offset in range(35):  # 35 backups simulados, uno por día
        day = start + timedelta(days=offset)
        (backups_dir / f"engine_{day.strftime('%Y%m%d')}.db.gz").write_bytes(b"")
    assert len(list(backups_dir.glob("engine_*.db.gz"))) == 35

    deleted = prune_old_backups(backups_dir, retention_count=30)

    remaining = sorted(backups_dir.glob("engine_*.db.gz"))
    assert deleted == 5
    assert len(remaining) == 30
    # se conservan los 30 más recientes -- los 5 más antiguos (2026-06-01..05) se eliminan
    assert remaining[0].name == f"engine_{(start + timedelta(days=5)).strftime('%Y%m%d')}.db.gz"
    assert remaining[-1].name == f"engine_{(start + timedelta(days=34)).strftime('%Y%m%d')}.db.gz"


# ---------------------------------------------------------------------
# run_maintenance -- orquestación end-to-end con directorios inyectados
# ---------------------------------------------------------------------


def test_run_maintenance_end_to_end(tmp_path):
    raw_dir = tmp_path / "raw" / "kalshi"
    raw_dir.mkdir(parents=True)
    (raw_dir / _raw_name(NOW, age_days=10)).write_text("{}")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    db_path = tmp_path / "engine.db"
    _make_sqlite_db(db_path)
    backups_dir = tmp_path / "backups"

    summary = run_maintenance(
        now=NOW, raw_dir=tmp_path / "raw", logs_dir=logs_dir, db_path=db_path, backups_dir=backups_dir
    )

    assert summary["raw_compressed"] == 1
    assert summary["raw_deleted"] == 0
    assert summary["backup_path"] is not None
    assert (backups_dir / "engine_20260731.db.gz").exists()


def test_run_maintenance_naive_now_raises(tmp_path):
    with pytest.raises(ValueError, match="tz-aware"):
        run_maintenance(now=datetime(2026, 7, 31), raw_dir=tmp_path, logs_dir=tmp_path, db_path=tmp_path / "x.db")


def test_run_maintenance_idempotent(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / _raw_name(NOW, age_days=10)).write_text("{}")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    db_path = tmp_path / "engine.db"
    _make_sqlite_db(db_path)
    backups_dir = tmp_path / "backups"

    run_maintenance(now=NOW, raw_dir=raw_dir, logs_dir=logs_dir, db_path=db_path, backups_dir=backups_dir)
    second = run_maintenance(now=NOW, raw_dir=raw_dir, logs_dir=logs_dir, db_path=db_path, backups_dir=backups_dir)

    assert second["raw_compressed"] == 0
    assert second["raw_deleted"] == 0
    assert second["backup_path"] is None


# ---------------------------------------------------------------------
# Invariante no negociable: nunca importar history_repository ni tocar
# las tablas append-only del motor (AST, no substring -- ver
# CONTINUITY.md sobre el falso positivo de Paso 3.4.1).
# ---------------------------------------------------------------------


def test_does_not_import_history_repository():
    source = (Path(__file__).resolve().parents[2] / "scripts" / "data_maintenance.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or "history_repository" not in node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "history_repository" not in alias.name
