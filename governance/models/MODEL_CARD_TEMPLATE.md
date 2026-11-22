# MODEL CARD — <model_version>

**Estado**: PLANTILLA. Esto no es una model card real, no es una model card de producción y no aprueba nada. Una
model card real solo puede crearse al promover un modelo (`ARTIFACT_STORAGE_DECISION.md`, D8 y PR-3), se copia a su
propia ruta y se incorpora mediante PR revisable. No sustituye al registro (`config/model_registry.json`), al libro ni
a los metadatos del paquete, que prevalecen: ante cualquier discrepancia manda el registro.

**Qué puede contener (D6)**: identificación y versiones de esquema; procedencia pública; uso previsto y limitaciones;
conteos y rangos temporales; hashes y referencias; métricas agregadas con su partición. **Nunca** listas completas de
`event_id` ni resultados por `event_id`, y nunca rutas absolutas ni campos de ubicación local. Las métricas de test
solo las registra el evaluador en el libro: aquí se cita su entrada, no se calculan ni se copian de otro lugar.

Un paquete verificado por `verify_package` prueba integridad y coherencia de sus tres blobs; no prueba que el modelo
sea bueno, no lo activa y no sustituye la decisión humana de promoverlo.

## 1. Identificación

- `model_version`: <identificador, como en el manifiesto de paquete>
- `model_type`: <imputed_standardized_logreg_v1 o platt_logreg_1d_v1>
- Clave del manifiesto de paquete (`package_manifest_key`, clave del almacén de 64 hexadecimales): <clave>
- Estado en `config/model_registry.json` y fecha de consulta: <estado copiado del registro; esta plantilla no lo decide>

## 2. Uso previsto y límites

- Uso previsto (`limits.intended_use`, máximo 500 caracteres): <texto>
- Limitaciones conocidas (`limits.known_limitations`, hasta 20, máximo 300 caracteres cada una): <lista>
- Para qué NO debe usarse: <texto>

## 3. Procedencia

- Commit de código (`provenance.git_commit`, 40 hexadecimales) y si el árbol estaba limpio (`git_tree_clean`): <dato>
- Punto de entrada (`provenance.entrypoint`, ruta relativa al repositorio): <ruta>
- Entorno (`python`, `scikit_learn`): <versiones>
- Preregistro y su firma, si existen: <referencia>

## 4. Datos

Solo conteos, rangos temporales y referencias. Ninguna lista de eventos.

- Referencia al manifiesto de instantánea (blob protegido): <clave del almacén y versión de esquema>
- Conteos por partición (eventos y muestras de train, validation y test): <números>
- Rango temporal de cada partición: <desde y hasta, en UTC>

## 5. Entrenamiento

- Fecha de entrenamiento (`trained_at`, UTC): <fecha>
- Columnas de entrada (solo modelo base): <referencia a `training.feature_columns`>
- Modelo base al que está atado (solo calibrador, `base_model_ref`): <model_version y clave del manifiesto de su paquete>
- Hiperparámetros y mínimos de política aplicados: <datos>

## 6. Validación

Métricas agregadas de validación, siempre indicando su partición. Nunca resultados por evento.

- Partición: <validation>
- Número de eventos y métricas agregadas (Brier, log-loss, ECE): <valores>

## 7. Resultado del test

El test se lee una sola vez, y su resultado lo registra únicamente el evaluador en el libro.

- Entrada del libro que lo registra (`TEST_READ` y `TEST_RESULT`) y su hash: <referencia>
- Veredicto final del libro: <referencia; no se interpreta aquí>

## 8. Riesgos y limitaciones

- Riesgos conocidos del modelo y de los datos: <texto>
- Qué evidencia falta para confiar en él: <texto>

## 9. Aprobación

La aprobación es una decisión humana, separada y registrada por PR; esta plantilla no la otorga.

- PR de promoción: <enlace o número>
- Aprobado por y fecha (UTC): <nombre y fecha>

Firma: ______________________   Fecha: ______________________
