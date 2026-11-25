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
| D2 | Los blobs, los artefactos y los datasets son **privados**. Git solo puede contener hashes, metadatos no sensibles y referencias gobernadas. | Nunca se versionan en git parámetros de modelo, filas de datasets ni capturas de mercado. Qué metadatos cuentan como "no sensibles" lo fija D6 (ver §2). |
| D3 | Autorizado explícitamente: el almacén local está **fuera del repositorio**; su raíz se suministra **explícitamente** mediante configuración o variable de entorno; se **rechazan** raíces ubicadas dentro del repositorio. | Nada más está decidido aquí. Los detalles que no se decidieron al aceptar D3 quedan delegados a PR-1 (ver §3.1). |
| D1 (parcial) | La selección del backend remoto específico se aplaza. **El uso local inicial no autoriza tratar el disco local como almacenamiento duradero suficiente para producción.** | Ningún artefacto destinado a producción puede depender únicamente del almacén local. Cualquier afirmación de "almacenamiento duradero" exige antes decidir D1 y D11. |
| D6 | Decidida el 2026-11-21. Los cinco objetos del flujo de un modelo son distintos y se relacionan solo por referencia: (1) **artefacto**: bytes inmutables, identificados en el almacén por su clave; (2) **metadatos**: documento canónico y versionado (`model_artifact_metadata`), también un blob del almacén, que describe procedencia, código, datos, entrenamiento, límites y validación del artefacto; (3) **manifiesto de paquete** (`artifact_package_manifest`): documento canónico, también un blob del almacén, que enlaza la clave del artefacto con la de los metadatos, fija sus hashes y versiones de esquema y declara el formato del artefacto (`artifact.format = "safe_json_b1"`); no es el manifiesto de instantánea del libro (`governance/calibration/snapshots/`) ni el `PolicyManifest` de `config/policy/`; (4) **registro** (`config/model_registry.json`): referencia el manifiesto aprobado por su clave y conserva el estado gobernado: los estados actuales son `ALLOWED`, `INVALID` y `REJECTED_CANDIDATE`, y la existencia de `REJECTED_CANDIDATE` no resuelve D15, que sigue pendiente para decidir su tratamiento durante la publicación de PR-7; (5) **libro y evaluador**: registran o consumen la decisión de evaluación o promoción sin duplicar los bytes del artefacto, de los metadatos ni del manifiesto. **Clave y hash.** Una *clave del almacén* es la cadena de 64 hexadecimales en minúsculas que acepta `validate_key` y que identifica un blob; es el SHA-256 de sus bytes (D4). La ruta interna `sha256/<2 hex>/<64 hex>` es solo la disposición del backend local, no aparece en documentos ni en la API y `validate_key` la rechaza. Los campos llamados `key` o `*_key` (por ejemplo `package_manifest_key`) contienen una clave del almacén y se validan con `validate_key`; los campos llamados `*_sha256` contienen exactamente 64 hexadecimales en minúsculas, el SHA-256 de unos bytes cualesquiera que no tienen por qué ser un blob del almacén. La referencia de un calibrador a su modelo base (`base_model_ref`) contiene `model_version` y `package_manifest_key`, validada con `validate_key`. **Qué se permite en Git:** identificación y versiones de esquema; procedencia pública; uso previsto y limitaciones; conteos y rangos temporales; hashes y referencias; métricas agregadas de validación y de test, siempre identificando su partición. **Nunca** listas completas de `event_id` ni resultados por `event_id`. Los metadatos de entrenamiento pueden contener métricas agregadas de validación; **las métricas de test solo las registra el evaluador en el libro.** Las listas completas de `event_id` de train, validation y test permanecen protegidas, fuera de Git, en el manifiesto de instantánea, que pasa a ser un blob del almacén; los hashes de esas listas aportan integridad, no confidencialidad. **Rutas (confirma D12 para los metadatos nuevos).** Ningún documento nuevo contiene rutas absolutas ni campos de ubicación local como `file_path` o `artifact_path`. `provenance.entrypoint` es una ruta relativa al repositorio, sin `..`, sin `/` inicial y sin forma absoluta de Windows; D12 no la prohíbe. | PR-2 define y verifica los esquemas del documento de metadatos y del manifiesto de paquete (el esquema campo por campo pertenece a `ARTIFACT_PACKAGE_SPEC.md`), únicamente para los dos `model_type` seguros de B1; MLB queda fuera. PR-2 no decide elegibilidad y no migra entrenadores, cargadores, registro, libro ni evaluador. Hasta que PR-5 resuelva el manifiesto de instantánea desde el almacén, **no se registra ningún `SNAPSHOT_FROZEN` real**: la herramienta actual (`load_registered_manifest`, `validate_snapshot_manifest`) exige versionar ese manifiesto, con las listas completas, bajo `governance/calibration/snapshots/`. |
| D18 | La réplica y la auditoría periódica por re-hash no van dentro de PR-1: van en un PR propio, PR-1b. PR-1 solo verifica la integridad de cada blob al leerlo. Decidida por el propietario durante la planificación de PR-1 y documentada en `CONTINUITY.md` §0.46 («Decisiones aplicadas», punto 1). | PR-1b sigue dependiendo de D11, que permanece pendiente. PR-1 no incluye réplica ni auditoría periódica. |
| D20 | Decidida el 2026-11-21. Se crea `governance/models/MODEL_CARD_TEMPLATE.md`. Es prerrequisito de PR-2, y PR-2 crea únicamente la plantilla: no crea ni aprueba ninguna model card de producción. La plantilla se limita a lo que D6 permite en Git y nunca admite listas de `event_id`. | Una model card real solo puede crearse al realizar una promoción real de un modelo (ver D8; PR-3 no promueve ningún modelo), mediante PR revisable. No sustituye al registro, al libro ni a los metadatos, que prevalecen. Dónde se guardan las model cards de producción sigue sin decidir. |
| D8 | Decidida el 2026-11-22, aprobada por el propietario para el alcance de PR-3. **Reversión.** Si una promoción se revierte porque el modelo no debe seguir activo, otro PR marca su entrada `INVALID`, registra el motivo en `reason` y enlaza la promoción citando en ese texto su PR o commit. La entrada se conserva y su `model_version` no se reutiliza para otro artefacto. **Reactivación.** Reactivar un modelo anterior exige un PR explícito; nunca hay retorno automático al modelo anterior. **Recuperación.** Git permite recuperar el estado del registro, no los archivos del modelo: estos solo se recuperan si el almacén lo permite (D1 y D11 siguen pendientes). **Estados.** Los tres existentes (D6): `ALLOWED`, `INVALID` y `REJECTED_CANDIDATE`; D8 no añade ninguno y D15 sigue pendiente. **Selección v2 (alcance actual de tenis).** Como máximo un modelo base `ALLOWED` en total y un calibrador `ALLOWED` por cada versión de modelo base. Dos o más candidatos `ALLOWED` bien formados en el grupo aplicable producen «sin modelo» solo para ese grupo, sin afectar a los demás: es un resultado de la selección, no un error de formato. Un error de validación rechaza toda la lista v2 (D16); una ambigüedad de selección afecta solo a un grupo. | PR-3 prueba la regla de selección v2 como lógica aislada, sin conectarla a ningún cargador; PR-4 la integra en los cargadores. PR-3 no cambia la selección heredada (`src/models/tennis_baseline.py` y `src/calibration/tennis_calibrator_training.py`, que hoy eligen en silencio entre varios `ALLOWED`). **Siguen pendientes, y esta aprobación no decide ninguno** (visibles en §4): cómo retirar un modelo sano antes de sustituirlo, cómo agrupar los modelos de otros deportes y qué requisitos debe cumplir la referencia del calibrador (si debe apuntar a una entrada v2 y en qué estado). D11 no bloquea este alcance de PR-3. Esta decisión no autoriza entrenamiento, promoción real ni el Tramo 5A, que siguen **BLOQUEADOS**. |
| D16 | Decidida el 2026-11-22, aprobada por el propietario para el alcance de PR-3. **Opción B.** El registro v2 vive en el mismo archivo, `config/model_registry.json`, como una lista opcional `package_models`, separada de `models`. **Entrada v2.** Lleva `model_version`, `status`, `reason`, `package_manifest_key` (una clave del almacén, D6) y `role`. `role` es obligatorio y sus únicos valores son `base` y `calibrator`. Una entrada `calibrator` exige `base_model_version`; una entrada `base` lo prohíbe. Un rol ausente o inválido, o una combinación incorrecta, es un error de validación v2: nunca se reclasifica la entrada como base. **Unicidad y estados.** Un `model_version` no puede aparecer dos veces, ni dentro de `package_models` ni entre `package_models` y `models`. Los estados son los tres existentes. **Rechazo de toda la lista v2.** Si `package_models` está presente pero no es una lista válida, o si alguna entrada incumple el esquema, los estados permitidos o la unicidad de `model_version`, el analizador rechaza toda la lista v2 con un error de validación. No descarta entradas individuales ni devuelve resultados parciales. Solo la ausencia de la clave se interpreta como lista vacía. El lector heredado sigue ignorando `package_models`. **Por qué no dentro de `models`.** El cargador heredado (`load_model_registry`) lee solo `models` e ignora las demás claves de nivel superior (comprobado el 2026-11-22 sobre `8b031d8`, aunque hoy ninguna prueba lo fija), pero rechaza todo el registro ante un `status` desconocido o un `model_version` repetido dentro de `models`. | PR-3 solo valida el registro v2: deja intacto el JSON de producción, no lee el almacén y no conecta el analizador a los cargadores. Añade una prueba que fija que el cargador heredado ignora `package_models`. PR-4 contrasta el rol declarado y, para un calibrador, su referencia al modelo base con el paquete verificado. D11 no bloquea este alcance de PR-3 (§4 la asocia a PR-1b y PR-7); lo ya decidido de D1 sigue vigente y nada de esto hace activable un modelo. El entrenamiento y el Tramo 5A siguen **BLOQUEADOS**. |
| D14 | Decidida el 2026-11-22, aprobada por el propietario (opción A, migración solo hacia adelante). **Sin conversión ni deserialización.** No se convierten ni se deserializan artefactos heredados como parte de la migración, y los cargadores seguros no recurren a ellos. Los dos existentes son `INVALID` y siguen solo como evidencia (§1, punto 1). **PR-4.** Añade cargadores seguros de tenis (modelo base y calibrador) desde el almacén, sin conectarlos a producción. Devuelven el modelo y los metadatos verificados, sin adaptar la interfaz de inferencia. **Cargadores heredados.** Quedan intactos en PR-4. Su retiro, el cableado de los cargadores nuevos y el tratamiento de MLB quedan para D22, que sigue pendiente. **Fallos esperados.** Los fallos esperados de configuración, selección, lectura, validación o concordancia con el registro devuelven «sin modelo» y dejan un motivo en el log, sin fallback entre formatos. No se capturan indiscriminadamente los errores inesperados de programación. | D14 no aprueba un esquema v2 de metadatos. La inferencia de tenis consume `feature_set_version` y `round_categories`, y los metadatos v1 no los representan (`ARTIFACT_PACKAGE_SPEC.md` §4, aplazados a `schema_version` 2): su representación sigue pendiente (§4, «Metadatos de inferencia») y debe definirse antes de que PR-7 publique modelos nuevos; PR-4 no los inventa ni los deduce. D22, D15, D11 y D1 siguen pendientes, y D11 no bloquea PR-4 (§4 la asocia a PR-1b y PR-7). Esta decisión no autoriza PR-4 ni ninguna promoción; el entrenamiento y el Tramo 5A siguen **BLOQUEADOS**. |

