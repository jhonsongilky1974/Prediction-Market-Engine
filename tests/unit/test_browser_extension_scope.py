"""Auditoría de scope de Phase 6 -- Tramo 3 (integración browser-extension
<-> Position Management API). Verificaciones puramente textuales sobre
el código fuente real de la extensión -- no requieren un motor JS (ver
`browser-extension/tests/position_logic.test.js` para la lógica pura,
verificada además en vivo con el motor JS del navegador por falta de
`node` en este entorno, documentado en el propio archivo).

Objetivo: confirmar, de forma repetible en CI, que la extensión NUNCA
adquirió capacidad de ejecución real -- ni hacia Robinhood ni hacia
SQLite directamente -- al integrarse con la API de Tramo 2."""
from __future__ import annotations

import json
import re
from pathlib import Path

EXTENSION_DIR = Path("browser-extension")
JS_FILES = ["background.js", "content_script.js", "position_logic.js", "page_hook.js"]


def _read(filename: str) -> str:
    return (EXTENSION_DIR / filename).read_text(encoding="utf-8")


def test_no_click_or_dispatch_event_anywhere_in_extension():
    """La extensión nunca automatiza clicks ni eventos DOM sobre
    elementos ajenos -- nuestros propios botones son clickeados por el
    USUARIO (addEventListener("click", ...) del lado de escucha, nunca
    `.click()`/`dispatchEvent(...)` del lado de disparo)."""
    for filename in JS_FILES:
        content = _read(filename)
        assert ".click(" not in content, f"{filename} contiene una llamada .click() -- prohibido"
        assert "dispatchEvent(" not in content, f"{filename} contiene dispatchEvent() -- prohibido"


def test_no_selenium_playwright_webdriver_references():
    for filename in JS_FILES:
        content = _read(filename).lower()
        for token in ("selenium", "playwright", "webdriver"):
            assert token not in content, f"{filename} menciona {token!r} -- prohibido"


def test_no_credentials_password_token_cookie_handling():
    """Busca USO real de credenciales/cookies (patrones de API), no la
    palabra suelta -- `page_hook.js` (Fase 5, sin cambios en este tramo)
    documenta en prosa que la SPA de Robinhood ya trae sus propias
    cookies de sesión (es precisamente la razón de NO necesitar
    credenciales propias); esa frase explicativa es legítima y no debe
    hacer fallar la auditoría."""
    for filename in JS_FILES:
        content = _read(filename)
        assert "password" not in content.lower(), f"{filename} menciona 'password' -- prohibido"
        assert not re.search(r"\bcredential", content, re.IGNORECASE), f"{filename} menciona 'credential' -- prohibido"
        assert "document.cookie" not in content, f"{filename} accede a document.cookie -- prohibido"
        assert "chrome.cookies" not in content, f"{filename} usa la API chrome.cookies -- prohibido"
        assert not re.search(r"\btoken\b", content, re.IGNORECASE), f"{filename} menciona 'token' -- revisar manualmente"


def test_no_sqlite_import_in_extension():
    """La extensión nunca debe importar/requerir sqlite -- toda
    persistencia pasa por FastAPI (browser-extension -> FastAPI ->
    service/repository -> SQLite, nunca browser-extension -> SQLite)."""
    for filename in JS_FILES:
        content = _read(filename).lower()
        assert "require(" not in content or "sqlite" not in content, f"{filename} podría importar sqlite -- prohibido"
        assert "import sqlite" not in content


def test_fetch_calls_only_target_local_backend_never_robinhood():
    """Único origen real de red permitido: BACKEND_BASE
    (127.0.0.1:8000). Ninguna llamada `fetch(...)` debe apuntar a un
    literal que contenga "robinhood.com" -- si el propio backend algún
    día expusiera una URL con ese substring como parte de un mensaje de
    error/log, este test seguiría siendo válido porque busca
    específicamente el patrón `fetch(` seguido de un literal con
    robinhood.com, no la palabra "robinhood" a secas (que sí aparece
    legítimamente en comentarios y en el nombre del propio endpoint
    /map/robinhood, que es un endpoint del backend LOCAL, no de
    robinhood.com)."""
    for filename in ("background.js", "content_script.js", "position_logic.js"):
        content = _read(filename)
        assert not re.search(r"fetch\(\s*[`\"'][^`\"']*robinhood\.com", content, re.IGNORECASE), (
            f"{filename} contiene un fetch() apuntando a un literal con robinhood.com -- prohibido"
        )

    # content_script.js/position_logic.js NUNCA deben hacer fetch directo
    # -- solo background.js está autorizado a hablar con la red (mismo
    # principio que el flujo de análisis ya auditado en Fase 5).
    assert "fetch(" not in _read("content_script.js")
    assert "fetch(" not in _read("position_logic.js")

    # Ambas llamadas fetch() reales de background.js usan la URL del
    # primer argumento -- o bien BACKEND_BASE, o `url` (variable interna
    # ya construida a partir de BACKEND_BASE en mapAndAnalyze -- flujo
    # preexistente de Fase 5, sin cambios).
    background = _read("background.js")
    fetch_calls = re.findall(r"fetch\(([^,\n]+)", background)
    assert fetch_calls, "se esperaba al menos una llamada fetch() en background.js"
    for call_arg in fetch_calls:
        assert "robinhood" not in call_arg.lower(), f"fetch() con argumento sospechoso: {call_arg}"


