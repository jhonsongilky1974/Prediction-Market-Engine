import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mlb_schedule_sample():
    return load_fixture("mlb_schedule_sample.json")


@pytest.fixture
def mlb_boxscore_sample():
    return load_fixture("mlb_boxscore_sample.json")


@pytest.fixture
def kalshi_mlb_market_sample():
    return load_fixture("kalshi_mlb_market_sample.json")


@pytest.fixture
def kalshi_atp_events_sample():
    return load_fixture("kalshi_atp_events_sample.json")


@pytest.fixture
def espn_atp_scoreboard_sample():
    return load_fixture("espn_atp_scoreboard_sample.json")


@pytest.fixture
def espn_atp_scoreboard_with_doubles_sample():
    return load_fixture("espn_atp_scoreboard_with_doubles_sample.json")


@pytest.fixture
def tmp_repository(tmp_path):
    from src.storage.repository import Repository

    return Repository(db_path=tmp_path / "test.db", raw_dir=tmp_path / "raw")