Ninguna de estas decisiones autoriza entrenamiento, evaluación real, promoción, `ELEGIBLE`, cableado
productivo ni el Tramo 5A.

---

## 3. Decisiones delegadas para su auditoría en PR-1

El propietario acepta estas recomendaciones **como decisiones de diseño para PR-1**, sujetas a auditoría
durante ese PR. Este documento no las implementa y PR-1 puede proponer ajustes justificados.

| ID | Diseño aceptado para PR-1 |
|---|---|
| D4 | Estructura de claves: la clave pública de un blob es una cadena de 64 caracteres hexadecimales en minúsculas (su SHA-256), sin extensión, y se valida con `validate_key`. `sha256/<2 caracteres hex>/<64 caracteres hex>` es solo la disposición interna del backend local, no una clave (`validate_key` la rechaza). Ningún consumidor entrega una ruta: quien llama entrega siempre una clave. |
| D5 | Inmutabilidad: escritura única. La versión es el hash de los bytes; el nombre legible es una etiqueta no autoritativa. `put` es idempotente: si el blob existe, verifica que sus bytes coincidan antes de aceptar. Una colisión de nombre con contenido distinto no sobrescribe nada; la unicidad de etiquetas se comprueba al promover (dependencia de D8; D6 y D8 están decididas, ver §2, con los pendientes de D8 en §4). |
| D7 | Publicación atómica: escritura en un directorio temporal del mismo sistema de archivos, `fsync` del archivo, enlace sin sobrescribir al destino, `fsync` del directorio y permisos de solo lectura. El registro solo referencia blobs completos. |
| D9 (local) | Escritor y lector separados: el código que carga modelos recibe una interfaz de solo lectura; solo el proceso de publicación puede escribir. Directorios `0700` y blobs `0444`. Las credenciales y principales de un backend remoto quedan aplazados. |
| D12 | Sin rutas absolutas en los artefactos y metadatos nuevos; la raíz del almacén viene de la configuración. Los `file_path` absolutos heredados y las rutas absolutas de los LaunchAgents no se tocan aquí (deuda aparte, ya documentada en §0.40). |

