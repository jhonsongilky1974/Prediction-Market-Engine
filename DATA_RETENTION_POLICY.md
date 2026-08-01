# Política de Retención, Rotación y Respaldo de Datos — Fase 3

**Estado: IMPLEMENTADA (2026-08-01).** Propuesta cerrada, Alternativa 1 aprobada
por el usuario, mecanismo implementado (`scripts/data_maintenance.py`,
`tests/unit/test_data_maintenance.py`, LaunchAgent propio), 927/927 tests
pasando, ambos LaunchAgents (captura histórica + mantenimiento) reactivados de
forma permanente. Ver `CONTINUITY.md` §0.19 para el registro completo de
auditoría. Cierra formalmente D-1 (`FASE2_CIERRE_FINAL.md` §7, punto 1) y el
punto 7 de esa misma sección ("Diseñar la política de purgado/compactación").

**Principio rector (no negociable):** la reproducibilidad determinística exigida
por `TEMPORAL_REPRODUCIBILITY_SPEC.md` §3 depende del estado exacto de
`event_snapshots`/`feature_snapshots`/`event_results` en cualquier instante
pasado. Estas tres tablas son append-only a nivel de base de datos
(`src/storage/history_repository.py`, triggers `RAISE(ABORT, ...)` en
`UPDATE`/`DELETE`). **Ninguna cláusula de esta política purga, compacta,
archiva ni modifica esas tablas.** Su retención es indefinida y queda fuera
de alcance de este documento.

---

## 1. Inventario actual (medido, no estimado)

| Recurso | Tamaño actual | Volumen observado | Convención de nombre |
|---|---|---|---|
| `data/engine.db` (incluye `event_snapshots`/`feature_snapshots`/`event_results`, append-only) | 6.1 MB | ~2 MB/día (7 corridas / 3 días, ritmo irregular por sueño de la máquina) | archivo único SQLite |
| `data/raw/{mlb,kalshi,espn_tennis,sofascore}/*.json` | 63 MB, 1852 archivos | ~9 MB / ~265 archivos por corrida | `YYYYMMDDTHHMMSSffffffZ_<fuente>.json` (prefijo timestamp ISO8601 compacto, ordenable lexicográficamente) |
| `logs/run_e2e.stdout.log` / `.stderr.log` | 552 KB / 11 KB | crecimiento no acotado, sin rotación hoy | archivo único de texto plano |
| `data/normalized/` | 0 B | sin uso — 0 referencias en `src/`/`scripts/` | — |
| Espacio libre en disco | 129 GiB (9% usado) | — | — |

`data/normalized/` está vacío y sin ningún lector/escritor en el código (confirmado por
`grep`). Queda fuera del alcance operativo de esta política por no representar un
riesgo de crecimiento; se recomienda por separado evaluar si es un vestigio a eliminar.

## 2. Política por categoría

### 2.1 Datos históricos del motor — SIN CAMBIOS

`event_snapshots`, `feature_snapshots`, `event_results` (dentro de `data/engine.db`):
retención **indefinida**, sin purga, sin compactación, sin archivado en frío. Esta
política no introduce ningún mecanismo que las toque. Si el volumen se vuelve un
problema práctico de almacenamiento en el futuro, se diseñará una extensión
independiente (archivado en frío, explícitamente diferido — ver §5).

### 2.2 `data/raw/*.json` — rotación + compresión + purga

Estos archivos son una copia cruda de auditoría por request a cada API (MLB Stats
API, Kalshi, ESPN Tennis, SofaScore). No están referenciados por ningún cálculo en
tiempo de ejecución una vez que el registro normalizado ya fue persistido en
`engine.db` — su único uso confirmado en `src/` es un caso de investigación puntual
documentado en `payoff_model.py` (D-3), no una dependencia de producción.

| Antigüedad | Acción |
|---|---|
| 0–7 días | sin cambios (formato original, para depuración inmediata) |
| 7–90 días | comprimidos individualmente (`gzip`, mismo nombre + `.gz`) |
| > 90 días | eliminados |

### 2.3 `logs/run_e2e.stdout.log` / `.stderr.log` — rotación + compresión + purga

| Condición | Acción |
|---|---|
| Log activo excede 10 MB, o cambia el día calendario (UTC) | se rota: se cierra y renombra a `run_e2e.stdout.YYYYMMDD.log`, se abre un archivo nuevo |
| Rotado, 0–14 días | comprimido (`.log.gz`) |
| Rotado, > 14 días | eliminado |

### 2.4 `data/engine.db` — respaldo periódico (backup, no purga)

Backup **no sustituye** la retención indefinida de §2.1 — es una copia de
recuperación ante corrupción/pérdida del archivo, no un mecanismo de purga.

