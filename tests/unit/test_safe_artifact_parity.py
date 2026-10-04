"""Paridad numérica contra scikit-learn y rigidez de los exportadores (B1). Datos SINTÉTICOS, todo en memoria o en
`tmp_path`; no entrena ningún modelo real, no genera artefactos fuera de pruebas y no toca el registro de producción.
Tolerancia de paridad: diferencia absoluta máxima <= 1e-12 en todos los escenarios."""
from __future__ import annotations

import io

import numpy as np
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from src.calibration.platt_calibrator import fit_platt_calibrator
from src.models.safe_artifact_export import export_imputed_logreg_pipeline, export_platt_logreg
from src.models.safe_artifact_format import (
    ArtifactExportError,
    ImputedLogRegModel,
    PlattModel,
    SafeArtifactError,
    artifact_sha256,
    load_artifact,
)

TOLERANCE = 1e-12
# Avisos que scikit-learn emite a propósito en estos escenarios (columnas sin valores observados, desbordes con
# entradas de 1e12 o ajustes degenerados); el resto de avisos de la suite se conserva.
pytestmark = [
    pytest.mark.filterwarnings("ignore:Skipping features without any observed values:UserWarning"),
    pytest.mark.filterwarnings("ignore::RuntimeWarning"),
]


def load(data: bytes, version: str):
    return load_artifact(data, expected_sha256=artifact_sha256(data), expected_model_version=version)


