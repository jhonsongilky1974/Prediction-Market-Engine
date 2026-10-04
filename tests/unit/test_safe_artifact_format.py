"""Formato de artefactos JSON de solo datos (B1): esquema, representación canónica, carga fail-closed,
predicción pura, pruebas adversariales y de propiedades (semilla fija) y aislamiento (sin joblib, pickle,
numpy ni scikit-learn). No usa scikit-learn: la paridad vive en `test_safe_artifact_parity.py`.
Todo en memoria; no escribe archivos ni genera artefactos reales."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import typing
from collections import UserList
from pathlib import Path
from typing import Any, List, Tuple, Union

import pytest

import src.models.safe_artifact_format as fmt
from src.models.safe_artifact_format import (
    MAX_ARTIFACT_BYTES,
    MAX_INPUT_COLUMNS,
    ArtifactFormatError,
    ArtifactHashError,
    ArtifactInputError,
    ArtifactSchemaError,
    ImputedLogRegModel,
    PlattModel,
    SafeArtifactError,
    artifact_sha256,
    canonical_bytes,
    load_artifact,
)

SRC_FORMAT = Path("src/models/safe_artifact_format.py")
SRC_EXPORT = Path("src/models/safe_artifact_export.py")


def imputed_doc(**overrides):
    doc = {
        "schema_version": 1,
        "model_type": "imputed_standardized_logreg_v1",
        "model_version": "example_v1",
        "parameters": {
            "input_columns": ["rest_days.participant_a", "rest_days.participant_b", "tournament_round.Final"],
            "imputer_statistics": [3.0, None, 0.0],
            "scaler_mean": [2.5, 0.2],
            "scaler_scale": [1.5, 0.4],
            "coef": [0.5, -0.25],
            "intercept": 0.1,
            "classes": [0, 1],
        },
    }
    doc.update(overrides)
    return doc


def platt_doc():
    return {
        "schema_version": 1,
        "model_type": "platt_logreg_1d_v1",
        "model_version": "example_cal_v1",
        "parameters": {"coef": 1.2, "intercept": -0.6, "classes": [0, 1]},
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(data: bytes, model_version: str = "example_v1"):
    return load_artifact(data, expected_sha256=sha(data), expected_model_version=model_version)


def dump(doc, **kwargs) -> bytes:
    """Serialización NO validada (para fabricar documentos inválidos, con salto final)."""
    kwargs.setdefault("sort_keys", True)
    kwargs.setdefault("separators", (",", ":"))
    return (json.dumps(doc, **kwargs) + "\n").encode("utf-8")


def sigmoid_ref(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


# =====================================================================
# Representación canónica y vectores dorados
# =====================================================================

GOLDEN_IMPUTED = (
    b'{"model_type":"imputed_standardized_logreg_v1","model_version":"example_v1","parameters":{"classes":[0,1],'
    b'"coef":[0.5,-0.25],"imputer_statistics":[3.0,null,0.0],"input_columns":["rest_days.participant_a",'
    b'"rest_days.participant_b","tournament_round.Final"],"intercept":0.1,"scaler_mean":[2.5,0.2],'
    b'"scaler_scale":[1.5,0.4]},"schema_version":1}\n'
)
GOLDEN_PLATT = (
    b'{"model_type":"platt_logreg_1d_v1","model_version":"example_cal_v1","parameters":{"classes":[0,1],'
    b'"coef":1.2,"intercept":-0.6},"schema_version":1}\n'
)


def test_canonical_bytes_are_exactly_the_documented_form_and_the_hash_is_stable():
    imputed = canonical_bytes(imputed_doc())
    assert imputed.endswith(b"}\n") and imputed.count(b"\n") == 1 and imputed.isascii()
    assert sha(imputed) == artifact_sha256(imputed) and len(artifact_sha256(imputed)) == 64
    assert canonical_bytes(platt_doc()) == GOLDEN_PLATT
    assert canonical_bytes(imputed_doc()) == GOLDEN_IMPUTED


def test_canonical_form_is_independent_of_dict_insertion_order_and_idempotent():
    doc = imputed_doc()
    shuffled = dict(reversed(list(doc.items())))
    shuffled["parameters"] = dict(reversed(list(doc["parameters"].items())))
    assert canonical_bytes(shuffled) == canonical_bytes(doc)
    assert canonical_bytes(json.loads(canonical_bytes(doc))) == canonical_bytes(doc)


def test_negative_zero_and_exponents_roundtrip_exactly():
    doc = imputed_doc()
    doc["parameters"]["intercept"] = -0.0
    doc["parameters"]["coef"] = [1e-7, 123456.5]
    data = canonical_bytes(doc)
    assert b'"intercept":-0.0' in data and b"1e-07" in data
    model = load(data)
    assert math.copysign(1.0, model.intercept) == -1.0 and model.coef == (1e-07, 123456.5)


def test_non_ascii_column_names_are_escaped_to_ascii_and_roundtrip():
    doc = imputed_doc()
    doc["parameters"]["input_columns"][2] = "tournament_round.Final á ü"
    data = canonical_bytes(doc)
    assert data.isascii() and b"\\u00e1" in data
    assert load(data).input_columns[2] == "tournament_round.Final á ü"


# =====================================================================
# Carga y predicción: valores calculados a mano
# =====================================================================


def test_loaded_models_are_immutable_data_objects():
    model = load(canonical_bytes(imputed_doc()))
    assert isinstance(model, ImputedLogRegModel)
    with pytest.raises(Exception):
        model.intercept = 5.0  # dataclass congelada
    assert isinstance(model.coef, tuple) and isinstance(model.input_columns, tuple)


def test_imputed_prediction_matches_the_hand_computed_formula():
    model = load(canonical_bytes(imputed_doc()))
    # kept: a (media 2.5, escala 1.5, coef 0.5) y c (media 0.2, escala 0.4, coef -0.25); b descartada
    expected = sigmoid_ref(((4.0 - 2.5) / 1.5) * 0.5 + ((1.0 - 0.2) / 0.4) * -0.25 + 0.1)
    assert model.predict_proba_vector([4.0, 99.0, 1.0]) == pytest.approx(expected, abs=1e-15)
    assert model.predict_proba_row({"rest_days.participant_a": 4.0, "tournament_round.Final": 1.0}) == pytest.approx(
        expected, abs=1e-15
    )


def test_missing_values_are_imputed_with_the_statistic_and_dropped_columns_have_no_influence():
    model = load(canonical_bytes(imputed_doc()))
    nan = float("nan")
    imputed = sigmoid_ref(((3.0 - 2.5) / 1.5) * 0.5 + ((0.0 - 0.2) / 0.4) * -0.25 + 0.1)
    assert model.predict_proba_vector([nan, nan, nan]) == pytest.approx(imputed, abs=1e-15)
    assert model.predict_proba_row({}) == model.predict_proba_vector([nan, nan, nan])  # columna ausente = NaN
    assert model.predict_proba_vector([4.0, 1.0, 1.0]) == model.predict_proba_vector([4.0, -777.0, 1.0])


def test_row_key_order_and_extra_keys_do_not_matter_and_calls_are_deterministic():
    model = load(canonical_bytes(imputed_doc()))
    a = {"rest_days.participant_a": 2.0, "tournament_round.Final": 1.0, "extra": "ignored"}
    b = {"extra": "ignored", "tournament_round.Final": 1.0, "rest_days.participant_a": 2.0}
    assert model.predict_proba_row(a) == model.predict_proba_row(b)
    assert len({model.predict_proba_row(a) for _ in range(20)}) == 1


def test_platt_prediction_matches_the_hand_computed_formula_and_domain_is_enforced():
    model = load(canonical_bytes(platt_doc()), "example_cal_v1")
    assert isinstance(model, PlattModel)
    assert model.calibrate(0.3) == pytest.approx(sigmoid_ref(1.2 * 0.3 - 0.6), abs=1e-15)
    assert model.calibrate(0) == pytest.approx(sigmoid_ref(-0.6), abs=1e-15) and 0.0 <= model.calibrate(1.0) <= 1.0
    for bad in (-0.001, 1.001, math.nan, math.inf, -math.inf, True, "0.5", None, [0.5]):
        with pytest.raises(ArtifactInputError):
            model.calibrate(bad)


@pytest.mark.parametrize(
    "values",
    [[math.inf, 0.0, 0.0], [0.0, -math.inf, 0.0], [True, 0.0, 0.0], ["1", 0.0, 0.0], [None, 0.0, 0.0], [1.0, 2.0], [1.0] * 4,
     "abc", b"abc", 5, None],
)
def test_invalid_prediction_inputs_fail_closed(values):
    model = load(canonical_bytes(imputed_doc()))
    with pytest.raises(ArtifactInputError):
        model.predict_proba_vector(values)


HUGE_INTS = [
    10**400, -(10**400), 10**309, -(10**309), 2**1024, -(2**1024),
    2**1024 - 2**970,  # primer entero que ya redondea a infinito: float(...) lanza OverflowError
    2**5000, 10**4000,
]


@pytest.mark.parametrize("huge", HUGE_INTS)
def test_huge_python_integers_never_leak_overflow_error_in_the_imputed_model(huge):
    model = load(canonical_bytes(imputed_doc()))
    for position in range(3):  # en cada columna, conservada o descartada
        values = [1.0, 2.0, 3.0]
        values[position] = huge
        with pytest.raises(ArtifactInputError, match="fuera del rango de coma flotante") as caught:
            model.predict_proba_vector(values)
        assert not isinstance(caught.value, OverflowError) and isinstance(caught.value, SafeArtifactError)
        assert isinstance(caught.value.__cause__, OverflowError)  # la causa original se conserva para depurar
    columns = ["rest_days.participant_a", "rest_days.participant_b", "tournament_round.Final"]
    for column in columns:
        with pytest.raises(ArtifactInputError, match="fuera del rango de coma flotante"):
            model.predict_proba_row({column: huge})


@pytest.mark.parametrize("huge", HUGE_INTS)
def test_huge_python_integers_never_leak_overflow_error_in_the_platt_model(huge):
    model = load(canonical_bytes(platt_doc()), "example_cal_v1")
    with pytest.raises(ArtifactInputError, match="fuera del rango de coma flotante") as caught:
        model.calibrate(huge)
    assert not isinstance(caught.value, OverflowError) and isinstance(caught.value, SafeArtifactError)
    assert isinstance(caught.value.__cause__, OverflowError)


def test_large_but_representable_integers_keep_their_previous_behavior():
    model = load(canonical_bytes(imputed_doc()))
    assert model.predict_proba_vector([10**300, 0.0, 0.0]) in (0.0, 1.0)  # finito: satura, no falla
    assert model.predict_proba_vector([int(sys.float_info.max), 0.0, 0.0]) == 1.0  # el mayor entero representable: finito, satura
    assert model.predict_proba_vector([-(10**300), 0.0, 0.0]) == 0.0
    for small in (0, 1, -1, 10, 2**53 + 1):
        assert 0.0 <= model.predict_proba_vector([small, 0.0, 0.0]) <= 1.0
    platt = load(canonical_bytes(platt_doc()), "example_cal_v1")
    assert platt.calibrate(0) == pytest.approx(sigmoid_ref(-0.6)) and platt.calibrate(1) == pytest.approx(sigmoid_ref(0.6))
    for out_of_range in (2, -1, 10**300):
        with pytest.raises(ArtifactInputError, match="finito y estar en"):  # entero representable fuera de [0, 1]
            platt.calibrate(out_of_range)


def test_prediction_never_raises_anything_but_safe_errors_for_arbitrary_magnitudes_and_types():
    """Propiedad (semilla fija): para entradas de cualquier tipo y magnitud la predicción devuelve una probabilidad
    en [0, 1] o lanza una subclase de `SafeArtifactError`; nunca `OverflowError`, `TypeError` ni `ValueError`."""
    rng = random.Random(424242)
    imputed = load(canonical_bytes(imputed_doc()))
    platt = load(canonical_bytes(platt_doc()), "example_cal_v1")

    def draw():
        kind = rng.randrange(9)
        if kind == 0:
            return rng.choice([-1, 1]) * rng.randrange(10 ** rng.randrange(1, 800))
        if kind == 1:
            return rng.uniform(-1e12, 1e12)
        if kind == 2:
            return rng.choice([math.nan, math.inf, -math.inf])
        if kind == 3:
            return rng.choice([True, False, None, "1.0", b"1", [1.0], {"a": 1}, (1.0,), 1 + 2j])
        if kind == 4:
            return rng.uniform(0.0, 1.0)
        if kind == 5:
            return rng.choice([0, 1, -1, 2**53, 2**63, 2**64, 2**1023, 2**1024])
        if kind == 6:
            return rng.choice([1e308, -1e308, 1e-320, 5e-324, 1.7976931348623157e308])
        if kind == 7:
            return float("nan")
        return rng.randrange(-100, 100)

    outcomes = {"ok": 0, "safe_error": 0}
    for _ in range(3000):
        for call in (
            lambda v: imputed.predict_proba_vector([v, draw(), draw()]),
            lambda v: imputed.predict_proba_row({"rest_days.participant_a": v, "tournament_round.Final": draw()}),
            lambda v: platt.calibrate(v),
        ):
            try:
                result = call(draw())
            except SafeArtifactError:
                outcomes["safe_error"] += 1
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"escapó una excepción que no es SafeArtifactError: {type(exc).__name__}: {exc}")
            assert isinstance(result, float) and 0.0 <= result <= 1.0
            outcomes["ok"] += 1
    assert outcomes["ok"] > 100 and outcomes["safe_error"] > 1000  # la propiedad ejercita ambos caminos


def test_predict_proba_vector_annotation_matches_the_types_it_really_accepts():
    hints = typing.get_type_hints(ImputedLogRegModel.predict_proba_vector)
    assert hints["values"] == Union[List[Any], Tuple[Any, ...]] and "Sequence" not in str(hints["values"])
    model = load(canonical_bytes(imputed_doc()))
    as_list, as_tuple = [4.0, 99.0, 1.0], (4.0, 99.0, 1.0)
    assert model.predict_proba_vector(as_list) == model.predict_proba_vector(as_tuple)
    for other in (
        range(3), UserList([4.0, 99.0, 1.0]), (v for v in as_list), {4.0, 99.0, 1.0}, {"a": 4.0, "b": 99.0, "c": 1.0},
        bytearray(b"abc"), memoryview(b"abc"), "abc", b"abc",
    ):
        with pytest.raises(ArtifactInputError, match="lista o tupla"):  # secuencias que NO son list/tuple se rechazan
            model.predict_proba_vector(other)


def test_row_must_be_a_mapping_and_overflowing_logits_are_rejected():
    model = load(canonical_bytes(imputed_doc()))
    with pytest.raises(ArtifactInputError):
        model.predict_proba_row([1.0, 2.0, 3.0])
    doc = imputed_doc()
    doc["parameters"]["scaler_scale"] = [1e-300, 0.4]
    huge = load(canonical_bytes(doc))
    with pytest.raises(ArtifactInputError, match="no es finito"):
        huge.predict_proba_vector([1e300, 0.0, 0.0])  # el logit desborda a infinito


def test_extreme_logits_do_not_overflow_and_saturate_to_zero_or_one():
    for coef, intercept, expected in ((1e6, 0.0, 1.0), (-1e6, 0.0, 0.0)):
        doc = platt_doc()
        doc["parameters"]["coef"], doc["parameters"]["intercept"] = coef, intercept
        assert load(canonical_bytes(doc), "example_cal_v1").calibrate(1.0) == expected
    assert fmt._sigmoid(800.0) == 1.0 and fmt._sigmoid(-800.0) == 0.0


# =====================================================================
# Hash y tipo de los argumentos
# =====================================================================


def test_hash_is_checked_before_parsing_and_wrong_hashes_are_refused():
    data = canonical_bytes(imputed_doc())
    right = sha(data)
    for bad in ("0" * 64, right.upper(), right[:-1], right + "0", "", None, 5, b"x", right.replace(right[0], "g", 1)):
        with pytest.raises(ArtifactHashError):
            load_artifact(data, expected_sha256=bad, expected_model_version="example_v1")
    # bytes que NO son JSON, con su hash correcto, llegan al analizador; con hash incorrecto nunca se analizan
    with pytest.raises(ArtifactHashError):
        load_artifact(b"{not json\n", expected_sha256="0" * 64, expected_model_version="example_v1")
    with pytest.raises(ArtifactFormatError):
        load(b"{not json\n")


@pytest.mark.parametrize("data", ["texto", bytearray(b"{}\n"), memoryview(b"{}\n"), None, 5, [b"{}"]])
def test_only_exact_bytes_are_accepted(data):
    with pytest.raises(ArtifactFormatError):
        load_artifact(data, expected_sha256="0" * 64, expected_model_version="example_v1")
    with pytest.raises(ArtifactFormatError):
        artifact_sha256(data)


def test_size_limit_applies_before_anything_else():
    data = b"[" + b"0," * (MAX_ARTIFACT_BYTES // 2) + b"0]\n"
    assert len(data) > MAX_ARTIFACT_BYTES
    with pytest.raises(ArtifactFormatError, match="supera el máximo"):
        load_artifact(data, expected_sha256="0" * 64, expected_model_version="example_v1")


def test_expected_model_version_must_match_and_be_valid():
    data = canonical_bytes(imputed_doc())
    with pytest.raises(ArtifactSchemaError):
        load(data, "otro_modelo")
    for bad in ("", "a b", "../x", "x" * 129, None, 5, "\n"):
        with pytest.raises(ArtifactSchemaError):
            load(data, bad)


def test_expected_arguments_are_keyword_only_and_mandatory():
    data = canonical_bytes(imputed_doc())
    with pytest.raises(TypeError):
        load_artifact(data)
    with pytest.raises(TypeError):
        load_artifact(data, sha(data), "example_v1")


# =====================================================================
# Adversariales: formato de bytes
# =====================================================================


def text_of(doc=None) -> str:
    return canonical_bytes(doc or imputed_doc()).decode("ascii")


FORMAT_CASES = {
    "utf8 inválido": b"\xff\xfe{}\n",
    "BOM": b"\xef\xbb\xbf" + canonical_bytes(imputed_doc()),
    "CRLF": canonical_bytes(imputed_doc()).replace(b"\n", b"\r\n"),
    "sin salto final": canonical_bytes(imputed_doc())[:-1],
    "doble salto final": canonical_bytes(imputed_doc()) + b"\n",
    "espacio inicial": b" " + canonical_bytes(imputed_doc()),
    "salto inicial": b"\n" + canonical_bytes(imputed_doc()),
    "espacio tras ':' (no canónico)": canonical_bytes(imputed_doc()).replace(b'"schema_version":1', b'"schema_version": 1'),
    "indentado": dump(imputed_doc(), indent=2),
    "claves sin ordenar": dump(imputed_doc(), sort_keys=False),
    "separadores con espacio": dump(imputed_doc(), separators=(", ", ": ")),
    "no ASCII sin escapar": dump(
        {**imputed_doc(), "model_version": "example_v1"}, ensure_ascii=False
    ).replace(b"rest_days.participant_a", "rest_días.participant_a".encode("utf-8")),
    "clave duplicada (raíz)": canonical_bytes(imputed_doc()).replace(
        b'"schema_version":1}', b'"schema_version":1,"schema_version":1}'
    ),
    "clave duplicada (anidada)": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1,', b'"intercept":0.1,"intercept":0.2,'),
    "NaN": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":NaN'),
    "Infinity": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":Infinity'),
    "-Infinity": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":-Infinity'),
    "exponente que desborda": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":1e999'),
    "entero enorme": canonical_bytes(imputed_doc()).replace(b'"schema_version":1', b'"schema_version":' + b"9" * 10_000),
    "cero inicial": canonical_bytes(imputed_doc()).replace(b'"schema_version":1', b'"schema_version":01'),
    "mayúscula en exponente": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":1E-1'),
    "entero donde va flotante (0.1 -> 1)": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":1'),
    "flotante con ceros sobrantes": canonical_bytes(imputed_doc()).replace(b'"intercept":0.1', b'"intercept":0.10'),
    "bomba de anidamiento": b"[" * 100_000 + b"]" * 100_000 + b"\n",
    "objeto anidado profundo": b'{"a":' * 30_000 + b"1" + b"}" * 30_000 + b"\n",
    "vacío": b"",
    "solo salto": b"\n",
    "NUL": canonical_bytes(imputed_doc()).replace(b'"example_v1"', b'"example\\u0000v1"'),
    "no es objeto": b"[]\n",
    "null": b"null\n",
    "texto JSON": b'"hola"\n',
    "truncado": canonical_bytes(imputed_doc())[:-30] + b"\n",
}


@pytest.mark.parametrize("name", sorted(FORMAT_CASES))
def test_malformed_or_non_canonical_bytes_are_refused_even_with_a_correct_hash(name):
    data = FORMAT_CASES[name]
    with pytest.raises(SafeArtifactError):
        load(data)


# Cada capa de defensa debe rechazar por sí misma (no solo la comprobación canónica final): mensaje esperado por caso.
LAYER_MESSAGES = {
    "BOM": "no puede llevar BOM",
    "CRLF": "salto de línea final",
    "sin salto final": "salto de línea final",
    "doble salto final": "salto de línea final",
    "clave duplicada (raíz)": "clave duplicada",
    "clave duplicada (anidada)": "clave duplicada",
    "NaN": "constante no permitida",
    "Infinity": "constante no permitida",
    "-Infinity": "constante no permitida",
    "exponente que desborda": "fuera del rango",
    "entero enorme": "demasiados dígitos",
    "utf8 inválido": "UTF-8 inválido",
    "bomba de anidamiento": "JSON inválido",
}


@pytest.mark.parametrize("name", sorted(LAYER_MESSAGES))
def test_each_defensive_layer_rejects_on_its_own_not_only_the_final_canonical_check(name):
    with pytest.raises(ArtifactFormatError, match=LAYER_MESSAGES[name]):
        load(FORMAT_CASES[name])


def test_the_parser_hooks_reject_directly():
    with pytest.raises(ArtifactFormatError, match="clave duplicada"):
        fmt._reject_duplicates([("a", 1), ("a", 2)])
    for constant in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ArtifactFormatError, match="constante no permitida"):
            fmt._reject_constant(constant)
    with pytest.raises(ArtifactFormatError):
        fmt._strict_int("9" * 21)
    assert fmt._strict_int("-" + "9" * 20) == -(10**20 - 1)
    with pytest.raises(ArtifactFormatError):
        fmt._strict_float("1e999")


def test_canonical_bytes_also_enforces_the_size_cap_so_it_only_returns_loadable_bytes():
    n = MAX_INPUT_COLUMNS
    doc = imputed_doc()
    doc["parameters"] = {
        "input_columns": [f"{i:03d}" + "\U0001F600" * 125 for i in range(n)],  # no BMP: 12 bytes por carácter escapado
        "imputer_statistics": [1.0] * n, "scaler_mean": [0.0] * n, "scaler_scale": [1.0] * n, "coef": [0.1] * n,
        "intercept": 0.0, "classes": [0, 1],
    }
    assert len(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)) > MAX_ARTIFACT_BYTES
    with pytest.raises(ArtifactFormatError, match="supera el máximo"):
        canonical_bytes(doc)


def test_a_model_is_never_built_from_refused_bytes():
    built = []
    original = fmt._build
    fmt._build = lambda doc: built.append(doc) or original(doc)  # type: ignore[assignment]
    try:
        for data in FORMAT_CASES.values():
            with pytest.raises(SafeArtifactError):
                load(data)
    finally:
        fmt._build = original  # type: ignore[assignment]
    assert built == []


# =====================================================================
# Adversariales: esquema (documentos inválidos serializados con hash correcto)
# =====================================================================


def mutate(path, value, doc=None, delete=False):
    doc = copy.deepcopy(doc or imputed_doc())
    node = doc
    for key in path[:-1]:
        node = node[key]
    if delete:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


P = "parameters"
SCHEMA_CASES = {
    "schema_version 0": mutate(["schema_version"], 0),
    "schema_version 2": mutate(["schema_version"], 2),
    "schema_version texto": mutate(["schema_version"], "1"),
    "schema_version flotante": mutate(["schema_version"], 1.0),
    "schema_version bool": mutate(["schema_version"], True),
    "model_type desconocido": mutate(["model_type"], "os.system"),
    "model_type distinta capitalización": mutate(["model_type"], "Imputed_Standardized_Logreg_V1"),
    "model_type numérico": mutate(["model_type"], 1),
    "model_type lista": mutate(["model_type"], ["imputed_standardized_logreg_v1"]),
    "model_type con ruta de módulo": mutate(["model_type"], "sklearn.pipeline.Pipeline"),
    "model_version inválido": mutate(["model_version"], "../x"),
    "model_version vacío": mutate(["model_version"], ""),
    "model_version largo": mutate(["model_version"], "a" * 129),
    "model_version salto de línea": mutate(["model_version"], "example_v1\n"),
    "clave extra raíz": {**imputed_doc(), "extra": 1},
    "clave extra __class__": {**imputed_doc(), "__class__": "x"},
    "clave extra __reduce__": {**imputed_doc(), "__reduce__": ["os.system", ["x"]]},
    "clave extra py/object": {**imputed_doc(), "py/object": "os.system"},
    "clave extra @type": {**imputed_doc(), "@type": "x"},
    "clave extra $ref": {**imputed_doc(), "$ref": "#/x"},
    "falta clave raíz": mutate(["model_type"], None, delete=True),
    "falta parameters": mutate([P], None, delete=True),
    "parameters no es objeto": mutate([P], []),
    "clave extra en parameters": mutate([P, "extra"], 1),
    "falta coef": mutate([P, "coef"], None, delete=True),
    "falta classes": mutate([P, "classes"], None, delete=True),
    "falta input_columns": mutate([P, "input_columns"], None, delete=True),
    "coef enteros": mutate([P, "coef"], [1, 2]),
    "coef con bool": mutate([P, "coef"], [True, 0.5]),
    "coef con null": mutate([P, "coef"], [None, 0.5]),
    "coef con texto": mutate([P, "coef"], ["0.5", 0.5]),
    "coef lista anidada": mutate([P, "coef"], [[0.5], 0.5]),
    "coef longitud corta": mutate([P, "coef"], [0.5]),
    "coef longitud larga": mutate([P, "coef"], [0.5, 0.5, 0.5]),
    "coef vacío": mutate([P, "coef"], []),
    "coef no es lista": mutate([P, "coef"], 0.5),
    "coef sobre el límite": mutate([P, "coef"], [1e6 * 1.0001, 0.5]),
    "coef bajo el límite": mutate([P, "coef"], [-1e7, 0.5]),
    "intercept entero": mutate([P, "intercept"], 1),
    "intercept texto": mutate([P, "intercept"], "0.1"),
    "intercept null": mutate([P, "intercept"], None),
    "intercept bool": mutate([P, "intercept"], False),
    "intercept sobre el límite": mutate([P, "intercept"], 2e6),
    "scale cero": mutate([P, "scaler_scale"], [0.0, 0.4]),
    "scale negativa": mutate([P, "scaler_scale"], [-1.5, 0.4]),
    "scale sobre el límite": mutate([P, "scaler_scale"], [2e6, 0.4]),
    "scale -0.0": mutate([P, "scaler_scale"], [-0.0, 0.4]),
    "mean longitud": mutate([P, "scaler_mean"], [2.5]),
    "classes invertidas": mutate([P, "classes"], [1, 0]),
    "classes tres": mutate([P, "classes"], [0, 1, 2]),
    "classes flotantes": mutate([P, "classes"], [0.0, 1.0]),
    "classes bool": mutate([P, "classes"], [False, True]),
    "classes texto": mutate([P, "classes"], ["0", "1"]),
    "classes vacías": mutate([P, "classes"], []),
    "estadísticas longitud": mutate([P, "imputer_statistics"], [3.0, None]),
    "estadísticas todo null": mutate([P, "imputer_statistics"], [None, None, None]),
    "estadísticas enteras": mutate([P, "imputer_statistics"], [3, None, 0]),
    "estadísticas texto": mutate([P, "imputer_statistics"], ["3.0", None, 0.0]),
    "estadísticas sobre el límite": mutate([P, "imputer_statistics"], [3e6, None, 0.0]),
    "estadísticas no es lista": mutate([P, "imputer_statistics"], {}),
    "más columnas conservadas que parámetros": mutate([P, "imputer_statistics"], [3.0, 1.0, 0.0]),
    "columnas vacías": mutate([P, "input_columns"], []),
    "columnas 257": mutate([P, "input_columns"], [f"c{i}" for i in range(MAX_INPUT_COLUMNS + 1)]),
    "columnas duplicadas": mutate([P, "input_columns"], ["a", "a", "b"]),
    "columna vacía": mutate([P, "input_columns"], ["a", "", "b"]),
    "columna numérica": mutate([P, "input_columns"], ["a", 1, "b"]),
    "columna con NUL": mutate([P, "input_columns"], ["a", "b\u0000", "c"]),
    "columna con control": mutate([P, "input_columns"], ["a", "b\tc", "c"]),
    "columna con salto": mutate([P, "input_columns"], ["a", "b\nc", "c"]),
    "columna con espacios extremos": mutate([P, "input_columns"], ["a", " b", "c"]),
    "columna con NBSP": mutate([P, "input_columns"], ["a", "b\u00a0c", "c"]),
    "columna con sustituto suelto": mutate([P, "input_columns"], ["a", "b\ud800", "c"]),
    "columna larga": mutate([P, "input_columns"], ["a", "x" * 129, "c"]),
    "columna lista": mutate([P, "input_columns"], ["a", ["b"], "c"]),
    "input_columns no es lista": mutate([P, "input_columns"], "abc"),
    "platt con claves de pipeline": {**platt_doc(), P: {**platt_doc()[P], "scaler_mean": [0.0]}},
    "platt coef lista": mutate([P, "coef"], [1.2], platt_doc()),
    "platt coef entero": mutate([P, "coef"], 1, platt_doc()),
    "platt sin intercept": mutate([P, "intercept"], None, platt_doc(), delete=True),
    "platt con parámetros de pipeline faltantes pero tipo pipeline": {**platt_doc(), "model_type": "imputed_standardized_logreg_v1"},
    "pipeline con parámetros de platt": {**imputed_doc(), P: platt_doc()[P]},
}


VALID_MODEL_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def expected_version_for(document: dict) -> str:
    """`expected_model_version` a pasar al cargador: el `model_version` del propio documento cuando es un identificador
    válido, para que el rechazo se deba SOLO al defecto del documento y no a una discrepancia de versión; si el documento
    trae un identificador inválido (o ninguno), se pasa uno válido cualquiera."""
    version = document.get("model_version")
    return version if isinstance(version, str) and VALID_MODEL_VERSION.fullmatch(version) else "example_v1"


@pytest.mark.parametrize("name", sorted(SCHEMA_CASES))
def test_schema_violations_are_refused_with_a_matching_hash(name):
    document = SCHEMA_CASES[name]
    with pytest.raises(SafeArtifactError) as caught:
        load(dump(document, ensure_ascii=True), expected_version_for(document))
    # el rechazo proviene del defecto del documento, no de que la versión esperada difiera de la del documento
    assert "model_version distinto del esperado" not in str(caught.value)
    assert "expected_model_version inválido" not in str(caught.value)


def test_canonical_bytes_refuses_invalid_documents_too():
    for doc in (SCHEMA_CASES["coef enteros"], SCHEMA_CASES["classes invertidas"], SCHEMA_CASES["estadísticas todo null"]):
        with pytest.raises(ArtifactSchemaError):
            canonical_bytes(doc)
    for doc in ([], None, "x", 5):
        with pytest.raises(ArtifactSchemaError):
            canonical_bytes(doc)
    bad = imputed_doc()
    bad["parameters"]["intercept"] = math.nan
    with pytest.raises(ArtifactSchemaError):
        canonical_bytes(bad)
    tupled = imputed_doc()
    tupled["parameters"]["coef"] = (0.5, -0.25)  # tupla, no lista
    with pytest.raises(ArtifactSchemaError):
        canonical_bytes(tupled)


def test_extreme_but_allowed_values_load_and_the_exact_limits_are_inclusive():
    doc = imputed_doc()
    doc["parameters"]["coef"] = [1e6, -1e6]
    doc["parameters"]["scaler_scale"] = [1e6, 5e-324]
    doc["parameters"]["intercept"] = -1e6
    model = load(canonical_bytes(doc))
    assert model.coef == (1e6, -1e6) and model.scale == (1e6, 5e-324)
    many = imputed_doc()
    n = MAX_INPUT_COLUMNS
    many["parameters"] = {
        "input_columns": [f"c{i}" for i in range(n)], "imputer_statistics": [float(i) for i in range(n)],
        "scaler_mean": [0.0] * n, "scaler_scale": [1.0] * n, "coef": [0.01] * n, "intercept": 0.0, "classes": [0, 1],
    }
    assert len(load(canonical_bytes(many)).input_columns) == n
    assert len(canonical_bytes(many)) < MAX_ARTIFACT_BYTES


# =====================================================================
# Propiedades (semilla fija)
# =====================================================================


def random_doc(rng: random.Random) -> dict:
    n_in = rng.randint(1, 12)
    kept = [rng.random() > 0.3 for _ in range(n_in)]
    if not any(kept):
        kept[rng.randrange(n_in)] = True
    n_kept = sum(kept)
    f = lambda lo, hi: float(rng.uniform(lo, hi))
    return {
        "schema_version": 1,
        "model_type": "imputed_standardized_logreg_v1",
        "model_version": f"prop_{rng.randint(0, 10**6)}",
        "parameters": {
            "input_columns": [f"col_{i}.x" for i in range(n_in)],
            "imputer_statistics": [f(-30, 30) if k else None for k in kept],
            "scaler_mean": [f(-30, 30) for _ in range(n_kept)],
            "scaler_scale": [f(0.01, 20) for _ in range(n_kept)],
            "coef": [f(-5, 5) for _ in range(n_kept)],
            "intercept": f(-5, 5),
            "classes": [0, 1],
        },
    }


def reference_predict(doc: dict, row: list) -> float:
    p = doc["parameters"]
    k, z = 0, 0.0
    parts = []
    for stat, value in zip(p["imputer_statistics"], row):
        if stat is None:
            continue
        x = stat if math.isnan(value) else value
        parts.append(((x - p["scaler_mean"][k]) / p["scaler_scale"][k]) * p["coef"][k])
        k += 1
    z = sum(parts) + p["intercept"]
    return sigmoid_ref(z) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def test_random_valid_documents_roundtrip_and_predict_like_the_independent_reference():
    rng = random.Random(20261004)
    for _ in range(300):
        doc = random_doc(rng)
        data = canonical_bytes(doc)
        assert canonical_bytes(json.loads(data)) == data
        model = load(data, doc["model_version"])
        for _ in range(5):
            row = [float("nan") if rng.random() < 0.3 else rng.uniform(-40, 40) for _ in doc["parameters"]["input_columns"]]
            p = model.predict_proba_vector(row)
            assert 0.0 <= p <= 1.0
            assert abs(p - reference_predict(doc, row)) <= 1e-15


def test_random_byte_mutations_never_yield_a_non_canonical_model_and_only_raise_safe_errors():
    rng = random.Random(7)
    base = canonical_bytes(imputed_doc())
    accepted = rejected = 0
    for i in range(2500):
        data = bytearray(base)
        kind = i % 4
        pos = rng.randrange(len(data))
        if kind == 0:
            data[pos] = rng.randrange(256)
        elif kind == 1:
            data.insert(pos, rng.randrange(256))
        elif kind == 2 and len(data) > 1:
            del data[pos]
        else:
            other = rng.randrange(len(data))
            data[pos], data[other] = data[other], data[pos]
        mutated = bytes(data)
        try:
            model = load(mutated)
        except SafeArtifactError:
            rejected += 1
            continue
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"escapó una excepción no controlada: {exc!r} con {mutated!r}")
        accepted += 1
        # si se aceptó, son exactamente los bytes canónicos de un documento válido (p. ej. una mutación nula)
        assert canonical_bytes(json.loads(mutated)) == mutated
        assert isinstance(model, ImputedLogRegModel)
    assert rejected > 2000 and accepted + rejected == 2500


def test_sigmoid_properties():
    rng = random.Random(3)
    last = -1.0
    for z in sorted(rng.uniform(-35, 35) for _ in range(500)):
        p = fmt._sigmoid(z)
        assert 0.0 <= p <= 1.0 and p >= last
        last = p
        assert abs(p + fmt._sigmoid(-z) - 1.0) <= 1e-15
    assert fmt._sigmoid(0.0) == 0.5


def test_perturbing_a_dropped_column_never_changes_the_output():
    rng = random.Random(11)
    for _ in range(100):
        doc = random_doc(rng)
        model = load(canonical_bytes(doc), doc["model_version"])
        row = [rng.uniform(-10, 10) for _ in doc["parameters"]["input_columns"]]
        base = model.predict_proba_vector(row)
        for i, stat in enumerate(doc["parameters"]["imputer_statistics"]):
            if stat is None:
                changed = list(row)
                changed[i] = rng.uniform(-1e6, 1e6)
                assert model.predict_proba_vector(changed) == base


# =====================================================================
# Aislamiento: sin joblib, pickle, numpy ni scikit-learn; sin ejecución dinámica ni E/S
# =====================================================================

FORBIDDEN_MODULES = {"joblib", "pickle", "cloudpickle", "dill", "shelve", "marshal", "numpy", "sklearn", "scipy", "importlib", "os", "subprocess", "builtins", "ctypes"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "getattr", "setattr", "globals", "locals", "vars", "input"}


def imports_of(path: Path, only_top_level: bool = False):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body if only_top_level else list(ast.walk(tree))
    found = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def calls_of(path: Path, builtins_only: bool = False):
    """Nombres de funciones llamadas: por nombre (`eval(...)`) y, salvo `builtins_only`, por atributo (`x.load(...)`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute) and not builtins_only:
                names.add(func.attr)
    return names


