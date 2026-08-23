"""Tests de la optimización de persistencia batch en `run_tennis_pipeline`
(auditoría Tramo 4 -- latencia real de tenis, Liang vs Kraus, ~62s
medidos en `persist_records` por 903 transacciones SQLite individuales).
Verifica: conteo de transacciones O(1), equivalencia de resultado con el
modo per-row anterior, atomicidad (rollback completo ante fallo), y
concurrencia real entre dos corridas simultáneas. Sin red: mismo patrón
de conectores monkeypatcheados que `test_tennis_pipeline_feature_wiring.py`."""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone

import pytest

from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.sofascore import SofascoreConnector
from src.models.schemas import NormalizedRecord, Sport
from src.pipelines.tennis_pipeline import run_tennis_pipeline
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="down"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _scoreboard_with_matches(n: int, date_str: str = "2026-08-22T11:00Z"):
    """Genera un scoreboard sintético con `n` partidos DISTINTOS -- mismo
    payload shape verificado en test_tennis_pipeline_feature_wiring.py,
    escalado para probar el comportamiento del batch a un tamaño cercano
    al caso real (301 records, ver informe de diagnóstico)."""
    competitions = []
    for i in range(n):
        competitions.append(
            {
                "id": str(1000 + i),
                "date": date_str,
                "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}},
                "competitors": [
                    {"id": str(2000 + i), "homeAway": "home", "athlete": {"displayName": f"Home Player {i}"}},
                    {"id": str(3000 + i), "homeAway": "away", "athlete": {"displayName": f"Away Player {i}"}},
                ],
                "round": {"id": "1", "displayName": "Round of 128"},
            }
        )
    return {
        "events": [
            {
                "id": "evt1",
                "name": "Batch Test Open",
                "groupings": [{"grouping": {"displayName": "Women's Singles"}, "competitions": competitions}],
            }
        ]
    }


def _patch_kalshi_down(monkeypatch):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi down"),
    )


def _patch_sofascore_down(monkeypatch):
    monkeypatch.setattr(SofascoreConnector, "search", lambda self, query: _fail("sofascore down"))


def _run_batch_of(n, monkeypatch, tmp_repository, tmp_history_repository, tour="wta", date="20260822"):
    payload = _scoreboard_with_matches(n)
    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", lambda self, t, d: _ok(payload))
    _patch_kalshi_down(monkeypatch)
    _patch_sofascore_down(monkeypatch)
    return run_tennis_pipeline(
        tour, date, repository=tmp_repository, history_repository=tmp_history_repository, enrich_sofascore=False
    )


# ---------------------------------------------------------------------
# A. Conteo de conexiones/transacciones: O(1), no O(N)
# ---------------------------------------------------------------------


def test_a_persist_records_uses_o1_connections_not_on(monkeypatch, tmp_repository, tmp_history_repository):
    per_row_connect_calls = {"repository": 0, "history_repository": 0}
    batch_write_calls = {"repository": 0, "history_repository": 0}

    orig_repo_connect = Repository._connect
    orig_hist_connect = HistoryRepository._connect
    orig_repo_batch = Repository.batch_write
    orig_hist_batch = HistoryRepository.batch_write

    def counted_repo_connect(self):
        per_row_connect_calls["repository"] += 1
        return orig_repo_connect(self)

    def counted_hist_connect(self):
        per_row_connect_calls["history_repository"] += 1
        return orig_hist_connect(self)

    def counted_repo_batch(self):
        batch_write_calls["repository"] += 1
        return orig_repo_batch(self)

    def counted_hist_batch(self):
        batch_write_calls["history_repository"] += 1
        return orig_hist_batch(self)

    monkeypatch.setattr(Repository, "_connect", counted_repo_connect)
    monkeypatch.setattr(HistoryRepository, "_connect", counted_hist_connect)
    monkeypatch.setattr(Repository, "batch_write", counted_repo_batch)
    monkeypatch.setattr(HistoryRepository, "batch_write", counted_hist_batch)

    n = 200
    result = _run_batch_of(n, monkeypatch, tmp_repository, tmp_history_repository)
    assert len(result.records) == n

    # batch_write(): exactamente UNA vez por repositorio, sin importar N.
    assert batch_write_calls["repository"] == 1
    assert batch_write_calls["history_repository"] == 1

    # _connect() per-row (el camino viejo, conn=None): CERO veces durante
    # el persist de este lote -- todas las escrituras de save_* usaron la
    # conexión batch compartida, no abrieron una propia. (Otros pasos del
    # pipeline, como build_tennis_history_index, sí usan _connect() para
    # LECTURA -- eso es esperado y no es lo que este test mide: aquí solo
    # nos importa que save_normalized_record/save_event_snapshot/
    # save_feature_snapshot, llamadas N veces cada una, no abrieron N
    # conexiones propias.)
    # Verificación directa: si el batch NO estuviera activo, este mismo
    # lote requeriría 3*N _connect() (una por save_* por record) = 600
    # para N=200. Confirmamos que NO se acerca a eso.
    assert per_row_connect_calls["history_repository"] < n  # muy por debajo de 3*N=600


