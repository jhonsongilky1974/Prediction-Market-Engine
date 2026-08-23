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
  el análisis a `background.js` y pinta el panel flotante en la pestaña
  (sección "Market Analysis" + sección "Position Management").
- `position_logic.js` (mundo aislado, se carga ANTES que
  `content_script.js`) — lógica PURA de Position Management (Fase 6,
  Tramo 3): asociación Position↔ticker fail-closed, estabilidad de
  idempotency keys de UI, validación de formato de fees, helpers de
  formato. Cero dependencias de `chrome.*`/DOM -- por eso es testeable
  fuera del navegador, ver `tests/position_logic.test.js`.
- `background.js` (service worker) — único contexto que llama al
  backend: `POST /map/robinhood` → `GET /analyze/{kalshi_ticker}`, y
  (Tramo 3) el bridge de Position Management (`POSITION_ACTIONS`,
  whitelist cerrado de 8 acciones read/register/prepare/reconcile bajo
  `/positions`, nunca un passthrough de URL/método arbitrario).

## Position Management (Fase 6, Tramo 3)

Sección nueva del panel, bajo "Market Analysis". Estrictamente
human-in-the-loop: la extensión puede consultar/mostrar/calcular,
crear/seleccionar una Position, registrar manualmente fills que el
usuario confirma que YA ocurrieron en Robinhood, calcular un
`PositionPlan` advisory, preparar una Order en estado `PLANNED`
("prepared locally — not submitted to Robinhood") y reconciliar
manualmente el status observado de una Order. **Nunca** ejecuta nada en
Robinhood, nunca hace click/automatiza el DOM del broker, nunca escribe
SQLite directamente -- todo pasa por `browser-extension → FastAPI →
positions_service/repository → SQLite`. Ver `tests/unit/
test_browser_extension_scope.py` (auditoría de scope, corre con
`pytest`) y `tests/position_logic.test.js` (lógica pura, corre con
`node --test`).

Asociación Position↔ticker: 0 coincidencias → "No position registered"
+ acción explícita "Create Position"; exactamente 1 → se muestra
directo; 2+ (posible YES/NO opuestos, o dos posiciones del mismo
ticker) → nunca se selecciona sola, exige selección explícita del
usuario (`NEEDS_REVIEW`).

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
- Flujo de análisis (Market Analysis) sin tests automatizados (JS) --
  verificación manual, vía `chrome://extensions` → "Inspeccionar vistas:
  service worker" para confirmar el `symbol` que sale hacia
  `/map/robinhood` y la respuesta que entra. `position_logic.js` (Tramo
  3) SÍ tiene tests (`tests/position_logic.test.js`, `node --test`) --
  este sandbox de desarrollo no tenía `node` instalado, así que se
  verificaron en su lugar ejecutando la misma lógica en vivo con el
  motor JS del navegador (Claude Browser tool); quedan listos para
  correr con `node --test browser-extension/tests/` en cualquier
  máquina con Node ≥18.
- `POST /positions` (crear Position) NO tiene idempotency key en el
  contrato de Tramo 2 -- la UI mitiga con un guard de "single flight"
  (botón deshabilitado durante el envío) pero no hay protección de
  idempotencia real del lado del servidor para ESTE endpoint específico
  (a diferencia de fills/orders, que sí la tienen vía `fill_id`/
  `intent_id`). Riesgo residual documentado, no corregido en este tramo
  (requeriría tocar el contrato ya auditado de Tramo 2).
