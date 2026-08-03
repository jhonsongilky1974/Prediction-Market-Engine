# Diseño: mapeador Robinhood → Kalshi

**Estado: diseño + implementación del mapeador (módulo Python interno)
autorizados, basados en evidencia real verificada en vivo contra las
APIs de Robinhood.** Este documento registra esa evidencia, el hallazgo
que obligó a ajustar el diseño original, y la arquitectura recomendada
para la integración completa (extensión de navegador, todavía no
construida — ver §5).

## 0. Contexto y método

Objetivo: que una extensión de Chrome pueda traducir automáticamente el
evento de "Prediction Markets" que el usuario está viendo en Robinhood
al ticker real de Kalshi, para alimentar `GET /analyze/{ticker}` (Fase
5, `HTTP_SERVICE_SPEC.md`).

Verificado antes de diseñar (Regla de investigación previa, igual que en
Fase 5): **la extensión de Chrome no existe en este repositorio, ni
existió nunca** — búsqueda por nombre de archivo/carpeta y por contenido
(`manifest_version`, `chrome.runtime`, etc.) en el working tree Y en
`git log --all --full-history` de todas las ramas: cero resultados.

La evidencia de este documento se obtuvo inspeccionando en vivo, con la
sesión real de Robinhood del usuario ya autenticada (Chrome real vía la
herramienta `claude-in-chrome`, nunca credenciales manejadas por
Claude), el tráfico de red (`fetch` ejecutado en el contexto de la
página, mismo origen, cookies de sesión ya presentes) de dos eventos
reales el 2026-08-03: un partido de MLB (Washington @ Philadelphia) y un
partido de tenis WTA (Pegula vs Eala). Se descartó un intento previo de
capturar esta evidencia vía exportación HAR de DevTools por fallar
repetidamente en guardarse físicamente en disco (ver historial de la
sesión) — la inspección en vivo fue el método que finalmente produjo
evidencia verificable.

## 1. Endpoints identificados (evidencia real)

Todos bajo `api.robinhood.com`, mismo origen que la SPA, autenticados
por cookie de sesión (sin header `Authorization` propio observado).

### 1.1 `GET /prediction-markets/v1/event_state?event_ids=<uuid-robinhood>`

Estructura del evento. Se observó que la SPA lo llama repetidamente
(polling para datos en vivo) — el mapeador solo necesita una lectura
puntual.

Ejemplo real, MLB (`event_ids=9b20e97c-19ec-4bdc-8da1-c35f449b7956`):

```json
{
  "eventStates": [{
    "eventStatus": "EVENT_STATUS_UPCOMING",
    "eventId": "9b20e97c-19ec-4bdc-8da1-c35f449b7956",
    "category": "Baseball",
    "gameStart": "2026-08-03T22:40:00Z",
    "gdpTitle": "WSH 0 - 0 PHI",
    "pageType": "PAGE_TYPE_GDP",
    "sportMetadata": {"baseball": {"gamePeriodIndicator": {...}}},
    "totalVolumeOfAllContractsV2": "71279",
    "totalOpenInterestOfAllContractsV2": "86235",
    "isSport": true
  }]
}
```

Ejemplo real, tenis (`event_ids=9e2d0eeb-6250-4ac2-84d6-b0d74d5f1409`,
partido ya en curso):

```json
{
  "eventStates": [{
    "eventStatus": "EVENT_STATUS_UPCOMING",
    "eventProgress": "Interrupted",
    "eventId": "9e2d0eeb-6250-4ac2-84d6-b0d74d5f1409",
    "category": "Tennis",
    "gdpTitle": "",
    "pageType": "PAGE_TYPE_EDP",
    "sportMetadata": {"tennis": {
      "topPlayer": {"contractId": "2e924757-...", "sets": [{"games": 6, "isWin": true}, {"games": 1, "isWin": false}]},
      "bottomPlayer": {"contractId": "fef0ca91-...", "sets": [{"games": 4, "isWin": false}, {"games": 2, "isWin": false}]}
    }}
  }]
}
```

Puntos verificados, no supuestos:

- `eventId` es un **UUID interno de Robinhood** — no aparece ningún
  ticker ni identificador de Kalshi en esta respuesta.
- `gameStart` (ISO 8601 UTC) está presente para el partido de MLB
  (aún no empezado) y **ausente** en el de tenis (ya en curso,
  interrumpido) — no se puede asumir que siempre esté disponible.
- `gdpTitle` (marcador en texto libre) solo aparece en MLB; en tenis
  llega vacío.
- `pageType` difiere por deporte (`PAGE_TYPE_GDP` vs `PAGE_TYPE_EDP`) y
  el bloque `sportMetadata` tiene forma distinta por deporte — la
  estructura de este endpoint **no es uniforme entre deportes**.
- Ningún nombre completo de equipo/jugador en ningún campo — solo
  abreviaturas de 3 letras, indirectamente (sufijo de `symbol` en
  `quotes/v1`, §1.2; o en `gdpTitle`, solo MLB).

