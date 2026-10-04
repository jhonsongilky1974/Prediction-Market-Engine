"""Reglas puras de elegibilidad pre-evento (CONTINUITY.md §0.38)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.preevent_snapshots import (
    MIN_SNAPSHOT_LEAD_MINUTES,
    PreeventViolation as V,
    preevent_violations,
    select_one_snapshot_per_event,
)
from src.models.schemas import EventStatus

START = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)


def test_policy_constants_are_the_authorized_values():
    assert MIN_SNAPSHOT_LEAD_MINUTES == 60


def test_fully_eligible_snapshot_has_no_violations():
    assert preevent_violations(
        event_start_time=START, status=EventStatus.SCHEDULED,
        data_cutoff_timestamp=START - timedelta(hours=2), computed_at=START - timedelta(hours=2),
        captured_at=START - timedelta(hours=2), min_lead_minutes=60,
    ) == []


def test_missing_start_time_is_a_violation_and_short_circuits():
    assert preevent_violations(event_start_time=None, status="SCHEDULED") == [V.MISSING_START_TIME]


@pytest.mark.parametrize("status", [EventStatus.LIVE, EventStatus.FINAL, EventStatus.POSTPONED, EventStatus.UNKNOWN, None, "FINAL"])
def test_non_scheduled_status_is_a_violation(status):
    assert V.STATUS_NOT_SCHEDULED in preevent_violations(event_start_time=START, status=status)


def test_accepts_status_as_plain_string_or_enum():
    assert preevent_violations(event_start_time=START, status="SCHEDULED") == []
    assert preevent_violations(event_start_time=START, status=EventStatus.SCHEDULED) == []


@pytest.mark.parametrize("delta_minutes", [0, 1, 600])  # igual o posterior al inicio
def test_timestamps_at_or_after_start_are_violations(delta_minutes):
    at = START + timedelta(minutes=delta_minutes)
    got = preevent_violations(
        event_start_time=START, status="SCHEDULED", data_cutoff_timestamp=at, computed_at=at, captured_at=at,
    )
    assert set(got) == {V.CUTOFF_NOT_BEFORE_START, V.COMPUTED_AT_NOT_BEFORE_START, V.CAPTURED_AT_NOT_BEFORE_START}


def test_lead_boundary_is_exactly_60_minutes():
    def run(lead):
        return preevent_violations(
            event_start_time=START, status="SCHEDULED", computed_at=START - timedelta(minutes=lead), min_lead_minutes=60,
        )

    assert V.INSUFFICIENT_LEAD in run(59)
    assert run(60) == []
    assert run(61) == []


def test_lead_is_not_evaluated_without_min_lead_minutes_live_inference():
    assert preevent_violations(event_start_time=START, status="SCHEDULED", computed_at=START - timedelta(minutes=1)) == []


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        preevent_violations(event_start_time=datetime(2026, 8, 1, 15, 0), status="SCHEDULED")
    with pytest.raises(ValueError):
        preevent_violations(event_start_time=START, status="SCHEDULED", computed_at=datetime(2026, 8, 1, 10, 0))


def test_select_one_snapshot_per_event_picks_latest_and_ties_break_by_id():
    rows = [
        ("e1", START - timedelta(hours=5), 1),
        ("e1", START - timedelta(hours=2), 2),
        ("e1", START - timedelta(hours=3), 3),
        ("e2", START - timedelta(hours=2), 4),
        ("e2", START - timedelta(hours=2), 9),  # empate -> id mayor
    ]
    chosen = select_one_snapshot_per_event(
        rows, event_id_of=lambda r: r[0], computed_at_of=lambda r: r[1], tie_break_of=lambda r: r[2]
    )
    assert {k: v[2] for k, v in chosen.items()} == {"e1": 2, "e2": 9}
    # independiente del orden de entrada
    chosen_rev = select_one_snapshot_per_event(
        list(reversed(rows)), event_id_of=lambda r: r[0], computed_at_of=lambda r: r[1], tie_break_of=lambda r: r[2]
    )
    assert chosen == chosen_rev
