#!/usr/bin/env python3
"""Mantenimiento de datos operacionales (Fase 3 -- ver DATA_RETENTION_POLICY.md).

Rota/comprime/purga `data/raw/*.json` y `logs/run_e2e.*.log`, y respalda
`data/engine.db` -- NUNCA toca `event_snapshots`/`feature_snapshots`/
`event_results` (retención indefinida, ver DATA_RETENTION_POLICY.md §2.1 y
TEMPORAL_REPRODUCIBILITY_SPEC.md §3): este módulo no importa
`src.storage.history_repository` ni abre ninguna tabla del motor -- el
respaldo de `engine.db` copia el archivo completo vía la API de backup en
caliente de SQLite (segura en concurrencia con `run_e2e.py`), sin ejecutar
ninguna sentencia SQL sobre su contenido.

Todas las funciones de clasificación y orquestación reciben rutas y `now`
como parámetros inyectables (mismo patrón de pureza que
`src/payoff/payoff_model.py`/`src/calibration/calibration_layer.py`) --
`main()` es la única capa que decide las rutas reales de producción.

Uso:
    source .venv/bin/activate
    python scripts/data_maintenance.py
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_BACKUPS_DIR, DATA_RAW_DIR, DB_PATH, LOGS_DIR, PROJECT_ROOT
from scripts.pipeline_lock import LockAcquisitionError, single_instance_lock

LOCK_PATH = PROJECT_ROOT / "data" / ".maintenance.lock"
# sysexits.h EX_TEMPFAIL -- mismo convenio que scripts/run_e2e.py.
EXIT_ALREADY_RUNNING = 75

RAW_UNCOMPRESSED_DAYS = 7
RAW_COMPRESSED_RETENTION_DAYS = 90
LOG_ROTATE_MAX_BYTES = 10 * 1024 * 1024
LOG_COMPRESSED_RETENTION_DAYS = 14
DB_BACKUP_RETENTION_COUNT = 30
# Margen de seguridad: nunca actuar sobre un archivo con menos de 1 día de
# antigüedad, para no interferir jamás con una corrida de run_e2e.py en curso.
MIN_FILE_AGE_DAYS = 1.0

_RAW_TIMESTAMP_RE = re.compile(r"^(\d{8}T\d{12})Z")


class FileAction(Enum):
    KEEP = "KEEP"
    COMPRESS = "COMPRESS"
    DELETE = "DELETE"


def classify_raw_file(is_compressed: bool, age_days: float) -> FileAction:
    """DATA_RETENTION_POLICY.md §2.2: 0-7 días sin cambios, 7-90 comprimido,
    >90 eliminado. Puro -- sin I/O."""
    if age_days >= RAW_COMPRESSED_RETENTION_DAYS:
        return FileAction.DELETE
    if not is_compressed and age_days >= RAW_UNCOMPRESSED_DAYS:
        return FileAction.COMPRESS
    return FileAction.KEEP


def classify_rotated_log(age_days: float) -> FileAction:
    """DATA_RETENTION_POLICY.md §2.3: un log ya rotado se comprime de
    inmediato (ver _rotate_log_if_needed) y se elimina pasados 14 días.
    Puro -- sin I/O."""
    if age_days >= LOG_COMPRESSED_RETENTION_DAYS:
        return FileAction.DELETE
    return FileAction.KEEP


def _parse_raw_timestamp(name: str) -> Optional[datetime]:
    match = _RAW_TIMESTAMP_RE.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def file_age_days(path: Path, now: datetime) -> float:
    """Antigüedad en días -- usa el timestamp embebido en el nombre cuando
    existe (convención `data/raw/`, más confiable que mtime ante una copia),
    si no cae a mtime del filesystem (logs rotados, cualquier otro caso)."""
    ts = _parse_raw_timestamp(path.name)
    if ts is None:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (now - ts).total_seconds() / 86400.0


def _compress_file(path: Path) -> Path:
    gz_path = path.with_name(path.name + ".gz")
    with open(path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    path.unlink()
    return gz_path


def process_raw_files(raw_dir: Path, now: datetime) -> Dict[str, int]:
    """Recorre raw_dir recursivamente; nunca actúa sobre archivos con
    age_days < MIN_FILE_AGE_DAYS (margen de seguridad frente a una corrida
    de run_e2e.py en curso). Ignora `.gitkeep`."""
    stats = {"compressed": 0, "deleted": 0}
    if not raw_dir.exists():
        return stats
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        age = file_age_days(path, now)
        if age < MIN_FILE_AGE_DAYS:
            continue
        is_compressed = path.name.endswith(".gz")
        action = classify_raw_file(is_compressed, age)
        if action is FileAction.COMPRESS:
            _compress_file(path)
            stats["compressed"] += 1
        elif action is FileAction.DELETE:
            path.unlink()
            stats["deleted"] += 1
    return stats


def rotate_log_if_needed(log_path: Path, now: datetime) -> Optional[Path]:
    """DATA_RETENTION_POLICY.md §2.3: rota cuando el archivo activo supera
    LOG_ROTATE_MAX_BYTES o cambió el día calendario (UTC) desde su última
    escritura, y comprime el archivo rotado de inmediato. No rota (ni toca)
    un archivo con menos de MIN_FILE_AGE_DAYS de antigüedad de todas formas
    -- ver guarda de tamaño/fecha abajo, que ya implica esa condición en la
    práctica para un log activo escrito continuamente."""
    if not log_path.exists():
        return None
    size = log_path.stat().st_size
    last_modified_date = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc).date()
    needs_rotation = size >= LOG_ROTATE_MAX_BYTES or last_modified_date < now.date()
    if not needs_rotation:
        return None

    base_rotated_name = f"{log_path.stem}.{last_modified_date.strftime('%Y%m%d')}{log_path.suffix}"
    rotated_path = log_path.with_name(base_rotated_name)
    counter = 1
    while rotated_path.exists() or rotated_path.with_name(rotated_path.name + ".gz").exists():
        rotated_path = log_path.with_name(
            f"{log_path.stem}.{last_modified_date.strftime('%Y%m%d')}_{counter}{log_path.suffix}"
        )
        counter += 1

    log_path.rename(rotated_path)
    return _compress_file(rotated_path)


def purge_old_logs(logs_dir: Path, now: datetime, active_log_names: frozenset) -> int:
    """Elimina logs rotados+comprimidos (`*.log.gz`) con más de
    LOG_COMPRESSED_RETENTION_DAYS. Nunca toca los logs activos (nombres en
    active_log_names, ej. `run_e2e.stdout.log`) ni nada que no termine en
    `.log.gz`."""
    deleted = 0
    if not logs_dir.exists():
        return deleted
    for path in sorted(logs_dir.glob("*.log.gz")):
        if path.name in active_log_names:
            continue
        age = file_age_days(path, now)
        if classify_rotated_log(age) is FileAction.DELETE:
            path.unlink()
            deleted += 1
    return deleted


def backup_database(db_path: Path, backups_dir: Path, now: datetime) -> Optional[Path]:
    """Respaldo diario e idempotente de db_path completo, vía la API de
    backup en caliente de sqlite3 (segura en concurrencia con un escritor
    activo -- no requiere pausar run_e2e.py ni su lock de instancia única).
    Si ya existe el backup de hoy (comprimido o no), no hace nada -- devuelve
    None. No abre ninguna tabla del contenido de db_path; el único ejecutable
    de esta función es `Connection.backup()`, que opera a nivel de archivo."""
    if not db_path.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"engine_{now.strftime('%Y%m%d')}.db"
    dest_path = backups_dir / dest_name
    gz_path = dest_path.with_name(dest_path.name + ".gz")
    if dest_path.exists() or gz_path.exists():
        return None

    src_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()
    return _compress_file(dest_path)


def prune_old_backups(backups_dir: Path, retention_count: int = DB_BACKUP_RETENTION_COUNT) -> int:
    """Conserva los retention_count backups más recientes (orden lexicográfico
    == cronológico dado el prefijo YYYYMMDD), elimina el resto."""
    if not backups_dir.exists():
        return 0
    backups = sorted(backups_dir.glob("engine_*.db.gz"), reverse=True)
    to_delete = backups[retention_count:]
    for path in to_delete:
        path.unlink()
    return len(to_delete)


def run_maintenance(
    now: Optional[datetime] = None,
    raw_dir: Path = DATA_RAW_DIR,
    logs_dir: Path = LOGS_DIR,
    db_path: Path = DB_PATH,
    backups_dir: Path = DATA_BACKUPS_DIR,
) -> Dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now debe ser tz-aware (UTC), recibido naive: {now!r}")

    raw_stats = process_raw_files(raw_dir, now)

    active_logs = ("run_e2e.stdout.log", "run_e2e.stderr.log")
    rotated = {}
    for name in active_logs:
        result = rotate_log_if_needed(logs_dir / name, now)
        rotated[name] = str(result) if result else None
    logs_purged = purge_old_logs(logs_dir, now, frozenset(active_logs))

    backup_path = backup_database(db_path, backups_dir, now)
    backups_pruned = prune_old_backups(backups_dir)

    return {
        "raw_compressed": raw_stats["compressed"],
        "raw_deleted": raw_stats["deleted"],
        "log_rotated": {k: v for k, v in rotated.items() if v is not None},
        "logs_purged": logs_purged,
        "backup_path": str(backup_path) if backup_path else None,
        "backups_pruned": backups_pruned,
    }


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        with single_instance_lock(LOCK_PATH):
            summary = run_maintenance()
    except LockAcquisitionError as exc:
        print(f"\n{exc}")
        print("Saliendo sin ejecutar mantenimiento.")
        return EXIT_ALREADY_RUNNING

    print("=== Mantenimiento de datos completado ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
