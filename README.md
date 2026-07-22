# Prediction Market Engine — Fase 1: Infraestructura de Datos

Motor de detección de valor en mercados deportivos de predicción (MLB y tenis).
Esta es **Fase 1**: ingestión, normalización, event/market matching, validación
de calidad y almacenamiento local reproducible. **READ-ONLY.** No hay P_model,
EDGE, EV, CONFIDENCE ni señales de entrada/salida — eso es Fase 2.

Ver [`PLAN.md`](PLAN.md) para el plan de implementación.

## Requisitos

- Python 3.9+ (probado con el Python del sistema en macOS, 3.9.6)
- Conexión a internet (para los conectores reales; los tests unitarios no la requieren)

## Instalación

```bash
cd /Users/jhonsongil/Prediction-Market-Engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración (opcional)

Solo necesaria si se quiere probar The Odds API:

```bash
cp .env.example .env
# editar .env y poner ODDS_API_KEY=<tu-key>
export $(cat .env | xargs)   # o usar python-dotenv en tu propio script
```

Si `ODDS_API_KEY` no está seteada, el conector se marca `NOT_CONFIGURED` y
todo el resto del sistema funciona con normalidad (Kalshi es la fuente de
mercado usada en el test end-to-end).

## Ejecutar los tests

```bash
source .venv/bin/activate

# Unitarios (sin red, con fixtures) — deben pasar siempre
python -m pytest tests/unit -q

# Integración (red real contra MLB Stats API, Kalshi, ESPN, SofaScore)
python -m pytest tests/integration -q -m integration

