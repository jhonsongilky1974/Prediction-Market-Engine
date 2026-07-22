# PLAN — Fase 1: Infraestructura de Datos del Motor de Detección de Valor

## Alcance
Solo Fase 1: ingestión → normalización → event matching → market matching →
validación/data quality → almacenamiento local → test end-to-end real (MLB + tenis).
READ-ONLY. Sin P_model/EDGE/EV/CONFIDENCE/umbrales/ejecución de órdenes.

## Stack
- Python 3.9 (sistema, vía venv local `.venv`) — sin dependencias pesadas.
- `requests` para HTTP, `pydantic` para el esquema tipado, `pytest` para tests,
  `python-dotenv` opcional para cargar `.env`. Todo lo demás con stdlib
  (`sqlite3`, `json`, `datetime`, `difflib`/`rapidfuzz` si se justifica).
- SQLite (`data/engine.db`) + JSON RAW en `data/raw/<source>/<capture_ts>_<id>.json`.

## Estructura (según especificación del usuario)
```
src/connectors/      mlb.py, sofascore.py, espn_tennis.py, kalshi.py, odds_api.py
src/normalization/   mlb_normalizer.py, tennis_normalizer.py, market_normalizer.py
src/matching/         event_matcher.py, market_matcher.py
src/models/           schemas.py
src/quality/          validators.py, completeness.py
src/storage/          repository.py
src/pipelines/        mlb_pipeline.py, tennis_pipeline.py
tests/unit/, tests/integration/, tests/fixtures/
data/raw/, data/normalized/
logs/, config/
```

## Orden de implementación
1. `src/models/schemas.py` — dataclasses/pydantic para NormalizedRecord, campos NULL explícitos.
2. `src/connectors/*` — un cliente HTTP fino por fuente con timeout, retry+backoff
   limitado, rate limit conservador, guardado de RAW con timestamp de captura,
   manejo de fallo limpio (nunca lanza al pipeline, retorna estado + error).
3. `src/storage/repository.py` — SQLite (raw_captures, events, markets, matches) +
   helper para volcar JSON RAW a disco.
4. `src/normalization/*` — RAW → esquema normalizado, sin inventar valores.
5. `src/matching/event_matcher.py` y `market_matcher.py` — normalización de texto,
   tolerancia temporal, confidence/method/warnings, NEEDS_REVIEW si ambiguo.
6. `src/quality/validators.py` + `completeness.py` — reglas de validación de precios,
   timestamps, duplicados, completeness score, missing fields.
7. `src/pipelines/mlb_pipeline.py` y `tennis_pipeline.py` — orquestan todo lo anterior.
8. Tests unitarios con fixtures (sin red) + tests de integración reales (marcados,
   se saltan limpiamente si no hay red/API key).
9. Test end-to-end real (script en `tests/integration` o `scripts/`) que imprime
   la tabla resumen pedida (SOURCE/DATA FETCHED/NORMALIZED/MATCHED/MISSING/WARNINGS).
10. README.md + `.env.example` + `config/` (settings de timeouts, rate limits).

## Notas de diseño
- The Odds API: key solo desde env var `ODDS_API_KEY`; si falta, el conector
  se marca `NOT_CONFIGURED` y el pipeline continúa sin romperse.
- Kalshi: conector read-only, sin auth (mercados públicos); conservar bid/ask reales,
  nunca reconstruir con `1 - precio`.
- Robinhood: sin conector automatizado esta fase; solo campo opcional
  `ROBINHOOD_PRICE_OBSERVED` en el esquema para uso manual futuro.
- Todo campo no disponible → `None` + entrada en `MISSING_FIELDS`, nunca 0 ni default arbitrario.

Ejecuto en bloques, corriendo tests después de cada uno.
