// Tests de browser-extension/position_logic.js -- Fase 6, Tramo 3.
// Cero dependencias externas: usa el runner y el assert INTEGRADOS de
// Node (>=18), sin instalar ningún framework. Ejecutar con:
//   node --test browser-extension/tests/
//
// NOTA de entorno: este sandbox no tiene `node` instalado, así que este
// archivo no se ejecutó aquí con `node --test` -- la lógica se verificó
// en su lugar evaluándola en el motor JS real del navegador (Claude
// Browser tool), ejecutando exactamente las mismas aserciones. Este
// archivo queda listo para correr con `node --test` en cualquier
// máquina con Node >=18 (ver README.md de browser-extension/).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  sportBucketToDomain,
  matchPositionsByTicker,
  generateUuid,
  ensureIntentId,
  resetIntentId,
  validateFeeInput,
  isCapitalRecoveryConfirmed,
  contractsRemainingAfterExit,
  formatCentsLabel,
} = require("../position_logic.js");

test("sportBucketToDomain mapea baseball/tennis a MLB/TENNIS, resto a null", () => {
  assert.equal(sportBucketToDomain("baseball"), "MLB");
  assert.equal(sportBucketToDomain("tennis"), "TENNIS");
  assert.equal(sportBucketToDomain("basketball"), null);
  assert.equal(sportBucketToDomain(undefined), null);
});

test("matchPositionsByTicker: 0 coincidencias -> none", () => {
  const result = matchPositionsByTicker([{ kalshi_ticker: "K-OTHER" }], "K-1");
  assert.equal(result.kind, "none");
  assert.deepEqual(result.matches, []);
});

test("matchPositionsByTicker: exactamente 1 coincidencia -> single", () => {
  const positions = [{ position_id: "p1", kalshi_ticker: "K-1", side: "YES" }, { position_id: "p2", kalshi_ticker: "K-2", side: "YES" }];
  const result = matchPositionsByTicker(positions, "K-1");
  assert.equal(result.kind, "single");
  assert.equal(result.matches.length, 1);
  assert.equal(result.matches[0].position_id, "p1");
});

test("matchPositionsByTicker: 2+ coincidencias (incluye lados opuestos) -> ambiguous, nunca se selecciona sola", () => {
  const positions = [
    { position_id: "p1", kalshi_ticker: "K-1", side: "YES" },
    { position_id: "p2", kalshi_ticker: "K-1", side: "NO" },
  ];
  const result = matchPositionsByTicker(positions, "K-1");
  assert.equal(result.kind, "ambiguous");
  assert.equal(result.matches.length, 2);
});

test("matchPositionsByTicker nunca mezcla posiciones de otro ticker", () => {
  const positions = [
    { position_id: "p1", kalshi_ticker: "K-1", side: "YES" },
    { position_id: "p2", kalshi_ticker: "K-2", side: "YES" },
  ];
  const result = matchPositionsByTicker(positions, "K-1");
  assert.equal(result.kind, "single");
  assert.equal(result.matches[0].position_id, "p1");
});

test("ensureIntentId genera una key la primera vez y la reutiliza siempre después (estabilidad de idempotencia de UI)", () => {
  const state = {};
  const first = ensureIntentId(state);
  const second = ensureIntentId(state);
  const third = ensureIntentId(state);
  assert.equal(first, second);
  assert.equal(second, third);
  assert.equal(typeof first, "string");
  assert.ok(first.length > 0);
});

test("resetIntentId es la UNICA forma de obtener una key nueva -- simula 'nueva intención consciente'", () => {
  const state = {};
  const first = ensureIntentId(state);
  resetIntentId(state);
  const second = ensureIntentId(state);
  assert.notEqual(first, second);
});

test("generateUuid produce valores distintos en llamadas sucesivas", () => {
  const a = generateUuid();
  const b = generateUuid();
  assert.notEqual(a, b);
});

test("validateFeeInput: KNOWN sin cents es inválido", () => {
  const result = validateFeeInput({ status: "KNOWN", cents: null });
  assert.equal(result.valid, false);
});

test("validateFeeInput: KNOWN con cents es válido", () => {
  const result = validateFeeInput({ status: "KNOWN", cents: "0" });
  assert.equal(result.valid, true);
});

test("validateFeeInput: ESTIMATED con cents fraccionario es válido", () => {
  const result = validateFeeInput({ status: "ESTIMATED", cents: "6.93" });
  assert.equal(result.valid, true);
});

test("validateFeeInput: UNKNOWN con cents presente es inválido", () => {
  const result = validateFeeInput({ status: "UNKNOWN", cents: "0" });
  assert.equal(result.valid, false);
});

test("validateFeeInput: UNKNOWN sin cents es válido", () => {
  const result = validateFeeInput({ status: "UNKNOWN", cents: null });
  assert.equal(result.valid, true);
});

test("isCapitalRecoveryConfirmed: false si status no es CAPITAL_RECOVERED, sin importar fees", () => {
  assert.equal(isCapitalRecoveryConfirmed("OPEN", "KNOWN", "KNOWN"), false);
  assert.equal(isCapitalRecoveryConfirmed("RECOVERY_IN_PROGRESS", "KNOWN", "KNOWN"), false);
});

test("isCapitalRecoveryConfirmed: requiere AMBOS lados KNOWN", () => {
  assert.equal(isCapitalRecoveryConfirmed("CAPITAL_RECOVERED", "KNOWN", "KNOWN"), true);
  assert.equal(isCapitalRecoveryConfirmed("CAPITAL_RECOVERED", "ESTIMATED", "KNOWN"), false);
  assert.equal(isCapitalRecoveryConfirmed("CAPITAL_RECOVERED", "KNOWN", "ESTIMATED"), false);
  assert.equal(isCapitalRecoveryConfirmed("CAPITAL_RECOVERED", "UNKNOWN", "UNKNOWN"), false);
});

test("contractsRemainingAfterExit: resta simple cuando la venta cabe", () => {
  assert.equal(contractsRemainingAfterExit(19, 16), 3);
  assert.equal(contractsRemainingAfterExit(19, 19), 0);
});

test("contractsRemainingAfterExit: null (no negativo) cuando la venta excede lo abierto", () => {
  assert.equal(contractsRemainingAfterExit(5, 6), null);
});

test("formatCentsLabel: formatea un decimal exacto de forma legible sin perder el valor original", () => {
  assert.equal(formatCentsLabel("950"), "950c ($9.50)");
  assert.equal(formatCentsLabel("6.93"), "6.93c ($0.07)");
  assert.equal(formatCentsLabel(null), "n/d");
});
