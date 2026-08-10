# Puente Robinhood → Kalshi (extensión de navegador)

Implementación mínima de la arquitectura documentada en
`ROBINHOOD_KALSHI_MAPPER_SPEC.md` §5: lee los eventos de Prediction
Markets que la propia SPA de Robinhood ya carga en la pestaña del
usuario, los traduce a un ticker Kalshi vía `POST /map/robinhood` y
muestra el análisis de `GET /analyze/{ticker}` (backend local, Fase 5,
`src/api/main.py`) en un panel inyectado en la página.

No hace scraping de DOM ni repite llamadas a Robinhood: intercepta las
respuestas que la SPA ya obtuvo (mismo origen, cookies de sesión ya
presentes).

## Archivos

- `manifest.json` — MV3. `host_permissions` para `robinhood.com` y
  `127.0.0.1:8000`; dos content scripts (uno en el mundo `MAIN` de la
  página, otro en el mundo aislado por defecto).
- `page_hook.js` (mundo `MAIN`) — parchea `window.fetch`/`XMLHttpRequest`
  para leer las respuestas de `.../prediction-markets/v1/event_state` y
  `.../marketdata/event/contract/quotes/v1/`, y las publica vía
  `window.postMessage`.
- `content_script.js` (mundo aislado) — recibe ese `postMessage`, pide
  el análisis a `background.js` y pinta el panel flotante en la pestaña.
- `background.js` (service worker) — único contexto que llama al
  backend: `POST /map/robinhood` → `GET /analyze/{kalshi_ticker}`.

## Cómo cargarla

1. Levantar el backend local (si no está corriendo):
   ```
   source .venv/bin/activate
   uvicorn src.api.main:app --reload --port 8000
   ```
2. En Chrome, ir a `chrome://extensions`.
3. Activar "Modo de desarrollador" (arriba a la derecha).
4. Clic en "Cargar descomprimida" y seleccionar esta carpeta
   (`browser-extension/`).
5. Abrir un evento real de "Prediction Markets" en `robinhood.com`. El
   panel debería aparecer arriba a la derecha de la pestaña en cuanto la
   SPA cargue las cotizaciones del evento.

## Estado / límites conocidos

- **No probada contra Robinhood en vivo todavía** — implementación
  basada en los endpoints y formatos ya verificados en
  `ROBINHOOD_KALSHI_MAPPER_SPEC.md` §1, pero el hook de red (`fetch` vs
  `XMLHttpRequest`, timing de `document_start`) no se ha confirmado
  contra la SPA real en esta sesión.
- Si `event_state` no trae `gameStart` (ocurre en partidos ya en curso,
  ver spec §1.1), el mapeo sigue funcionando -- solo pierde la señal
  opcional que usa la estrategia 3 (`event_matcher`) del mapeador.
- Sin CORS explícito en el backend: las llamadas salen del *service
  worker* (contexto privilegiado de la extensión, no de la página), que
  con `host_permissions` declarado no está sujeto a la política CORS de
  un fetch de página normal -- si en algún navegador/versión esto no
  aplica, el síntoma sería un error de red visible en el panel.
- Sin tests automatizados (JS) -- verificación es manual, vía
  `chrome://extensions` → "Inspeccionar vistas: service worker" para
  confirmar el `symbol` que sale hacia `/map/robinhood` y la respuesta
  que entra.
