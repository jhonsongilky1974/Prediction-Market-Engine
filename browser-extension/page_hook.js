// Corre en el MAIN world de la pestaña de Robinhood (declarado en
// manifest.json) -- es el único lugar donde se puede interceptar el
// `fetch`/XHR que la propia SPA ya dispara hacia
// `event_state`/`quotes/v1` (ver ROBINHOOD_KALSHI_MAPPER_SPEC.md §1).
// Un content script normal corre en un mundo aislado y no ve esas
// llamadas. No se repite ningún fetch propio -- solo se lee la
// respuesta que la SPA ya obtuvo, con las cookies de sesión del propio
// usuario.
//
// IMPORTANTE (auditoría 2026-08-06, ver CONTINUITY.md): este hook
// intercepta CUALQUIER respuesta que matchee las URLs de abajo, en
// TODA la pestaña -- no solo la del evento que el usuario está
// mirando. La SPA hace polling repetido del evento activo (documentado
// en el spec) y puede tener widgets/carruseles con OTROS eventos en la
// misma página, cada uno disparando sus propias llamadas a
// `quotes/v1`. Este archivo NO decide qué es "el evento actual" --
// solo reporta honestamente cada respuesta interceptada con su propio
// `netReqId` para que content_script.js pueda decidir, con contexto
// (categoría del evento activo), si una respuesta es relevante o
// contaminación de otro evento/pestaña. Ver content_script.js.
(() => {
  const EVENT_STATE_RE = /\/prediction-markets\/v1\/event_state/;
  const QUOTES_RE = /\/marketdata\/event\/contract\/quotes\/v1\//;
  const LOG_PREFIX = "[pme:page_hook]";

  function newRequestId() {
    return (crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`);
  }

  function publish(url, body) {
    const netReqId = newRequestId();
    // Log temporal de diagnóstico (auditoría 2026-08-06) -- payload
    // exacto que sale de este hook hacia content_script.js.
    console.debug(`${LOG_PREFIX} netReqId=${netReqId} url=${url} body=`, body);
    window.postMessage({ source: "pme-robinhood-bridge", netReqId, url, body }, "*");
  }

  function urlOf(input) {
    if (typeof input === "string") return input;
    if (input instanceof Request) return input.url;
    return input?.url;
  }

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    const url = urlOf(args[0]);
    if (url && (EVENT_STATE_RE.test(url) || QUOTES_RE.test(url))) {
      response
        .clone()
        .json()
        .then((body) => publish(url, body))
        .catch((err) => console.debug(`${LOG_PREFIX} respuesta no-JSON en ${url}:`, err));
    }
    return response;
  };

  const OriginalXHR = window.XMLHttpRequest;
  function PatchedXHR() {
    const xhr = new OriginalXHR();
    let requestUrl = "";
    const originalOpen = xhr.open;
    xhr.open = function (method, url, ...rest) {
      requestUrl = url;
      return originalOpen.call(xhr, method, url, ...rest);
    };
    xhr.addEventListener("load", () => {
      if (requestUrl && (EVENT_STATE_RE.test(requestUrl) || QUOTES_RE.test(requestUrl))) {
        try {
          publish(requestUrl, JSON.parse(xhr.responseText));
        } catch (err) {
          console.debug(`${LOG_PREFIX} respuesta XHR no-JSON en ${requestUrl}:`, err);
        }
      }
    });
    return xhr;
  }
  PatchedXHR.prototype = OriginalXHR.prototype;
  window.XMLHttpRequest = PatchedXHR;
})();