### 3.1 Detalles de D3 delegados a PR-1 (resueltos por PR-1)

Al aceptar D3 no se decidieron tres detalles, que PR-1 fijó y el propietario aceptó (`CONTINUITY.md` §0.46,
«Decisiones aplicadas»): (a) la raíz se lee de la variable de entorno `PME_ARTIFACT_STORE_ROOT`; (b) "dentro
del repositorio" se decide por ascendencia física (`st_dev`, `st_ino`) de la raíz y de sus ancestros, sin
examinar otros árboles de trabajo; (c) sin raíz suministrada, `LocalFilesystemStore.from_environment` lanza
`StoreConfigurationError`, y el constructor exige una raíz explícita.

---

## 4. Decisiones aplazadas

Siguen abiertas. Solo se documenta la pregunta, de qué dependen y qué PR bloquean; ninguna se da por
decidida.

| ID | Pregunta | Bloquea | Plazo |
|---|---|---|---|
| D1 | ¿Qué backend duradero específico usa producción? | PR-B; condiciona PR-7 y el desbloqueo del entrenamiento | Antes de PR-7 y de PR-B |
| D8 (pendientes) | D8 está decidida para el alcance de PR-3 (§2), pero siguen abiertas tres preguntas que esa aprobación no decide: (a) ¿cómo se retira un modelo sano antes de sustituirlo?; (b) ¿cómo se agrupan los modelos de otros deportes en la selección v2?; (c) ¿qué requisitos debe cumplir la referencia del calibrador (si debe apuntar a una entrada v2 y en qué estado)? | Sin asignar | Sin plazo fijado; (a) se necesita antes de la primera promoción real que sustituya a otro modelo |
| D9 (remoto) | ¿Quién escribe y quién lee en un backend remoto? | PR-B | Antes de PR-B |
| D10 | ¿Cuánto se retienen los blobs sin referencia y quién los limpia? | Ninguno de código por ahora | Antes de cualquier limpieza |
| D11 | ¿Qué respaldo y qué medio independiente se usa? | PR-1b, PR-7 y el desbloqueo del entrenamiento | Antes de PR-7 |
| D13 | ¿Qué se congela (extracto, copia de la base o ambos) y se prohíbe entrenar sobre la base viva en modo gobernado? | PR-6, PR-7 | Antes de PR-6 |
| D15 | ¿Qué ocurre si el modelo base termina `REJECTED_CANDIDATE`? | PR-7: es el primer PR cuyos entrenadores publican artefactos y metadatos, y los entrenadores son quienes calculan `REJECTED_CANDIDATE`. Hasta entonces el registro y los cargadores de tenis ya lo tratan como no activable (fail-closed) | Antes de PR-7 |
| D19 | ¿Se tocan los scripts de entrenamiento en un PR o en dos? | PR-6 | Antes de PR-6 |
| D21 | ¿Se autoriza un PR que haga alcanzable `ELEGIBLE`? | PR-8 | Después de PR-7 y con decisión explícita |
| D22 | ¿Cuándo se cablean los cargadores nuevos a producción, se retiran los de joblib de tenis y qué se hace con el cargador MLB sin guardián? | PR-9 | Después de que exista un modelo promovido |
| D23 | ¿Se implementa el backend remoto? | PR-B | Después de D1 |
| Metadatos de inferencia (esquema v2, sin ID) | ¿Cómo se representan `feature_set_version`, `round_categories` y los demás metadatos que requiere la inferencia? D14 (§2) no lo define ni aprueba un esquema v2. | PR-7 | Antes de que PR-7 publique modelos nuevos |

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
| Artefacto B1 (JSON de solo datos) como formato seguro de referencia | Existente (§0.44); migración solo hacia adelante decidida en D14 (§2): PR-4 añade cargadores seguros sin cablear; su cableado y el retiro de los heredados están aplazados (D22, PR-9), y la publicación por entrenamiento también (PR-7) |
| Documento de metadatos canónico que reemplaza al sidecar | Definido por D6; esquema en PR-2 |
| Registro como la única vía de promoción, con referencias por hash | Relación definida por D6; forma del registro v2 (D16) y reversión y selección (D8) decididas para el alcance de PR-3, ver §2 (pendientes de D8 en §4); implementación en PR-3 |
| Réplica y auditoría independientes | Aplazado (D11); alcance en PR-1b (D18 resuelta) |
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
| Selección ambigua entre varios modelos activos | P6 | PR-3 (regla de selección v2, D8; no cambia la heredada), PR-4 (cargadores) |

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
| PR-1b | Réplica verificada del almacén y auditoría por re-hash (depende de D11; D18 resuelta, ver §2). |
| PR-2 | Formato canónico del documento de metadatos y del manifiesto de paquete, verificación del paquete artefacto-metadatos y plantilla `governance/models/MODEL_CARD_TEMPLATE.md` (D6 y D20 resueltas, ver §2; D12 confirmada). |
| PR-3 | Registro v2 aditivo que permite entradas por hash y formato sin cambiar el comportamiento heredado (D8 y D16 decididas para este alcance, ver §2). Solo valida el registro v2: no toca el JSON de producción, no lee el almacén y no se conecta a los cargadores. |
| PR-4 | Cargadores seguros desde el almacén, sin cablear (D14 decidida, ver §2). No convierte ni deserializa artefactos heredados, no recurre a ellos y no modifica los cargadores heredados. |
| PR-5 | El libro y el evaluador resuelven los manifiestos de instantánea desde el almacén mediante una abstracción de resolución, conservando el comportamiento heredado por ruta (alcance en §8.1). |
| PR-6 | `--db-path`, modo gobernado, congelado de datos y herramienta del manifiesto (depende de D13, D19). |
| PR-7 | Los entrenadores publican artefactos B1 y metadatos en el almacén, solo con pruebas sintéticas (depende de D11, D15). |
| PR-8 | Proveedor de métricas del test. Haría alcanzable `ELEGIBLE`; requiere decisión explícita (D21). |
| PR-9 | Cableado a producción y retiro de cargadores joblib de tenis, solo con un modelo ya promovido (D22). |
| PR-B | Backend remoto privado, solo tras D1 y D23. |

