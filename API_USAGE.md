# Servicio HTTP local — `/analyze` (Fase 5)

Expone el motor de análisis (Fase 1-4) vía HTTP. Ver `HTTP_SERVICE_SPEC.md`
para el diseño completo y `CONTINUITY.md` (§0.28) para el informe de
implementación y la evidencia real.

## Arrancar el servidor

```bash
source .venv/bin/activate
pip install -r requirements.txt   # primera vez -- añade fastapi/uvicorn/httpx
uvicorn src.api.main:app --reload --port 8000
```

`--reload` es opcional (útil en desarrollo). En producción local, omitirlo.

## Endpoint

```
GET /analyze/{ticker}
```

`ticker` debe ser el **ticker de MERCADO** de Kalshi (no el
`event_ticker`, que agrupa varios mercados) — el identificador que
representa una posición YES concreta, p. ej.
`KXMLBGAME-25AUG01LAADET-LAA` o `KXATPMATCH-26AUG01NAKFRI-NAK`. Puedes
encontrarlo en la app/API pública de Kalshi.

### Ejemplo

```bash
curl -s http://127.0.0.1:8000/analyze/KXATPMATCH-26AUG01NAKFRI-NAK | python3 -m json.tool
```

Respuesta real (ejecutada contra APIs en vivo durante el desarrollo de este paso):

```json
{
  "ticker": "KXATPMATCH-26AUG01NAKFRI-NAK",
  "event_id": "espn_tennis_atp_178956",
  "sport": "TENNIS",
  "participant_a": "Brandon Nakashima",
  "participant_b": "Taylor Fritz",
  "p_model": 0.00227894315900518,
  "p_market": 0.38,
  "p_consensus_no_vig": null,
  "p_consensus_no_vig_unavailable_reason": "no disponible: ...",
  "edge": -0.37772105684099483,
  "ev_bruto": -0.3777210568409948,
  "ev_neto": null,
  "net_ev_status": "UNKNOWN",
  "recommendation": "WATCH",
  "recommendation_reasons": ["HARD_HOLD: ...", "..."],
  "uncertainty": {
    "data_quality": 58.82, "model_reliability": null, "market_quality": 100.0,
    "operational_safety": 98.97, "operational_risk": 1.03, "aggregate_confidence": 89.98
  },
  "most_influential_variables": [
    {"fact": "...", "direction": "FOR", "source_field": "...", "strength": 0.8}
  ],
  "model_version": "tennis_baseline_logreg_v1_20260801T184245Z",
  "calibration_version": null,
  "policy_version": "tennis_v1",
  "feature_schema_version": "phase2_registry_v1",
  "freshness": {
    "analysis_timestamp": "2026-08-01T21:30:11.838134Z",
    "market_timestamp": "2026-08-01T21:29:31.457288Z",
    "data_freshness_seconds": 40.38
  },
  "enrichment_mode": "reduced",
  "processing_time_ms": 40382.8
}
```

### Errores (siempre honestos, nunca un 200 fabricado)

| Código | Cuándo |
|---|---|
| `400` | El ticker no pertenece a ninguna serie soportada (`KXMLBGAME`/`KXATPMATCH`/`KXWTAMATCH`), o es un `event_ticker` en vez de un ticker de mercado (el error lista los tickers de mercado disponibles de ese evento). |
| `404` | El ticker no está entre los eventos ACTUALMENTE abiertos de Kalshi, o existe pero el motor (matcher de Fase 1, sin modificar) no alcanzó confianza suficiente para emparejarlo con datos reales de MLB/tenis. |
| `502` | Fallo real de un conector upstream (Kalshi/MLB Stats API/ESPN) durante el fetch en vivo. |

```bash
curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/analyze/KXNFLGAME-BOGUS
# {"detail":"ticker 'KXNFLGAME-BOGUS' no pertenece a ninguna serie de Kalshi soportada (KXMLBGAME, KXATPMATCH, KXWTAMATCH)."}
# HTTP 400
```

## Campos de la respuesta