### 1.2 `GET /marketdata/event/contract/quotes/v1/?ids=<uuid-contrato>,...`

Precios en vivo por contrato (un contrato = un lado/equipo/jugador del
evento). Acepta múltiples `instrument_id` separados por coma en un solo
request.

Ejemplo real, MLB, dos contratos (WSH y PHI):

```json
{"status": "SUCCESS", "data": [
  {"status": "SUCCESS", "data": {
    "yes_bid_price": "0.42", "yes_ask_price": "0.43",
    "no_bid_price": "0.57", "no_ask_price": "0.58",
    "last_trade_price": "0.43",
    "symbol": "MLBGAME-26AUG03WSHPHI-WSH",
    "instrument_id": "7415341b-f29f-432e-8824-92607b2dcec5",
    "state": "active", "updated_at": "2026-08-03T05:58:45.57109335Z"
  }},
  {"status": "SUCCESS", "data": {
    "yes_bid_price": "0.58", "yes_ask_price": "0.6",
    "symbol": "MLBGAME-26AUG03WSHPHI-PHI",
    "instrument_id": "da26cfce-a42a-4962-980e-4dae54564dd6",
    "state": "active", "updated_at": "2026-08-03T05:56:34.257306089Z"
  }}
]}
```

Ejemplo real, tenis (WTA), dos contratos (PEG y EAL):

```json
{"status": "SUCCESS", "data": [
  {"status": "SUCCESS", "data": {
    "yes_bid_price": "0.81", "yes_ask_price": "0.82",
    "symbol": "KXWTAMATCH-26AUG02PEGEAL-PEG",
    "instrument_id": "2e924757-1512-4df0-9518-548a49059cc8",
    "state": "active"
  }},
  {"status": "SUCCESS", "data": {
    "yes_bid_price": "0.18", "yes_ask_price": "0.19",
    "symbol": "KXWTAMATCH-26AUG02PEGEAL-EAL",
    "instrument_id": "fef0ca91-1104-49c5-9fa0-be59d8dfd765",
    "state": "active"
  }}
]}
```

Este es el endpoint que el usuario refería informalmente como
`v1/pids` — el nombre real es `quotes/v1/?ids=`.

### 1.3 `GET /marketdata/event/contract/fundamentals/v1/?ids=...`

Solo `volume`/`open_interest` por contrato. Sin nombres, sin tickers.
No aporta nada útil al mapeo — documentado por completitud, no se usa.

## 2. El hallazgo que cambió el diseño

El campo `symbol` de `quotes/v1` **no es un mapeo 1:1 confiable de forma
universal entre deportes** — verificado con datos reales, no supuesto:

| Deporte | `symbol` (Robinhood) | Ticker Kalshi real |
|---|---|---|
| Tenis (WTA) | `KXWTAMATCH-26AUG02PEGEAL-PEG` | **idéntico**, byte a byte |
| MLB | `MLBGAME-26AUG03WSHPHI-WSH` | `KXMLBGAME-26AUG03WSHPHI-WSH` (falta `KX`) |

Y, según evidencia ya documentada en `CONTINUITY.md` (§0.28, ticker MLB
real capturado en Fase 5), Kalshi a veces inserta un **segmento de
hora** entre la fecha y los equipos para desambiguar doubleheaders:
`KXMLBGAME-26AUG011507STLTOR-STL` (`1507` = hora, ausente en el
`symbol` de Robinhood, que solo trae fecha + equipos).

Conclusión: el `symbol` de Robinhood es, según el deporte, o bien el
ticker real, o bien un **candidato** que necesita verificarse contra los
mercados abiertos y en vivo de Kalshi — nunca se pasa directamente a
`/analyze` sin verificar.

## 3. Diseño del mapeador — `src/api/robinhood_mapper.py`

```python
def map_robinhood_symbol_to_kalshi_ticker(
    robinhood_symbol: str,
    robinhood_start_time: Optional[datetime] = None,
    repository: Optional[Repository] = None,
    kalshi_connector: Optional[KalshiConnector] = None,
) -> MappingResult  # .kalshi_ticker, .strategy, .candidate, .sport, .sport_key
```

Tres estrategias, en orden estricto (decisión explícita del usuario),
cada intento (éxito o fallo) registrado vía `logging` para que la
estrategia efectivamente usada sea siempre auditable:

1. **EXACT** — candidato (`symbol` con `KX` al frente si no lo trae ya)
   coincide ticker a ticker con un mercado Kalshi realmente abierto
   (`KalshiConnector.get_all_events_for_sport`, ya existente de Fase 1 —
   cero endpoints nuevos de Kalshi).
2. **SUBSTRING** — si falla lo anterior, se busca un ticker Kalshi
   abierto cuyo segmento central **empiece** con la fecha del candidato
   y **termine** con su bloque de equipos/jugadores, filtrando además
   por el mismo código de lado (`-WSH`/`-STL`/...). Tolera el segmento
   de hora opcional sin necesidad de adivinar su valor. Si hay más de
   un mercado que coincide (ambiguo — el propio caso que el segmento de
   hora de Kalshi existe para prevenir) se rechaza explícitamente
   (`MappingError` 409) en vez de elegir a ciegas.
