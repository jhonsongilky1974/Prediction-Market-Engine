"""Tests de regresión del histórico append-only (Fase 2, Paso 0).

Cubren exactamente los requisitos no negociables del Paso 0: nunca
UPDATE/UPSERT destructivo, timestamps UTC-aware, precios distintos por
snapshot preservados, resultado final separado y nunca mezclado con
snapshots pre-evento, e inicialización idempotente.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import json

import pytest
import sqlite3

from src.models.schemas import EventStatus, MarketData, NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository, _require_utc_aware


def _record(
    event_id="mlb_824409",
    yes_bid=0.40,
    yes_ask=0.42,
    market_id="M1",
    participant_a="Minnesota Twins",
    participant_b="Cleveland Guardians",
    **overrides,
):
    no_bid = round(1 - yes_ask, 4) if yes_ask is not None else None
    no_ask = round(1 - yes_bid, 4) if yes_bid is not None else None
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id=event_id,
        participant_a=participant_a,
        participant_b=participant_b,
        market_id=market_id,
        market=MarketData(
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            last_price=yes_ask,
            volume=100.0,
            open_interest=50.0,
        ),
        **overrides,
    )


def test_two_snapshots_same_event_id_different_times_both_preserved(tmp_path):
    """Requisito no negociable: dos snapshots del mismo event_id en
    momentos distintos se conservan AMBOS, no se sobrescriben."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)

    id1 = hist.save_event_snapshot(_record(yes_bid=0.40, yes_ask=0.42), source="run1", captured_at=t1)
    id2 = hist.save_event_snapshot(_record(yes_bid=0.55, yes_ask=0.57), source="run2", captured_at=t2)

    assert id1 != id2
    snapshots = hist.get_snapshots_for_event("mlb_824409")
    assert len(snapshots) == 2


def test_no_previous_snapshot_is_overwritten(tmp_path):
    """El primer snapshot conserva EXACTAMENTE sus propios valores después
    de insertar un segundo snapshot distinto para el mismo event_id."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)

    hist.save_event_snapshot(_record(yes_bid=0.40, yes_ask=0.42), source="run1", captured_at=t1)
    hist.save_event_snapshot(_record(yes_bid=0.55, yes_ask=0.57), source="run2", captured_at=t2)

    snapshots = hist.get_snapshots_for_event("mlb_824409")
    first, second = snapshots[0], snapshots[1]
    assert first["yes_bid"] == 0.40 and first["yes_ask"] == 0.42
    assert second["yes_bid"] == 0.55 and second["yes_ask"] == 0.57
    assert first["captured_at"] == t1.isoformat()
    assert second["captured_at"] == t2.isoformat()


def test_distinct_prices_per_snapshot_are_preserved_precisely(tmp_path):
    """Precios distintos por snapshot se preservan exactamente, sin
    promediarse ni colapsarse en un único valor 'actual'."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    prices = [(0.30, 0.32), (0.45, 0.47), (0.60, 0.62)]
    base_t = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    for i, (bid, ask) in enumerate(prices):
        hist.save_event_snapshot(
            _record(yes_bid=bid, yes_ask=ask),
            source="run",
            captured_at=base_t + timedelta(hours=i),
        )
    snapshots = hist.get_snapshots_for_event("mlb_824409")
    assert [(s["yes_bid"], s["yes_ask"]) for s in snapshots] == prices


