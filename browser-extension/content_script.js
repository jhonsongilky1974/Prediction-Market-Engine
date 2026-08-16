// Mundo aislado (default). Recibe vía window.postMessage lo que
// page_hook.js (MAIN world) intercepta del fetch/XHR real de la SPA,
// decide si esa respuesta pertenece al evento que el usuario está
// mirando, pide el análisis a background.js (único contexto con
// permiso para llamar al backend local) y pinta el resultado en un
// panel inyectado en la propia pestaña de Robinhood.
//
// AUDITORÍA 2026-08-06 (ver CONTINUITY.md): un evento de tenis
// (Nakashima vs Droguet, symbols KXATPMATCH-26AUG06NAKDRO-{NAK,DRO})
// disparó, en el mismo Uvicorn, un /analyze contra un ticker
// KXMLBGAME. Verificado con curl directo contra el backend real
// (127.0.0.1:8000) que AMBOS symbols reportados mapean correcta y
// rápidamente a TENNIS/ATP (200, ~0.3s) -- el ticker MLB no puede
// haber salido de esos dos symbols. Conclusión: page_hook.js no
// filtraba por evento, así que una respuesta de OTRO evento (polling
// residual tras navegación SPA sin full reload, o un widget de otros
// partidos en la misma página) se procesaba igual que la del evento
// activo. Fix: filtrar por `category` de `event_state` (única señal
// verificada en ROBINHOOD_KALSHI_MAPPER_SPEC.md §1.1 que distingue
// deporte) antes de siquiera pedir el mapeo, y resetear todo el estado
// local cuando cambia el `eventId` (navegación SPA a otro evento).
//
// FASE 6, TRAMO 3 (añadido, aditivo -- el flujo de arriba permanece
// intacto): sección "Position Management" bajo cada fila de análisis.
// Requiere `position_logic.js` cargado ANTES que este archivo (ver
// manifest.json) -- expone matchPositionsByTicker/ensureIntentId/
// validateFeeInput/etc. como globals en este mismo mundo aislado.
// Frontera estricta: este archivo NUNCA hace fetch directo (ni al
// backend ni a Robinhood) -- todo pasa por background.js vía
// chrome.runtime.sendMessage, exactamente igual que el flujo de
// análisis ya existente. Ninguna acción de esta sección ejecuta nada
// en Robinhood: crear una Order siempre queda en PLANNED ("prepared
// locally"), un fill solo se registra si el usuario lo confirma
// explícitamente como algo que YA ocurrió.
(() => {
  const EVENT_STATE_RE = /\/prediction-markets\/v1\/event_state/;
  const QUOTES_RE = /\/marketdata\/event\/contract\/quotes\/v1\//;
  const LOG_PREFIX = "[pme:content_script]";

  // Bucket grueso de deporte por prefijo de serie -- misma tabla que
  // `_SERIES_TO_SPORT_KEY` en src/api/robinhood_mapper.py, pero
  // colapsada a "baseball"/"tennis" porque `event_state.category` no
  // distingue ATP de WTA.
  const SYMBOL_SPORT_BUCKET = {
    KXMLBGAME: "baseball",
    KXATPMATCH: "tennis",
    KXWTAMATCH: "tennis",
  };
  // `category` real observado en event_state (spec §1.1): "Baseball" / "Tennis".
  const CATEGORY_SPORT_BUCKET = { Baseball: "baseball", Tennis: "tennis" };

  // AUDITORÍA 2026-08-06 (2a parte, ver CONTINUITY.md): con un timeout
  // único de 25s, un evento MLB real (Chicago White Sox vs Boston)
  // expiraba del lado extensión mientras Uvicorn seguía procesando --
  // medido directo contra el backend real: GET /analyze para ese mismo
  // ticker tardó ~25.4s (usuario reportó 31-33s en otra corrida). Fix:
  // timeout de seguridad por deporte, mayor que el de background.js
  // (éste es solo la red de seguridad si background.js no responde en
  // absoluto). "baseball" >= tiempo real observado con margen; default
  // conservador (igual al de baseball) si el symbol no matchea ningún
  // prefijo conocido -- nunca se asume el valor corto de tenis para un
  // deporte no identificado.
  const RESPONSE_TIMEOUT_MS_BY_SPORT = { baseball: 50000, tennis: 20000 };
  const DEFAULT_RESPONSE_TIMEOUT_MS = RESPONSE_TIMEOUT_MS_BY_SPORT.baseball;

  // Estados de Order alcanzables vía "Update observed status"
  // (reconciliación MANUAL, PATCH .../orders/:id) -- EXACTAMENTE los
  // valores reales del backend (src.positions.enums.OrderStatus), sin
  // inventar EXPIRED. FILLED/PARTIALLY_FILLED se EXCLUYEN a propósito:
  // el backend (auditoría Tramo 3, ver positions_repository.py::
  // update_order_status) rechaza asignarlos por esta vía porque no hay
  // ningún OrderFill detrás que los respalde -- para eso existe
  // "Register Fill", que sí registra un OrderFill real y deriva el
  // status correctamente. PLANNED tampoco es un destino válido (ningún
  // estado transiciona hacia él).
  const RECONCILE_TARGET_STATUSES = ["SUBMITTED", "PENDING", "CANCELED", "REJECTED", "UNKNOWN"];

  let currentEventId = null;
  let currentCategoryBucket = null; // null = sin señal todavía, no se filtra
  let currentGameStart = null;
  let currentEpoch = 0;
  const seenSymbols = new Set();
  const rowState = new Map(); // symbol -> { analysisText, kalshiTicker, sportDomain, position }

  function newRequestId() {
    return (crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`);
  }

  function symbolSportBucket(symbol) {
    const prefix = symbol.split("-")[0];
    if (!prefix) return null;
    const seriesPrefix = prefix.startsWith("KX") ? prefix : `KX${prefix}`;
    return SYMBOL_SPORT_BUCKET[seriesPrefix] ?? null;
  }

  function extractEventId(body) {
    return body?.eventStates?.[0]?.eventId ?? null;
  }

  function extractCategory(body) {
    return body?.eventStates?.[0]?.category ?? null;
  }

  function extractGameStart(body) {
    return body?.eventStates?.[0]?.gameStart ?? null;
  }

  function extractSymbols(body) {
    const items = body?.data ?? [];
    return items.map((entry) => entry?.data?.symbol).filter(Boolean);
  }

  function resetForNewEvent(eventId, categoryBucket, gameStart) {
    console.info(
      `${LOG_PREFIX} evento cambió (eventId ${currentEventId} -> ${eventId}, categoria -> ${categoryBucket}); ` +
        `limpiando estado local (epoch ${currentEpoch} -> ${currentEpoch + 1})`
    );
    currentEventId = eventId;
    currentCategoryBucket = categoryBucket;
    currentGameStart = gameStart;
    currentEpoch += 1;
    seenSymbols.clear();
    rowState.clear(); // limpia también TODO el estado de Position Management de la fila anterior
    renderPanel();
  }

  // -----------------------------------------------------------------
  // Position Management -- estado por fila
  // -----------------------------------------------------------------

  function defaultPositionState() {
    return {
      phase: "idle", // idle -> loading -> none | single | ambiguous | error
      matches: [],
      selected: null,
      error: null,
      requestSeq: 0, // protege contra respuestas stale que lleguen fuera de orden
      createIntentId: null, // idempotency key de "Create Position" -- ESTABLE mientras dure la intención (ver renderCreateForm)
      createForm: null,
      fillForm: null,
      planForm: null,
      exitForm: null,
      orders: { loading: false, list: [], error: null },
      reconcileOpenFor: null,
      reconcileForm: null,
    };
  }

  function ensureRow(symbol) {
    let row = rowState.get(symbol);
    if (!row) {
      row = { analysisText: null, kalshiTicker: null, sportDomain: null, position: defaultPositionState() };
      rowState.set(symbol, row);
    }
    return row;
  }

  function pmRequest(action, payload) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: "pme-position-request", action, payload }, (result) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, status: 0, body: { detail: chrome.runtime.lastError.message } });
            return;
          }
          resolve(result ?? { ok: false, status: 0, body: { detail: "sin respuesta de background.js" } });
        });
      } catch (err) {
        resolve({ ok: false, status: 0, body: { detail: `excepción enviando mensaje: ${err?.message ?? err}` } });
      }
    });
  }

  // Mapea 400/404/409/422/500/red a un mensaje legible, distinguiendo
  // dentro de 409 (stale version / idempotency conflict / transición
  // inválida / reserva no-terminal) cuando el texto del backend lo
  // permite -- nunca se oculta un error como éxito.
  function describeApiError(result) {
    const detail = result?.body?.detail ? String(result.body.detail) : "(sin detalle)";
    if (result.status === 0) return `Network/timeout error: ${detail}`;
    if (result.status === 400) return `Invalid request (400): ${detail}`;
    if (result.status === 404) return `Not found (404): ${detail}`;
    if (result.status === 422) return `Invalid input format (422): ${detail}`;
    if (result.status === 409) {
      if (/version esperada/.test(detail)) return `Conflict (409) -- STALE VERSION: ${detail}`;
      if (/ya fue usado con datos distintos|ya existe/.test(detail)) return `Conflict (409) -- IDEMPOTENCY CONFLICT: ${detail}`;
      if (/transición inválida/.test(detail)) return `Conflict (409) -- INVALID STATE TRANSITION: ${detail}`;
      if (/no terminal/.test(detail)) return `Conflict (409) -- EXISTING NON-TERMINAL ORDER: ${detail}`;
      return `Conflict (409): ${detail}`;
    }
    return `Server error (${result.status}): ${detail}`;
  }

  function refreshPositionSection(symbol) {
    const row = ensureRow(symbol);
    if (!row.kalshiTicker) return;
    const epochAtRequest = currentEpoch;
    const mySeq = ++row.position.requestSeq;
    row.position.phase = "loading";
    renderPanel();

    pmRequest("list_positions", {}).then((result) => {
      if (epochAtRequest !== currentEpoch) return; // evento cambió -- descartar, no pisar estado nuevo
      const current = rowState.get(symbol);
      if (!current || mySeq !== current.position.requestSeq) return; // respuesta stale -- una más nueva ya llegó/está en curso

      if (!result.ok) {
        current.position.phase = "error";
        current.position.error = describeApiError(result);
        renderPanel();
        return;
      }
      const match = matchPositionsByTicker(result.body.positions, row.kalshiTicker);
      current.position.matches = match.matches;
      current.position.phase = match.kind;
      current.position.error = null;
      if (match.kind === "single") {
        current.position.selected = match.matches[0];
      } else if (match.kind === "ambiguous") {
        const stillValid = current.position.selected && match.matches.some((m) => m.position_id === current.position.selected.position_id);
        current.position.selected = stillValid ? current.position.selected : null;
      } else {
        current.position.selected = null;
      }
      renderPanel();
    });
  }

  function selectAmbiguousPosition(symbol, positionId) {
    const row = rowState.get(symbol);
    if (!row) return;
    const found = row.position.matches.find((m) => m.position_id === positionId);
    if (!found) return; // fail-closed: nunca selecciona algo que no está en la lista verificada
    row.position.selected = found;
    row.position.orders = { loading: false, list: [], error: null };
    renderPanel();
  }

  function refreshOrders(symbol) {
    const row = rowState.get(symbol);
    if (!row || !row.position.selected) return;
    const positionId = row.position.selected.position_id;
    const epochAtRequest = currentEpoch;
    row.position.orders = { loading: true, list: row.position.orders.list, error: null };
    renderPanel();
    pmRequest("list_orders", { position_id: positionId }).then((result) => {
      if (epochAtRequest !== currentEpoch) return;
      const current = rowState.get(symbol);
      if (!current || !current.position.selected || current.position.selected.position_id !== positionId) return;
      if (!result.ok) {
        current.position.orders = { loading: false, list: [], error: describeApiError(result) };
      } else {
        current.position.orders = { loading: false, list: result.body.orders, error: null };
      }
      renderPanel();
    });
  }

  // -----------------------------------------------------------------
  // DOM helpers -- SIEMPRE createElement/textContent, NUNCA innerHTML
  // con strings interpolados (evita cualquier riesgo de inyección
  // desde datos del backend o de la propia página de Robinhood).
  // -----------------------------------------------------------------

  function el(tag, opts, children) {
    const node = document.createElement(tag);
    opts = opts || {};
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.title) node.title = opts.title;
    if (opts.style) node.style.cssText = opts.style;
    if (opts.onClick) node.addEventListener("click", opts.onClick);
    if (opts.onChange) node.addEventListener("change", opts.onChange);
    if (opts.onInput) node.addEventListener("input", opts.onInput);
    if (opts.type) node.type = opts.type;
    if (opts.value !== undefined) node.value = opts.value;
    if (opts.placeholder) node.placeholder = opts.placeholder;
    if (opts.disabled) node.disabled = true;
    if (opts.name) node.name = opts.name;
    (children || []).forEach((c) => {
      if (c) node.appendChild(c);
    });
    return node;
  }

  function label(t, extraStyle) {
    return el("div", { text: t, style: `font-weight:600;opacity:.85;margin-top:6px;${extraStyle || ""}` });
  }

  function badge(t, kind) {
    const colors = { info: "#2c5aa0", warn: "#a0662c", danger: "#a02c2c", ok: "#2ca05a", neutral: "#555" };
    return el("span", {
      text: t,
      style: `display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;margin-right:4px;background:${colors[kind] || colors.neutral};color:#fff;`,
    });
  }

  function field(labelText, inputNode) {
    return el("div", { style: "margin:4px 0;" }, [el("div", { text: labelText, style: "font-size:10px;opacity:.7;" }), inputNode]);
  }

  function textInput(value, onInput, placeholder) {
    return el("input", {
      type: "text",
      value: value ?? "",
      placeholder,
      onInput: (e) => onInput(e.target.value),
      style: "width:100%;box-sizing:border-box;background:#1c1f26;color:#f2f2f2;border:1px solid #333;border-radius:4px;padding:3px 5px;",
    });
  }

  function select(options, value, onChange) {
    const node = el("select", {
      onChange: (e) => onChange(e.target.value),
      style: "width:100%;background:#1c1f26;color:#f2f2f2;border:1px solid #333;border-radius:4px;padding:3px;",
    });
    options.forEach((opt) => {
      const optNode = el("option", { text: opt, value: opt });
      if (opt === value) optNode.selected = true;
      node.appendChild(optNode);
    });
    return node;
  }

  function button(t, onClick, opts) {
    opts = opts || {};
    return el("button", {
      text: t,
      onClick,
      disabled: opts.disabled,
      style:
        "margin:3px 4px 3px 0;padding:3px 8px;border-radius:4px;border:1px solid #444;cursor:pointer;" +
        `background:${opts.disabled ? "#2a2d33" : opts.danger ? "#5a2c2c" : "#2c3e5a"};color:#f2f2f2;`,
    });
  }

  // -----------------------------------------------------------------
  // Render: MARKET ANALYSIS (preservado tal cual) + POSITION MANAGEMENT
  // -----------------------------------------------------------------

  function ensurePanel() {
    let panel = document.getElementById("pme-robinhood-bridge-panel");
    if (panel) return panel;
    panel = document.createElement("div");
    panel.id = "pme-robinhood-bridge-panel";
    panel.style.cssText = [
      "position:fixed",
      "top:16px",
      "right:16px",
      "z-index:2147483647",
      "background:#111318",
      "color:#f2f2f2",
      "font-family:ui-monospace,SFMono-Regular,Menlo,monospace",
      "font-size:12px",
      "padding:10px 12px",
      "border-radius:8px",
      "width:360px",
      "max-height:85vh",
      "overflow:auto",
      "box-shadow:0 4px 16px rgba(0,0,0,.45)",
      "line-height:1.45",
    ].join(";");
    document.documentElement.appendChild(panel);
    return panel;
  }

  function renderPanel() {
    const panel = ensurePanel();
    panel.textContent = "";
    panel.appendChild(el("div", { text: "Prediction Market Engine", style: "font-weight:700;margin-bottom:6px;" }));
    for (const [symbol, row] of rowState.entries()) {
      panel.appendChild(renderRow(symbol, row));
    }
  }

  function renderRow(symbol, row) {
    const container = el("div", { style: "margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #2a2d33;" });

    // --- MARKET ANALYSIS (sección existente, sin cambios de contenido) ---
    container.appendChild(badge("MARKET ANALYSIS", "info"));
    container.appendChild(
      el("div", { text: row.analysisText ?? `${symbol}\n  cargando...`, style: "white-space:pre-wrap;margin:4px 0 8px 0;" })
    );

    // --- POSITION MANAGEMENT (Tramo 3) ---
    container.appendChild(badge("POSITION MANAGEMENT", "ok"));
    container.appendChild(renderPositionSection(symbol, row));

    return container;
  }

  function renderPositionSection(symbol, row) {
    const box = el("div", { style: "margin-top:4px;" });
    const pos = row.position;

    if (!row.kalshiTicker) {
      box.appendChild(el("div", { text: "(waiting for market analysis to resolve)", style: "opacity:.6;" }));
      return box;
    }
    if (pos.phase === "loading" && pos.selected) {
      // No se borra el último estado válido solo porque hay un refresh
      // en curso -- se sigue mostrando la tarjeta (y sus botones) con un
      // indicador de "updating…" hasta que llegue la respuesta nueva.
      box.appendChild(el("div", { text: "updating…", style: "opacity:.6;font-size:11px;" }));
      box.appendChild(renderPositionCard(symbol, row));
      return box;
    }
    if (pos.phase === "idle" || pos.phase === "loading") {
      box.appendChild(el("div", { text: "loading position…", style: "opacity:.7;" }));
      return box;
    }
    if (pos.phase === "error") {
      box.appendChild(el("div", { text: pos.error, style: "color:#e08080;" }));
      box.appendChild(button("Retry", () => refreshPositionSection(symbol)));
      return box;
    }
    if (pos.phase === "none") {
      box.appendChild(el("div", { text: "No position registered", style: "font-weight:600;" }));
      box.appendChild(renderCreateForm(symbol, row));
      return box;
    }
    if (pos.phase === "ambiguous" && !pos.selected) {
      box.appendChild(
        el("div", {
          text: `NEEDS_REVIEW: ${pos.matches.length} positions match this ticker -- select one explicitly (never auto-selected):`,
          style: "color:#e0c080;font-weight:600;",
        })
      );
      pos.matches.forEach((m) => {
        box.appendChild(
          button(`${m.side} · ${m.status} · ${m.position_id.slice(0, 12)}…`, () => selectAmbiguousPosition(symbol, m.position_id))
        );
      });
      return box;
    }

    // "single" o "ambiguous"-ya-seleccionada: mostrar la Position elegida.
    box.appendChild(renderPositionCard(symbol, row));
    return box;
  }

  function renderCreateForm(symbol, row) {
    if (!row.position.createForm) {
      const wrapper = el("div", {});
      wrapper.appendChild(
        button("Create Position", () => {
          // Key de idempotencia ESTABLE para esta intención de creación
          // -- generada UNA vez (ensureIntentId es no-op si ya existe),
          // reutilizada en todo retry/doble-click/reopen mientras el
          // usuario no confirme que quiere iniciar una intención
          // consciente nueva (no hay ningún flujo que la regenere salvo
          // que cambie el evento/epoch, lo que limpia toda la fila).
          ensureIntentId(row.position, "createIntentId");
          row.position.createForm = { side: null, submitting: false, error: null };
          renderPanel();
        })
      );
      return wrapper;
    }

    const form = row.position.createForm;
    const box = el("div", { style: "border:1px solid #333;border-radius:6px;padding:6px;margin-top:4px;" });
    box.appendChild(el("div", { text: `Ticker: ${row.kalshiTicker}`, style: "font-size:11px;" }));
    box.appendChild(el("div", { text: "Source: MANUAL (no verified model_opportunity_id available here)", style: "font-size:11px;opacity:.75;" }));
    box.appendChild(label("Side (required, no default):"));
    const sideRow = el("div", {});
    ["YES", "NO"].forEach((s) => {
      sideRow.appendChild(
        button(s, () => {
          form.side = s;
          renderPanel();
        }, { disabled: form.submitting })
      );
    });
    box.appendChild(sideRow);
    box.appendChild(el("div", { text: `Selected side: ${form.side ?? "(none yet)"}`, style: "font-size:11px;margin:3px 0;" }));
    box.appendChild(
      el("div", {
        text: `This will create: MANUAL position for ${row.kalshiTicker}, side=${form.side ?? "?"}. This does not mean any contracts were purchased.`,
        style: "font-size:11px;opacity:.85;margin:4px 0;",
      })
    );
    if (form.error) box.appendChild(el("div", { text: form.error, style: "color:#e08080;font-size:11px;" }));

    const confirmBtn = button(
      "Confirm Create",
      () => {
        if (!form.side || form.submitting) return;
        form.submitting = true;
        form.error = null;
        renderPanel();
        pmRequest("create_position", {
          body: {
            idempotency_key: row.position.createIntentId,
            kalshi_ticker: row.kalshiTicker,
            sport: row.sportDomain,
            side: form.side,
            source: "MANUAL",
          },
        }).then((result) => {
          form.submitting = false;
          if (!result.ok) {
            form.error = describeApiError(result);
            renderPanel();
            return;
          }
          row.position.createForm = null;
          refreshPositionSection(symbol);
        });
      },
      { disabled: !form.side || form.submitting }
    );
    box.appendChild(confirmBtn);
    box.appendChild(button("Cancel", () => { row.position.createForm = null; renderPanel(); }, { disabled: form.submitting }));
    return box;
  }

  function renderPositionCard(symbol, row) {
    const p = row.position.selected;
    const box = el("div", {});

    const confirmed = isCapitalRecoveryConfirmed(p.status, p.total_capital_at_risk_fee_status, p.realized_net_proceeds_fee_status);

    box.appendChild(el("div", { text: `${p.side} · ${p.source}`, style: "font-weight:600;" }));
    box.appendChild(el("div", { text: `status: ${p.status}${p.blocked_by_unknown_order ? " (BLOCKED: unresolved UNKNOWN order)" : ""}` }));
    if (p.status === "CAPITAL_RECOVERED") {
      box.appendChild(badge(confirmed ? "CONFIRMED" : "PROVISIONAL", confirmed ? "ok" : "warn"));
    }
    box.appendChild(el("div", { text: `open contracts: ${p.open_contracts}   buy qty: ${p.total_buy_qty}   sell qty: ${p.total_sell_qty}` }));
    box.appendChild(el("div", { text: `capital at risk: ${formatCentsLabel(p.total_capital_at_risk_cents)} (fee: ${p.total_capital_at_risk_fee_status})` }));
    box.appendChild(el("div", { text: `net proceeds recovered: ${formatCentsLabel(p.realized_net_proceeds_cents)} (fee: ${p.realized_net_proceeds_fee_status})` }));
    box.appendChild(el("div", { text: `capital remaining: ${formatCentsLabel(p.capital_remaining_cents)}` }));
    box.appendChild(el("div", { text: `version: ${p.version}   position_id: ${p.position_id.slice(0, 16)}…`, style: "font-size:10px;opacity:.6;" }));

    const actions = el("div", { style: "margin-top:4px;" });
    actions.appendChild(button("Refresh", () => refreshPositionSection(symbol)));
    actions.appendChild(button("Register Fill", () => { row.position.fillForm = row.position.fillForm || newFillFormState(); renderPanel(); }));
    actions.appendChild(button("Calculate Recovery Plan", () => { row.position.planForm = row.position.planForm || newPlanFormState(); renderPanel(); }));
    actions.appendChild(button("Prepare Exit Order", () => { row.position.exitForm = row.position.exitForm || newExitFormState(); renderPanel(); }));
    actions.appendChild(button("Show Orders", () => refreshOrders(symbol)));
    box.appendChild(actions);

    if (row.position.fillForm) box.appendChild(renderFillForm(symbol, row));
    if (row.position.planForm) box.appendChild(renderPlanForm(symbol, row));
    if (row.position.exitForm) box.appendChild(renderExitForm(symbol, row));
    box.appendChild(renderOrdersList(symbol, row));

    return box;
  }

  // --- Register Fill ------------------------------------------------

  function newFillFormState() {
    const state = { action: "BUY", qty: "", price: "", feeStatus: "ESTIMATED", feeCents: "", submitting: false, error: null, lastResult: null };
    ensureIntentId(state); // key ESTABLE mientras el formulario esté abierto -- ver position_logic.js
    return state;
  }

  function renderFillForm(symbol, row) {
    const form = row.position.fillForm;
    const box = el("div", { style: "border:1px solid #333;border-radius:6px;padding:6px;margin-top:6px;" });
    box.appendChild(badge("OBSERVED", "warn"));
    box.appendChild(
      el("div", {
        text: "Registering a fill records what already happened in Robinhood. It does not place an order.",
        style: "font-size:11px;opacity:.9;margin:3px 0;",
      })
    );

    box.appendChild(field("Action", select(["BUY", "SELL"], form.action, (v) => { form.action = v; renderPanel(); })));
    box.appendChild(field("Quantity", textInput(form.qty, (v) => (form.qty = v), "e.g. 19")));
    box.appendChild(field("Actual fill price (cents)", textInput(form.price, (v) => (form.price = v), "e.g. 50")));
    box.appendChild(field("Fee status", select(["KNOWN", "ESTIMATED", "UNKNOWN"], form.feeStatus, (v) => { form.feeStatus = v; renderPanel(); })));
    if (form.feeStatus !== "UNKNOWN") {
      box.appendChild(field("Fee (cents, exact decimal)", textInput(form.feeCents, (v) => (form.feeCents = v), "e.g. 0 or 6.93")));
    }

    if (form.error) box.appendChild(el("div", { text: form.error, style: "color:#e08080;font-size:11px;margin:3px 0;" }));
    if (form.lastResult) box.appendChild(el("div", { text: "Fill registered.", style: "color:#8ad08a;font-size:11px;" }));

    box.appendChild(
      button(
        "Register",
        () => submitFill(symbol, row),
        { disabled: form.submitting }
      )
    );
    box.appendChild(
      button("New fill", () => { row.position.fillForm = newFillFormState(); renderPanel(); }, { disabled: form.submitting })
    );
    box.appendChild(button("Close", () => { row.position.fillForm = null; renderPanel(); }, { disabled: form.submitting }));
    return box;
  }

  function submitFill(symbol, row) {
    const form = row.position.fillForm;
    if (form.submitting) return; // guarda de un solo vuelo -- doble click no dispara un segundo submit

    const qty = Number(form.qty);
    const price = Number(form.price);
    const feeInput = { status: form.feeStatus, cents: form.feeStatus === "UNKNOWN" ? null : form.feeCents };
    const feeCheck = validateFeeInput(feeInput);
    if (!Number.isInteger(qty) || qty <= 0) { form.error = "Quantity must be a positive integer."; renderPanel(); return; }
    if (!Number.isInteger(price) || price < 0) { form.error = "Price must be a non-negative integer number of cents."; renderPanel(); return; }
    if (!feeCheck.valid) { form.error = feeCheck.error; renderPanel(); return; }

    form.submitting = true;
    form.error = null;
    renderPanel();

    const positionId = row.position.selected.position_id;
    const intentId = ensureIntentId(form); // MISMA key en todo reintento de esta misma intención

    pmRequest("list_orders", { position_id: positionId }).then((ordersResult) => {
      if (!ordersResult.ok) {
        form.submitting = false;
        form.error = describeApiError(ordersResult);
        renderPanel();
        return;
      }
      const nonTerminal = ["PLANNED", "SUBMITTED", "PENDING", "PARTIALLY_FILLED", "UNKNOWN"];
      const existing = ordersResult.body.orders.find((o) => nonTerminal.includes(o.status));

      const proceedWithOrder = (orderId, orderVersion) => {
        pmRequest("register_fill", {
          position_id: positionId,
          body: {
            fill_id: `${intentId}-fill`,
            order_id: orderId,
            action: form.action,
            qty,
            actual_fill_price_cents: price,
            fee: feeInput,
            filled_at: new Date().toISOString(),
            expected_order_version: orderVersion,
          },
        }).then((fillResult) => {
          form.submitting = false;
          if (!fillResult.ok) {
            form.error = describeApiError(fillResult);
            // 409 (stale/conflict): NUNCA se reintenta silenciosamente --
            // se refresca el estado real para que el usuario lo revise.
            if (fillResult.status === 409) {
              refreshPositionSection(symbol);
              refreshOrders(symbol);
            }
            renderPanel();
            return;
          }
          form.lastResult = fillResult.body;
          // Tras un fill exitoso: refrescar Position, invalidar un plan
          // previo (las cifras de capital cambiaron -- nunca se
          // recalcula solo, se limpia y se ofrece recalcular a propósito).
          if (row.position.planForm) row.position.planForm.lastPlan = null;
          refreshPositionSection(symbol);
          refreshOrders(symbol);
        });
      };

      if (existing) {
        if (existing.action !== form.action || existing.requested_qty - existing.confirmed_filled_qty < qty) {
          form.submitting = false;
          form.error = `An unresolved order already exists (action=${existing.action}, status=${existing.status}). Resolve it via "Update observed status" before registering a new fill.`;
          renderPanel();
          return;
        }
        proceedWithOrder(existing.order_id, existing.version);
        return;
      }

      pmRequest("create_order", {
        position_id: positionId,
        body: {
          order_id: `${intentId}-order`,
          intent_id: `${intentId}-order`,
          action: form.action,
          requested_qty: qty,
          planned_target_price_cents: price,
        },
      }).then((orderResult) => {
        if (!orderResult.ok) {
          form.submitting = false;
          form.error = describeApiError(orderResult);
          renderPanel();
          return;
        }
        proceedWithOrder(orderResult.body.order_id, orderResult.body.version);
      });
    });
  }

  // --- Calculate Recovery Plan ---------------------------------------

  function newPlanFormState() {
    return { targetPrice: "", feeStatus: "ESTIMATED", feeCents: "", observedPrice: "", submitting: false, error: null, lastPlan: null };
  }

  function renderPlanForm(symbol, row) {
    const form = row.position.planForm;
    const box = el("div", { style: "border:1px solid #333;border-radius:6px;padding:6px;margin-top:6px;" });
    box.appendChild(badge("ADVISORY PLAN", "info"));

    box.appendChild(field("Target price (cents) -- explicit, never auto-derived", textInput(form.targetPrice, (v) => (form.targetPrice = v), "e.g. 63")));
    box.appendChild(
      field(
        "Observed price (cents) -- optional reference only, kept separate from Target price",
        textInput(form.observedPrice, (v) => (form.observedPrice = v), "optional")
      )
    );
    box.appendChild(field("Fee assumption status", select(["KNOWN", "ESTIMATED", "UNKNOWN"], form.feeStatus, (v) => { form.feeStatus = v; renderPanel(); })));
    if (form.feeStatus !== "UNKNOWN") {
      box.appendChild(field("Fee assumption (cents)", textInput(form.feeCents, (v) => (form.feeCents = v), "e.g. 0")));
    }
    if (form.error) box.appendChild(el("div", { text: form.error, style: "color:#e08080;font-size:11px;" }));

    if (form.lastPlan) box.appendChild(renderPlanResult(form.lastPlan));

    box.appendChild(button("Calculate Recovery Plan", () => submitPlan(symbol, row), { disabled: form.submitting }));
    box.appendChild(button("Close", () => { row.position.planForm = null; renderPanel(); }, { disabled: form.submitting }));
    return box;
  }

  function renderPlanResult(plan) {
    const box = el("div", { style: "margin:4px 0;padding:4px;background:#181b22;border-radius:4px;" });
    if (plan.contracts_to_sell === 0) {
      box.appendChild(el("div", { text: "Capital recovery complete", style: "color:#8ad08a;font-weight:600;" }));
    } else {
      box.appendChild(el("div", { text: `contracts to sell (recovery qty): ${plan.contracts_to_sell}` }));
      box.appendChild(el("div", { text: `projected runner: ${plan.contracts_remaining_after}` }));
    }
    box.appendChild(el("div", { text: `capital remaining: ${formatCentsLabel(plan.capital_remaining_cents)}` }));
    box.appendChild(el("div", { text: `projected net proceeds: ${formatCentsLabel(plan.net_proceeds_cents)}` }));
    box.appendChild(el("div", { text: `achievability: ${plan.achievability}` }));
    box.appendChild(badge(plan.provisional ? "PROVISIONAL" : "CONFIRMED", plan.provisional ? "warn" : "ok"));
    if (plan.provisional && plan.provisional_reason) {
      box.appendChild(el("div", { text: plan.provisional_reason, style: "font-size:11px;opacity:.85;" }));
    }
    box.appendChild(el("div", { text: `fee status used: ${plan.fee_assumption?.status}`, style: "font-size:11px;" }));
    if (plan.observed_market_price_cents !== null && plan.observed_market_price_cents !== undefined) {
      box.appendChild(el("div", { text: `Observed price (reference only): ${plan.observed_market_price_cents}c`, style: "font-size:11px;opacity:.7;" }));
    }
    return box;
  }

  function submitPlan(symbol, row) {
    const form = row.position.planForm;
    if (form.submitting) return;

    const targetPrice = Number(form.targetPrice);
    const feeInput = { status: form.feeStatus, cents: form.feeStatus === "UNKNOWN" ? null : form.feeCents };
    const feeCheck = validateFeeInput(feeInput);
    if (!Number.isInteger(targetPrice) || targetPrice < 0) { form.error = "Target price must be a non-negative integer number of cents."; renderPanel(); return; }
    if (!feeCheck.valid) { form.error = feeCheck.error; renderPanel(); return; }
    const observedPrice = form.observedPrice ? Number(form.observedPrice) : null;
    if (observedPrice !== null && (!Number.isInteger(observedPrice) || observedPrice < 0)) {
      form.error = "Observed price must be a non-negative integer number of cents, or left blank.";
      renderPanel();
      return;
    }

    form.submitting = true;
    form.error = null;
    renderPanel();

    // A diferencia de fillForm/exitForm: cada click explícito en
    // "Calculate" genera un plan_id NUEVO (guardado solo por el
    // single-flight lock de `submitting`, no por una key estable entre
    // clicks) -- recalcular con inputs distintos es una acción
    // consciente normal, y el backend rechaza CUALQUIER reutilización
    // de plan_id sin importar si el payload coincide (no es
    // "mismo payload = no-op" como fills/orders). Ver informe de
    // entrega, sección I.
    const planId = generateUuid();

    pmRequest("compute_plan", {
      position_id: row.position.selected.position_id,
      body: {
        plan_id: planId,
        planned_target_price_cents: targetPrice,
        fee_assumption: feeInput,
        observed_market_price_cents: observedPrice,
      },
    }).then((result) => {
      form.submitting = false;
      if (!result.ok) {
        form.error = describeApiError(result);
        renderPanel();
        return;
      }
      form.lastPlan = result.body;
      renderPanel();
    });
  }

  // --- Prepare Exit Order --------------------------------------------

  function newExitFormState() {
    const state = { qty: "", price: "", submitting: false, error: null, lastOrder: null };
    ensureIntentId(state);
    return state;
  }

  function renderExitForm(symbol, row) {
    const form = row.position.exitForm;
    const p = row.position.selected;
    const box = el("div", { style: "border:1px solid #333;border-radius:6px;padding:6px;margin-top:6px;" });
    box.appendChild(badge("LOCAL PREPARED ORDER", "warn"));

    box.appendChild(field("SELL quantity", textInput(form.qty, (v) => (form.qty = v), `<= ${p.open_contracts}`)));
    box.appendChild(field("Limit price (cents)", textInput(form.price, (v) => (form.price = v), "e.g. 63")));

    const remaining = contractsRemainingAfterExit(p.open_contracts, Number(form.qty));
    box.appendChild(el("div", { text: `Contracts that would remain: ${remaining === null ? "n/a (invalid quantity)" : remaining}`, style: "font-size:11px;" }));
    box.appendChild(
      el("div", {
        text: "This does NOT submit anything to Robinhood. Prepared locally — not submitted to Robinhood.",
        style: "font-size:11px;color:#e0c080;margin:3px 0;",
      })
    );

    if (form.error) box.appendChild(el("div", { text: form.error, style: "color:#e08080;font-size:11px;" }));
    if (form.lastOrder) {
      box.appendChild(el("div", { text: `Order status: ${form.lastOrder.status}`, style: "color:#8ad08a;" }));
      box.appendChild(el("div", { text: "Prepared locally — not submitted to Robinhood.", style: "font-size:11px;opacity:.85;" }));
    }

    box.appendChild(
      button(
        "Prepare Locally",
        () => submitExitOrder(symbol, row),
        { disabled: form.submitting || remaining === null }
      )
    );
    box.appendChild(button("Close", () => { row.position.exitForm = null; renderPanel(); }, { disabled: form.submitting }));
    return box;
  }

  function submitExitOrder(symbol, row) {
    const form = row.position.exitForm;
    if (form.submitting) return;
    const qty = Number(form.qty);
    const price = Number(form.price);
    if (!Number.isInteger(qty) || qty <= 0) { form.error = "Quantity must be a positive integer."; renderPanel(); return; }
    if (!Number.isInteger(price) || price < 0) { form.error = "Price must be a non-negative integer number of cents."; renderPanel(); return; }

    form.submitting = true;
    form.error = null;
    renderPanel();

    const intentId = ensureIntentId(form);
    pmRequest("create_order", {
      position_id: row.position.selected.position_id,
      body: { order_id: `${intentId}-order`, intent_id: `${intentId}-order`, action: "SELL", requested_qty: qty, planned_target_price_cents: price },
    }).then((result) => {
      form.submitting = false;
      if (!result.ok) {
        form.error = describeApiError(result);
        if (result.status === 409) refreshOrders(symbol);
        renderPanel();
        return;
      }
      form.lastOrder = result.body;
      refreshOrders(symbol);
      renderPanel();
    });
  }

  // --- Orders list + Update observed status ---------------------------

  function renderOrdersList(symbol, row) {
    const box = el("div", { style: "margin-top:6px;" });
    const orders = row.position.orders;
    if (orders.loading) {
      box.appendChild(el("div", { text: "loading orders…", style: "opacity:.7;" }));
      return box;
    }
    if (orders.error) {
      box.appendChild(el("div", { text: orders.error, style: "color:#e08080;font-size:11px;" }));
      return box;
    }
    if (orders.list.length === 0) return box;

    box.appendChild(badge("OBSERVED BROKER STATUS", "neutral"));
    orders.list.forEach((o) => {
      const row2 = el("div", { style: "border-top:1px solid #262932;padding:3px 0;font-size:11px;" });
      row2.appendChild(
        el("div", { text: `${o.action} ${o.requested_qty} @ ${o.planned_target_price_cents}c — status: ${o.status} (filled ${o.confirmed_filled_qty}/${o.requested_qty}, v${o.version})` })
      );
      if (o.status === "PLANNED") {
        row2.appendChild(el("div", { text: "Prepared locally — not submitted to Robinhood.", style: "opacity:.75;" }));
      }
      row2.appendChild(
        button("Update observed status", () => {
          row.position.reconcileOpenFor = row.position.reconcileOpenFor === o.order_id ? null : o.order_id;
          row.position.reconcileForm = { newStatus: RECONCILE_TARGET_STATUSES.find((s) => s !== o.status) ?? RECONCILE_TARGET_STATUSES[0], submitting: false, error: null };
          renderPanel();
        })
      );
      if (row.position.reconcileOpenFor === o.order_id) {
        row2.appendChild(renderReconcileForm(symbol, row, o));
      }
      box.appendChild(row2);
    });
    return box;
  }

  function renderReconcileForm(symbol, row, order) {
    const form = row.position.reconcileForm;
    const box = el("div", { style: "margin:3px 0;padding:4px;background:#181b22;border-radius:4px;" });
    box.appendChild(
      el("div", {
        text: "To record fills, use Register Fill — this only updates administrative status.",
        style: "font-size:10px;opacity:.7;",
      })
    );
    box.appendChild(
      field("New observed status", select(RECONCILE_TARGET_STATUSES.filter((s) => s !== order.status), form.newStatus, (v) => { form.newStatus = v; renderPanel(); }))
    );
    if (form.error) box.appendChild(el("div", { text: form.error, style: "color:#e08080;font-size:11px;" }));
    box.appendChild(
      button(
        "Confirm",
        () => {
          if (form.submitting) return;
          form.submitting = true;
          form.error = null;
          renderPanel();
          pmRequest("update_order", {
            position_id: row.position.selected.position_id,
            order_id: order.order_id,
            body: { expected_version: order.version, new_status: form.newStatus, reason: "MANUAL_RECONCILIATION" },
          }).then((result) => {
            form.submitting = false;
            if (!result.ok) {
              form.error = describeApiError(result);
              renderPanel();
              return;
            }
            row.position.reconcileOpenFor = null;
            refreshOrders(symbol);
          });
        },
        { disabled: form.submitting }
      )
    );
    box.appendChild(button("Cancel", () => { row.position.reconcileOpenFor = null; renderPanel(); }, { disabled: form.submitting }));
    return box;
  }

  // -----------------------------------------------------------------
  // Flujo de análisis existente -- SIN cambios de comportamiento,
  // salvo que ahora también dispara refreshPositionSection() una vez
  // conocido el ticker mapeado.
  // -----------------------------------------------------------------

  function formatAnalysis(symbol, mapping, analysis) {
    return (
      `${symbol}\n` +
      `  kalshi: ${mapping.kalshi_ticker} (${mapping.strategy})\n` +
      `  ${analysis.participant_a ?? "?"} vs ${analysis.participant_b ?? "?"}\n` +
      `  recomendacion: ${analysis.recommendation}\n` +
      `  edge: ${analysis.edge ?? "n/d"}  ev_neto: ${analysis.ev_neto ?? "n/d"}\n` +
      `  confianza: ${analysis.uncertainty?.aggregate_confidence ?? "n/d"}`
    );
  }

  function setRow(symbol, text) {
    ensureRow(symbol).analysisText = text;
    renderPanel();
  }

  function requestAnalysis(symbol, gameStart, netReqId, sportBucket) {
    const analyzeReqId = newRequestId();
    const epochAtRequest = currentEpoch;
    let settled = false;

    const sportLabel = sportBucket ?? "desconocido";
    const timeoutMs = RESPONSE_TIMEOUT_MS_BY_SPORT[sportBucket] ?? DEFAULT_RESPONSE_TIMEOUT_MS;
    if (!sportBucket) {
      console.warn(
        `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} deporte no identificado -- ` +
          `usando timeout por defecto de ${DEFAULT_RESPONSE_TIMEOUT_MS}ms`
      );
    }

    console.info(
      `${LOG_PREFIX} analyzeReqId=${analyzeReqId} netReqId=${netReqId} epoch=${epochAtRequest} ` +
        `symbol=${symbol} gameStart=${gameStart} deporte=${sportLabel} timeoutMs=${timeoutMs} -- enviando a background.js`
    );
    setRow(symbol, `${symbol}\n  mapeando... (analyzeReqId=${analyzeReqId})`);

    const timeoutHandle = setTimeout(() => {
      if (settled) return;
      settled = true;
      console.warn(
        `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} TIMEOUT del lado content_script ` +
          `(${timeoutMs}ms sin respuesta de background.js, deporte=${sportLabel})`
      );
      if (epochAtRequest === currentEpoch) {
        setRow(
          symbol,
          `${symbol}\n  error: timeout de extensión -- deporte=${sportLabel}, tiempo_esperado=${timeoutMs}ms, ` +
            `symbol=${symbol}, endpoint=background.js (sin respuesta)`
        );
      } else {
        console.info(
          `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} timeout de epoch obsoleto ` +
            `(${epochAtRequest} != ${currentEpoch}) -- no se pinta, no se sobrescribe la fila actual`
        );
      }
    }, timeoutMs);

    try {
      chrome.runtime.sendMessage({ type: "pme-analyze", analyzeReqId, symbol, gameStart, sportBucket }, (result) => {
        if (settled) return; // ya se marcó timeout -- respuesta tardía, se ignora para no pisar el error
        settled = true;
        clearTimeout(timeoutHandle);

        if (chrome.runtime.lastError) {
          console.error(
            `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} runtime.lastError:`,
            chrome.runtime.lastError.message
          );
          if (epochAtRequest === currentEpoch) {
            setRow(symbol, `${symbol}\n  error: ${chrome.runtime.lastError.message}`);
          }
          return;
        }

        if (epochAtRequest !== currentEpoch) {
          console.info(
            `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} respuesta de epoch obsoleto ` +
              `(${epochAtRequest} != ${currentEpoch}) -- descartada, no se pinta`
          );
          return;
        }

        if (result?.error) {
          console.error(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} error:`, result.error);
          setRow(symbol, `${symbol}\n  error: ${result.error}`);
          return;
        }

        console.info(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} OK kalshi_ticker=${result.mapping?.kalshi_ticker}`);
        setRow(symbol, formatAnalysis(symbol, result.mapping, result.analysis));

        // Tramo 3: ahora que el ticker Kalshi es conocido, resolver la
        // sección de Position Management asociada -- fail-closed (nunca
        // selecciona sola entre 2+ candidatas), nunca crea nada
        // automáticamente.
        const row = ensureRow(symbol);
        row.kalshiTicker = result.mapping.kalshi_ticker;
        row.sportDomain = sportBucketToDomain(sportBucket);
        refreshPositionSection(symbol);
      });
    } catch (err) {
      settled = true;
      clearTimeout(timeoutHandle);
      console.error(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} excepción enviando el mensaje:`, err);
      setRow(symbol, `${symbol}\n  error: no se pudo contactar a la extensión (${err?.message ?? err})`);
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.source !== "pme-robinhood-bridge") return;

    console.debug(`${LOG_PREFIX} netReqId=${msg.netReqId} recibido de page_hook.js, url=${msg.url}`);

    if (EVENT_STATE_RE.test(msg.url)) {
      const eventId = extractEventId(msg.body);
      const categoryBucket = CATEGORY_SPORT_BUCKET[extractCategory(msg.body)] ?? null;
      const gameStart = extractGameStart(msg.body);
      if (eventId && eventId !== currentEventId) {
        resetForNewEvent(eventId, categoryBucket, gameStart);
      } else {
        if (categoryBucket) currentCategoryBucket = categoryBucket;
        if (gameStart) currentGameStart = gameStart;
      }
      return;
    }

    if (QUOTES_RE.test(msg.url)) {
      for (const symbol of extractSymbols(msg.body)) {
        if (seenSymbols.has(symbol)) continue;

        const bucket = symbolSportBucket(symbol);
        if (currentCategoryBucket && bucket && bucket !== currentCategoryBucket) {
          console.warn(
            `${LOG_PREFIX} netReqId=${msg.netReqId} symbol=${symbol} (bucket=${bucket}) NO coincide con el ` +
              `evento activo (eventId=${currentEventId}, categoria=${currentCategoryBucket}) -- descartado, ` +
              `nunca se llama a /map/robinhood para este symbol`
          );
          continue;
        }

        seenSymbols.add(symbol);
        requestAnalysis(symbol, currentGameStart, msg.netReqId, bucket);
      }
    }
  });
})();
