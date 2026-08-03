# Informe Final de Cierre — Fase 5

**Fase 5 queda declarada oficialmente cerrada (2026-08-03).** Expone el
motor de análisis (Fase 1-4) vía HTTP, e integra Robinhood como fuente
de identificación de mercados (traducción de `symbol` → ticker Kalshi
real, verificado en vivo). Todo el alcance implementado está testeado
(1077 tests, 0 regresiones) y committeado. Un hallazgo real de fallo
(tenis, ver §3) queda documentado explícitamente como no resuelto, sin
fecha — no se fabricó ningún resultado para cerrar la fase
artificialmente. Ver `CONTINUITY.md` §0.28–§0.33 para el registro
completo, paso a paso.

## 1. Qué se construyó (alcance completo de la fase)

| Componente | Estado |
|---|---|
| `GET /analyze/{ticker}` (FastAPI, `src/api/`) — resuelve un ticker de MERCADO de Kalshi a un análisis completo (Fase 1-4, sin modificar) | Cerrado — `HTTP_SERVICE_SPEC.md`/`API_USAGE.md` |
| `src/api/robinhood_mapper.py` — traduce `symbol` de Robinhood → ticker Kalshi real, 3 estrategias (exact/substring/event_matcher), nunca fabrica un ticker sin verificar contra Kalshi en vivo | Cerrado — `ROBINHOOD_KALSHI_MAPPER_SPEC.md` |
| `POST /map/robinhood` — expone el mapeador vía HTTP, capa de transporte pura, cero lógica de mapeo duplicada | Cerrado |
| **Fix de causa raíz**: `/analyze` devolvía 404 tras un mapeo Robinhood exitoso — `occurrence_datetime` de Kalshi no es start_time mientras el evento no ha ocurrido (verificado contra la documentación oficial de Kalshi + evidencia real) | Cerrado — `CONTINUITY.md` §0.31 |
| Auditoría completa del flujo extremo a extremo + 3 correcciones adicionales (tolerancia de tenis en el mapeador, consistencia de mapas serie→deporte, constante duplicada) | Cerrado — `CONTINUITY.md` §0.32 |
| Revisión arquitectónica final (riesgos, supuestos, cuellos de botella, mantenibilidad) | Cerrado, sin cambios de código — `CONTINUITY.md` §0.33 |

Reutilización total verificada en cada paso vía `git diff --stat`:
ningún archivo de Fase 1-4 modificado salvo los cambios aditivos ya
documentados individualmente (`src/matching/market_matcher.py`,
`src/api/event_resolver.py` — ambos por el fix de causa raíz, no por
funcionalidad nueva).

## 2. Qué está listo para producción hoy

- **Flujo MLB completo, extremo a extremo, verificado con datos reales
  en vivo**: Robinhood → `POST /map/robinhood` → `GET /analyze/{ticker}`
  → respuesta con `p_market`/`recommendation`/`uncertainty` reales.
  Confirmado repetidamente contra un servidor real (`uvicorn`), no solo
  en tests.
- **Todo fallo posible (ticker no encontrado, mercado cerrado, timeout,
  error de red, respuesta incompleta de Kalshi, symbol malformado)
  termina en un error honesto y tipado (400/404/409/502) — nunca un
  200 fabricado.** Verificado explícitamente en la auditoría de §0.32.
- **Manejo de red/timeout robusto por diseño desde Fase 1**
  (`base_client.py`: reintentos limitados, backoff exponencial + jitter,
  nunca lanza excepción al pipeline) — reutilizado sin cambios por las
  3 capas nuevas de esta fase.
- **`data/models/`/`data/engine.db` de producción sin efectos
  colaterales inesperados** — cada `/analyze` escribe exactamente como
  la corrida horaria del LaunchAgent, mismo tratamiento, mismo rastro
  de auditoría.

## 3. Qué NO está listo para producción — deuda técnica documentada, sin fecha

