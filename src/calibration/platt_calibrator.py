"""Platt scaling (calibración real, ver `CALIBRATION_SPEC.md` §3).

Satisface el Protocol `Calibrator` (`src/calibration/calibration_layer.py`,
Fase 3, Paso 3.1, sin cambios) sin ningún cambio a ese módulo. Ajusta una
regresión logística de 1 sola feature (`p_raw`) contra el resultado real
-- técnica clásica de Platt scaling, mismo mecanismo que usa
internamente `sklearn.calibration.CalibratedClassifierCV(method="sigmoid")`.

Agnóstico de deporte: no importa nada de `src/models/` ni de
`HistoryRepository` -- solo sabe ajustar/aplicar la transformación sobre
pares `(p_raw, y)` ya extraídos por el llamador. La construcción de esos
pares para tenis vive en `src/calibration/tennis_calibrator_training.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass
class PlattCalibrator:
    """Instancia concreta del Protocol `Calibrator`. `_model` es un
    `sklearn.linear_model.LogisticRegression` ya ajustado sobre 1 feature
    (`p_raw`)."""

    calibration_version: str
    _model: Any
    calibration_method: str = "PLATT_V1"

    def calibrate(self, p_raw: float) -> float:
        import numpy as np

        proba = self._model.predict_proba(np.array([[p_raw]]))[0, 1]
        return float(proba)


def fit_platt_calibrator(
    p_raw: Sequence[float], y: Sequence[int], calibration_version: str
) -> PlattCalibrator:
    """Ajusta Platt scaling sobre `(p_raw, y)`. No valida tamaño mínimo de
    muestra aquí -- esa decisión (tamaño suficiente, agrupación por
    evento) es responsabilidad del llamador (`CALIBRATION_SPEC.md` §2),
    esta función es puramente el ajuste matemático."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    X = np.array(p_raw).reshape(-1, 1)
    y_arr = np.array(y)
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y_arr)
    return PlattCalibrator(calibration_version=calibration_version, _model=model)