def test_ast_the_safe_module_imports_no_deserializer_numeric_or_dynamic_machinery():
    assert not imports_of(SRC_FORMAT) & FORBIDDEN_MODULES
    assert imports_of(SRC_FORMAT) <= {"__future__", "hashlib", "hmac", "json", "math", "re", "dataclasses", "typing"}
    assert not calls_of(SRC_FORMAT, builtins_only=True) & FORBIDDEN_CALLS  # `re.compile` (regex) es atributo, no el builtin
    assert not calls_of(SRC_FORMAT) & {"eval", "exec", "__import__", "open", "getattr", "system", "popen"}
    tree = ast.parse(SRC_FORMAT.read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"load", "dump", "read_text", "read_bytes", "write_text", "write_bytes", "system", "popen"}


SERIALIZATION_ATTRS = {"load", "loads", "dump", "dumps", "Unpickler", "Pickler", "unpickle"}


def serialization_calls(source: str) -> set:
    """Pares `(receptor, nombre)` de las llamadas por atributo cuyo nombre es de (de)serialización."""
    tree = ast.parse(source)
    return {
        (ast.unparse(node.func.value), node.func.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SERIALIZATION_ATTRS
    }


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("import pickle\npickle.loads(b'')", {("pickle", "loads")}),
        ("import joblib\njoblib.load(path)", {("joblib", "load")}),
        ("import marshal\nmarshal.loads(b'')", {("marshal", "loads")}),
        ("import cloudpickle\ncloudpickle.dumps(obj)", {("cloudpickle", "dumps")}),
        ("import pickle\npickle.Unpickler(handle).load()", {("pickle", "Unpickler"), ("pickle.Unpickler(handle)", "load")}),
        ("import json\njson.loads('1')\njson.dumps(1)", {("json", "loads"), ("json", "dumps")}),
        ("x = 1\nprint(x)", set()),
    ],
)
def test_the_serialization_call_detector_flags_realistic_deserializers(snippet, expected):
    assert serialization_calls(snippet) == expected