def test_captured_at_must_be_utc_aware(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    naive = datetime(2026, 7, 21, 10, 0)  # sin tzinfo
    with pytest.raises(ValueError, match="tz-aware"):
        hist.save_event_snapshot(_record(), source="run", captured_at=naive)


def test_captured_at_defaults_to_utc_aware_now(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(_record(), source="run")
    snap = hist.get_snapshots_for_event("mlb_824409")[0]
    parsed = datetime.fromisoformat(snap["captured_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_require_utc_aware_helper_rejects_naive_and_accepts_aware():
    with pytest.raises(ValueError):
        _require_utc_aware(datetime(2026, 7, 21), "x")
    _require_utc_aware(datetime(2026, 7, 21, tzinfo=timezone.utc), "x")  # no debe lanzar


def test_snapshot_conserves_full_normalized_record_and_market_fields(tmp_path):
    """Conserva event_id, event_start_time, source timestamps y el
    NormalizedRecord completo (o referencia reproducible), además de
    YES_BID/YES_ASK/NO_BID/NO_ASK/LAST_PRICE/volume/open_interest/
    data_quality/source_timestamps -- exactamente lo pedido."""
    import json

    start = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    record = _record(start_time=start)
    record.data_quality.source_timestamps = {"mlb": start - timedelta(minutes=5)}
    record.data_quality.needs_review = False

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(record, source="run", captured_at=start + timedelta(minutes=1))
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    assert snap["event_id"] == "mlb_824409"
    assert snap["event_start_time"] == start.isoformat()
    assert snap["yes_bid"] == 0.40 and snap["yes_ask"] == 0.42
    assert snap["no_bid"] == 0.58 and snap["no_ask"] == 0.60
    assert snap["last_price"] == 0.42
    assert snap["volume"] == 100.0
    assert snap["open_interest"] == 50.0

    source_ts = json.loads(snap["source_timestamps_json"])
    assert source_ts["mlb"] == (start - timedelta(minutes=5)).isoformat()

    dq = json.loads(snap["data_quality_json"])
    assert dq["needs_review"] is False

    full_record = json.loads(snap["normalized_record_json"])
    assert full_record["event_id"] == "mlb_824409"
    assert full_record["participant_a"] == "Minnesota Twins"
    assert full_record["market"]["yes_ask"] == 0.42


def test_event_result_stored_separately_and_not_mixed_into_snapshots(tmp_path):
    """El resultado final vive en su propia tabla; nunca se escribe dentro
    de una fila de event_snapshots ni la modifica retroactivamente."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    hist.save_event_snapshot(_record(yes_bid=0.40, yes_ask=0.42), source="run", captured_at=t1)

    result_time = datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc)
    hist.save_event_result(
        event_id="mlb_824409",
        sport="MLB",
        result="PARTICIPANT_A_WON",
        source="mlb_boxscore_final",
        settled_at=result_time,
        recorded_at=result_time,
    )

    # el snapshot pre-evento sigue exactamente igual, sin ningún campo de resultado
    snap = hist.get_snapshots_for_event("mlb_824409")[0]
    assert "result" not in snap
    assert snap["yes_bid"] == 0.40

    results = hist.get_results_for_event("mlb_824409")
    assert len(results) == 1
    assert results[0]["result"] == "PARTICIPANT_A_WON"
    assert results[0]["recorded_at"] == result_time.isoformat()


def test_event_result_requires_utc_aware_timestamps(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    with pytest.raises(ValueError, match="tz-aware"):
        hist.save_event_result(
            event_id="mlb_824409",
            sport="MLB",
            result="PARTICIPANT_A_WON",
            source="x",
            recorded_at=datetime(2026, 7, 22, 2, 0),  # naive
        )


def test_feature_snapshot_links_to_event_snapshot_and_is_append_only(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    snap_id = hist.save_event_snapshot(_record(), source="run", captured_at=t1)

    hist.save_feature_snapshot(
        event_id="mlb_824409",
        event_snapshot_id=snap_id,
        feature_set_version="v0",
        data_cutoff_timestamp=t1,
        features={"pitcher_era_season": 3.2},
        missing_features=["bullpen_era_recent"],
        computed_at=t1,
    )
    hist.save_feature_snapshot(
        event_id="mlb_824409",
        event_snapshot_id=snap_id,
        feature_set_version="v0",
        data_cutoff_timestamp=t1,
        features={"pitcher_era_season": 3.1},  # recalculado más tarde, valor distinto
        missing_features=[],
        computed_at=t1 + timedelta(hours=1),
    )

    feature_snaps = hist.get_feature_snapshots_for_event("mlb_824409")
    assert len(feature_snaps) == 2  # ambos cálculos conservados, ninguno sobrescrito
    assert feature_snaps[0]["event_snapshot_id"] == snap_id


def test_deliberately_no_content_based_deduplication(tmp_path):
    """Diseño intencional: dos llamadas con datos IDÉNTICOS producen DOS
    filas. El histórico es un log de observaciones, no un store de estado
    -- si el llamador no quiere una nueva observación, no debe invocar
    save_event_snapshot, en vez de depender de una deduplicación implícita
    que este módulo NO implementa (ver PLAN_PHASE2.md §11)."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    record = _record(yes_bid=0.40, yes_ask=0.42)

    hist.save_event_snapshot(record, source="run", captured_at=t1)
    hist.save_event_snapshot(record, source="run", captured_at=t1)  # mismo contenido, mismo instante

    snapshots = hist.get_snapshots_for_event("mlb_824409")
    assert len(snapshots) == 2


def test_init_is_idempotent_and_preserves_existing_data(tmp_path):
    """Reiniciar el proceso (nueva instancia de HistoryRepository sobre el
    mismo archivo) no falla y no borra ni duplica el schema -- CREATE
    TABLE IF NOT EXISTS es idempotente por diseño."""
    db_path = tmp_path / "hist.db"

    hist1 = HistoryRepository(db_path=db_path)
    t1 = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    hist1.save_event_snapshot(_record(yes_bid=0.40, yes_ask=0.42), source="run1", captured_at=t1)

    # "reinicio del proceso": nueva instancia, mismo archivo
    hist2 = HistoryRepository(db_path=db_path)
    snapshots_after_reinit = hist2.get_snapshots_for_event("mlb_824409")
    assert len(snapshots_after_reinit) == 1  # el dato previo sigue ahí, no se duplicó ni se perdió

    t2 = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)
    hist2.save_event_snapshot(_record(yes_bid=0.55, yes_ask=0.57), source="run2", captured_at=t2)
    assert len(hist2.get_snapshots_for_event("mlb_824409")) == 2

    # una TERCERA instancia (otro "reinicio") sigue viendo ambos snapshots
    hist3 = HistoryRepository(db_path=db_path)
    assert len(hist3.get_snapshots_for_event("mlb_824409")) == 2


def test_history_tables_coexist_with_phase1_repository_without_interference(tmp_path):
    """El histórico vive en el mismo archivo SQLite que Repository (Fase 1)
    sin alterar sus tablas ni su comportamiento."""
    from src.storage.repository import Repository

    db_path = tmp_path / "shared.db"
    repo = Repository(db_path=db_path, raw_dir=tmp_path / "raw")
    hist = HistoryRepository(db_path=db_path)

    record = _record()
    repo.save_normalized_record(record)  # Fase 1: upsert por event_id
    hist.save_event_snapshot(record, source="run", captured_at=datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc))
    hist.save_event_snapshot(
        _record(yes_bid=0.55, yes_ask=0.57),
        source="run",
        captured_at=datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc),
    )

    # Fase 1 sigue teniendo exactamente 1 fila (su semántica de estado actual, sin cambios)
    assert len(repo.get_normalized_records("MLB")) == 1
    # el histórico conserva las 2 observaciones, independientemente de Fase 1
    assert len(hist.get_snapshots_for_event("mlb_824409")) == 2


# =========================================================================
# Casos adversariales (auditoría del Paso 0)
# =========================================================================

def test_needs_review_snapshot_preserves_null_market_not_zero(tmp_path):
    """Un registro NEEDS_REVIEW (Fase 1) debe conservarse en el snapshot
    con precios en None, nunca en 0 -- 0 y "sin dato" no son lo mismo."""
    record = _record(yes_bid=None, yes_ask=None, market_id=None)
    record.data_quality.needs_review = True
    record.data_quality.match_confidence = 0.5

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(record, source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc))
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    assert snap["yes_bid"] is None
    assert snap["yes_ask"] is None
    assert snap["market_id"] is None
    dq = json.loads(snap["data_quality_json"])
    assert dq["needs_review"] is True


