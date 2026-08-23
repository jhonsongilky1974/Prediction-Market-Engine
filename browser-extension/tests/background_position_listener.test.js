// Test de regresión de background.js -- Fase 6, Tramo 4 (2a parte):
// "el puerto de mensajes se cerró antes de recibir una respuesta" en
// Position Management. Cero dependencias externas: node --test +
// node:assert, mismo patrón que position_logic.test.js. Ejecutar con:
//   node --test browser-extension/tests/
//
// NOTA de entorno: este sandbox no tiene `node` instalado -- la lógica
// se verificó en su lugar evaluándola en el motor JS real del
// navegador (Claude Browser tool), ejecutando exactamente el mismo
// escenario de excepción síncrona que este archivo prueba. Listo para
// correr con `node --test` en cualquier máquina con Node >=18.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BACKGROUND_SRC = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");

// Carga background.js en un contexto aislado por test -- captura los
// listeners registrados vía chrome.runtime.onMessage.addListener sin
// depender de ningún estado compartido entre tests.
function loadBackgroundWithStubs({ fetchImpl } = {}) {
  const listeners = [];
  const sandbox = {
    chrome: {
      runtime: {
        onMessage: {
          addListener: (fn) => listeners.push(fn),
        },
      },
    },
    fetch: fetchImpl,
    console,
    setTimeout,
    clearTimeout,
    Date,
    AbortController,
    Promise,
    Error,
    URLSearchParams,
    encodeURIComponent,
    JSON,
  };
  const vm = require("node:vm");
  const context = vm.createContext(sandbox);
  vm.runInContext(BACKGROUND_SRC, context);
  return listeners;
}

function fakeOkResponse(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

test("background.js registra exactamente 2 listeners (pme-analyze, pme-position-request)", () => {
  const listeners = loadBackgroundWithStubs({ fetchImpl: () => fakeOkResponse({ positions: [] }) });
  assert.equal(listeners.length, 2);
});

test("el listener pme-position-request DEVUELVE una Promise para una acción válida (no true/false)", async () => {
  const listeners = loadBackgroundWithStubs({ fetchImpl: () => fakeOkResponse({ positions: [] }) });
  const positionListener = listeners[1];

  const message = { type: "pme-position-request", action: "list_positions", payload: {} };
  const returnValue = positionListener(message, {}, () => {});

  assert.ok(returnValue instanceof Promise, "el listener debe devolver una Promise (patrón Chrome MV3 >=99)");
  const resolved = await returnValue;
  assert.deepEqual(resolved, { ok: true, status: 200, body: { positions: [] } });
});

test(
  "REGRESIÓN: una excepción SÍNCRONA dentro de action(...) (antes de devolver su Promise) " +
    "NUNCA escapa del listener ni deja el canal sin respuesta -- produce una Promise resuelta con error",
  async () => {
    // fetch() lanza SÍNCRONAMENTE -- simula exactamente el escenario que
    // producía "message port closed before a response was received" con
    // el patrón anterior (sendResponse(...) + return true): la excepción
    // abortaba el listener ANTES de llegar a `return true`, dejando a
    // Chrome sin ninguna señal de "responderé async".
    const listeners = loadBackgroundWithStubs({
      fetchImpl: () => {
        throw new Error("fallo síncrono simulado en fetch()");
      },
    });
    const positionListener = listeners[1];

    const message = { type: "pme-position-request", action: "list_positions", payload: {} };

    let thrown = null;
    let returnValue;
    try {
      returnValue = positionListener(message, {}, () => {});
    } catch (err) {
      thrown = err;
    }

    assert.equal(thrown, null, "el listener NUNCA debe dejar escapar una excepción síncrona");
    assert.ok(returnValue instanceof Promise, "incluso ante un throw síncrono, debe devolver una Promise");

    const resolved = await returnValue;
    assert.equal(resolved.ok, false);
    assert.equal(resolved.status, 0);
    assert.match(resolved.body.detail, /excepción síncrona inesperada/);
  }
);

test("una acción desconocida devuelve una Promise resuelta con error, nunca deja el canal sin respuesta", async () => {
  const listeners = loadBackgroundWithStubs({ fetchImpl: () => fakeOkResponse({}) });
  const positionListener = listeners[1];

  const message = { type: "pme-position-request", action: "no_existe", payload: {} };
  const returnValue = positionListener(message, {}, () => {});

  assert.ok(returnValue instanceof Promise);
  const resolved = await returnValue;
  assert.equal(resolved.ok, false);
  assert.match(resolved.body.detail, /acción desconocida/);
});

test("un rechazo async inesperado dentro de action(...) también se convierte en una Promise resuelta (nunca rejected)", async () => {
  const listeners = loadBackgroundWithStubs({
    fetchImpl: () => Promise.reject(new Error("network down (no AbortError)")),
  });
  const positionListener = listeners[1];

  const message = { type: "pme-position-request", action: "list_positions", payload: {} };
  const returnValue = positionListener(message, {}, () => {});

  assert.ok(returnValue instanceof Promise);
  // No debe rechazar -- backendJsonFetch ya captura errores de red, y el
  // .catch() adicional del listener es la segunda red de seguridad.
  const resolved = await returnValue;
  assert.equal(resolved.ok, false);
});

test("mensajes de otro tipo (pme-analyze) siguen intactos: el listener de position-request los ignora (return false)", () => {
  const listeners = loadBackgroundWithStubs({ fetchImpl: () => fakeOkResponse({}) });
  const positionListener = listeners[1];

  const returnValue = positionListener({ type: "pme-analyze", symbol: "X" }, {}, () => {});
  assert.equal(returnValue, false);
});
