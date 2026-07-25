"""Lock de instancia única para `scripts/run_e2e.py` (subfase de
preparación de automatización, Paso 0d -- ver PLAN_PHASE2.md §11 y la
decisión arquitectónica que autoriza esta subfase, NO todavía el
scheduler). Usa `fcntl.flock`, nativo de macOS/POSIX -- sin dependencias
externas ni servicios nuevos.

Garantía de liberación: `fcntl.flock` está atado a la "open file
description" (no al proceso ni al hilo) -- el kernel la libera
automáticamente al cerrarse el file descriptor, incluso si el proceso
termina de forma abrupta (excepción no capturada, `kill -9`, panic). El
`finally` de abajo cubre explícitamente el camino normal (incluidas
excepciones lanzadas DENTRO del bloque `with`); la garantía ante una
terminación más abrupta del proceso viene del propio sistema operativo,
no de este código.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockAcquisitionError(Exception):
    """Otra instancia ya sostiene el lock. El llamador debe salir limpio,
    sin instanciar Repository/HistoryRepository ni ejecutar ningún pipeline."""


@contextmanager
def single_instance_lock(lock_path: Path) -> Iterator[None]:
    """Adquiere un lock exclusivo, no bloqueante, sobre `lock_path`.

    Lanza `LockAcquisitionError` de inmediato (nunca espera) si otra
    instancia ya lo sostiene -- el llamador decide qué hacer, este módulo
    nunca ejecuta lógica de pipeline ni de storage por sí mismo."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockAcquisitionError(
                f"otra instancia ya está en ejecución (lock activo en {lock_path})"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
