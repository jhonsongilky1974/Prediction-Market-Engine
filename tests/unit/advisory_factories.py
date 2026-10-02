"""Factories de ejemplo mínimo válido para Phase 6 -- Tramo 5B (Position
Management Advisory). Mismo patrón `_kwargs(**overrides)` que
`tests/unit/positions_factories.py`. No es un módulo de tests en sí."""
from __future__ import annotations

from datetime import datetime, timezone

from src.advisory.event_identity import EventIdentity
from src.models.schemas import Sport
from src.signals.signal_schema import Side

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def make_event_identity(**overrides) -> EventIdentity:
    base = dict(
        event_id="evt-1",
        sport=Sport.MLB,
        kalshi_ticker_side_a="KXMLBGAME-26AUG03WSHPHI-WSH",
        kalshi_ticker_side_b="KXMLBGAME-26AUG03WSHPHI-PHI",
        side_a=Side.YES,
        side_b=Side.NO,
        participant_a_canonical="WSH",
        participant_b_canonical="PHI",
        participant_a_display="Washington Nationals",
        participant_b_display="Philadelphia Phillies",
        scheduled_start_time=NOW,
        market_profile="KXMLBGAME",
    )
    base.update(overrides)
    return EventIdentity(**base)