def make_pipeline(**overrides) -> Pipeline:
    kwargs = dict(
        imputer=SimpleImputer(strategy="median"), scaler=StandardScaler(),
        logreg=LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    kwargs.update(overrides)
    return Pipeline([(name, step) for name, step in kwargs.items() if step is not None])


def synthetic(rng, n_rows, n_cols, nan_rate=0.15, empty_cols=(), const_cols=(), scale=10.0):
    X = rng.normal(0, scale, (n_rows, n_cols)) + rng.normal(0, 5, n_cols)
    for c in const_cols:
        X[:, c] = 4.0
    X[rng.random(X.shape) < nan_rate] = np.nan
    for c in empty_cols:
        X[:, c] = np.nan
    y = (rng.random(n_rows) < 0.5).astype(int)
    return X, y


def fit(X, y, **overrides) -> Pipeline:
    return make_pipeline(**overrides).fit(X, y)


def max_difference(pipeline: Pipeline, model: ImputedLogRegModel, X_test: np.ndarray) -> float:
    reference = pipeline.predict_proba(X_test)[:, 1]
    mine = np.array([model.predict_proba_vector([float(v) for v in row]) for row in X_test])
    return float(np.max(np.abs(reference - mine)))


SCENARIOS = [
    dict(n_cols=1, empty=(), const=(), nan_rate=0.2),
    dict(n_cols=2, empty=(), const=(), nan_rate=0.0),
    dict(n_cols=4, empty=(1,), const=(), nan_rate=0.15),
    dict(n_cols=5, empty=(), const=(2,), nan_rate=0.15),
    dict(n_cols=6, empty=(0, 3), const=(4,), nan_rate=0.3),
    dict(n_cols=12, empty=(5,), const=(0, 7), nan_rate=0.25),
    dict(n_cols=64, empty=(10, 20, 30), const=(1,), nan_rate=0.1),
    dict(n_cols=256, empty=(0, 255), const=(100,), nan_rate=0.05),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"cols{s['n_cols']}_empty{len(s['empty'])}_const{len(s['const'])}")
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_pipeline_parity_with_scikit_learn(scenario, seed):
    rng = np.random.default_rng(1000 * seed + scenario["n_cols"])
    X, y = synthetic(rng, 400, scenario["n_cols"], scenario["nan_rate"], scenario["empty"], scenario["const"])
    pipeline = fit(X, y)
    columns = [f"c{i}.x" for i in range(scenario["n_cols"])]
    model = load(export_imputed_logreg_pipeline(pipeline, model_version="parity_v1", input_columns=columns), "parity_v1")
    X_test, _ = synthetic(rng, 300, scenario["n_cols"], 0.3, (), (), scale=30.0)
    assert max_difference(pipeline, model, X_test) <= TOLERANCE
    # el patrón de columnas descartadas coincide con el del imputer de scikit-learn
    dropped = [i for i, s in enumerate(model.statistics) if s is None]
    assert dropped == sorted(scenario["empty"])


def test_pipeline_parity_with_extreme_inputs():
    rng = np.random.default_rng(5)
    X, y = synthetic(rng, 400, 5)
    pipeline = fit(X, y)
    model = load(export_imputed_logreg_pipeline(pipeline, model_version="extreme_v1", input_columns=list("abcde")), "extreme_v1")
    for magnitude in (0.0, 1e-9, 1.0, 1e3, 1e6, 1e12):
        X_test = rng.choice([-1.0, 1.0], (50, 5)) * magnitude
        assert max_difference(pipeline, model, X_test) <= TOLERANCE


def test_every_missing_row_and_unseen_values_match():
    rng = np.random.default_rng(6)
    X, y = synthetic(rng, 300, 4)
    pipeline = fit(X, y)
    model = load(export_imputed_logreg_pipeline(pipeline, model_version="m_v1", input_columns=list("abcd")), "m_v1")
    all_nan = np.full((1, 4), np.nan)
    assert max_difference(pipeline, model, all_nan) <= TOLERANCE


def test_platt_parity_on_a_grid_including_the_domain_edges():
    rng = np.random.default_rng(8)
    p_raw = rng.random(500)
    y = (rng.random(500) < p_raw).astype(int)
    logreg = LogisticRegression(max_iter=1000).fit(p_raw.reshape(-1, 1), y)
    model = load(export_platt_logreg(logreg, model_version="platt_v1"), "platt_v1")
    grid = np.concatenate([[0.0, 1.0, 1e-12, 1 - 1e-12, 0.5], np.linspace(0, 1, 1001), rng.random(500)])
    reference = logreg.predict_proba(grid.reshape(-1, 1))[:, 1]
    mine = np.array([model.calibrate(float(x)) for x in grid])
    assert float(np.max(np.abs(reference - mine))) <= TOLERANCE


def test_platt_parity_with_saturated_logits():
    rng = np.random.default_rng(9)
    logreg = LogisticRegression(max_iter=1000).fit(rng.random((100, 1)), (rng.random(100) < 0.5).astype(int))
    for coef, intercept in ((800.0, -400.0), (-800.0, 400.0), (1e4, -5e3), (0.0, 0.0), (1e-12, -1e-12)):
        logreg.coef_ = np.array([[coef]])
        logreg.intercept_ = np.array([intercept])
        model = load(export_platt_logreg(logreg, model_version="sat_v1"), "sat_v1")
        for p in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert abs(model.calibrate(p) - float(logreg.predict_proba([[p]])[0, 1])) <= TOLERANCE


def test_project_platt_calibrator_parity_through_its_public_method():
    rng = np.random.default_rng(10)
    p_raw = [float(x) for x in rng.random(200)]
    y = [int(rng.random() < p) for p in p_raw]
    calibrator = fit_platt_calibrator(p_raw, y, "calibration_v1")  # código del proyecto, sin modificarlo
    model = load(export_platt_logreg(calibrator._model, model_version="cal_v1"), "cal_v1")
    assert isinstance(model, PlattModel)
    for p in [0.0, 0.1, 0.33, 0.5, 0.9, 1.0]:
        assert abs(model.calibrate(p) - calibrator.calibrate(p)) <= TOLERANCE


def test_parity_with_the_project_real_tennis_pipeline_trained_on_synthetic_events(tmp_path):
    """Entrena con la política real del proyecto sobre eventos sintéticos en `tmp_path` (sin tocar datos reales) y compara
    el pipeline que guardaría `train_tennis_baseline_model` con su versión de solo datos, con nombres de columna reales."""
    import joblib

    from src.models.base import ModelStatus
    from src.models.tennis_baseline import _vectorize_features, build_tennis_training_dataset, train_tennis_baseline_model
    from src.storage.history_repository import HistoryRepository
    from tests.unit.calibration_governance_factories import BASE_TRAINED_AT, seed_events

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    seed_events(hist, 160, True)
    status, artifact, _ = train_tennis_baseline_model(hist, models_dir=tmp_path / "models", now=BASE_TRAINED_AT)
    assert status == ModelStatus.TRAINED
    pipeline = joblib.load(io.BytesIO(artifact.file_path.read_bytes()))  # el artefacto sintético de la propia prueba
    data = export_imputed_logreg_pipeline(
        pipeline, model_version="tennis_real_v1", input_columns=artifact.feature_columns
    )
    model = load(data, "tennis_real_v1")
    assert any(" " in c for c in model.input_columns)  # p. ej. "tournament_round.Qualifying 1st Round"
    dataset = build_tennis_training_dataset(hist)
    rows = [_vectorize_features(s.features, artifact.round_categories) for s in dataset.samples]
    X = np.array([[row.get(col, float("nan")) for col in artifact.feature_columns] for row in rows])
    reference = pipeline.predict_proba(X)[:, 1]
    mine = np.array([model.predict_proba_row(row) for row in rows])
    assert float(np.max(np.abs(reference - mine))) <= TOLERANCE


# =====================================================================
# Rigidez de los exportadores
# =====================================================================


class PipelineSub(Pipeline):
    pass


class ImputerSub(SimpleImputer):
    pass


class ScalerSub(StandardScaler):
    pass


class LogRegSub(LogisticRegression):
    pass


def good_data():
    rng = np.random.default_rng(0)
    X, y = synthetic(rng, 200, 3)
    return X, y


def export_pipe(pipeline, columns=("a", "b", "c")):
    return export_imputed_logreg_pipeline(pipeline, model_version="strict_v1", input_columns=list(columns))


def test_the_baseline_configuration_exports_and_loads():
    X, y = good_data()
    assert isinstance(load(export_pipe(fit(X, y)), "strict_v1"), ImputedLogRegModel)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda X, y: PipelineSub(make_pipeline().steps).fit(X, y), id="subclase de Pipeline"),
        pytest.param(lambda X, y: fit(X, y, imputer=ImputerSub(strategy="median")), id="subclase de SimpleImputer"),
        pytest.param(lambda X, y: fit(X, y, scaler=ScalerSub()), id="subclase de StandardScaler"),
        pytest.param(lambda X, y: fit(X, y, logreg=LogRegSub(max_iter=1000)), id="subclase de LogisticRegression"),
        pytest.param(lambda X, y: fit(X, y, imputer=SimpleImputer(strategy="mean")), id="strategy mean"),
        pytest.param(lambda X, y: fit(X, y, imputer=SimpleImputer(strategy="most_frequent")), id="strategy most_frequent"),
        pytest.param(lambda X, y: fit(X, y, imputer=SimpleImputer(strategy="constant", fill_value=0.0)), id="strategy constant"),
        pytest.param(lambda X, y: fit(X, y, imputer=SimpleImputer(strategy="median", add_indicator=True)), id="add_indicator"),
        pytest.param(lambda X, y: fit(X, y, imputer=SimpleImputer(strategy="median", keep_empty_features=True)), id="keep_empty_features"),
        pytest.param(lambda X, y: fit(np.nan_to_num(X, nan=0.0) + 0.0, y, imputer=SimpleImputer(strategy="median", missing_values=0.0)), id="missing_values distinto de NaN"),
        pytest.param(lambda X, y: fit(X, y, scaler=StandardScaler(with_mean=False)), id="sin media"),
        pytest.param(lambda X, y: fit(X, y, scaler=StandardScaler(with_std=False)), id="sin desviación"),
        pytest.param(lambda X, y: fit(X, y, scaler=MinMaxScaler()), id="otro escalador"),
        pytest.param(lambda X, y: fit(X, y, logreg=SGDClassifier(loss="log_loss")), id="otro clasificador"),
        pytest.param(lambda X, y: fit(X, y, logreg=LogisticRegression(fit_intercept=False)), id="sin intercepto"),
        pytest.param(lambda X, y: fit(X, y, scaler=None), id="falta el escalador"),
        pytest.param(lambda X, y: fit(np.nan_to_num(X), y, imputer=None), id="falta el imputer"),
        pytest.param(lambda X, y: Pipeline([("scaler", StandardScaler()), ("imputer", SimpleImputer(strategy="median")), ("logreg", LogisticRegression())]).fit(np.nan_to_num(X), y), id="orden distinto"),
        pytest.param(lambda X, y: Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("extra", "passthrough"), ("logreg", LogisticRegression())]).fit(X, y), id="paso extra"),
        pytest.param(lambda X, y: Pipeline([("imp", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("logreg", LogisticRegression())]).fit(X, y), id="nombres distintos"),
    ],
)
def test_exporter_refuses_unauthorized_pipelines(build):
    X, y = good_data()
    with pytest.raises(ArtifactExportError):
        export_pipe(build(X, y))