### 8.1 Alcance de PR-5

Este apartado delimita el contenido de PR-5. Como todo PR de §8, requiere autorización explícita y una auditoría de solo lectura previa: **este texto no las concede**.

**Qué hace PR-5.** El libro de calibración y el evaluador resuelven los manifiestos de instantánea desde el almacén, además de por ruta. El comportamiento heredado por ruta se conserva sin cambios.

**Reglas del alcance**

- **Una sola referencia.** `SNAPSHOT_FROZEN` admite exactamente uno de `manifest_path` o `manifest_key`. Una referencia por clave se resuelve solo en el almacén y una por ruta solo en el repositorio: si la resolución falla, no se recurre al otro modo. En el modo por clave, `manifest_sha256` es obligatorio e igual a `manifest_key`.
- **Blob por clave.** Los bytes del blob deben coincidir byte por byte con `manifest_bytes()` del manifiesto validado. El límite es de 262 144 bytes inclusive (un blob de exactamente 262 144 bytes se acepta y uno de 262 145 se rechaza) y se comprueba antes de analizar. La lectura rechaza claves JSON duplicadas, `NaN` e `Infinity`. Estas exigencias de lectura se aplican solo al modo por clave: la lectura por ruta no cambia.
- **Fallo de verificación por falta de acceso al almacén.** Si el libro contiene manifiestos referenciados por clave y no hay acceso al almacén, la verificación completa falla e identifica los manifiestos que quedaron sin verificar. Es un fallo distinto de una cadena de hashes rota y de un blob ausente, corrupto o inválido en un almacén accesible. El mensaje solo afirma que la cadena de hashes o el prefijo con la base se verificaron si esas comprobaciones se ejecutaron y pasaron.
- **Lo que se conserva.** El evaluador no importa `package_loaders`. `BASE_TRAINED`, `CALIBRATOR_TRAINED` y sus comprobaciones actuales (sidecar y artefacto heredados) no cambian. `ELEGIBLE` sigue sin ser alcanzable: el evaluador se detiene con `SafeLoadRequiredError`.