3. **EVENT_MATCHER** — último recurso: delega en
   `src.matching.market_matcher.find_best_kalshi_event` (Fase 1, sin
   modificar), usando como nombres de participantes los códigos de 3
   letras derivados del propio `symbol` (Robinhood no expone nombres
   completos en ninguna respuesta JSON — ver §1). **Limitación
   documentada, no un defecto**: `name_similarity` compara
   tokens/prefijos de texto, y un código como `"WSH"` no es un prefijo
   textual de `"Washington"` — esta estrategia puede rendir peor que
   1/2 contra el `yes_sub_title` real de Kalshi (que sí suele traer
   nombres completos).

Sin match confidente en ninguna estrategia → `MappingError` (400/404/
409/502, mismo principio que `ResolverError` de `event_resolver.py`)
— nunca se fabrica un ticker.

**Reutilización, cero lógica de negocio nueva**: el mapeador solo
construye el ticker de mercado; la verificación en vivo usa
`KalshiConnector` tal cual, y la estrategia 3 usa `find_best_kalshi_event`
tal cual (mismo módulo que ya usa el pipeline MLB/tenis para su propio
matching contra Kalshi). No se reimplementa `resolve_ticker`/
`analyze_ticker` (Fase 5) — el resultado de este módulo (`kalshi_ticker`)
es exactamente el `ticker` que ya consume `GET /analyze/{ticker}`.

## 4. Pruebas

`tests/unit/test_robinhood_mapper.py` (25 tests, sin red real —
`KalshiConnector` sustituido por un stub, mismo patrón que
`test_event_resolver.py`):

- Helpers puros: `_parse_symbol` (formas válidas/inválidas),
  `_series_prefix_and_sport` (con/sin `KX`, serie no soportada),
  `_derive_opponent_code` (prefijo/sufijo/no derivable).
- Estrategia 1 (exact): tenis con `symbol` ya en formato Kalshi, MLB sin
  prefijo `KX`.
- Estrategia 2 (substring): ticker Kalshi real con segmento de hora que
  el `symbol` de Robinhood no trae; caso ambiguo (dos partidos del
  mismo día/equipos, doubleheader) → 409.
- Estrategia 3 (event_matcher): cableado verificado con un caso
  favorable de nombres (ver limitación documentada en §3) para
  confirmar que la estrategia se invoca y selecciona el mercado
  correcto cuando sí hay señal suficiente.
- Casos de fallo total (404 tras las 3 estrategias), fallo de Kalshi
  (502), serie no soportada (400, sin llamar a Kalshi).

Suite completa (`tests/unit`): **1025 passed, 0 failed** — sin
regresiones en ningún módulo existente.

## 5. Arquitectura recomendada para la integración completa

**Lo implementado en este paso es solo el módulo Python interno**
(`src/api/robinhood_mapper.py` + tests) — decisión deliberada de
alcance mínimo, consistente con cómo se construyó Fase 5 (`resolver` →
`service` → `endpoint`, cada capa aprobada antes de la siguiente).
**Todavía no existen**: un endpoint HTTP que reciba el `symbol`/
`event_state` desde afuera, ni la extensión de Chrome.

Arquitectura recomendada para cuando se decida avanzar (content script
→ background service worker → backend local, como ya se había
acordado):

```
Robinhood (pestaña del usuario)
  │  content script: NO hace scraping de DOM para el mapeo -- el propio
  │  event_state/quotes/v1 ya está disponible como fetch/XHR de la
  │  página (mismo origen, cookies ya presentes); el content script solo
  │  necesita leer esas dos respuestas (via un listener de red del lado
  │  de la extensión, o repitiendo el fetch con las cookies del propio
  │  navegador, igual que se hizo para esta investigación)
  ▼
background service worker (extensión)
  │  POST http://localhost:8000/map/robinhood  { symbol, game_start? }
  ▼
Backend local (este repo, FastAPI, Fase 5 ya corriendo)
  │  map_robinhood_symbol_to_kalshi_ticker(...)  [este módulo]
  │  → ticker Kalshi verificado
  │  → resolve_ticker(ticker) / analyze_ticker(ticker)  [Fase 5, sin tocar]
  ▼
Respuesta AnalyzeResponse → extensión → UI inyectada en la pestaña de Robinhood
```

**Siguiente paso real** (requiere una decisión de alcance explícita del
usuario antes de escribir código, igual que en cada paso anterior):
decidir el contrato del nuevo endpoint (`POST /map/robinhood` o
equivalente) — qué payload exacto envía la extensión (¿un `symbol` por
lado, o el `event_state` completo?), y si la extensión vive en este
mismo repositorio o en uno aparte. Ninguna de las dos cosas está
autorizada todavía por este paso.