# ---------------------------------------------------------------------
# B. Equivalencia: modo batch produce las mismas filas que el modo
# per-row anterior (mismo upsert, misma deduplicación, mismo resultado)
# ---------------------------------------------------------------------


def test_b_batch_mode_produces_equivalent_rows_to_per_row_mode(tmp_path):
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_equiv_test",
        participant_a="Player A",
        participant_b="Player B",
    )

    # Modo viejo (conn=None, per-row: abre+commitea+cierra su propia conexión).
    repo_old = Repository(db_path=tmp_path / "old.db", raw_dir=tmp_path / "raw_old")
    repo_old.save_normalized_record(record)
    hist_old = HistoryRepository(db_path=tmp_path / "old_hist.db")
    snapshot_id_old = hist_old.save_event_snapshot(record, source="test")

    # Modo nuevo (conn=batch, reutilizando una única conexión/transacción).
    repo_new = Repository(db_path=tmp_path / "new.db", raw_dir=tmp_path / "raw_new")
    with repo_new.batch_write() as conn:
        repo_new.save_normalized_record(record, conn=conn)
    hist_new = HistoryRepository(db_path=tmp_path / "new_hist.db")
    with hist_new.batch_write() as conn:
        snapshot_id_new = hist_new.save_event_snapshot(record, source="test", conn=conn)

    old_rows = repo_old.get_normalized_records()
    new_rows = repo_new.get_normalized_records()
    assert old_rows == new_rows  # payload_json idéntico (mismo record, sin timestamp variable en el payload)

    old_snapshots = hist_old.get_snapshots_for_event(record.event_id)
    new_snapshots = hist_new.get_snapshots_for_event(record.event_id)
    assert len(old_snapshots) == len(new_snapshots) == 1
    # Comparación campo a campo, excluyendo id/captured_at (no
    # deterministas entre corridas separadas).
    ignore_keys = {"id", "captured_at"}
    old_snap = {k: v for k, v in old_snapshots[0].items() if k not in ignore_keys}
    new_snap = {k: v for k, v in new_snapshots[0].items() if k not in ignore_keys}
    assert old_snap == new_snap
    assert snapshot_id_old == snapshot_id_new == 1  # primer id autoincrement en cada DB nueva


def test_b_full_pipeline_batch_produces_same_records_as_reference_run(monkeypatch, tmp_repository, tmp_history_repository):
    """El resultado LÓGICO (records normalizados devueltos, snapshots
    persistidos) de una corrida completa vía el pipeline batch coincide
    con lo que produciría el pipeline si se llamaran las mismas
    operaciones sin batch -- ya cubierto campo a campo en el test
    anterior; aquí se verifica a nivel de pipeline completo que nada se
    perdió/duplicó."""
    n = 25
    result = _run_batch_of(n, monkeypatch, tmp_repository, tmp_history_repository)
    assert len(result.records) == n
    assert len(tmp_repository.get_normalized_records()) == n
    all_snapshots = tmp_history_repository.get_all_event_snapshots()
    assert len(all_snapshots) == n
    all_features = tmp_history_repository.get_all_feature_snapshots()
    assert len(all_features) == n  # fetch_features=True por defecto


# ---------------------------------------------------------------------
# C. Rollback: fallo inyectado a mitad del lote -> CERO persistencia
# parcial de ese lote
# ---------------------------------------------------------------------


