"""Tests del wiring Paso 0c: HistoryRepository conectado a los pipelines
reales de MLB y tenis (ver PLAN_PHASE2.md §11/§12, decisión arquitectónica
que autoriza reabrir exclusivamente 0c/0d, sin implementar el Paso 5).

Sin red: los conectores externos se monkeypatchean a nivel de método para
devolver fixtures ya capturadas de Fase 1. Estos tests verifican el WIRING
(pipeline -> HistoryRepository), no la lógica de matching/normalización,
que ya está cubierta por los tests de Fase 1 y no se modifica aquí.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.connectors.base_client import FetchResult
from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.mlb import MlbConnector
from src.pipelines.mlb_pipeline import run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _fail(error="fuente caída"):
    return FetchResult(ok=False, status_code=503, data=None, error=error, url="x", capture_ts=datetime.now(timezone.utc))


def _patch_kalshi_down(monkeypatch):
    """Kalshi caído -> kalshi_events=[] -> needs_review=True por el código
    ya existente del pipeline (sin tocar esa lógica). Nos da, sin fixtures
    adicionales, el escenario "falla de matching" pedido en las pruebas
    obligatorias del wiring."""
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _fail("kalshi down"),
    )


# ---------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------

def test_mlb_pipeline_persists_event_snapshot_when_history_repository_configured(
    monkeypatch, tmp_repository, tmp_history_repository, mlb_schedule_sample
):
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(mlb_schedule_sample)
    )
    _patch_kalshi_down(monkeypatch)

    before = datetime.now(timezone.utc)
    result = run_mlb_pipeline(
        "2026-07-21",
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        fetch_boxscore=False,
        fetch_pitcher_stats=False,
    )
    after = datetime.now(timezone.utc)

    assert len(result.records) == 1
    record = result.records[0]
    # Kalshi caído -> matching falla -> needs_review=True (comportamiento
    # PRE-EXISTENTE del pipeline, no modificado por este wiring).
    assert record.data_quality.needs_review is True

    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    snap = snapshots[0]

    # captured_at UTC-aware y real ("ahora" de la ejecución, nunca backfilled).
    captured_at = datetime.fromisoformat(snap["captured_at"])
    assert captured_at.tzinfo is not None
    assert before <= captured_at <= after

    # Falla de matching -> snapshot HONESTO: needs_review reflejado y
    # precios de mercado en None, nunca fabricados. No es un "snapshot
    # inválido": es un snapshot válido de un instante de baja calidad.
    assert snap["yes_bid"] is None and snap["yes_ask"] is None
    assert snap["no_bid"] is None and snap["no_ask"] is None
    dq = json.loads(snap["data_quality_json"])
    assert dq["needs_review"] is True

    # normalized_record_json es la fuente de verdad completa del instante.
    stored_record = json.loads(snap["normalized_record_json"])
    assert stored_record["event_id"] == record.event_id

    # normalized_records (Fase 1) no se altera por el wiring nuevo.
    stored = tmp_repository.get_normalized_records(sport="MLB")
    assert len(stored) == 1
    assert stored[0]["event_id"] == record.event_id


def test_mlb_pipeline_two_runs_preserve_two_snapshots_but_repository_stays_upsert(
    monkeypatch, tmp_repository, tmp_history_repository, mlb_schedule_sample
):
    """Recuperación point-in-time: dos ejecuciones reales del pipeline para
    el mismo evento producen DOS snapshots preservados (nunca se
    sobrescriben), mientras que `normalized_records` (Fase 1) sigue siendo
    una vista de estado actual (upsert, una sola fila) -- exactamente el
    contraste que motiva el histórico append-only (PLAN_PHASE2.md §11)."""
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(mlb_schedule_sample)
    )
    _patch_kalshi_down(monkeypatch)

    kwargs = dict(
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        fetch_boxscore=False,
        fetch_pitcher_stats=False,
    )
    run_mlb_pipeline("2026-07-21", **kwargs)
    result2 = run_mlb_pipeline("2026-07-21", **kwargs)

    event_id = result2.records[0].event_id
    snapshots = tmp_history_repository.get_snapshots_for_event(event_id)
    assert len(snapshots) == 2
    assert snapshots[0]["id"] != snapshots[1]["id"]

    stored = tmp_repository.get_normalized_records(sport="MLB")
    assert len(stored) == 1


def test_mlb_pipeline_without_history_repository_is_unaffected(
    monkeypatch, tmp_repository, mlb_schedule_sample
):
    """Compatibilidad hacia atrás: `history_repository` es opcional -- un
    llamador que no lo pasa (comportamiento de todo el código anterior al
    wiring) sigue funcionando exactamente igual, sin ningún efecto nuevo."""
    monkeypatch.setattr(
        MlbConnector, "get_schedule", lambda self, date, hydrate_probable_pitcher=True: _ok(mlb_schedule_sample)
    )
    _patch_kalshi_down(monkeypatch)

    result = run_mlb_pipeline(
        "2026-07-21", repository=tmp_repository, fetch_boxscore=False, fetch_pitcher_stats=False
    )
    assert len(result.records) == 1
    stored = tmp_repository.get_normalized_records(sport="MLB")
    assert len(stored) == 1


# ---------------------------------------------------------------------
# Tenis
# ---------------------------------------------------------------------

def test_tennis_pipeline_persists_event_snapshot_when_history_repository_configured(
    monkeypatch, tmp_repository, tmp_history_repository, espn_atp_scoreboard_sample
):
    monkeypatch.setattr(
        EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(espn_atp_scoreboard_sample)
    )
    _patch_kalshi_down(monkeypatch)

    before = datetime.now(timezone.utc)
    result = run_tennis_pipeline(
        "ATP",
        "20260721",
        repository=tmp_repository,
        history_repository=tmp_history_repository,
        enrich_sofascore=False,
    )
    after = datetime.now(timezone.utc)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.data_quality.needs_review is True

    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    snap = snapshots[0]

    captured_at = datetime.fromisoformat(snap["captured_at"])
    assert captured_at.tzinfo is not None
    assert before <= captured_at <= after

    assert snap["yes_bid"] is None and snap["yes_ask"] is None
    dq = json.loads(snap["data_quality_json"])
    assert dq["needs_review"] is True

    stored = tmp_repository.get_normalized_records(sport="TENNIS")
    assert len(stored) == 1
    assert stored[0]["event_id"] == record.event_id


def test_tennis_pipeline_without_history_repository_is_unaffected(
    monkeypatch, tmp_repository, espn_atp_scoreboard_sample
):
    monkeypatch.setattr(
        EspnTennisConnector, "get_scoreboard", lambda self, tour, date: _ok(espn_atp_scoreboard_sample)
    )
    _patch_kalshi_down(monkeypatch)

    result = run_tennis_pipeline(
        "ATP", "20260721", repository=tmp_repository, enrich_sofascore=False
    )
    assert len(result.records) == 1
    stored = tmp_repository.get_normalized_records(sport="TENNIS")
    assert len(stored) == 1