| Deuda | Depende de | Estado verificado hoy (2026-08-03) |
|---|---|---|
| **Tenis (ATP/WTA) — matching de mercado no confiable** | Evidencia real equivalente a la de MLB sobre qué representa `occurrence_datetime` para tenis | **CONFIRMADO ROTO** — corrida real: 0/310 registros con match confidente; 31 casos de nombre exacto rechazados por tiempo (ej. desfase de -1680min). A diferencia de MLB: `occurrence_datetime` ≠ `expected_expiration_time`, sin segmento de hora en el ticker, sin texto `rules_primary` con hora — ninguna fuente estructurada de verdad disponible. Requiere sesión dedicada con su propio Design Proposal antes de cualquier fix (`CONTINUITY.md` §0.32, hallazgo H4). |
| **R1: partidos pospuestos/reprogramados** | Un caso real de partido pospuesto para verificar el comportamiento del fix de §0.31 en ese escenario | **RIESGO DOCUMENTADO, NO VERIFICADO** — Kalshi documenta explícitamente que un mercado permanece abierto tras un aplazamiento; el fix de §0.31 confía en el ticker (string estático) como fuente primaria de fecha/hora, sin evidencia de cómo se comporta ante un aplazamiento real (`CONTINUITY.md` §0.33). |
| **D-3** (fees de Kalshi) y **entrenamiento de MLB** | Deuda heredada de Fase 4, sin cambios en esta fase | Sin cambios — ver `FASE4_CIERRE_FINAL.md` §3 |

Ninguna de estas deudas bloquea el flujo MLB, que es el único
declarado listo para producción por esta fase.

## 4. Riesgos arquitectónicos remanentes (no bloquean el cierre, sí la siguiente fase)

De la revisión arquitectónica final (`CONTINUITY.md` §0.33), sin
cambios de código en este paso por instrucción explícita del usuario:

- SQLite como escritor único de `data/engine.db`, con dos escritores
  potenciales concurrentes hoy (LaunchAgent horario + requests en vivo
  de la extensión) — contención de locks real, sin monitoreo.
- Sin ningún control de concurrencia/rate-limiting en el servidor
  local — nada impide varios `/analyze` simultáneos saturando las 3
  APIs externas colectivamente.
- Costo por análisis fijo y alto, no baja con volumen (cada request
  re-ejecuta el pipeline completo del día); doble fetch de Kalshi por
  request (ineficiencia verificada, no solo teórica).
- Supuestos sin evidencia suficiente sobre la estabilidad del formato
  de ticker de Kalshi y del `symbol` de Robinhood (ambas APIs no
  oficiales/no versionadas para este uso).

## 5. Plan recomendado para el futuro (no una fase aprobada)

1. **Tenis**: sesión dedicada, con su propio Design Proposal, reuniendo
   evidencia real de varios partidos cruzados contra ESPN (fuente
   independiente) antes de proponer cualquier corrección.
2. **R1 (partidos pospuestos)**: verificar contra un caso real antes de
   confiar sin reservas en el fix de §0.31 fuera de los escenarios ya
   probados.
3. Los riesgos de escala (§4) no requieren acción mientras el uso siga
   siendo de un solo usuario en local — revisar antes de cualquier
   decisión de exponer el sistema más allá de ese contexto.
4. D-3 y entrenamiento de MLB: sin cambios respecto al plan ya
   documentado en `FASE4_CIERRE_FINAL.md` §4.

**Explícitamente fuera de alcance, sin cambios**: cualquier forma de
ejecución automática o `src/risk/` (Principio 21, heredado sin
excepción de fases anteriores).

## 6. Estado del repositorio al cierre

- **1077 tests pasando, 0 fallando** (`tests/unit` + `tests/integration`).
- **Último commit de Fase 5**: pendiente de este mismo commit de cierre
  (rama `main`).
- Servidor HTTP local (`uvicorn src.api.main:app`) validado en vivo
  repetidamente contra APIs reales durante toda la fase — ver
  `API_USAGE.md` para el uso.
- **Veredicto formal** (`CONTINUITY.md` §0.33): la arquitectura del
  flujo MLB (incluida la vía Robinhood) es suficientemente sólida para
  continuar a la siguiente fase; tenis explícitamente no.
