from src.models.schemas import NormalizedRecord, Sport


def test_save_and_read_raw_capture(tmp_repository):
    path = tmp_repository.save_raw_capture("mlb", "schedule_2026-07-21", {"a": 1}, True)
    import json
    from pathlib import Path

    saved = json.loads(Path(path).read_text())
    assert saved["source"] == "mlb"
    assert saved["ok"] is True
    assert saved["payload"] == {"a": 1}


def test_raw_capture_never_overwrites(tmp_repository):
    p1 = tmp_repository.save_raw_capture("mlb", "schedule", {"n": 1}, True)
    p2 = tmp_repository.save_raw_capture("mlb", "schedule", {"n": 2}, True)
    assert p1 != p2


def test_raw_capture_never_overwrites_on_identical_microsecond_timestamp(tmp_repository):
    """Regresión: el nombre de archivo se derivaba solo del timestamp
    (resolución de microsegundo) + endpoint. Dos capturas con el MISMO
    `capture_ts` explícito (colisión real, aunque improbable con
    datetime.now()) se sobrescribían en silencio -- contradice la garantía
    documentada de "nunca sobrescribe"."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    same_ts = datetime(2026, 7, 21, 12, 0, 0, 123456, tzinfo=timezone.utc)
    p1 = tmp_repository.save_raw_capture("mlb", "schedule", {"n": 1}, True, capture_ts=same_ts)
    p2 = tmp_repository.save_raw_capture("mlb", "schedule", {"n": 2}, True, capture_ts=same_ts)
    p3 = tmp_repository.save_raw_capture("mlb", "schedule", {"n": 3}, True, capture_ts=same_ts)

    assert len({p1, p2, p3}) == 3
    assert json.loads(Path(p1).read_text())["payload"] == {"n": 1}
    assert json.loads(Path(p2).read_text())["payload"] == {"n": 2}
    assert json.loads(Path(p3).read_text())["payload"] == {"n": 3}


def test_save_and_read_normalized_record(tmp_repository):
    record = NormalizedRecord(sport=Sport.MLB, event_id="e1", participant_a="A", participant_b="B")
    tmp_repository.save_normalized_record(record)
    records = tmp_repository.get_normalized_records("MLB")
    assert len(records) == 1
    assert records[0]["participant_a"] == "A"


def test_save_normalized_record_upsert(tmp_repository):
    r1 = NormalizedRecord(sport=Sport.MLB, event_id="e1", participant_a="A")
    tmp_repository.save_normalized_record(r1)
    r2 = NormalizedRecord(sport=Sport.MLB, event_id="e1", participant_a="A-updated")
    tmp_repository.save_normalized_record(r2)
    records = tmp_repository.get_normalized_records("MLB")
    assert len(records) == 1
    assert records[0]["participant_a"] == "A-updated"