# Todo junto
python -m pytest tests/ -q
```

## Ejecutar el test end-to-end real (MLB + tenis)

```bash
source .venv/bin/activate
python scripts/run_e2e.py
```

Opciones:

```bash
python scripts/run_e2e.py --mlb-date 2026-07-22 --tour atp --tennis-date 20260722
python scripts/run_e2e.py --tour wta
```

El script:
1. Busca automáticamente el próximo día con juegos MLB / partidos ATP
   disponibles si no se especifica fecha.
2. Corre `run_mlb_pipeline` y `run_tennis_pipeline` contra las APIs reales.
3. Imprime, por cada registro normalizado: participantes, estado, mercado
   Kalshi emparejado (bid/ask reales), confianza/método/warnings del
   matching, completeness score y campos faltantes.
4. Imprime la tabla resumen `SOURCE | DATA FETCHED | NORMALIZED | MATCHED |
   MISSING | WARNINGS`.
5. Deja todo persistido en `data/engine.db` (SQLite) y `data/raw/<source>/`
   (JSON crudo, un archivo por captura, nunca sobrescrito).

## Estructura del proyecto

```
config/settings.py        Timeouts, retries, rate limits, tolerancias de matching, rutas
src/connectors/            Un cliente por fuente (mlb, sofascore, espn_tennis, kalshi, odds_api)
src/connectors/base_client.py   Cliente HTTP compartido (timeout/retry/backoff/rate-limit/RAW capture)
src/normalization/         RAW -> esquema único (mlb_normalizer, tennis_normalizer, market_normalizer)
src/matching/               event_matcher (nombre+tiempo, confidence/method/warnings), market_matcher (Kalshi)
src/models/schemas.py       NormalizedRecord tipado (pydantic), todo opcional = None si falta
src/quality/                validators.py (reglas de sanidad), completeness.py (score, missing fields)
src/storage/repository.py   SQLite + JSON RAW en disco
src/pipelines/              mlb_pipeline.py, tennis_pipeline.py (orquestación end-to-end)
scripts/run_e2e.py          Test end-to-end real, imprime la tabla resumen
tests/unit/                 Tests con fixtures, sin red
tests/integration/          Tests marcados `integration`, contra APIs reales
tests/fixtures/             JSON de ejemplo (payloads reales recortados)
data/raw/, data/normalized/ Salida de la ejecución (gitignored salvo .gitkeep)
```

### Desviaciones documentadas de la estructura sugerida

- `src/connectors/base_client.py`: no estaba en el árbol pedido. Se añadió
  porque los 5 conectores comparten idéntica lógica de timeout/retry/
  backoff/rate-limit/captura-RAW; sin él, esa lógica se duplicaría 5 veces.
  Cada conector sigue siendo dueño exclusivo de sus endpoints y su parsing.
- `scripts/run_e2e.py`: el test end-to-end "real" pedido necesita imprimir
  una tabla legible por humanos, no solo pass/fail. Se separó en dos piezas:
  `scripts/run_e2e.py` (reporte legible) y
  `tests/integration/test_e2e_real.py` (pass/fail automatizable con pytest).

## Fuentes y reglas clave respetadas

- **Kalshi**: se conservan `yes_bid`, `yes_ask`, `no_bid`, `no_ask` tal como
  llegan del payload (`*_dollars`). Nunca se reconstruyen como `1 - precio`.
  `SPREAD_YES`/`SPREAD_NO` sí se calculan (`ask - bid`). `EXCHANGE_FEE` queda
  `NULL` porque el payload actual no trae ningún campo de fee.
  `ACTUAL_SETTLEMENT_TIME` queda `NULL` porque no hay evidencia de
  liquidación real en el payload de `/markets` (ver
  `src/normalization/market_normalizer.py`). Sigue el `cursor` de
  paginación de `/events` hasta agotarlo (o un tope de páginas, nunca un
  loop sin límite) — ver `KalshiConnector.get_all_events_for_sport`.
- **Los datos de mercado SOLO se adjuntan si el match es confidente**
  (`EXACT_NAME_TIME`/`FUZZY_NAME_TIME`). Si el mejor candidato de Kalshi
  disponible queda en `NEEDS_REVIEW`/`NO_MATCH`, el registro NUNCA lleva
  `market_id`/bid/ask/timestamps de ese candidato — quedan `NULL` +
  `MISSING_FIELDS`, y el ticker descartado se documenta como texto en
  `match_warnings` para revisión humana (ver
  `src/matching/market_matcher.py::apply_kalshi_match`).
- **SofaScore**: API interna no documentada. El conector implementa
  timeouts, reintentos limitados, backoff exponencial y rate limiting
  conservador — pero **desde este entorno de ejecución responde 403 Forbidden
  de forma consistente** (headers de navegador incluidos), compatible con un
  bloqueo Cloudflare por IP de datacenter. El pipeline de tenis lo trata
  como best-effort: si falla, sigue con ESPN + Kalshi y deja
  `TENNIS_VARIABLES` en `None` + `MISSING_FIELDS`. Debe revalidarse desde una
  IP residencial/oficina antes de depender de él en Fase 2.
- **The Odds API**: la key se lee solo de `ODDS_API_KEY`. Sin key, el
  conector es `NOT_CONFIGURED` y no toca la red (verificado con test que
  falla si intenta llamar a `requests`).
- **Robinhood**: sin conector automatizado. El esquema reserva
  `market.robinhood_price_observed` (siempre `None` en Fase 1) para uso
  manual futuro.
- **MISSING nunca se convierte en 0** ni en ningún valor por defecto — se
  deja `None` y se registra el nombre del campo en
  `data_quality.missing_fields`.
- **MODEL_OUTPUT** (`model_probability`, `confidence`, `uncertainty`,
  `edge`, `expected_value`, `signal`) permanece **siempre `None`** en Fase 1
  (verificado por test unitario).

## Qué NO hace esta fase (por diseño)

- No calcula probabilidad de modelo, edge, EV, confidence ni señales
  ENTER/WATCH/PASS.
- No ejecuta órdenes ni operaciones financieras.
- No hace scraping de Robinhood.
- No usa servicios de pago (Apify de pago, suscripciones, etc).