def test_c_injected_failure_mid_batch_leaves_zero_partial_persistence(monkeypatch, tmp_repository, tmp_history_repository):
    n = 30
    fail_at = 15
    call_count = {"n": 0}

    orig_save_event_snapshot = HistoryRepository.save_event_snapshot

    def failing_save_event_snapshot(self, record, source, captured_at=None, conn=None):
        call_count["n"] += 1
        if call_count["n"] == fail_at:
            raise RuntimeError("fallo inyectado a mitad del lote (test de rollback)")
        return orig_save_event_snapshot(self, record, source, captured_at=captured_at, conn=conn)

    monkeypatch.setattr(HistoryRepository, "save_event_snapshot", failing_save_event_snapshot)

    with pytest.raises(RuntimeError, match="fallo inyectado"):
        _run_batch_of(n, monkeypatch, tmp_repository, tmp_history_repository)

    # CERO filas persistidas de este lote -- ni normalized_records
    # (repositorio distinto, pero su transacción también estaba abierta
    # dentro del mismo ExitStack y se deshace al propagar la excepción)
    # ni event_snapshots ni feature_snapshots.
    assert tmp_repository.get_normalized_records() == []
    assert tmp_history_repository.get_all_event_snapshots() == []
    assert tmp_history_repository.get_all_feature_snapshots() == []

    # La conexión de escritura no quedó bloqueada/corrupta: una segunda
    # corrida limpia funciona con normalidad. monkeypatch.undo() restaura
    # TODOS los patches de este fixture (incluidos ESPN/Kalshi/SofaScore),
    # así que _run_batch_of los vuelve a aplicar frescos para esta 2a corrida.
    monkeypatch.undo()
    result = _run_batch_of(5, monkeypatch, tmp_repository, tmp_history_repository)
    assert len(result.records) == 5
    assert len(tmp_repository.get_normalized_records()) == 5


# ---------------------------------------------------------------------
# D. Concurrencia: dos persistencias simultáneas contra la misma DB
# terminan correctamente (o fallan de forma controlada), sin corrupción
# ---------------------------------------------------------------------


