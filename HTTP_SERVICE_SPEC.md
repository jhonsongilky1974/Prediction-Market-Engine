# Diseño: servicio HTTP local (Fase 5) — `/analyze`

**Estado: diseño + implementación autorizados en el mismo mensaje** —
mismo patrón de delegación que la calibración real (§Fase 4). El
usuario ya resolvió los dos puntos de arquitectura genuinamente suyos
(frescura de datos = pipeline en vivo por request; formato de
identificador = implícito en su pedido original, "identificador de un
evento de Robinhood/Kalshi" → identificador real de Kalshi). Este
documento registra las decisiones mecánicas restantes y el punto real
encontrado en la investigación (Robinhood no existe), sin fabricar
nada no verificado contra el código real.

## 0. Investigación previa (contra código real)

- **Robinhood no está integrado en absoluto** — único rastro:
  `MarketData.robinhood_price_observed: Optional[float] = None`
  (Fase 1, vestigial, nunca poblado por ningún conector). Confirmado
  con el usuario: el endpoint sirve exclusivamente eventos de Kalshi.
- **`P_consensus_no_vig` no es utilizable con datos reales hoy** —
  `src/pricing/odds_consensus.py` requiere `LabeledBookmakerOdds`
  (cuotas ya etiquetadas YES/NO), y la capa que resolvería
  nombre-de-participante → YES/NO nunca se construyó (diferida
  deliberadamente en Fase 2, documentado literalmente en ese módulo).
  El endpoint devuelve `null` para este campo, con una nota explícita
  — el usuario mismo anticipó esto ("si está disponible").
- **`KalshiConnector` no tiene fetch de un solo ticker** — solo
  `get_events`/`get_markets`/`get_events_for_sport`/`get_all_events_for_sport`
  (por `series_ticker`, con paginación). Resolver un ticker concreto
  significa: derivar la serie del prefijo (`KXMLBGAME`/`KXATPMATCH`/
  `KXWTAMATCH`, `config/settings.KALSHI_SPORT_SERIES`), pedir TODOS los
  eventos abiertos de esa serie (`get_all_events_for_sport`, ya sigue
  paginación), y buscar el ticker exacto entre los mercados anidados —
  no se inventa ningún endpoint nuevo de Kalshi no verificado.
- **Un ticker de mercado de Kalshi ya representa una posición YES
  concreta** (`market_matcher.py`, documentado literalmente) — el
  endpoint por lo tanto siempre reporta el análisis del lado
  `Side.YES` de ESE mercado, nunca ambos lados ni el lado NO. Un
  `event_ticker` (agrupa varios mercados) es rechazado explícitamente
  con un error claro — inventar una regla de "cuál mercado es el que
  el usuario quiso decir" no está respaldado por evidencia.
- **`run_mlb_pipeline(date)`/`run_tennis_pipeline(tour, date)` ya
  hacen fetch + matching + normalización completos** para un día
  entero — el endpoint reutiliza estas funciones TAL CUAL (ninguna
  lógica de matching/normalización nueva), filtrando el resultado al
  registro cuyo `record.market_id` coincide exactamente con el ticker
  pedido. Si el matcher (ya existente, con su propio umbral de
  confianza) no llegó a un match confidente para ese ticker
  específico, el endpoint lo reporta honestamente (404) en vez de
  forzar un resultado.
- **La fecha a consultar se deriva del propio ticker de Kalshi**
  (`occurrence_datetime` del mercado encontrado en el paso anterior,
  ya en vivo) — nunca se asume "hoy", evita perder eventos ya
  programados para otro día.
- `run_decision_pipeline` (orquestador, Fase 4, sin modificar) persiste
  igual que la corrida horaria real — el endpoint reutiliza el MISMO
  `OpportunityRepository`/`data/engine.db`, mismo `SPORT_ADAPTERS`
  importado literalmente de `scripts/run_e2e.py` (sin redeclarar la
  construcción del adapter en un segundo lugar). Cada llamada a
  `/analyze` dejo un rastro real: nuevos `event_snapshots`/
  `feature_snapshots` (de los pipelines) + una nueva
  `OpportunityEvaluation` (del orquestador), exactamente igual que la
  corrida horaria del LaunchAgent — **no hay una variante "de solo
  lectura"**, construir una implicaría duplicar el pipeline (prohibido
  explícitamente por el usuario).
- **`ConfidenceProfile`** (`data_quality`/`model_reliability`/
  `market_quality`/`operational_safety`/`operational_risk`/
  `aggregate_confidence`) ya es exactamente el desglose de
  incertidumbre pedido — se reutiliza tal cual desde
  `OpportunityEvaluation.confidence_profile`.
- **"Variables más influyentes"** se resuelve con `EvidenceItem`
  (`OpportunityEvaluation.evidence_items`, ya calculado por
  `evidence_engine.collect_evidence`, Fase 3) ordenado por `strength`
  descendente — cada uno ya trae `fact`/`direction`/`source_field`/
  `strength`, cero cálculo nuevo.

## 1. Contrato del endpoint

