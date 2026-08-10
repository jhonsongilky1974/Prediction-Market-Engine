"""Test end-to-end REAL (sin mocks) del endpoint `/analyze` (Fase 5). Ver
`HTTP_SERVICE_SPEC.md` §4. Mismo patrón que `test_e2e_real.py`: APIs
reales, `tmp_path` exclusivamente, nunca `data/engine.db`.

No asume que el matching heurístico (Fase 1, sin modificar) vaya a
confirmar un match confidente para el ticker real elegido en el momento
de la corrida -- eso depende de cuánto concuerden las fuentes en vivo
(ver hallazgo real documentado en CONTINUITY.md: discrepancias de
horario entre MLB Stats API y Kalshi pueden exceder la tolerancia). La
aserción real de este test es que `resolve_ticker`/`analyze_ticker`
nunca lanzan una excepción NO controlada -- siempre `ResolvedEvent`
real o `ResolverError` honesto.
"""
from __future__ import annotations

import pytest

from src.api.analysis_service import analyze_ticker
from src.api.event_resolver import ResolverError
from src.connectors.kalshi import KalshiConnector
from src.storage.history_repository import HistoryRepository
from src.storage.repository import Repository

pytestmark = pytest.mark.integration


def _find_real_open_mlb_ticker():
    kalshi = KalshiConnector()
    result = kalshi.get_all_events_for_sport("MLB", status="open")
    if not result.ok:
        return None
    events = KalshiConnector.extract_events(result.data)
    for event in events:
        for market in event.get("markets") or []:
            ticker = market.get("ticker")
            if ticker:
                return ticker
    return None


def test_analyze_ticker_against_real_kalshi_and_mlb_apis(tmp_path):
    ticker = _find_real_open_mlb_ticker()
    if ticker is None:
        pytest.skip("no hay mercados MLB abiertos en Kalshi ahora mismo -- no es un fallo del código")

    repo = Repository(db_path=tmp_path / "hist.db")
    hist_repo = HistoryRepository(db_path=tmp_path / "hist.db")

    try:
        response = analyze_ticker(ticker, repository=repo, history_repository=hist_repo)
    except ResolverError as exc:
        # Honesto: el matcher (Fase 1, sin modificar) puede no confirmar
        # el match hoy -- 404/400 son resultados válidos, nunca un 5xx
        # inesperado ni un crash. 502 también es válido desde el fix de
        # 2026-08-10: una fuente upstream caída (ver event_resolver.py)
        # se reporta como caída de fuente, no como 404 de matching --
        # sigue siendo un ResolverError honesto y controlado, no un crash.
        assert exc.status_code in (400, 404, 502)
        return

    assert response.ticker == ticker
    assert response.sport == "MLB"
    assert response.recommendation in ("ENTER", "WATCH", "PASS")
    assert response.freshness.data_freshness_seconds >= 0
    assert 0.0 <= (response.p_market or 0.0) <= 1.0
