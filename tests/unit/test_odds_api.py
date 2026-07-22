import os

import pytest

from src.connectors.odds_api import OddsApiConnector


def test_not_configured_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    connector = OddsApiConnector()
    assert connector.is_configured() is False


def test_get_odds_returns_not_configured_without_network_call(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no debería llamar a la red si no hay API key")

    connector = OddsApiConnector()
    monkeypatch.setattr(connector._client, "get_json", fail_if_called)

    result = connector.get_odds("baseball_mlb")
    assert result.ok is False
    assert result.error == "NOT_CONFIGURED"


def test_configured_when_env_var_present(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "fake-key-for-test")
    connector = OddsApiConnector()
    assert connector.is_configured() is True