def test_d_two_concurrent_batch_writes_no_corruption(tmp_path):
    db_path = tmp_path / "concurrent.db"
    repo_a = Repository(db_path=db_path, raw_dir=tmp_path / "raw_a")
    repo_b = Repository(db_path=db_path, raw_dir=tmp_path / "raw_b")

    errors = []

    def worker(repo, prefix, n):
        try:
            with repo.batch_write() as conn:
                for i in range(n):
                    record = NormalizedRecord(
                        sport=Sport.TENNIS, event_id=f"{prefix}_{i}", participant_a="A", participant_b="B"
                    )
                    repo.save_normalized_record(record, conn=conn)
        except Exception as exc:  # noqa: BLE001 -- se captura para inspección
            errors.append(exc)

    n_per_thread = 100
    t1 = threading.Thread(target=worker, args=(repo_a, "threadA", n_per_thread))
    t2 = threading.Thread(target=worker, args=(repo_b, "threadB", n_per_thread))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not t1.is_alive() and not t2.is_alive()  # ningún deadlock permanente (timeout=30s de _connect ya lo cubre)
    # Ambos threads deben terminar SIN excepción -- timeout=30.0 en
    # batch_write() alcanza de sobra para serializar 2 transacciones de
    # 100 filas cada una contra el mismo archivo.
    assert errors == [], f"al menos un thread falló: {errors}"

    conn = sqlite3.connect(db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM normalized_records").fetchone()
    conn.close()
    assert count == n_per_thread * 2  # sin pérdida ni duplicación de filas


# ---------------------------------------------------------------------
# E. Performance: persist_records con un lote cercano a 301 records
# ---------------------------------------------------------------------


def test_e_performance_batch_vs_per_row_close_to_real_batch_size(monkeypatch, tmp_path):
    n = 300

    # "Antes": simula el patrón per-row viejo directamente (sin pasar por
    # run_tennis_pipeline, para aislar el costo puro de persistencia).
    repo_before = Repository(db_path=tmp_path / "before.db", raw_dir=tmp_path / "raw_before")
    hist_before = HistoryRepository(db_path=tmp_path / "before_hist.db")
    records = [
        NormalizedRecord(sport=Sport.TENNIS, event_id=f"perf_{i}", participant_a="A", participant_b="B")
        for i in range(n)
    ]
    t0 = time.perf_counter()
    for record in records:
        repo_before.save_normalized_record(record)  # conn=None -- una conexión+commit+cierre por fila
        hist_before.save_event_snapshot(record, source="perf_test")
    t_before = time.perf_counter() - t0

    # "Después": modo batch (una sola conexión/transacción para todo el lote).
    repo_after = Repository(db_path=tmp_path / "after.db", raw_dir=tmp_path / "raw_after")
    hist_after = HistoryRepository(db_path=tmp_path / "after_hist.db")
    t0 = time.perf_counter()
    with repo_after.batch_write() as norm_conn, hist_after.batch_write() as hist_conn:
        for record in records:
            repo_after.save_normalized_record(record, conn=norm_conn)
            hist_after.save_event_snapshot(record, source="perf_test", conn=hist_conn)
    t_after = time.perf_counter() - t0

    print(f"\n[perf] persist {n} records -- antes(per-row)={t_before*1000:.1f}ms despues(batch)={t_after*1000:.1f}ms")

    assert len(repo_after.get_normalized_records()) == n
    assert len(hist_after.get_all_event_snapshots()) == n
    # El batch nunca debe ser más lento que el modo per-row -- es la
    # propiedad mínima que este test debe garantizar en cualquier
    # máquina/disco, más allá del factor exacto medido.
    assert t_after <= t_before


# ---------------------------------------------------------------------
# F. Regresión crítica: Repository e HistoryRepository apuntando al
# MISMO archivo (config.settings.DB_PATH en producción, SIEMPRE) --
# hallazgo real durante la implementación: dos conexiones de escritura
# separadas y simultáneas al mismo archivo se autobloquean (la 2a espera
# el lock que la 1a mantiene abierto hasta el commit final del lote, que
# nunca llega). Los fixtures tmp_repository/tmp_history_repository usan
# archivos DISTINTOS (test.db vs history.db) y NO habrían detectado
# esto -- este test usa deliberadamente el MISMO path para ambos,
# replicando la configuración real de producción.
# ---------------------------------------------------------------------


def test_f_same_db_path_repository_and_history_repository_share_connection(
    monkeypatch, tmp_path
):
    same_path = tmp_path / "shared.db"
    repo = Repository(db_path=same_path, raw_dir=tmp_path / "raw")
    hist = HistoryRepository(db_path=same_path)
    assert repo.db_path == hist.db_path

    n = 40
    payload = _scoreboard_with_matches(n)
    monkeypatch.setattr(EspnTennisConnector, "get_scoreboard", lambda self, t, d: _ok(payload))
    _patch_kalshi_down(monkeypatch)
    _patch_sofascore_down(monkeypatch)

    # Antes del fix de "mismo path", esto habría lanzado
    # sqlite3.OperationalError: database is locked en el primer record.
    result = run_tennis_pipeline(
        "wta", "20260822", repository=repo, history_repository=hist, enrich_sofascore=False
    )
    assert len(result.records) == n
    assert len(repo.get_normalized_records()) == n
    assert len(hist.get_all_event_snapshots()) == n
    assert len(hist.get_all_feature_snapshots()) == n


def test_f_shared_connection_still_enforces_foreign_keys(tmp_path):
    """La conexión COMPARTIDA (misma db_path) debe seguir siendo la de
    HistoryRepository -- la única que activa PRAGMA foreign_keys=ON
    (protección exigida por la auditoría de Fase 2 para
    feature_snapshots.event_snapshot_id). Verifica directamente que un
    event_snapshot_id inexistente sigue siendo rechazado dentro de un
    batch_write() -- si por error se compartiera la conexión de
    Repository (sin ese pragma), esta escritura pasaría silenciosamente."""
    same_path = tmp_path / "shared_fk.db"
    hist = HistoryRepository(db_path=same_path)

    with pytest.raises(sqlite3.IntegrityError):
        with hist.batch_write() as conn:
            conn.execute(
                "INSERT INTO feature_snapshots (event_id, event_snapshot_id, feature_set_version, "
                "data_cutoff_timestamp, computed_at, features_json, missing_features_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("fk_test", 99999, "v1", "2026-08-22T00:00:00+00:00", "2026-08-22T00:00:00+00:00", "{}", "[]"),
            )