**Fuera de PR-5.** La validación de `dataset_manifest_ref` desde un paquete, la verificación de paquetes de base y calibrador por el libro, las métricas, `trained_at`, `git_commit` y el estado en el registro quedan aplazadas; `ARTIFACT_PACKAGE_SPEC.md` §8 explica la dependencia de cada una. La construcción y publicación del manifiesto de instantánea conserva su alcance en PR-6.

**Registro real.** La fusión de PR-5 no autoriza registrar ningún `SNAPSHOT_FROZEN` real.

- *Reglas vigentes ya documentadas:* D6 impide registrar ninguno hasta que el manifiesto se resuelva desde el almacén; `governance/calibration/README.md` y `CONTINUITY.md` §0.42–§0.43 exigen preregistro firmado antes del entrenamiento, el intento anterior cerrado, un mínimo de eventos nuevos y el ancla en `main`; y D1 (parcial) establece que ningún artefacto destinado a producción puede depender únicamente del almacén local.
- *Requisitos propuestos, no aprobados:* que D13 y D19 estén decididas, que el manifiesto se publique en el almacén con una herramienta o un procedimiento documentado, y que el manifiesto no dependa únicamente del almacén local (aplicación propuesta de D1 al libro).

---

## 9. Puntos de parada humana

- Tras cada PR: auditoría de solo lectura del PR, merge manual, sincronización de `main` y cierre documental
  en `CONTINUITY.md`.
- **Antes de PR-1:** auditoría de solo lectura del repositorio y confirmación del alcance y de las decisiones
  delegadas (§3).
- **Antes de cerrar PR-1:** D18, ya resuelta a favor de PR-1b (ver §2).
- **Antes de PR-1b:** decidir D11.
- **Antes de PR-2:** D6 y D20 resueltas (ver §2) y D12 confirmada para los metadatos nuevos.
- **Antes de PR-3:** D8 y D16 decididas para el alcance de PR-3 (ver §2). Los pendientes de D8 (§4: retirar un modelo sano, agrupar otros deportes y requisitos de la referencia del calibrador) no se deciden con esa aprobación y no forman parte del alcance de PR-3.
- **Antes de PR-4:** D14 decidida (ver §2). D22 sigue pendiente y no forma parte del alcance de PR-4.
- **Antes de PR-6:** decidir D13 y D19.
- **Antes de PR-7:** decidir D11, D15 y D1.
- **Antes de que PR-7 publique modelos nuevos:** definir la representación de los metadatos de inferencia (ver §4). D14 no aprueba un esquema v2.
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
