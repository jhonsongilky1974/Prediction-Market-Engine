// Lógica PURA de Position Management (Fase 6, Tramo 3) -- CERO
// dependencias de chrome.*, document.*, window.fetch. Se carga ANTES de
// content_script.js en el mismo mundo aislado (ver manifest.json) para
// que sus funciones queden disponibles como globals ahí. Precisamente
// por no tocar ninguna API de extensión ni del DOM, es testeable fuera
// del navegador -- ver tests/position_logic.test.js (node --test) y
// tests/unit/test_browser_extension_scope.py (auditoría de scope).
//
// Frontera de responsabilidad: este archivo NUNCA decide nada
// financiero (capital recovery, fees reales, etc.) -- esas reglas viven
// exclusivamente en el backend (src.positions.capital_recovery, ya
// auditado). Lo que hay aquí es: (a) asociación Position<->ticker
// fail-closed, (b) estabilidad de idempotency keys de UI, (c)
// validación de FORMATO de un input de fee (no de su corrección
// financiera), (d) helpers de formato/label puramente cosméticos que
// replican una etiqueta ya decidida por el backend (nunca la inventan).
(function (global) {
  "use strict";

  const SPORT_BUCKET_TO_DOMAIN = { baseball: "MLB", tennis: "TENNIS" };

  function sportBucketToDomain(bucket) {
    return SPORT_BUCKET_TO_DOMAIN[bucket] ?? null;
  }

  // Asociación Position <-> ticker actual. Fail-closed: NUNCA selecciona
  // silenciosamente entre 2+ candidatas (podrían ser lados YES/NO
  // opuestos, o dos posiciones distintas para el mismo ticker) -- se
  // devuelve "ambiguous" y la UI debe exigir selección explícita del
  // usuario. 0 coincidencias -> "none". Exactamente 1 -> "single".
  function matchPositionsByTicker(positions, ticker) {
    if (!ticker) return { kind: "none", matches: [] };
    const matches = (positions || []).filter((p) => p && p.kalshi_ticker === ticker);
    if (matches.length === 0) return { kind: "none", matches: [] };
    if (matches.length === 1) return { kind: "single", matches };
    return { kind: "ambiguous", matches };
  }

  function generateUuid() {
    return typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

  // Idempotencia de UI: la MISMA intención lógica (mismo formulario
  // abierto, sin que el usuario lo haya cerrado/reiniciado
  // conscientemente) siempre reutiliza la misma key -- protege contra
  // doble click, reintento por latencia, o un re-render accidental.
  // `resetIntentId` es la ÚNICA función que limpia el campo, y debe
  // llamarse solo desde una acción explícita del usuario ("New fill" /
  // cerrar+reabrir el formulario para una entrada consciente nueva) --
  // nunca automáticamente tras un error o un timeout.
  function ensureIntentId(stateObj, key) {
    const k = key || "intentId";
    if (!stateObj[k]) stateObj[k] = generateUuid();
    return stateObj[k];
  }

  function resetIntentId(stateObj, key) {
    stateObj[key || "intentId"] = null;
  }

  // Validación de FORMATO únicamente -- mismo invariante de forma que
  // src.positions.schemas.Fee, pero replicado aquí SOLO para dar
  // feedback inmediato antes de golpear la red; la regla real y
  // definitiva la sigue aplicando el backend.
  function validateFeeInput(fee) {
    if (!fee || !["KNOWN", "ESTIMATED", "UNKNOWN"].includes(fee.status)) {
      return { valid: false, error: "fee.status debe ser KNOWN, ESTIMATED o UNKNOWN" };
    }
    if (fee.status === "UNKNOWN") {
      if (fee.cents !== null && fee.cents !== undefined && fee.cents !== "") {
        return { valid: false, error: "fee.cents debe omitirse cuando status=UNKNOWN" };
      }
      return { valid: true, error: null };
    }
    if (fee.cents === null || fee.cents === undefined || fee.cents === "") {
      return { valid: false, error: `fee.cents es obligatorio cuando status=${fee.status}` };
    }
    if (Number.isNaN(Number(fee.cents))) {
      return { valid: false, error: "fee.cents debe ser un decimal exacto (ej. 6.93)" };
    }
    return { valid: true, error: null };
  }

  // Etiqueta de "recuperación de capital confirmada" -- mismo criterio
  // que src.positions.capital_recovery.is_capital_recovery_confirmed
  // (AMBOS lados, entrada y salida, deben ser KNOWN). Puramente para
  // ETIQUETAR lo que el backend ya decidió (status/fee_status) -- nunca
  // decide nada financiero por sí misma.
  function isCapitalRecoveryConfirmed(status, investedFeeStatus, recoveredFeeStatus) {
    if (status !== "CAPITAL_RECOVERED") return false;
    return investedFeeStatus === "KNOWN" && recoveredFeeStatus === "KNOWN";
  }

  // Resta pura para el preview de "Prepare Exit Order" (contratos que
  // quedarían tras la venta propuesta) -- NO es lógica de capital
  // recovery (esa vive exclusivamente en el backend); es una resta de
  // enteros para mostrar antes de confirmar. null si la cantidad
  // propuesta excede lo abierto -- la UI debe bloquear el submit, nunca
  // mostrar un remanente negativo.
  function contractsRemainingAfterExit(openContracts, sellQty) {
    const open = Number(openContracts);
    const sell = Number(sellQty);
    if (!Number.isFinite(open) || !Number.isFinite(sell) || sell < 0) return null;
    const remaining = open - sell;
    return remaining >= 0 ? remaining : null;
  }

  function formatCentsLabel(centsDecimalString) {
    if (centsDecimalString === null || centsDecimalString === undefined) return "n/d";
    const value = Number(centsDecimalString);
    if (Number.isNaN(value)) return `${centsDecimalString}c`;
    return `${centsDecimalString}c ($${(value / 100).toFixed(2)})`;
  }

  const api = {
    sportBucketToDomain,
    matchPositionsByTicker,
    generateUuid,
    ensureIntentId,
    resetIntentId,
    validateFeeInput,
    isCapitalRecoveryConfirmed,
    contractsRemainingAfterExit,
    formatCentsLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api; // permite `require(...)` desde `node --test`
  }
  Object.assign(global, api); // expone como globals en el mundo aislado de la extensión
})(typeof globalThis !== "undefined" ? globalThis : this);