def test_ast_the_safe_module_only_calls_json_loads_and_json_dumps_among_serialization_functions():
    assert serialization_calls(SRC_FORMAT.read_text(encoding="utf-8")) == {("json", "loads"), ("json", "dumps")}


def test_ast_the_exporter_imports_scikit_learn_only_lazily_and_never_reads_files_or_deserializes():
    top = imports_of(SRC_EXPORT, only_top_level=True)
    assert not top & {"sklearn", "numpy", "joblib", "pickle", "scipy"}
    assert not imports_of(SRC_EXPORT) & {"joblib", "pickle", "cloudpickle", "dill", "shelve", "marshal", "os", "subprocess", "io", "pathlib"}
    assert not calls_of(SRC_EXPORT) & {"eval", "exec", "compile", "__import__", "open", "load", "loads", "dump", "dumps", "read_text", "read_bytes"}
    tree = ast.parse(SRC_EXPORT.read_text(encoding="utf-8"))
    # los imports de sklearn/numpy ocurren solo dentro de funciones
    for node in tree.body:
        assert not isinstance(node, (ast.Import, ast.ImportFrom)) or (getattr(node, "module", "") or "").split(".")[0] not in {"sklearn", "numpy"}


def run_isolated(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path.cwd(), timeout=60)


def test_the_safe_module_loads_and_predicts_with_every_forbidden_module_blocked():
    data = canonical_bytes(imputed_doc())
    code = (
        "import sys\n"
        "for m in ('joblib','pickle','cloudpickle','numpy','sklearn','scipy','dill'):\n"
        "    sys.modules[m] = None\n"
        "import src.models.safe_artifact_format as f\n"
        f"data = bytes.fromhex('{data.hex()}')\n"
        "m = f.load_artifact(data, expected_sha256=f.artifact_sha256(data), expected_model_version='example_v1')\n"
        "print(repr(m.predict_proba_vector([4.0, 99.0, 1.0])))\n"
        "assert all(sys.modules[k] is None for k in ('joblib','pickle','numpy','sklearn'))\n"
    )
    result = run_isolated(code)
    assert result.returncode == 0, result.stderr
    expected = sigmoid_ref(((4.0 - 2.5) / 1.5) * 0.5 + ((1.0 - 0.2) / 0.4) * -0.25 + 0.1)
    assert float(result.stdout.strip()) == pytest.approx(expected, abs=1e-15)


