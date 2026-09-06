"""Tests API/integration de Phase 6 -- Tramo 5B (`src.api.advisory_router`
+ `src.api.advisory_service`). Ejercitan el stack real router -> service
-> dominio -> `PositionsRepository` -> SQLite sobre un archivo `tmp_path`
(nunca `data/engine.db`), mismo patrón que `test_positions_router.py`."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import src.api.main as main_module
from src.api.positions_router import get_positions_repository
from src.api.rate_limiter import RateLimiter, get_rate_limiter
from src.positions.positions_repository import PositionsRepository

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    repo = PositionsRepository(db_path=db_path)
    # UNA sola instancia de RateLimiter para todo el ciclo de vida del
    # cliente de test -- si el override construyera una instancia NUEVA
    # en cada request (p.ej. `lambda: RateLimiter(...)`), el estado de los
    # buckets nunca persistiría entre requests y el límite nunca se
    # activaría.
    limiter = RateLimiter(rate_per_second=2.0, burst=5, clock=FakeClock())
    main_module.app.dependency_overrides[get_positions_repository] = lambda: repo
    main_module.app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


def _event_identity_payload(**overrides) -> dict:
    base = dict(
        event_id="evt-1",
        sport="MLB",
        kalshi_ticker_side_a="KXMLBGAME-26AUG03WSHPHI-WSH",
        kalshi_ticker_side_b="KXMLBGAME-26AUG03WSHPHI-PHI",
        side_a="YES",
        side_b="NO",
        participant_a_canonical="WSH",
        participant_b_canonical="PHI",
        participant_a_display="Washington Nationals",
        participant_b_display="Philadelphia Phillies",
        scheduled_start_time=NOW.isoformat(),
        market_profile="KXMLBGAME",
    )
    base.update(overrides)
    return base


def _evaluate_payload(**overrides) -> dict:
    # `prices_timestamp` se compara contra el reloj REAL del proceso en
    # `advisory_service.evaluate_positions` (sin reloj inyectable a nivel
    # HTTP) -- el default debe ser "ahora" real, nunca el NOW histórico
    # fijo usado para `scheduled_start_time`.
    base = dict(
        event_identity=_event_identity_payload(),
        current_price_side_a_cents=55,
        current_price_side_b_cents=45,
        prices_timestamp=datetime.now(timezone.utc).isoformat(),
        position_targets=[],
    )
    base.update(overrides)
    return base


def _create_position(client, *, ticker: str, side: str, idempotency_key: str) -> dict:
    body = dict(idempotency_key=idempotency_key, kalshi_ticker=ticker, sport="MLB", side=side, source="MANUAL")
    response = client.post("/positions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _dump_all_rows(db_path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = ["positions", "orders", "order_fills", "position_events", "order_events", "position_plans"]
    dump = {}
    for t in tables:
        rows = conn.execute(f"SELECT * FROM {t}").fetchall()
        dump[t] = [dict(r) for r in rows]
    conn.close()
    return dump


# ---------------------------------------------------------------------
# Cero escrituras
# ---------------------------------------------------------------------


def test_evaluate_endpoint_writes_nothing_to_the_database(client, db_path):
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    before = _dump_all_rows(db_path)

    response = client.post(
        "/advisory/positions/evaluate", json=_evaluate_payload(), headers={"X-Advisory-Client-Id": "t1"}
    )
    assert response.status_code == 200, response.text

    after = _dump_all_rows(db_path)
    assert before == after


def test_exposure_endpoint_writes_nothing(client, db_path):
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    before = _dump_all_rows(db_path)

    params = {k: v for k, v in _event_identity_payload().items()}
    response = client.get("/positions/exposure", params=params)
    assert response.status_code == 200, response.text

    after = _dump_all_rows(db_path)
    assert before == after


# ---------------------------------------------------------------------
# Contenido funcional
# ---------------------------------------------------------------------


def test_evaluate_returns_one_advice_per_relevant_position(client):
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-PHI", side="NO", idempotency_key="k2")

    response = client.post("/advisory/positions/evaluate", json=_evaluate_payload(), headers={"X-Advisory-Client-Id": "t2"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["advices"]) == 2
    assert len(body["exposure"]["positions"]) == 2


def test_tp1_unavailable_without_target(client):
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    response = client.post("/advisory/positions/evaluate", json=_evaluate_payload(), headers={"X-Advisory-Client-Id": "t3"})
    body = response.json()
    assert body["advices"][0]["tp1"]["recovery_kind"] == "UNAVAILABLE"
    assert body["advices"][0]["tp1"]["contracts_to_sell"] is None


def test_no_enter_watch_pass_literal_anywhere_in_response(client):
    _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    response = client.post("/advisory/positions/evaluate", json=_evaluate_payload(), headers={"X-Advisory-Client-Id": "t4"})
    raw = response.text
    for forbidden in ("\"ENTER\"", "\"WATCH\"", "\"PASS\""):
        assert forbidden not in raw


# ---------------------------------------------------------------------
# Staleness fail-closed
# ---------------------------------------------------------------------


def test_stale_prices_timestamp_rejected(client):
    # El servicio compara `prices_timestamp` contra el reloj REAL del
    # proceso (`datetime.now(UTC)`) -- cualquier timestamp mucho más
    # viejo que los 15s de `max_allowed_staleness_seconds` debe rechazarse.
    import datetime as dt

    really_old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
    payload = _evaluate_payload(prices_timestamp=really_old)
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "t5"})
    assert response.status_code == 422, response.text


def test_naive_prices_timestamp_rejected(client):
    payload = _evaluate_payload(prices_timestamp="2026-08-15T12:00:00")
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "t6"})
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------
# Identidad fail-closed
# ---------------------------------------------------------------------


def test_event_identity_mismatch_with_real_position_is_rejected(client):
    """Tramo 1-4 no valida ticker<->sport (esa es precisamente la
    invariante NUEVA de Tramo 5B) -- se puede crear una Position con un
    ticker MLB pero sport=TENNIS declarado; la identidad de evento
    consistente (MLB) debe rechazar esa contradicción explícitamente."""
    ticker = "KXMLBGAME-26AUG03WSHPHI-WSH"
    body = dict(idempotency_key="k1", kalshi_ticker=ticker, sport="TENNIS", side="YES", source="MANUAL")
    response = client.post("/positions", json=body)
    assert response.status_code == 200, response.text

    import datetime as dt

    payload = _evaluate_payload(prices_timestamp=dt.datetime.now(dt.timezone.utc).isoformat())
    payload["event_identity"]["kalshi_ticker_side_a"] = ticker  # sport=MLB declarado, market_profile=KXMLBGAME
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "t7"})
    assert response.status_code == 409, response.text


def test_event_identity_bad_market_profile_rejected_at_validation(client):
    payload = _evaluate_payload()
    payload["event_identity"]["market_profile"] = "KXNOTREAL"
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "t8"})
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------


def test_rate_limit_returns_429_after_burst(client):
    payload = _evaluate_payload()
    responses = [
        client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "burst-test"})
        for _ in range(6)
    ]
    statuses = [r.status_code for r in responses]
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


def test_rate_limit_never_present_as_a_domain_field(client):
    payload = _evaluate_payload()
    for _ in range(5):
        client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "burst-test-2"})
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "burst-test-2"})
    assert response.status_code == 429
    body = response.json()
    assert "advices" not in body  # 429 nunca produce un cuerpo de dominio


# ---------------------------------------------------------------------
# Suite completa del router previo (Tramo 1-4) sigue intacta
# ---------------------------------------------------------------------


def test_positions_router_still_works_after_mounting_advisory(client):
    response = client.get("/positions", params={"status": "all"})
    assert response.status_code == 200


# ---------------------------------------------------------------------
# Identidad y rutas -- /positions/exposure nunca debe interpretarse como
# /positions/{position_id} (bug de orden de rutas ya corregido en main.py)
# ---------------------------------------------------------------------


def test_positions_exposure_route_never_shadowed_by_position_id_route(client):
    """`GET /positions/exposure` debe resolver al endpoint de exposición
    (requiere query params de identidad, nunca produce 404 "position_id
    'exposure' no existe" -- esa sería la señal inequívoca de que
    /positions/{position_id} la interceptó)."""
    params = _event_identity_payload()
    response = client.get("/positions/exposure", params=params)
    assert response.status_code == 200, response.text
    assert "exposure" not in (response.json().get("detail") or "")


def test_get_position_by_real_id_still_works_after_exposure_route_mounted(client):
    created = _create_position(client, ticker="KXMLBGAME-26AUG03WSHPHI-WSH", side="YES", idempotency_key="k1")
    response = client.get(f"/positions/{created['position_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["position_id"] == created["position_id"]


def test_get_position_with_nonexistent_id_returns_404_not_exposure_shape(client):
    response = client.get("/positions/does-not-exist")
    assert response.status_code == 404
    # Confirma que esta ruta es realmente /positions/{position_id} (404
    # honesto "no existe"), no la ruta de exposición mal enrutada.
    assert "does-not-exist" in response.json()["detail"]


# ---------------------------------------------------------------------
# Staleness -- vencimiento durante el cálculo (no solo al principio)
# ---------------------------------------------------------------------


def test_prices_timestamp_that_expires_during_computation_is_rejected(client, monkeypatch):
    """Corrección de auditoría: `advisory_service.evaluate_positions`
    re-verifica la staleness contra el reloj REAL al final del cálculo,
    no solo al principio -- se simula aquí adelantando el reloj real
    ENTRE la primera y la segunda verificación."""
    import datetime as dt

    import src.api.advisory_service as service_module

    real_utcnow = dt.datetime.now
    call_count = {"n": 0}

    def fake_now(tz=None):
        call_count["n"] += 1
        base = real_utcnow(tz)
        if call_count["n"] == 1:
            return base  # primera verificación: dentro de los 15s
        return base + dt.timedelta(seconds=30)  # segunda verificación: ya vencido

    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now(tz)

    monkeypatch.setattr(service_module, "datetime", FakeDatetime)

    payload = _evaluate_payload()
    response = client.post("/advisory/positions/evaluate", json=payload, headers={"X-Advisory-Client-Id": "t9"})
    assert response.status_code == 422, response.text
    assert "venció durante el cálculo" in response.json()["detail"]