def test_no_execution_endpoint_paths_anywhere():
    """Ninguna ruta/endpoint de ejecución (/execute, /trade, /buy,
    /sell) debe aparecer como literal de path en ningún archivo de la
    extensión."""
    forbidden_fragments = ("/execute", "/trade", "/buy", "/sell")
    for filename in JS_FILES:
        content = _read(filename)
        for fragment in forbidden_fragments:
            assert fragment not in content, f"{filename} contiene el fragmento de ruta prohibido {fragment!r}"


def test_position_actions_whitelist_is_closed_and_matches_audited_endpoints():
    """El bridge de background.js (`POSITION_ACTIONS`) es un whitelist
    CERRADO -- nunca un passthrough genérico de URL/método arbitrario.
    Verifica que contenga EXACTAMENTE las 8 acciones correspondientes a
    los endpoints ya auditados en Tramo 2, ni una más."""
    background = _read("background.js")
    match = re.search(r"const POSITION_ACTIONS = \{(.*?)\n\};", background, re.DOTALL)
    assert match, "no se encontró la definición de POSITION_ACTIONS en background.js"
    body = match.group(1)
    action_names = set(re.findall(r"^\s*(\w+):", body, re.MULTILINE))
    expected = {
        "list_positions",
        "create_position",
        "register_fill",
        "compute_plan",
        "create_order",
        "update_order",
        "list_orders",
        "list_events",
    }
    assert action_names == expected, f"whitelist de acciones inesperado: {action_names}"

    # Cada acción de la whitelist debe construir su URL bajo /positions
    # exclusivamente (nunca un patrón externo).
    urls = re.findall(r"`([^`]*)`", body)
    assert all(u.startswith("/positions") for u in urls if u.startswith("/")), "alguna URL de POSITION_ACTIONS no está bajo /positions"


def test_manifest_declares_only_expected_hosts_and_scripts():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["host_permissions"]) == {
        "https://robinhood.com/*",
        "https://*.robinhood.com/*",
        "http://127.0.0.1:8000/*",
    }
    isolated_world_scripts = manifest["content_scripts"][1]["js"]
    assert isolated_world_scripts == ["position_logic.js", "content_script.js"], (
        "position_logic.js debe cargarse ANTES que content_script.js en el mismo mundo aislado"
    )


def test_extension_never_writes_directly_to_sqlite_frontier_preserved():
    """browser-extension -> FastAPI -> service/repository -> SQLite,
    nunca browser-extension -> SQLite. Confirmado indirectamente: ningún
    archivo de la extensión menciona un path de base de datos ni el
    driver sqlite3."""
    for filename in JS_FILES:
        content = _read(filename).lower()
        assert "engine.db" not in content
        assert "sqlite3" not in content


def test_planned_status_never_labeled_as_submitted_executed_or_placed():
    """Auditoría de "seguridad visual": una Order recién preparada
    (PLANNED) nunca debe describirse con palabras que sugieran que
    Robinhood la recibió."""
    content_script = _read("content_script.js")
    assert "Prepared locally" in content_script
    assert "not submitted to Robinhood" in content_script
    # Ninguna de estas palabras debe aparecer describiendo el resultado
    # de "Prepare Exit Order" / creación de Order.
    forbidden_words = ["Executed", "Placed", "Sent to Robinhood"]
    for word in forbidden_words:
        assert word not in content_script, f"content_script.js usa la palabra prohibida {word!r}"


def test_fill_registration_disclaimer_present():
    content_script = _read("content_script.js")
    assert "Registering a fill records what already happened in Robinhood. It does not place an order." in content_script


def test_reconciliation_never_offers_filled_or_partially_filled_targets():
    """Auditoría Tramo 3: el backend (positions_repository.py::
    update_order_status) rechaza asignar FILLED/PARTIALLY_FILLED sin un
    OrderFill real detrás -- la UI no debe ni siquiera ofrecerlos como
    destino de "Update observed status"."""
    content_script = _read("content_script.js")
    match = re.search(r"const RECONCILE_TARGET_STATUSES = \[(.*?)\];", content_script)
    assert match, "no se encontró RECONCILE_TARGET_STATUSES"
    values = re.findall(r'"(\w+)"', match.group(1))
    assert "FILLED" not in values
    assert "PARTIALLY_FILLED" not in values
    assert "PLANNED" not in values
    assert "EXPIRED" not in values  # nunca se inventó un estado que no existe en el backend
    assert set(values) == {"SUBMITTED", "PENDING", "CANCELED", "REJECTED", "UNKNOWN"}


def test_no_automatic_recompute_or_polling_loop_introduced():
    """No debe existir ningún `setInterval`/polling agresivo del backend
    para Position Management -- los refrescos son siempre reactivos a
    una acción (crear/fill/plan/order/refresh explícito)."""
    content_script = _read("content_script.js")
    assert "setInterval(" not in content_script