def test_exporter_refuses_multiclass_wrong_labels_and_unfitted_objects():
    X, y = good_data()
    rng = np.random.default_rng(1)
    y3 = rng.integers(0, 3, len(y))
    with pytest.raises(ArtifactExportError):
        export_pipe(fit(X, y3))
    with pytest.raises(ArtifactExportError):
        export_pipe(fit(X, np.where(y == 1, 2, 0)))  # clases {0, 2}
    with pytest.raises(ArtifactExportError):
        export_pipe(make_pipeline())  # sin ajustar
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogisticRegression(), model_version="p_v1")


def test_exporter_refuses_non_finite_or_inconsistent_fitted_attributes():
    X, y = good_data()
    pipeline = fit(X, y)
    pipeline.named_steps["logreg"].coef_[0, 0] = np.nan
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)
    pipeline = fit(X, y)
    pipeline.named_steps["scaler"].scale_[0] = 0.0
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)
    pipeline = fit(X, y)
    pipeline.named_steps["scaler"].mean_[0] = np.inf
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)
    pipeline = fit(X, y)
    pipeline.named_steps["imputer"].statistics_[0] = np.inf
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)
    pipeline = fit(X, y)
    pipeline.named_steps["logreg"].coef_ = pipeline.named_steps["logreg"].coef_.astype(np.float32)
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)