def test_legitimate_zero_values_are_not_coerced_to_none(tmp_path):
    """0.0 es un valor real (ej. liquidity/open_interest en cero) y debe
    preservarse como 0.0, no confundirse con MISSING/None."""
    record = _record(yes_bid=0.0, yes_ask=0.01)
    record.market.liquidity = 0.0
    record.market.open_interest = 0.0
    record.market.volume = 0.0

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(record, source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc))
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    assert snap["yes_bid"] == 0.0
    assert snap["yes_bid"] is not None  # explícito: 0.0 no es None en Python/SQLite
    assert snap["liquidity"] == 0.0
    assert snap["open_interest"] == 0.0
    assert snap["volume"] == 0.0


def test_unicode_characters_survive_json_round_trip(tmp_path):
    """Nombres con acentos/caracteres especiales (frecuentes en tenis, ej.
    'Łukasz Kubot', 'Świątek') no deben corromperse en el JSON persistido."""
    record = _record(participant_a="Łukasz Kubot", participant_b="Iga Świątek")
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(record, source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc))
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    full_record = json.loads(snap["normalized_record_json"])
    assert full_record["participant_a"] == "Łukasz Kubot"
    assert full_record["participant_b"] == "Iga Świątek"


def test_normalized_record_round_trip_reconstructs_without_loss(tmp_path):
    """NormalizedRecord original -> persistencia JSON -> lectura ->
    reconstrucción: ningún valor material se pierde ni cambia
    silenciosamente."""
    original = _record(yes_bid=0.401234, yes_ask=0.42, start_time=datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc))
    original.data_quality.match_confidence = 0.8734
    original.data_quality.missing_fields = ["mlb.boxscore", "mlb.injuries"]
    original.tennis_variables = None  # MLB: debe permanecer None, no fabricado

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(original, source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc))
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    reconstructed = NormalizedRecord.model_validate_json(snap["normalized_record_json"])

    assert reconstructed == original
    assert reconstructed.market.yes_bid == 0.401234
    assert reconstructed.data_quality.match_confidence == 0.8734
    assert reconstructed.data_quality.missing_fields == ["mlb.boxscore", "mlb.injuries"]
    assert reconstructed.start_time == original.start_time
    assert reconstructed.tennis_variables is None