- Backup diario, vía la API de backup en caliente de SQLite (`sqlite3.Connection.backup()`
  / `sqlite3 engine.db ".backup ..."`), segura para ejecutarse concurrentemente con
  `run_e2e.py` (SQLite gestiona la consistencia página a página; no requiere pausar
  el pipeline ni el lock de instancia única).
- Destino: `data/backups/engine_YYYYMMDD.db`, comprimido inmediatamente después
  (`.db.gz`).
- Retención: últimos 30 backups diarios (rolling). Backups más antiguos se eliminan.
- Fuera de alcance de este repo: copia periódica a almacenamiento externo/fuera de
  la máquina — se documenta como recomendación operativa, no se automatiza aquí.

## 3. Parámetros (configurables, valores propuestos)

```python
RAW_UNCOMPRESSED_DAYS = 7
RAW_COMPRESSED_RETENTION_DAYS = 90
LOG_ROTATE_MAX_BYTES = 10 * 1024 * 1024
LOG_COMPRESSED_RETENTION_DAYS = 14
DB_BACKUP_RETENTION_COUNT = 30
```

Basados en la tasa de crecimiento real observada (§1): con estos parámetros, el
volumen estacionario proyectado es de ~1.2 GB para `data/raw` comprimido (90 días
× ritmo actual) y ~200 MB para 30 backups comprimidos de `engine.db` — muy por
debajo de los 129 GiB libres actuales. Son parámetros de configuración operativa,
no observaciones de dominio — ajustables sin implicar ningún cambio de contrato.

## 4. Mecanismo de implementación (IMPLEMENTADO)

Un único script nuevo, `scripts/data_maintenance.py`, con el mismo patrón de
`scripts/pipeline_lock.py` (lock de instancia única propio,
`data/.maintenance.lock`, para no solaparse consigo mismo) y **sin tocar**
`data/.run_e2e.lock` — opera sobre archivos ya cerrados y con antigüedad mínima de
1 día, nunca sobre el archivo de log activo ni sobre raws de la corrida en curso,
por lo que no requiere coordinación con el lock de `run_e2e.py`.

Puntos de seguridad explícitos:
- Nunca ejecuta `DELETE`/`UPDATE` contra `event_snapshots`/`feature_snapshots`/
  `event_results` — el script ni siquiera abre esas tablas; solo copia el archivo
  `.db` completo para el backup.
- Nunca opera sobre un archivo con menos de 1 día de antigüedad (margen de
  seguridad frente a una corrida en curso).
- Idempotente: ejecutarlo dos veces seguidas sin nuevos datos no produce cambios
  adicionales.

Programación propuesta: un **segundo** LaunchAgent independiente
(`scripts/launchd/local.prediction-market-engine.data-maintenance.plist`),
diario (`StartCalendarInterval`, ej. 03:00 hora local), versionado igual que el
de captura histórica. **No se carga automáticamente** — sigue el mismo protocolo
que D-1: el `.plist` queda como fuente de verdad versionada, `launchctl bootstrap`
solo se ejecuta con autorización explícita.

## 5. Fuera de alcance (diferido explícitamente)

- **Archivado en frío** de `event_snapshots`/`feature_snapshots`/`event_results`
  (mover a una segunda base de solo lectura para acotar el tamaño de `engine.db`
  sin perder datos). No se diseña ni se implementa en este paso — se evaluará como
  extensión independiente si el crecimiento real lo justifica.
- Backup fuera de la máquina (offsite/nube).
- Eliminación o repropósito de `data/normalized/` (vestigio sin uso) — señalado,
  no resuelto aquí.

## 6. Pruebas propuestas (si se autoriza la implementación del mecanismo)

Funciones puras (clasificar archivo → acción, dado nombre + antigüedad + "now"
inyectable, mismo patrón que `estimate_payoff`/`calibrate`), cubriendo: límites
exactos de los cortes de 7/90/14 días, no tocar archivos < 1 día, no tocar
`event_snapshots`/`feature_snapshots`/`event_results` (test negativo explícito
que falle si el script alguna vez importa `history_repository`), idempotencia,
y que el backup de `engine.db` no interfiere con un lock activo de `run_e2e.py`
(test de integración con lock simulado).

## 7. Documentación afectada

- `FASE2_CIERRE_FINAL.md` §7, punto 7: se marca resuelto por este documento.
- `CONTINUITY.md`: nueva entrada `§0.19` (ver commit de cierre).
- `TEMPORAL_REPRODUCIBILITY_SPEC.md`: sin cambios — este documento reafirma,
  no modifica, su invariante de inmutabilidad.
