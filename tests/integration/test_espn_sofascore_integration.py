"""Tests de integración reales contra ESPN Tennis y SofaScore. Requieren red.
SofaScore puede fallar limpiamente (403 por WAF/IP de datacenter) — eso
también es un resultado válido para este test: verificamos manejo limpio
de fallos, no forzamos que la fuente responda 200.
"""
from datetime import date, timedelta

import pytest

from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.sofascore import SofascoreConnector

pytestmark = pytest.mark.integration


def test_espn_scoreboard_real():
    espn = EspnTennisConnector()
    today = date.today()
    found_any = False
    for i in range(7):
        d = (today + timedelta(days=i)).strftime("%Y%m%d")
        result = espn.get_scoreboard("atp", d)
        assert result.ok is True or result.error is not None
        if result.ok and EspnTennisConnector.extract_matches(result.data):
            found_any = True
            break
    if not found_any:
        pytest.skip("ESPN no devolvió partidos ATP en la ventana de 7 días probada")


def test_sofascore_fails_clean_or_succeeds():
    """No asumimos disponibilidad (API no documentada). Solo verificamos que
    ante un fallo, el conector nunca lanza excepción y siempre reporta un
    FetchResult coherente."""
    sofascore = SofascoreConnector()
    result = sofascore.search("djokovic")
    assert result.ok in (True, False)
    if not result.ok:
        assert result.error is not None
    else:
        assert isinstance(result.data, dict)