def test_exporter_refuses_bad_names_versions_and_column_mismatches():
    X, y = good_data()
    pipeline = fit(X, y)
    for columns in (["a", "b"], ["a", "b", "c", "d"], ["a", "a", "b"], [], ["a", "b", 3], "abc", None, ["a", "b", "c\n"]):
        with pytest.raises(ArtifactExportError):
            export_imputed_logreg_pipeline(pipeline, model_version="strict_v1", input_columns=columns)
    for version in ("", "../x", "a b", "x" * 129, None, 5):
        with pytest.raises(ArtifactExportError):
            export_imputed_logreg_pipeline(pipeline, model_version=version, input_columns=["a", "b", "c"])
        with pytest.raises(ArtifactExportError):
            export_platt_logreg(LogisticRegression().fit(np.array([[0.1], [0.9], [0.2], [0.8]]), [0, 1, 0, 1]), model_version=version)


def test_exporter_refuses_too_many_columns_and_huge_parameters():
    rng = np.random.default_rng(2)
    X, y = synthetic(rng, 400, 257, 0.0)
    with pytest.raises(ArtifactExportError):
        export_imputed_logreg_pipeline(fit(X, y), model_version="big_v1", input_columns=[f"c{i}" for i in range(257)])
    pipeline = fit(*good_data())
    pipeline.named_steps["logreg"].coef_ = np.array([[2e6, 0.0, 0.0]])
    with pytest.raises(ArtifactExportError):
        export_pipe(pipeline)


