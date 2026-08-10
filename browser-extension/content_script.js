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

  let currentEventId = null;
  let currentCategoryBucket = null; // null = sin señal todavía, no se filtra
  let currentGameStart = null;
  let currentEpoch = 0;
  const seenSymbols = new Set();
  const panelRows = new Map(); // symbol -> texto de la fila actual

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
    panelRows.clear();
    renderPanel();
  }

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
      "max-width:340px",
      "max-height:80vh",
      "overflow:auto",
      "box-shadow:0 4px 16px rgba(0,0,0,.45)",
      "white-space:pre-wrap",
      "line-height:1.45",
    ].join(";");
    document.documentElement.appendChild(panel);
    return panel;
  }

  function renderPanel() {
    const panel = ensurePanel();
    const sections = Array.from(panelRows.values());
    panel.textContent = ["Prediction Market Engine", ...sections].join("\n\n");
  }

  function setRow(symbol, text) {
    panelRows.set(symbol, text);
    renderPanel();
  }

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