| Campo | Significado |
|---|---|
| `p_model` | Probabilidad del modelo (calibrada si existe un calibrador real desplegado para ese `model_version`, cruda en caso contrario -- hoy siempre cruda, ver `CONTINUITY.md` §0.27). |
| `p_market` | Precio de mercado (yes_ask/no_ask según el lado) del ticker, capturado en vivo. |
| `p_consensus_no_vig` | **Siempre `null` hoy** -- ver `p_consensus_no_vig_unavailable_reason`. |
| `edge`, `ev_bruto` | Ver `src/signals/edge.py`/`expected_value.py` (Fase 2). |
| `ev_neto`, `net_ev_status` | `net_ev_status="UNKNOWN"` siempre hoy -- D-3 (fórmula de fees de Kalshi) sin resolver, bloqueado por rate-limit de la fuente primaria. |
| `recommendation` | `ENTER`/`WATCH`/`PASS` (Policy Engine, Fase 3). `ENTER` es estructuralmente inalcanzable mientras D-3 esté abierto. |
| `uncertainty` | Desglose completo de `ConfidenceProfile` (Fase 3). |
| `most_influential_variables` | `EvidenceItem[]` (Fase 3, `evidence_engine.py`) ordenados por `strength` descendente. |
| `freshness` | `analysis_timestamp` (fin del procesamiento), `market_timestamp` (captura real de Kalshi), `data_freshness_seconds` (diferencia, siempre >= 0). |
| `enrichment_mode` | `"full"` (MLB) o `"reduced"` (tenis -- ver más abajo). |
| `processing_time_ms` | Latencia total del request, en milisegundos. |

## Notas importantes (leer antes de usar en cualquier flujo real)

- **Solo Kalshi.** Robinhood no está integrado en el proyecto -- ningún
  conector existe (`MarketData.robinhood_price_observed` es un campo
  vestigial de Fase 1, nunca poblado). Un ticker que no pertenezca a
  las series de Kalshi soportadas devuelve `400`.
- **`P_consensus_no_vig` no es utilizable con datos reales hoy** -- la
  capa que resuelve qué participante de The Odds API corresponde al
  lado YES de un ticker de Kalshi nunca se construyó (diferida
  deliberadamente en Fase 2, `src/pricing/odds_consensus.py`). Siempre
  `null`, con la razón explícita en la respuesta.
- **Cada llamada re-ejecuta el pipeline en vivo** (aprobado
  explícitamente por el usuario, para que `P_market`/`EDGE`/`EV`
  reflejen siempre datos actuales) -- consulta Kalshi + MLB Stats
  API/ESPN Tennis de verdad en cada request, no lee ningún caché.
  **Efecto secundario real**: cada `/analyze` escribe
  `event_snapshots`/`feature_snapshots` nuevos y una nueva
  `OpportunityEvaluation` en `data/engine.db` de producción, exactamente
  igual que la corrida horaria del LaunchAgent -- no existe una
  variante de solo lectura (construir una habría duplicado la lógica
  del pipeline, explícitamente prohibido).
- **Latencia real, medida contra APIs en vivo**: MLB ~30-35s (día
  completo de partidos, sin filtro por evento), tenis ~30-40s con
  `enrichment_mode="reduced"` (SofaScore desactivado solo en esta vía
  en vivo -- con SofaScore activado se midió >5 minutos contra un día
  real de ATP, inaceptable para un servicio HTTP). La captura
  programada (LaunchAgent horario) sigue enriqueciendo con SofaScore
  completo, sin cambios -- la reducción es exclusiva de `/analyze`.
- **`ticker` debe ser un ticker de MERCADO**, no de evento -- un ticker
  de evento (agrupa varios mercados/lados) se rechaza con `400` y una
  lista de los tickers de mercado válidos de ese evento.

## Pruebas

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_event_resolver.py tests/unit/test_analysis_service.py tests/unit/test_api_main.py -v
python -m pytest tests/integration/test_analyze_real.py -m integration -v   # APIs reales, tmp_path, nunca data/engine.db
```
