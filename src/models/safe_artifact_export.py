"""Exportadores de objetos de scikit-learn YA AJUSTADOS a artefactos JSON de solo datos (B1; ver
`SAFE_ARTIFACT_FORMAT_SPEC.md`).

Condiciones:

* Solo reciben objetos en memoria. NO leen archivos, NO usan joblib ni pickle, NO escriben nada:
  devuelven `bytes` canónicos y quien los llama decide qué hacer con ellos (almacenamiento fuera de
  alcance).
* scikit-learn (y numpy) se importan PEREZOSAMENTE dentro de cada exportador; importar este módulo
  no importa scikit-learn.
* Solo aceptan tipos EXACTOS (no subclases) y configuraciones cerradas; cualquier variante no
  autorizada lanza `ArtifactExportError`.
* Ningún `__init__`, flujo existente, entrenamiento, evaluación o cargador heredado los invoca: no
  están cableados a nada.
* Antes de devolver los bytes comprueban que `load_artifact` los acepta (autoverificación).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

from src.models.safe_artifact_format import (
    MODEL_TYPE_IMPUTED_LOGREG,
    MODEL_TYPE_PLATT,
    SCHEMA_VERSION,
    ArtifactExportError,
    SafeArtifactError,
    artifact_sha256,
    canonical_bytes,
    load_artifact,
)

_PIPELINE_STEP_NAMES = ("imputer", "scaler", "logreg")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactExportError(message)


def _fitted(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except AttributeError as exc:
        raise ArtifactExportError(f"objeto sin ajustar: falta el atributo {name!r}") from exc


def _floats(array: Any, expected_shape: tuple, where: str) -> List[float]:
    import numpy as np

    _require(isinstance(array, np.ndarray) and array.dtype == np.float64, f"{where}: se esperaba un ndarray float64")
    _require(array.shape == expected_shape, f"{where}: forma {array.shape} distinta de la esperada {expected_shape}")
    return [float(x) for x in array.reshape(-1)]


def _check_binary_logreg(logreg: Any, n_features: int, where: str) -> None:
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    _require(type(logreg) is LogisticRegression, f"{where}: se esperaba exactamente LogisticRegression")
    _require(logreg.get_params().get("fit_intercept") is True, f"{where}: fit_intercept debe ser True")
    classes = _fitted(logreg, "classes_")
    _require(
        isinstance(classes, np.ndarray) and classes.shape == (2,) and classes.dtype.kind in "iu"
        and [int(c) for c in classes] == [0, 1],
        f"{where}: classes_ debe ser exactamente [0, 1]",
    )
    coef = _fitted(logreg, "coef_")
    _require(
        isinstance(coef, np.ndarray) and coef.shape == (1, n_features), f"{where}: coef_ debe tener forma (1, {n_features})"
    )


def export_imputed_logreg_pipeline(pipeline: Any, *, model_version: str, input_columns: Sequence[str]) -> bytes:
    """Exporta `Pipeline([("imputer", SimpleImputer(median)), ("scaler", StandardScaler()), ("logreg",
    LogisticRegression())])` ya ajustado. `input_columns` es el orden de las columnas con que se ajustó."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    _require(type(pipeline) is Pipeline, "se esperaba exactamente sklearn.pipeline.Pipeline")
    _require(
        tuple(name for name, _ in pipeline.steps) == _PIPELINE_STEP_NAMES,
        f"los pasos del Pipeline deben ser exactamente {list(_PIPELINE_STEP_NAMES)} en ese orden",
    )
    imputer, scaler, logreg = (step for _, step in pipeline.steps)
    _require(type(imputer) is SimpleImputer, "el paso 'imputer' debe ser exactamente SimpleImputer")
    _require(type(scaler) is StandardScaler, "el paso 'scaler' debe ser exactamente StandardScaler")
    _require(type(logreg) is LogisticRegression, "el paso 'logreg' debe ser exactamente LogisticRegression")
    _require(
        isinstance(input_columns, (list, tuple)) and all(type(c) is str for c in input_columns) and len(input_columns) > 0,
        "input_columns debe ser una lista no vacía de texto",
    )

    ip = imputer.get_params()
    _require(ip.get("strategy") == "median", "SimpleImputer: strategy debe ser 'median'")
    missing = ip.get("missing_values")
    _require(isinstance(missing, float) and math.isnan(missing), "SimpleImputer: missing_values debe ser NaN")
    _require(ip.get("add_indicator") is False, "SimpleImputer: add_indicator debe ser False")
    _require(ip.get("keep_empty_features") is False, "SimpleImputer: keep_empty_features debe ser False")
    _require(ip.get("fill_value") is None, "SimpleImputer: fill_value debe ser None")
    sp = scaler.get_params()
    _require(sp.get("with_mean") is True and sp.get("with_std") is True, "StandardScaler: with_mean y with_std deben ser True")

    n_in = len(input_columns)
    statistics = _floats(_fitted(imputer, "statistics_"), (n_in,), "imputer.statistics_")
    _require(_fitted(imputer, "n_features_in_") == n_in, "imputer.n_features_in_ no coincide con input_columns")
    _require(_fitted(imputer, "indicator_") is None, "SimpleImputer: indicator_ debe ser None")
    kept = [not math.isnan(v) for v in statistics]
    _require(all(math.isfinite(v) or math.isnan(v) for v in statistics), "imputer.statistics_ contiene infinitos")
    n_kept = sum(kept)
    _require(n_kept >= 1, "ninguna columna se conservó en el ajuste")
    _require(_fitted(scaler, "n_features_in_") == n_kept, "scaler.n_features_in_ no coincide con las columnas conservadas")
    mean = _floats(_fitted(scaler, "mean_"), (n_kept,), "scaler.mean_")
    scale = _floats(_fitted(scaler, "scale_"), (n_kept,), "scaler.scale_")
    _check_binary_logreg(logreg, n_kept, "logreg")
    _require(_fitted(logreg, "n_features_in_") == n_kept, "logreg.n_features_in_ no coincide con las columnas conservadas")
    coef = _floats(logreg.coef_, (1, n_kept), "logreg.coef_")
    intercept = _floats(_fitted(logreg, "intercept_"), (1,), "logreg.intercept_")[0]

    document: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_type": MODEL_TYPE_IMPUTED_LOGREG,
        "model_version": model_version,
        "parameters": {
            "input_columns": list(input_columns),
            "imputer_statistics": [v if k else None for v, k in zip(statistics, kept)],
            "scaler_mean": mean,
            "scaler_scale": scale,
            "coef": coef,
            "intercept": intercept,
            "classes": [0, 1],
        },
    }
    return _finish(document, model_version)


def export_platt_logreg(logreg: Any, *, model_version: str) -> bytes:
    """Exporta la `LogisticRegression` de 1 variable ya ajustada (`PlattCalibrator._model`)."""
    _check_binary_logreg(logreg, 1, "logreg")
    _require(_fitted(logreg, "n_features_in_") == 1, "la regresión de Platt debe tener exactamente 1 variable")
    coef = _floats(logreg.coef_, (1, 1), "logreg.coef_")[0]
    intercept = _floats(_fitted(logreg, "intercept_"), (1,), "logreg.intercept_")[0]
    document: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_type": MODEL_TYPE_PLATT,
        "model_version": model_version,
        "parameters": {"coef": coef, "intercept": intercept, "classes": [0, 1]},
    }
    return _finish(document, model_version)


def _finish(document: Dict[str, Any], model_version: str) -> bytes:
    """Serializa de forma canónica y comprueba que el cargador acepta exactamente esos bytes."""
    try:
        data = canonical_bytes(document)
        load_artifact(data, expected_sha256=artifact_sha256(data), expected_model_version=model_version)
    except SafeArtifactError as exc:
        raise ArtifactExportError(f"el modelo no se puede representar en el formato seguro: {exc}") from exc
    return data