def test_the_exporter_module_imports_without_scikit_learn_or_numpy():
    code = (
        "import sys\n"
        "for m in ('sklearn','numpy','scipy','joblib','pickle'):\n"
        "    sys.modules[m] = None\n"
        "import src.models.safe_artifact_export as e\n"
        "print('ok', hasattr(e, 'export_platt_logreg'))\n"
    )
    result = run_isolated(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok True"


def test_importing_the_safe_modules_does_not_import_scikit_learn_or_numpy():
    code = (
        "import sys\n"
        "import src.models.safe_artifact_format, src.models.safe_artifact_export\n"
        "bad = [m for m in ('sklearn','numpy','joblib','scipy') if m in sys.modules]\n"
        "print(bad)\n"
    )
    result = run_isolated(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_nothing_in_src_scripts_or_config_imports_the_safe_modules_automatically():
    own = {SRC_FORMAT.resolve(), SRC_EXPORT.resolve()}
    offenders = []
    for root in ("src", "scripts", "config"):
        for path in Path(root).rglob("*.py"):
            if path.resolve() in own:
                continue
            text = path.read_text(encoding="utf-8")
            if "safe_artifact_format" in text or "safe_artifact_export" in text:
                offenders.append(str(path))
    assert offenders == []
    assert "safe_artifact" not in Path("src/models/__init__.py").read_text(encoding="utf-8")


HOSTILE_SCRIPT = """
import json, sys
if len(sys.argv) > 1 and sys.argv[1] == "canary":
    import pickle  # control: el detector DEBE verlo
import src.models.safe_artifact_format as f
cases = json.load(sys.stdin)
rejected = 0
for hex_data in cases:
    data = bytes.fromhex(hex_data)
    try:
        f.load_artifact(data, expected_sha256=f.artifact_sha256(data), expected_model_version="example_v1")
    except f.SafeArtifactError:
        rejected += 1
FORBIDDEN = ("joblib", "pickle", "cloudpickle", "dill", "shelve", "numpy", "scipy", "sklearn", "ctypes")
print(json.dumps({"rejected": rejected, "total": len(cases), "forbidden": sorted(m for m in FORBIDDEN if m in sys.modules)}))
"""


def hostile_corpus() -> list:
    return list(FORMAT_CASES.values()) + [dump(doc, ensure_ascii=True) for doc in SCHEMA_CASES.values()]


def run_hostile(*args: str) -> dict:
    corpus = hostile_corpus()
    result = subprocess.run(
        [sys.executable, "-c", HOSTILE_SCRIPT, *args], input=json.dumps([data.hex() for data in corpus]),
        capture_output=True, text=True, cwd=Path.cwd(), timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["total"] == len(corpus)
    return report


def test_hostile_payloads_are_all_rejected_and_no_deserializer_or_numeric_module_is_ever_imported():
    """Intérprete NUEVO: importa solo el módulo seguro, procesa TODOS los casos hostiles (formato y esquema) y comprueba el
    conjunto completo de `sys.modules`, no solo lo importado durante la prueba."""
    report = run_hostile()
    assert report["rejected"] == report["total"]
    assert report["forbidden"] == []


def test_the_forbidden_module_check_is_not_trivial_a_deliberate_import_is_detected():
    report = run_hostile("canary")  # mismo script, pero importando `pickle` a propósito antes que el módulo seguro
    assert report["forbidden"] == ["pickle"]
