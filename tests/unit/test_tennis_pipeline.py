"""Tests unitarios del pipeline de tenis con SofaScore mockeado (sin red).

Cubre específicamente la regresión del bug donde `_try_enrich_sofascore`
fabricaba `tennis_variables.last_5` con un recuento de eventos en vez de
forma real (ver src/pipelines/tennis_pipeline.py).
"""
from __future__ import annotations

from src.connectors.base_client import FetchResult
from src.connectors.sofascore import SofascoreConnector
from src.models.schemas import NormalizedRecord, Sport, TennisVariables
from src.pipelines.tennis_pipeline import _try_enrich_sofascore


def _ok_result(data):
    from datetime import datetime, timezone

    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def test_sofascore_enrichment_never_fabricates_last_5(monkeypatch):
    """Regresión: antes del fix, un SofaScore exitoso con eventos rellenaba
    tennis_variables.last_5 = {"raw_event_count": N}, marcándolo como
    "lleno"/OK aunque no fuera forma real. Con el fix, un SofaScore exitoso
    NUNCA debe dejar last_5 poblado con datos inventados."""
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="e1",
        participant_a="Daniel Merida",
        participant_b="Kyrian Jacquet",
        tennis_variables=TennisVariables(),
    )

    sofascore = SofascoreConnector()
    monkeypatch.setattr(
        sofascore,
        "search",
        lambda query: _ok_result({"results": [{"type": "player", "entity": {"id": 123, "name": "Daniel Merida"}}]}),
    )
    monkeypatch.setattr(
        sofascore,
        "get_team_last_events",
        lambda team_id, page=0: _ok_result({"events": [{"id": 1}, {"id": 2}, {"id": 3}]}),
    )

    filled = _try_enrich_sofascore(sofascore, record, steps=[])

    assert record.tennis_variables.last_5 is None
    assert "tennis_variables.last_5" not in (filled or [])
    for field_name in TennisVariables.model_fields:
        assert getattr(record.tennis_variables, field_name) is None
