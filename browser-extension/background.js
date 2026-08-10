// Service worker (MV3). Único contexto de la extensión que llama al
// backend local -- content_script.js nunca hace fetch directo al
// backend para no depender de la CSP de la página de Robinhood.
//
// AUDITORÍA 2026-08-06 (1a parte): no había timeout en ninguno de los
// dos fetch -- si el backend (o la red) se colgaba, la promesa de
// mapAndAnalyze() nunca se resolvía ni rechazaba, `sendResponse` nunca
// se llamaba, y el panel quedaba en "mapeando..." para siempre sin
// ningún error visible. Fix: AbortController con timeout explícito en
// cada llamada.
//
// AUDITORÍA 2026-08-06 (2a parte): un timeout único de 15s cortaba un
// /analyze de MLB real (Chicago White Sox vs Boston) que seguía
// procesando en Uvicorn -- medido directo contra el backend real: ese
// mismo ticker tardó ~25.4s (usuario reportó 31-33s en otra corrida).
// Fix: timeout por deporte, derivado del `sportBucket` que
// content_script.js ya calculó a partir del prefijo del `symbol` (la
// misma tabla que usa `_SERIES_TO_SPORT_KEY` en
// src/api/robinhood_mapper.py). Se aplica el mismo presupuesto a
// ambas llamadas (map y analyze) por simplicidad -- map/robinhood es
// uniformemente rápido (~0.2-0.35s medido, ambos deportes) así que en
// la práctica solo importa para /analyze.
const BACKEND_BASE = "http://127.0.0.1:8000";
const LOG_PREFIX = "[pme:background]";

const FETCH_TIMEOUT_MS_BY_SPORT = { baseball: 45000, tennis: 15000 };
const DEFAULT_FETCH_TIMEOUT_MS = FETCH_TIMEOUT_MS_BY_SPORT.baseball; // deporte desconocido -> presupuesto conservador (el mayor), nunca el corto de tenis

function fetchWithTimeout(url, options, timeoutMs, analyzeReqId, label, symbol, sportLabel) {
  const controller = new AbortController();
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);
  const startedAt = Date.now();
  return fetch(url, { ...options, signal: controller.signal })
    .then((response) => {
      console.info(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} ${label} status=${response.status} tiempo=${Date.now() - startedAt}ms`);
      return response;
    })
    .catch((err) => {
      if (err?.name === "AbortError") {
        throw new Error(
          `timeout de backend -- deporte=${sportLabel}, tiempo_esperado=${timeoutMs}ms, symbol=${symbol}, ` +
            `endpoint=${label} (${url})`
        );
      }
      throw err;
    })
    .finally(() => clearTimeout(timeoutHandle));
}

async function mapAndAnalyze(symbol, gameStart, analyzeReqId, tabId, sportBucket) {
  const sportLabel = sportBucket ?? "desconocido";
  const timeoutMs = FETCH_TIMEOUT_MS_BY_SPORT[sportBucket] ?? DEFAULT_FETCH_TIMEOUT_MS;
  if (!sportBucket) {
    console.warn(
      `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} deporte no identificado (sportBucket vacío) -- ` +
        `usando timeout por defecto de ${DEFAULT_FETCH_TIMEOUT_MS}ms`
    );
  }

  console.info(
    `${LOG_PREFIX} analyzeReqId=${analyzeReqId} tabId=${tabId} symbol=${symbol} gameStart=${gameStart} ` +
      `deporte=${sportLabel} timeoutMs=${timeoutMs} -- POST /map/robinhood`
  );

  const mapResponse = await fetchWithTimeout(
    `${BACKEND_BASE}/map/robinhood`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol,
        ...(gameStart ? { game_start: gameStart } : {}),
      }),
    },
    timeoutMs,
    analyzeReqId,
    "POST /map/robinhood",
    symbol,
    sportLabel
  );
  const mapBody = await mapResponse.json();
  console.info(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} respuesta /map/robinhood:`, mapBody);
  if (!mapResponse.ok) {
    throw new Error(`map/robinhood ${mapResponse.status}: ${mapBody?.detail ?? JSON.stringify(mapBody)}`);
  }

  console.info(
    `${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} -- GET /analyze/${mapBody.kalshi_ticker} ` +
      `(strategy=${mapBody.strategy}, sport=${mapBody.sport}, timeoutMs=${timeoutMs})`
  );
  const analyzeResponse = await fetchWithTimeout(
    `${BACKEND_BASE}/analyze/${encodeURIComponent(mapBody.kalshi_ticker)}`,
    {},
    timeoutMs,
    analyzeReqId,
    `GET /analyze/${mapBody.kalshi_ticker}`,
    symbol,
    sportLabel
  );
  const analyzeBody = await analyzeResponse.json();
  console.info(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} symbol=${symbol} respuesta /analyze:`, analyzeBody);
  if (!analyzeResponse.ok) {
    throw new Error(`analyze ${analyzeResponse.status}: ${analyzeBody?.detail ?? JSON.stringify(analyzeBody)}`);
  }

  return { mapping: mapBody, analysis: analyzeBody };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "pme-analyze") return false;

  const { analyzeReqId, symbol, gameStart, sportBucket } = message;
  const tabId = sender?.tab?.id ?? "desconocido";

  // Nunca se reintenta automáticamente aquí -- una sola llamada a
  // mapAndAnalyze por mensaje recibido; si expira o falla, se informa
  // el error y termina, sin volver a llamar al backend por cuenta propia.
  mapAndAnalyze(symbol, gameStart, analyzeReqId, tabId, sportBucket)
    .then((result) => sendResponse(result))
    .catch((err) => {
      console.error(`${LOG_PREFIX} analyzeReqId=${analyzeReqId} tabId=${tabId} symbol=${symbol} FALLO:`, err);
      sendResponse({ error: String(err?.message ?? err) });
    });

  return true; // respuesta asíncrona -- mantiene el canal de sendResponse abierto
});
