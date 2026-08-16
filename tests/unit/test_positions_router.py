"""Tests API/integration de Phase 6 -- Tramo 2 (`src.api.positions_router`
+ `src.api.positions_service`). Ejercitan el stack real router -> service
-> `PositionsRepository` -> SQLite sobre un archivo `tmp_path` (nunca
`data/engine.db`) vía `app.dependency_overrides`. No están marcados
`integration` (ese marcador es exclusivamente para tests que golpean
APIs externas reales por red -- ver `pyproject.toml`); aquí no hay red
ni Robinhood involucrados en absoluto."""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.api.main as main_module
from src.api.positions_router import get_positions_repository
from src.positions.positions_repository import PositionsRepository


@pytest.fixture
def client(tmp_path):
    repo = PositionsRepository(db_path=tmp_path / "test.db")
    main_module.app.dependency_overrides[get_positions_repository] = lambda: repo
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


def _create_position(client, **overrides) -> dict:
    body = dict(kalshi_ticker="KXMLBGAME-1", sport="MLB", side="YES", source="MANUAL")
    body.update(overrides)
    response = client.post("/positions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _create_order(client, position_id, **overrides) -> dict:
    body = dict(
        order_id=overrides.pop("order_id", "ord-1"),
        intent_id=overrides.pop("intent_id", "intent-1"),
        action="BUY",
        requested_qty=19,
        planned_target_price_cents=50,
    )
    body.update(overrides)
    response = client.post(f"/positions/{position_id}/orders", json=body)
    return response


def _register_fill(client, position_id, **overrides) -> dict:
    body = dict(
        fill_id=overrides.pop("fill_id", "fill-1"),
        order_id=overrides.pop("order_id", "ord-1"),
        action="BUY",
        qty=19,
        actual_fill_price_cents=50,
        fee={"status": "ESTIMATED", "cents": "0"},
        filled_at="2026-08-15T12:00:00Z",
        expected_order_version=1,
    )
    body.update(overrides)
    response = client.post(f"/positions/{position_id}/fills", json=body)
    return response


# ---------------------------------------------------------------------
# 1/2 -- crear Position MANUAL / vinculada a model_opportunity_id
# ---------------------------------------------------------------------


def test_1_create_position_manual(client):
    body = _create_position(client)
    assert body["source"] == "MANUAL"
    assert body["linked_opportunity_id"] is None
    assert body["status"] == "OPEN"
    assert body["open_contracts"] == 0
    assert body["total_capital_at_risk_cents"] == "0"
    assert body["version"] == 1
    assert body["position_id"]


def test_2_create_position_model_opportunity(client):
    body = _create_position(client, source="MODEL_OPPORTUNITY", linked_opportunity_id="opp-1")
    assert body["source"] == "MODEL_OPPORTUNITY"
    assert body["linked_opportunity_id"] == "opp-1"


def test_create_position_model_opportunity_missing_link_returns_400(client):
    response = client.post(
        "/positions", json={"kalshi_ticker": "K-1", "sport": "MLB", "side": "YES", "source": "MODEL_OPPORTUNITY"}
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------
# 3/4 -- GET Position / listar posiciones
# ---------------------------------------------------------------------


def test_3_get_position(client):
    created = _create_position(client)
    response = client.get(f"/positions/{created['position_id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_4_list_positions_open_and_all(client):
    p1 = _create_position(client, kalshi_ticker="K-1")
    p2 = _create_position(client, kalshi_ticker="K-2")

    response = client.get("/positions")
    assert response.status_code == 200
    ids = {p["position_id"] for p in response.json()["positions"]}
    assert ids == {p1["position_id"], p2["position_id"]}

    response = client.get("/positions?status=all")
    assert response.status_code == 200
    assert {p["position_id"] for p in response.json()["positions"]} == ids

    response = client.get("/positions?status=bogus")
    assert response.status_code == 422  # Query(pattern=...) rechaza valores fuera de open/all


# ---------------------------------------------------------------------
# 5/6/7 -- registrar fills BUY/BUY-otro-precio/SELL-parcial
# ---------------------------------------------------------------------


def test_5_register_buy_fill(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    order_response = _create_order(client, pos_id)
    assert order_response.status_code == 200

    fill_response = _register_fill(client, pos_id)
    assert fill_response.status_code == 200, fill_response.text
    body = fill_response.json()
    assert body["order"]["status"] == "FILLED"
    assert body["position"]["open_contracts"] == 19
    assert body["position"]["total_capital_at_risk_cents"] == "950"
    assert body["position"]["total_buy_qty"] == 19
    assert body["position"]["total_sell_qty"] == 0


def test_6_register_second_buy_fill_at_different_price(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, order_id="ord-1", intent_id="i-1", requested_qty=10, planned_target_price_cents=44)
    r1 = _register_fill(
        client, pos_id, fill_id="f1", order_id="ord-1", qty=10, actual_fill_price_cents=44, expected_order_version=1
    )
    assert r1.status_code == 200

    _create_order(client, pos_id, order_id="ord-2", intent_id="i-2", requested_qty=10, planned_target_price_cents=25)
    r2 = _register_fill(
        client, pos_id, fill_id="f2", order_id="ord-2", qty=10, actual_fill_price_cents=25, expected_order_version=1
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    # 10*44 + 10*25 = 690, suma exacta -- no promedio*qty (Caso B, Tramo 1)
    assert body["position"]["total_capital_at_risk_cents"] == "690"
    assert body["position"]["open_contracts"] == 20


def test_7_register_sell_partial_fill(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id)
    _register_fill(client, pos_id)  # 19 BUY @ 50c

    sell_order = _create_order(
        client, pos_id, order_id="ord-sell", intent_id="i-sell", action="SELL", requested_qty=15,
        planned_target_price_cents=63,
    )
    assert sell_order.status_code == 200, sell_order.text

    partial = _register_fill(
        client, pos_id, fill_id="s1", order_id="ord-sell", action="SELL", qty=9,
        actual_fill_price_cents=63, expected_order_version=1,
    )
    assert partial.status_code == 200, partial.text
    body = partial.json()
    assert body["order"]["status"] == "PARTIALLY_FILLED"
    assert body["order"]["confirmed_filled_qty"] == 9
    assert body["position"]["open_contracts"] == 19 - 9
    assert body["position"]["status"] == "RECOVERY_IN_PROGRESS"


# ---------------------------------------------------------------------
# 8/9 -- idempotencia de fills
# ---------------------------------------------------------------------


def test_8_repeat_exact_fill_does_not_duplicate(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id)
    first = _register_fill(client, pos_id)
    assert first.status_code == 200

    retry = _register_fill(client, pos_id)  # mismo payload exacto
    assert retry.status_code == 200
    assert retry.json() == first.json()

    orders = client.get(f"/positions/{pos_id}/orders").json()["orders"]
    assert len(orders) == 1  # ninguna duplicación de efecto


def test_9_reuse_fill_key_with_incompatible_payload_returns_409(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id)
    first = _register_fill(client, pos_id)
    assert first.status_code == 200

    conflict = _register_fill(client, pos_id, qty=1)  # mismo fill_id, distinto qty
    assert conflict.status_code == 409


# ---------------------------------------------------------------------
# 10 -- SELL mayor que open_contracts -> rechazo
# ---------------------------------------------------------------------


def test_10_prepare_sell_order_exceeding_open_contracts_rejected(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=5, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=5, actual_fill_price_cents=50)

    response = _create_order(
        client, pos_id, order_id="ord-sell", intent_id="i-sell", action="SELL", requested_qty=6,
        planned_target_price_cents=60,
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------
# 11 -- optimistic locking (Order, ver nota de auditoría en el informe)
# -> 409
# ---------------------------------------------------------------------


def test_11_stale_order_version_on_fill_returns_409(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=10, planned_target_price_cents=50)
    r1 = _register_fill(client, pos_id, fill_id="f1", qty=5, actual_fill_price_cents=50, expected_order_version=1)
    assert r1.status_code == 200

    r2 = _register_fill(client, pos_id, fill_id="f2", qty=5, actual_fill_price_cents=50, expected_order_version=1)
    assert r2.status_code == 409  # la version real ya es 2 tras el primer fill


def test_11b_stale_order_version_on_patch_returns_409(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    order = _create_order(client, pos_id).json()

    response = client.patch(
        f"/positions/{pos_id}/orders/{order['order_id']}",
        json={"expected_version": 99, "new_status": "SUBMITTED", "reason": "STATUS_TRANSITION"},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------
# 12-16 -- POST .../plan (Kirkin, fees KNOWN/ESTIMATED/UNKNOWN,
# capital ya recuperado)
# ---------------------------------------------------------------------


def test_12_plan_kirkin_19_at_50_target_63(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=19, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=19, actual_fill_price_cents=50, fee={"status": "ESTIMATED", "cents": "0"})

    response = client.post(
        f"/positions/{pos_id}/plan",
        json={
            "plan_id": "plan-1",
            "planned_target_price_cents": 63,
            "fee_assumption": {"status": "ESTIMATED", "cents": "0"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contracts_to_sell"] == 16  # ceil(950/63), sin tolerancia (decisión 2)
    assert body["contracts_remaining_after"] == 3
    assert body["net_proceeds_cents"] == "1008"
    assert body["achievability"] == "FULLY_RECOVERABLE"
    assert body["provisional"] is True
    assert body["provisional_reason"]


def test_13_plan_with_known_fee_is_not_provisional(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=19, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=19, actual_fill_price_cents=50, fee={"status": "KNOWN", "cents": "0"})

    response = client.post(
        f"/positions/{pos_id}/plan",
        json={"plan_id": "plan-known", "planned_target_price_cents": 63, "fee_assumption": {"status": "KNOWN", "cents": "0"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provisional"] is False
    assert body["provisional_reason"] is None


def test_14_plan_with_estimated_fee_is_provisional(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=19, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=19, actual_fill_price_cents=50, fee={"status": "KNOWN", "cents": "0"})

    response = client.post(
        f"/positions/{pos_id}/plan",
        json={
            "plan_id": "plan-est",
            "planned_target_price_cents": 63,
            "fee_assumption": {"status": "ESTIMATED", "cents": "0"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provisional"] is True
    assert "ESTIMATED" in body["provisional_reason"]


def test_15_plan_with_unknown_fee_is_provisional_fail_closed(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=19, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=19, actual_fill_price_cents=50, fee={"status": "KNOWN", "cents": "0"})

    response = client.post(
        f"/positions/{pos_id}/plan",
        json={"plan_id": "plan-unk", "planned_target_price_cents": 63, "fee_assumption": {"status": "UNKNOWN"}},
    )
    assert response.status_code == 200  # no ejecuta nada, solo calcula -- provisional, no bloquea el cálculo
    body = response.json()
    assert body["provisional"] is True
    assert body["contracts_to_sell"] == 16  # fee usada como 0, pero marcada provisional (nunca KNOWN silencioso)


def test_16_plan_already_recovered_returns_zero_qty(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=10, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=10, actual_fill_price_cents=50, fee={"status": "KNOWN", "cents": "0"})
    _create_order(client, pos_id, order_id="ord-sell", intent_id="i-sell", action="SELL", requested_qty=10, planned_target_price_cents=60)
    _register_fill(client, pos_id, fill_id="s1", order_id="ord-sell", action="SELL", qty=10, actual_fill_price_cents=60, fee={"status": "KNOWN", "cents": "0"}, expected_order_version=1)

    response = client.post(
        f"/positions/{pos_id}/plan",
        json={"plan_id": "plan-done", "planned_target_price_cents": 50, "fee_assumption": {"status": "KNOWN", "cents": "0"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contracts_to_sell"] == 0
    assert body["achievability"] == "ALREADY_RECOVERED"


# ---------------------------------------------------------------------
# 17-19 -- crear Order PREPARED + idempotencia
# ---------------------------------------------------------------------


def test_17_create_order_prepared(client):
    position = _create_position(client)
    order = _create_order(client, position["position_id"]).json()
    assert order["status"] == "PLANNED"  # "PREPARED" del alcance == PLANNED del dominio auditado
    assert order["confirmed_filled_qty"] == 0


def test_18_repeat_same_order_intent_does_not_duplicate(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    first = _create_order(client, pos_id).json()
    retry = _create_order(client, pos_id).json()  # mismo order_id/intent_id/payload
    assert first == retry
    orders = client.get(f"/positions/{pos_id}/orders").json()["orders"]
    assert len(orders) == 1


def test_19_order_intent_incompatible_with_same_key_returns_409(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=10)
    response = _create_order(client, pos_id, requested_qty=99)  # mismo order_id/intent_id, distinto qty
    assert response.status_code == 409


def test_19b_new_intent_blocked_while_non_terminal_order_exists_returns_409(client):
    """"No permitir intención incompatible con estado UNKNOWN/reservado":
    mientras una Order siga no-terminal (aquí PLANNED, sin llegar a
    UNKNOWN), no se puede preparar una segunda Order con una
    intent_id/order_id DISTINTA para la misma posición (F5)."""
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, order_id="ord-1", intent_id="i-1")
    response = _create_order(client, pos_id, order_id="ord-2", intent_id="i-2")
    assert response.status_code == 409


# ---------------------------------------------------------------------
# 20-22 -- transición válida / inválida / CANCELED
# ---------------------------------------------------------------------


def test_20_patch_order_planned_to_submitted(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    order = _create_order(client, pos_id).json()

    response = client.patch(
        f"/positions/{pos_id}/orders/{order['order_id']}",
        json={"expected_version": 1, "new_status": "SUBMITTED", "reason": "STATUS_TRANSITION"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUBMITTED"


def test_21_patch_order_invalid_transition_rejected(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    order = _create_order(client, pos_id).json()

    response = client.patch(
        f"/positions/{pos_id}/orders/{order['order_id']}",
        json={"expected_version": 1, "new_status": "REJECTED", "reason": "STATUS_TRANSITION"},
    )
    assert response.status_code == 409  # PLANNED -> REJECTED no es una transición válida


def test_22_patch_order_canceled(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    order = _create_order(client, pos_id).json()

    response = client.patch(
        f"/positions/{pos_id}/orders/{order['order_id']}",
        json={"expected_version": 1, "new_status": "CANCELED", "reason": "CANCEL_REPLACE"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELED"


# ---------------------------------------------------------------------
# 23 -- events audit trail ordenado
# ---------------------------------------------------------------------


def test_23_events_ordered(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=10, planned_target_price_cents=50)
    _register_fill(client, pos_id, qty=10, actual_fill_price_cents=50, fee={"status": "KNOWN", "cents": "0"})
    _create_order(client, pos_id, order_id="ord-sell", intent_id="i-sell", action="SELL", requested_qty=10, planned_target_price_cents=60)
    _register_fill(client, pos_id, fill_id="s1", order_id="ord-sell", action="SELL", qty=10, actual_fill_price_cents=60, fee={"status": "KNOWN", "cents": "0"}, expected_order_version=1)

    response = client.get(f"/positions/{pos_id}/events")
    assert response.status_code == 200
    events = response.json()["events"]
    to_statuses = [e["to_status"] for e in events]
    assert to_statuses == ["OPEN", "CAPITAL_RECOVERED"]  # orden determinista de inserción


# ---------------------------------------------------------------------
# 24/25 -- 404
# ---------------------------------------------------------------------


def test_24_get_position_not_found_returns_404(client):
    response = client.get("/positions/does-not-exist")
    assert response.status_code == 404


def test_25_patch_order_not_found_returns_404(client):
    position = _create_position(client)
    response = client.patch(
        f"/positions/{position['position_id']}/orders/does-not-exist",
        json={"expected_version": 1, "new_status": "SUBMITTED", "reason": "STATUS_TRANSITION"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------
# 26 -- payload inválido -> 422
# ---------------------------------------------------------------------


def test_26_invalid_payload_returns_422(client):
    response = client.post("/positions", json={"kalshi_ticker": "K-1"})  # faltan campos obligatorios
    assert response.status_code == 422


def test_26b_fractional_cents_price_field_returns_422(client):
    position = _create_position(client)
    response = _create_order(client, position["position_id"], planned_target_price_cents=50.5)
    assert response.status_code == 422


# ---------------------------------------------------------------------
# 27 -- ninguna ruta ejecuta Robinhood / automatización de navegador
# ---------------------------------------------------------------------


def test_27_no_robinhood_execution_capability_in_positions_api():
    """Escanea el CÓDIGO real (imports + literales), no los docstrings --
    los docstrings de este módulo mencionan deliberadamente "nunca
    Selenium/Playwright/Robinhood" como documentación de la frontera,
    lo cual no debe hacer fallar al propio test que la verifica."""
    forbidden_tokens = (
        "robinhood.com", "selenium", "playwright", "webdriver", "cookiejar",
        "/execute", "/trade", "cookies=", "password", "credentials",
    )
    for module_path in ("src/api/positions_router.py", "src/api/positions_service.py", "src/api/positions_schemas.py"):
        source = Path(module_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_docstring = ast.get_docstring(tree) or ""
        code_without_module_docstring = source.replace(module_docstring, "", 1).lower()
        for token in forbidden_tokens:
            assert token not in code_without_module_docstring, f"{module_path} contiene {token!r} fuera del docstring -- prohibido"


def test_27b_no_route_named_execute_trade_buy_or_sell():
    import src.api.main as m

    forbidden_path_fragments = ("/execute", "/trade", "/buy", "/sell")
    for route in m.app.routes:
        path = getattr(route, "path", "")
        for fragment in forbidden_path_fragments:
            assert fragment not in path, f"ruta {path!r} contiene fragmento prohibido {fragment!r}"


# ---------------------------------------------------------------------
# 28 -- ninguna ruta escribe fuera de service/repository (sin SQL crudo
# en el router, sin import de sqlite3 fuera de positions_repository.py)
# ---------------------------------------------------------------------


def test_28_router_never_imports_sqlite3_or_writes_sql_directly():
    for module_path in ("src/api/positions_router.py", "src/api/positions_service.py"):
        tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "sqlite3", f"{module_path} importa sqlite3 directamente"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "sqlite3", f"{module_path} importa desde sqlite3 directamente"


def test_28b_router_only_talks_to_repository_via_service_layer():
    tree = ast.parse(Path("src/api/positions_router.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "src.positions.positions_repository" in imported  # solo para el tipo/Depends, no para escribir
    # El router nunca debe importar sqlite3 ni módulos de storage genéricos.
    assert "sqlite3" not in imported
    assert "src.storage.repository" not in imported
    assert "src.storage.history_repository" not in imported


# ---------------------------------------------------------------------
# 29 -- restart/reopen DB conserva estado API-visible
# ---------------------------------------------------------------------


def test_29_restart_reopen_db_preserves_api_visible_state(tmp_path):
    db_path = tmp_path / "restart.db"
    repo1 = PositionsRepository(db_path=db_path)
    main_module.app.dependency_overrides[get_positions_repository] = lambda: repo1
    with TestClient(main_module.app) as c1:
        created = _create_position(c1)
        _create_order(c1, created["position_id"])
        _register_fill(c1, created["position_id"])

    repo2 = PositionsRepository(db_path=db_path)  # "reinicio": instancia nueva, mismo archivo
    main_module.app.dependency_overrides[get_positions_repository] = lambda: repo2
    with TestClient(main_module.app) as c2:
        response = c2.get(f"/positions/{created['position_id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["open_contracts"] == 19
        assert body["total_capital_at_risk_cents"] == "950"

    main_module.app.dependency_overrides.clear()


# ---------------------------------------------------------------------
# Auditoría posterior a Tramo 2 -- punto 1: fill manual/external SIN
# ninguna Order previa preparada por el motor. Caso obligatorio: Position
# MANUAL nueva, el usuario informa directamente "BUY 19 @ 50c" y el
# motor nunca preparó nada. `OrderFill.order_id` es un campo obligatorio
# del dominio (cada fill pertenece a una Order -- ver
# `src.positions.schemas.OrderFill`) y `apply_fill` exige que esa Order
# ya exista; NO se fabrica una Order "fantasma" en el servidor -- el
# cliente declara explícitamente, en el momento real en que reporta el
# hecho, una Order cuyos parámetros son EXACTAMENTE los observados (no
# una intención distinta e inventada), y a continuación registra el
# fill completo contra ella. Ambos pasos quedan en el audit trail con
# sus propios timestamps reales (created_at de la Order = cuándo el
# usuario lo reportó; filled_at del Fill = cuándo ocurrió de verdad en
# Robinhood) -- no hay falsificación de historia, solo dos eventos
# reales y auditables en vez de uno.
# ---------------------------------------------------------------------


def test_manual_position_no_prior_order_can_register_observed_buy_faithfully(client):
    """Caso obligatorio de la auditoría: Position MANUAL nueva, CERO
    Orders existentes, el usuario reporta directamente BUY 19 @ 50c con
    fee ESTIMATED. v1 SÍ puede registrar esto fielmente -- vía
    prepare(=declarar la Order con los parámetros observados)+fill en la
    misma sesión de reporte, sin fabricar nada que el motor no haya
    observado (ambas llamadas las hace el propio cliente, en tiempo
    real, con los valores realmente ejecutados)."""
    position = _create_position(client, source="MANUAL")
    pos_id = position["position_id"]
    assert client.get(f"/positions/{pos_id}/orders").json()["orders"] == []  # cero Orders previas

    order_response = _create_order(
        client, pos_id, order_id="ord-observed", intent_id="i-observed",
        action="BUY", requested_qty=19, planned_target_price_cents=50,
    )
    assert order_response.status_code == 200, order_response.text

    fill_response = _register_fill(
        client, pos_id, fill_id="fill-observed", order_id="ord-observed",
        action="BUY", qty=19, actual_fill_price_cents=50,
        fee={"status": "ESTIMATED", "cents": "0"}, expected_order_version=1,
    )
    assert fill_response.status_code == 200, fill_response.text
    body = fill_response.json()
    assert body["order"]["status"] == "FILLED"
    assert body["position"]["open_contracts"] == 19
    assert body["position"]["total_capital_at_risk_cents"] == "950"

    # Audit trail honesto: la Order declarada por el cliente y su fill
    # quedan como dos eventos reales, en el orden real en que ocurrieron
    # -- nada fue fabricado retroactivamente por el servidor.
    order_events = client.get(f"/positions/{pos_id}/orders").json()["orders"]
    assert len(order_events) == 1
    assert order_events[0]["order_id"] == "ord-observed"


# ---------------------------------------------------------------------
# Auditoría posterior a Tramo 2 -- punto 2: expected_order_version y
# concurrencia. Escenario: Client B registra un fill legítimo contra
# Order O (version 1 -> 2). Client A, con información stale (todavía
# cree que O sigue en version 1), intenta registrar un fill DISTINTO
# contra la misma O. Debe rechazarse sin corromper Position -- ni lost
# update, ni open_contracts incorrecto, ni doble venta.
# ---------------------------------------------------------------------


def test_concurrent_fill_with_stale_order_version_rejected_without_corrupting_position(client):
    position = _create_position(client)
    pos_id = position["position_id"]
    _create_order(client, pos_id, requested_qty=10, planned_target_price_cents=50)

    # Client B: fill legítimo, primero en llegar. Order O: version 1 -> 2.
    client_b = _register_fill(
        client, pos_id, fill_id="fill-b", qty=6, actual_fill_price_cents=50, expected_order_version=1,
    )
    assert client_b.status_code == 200
    position_after_b = client_b.json()["position"]
    assert position_after_b["open_contracts"] == 6
    assert position_after_b["total_capital_at_risk_cents"] == "300"

    # Client A: información stale (cree que O sigue en version 1).
    # Rechazado -- NUNCA se aplica un lost update sobre la Position.
    client_a = _register_fill(
        client, pos_id, fill_id="fill-a", qty=4, actual_fill_price_cents=50, expected_order_version=1,
    )
    assert client_a.status_code == 409

    # Position queda exactamente como la dejó B -- ninguna corrupción,
    # ningún doble conteo, ningún open_contracts incorrecto.
    unchanged = client.get(f"/positions/{pos_id}").json()
    assert unchanged["open_contracts"] == 6
    assert unchanged["total_capital_at_risk_cents"] == "300"
    assert unchanged["version"] == position_after_b["version"]

    # Client A, tras releer la version real (2), reintenta correctamente
    # -- el flujo normal de recuperación de un 409 optimistic-lock.
    client_a_retry = _register_fill(
        client, pos_id, fill_id="fill-a-retry", qty=4, actual_fill_price_cents=50, expected_order_version=2,
    )
    assert client_a_retry.status_code == 200
    assert client_a_retry.json()["position"]["open_contracts"] == 10
    assert client_a_retry.json()["position"]["total_capital_at_risk_cents"] == "500"
