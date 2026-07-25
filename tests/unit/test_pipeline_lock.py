"""Tests del lock de instancia única (`scripts/pipeline_lock.py`, subfase
de preparación de automatización, Paso 0d). Sin red, sin tocar
`data/engine.db` -- todo sobre `tmp_path`.

Nota técnica: `flock` asocia el lock a la "open file description", no al
proceso -- dos llamadas a `os.open()` sobre la MISMA ruta, incluso desde el
mismo proceso de test, producen dos file descriptions independientes que
compiten entre sí exactamente igual que dos procesos distintos lo harían.
Es la forma estándar de testear `flock` sin necesitar subprocesos reales.
"""
from __future__ import annotations

import fcntl
import os

import pytest

from scripts.pipeline_lock import LockAcquisitionError, single_instance_lock


def test_second_lock_attempt_fails_while_first_holds_it(tmp_path):
    lock_path = tmp_path / "run_e2e.lock"
    with single_instance_lock(lock_path):
        with pytest.raises(LockAcquisitionError):
            with single_instance_lock(lock_path):
                pytest.fail("no debía poder adquirirse un segundo lock mientras el primero está activo")


def test_lock_released_after_normal_exit_allows_reacquisition(tmp_path):
    lock_path = tmp_path / "run_e2e.lock"
    with single_instance_lock(lock_path):
        pass  # primera adquisición, liberada al salir del `with`

    # Si no se liberó correctamente, esta segunda adquisición fallaría.
    with single_instance_lock(lock_path):
        pass


def test_lock_released_after_exception_inside_block_allows_reacquisition(tmp_path):
    lock_path = tmp_path / "run_e2e.lock"

    with pytest.raises(ValueError):
        with single_instance_lock(lock_path):
            raise ValueError("boom -- simula un pipeline que falla a mitad de corrida")

    # El `finally` de single_instance_lock debe haber liberado el lock aun
    # cuando el cuerpo del `with` lanzó una excepción no relacionada con el lock.
    with single_instance_lock(lock_path):
        pass


def test_lock_creates_parent_directory_if_missing(tmp_path):
    lock_path = tmp_path / "nested" / "dir" / "run_e2e.lock"
    assert not lock_path.parent.exists()
    with single_instance_lock(lock_path):
        assert lock_path.exists()


def test_lock_file_itself_is_actually_flock_locked(tmp_path):
    """Verifica el mecanismo real (no solo el comportamiento de alto nivel):
    mientras `single_instance_lock` está activo, un intento externo de
    `flock` no bloqueante sobre el mismo archivo debe fallar con OSError."""
    lock_path = tmp_path / "run_e2e.lock"
    with single_instance_lock(lock_path):
        fd = os.open(str(lock_path), os.O_RDWR)
        try:
            with pytest.raises(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