def test_feature_snapshot_rejects_nonexistent_event_snapshot_id(tmp_path):
    """Regresión del hallazgo de auditoría: una FK inexistente debe ser
    rechazada por SQLite (requiere PRAGMA foreign_keys=ON activo)."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        hist.save_feature_snapshot(
            event_id="fantasma",
            event_snapshot_id=999999,  # no existe ningún event_snapshots.id=999999
            feature_set_version="v0",
            data_cutoff_timestamp=datetime(2026, 7, 22, tzinfo=timezone.utc),
            features={"x": 1},
        )


def test_feature_snapshot_accepts_valid_event_snapshot_id(tmp_path):
    """Contraprueba: una FK válida sí debe insertarse sin error."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    snap_id = hist.save_event_snapshot(
        _record(), source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
    )
    row_id = hist.save_feature_snapshot(
        event_id="mlb_824409",
        event_snapshot_id=snap_id,
        feature_set_version="v0",
        data_cutoff_timestamp=datetime(2026, 7, 22, tzinfo=timezone.utc),
        features={"pitcher_era_season": 3.2},
    )
    assert row_id is not None
    feature_snaps = hist.get_feature_snapshots_for_event("mlb_824409")
    assert feature_snaps[0]["event_snapshot_id"] == snap_id


def test_raw_sql_update_on_event_snapshots_is_rejected_by_trigger(tmp_path):
    """Regresión del hallazgo de auditoría: incluso SQL crudo fuera de la
    API pública de HistoryRepository no puede mutar un snapshot existente
    -- el append-only se aplica a nivel de motor, no solo por convención."""
    db_path = tmp_path / "hist.db"
    hist = HistoryRepository(db_path=db_path)
    snap_id = hist.save_event_snapshot(
        _record(yes_bid=0.40), source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE event_snapshots SET yes_bid = 0.99 WHERE id = ?", (snap_id,))
            conn.commit()
    finally:
        conn.close()

    # el valor original sigue intacto
    snap = hist.get_snapshots_for_event("mlb_824409")[0]
    assert snap["yes_bid"] == 0.40


def test_raw_sql_delete_on_event_snapshots_is_rejected_by_trigger(tmp_path):
    db_path = tmp_path / "hist.db"
    hist = HistoryRepository(db_path=db_path)
    snap_id = hist.save_event_snapshot(
        _record(), source="run", captured_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM event_snapshots WHERE id = ?", (snap_id,))
            conn.commit()
    finally:
        conn.close()

    assert len(hist.get_snapshots_for_event("mlb_824409")) == 1


def test_raw_sql_update_on_event_results_is_rejected_by_trigger(tmp_path):
    db_path = tmp_path / "hist.db"
    hist = HistoryRepository(db_path=db_path)
    t = datetime(2026, 7, 22, tzinfo=timezone.utc)
    hist.save_event_result(event_id="mlb_824409", sport="MLB", result="PARTICIPANT_A_WON", source="x", recorded_at=t)

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE event_results SET result = 'PARTICIPANT_B_WON'")
            conn.commit()
    finally:
        conn.close()

    assert hist.get_results_for_event("mlb_824409")[0]["result"] == "PARTICIPANT_A_WON"


def test_registering_same_result_twice_is_allowed_and_append_only_not_silently_deduped(tmp_path):
    """Registrar el mismo resultado dos veces (ej. pipeline re-ejecutado)
    produce DOS filas -- mismo principio de log append-only que los
    snapshots. No se deduplica implícitamente; si el llamador no quiere
    una nueva fila, no debe invocar save_event_result de nuevo."""
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    t = datetime(2026, 7, 22, tzinfo=timezone.utc)
    hist.save_event_result(event_id="mlb_824409", sport="MLB", result="PARTICIPANT_A_WON", source="x", recorded_at=t)
    hist.save_event_result(event_id="mlb_824409", sport="MLB", result="PARTICIPANT_A_WON", source="x", recorded_at=t)

    results = hist.get_results_for_event("mlb_824409")
    assert len(results) == 2


def test_event_start_time_and_captured_at_are_never_confused(tmp_path):
    """captured_at (cuándo se tomó la foto) y event_start_time (cuándo
    empieza el evento) son columnas independientes con semántica distinta
    -- deben poder diferir libremente sin que el código las confunda."""
    start = datetime(2026, 7, 25, 22, 40, tzinfo=timezone.utc)  # el evento es en el futuro
    captured = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)  # la captura es hoy
    record = _record(start_time=start)

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    hist.save_event_snapshot(record, source="run", captured_at=captured)
    snap = hist.get_snapshots_for_event("mlb_824409")[0]

    assert snap["captured_at"] == captured.isoformat()
    assert snap["event_start_time"] == start.isoformat()
    assert snap["captured_at"] != snap["event_start_time"]
