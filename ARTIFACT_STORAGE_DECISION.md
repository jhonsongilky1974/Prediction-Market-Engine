# Decisión: gobernanza del almacenamiento de artefactos de modelo (PR-0)

**Estado: REGISTRO DE DECISIONES, SOLO DOCUMENTAL (2026-10-05).** Decidido por el propietario del
proyecto en el chat de la sesión. Este documento fija qué está decidido, qué se delega para su auditoría
en PR-1 y qué sigue pendiente. **No implementa nada**: no hay código, pruebas, configuración, scripts, datos
ni artefactos en este PR (ver §10).

Contexto vinculante: `CONTINUITY.md` §0.42 (gobernanza y ancla del libro), §0.43 (cierre del PR #10) y §0.44
(cierre del PR #11, formato JSON de solo datos). El formato y su verificación existen
(`SAFE_ARTIFACT_FORMAT_SPEC.md`) pero **no están cableados a producción**. El entrenamiento y el Tramo 5A
permanecen **BLOQUEADOS**.

---

## 1. Hechos comprobados

Verificados sobre `main` en `33044819f0a885a58964983aec36362084eb3415` el 2026-10-05. Los números de línea
son los de esa fecha y pueden desplazarse.

1. **No existe ningún modelo `ALLOWED`.** `config/model_registry.json` solo declara dos entradas `INVALID`
   (el modelo base de tenis con fuga temporal y su calibrador Platt). Sus cuatro archivos siguen en
   `data/models/` solo como evidencia. Qué hacer con estos dos artefactos `INVALID` y cómo se migra desde
   joblib/pickle sigue pendiente (D14).
2. **Escritura de artefactos sin atomicidad y con versión al segundo.** `joblib.dump` y `write_text` escriben
   directamente al destino final (`src/models/tennis_baseline.py:881-882`,
   `src/calibration/tennis_calibrator_training.py:228-229`, `src/models/mlb_baseline.py:426-427`). La versión
   usa el timestamp con resolución de un segundo (`{now:%Y%m%dT%H%M%SZ}`); dos entrenamientos en el mismo
   segundo escribirían sobre los mismos nombres.
3. **Los cargadores de tenis verifican el hash antes de deserializar joblib**
   (`tennis_baseline.py:644-646`, `tennis_calibrator_training.py:362-365`), pero deserializan joblib.
4. **El cargador de MLB no verifica nada.** `src/models/registry.py:77-79` hace
   `joblib.load(latest_data["file_path"])` con una ruta leída de un metadato, sin hash ni registro, y está
   conectado a producción mediante `SPORT_ADAPTERS[MLB]` (`scripts/run_e2e.py:58`). Hoy no hay ningún
   artefacto MLB en `data/models/`.
5. **`data/models/` está ignorado por git** (`.gitignore:9-10`) **y no tiene respaldo**:
   `scripts/data_maintenance.py` solo respalda `data/engine.db`, y esa copia es local.
6. **Los scripts de entrenamiento usan siempre la base viva**: `HistoryRepository()` sin argumentos
   (`scripts/train_tennis_model.py:54`, `scripts/train_tennis_calibrator.py:70`,
   `scripts/train_mlb_model.py:56`, `scripts/train_mlb_elo_model.py:49`). No existe `--db-path`.
7. **Existe el formato B1 y la gobernanza de evaluación**, sin cablear: el evaluador no deserializa y se
   detiene con `SafeLoadRequiredError` ante un candidato `ELEGIBLE_PRELIMINAR`.
8. **El repositorio es público** y **no hay CI configurado** (0 workflows de GitHub Actions).
9. **No existe `MODEL_CARD_TEMPLATE.md`** en el repositorio.
10. El almacén actual (`data/models/`) está en el mismo volumen que el repositorio y que `data/engine.db`.

---

## 2. Decisiones aceptadas

| ID | Decisión | Consecuencia normativa |
|---|---|---|
| D17 | PR-0 es exclusivamente documental y es el primer paso. | Ningún código ni configuración antes de que PR-0 se audite y se fusione. |
| D2 | Los blobs, los artefactos y los datasets son **privados**. Git solo puede contener hashes, metadatos no sensibles y referencias gobernadas. | Nunca se versionan en git parámetros de modelo, filas de datasets ni capturas de mercado. Qué metadatos cuentan como "no sensibles" se concreta en PR-2 (ver §4, D6); no se asume aquí. |
| D3 | Autorizado explícitamente: el almacén local está **fuera del repositorio**; su raíz se suministra **explícitamente** mediante configuración o variable de entorno; se **rechazan** raíces ubicadas dentro del repositorio. | Nada más está decidido aquí. Los detalles que no se decidieron al aceptar D3 quedan delegados a PR-1 (ver §3.1). |
| D1 (parcial) | La selección del backend remoto específico se aplaza. **El uso local inicial no autoriza tratar el disco local como almacenamiento duradero suficiente para producción.** | Ningún artefacto destinado a producción puede depender únicamente del almacén local. Cualquier afirmación de "almacenamiento duradero" exige antes decidir D1 y D11. |

Ninguna de estas decisiones autoriza entrenamiento, evaluación real, promoción, `ELEGIBLE`, cableado
productivo ni el Tramo 5A.

---

## 3. Decisiones delegadas para su auditoría en PR-1

El propietario acepta estas recomendaciones **como decisiones de diseño para PR-1**, sujetas a auditoría
durante ese PR. Este documento no las implementa y PR-1 puede proponer ajustes justificados.

| ID | Diseño aceptado para PR-1 |
|---|---|
| D4 | Estructura de claves: `sha256/<2 caracteres hex>/<64 caracteres hex>`, en minúsculas y sin extensión. Quien llama entrega siempre un hash, nunca una ruta. |
| D5 | Inmutabilidad: escritura única. La versión es el hash de los bytes; el nombre legible es una etiqueta no autoritativa. `put` es idempotente: si el blob existe, verifica que sus bytes coincidan antes de aceptar. Una colisión de nombre con contenido distinto no sobrescribe nada; la unicidad de etiquetas se comprueba al promover (dependencia de D6 y D8, pendientes). |
| D7 | Publicación atómica: escritura en un directorio temporal del mismo sistema de archivos, `fsync` del archivo, enlace sin sobrescribir al destino, `fsync` del directorio y permisos de solo lectura. El registro solo referencia blobs completos. |
| D9 (local) | Escritor y lector separados: el código que carga modelos recibe una interfaz de solo lectura; solo el proceso de publicación puede escribir. Directorios `0700` y blobs `0444`. Las credenciales y principales de un backend remoto quedan aplazados. |
| D12 | Sin rutas absolutas en los artefactos y metadatos nuevos; la raíz del almacén viene de la configuración. Los `file_path` absolutos heredados y las rutas absolutas de los LaunchAgents no se tocan aquí (deuda aparte, ya documentada en §0.40). |

### 3.1 Detalles de D3 que quedan delegados a PR-1 (no decididos)

Al aceptar D3 **no** se decidió: (a) el nombre de la variable de entorno o de la clave de configuración;
(b) el criterio exacto de "dentro del repositorio" (rutas reales, enlaces simbólicos, árboles de trabajo
adicionales); (c) qué ocurre cuando no se suministra la raíz. PR-1 debe proponerlos y justificarlos respetando
lo autorizado explícitamente en §2 (fuera del repositorio, raíz suministrada explícitamente, raíces internas
rechazadas); quedan sujetos a su auditoría.

---

## 4. Decisiones aplazadas

Siguen abiertas. Solo se documenta la pregunta, de qué dependen y qué PR bloquean; ninguna se da por
decidida.

| ID | Pregunta | Bloquea | Plazo |
|---|---|---|---|
| D1 | ¿Qué backend duradero específico usa producción? | PR-B; condiciona PR-7 y el desbloqueo del entrenamiento | Antes de PR-7 y de PR-B |
| D6 | ¿Qué relación exacta hay entre artefacto, documento de metadatos, manifiesto, registro y libro, y qué metadatos son "no sensibles" (incluidas las listas de `event_id` de los manifiestos)? | PR-2, PR-3 | Antes de PR-2 |
| D8 | ¿Cómo se recupera y revierte una promoción? | PR-3 | Antes de PR-3 |
| D9 (remoto) | ¿Quién escribe y quién lee en un backend remoto? | PR-B | Antes de PR-B |
| D10 | ¿Cuánto se retienen los blobs sin referencia y quién los limpia? | Ninguno de código por ahora | Antes de cualquier limpieza |
| D11 | ¿Qué respaldo y qué medio independiente se usa? | PR-1b, PR-7 y el desbloqueo del entrenamiento | Antes de PR-7 |
| D13 | ¿Qué se congela (extracto, copia de la base o ambos) y se prohíbe entrenar sobre la base viva en modo gobernado? | PR-6, PR-7 | Antes de PR-6 |
| D14 | ¿Cómo se migra desde joblib/pickle? | PR-4, PR-9 | Antes de PR-4 |
| D15 | ¿Qué ocurre si el modelo base termina `REJECTED_CANDIDATE`? | PR-2, PR-7 | Antes de PR-7 |
| D16 | ¿El registro v2 va en el mismo archivo con un discriminador de formato o en un módulo nuevo? | PR-3, PR-4 | Antes de PR-3 |
| D18 | ¿La réplica y la auditoría por re-hash van dentro de PR-1 o en un PR propio (PR-1b)? | PR-1b, PR-7 | Antes de cerrar PR-1 |
| D19 | ¿Se tocan los scripts de entrenamiento en un PR o en dos? | PR-6 | Antes de PR-6 |
| D20 | ¿Se crea `MODEL_CARD_TEMPLATE.md` (hoy inexistente) y dónde? | Ninguno (opcional) | Antes de PR-2 |
| D21 | ¿Se autoriza un PR que haga alcanzable `ELEGIBLE`? | PR-8 | Después de PR-7 y con decisión explícita |
| D22 | ¿Cuándo se cablean los cargadores nuevos a producción, se retiran los de joblib de tenis y qué se hace con el cargador MLB sin guardián? | PR-9 | Después de que exista un modelo promovido |
| D23 | ¿Se implementa el backend remoto? | PR-B | Después de D1 |

---

## 5. Arquitectura objetivo provisional

**Provisional**: describe la dirección, no un diseño aprobado. Los elementos marcados dependen de decisiones
aplazadas y pueden cambiar.

| Componente | Estado |
|---|---|
| Almacén direccionado por contenido: la identidad de un blob es el SHA-256 de sus bytes canónicos | Delegado a PR-1 (D4, D5) |
| Interfaz de almacén independiente del backend (`put`, `get`, `exists`, `verify`) con un backend local inicial | Delegado a PR-1 |
| Raíz local fuera del repositorio, suministrada explícitamente | Aceptado (D3) |
| Escritura única, atómica, con verificación del hash en cada lectura | Delegado a PR-1 (D5, D7) |
| Artefacto B1 (JSON de solo datos) como formato seguro de referencia | Existente (§0.44); su adopción por entrenamiento y cargadores está aplazada (D14, PR-4, PR-7) |
| Documento de metadatos canónico que reemplaza al sidecar | Provisional (D6, D12) |
| Registro como la única vía de promoción, con referencias por hash | Provisional (D6, D8, D16) |
| Réplica y auditoría independientes | Aplazado (D11, D18) |
| Backend remoto privado | Aplazado (D1, D23) |

**Publicar no es promover.** Publicar un blob en el almacén no cambia ningún comportamiento ni activa ningún
modelo. Solo una entrada aprobada por PR en el registro puede hacer activable un modelo, como hoy.

**Qué vive dónde (provisional):** los bytes (artefactos, metadatos, datasets) en el almacén privado; los
hashes, las decisiones y la evidencia (registro, libro, manifiestos) en git.

**Fail-closed:** hash que no coincide, blob ausente, versión distinta de la esperada, configuración inválida o
selección ambigua devuelven "sin modelo" y nunca una probabilidad inventada.

---

## 6. Amenazas y propiedades de seguridad

### 6.1 Propiedades objetivo

| ID | Propiedad |
|---|---|
| P1 | Identidad por contenido: dos blobs son el mismo si y solo si tienen el mismo SHA-256. |
| P2 | Verificación en cada lectura: nunca se entregan bytes cuyo hash no coincide con la clave. |
| P3 | Inmutabilidad: un blob publicado no se sobrescribe. |
| P4 | Atomicidad: ningún lector ve un blob parcial. |
| P5 | Privacidad: ningún blob, artefacto ni dataset llega a git. |
| P6 | Fail-closed en cualquier incoherencia. |
| P7 | Separación entre publicación y promoción. |
| P8 | Sin confianza en rutas: las rutas nunca vienen del llamador ni de metadatos. |
| P9 | Sin deserialización de código en los artefactos nuevos (B1). |

### 6.2 Amenazas cubiertas por el diseño propuesto

| Amenaza | Propiedad | PR que la trata |
|---|---|---|
| Recorrido de rutas o enlaces simbólicos hacia fuera del almacén | P8 | PR-1 |
| Escritura parcial por caída del proceso | P4 | PR-1 |
| Sobrescritura de un artefacto o colisión de versión | P3 | PR-1, PR-7 |
| Sustitución de bytes bajo el mismo nombre | P1, P2 | PR-1 |
| Corrupción silenciosa de un blob | P2 | PR-1 |
| Lectura TOCTOU entre verificar y usar | P2 | PR-1 |
| Un almacén colocado dentro del repositorio y subido por error | P5 | PR-1 (rechazo de raíces internas) |
| Modelo cruzado o metadatos de otro modelo | P1, P6 | PR-2 |
| Ejecución de código al cargar un artefacto | P9 | Ya cubierta por B1 (§0.44) |
| Selección ambigua entre varios modelos activos | P6 | PR-3, PR-4 (dependen de D16) |

### 6.3 Amenazas no cubiertas

- **Pérdida del disco o del equipo**: el almacén local no es durable (D1 parcial, D11 pendientes).
- **Procedencia, calidad y validez estadística**: un hash prueba identidad de bytes, nada más.
- **Compromiso de `main` o de quien lo controla**, y parámetros maliciosos pero válidos con un hash
  legítimamente registrado.
- **Un atacante con los mismos privilegios locales** que el proceso de publicación.
- **Compromiso de un respaldo o de un backend remoto**: se tratará cuando se decida D1.
- **Canales laterales** y metadatos que se filtren por referencias en git.

---

## 7. Límites y fuera de alcance

- El almacén local **no es** almacenamiento duradero suficiente para producción (D1 parcial).
- No se selecciona ni se implementa ningún backend remoto (D1, D23).
- No se decide la migración desde joblib/pickle (D14); no se modifican los cargadores heredados.
- No se decide qué se congela de la base de datos (D13) ni se añade `--db-path`.
- No se decide el comportamiento ante `REJECTED_CANDIDATE` (D15).
- No hay respaldo, réplica, retención ni limpieza definidos (D10, D11).
- No se toca `config/model_registry.json`, el libro, los manifiestos ni la gobernanza existente.
- No se cablea nada a producción ni se retiran cargadores.
- El formato B1 solo cubre las dos familias de modelo de tenis ya definidas; no se extiende a MLB.
- `CONTINUITY.md` **no** se modifica en este PR; su cierre documental seguirá, como en los PR anteriores, tras
  el merge.

---

## 8. Secuencia de PR propuesta

**Propuesta, no autorizada.** Cada PR requiere autorización explícita del propietario y una auditoría de solo
lectura previa; ninguno puede tocar `config/model_registry.json`, `data/`, `src/orchestration/`, los
cargadores heredados ni los scripts de entrenamiento salvo que su alcance lo diga expresamente.

| PR | Contenido |
|---|---|
| PR-0 (este) | Registro de decisiones y adenda a `DATA_RETENTION_POLICY.md`; solo documentación. |
| PR-1 | Interfaz `ArtifactStore` y backend de sistema de archivos local, direccionado por hash, con escritura única atómica y verificación en cada lectura; sin cablear. |
| PR-1b | Réplica verificada del almacén y auditoría por re-hash (depende de D11 y D18). |
| PR-2 | Formato canónico del documento de metadatos y verificación del paquete artefacto-metadatos (depende de D6, D12, D20). |
| PR-3 | Registro v2 aditivo que permite entradas por hash y formato sin cambiar el comportamiento heredado (depende de D8, D16). |
| PR-4 | Cargadores seguros desde el almacén, sin cablear (depende de D14). |
| PR-5 | El libro y el evaluador verifican desde el almacén mediante una abstracción de resolución. |
| PR-6 | `--db-path`, modo gobernado, congelado de datos y herramienta del manifiesto (depende de D13, D19). |
| PR-7 | Los entrenadores publican artefactos B1 y metadatos en el almacén, solo con pruebas sintéticas (depende de D11, D15). |
| PR-8 | Proveedor de métricas del test. Haría alcanzable `ELEGIBLE`; requiere decisión explícita (D21). |
| PR-9 | Cableado a producción y retiro de cargadores joblib de tenis, solo con un modelo ya promovido (D22). |
| PR-B | Backend remoto privado, solo tras D1 y D23. |

---

## 9. Puntos de parada humana

- Tras cada PR: auditoría de solo lectura del PR, merge manual, sincronización de `main` y cierre documental
  en `CONTINUITY.md`.
- **Antes de PR-1:** auditoría de solo lectura del repositorio y confirmación del alcance y de las decisiones
  delegadas (§3).
- **Antes de cerrar PR-1:** decidir D18 (si la réplica y la auditoría por re-hash van dentro de PR-1 o en PR-1b).
- **Antes de PR-1b:** decidir D11.
- **Antes de PR-2:** decidir D6 (incluida la clasificación de los metadatos "no sensibles") y D20; confirmar D12 (ya delegada a PR-1).
- **Antes de PR-3:** decidir D8 y D16.
- **Antes de PR-4:** decidir D14.
- **Antes de PR-6:** decidir D13 y D19.
- **Antes de PR-7:** decidir D11, D15 y D1.
- **Antes de PR-8, PR-9 y PR-B:** autorización explícita y específica de cada uno (D21, D22, D23).
- **Siempre aparte:** el desbloqueo del entrenamiento y del Tramo 5A es una decisión humana explícita y
  separada; ningún PR de esta secuencia la implica.

---

## 10. Declaración explícita

**PR-0 no implementa almacenamiento, no publica artefactos, no cambia cargadores y no desbloquea el
entrenamiento ni el Tramo 5A.** Tampoco autoriza evaluación real, promoción, que `ELEGIBLE` sea alcanzable,
cableado productivo ni el uso del conjunto test. El entrenamiento y el Tramo 5A permanecen **BLOQUEADOS** por
las razones ya documentadas en `CONTINUITY.md` §0.38–§0.44.

---

## 11. Datos no verificados

- Qué medio de respaldo independiente existe (D11) y si existe alguna infraestructura de nube: ningún
  documento la declara, pero no se ha podido comprobar.
- Qué LaunchAgents están cargados en este momento (solo se revisaron sus plantillas y archivos instalados).
- El esfuerzo de adaptar la construcción del dataset a un extracto (D13): no medido.
- Que el cargador MLB sin guardián sea explotable: deducido de leer el código, no probado.
- Que dos entrenamientos en el mismo segundo se sobrescriban: deducido del código, no observado.
- Las secciones históricas de `CONTINUITY.md` anteriores a §0.38 se revisaron solo por palabras clave.