```
GET /analyze/{ticker}
```

`ticker`: ticker de MERCADO de Kalshi (no de evento), p.ej.
`KXMLBGAME-25AUG01LAADET-LAA`.

**Respuesta 200** (`AnalyzeResponse`, ver `src/api/schemas.py`):

```
{
  "ticker": "...", "event_id": "...", "sport": "MLB"|"TENNIS",
  "participant_a": "...", "participant_b": "...",
  "p_model": float|null, "p_market": float|null,
  "p_consensus_no_vig": null,  # siempre null hoy -- ver §0
  "p_consensus_no_vig_unavailable_reason": "...",
  "edge": float|null, "ev_bruto": float|null, "ev_neto": float|null,
  "net_ev_status": "COMPUTED"|"UNKNOWN",
  "recommendation": "ENTER"|"WATCH"|"PASS",
  "recommendation_reasons": [str, ...],
  "uncertainty": {
    "data_quality": float|null, "model_reliability": float|null,
    "market_quality": float|null, "operational_safety": float|null,
    "operational_risk": float|null, "aggregate_confidence": float|null
  },
  "most_influential_variables": [
    {"fact": str, "direction": "FOR"|"AGAINST", "source_field": str, "strength": float|null}, ...
  ],  # ordenado por strength descendente, strength=None al final
  "model_version": str|null, "calibration_version": str|null,
  "policy_version": str, "feature_schema_version": str,
  "freshness": {
    "analysis_timestamp": iso8601,   # cuándo se generó esta respuesta
    "market_timestamp": iso8601,     # capture_ts real del fetch de Kalshi para este ticker
    "data_freshness_seconds": float  # analysis_timestamp - market_timestamp
  }
}
```

**Errores, honestos, nunca un 200 fabricado**:
- `400` — ticker no pertenece a ninguna serie soportada
  (`KXMLBGAME`/`KXATPMATCH`/`KXWTAMATCH`), o es un `event_ticker` en
  vez de un ticker de mercado.
- `404` — ticker con formato de serie válido pero no encontrado entre
  los eventos ACTUALMENTE abiertos de Kalshi (puede haber cerrado o no
  existir), o encontrado en Kalshi pero sin match confidente a un
  evento MLB/tenis conocido (el matcher existente no llegó al umbral
  de confianza).
- `502` — fallo real de un conector upstream (Kalshi/MLB/ESPN) al
  intentar el fetch en vivo — se propaga el error real, nunca se
  fabrica una respuesta parcial.

## 2. Estructura de código (reutilización, cero lógica de negocio nueva)

- `src/api/event_resolver.py` — `resolve_ticker(ticker) ->
  ResolvedEvent | ResolverError`: serie → sport_key → fetch en vivo de
  eventos abiertos (`KalshiConnector`) → localizar ticker → derivar
  fecha/tour → `run_mlb_pipeline`/`run_tennis_pipeline` (sin
  modificar) → filtrar por `record.market_id == ticker`.
- `src/api/analysis_service.py` — dado un `ResolvedEvent`, arma
  `Repository`/`HistoryRepository`/`OpportunityRepository` (mismo
  patrón que `scripts/run_e2e.py._run`), llama
  `run_decision_pipeline` (Fase 4, sin modificar) con
  `SPORT_ADAPTERS`/`load_policy_manifest` importados literalmente de
  `scripts.run_e2e`, recupera la `OpportunityEvaluation` del lado YES
  vía `opp_repo.get_latest_evaluation(...)`, compone `AnalyzeResponse`.
- `src/api/schemas.py` — `AnalyzeResponse` (pydantic, capa de
  presentación únicamente, no un contrato del motor).
- `src/api/main.py` — app FastAPI, una sola ruta, traduce
  `ResolverError`/excepciones de conector a los códigos HTTP de §1.

Ninguna lógica de predicción/policy/edge/EV se reimplementa — todo el
cálculo real sigue viviendo exactamente donde ya vivía.

## 3. Dependencias nuevas

`fastapi`, `uvicorn` — primera dependencia externa de Fase 5 (ninguna
de las fases anteriores tocó `requirements.txt` para código de
producción). Se documentan con el mismo criterio de versión que el
resto (`>=X,<Y`).

## 4. Pruebas

- `event_resolver`/`analysis_service`: conectores mockeados (mismo
  patrón que los tests de `mlb_pipeline.py`/`tennis_pipeline.py`
  existentes) — sin red real en tests unitarios.
- `main.py`: `fastapi.testclient.TestClient`, casos 200/400/404/502.
- Un test de integración real-API opcional (mismo patrón ya
  establecido, `tmp_path`, nunca `data/engine.db`) contra un ticker
  real actualmente abierto, si el tiempo de red lo permite en CI local.

## 5. Documentación

Nuevo `API_USAGE.md` (o sección en `README.md`): comando `uvicorn`,
ejemplos `curl`, tabla de campos de la respuesta, nota explícita sobre
Robinhood/`P_consensus_no_vig`/efecto de escritura en `data/engine.db`.
