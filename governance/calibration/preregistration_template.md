# PREREGISTRO — <prereg_id>

**Estado**: PLANTILLA. Un preregistro real se copia a `preregistrations/<prereg_id>.md`, se
firma **antes de cualquier entrenamiento** y se incorpora mediante PR revisable.

- `prereg_id`: <identificador seguro: letras, números, `_`, `.`, `-`>
- Autor y firmante: <nombre completo>
- Fecha de firma (UTC, ISO-8601): <YYYY-MM-DDTHH:MM:SS+00:00>
- `git_commit_base` (40 caracteres): <hash del commit de `main` usado>
- SHA-256 de este documento: se registra en `ledger.jsonl` (`PREREG_SIGNED`)
- Firma Git verificada: <sí/no/no disponible> (preferible; GPG no es obligatorio)

## 1. Objetivo
Decidir, con reglas fijadas de antemano, si el calibrador candidato puede proponerse para
promoción. No autoriza entrenar, promover, cablear ni desbloquear el Tramo 5A.

## 2. Contrato de veredicto
Vigente tal como se describe en `README.md` (τ = 1e-4; ECE y Brier; `n_min = 30`; fase 1 sobre
validación; veto único del test). Cualquier cambio exige un preregistro nuevo.

## 3. Datos congelados
- Modelo base: <model_version, SHA-256 del `.joblib` y del metadato>
- Snapshot: <snapshot_id, SHA-256 de la copia de la base, `cutoff_utc`>
- `models_dir` explícito para registrar y verificar artefactos y sidecars (nunca se deserializan)
- Mínimos entre intentos: ≥ 30 eventos nuevos en validación y ≥ 150 nuevos en total.

## 4. Intentos
Un intento por snapshot; repetir exige un snapshot nuevo. Todos los intentos se registran y todo
intento abierto termina en `FINAL_VERDICT` o `ATTEMPT_ABANDONED` (con motivo, autor y fecha, sin
métricas) antes de abrir otro. La evaluación solo opera con entradas ya aceptadas en `main`.

## 5. Restricciones
El test no se usa para ajustar nada. No se cambian umbrales, métricas, particiones ni
`cv_folds` después de ver resultados. ELEGIBLE no demuestra mejora ni autoriza promoción.

## 6. Entorno
<versiones de Python, scikit-learn, numpy, joblib>

Firma: ______________________   Fecha: ______________________