def test_platt_exporter_refuses_unauthorized_models():
    rng = np.random.default_rng(3)
    X1 = rng.random((100, 1))
    y = (rng.random(100) < 0.5).astype(int)
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogisticRegression().fit(rng.random((100, 2)), y), model_version="p_v1")  # 2 variables
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogRegSub().fit(X1, y), model_version="p_v1")
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogisticRegression(fit_intercept=False).fit(X1, y), model_version="p_v1")
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogisticRegression().fit(X1, np.where(y == 1, 2, 0)), model_version="p_v1")
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(LogisticRegression().fit(rng.random((90, 1)), rng.integers(0, 3, 90)), model_version="p_v1")
    ok = LogisticRegression().fit(X1, y)
    ok.coef_ = np.array([[np.nan]])
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(ok, model_version="p_v1")


def test_exporters_accept_only_in_memory_fitted_objects_never_paths_bytes_or_wrappers(tmp_path):
    missing = tmp_path / "no_existe.joblib"
    for value in (str(missing), missing, b"bytes", io.BytesIO(b"x"), {"coef": 1.0}, None, 5, [1, 2]):
        with pytest.raises(ArtifactExportError):
            export_imputed_logreg_pipeline(value, model_version="v1", input_columns=["a"])
        with pytest.raises(ArtifactExportError):
            export_platt_logreg(value, model_version="v1")
    assert not missing.exists() and list(tmp_path.iterdir()) == []  # no se creó ni se leyó ningún archivo
    calibrator = fit_platt_calibrator([0.1, 0.9, 0.2, 0.8, 0.4, 0.6], [0, 1, 0, 1, 0, 1], "v")
    with pytest.raises(ArtifactExportError):
        export_platt_logreg(calibrator, model_version="v1")  # el envoltorio del proyecto no se acepta: solo la regresión


def test_exporting_does_not_mutate_the_fitted_objects_and_is_deterministic():
    X, y = good_data()
    pipeline = fit(X, y)
    before = (pipeline.named_steps["logreg"].coef_.copy(), pipeline.named_steps["scaler"].scale_.copy())
    first, second = export_pipe(pipeline), export_pipe(pipeline)
    assert first == second and first.endswith(b"\n")
    assert np.array_equal(before[0], pipeline.named_steps["logreg"].coef_) and np.array_equal(before[1], pipeline.named_steps["scaler"].scale_)


def test_the_exporter_only_returns_bytes_it_has_verified_loadable():
    X, y = good_data()
    data = export_pipe(fit(X, y))
    assert isinstance(data, bytes) and load(data, "strict_v1")
    with pytest.raises(SafeArtifactError):
        load_artifact(data, expected_sha256=artifact_sha256(data), expected_model_version="otra_version")


def test_each_exporter_check_rejects_on_its_own_with_its_specific_message():
    X, y = good_data()
    cases = {
        "add_indicator": fit(X, y, imputer=SimpleImputer(strategy="median", add_indicator=True)),
        "keep_empty_features": fit(X, y, imputer=SimpleImputer(strategy="median", keep_empty_features=True)),
        "strategy": fit(X, y, imputer=SimpleImputer(strategy="mean")),
        "with_mean": fit(X, y, scaler=StandardScaler(with_mean=False)),
        "fit_intercept": fit(X, y, logreg=LogisticRegression(fit_intercept=False)),
    }
    for fragment, pipeline in cases.items():
        with pytest.raises(ArtifactExportError, match=fragment):
            export_pipe(pipeline)


def test_the_exporter_refuses_models_whose_canonical_bytes_exceed_the_size_cap():
    rng = np.random.default_rng(4)
    n = 256
    X, y = synthetic(rng, 400, n, 0.0)
    columns = [f"{i:03d}" + "\U0001F600" * 125 for i in range(n)]
    with pytest.raises(ArtifactExportError, match="supera el máximo"):
        export_imputed_logreg_pipeline(fit(X, y), model_version="huge_v1", input_columns=columns)
