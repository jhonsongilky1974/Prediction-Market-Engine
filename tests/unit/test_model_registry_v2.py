"""PR-3: analizador y selección del registro v2 (`package_models`).

Cuatro bloques, que reproducen la separación aprobada en `ARTIFACT_STORAGE_DECISION.md` (D8 y D16):

A. Una lista `package_models` inválida se rechaza ENTERA (`PackageRegistryError`), sin resultados parciales.
B. Varios candidatos `ALLOWED` bien formados dejan "sin modelo" SOLO a su grupo de selección (no es un error).
C. El lector heredado (`load_model_registry`) ignora `package_models` y conserva su comportamiento.
D. Aislamiento: sin E/S, sin importar el verificador de paquetes ni el almacén, y sin cablear.

Los datos son sintéticos. Ninguna prueba fija el hash del registro real ni que no tenga ningún `ALLOWED`: una promoción
legítima puede cambiar ambos.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import itertools
import json
from pathlib import Path

import pytest

from src.models.artifact_package import PackageSchemaError, canonical_package_manifest_bytes
from src.models.model_registry_policy import DEFAULT_MODEL_REGISTRY_PATH, RegistryStatus, load_model_registry
from src.models.model_registry_v2 import (
    PackageEntry,
    PackageRegistry,
    PackageRegistryError,
    PackageRole,
    SelectionOutcome,
    parse_package_registry,
    select_base,
    select_calibrator,
)
from src.storage.artifact_store import InvalidArtifactKeyError, validate_key

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "models" / "model_registry_v2.py"

KEY_1, KEY_2, KEY_3, KEY_4 = ("1" * 64, "2" * 64, "3" * 64, "4" * 64)
BASE_V, BASE_V2, CAL_V, CAL_V2 = "tennis_base_v2_a", "tennis_base_v2_b", "tennis_cal_v2_a", "tennis_cal_v2_b"
LEGACY_OK = {"model_version": "tennis_baseline_logreg_v1_legacy_ok", "status": "ALLOWED", "artifact_sha256": "c" * 64}
LEGACY_BAD = {"model_version": "tennis_baseline_logreg_v1_legacy_bad", "status": "INVALID", "reason": "r",
              "artifact_sha256": "a" * 64}
LEGACY_CAL = {"model_version": "tennis_calibrator_platt_v1_legacy", "status": "ALLOWED", "artifact_sha256": "d" * 64,
              "base_model_version": LEGACY_OK["model_version"], "metadata_sha256": "e" * 64}


def base(version=BASE_V, status="ALLOWED", key=KEY_1, reason="promoción de prueba", **over) -> dict:
    return {"model_version": version, "status": status, "reason": reason, "package_manifest_key": key,
            "role": "base", **over}


def cal(version=CAL_V, base_version=BASE_V, status="ALLOWED", key=KEY_2, reason="promoción de prueba", **over) -> dict:
    return {"model_version": version, "status": status, "reason": reason, "package_manifest_key": key,
            "role": "calibrator", "base_model_version": base_version, **over}


def doc(*entries, models=None, **top) -> dict:
    return {"schema_version": 1, "models": [LEGACY_BAD] if models is None else models,
            "package_models": list(entries), **top}


def registry(*entries) -> PackageRegistry:
    return parse_package_registry(doc(*entries))


def without(entry: dict, *keys) -> dict:
    return {k: v for k, v in entry.items() if k not in keys}


# =====================================================================
# A. Una lista inválida se rechaza entera
# =====================================================================


def test_the_error_is_a_value_error_and_a_registry_is_immutable():
    assert issubclass(PackageRegistryError, ValueError)
    result = registry(base())
    assert isinstance(result.entries, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.entries = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.entries[0].status = RegistryStatus.INVALID  # type: ignore[misc]


@pytest.mark.parametrize("document", [
    {}, {"schema_version": 1}, {"models": [LEGACY_OK]}, {"otra": 1},
    {"models": "no es una lista"}, {"models": None},  # sin la clave no hay nada que comparar: ni se mira `models`
])
def test_a_missing_package_models_key_is_an_empty_registry(document):
    assert parse_package_registry(document) == PackageRegistry(entries=())


@pytest.mark.parametrize("models", [None, "x", {}, [None], [{}], [{"model_version": 1}], [LEGACY_OK]])
def test_an_empty_list_is_an_empty_registry_even_if_models_could_not_be_compared(models):
    assert parse_package_registry({"package_models": [], "models": models}) == PackageRegistry(entries=())
    assert parse_package_registry({"package_models": []}) == PackageRegistry(entries=())


@pytest.mark.parametrize("document", [None, [], "x", 1, 1.5, True, (), b"{}"])
def test_the_document_must_be_a_json_object(document):
    with pytest.raises(PackageRegistryError):
        parse_package_registry(document)


@pytest.mark.parametrize("value", [None, {}, "x", "", 0, 1, True, False, 1.5, (), b"[]", {"a": 1}])
def test_a_present_package_models_that_is_not_a_list_is_rejected(value):
    with pytest.raises(PackageRegistryError):
        parse_package_registry({"models": [], "package_models": value})


@pytest.mark.parametrize("item", [None, [], "x", 1, True, 1.5, (), b"x", [base()]])
def test_an_entry_that_is_not_an_object_rejects_the_whole_list(item):
    with pytest.raises(PackageRegistryError):
        registry(base(), item)


@pytest.mark.parametrize("key", ["model_version", "status", "reason", "package_manifest_key", "role"])
def test_a_missing_required_key_rejects_the_whole_list_for_both_roles(key):
    with pytest.raises(PackageRegistryError):
        registry(without(base(), key))
    with pytest.raises(PackageRegistryError):
        registry(without(cal(), key))


@pytest.mark.parametrize("entry", [
    base(extra=1), base(path="x"), cal(extra=None), cal(status_note="x"),
], ids=["base+extra", "base+path", "cal+extra", "cal+note"])
def test_an_extra_key_rejects_the_whole_list(entry):
    with pytest.raises(PackageRegistryError):
        registry(entry)


@pytest.mark.parametrize("field", ["model_version", "status", "reason", "package_manifest_key", "role"])
@pytest.mark.parametrize("value", [None, 1, 1.5, True, False, [], {}, b"x"])
def test_a_wrongly_typed_field_rejects_the_whole_list(field, value):
    with pytest.raises(PackageRegistryError):
        registry(base(**{field: value}))


@pytest.mark.parametrize("status", ["allowed", "Allowed", "ALLOWED ", " ALLOWED", "", "REVOKED", "SUPERSEDED", "CANDIDATE_EVALUATION"])
def test_a_status_outside_the_three_existing_ones_is_rejected(status):
    with pytest.raises(PackageRegistryError):
        registry(base(status=status))


@pytest.mark.parametrize("status", ["ALLOWED", "INVALID", "REJECTED_CANDIDATE"])
def test_the_three_existing_statuses_are_accepted_for_both_roles(status):
    result = registry(base(status=status), cal(status=status))
    assert [e.status for e in result.entries] == [RegistryStatus(status)] * 2


@pytest.mark.parametrize("role", ["Base", "BASE", "calibrador", "Calibrator", "", " base", "base ", "model", None, 1, True])
def test_a_missing_or_invalid_role_is_an_error_never_a_reclassification(role):
    with pytest.raises(PackageRegistryError):
        registry(base(role=role))
    with pytest.raises(PackageRegistryError):
        registry(cal(role=role))


def test_an_entry_without_role_is_never_reclassified_as_base_or_calibrator():
    with pytest.raises(PackageRegistryError):
        registry(without(base(), "role"))
    with pytest.raises(PackageRegistryError):
        registry(without(cal(), "role"))  # lleva base_model_version, pero sin rol no se deduce que sea calibrador


@pytest.mark.parametrize("value", [BASE_V, None, "", 1])
def test_a_base_entry_forbids_base_model_version_even_when_null(value):
    with pytest.raises(PackageRegistryError):
        registry(base(base_model_version=value))


def test_a_calibrator_requires_base_model_version():
    with pytest.raises(PackageRegistryError):
        registry(without(cal(), "base_model_version"))


@pytest.mark.parametrize("value", [None, "", "-x", "a b", "a/b", 1, True, "a" * 129, "é"])
def test_a_calibrator_needs_a_well_formed_base_model_version(value):
    with pytest.raises(PackageRegistryError):
        registry(cal(base_version=value))


def test_a_calibrator_cannot_reference_itself():
    with pytest.raises(PackageRegistryError):
        registry(cal(version="same_v1", base_version="same_v1"))
    # una referencia a otra versión, aunque no exista ni esté ALLOWED, no se comprueba (pendiente de D8)
    assert registry(cal(version="same_v1", base_version="other_v1")).entries[0].base_model_version == "other_v1"


MODEL_VERSION_CORPUS = [
    "a", "A", "0", "a" * 128, "a" * 129, "", "-a", "_a", ".a", " a", "a ", "a b", "a/b", "a\\b", "a\n", "a\t", "a\x00",
    "é", "aé", "a" * 64 + "é", "ａ", "٠a", "a٠", "../x", "x/../y", "a.b-c_d", "A.b-c_d9",
    "tennis_baseline_logreg_v1_20260801T184245Z", None, 1, True, b"a", ["a"],
]
KEY_CORPUS = [
    "a" * 64, "0123456789abcdef" * 4, "A" * 64, "a" * 63, "a" * 65, "", "g" * 64, "a" * 64 + "\n", " " + "a" * 63,
    "\n" + "a" * 63, "sha256/aa/" + "a" * 64, "a" * 63 + "é", "０" * 64, "a" * 32 + "٠" * 32, None, 1, True, b"a" * 64,
]


def _pr2_accepts_model_version(value) -> bool:
    manifest = {
        "schema_version": 1, "document_type": "artifact_package_manifest", "model_version": value,
        "artifact": {"key": KEY_1, "format": "safe_json_b1", "schema_version": 1,
                     "model_type": "imputed_standardized_logreg_v1"},
        "metadata": {"key": KEY_2, "schema_version": 1},
    }
    try:
        canonical_package_manifest_bytes(manifest)
    except PackageSchemaError:
        return False
    return True


def _store_accepts_key(value) -> bool:
    try:
        validate_key(value)
    except InvalidArtifactKeyError:
        return False
    return True


def test_the_concordance_checks_are_meaningful_the_reference_validators_accept_a_known_good_value():
    assert _pr2_accepts_model_version("pkg_example_v1") is True
    assert _pr2_accepts_model_version("a b") is False
    assert _store_accepts_key("a" * 64) is True
    assert _store_accepts_key("A" * 64) is False


@pytest.mark.parametrize("value", MODEL_VERSION_CORPUS, ids=repr)
def test_model_version_rules_agree_with_the_package_verifier_by_behaviour(value):
    try:
        registry(base(version=value))
        v2_accepts = True
    except PackageRegistryError:
        v2_accepts = False
    assert v2_accepts == _pr2_accepts_model_version(value)
    try:
        registry(cal(base_version=value))
        v2_accepts_as_reference = True
    except PackageRegistryError:
        v2_accepts_as_reference = False
    assert v2_accepts_as_reference == _pr2_accepts_model_version(value)


@pytest.mark.parametrize("value", KEY_CORPUS, ids=repr)
def test_package_manifest_key_rules_agree_with_the_store_key_validator_by_behaviour(value):
    try:
        registry(base(key=value))
        v2_accepts = True
    except PackageRegistryError:
        v2_accepts = False
    assert v2_accepts == _store_accepts_key(value)


@pytest.mark.parametrize("reason", ["", " ", "   ", "\t", " ", "　", "   ", "a" * 501, "a\nb", "a\rb", "a\tb",
                                    "a\x00b", "a\x1fb", "a\x7fb", "a\x85b", "\n"])
def test_an_empty_blank_long_or_control_reason_is_rejected(reason):
    with pytest.raises(PackageRegistryError):
        registry(base(reason=reason))


@pytest.mark.parametrize("reason", ["x", "a" * 500, " con espacios internos y de borde ", "motivo con ñ y é: PR #16 — revertido",
                                    "a" * 499 + "é"])
def test_a_reason_of_one_to_five_hundred_characters_without_control_characters_is_accepted(reason):
    assert registry(base(reason=reason)).entries[0].reason == reason


def test_model_version_must_be_unique_inside_package_models_whatever_role_and_status():
    with pytest.raises(PackageRegistryError):
        registry(base(version="dup_v1"), base(version="dup_v1", key=KEY_3))
    with pytest.raises(PackageRegistryError):
        registry(base(version="dup_v1"), cal(version="dup_v1", base_version="otro_v1", status="INVALID"))
    # mayúsculas y minúsculas son versiones distintas
    assert len(registry(base(version="Dup_v1"), base(version="dup_v1", key=KEY_3)).entries) == 2


def test_model_version_must_be_unique_across_both_lists():
    with pytest.raises(PackageRegistryError):
        parse_package_registry(doc(base(version=LEGACY_BAD["model_version"]), models=[LEGACY_OK, LEGACY_BAD]))
    with pytest.raises(PackageRegistryError):
        parse_package_registry(doc(cal(version=LEGACY_CAL["model_version"], base_version="x_v1"), models=[LEGACY_CAL]))
    result = parse_package_registry(doc(base(version="tennis_baseline_logreg_v1_LEGACY_BAD"), models=[LEGACY_BAD]))
    assert len(result.entries) == 1


@pytest.mark.parametrize("models", [
    "missing", None, {}, "x", 1, [None], [1], ["x"], [{}], [{"status": "ALLOWED"}], [{"model_version": None}],
    [{"model_version": 1}], [{"model_version": ["a"]}], [LEGACY_OK, None], [LEGACY_OK, {"model_version": 3}],
], ids=repr)
def test_if_models_does_not_allow_comparing_versions_the_v2_list_is_rejected(models):
    document = {"package_models": [base()]}
    if models != "missing":
        document["models"] = models
    with pytest.raises(PackageRegistryError):
        parse_package_registry(document)


def test_models_is_only_read_for_its_structure_and_versions_not_validated_like_the_legacy_reader():
    odd = [{"model_version": "legacy_x", "status": "WHATEVER"}, {"model_version": "legacy_x", "status": "ALLOWED"},
           {"model_version": "legacy_y", "unknown": object()}]
    assert len(parse_package_registry(doc(base(), models=odd)).entries) == 1  # duplicados y estados raros: no es asunto de v2


def test_entries_keep_document_order_and_fields_and_none_for_base_model_version_of_a_base():
    result = registry(cal(), base(), cal(version=CAL_V2, base_version=BASE_V2, status="INVALID", reason="motivo"))
    assert result.entries == (
        PackageEntry(CAL_V, RegistryStatus.ALLOWED, "promoción de prueba", KEY_2, PackageRole.CALIBRATOR, BASE_V),
        PackageEntry(BASE_V, RegistryStatus.ALLOWED, "promoción de prueba", KEY_1, PackageRole.BASE, None),
        PackageEntry(CAL_V2, RegistryStatus.INVALID, "motivo", KEY_2, PackageRole.CALIBRATOR, BASE_V2),
    )


def test_two_different_versions_may_share_a_manifest_key_and_the_base_reference_is_not_resolved():
    shared = registry(base(version="v_a", key=KEY_3), base(version="v_b", key=KEY_3, status="INVALID"))
    assert [e.package_manifest_key for e in shared.entries] == [KEY_3, KEY_3]
    # el calibrador apunta a una versión inexistente y a otra INVALID: no se comprueba existencia ni estado
    orphan = registry(cal(base_version="no_existe_v1"), base(version="b_inv", status="INVALID"), cal(version="c2", base_version="b_inv"))
    assert len(orphan.entries) == 3


@pytest.mark.parametrize("bad_position", [0, 1, 2])
@pytest.mark.parametrize("bad", [
    base(version="malo_v1", status="REVOKED"), base(version="malo_v1", role="x"), base(version="malo v1"),
    cal(version="malo_v1", base_version="malo_v1"), base(version="malo_v1", reason=" "), "no es un objeto",
    base(version=BASE_V),  # duplicado de otra entrada válida
], ids=["status", "role", "version", "self-ref", "reason", "no-objeto", "duplicado"])
def test_one_invalid_entry_anywhere_rejects_everything_without_partial_results(bad_position, bad):
    valid = [base(), cal(), base(version=BASE_V2, status="INVALID", key=KEY_3)]
    entries = valid[:bad_position] + [bad] + valid[bad_position:]
    result = None
    with pytest.raises(PackageRegistryError):
        result = parse_package_registry(doc(*entries))
    assert result is None


def test_a_defect_is_an_error_even_when_the_valid_entries_would_only_be_an_ambiguous_group():
    with pytest.raises(PackageRegistryError):
        registry(base(version="a_v1"), base(version="b_v1", key=KEY_3), base(version="c_v1", status="nope"))


def test_the_input_document_is_never_modified():
    good = doc(base(), cal(), models=[LEGACY_OK, LEGACY_BAD])
    snapshot = copy.deepcopy(good)
    parse_package_registry(good)
    assert good == snapshot
    bad = doc(base(), base(version=BASE_V))
    snapshot = copy.deepcopy(bad)
    with pytest.raises(PackageRegistryError):
        parse_package_registry(bad)
    assert bad == snapshot


# =====================================================================
# B. Selección: la ambigüedad afecta solo a su grupo y no es un error de formato
# =====================================================================


def test_selection_without_candidates_is_no_candidate_with_no_entry():
    result = registry(base(status="INVALID"), base(version=BASE_V2, status="REJECTED_CANDIDATE", key=KEY_3))
    for selection in (select_base(result), select_calibrator(result, "cualquiera_v1"), select_base(PackageRegistry())):
        assert selection.outcome is SelectionOutcome.NO_CANDIDATE and selection.entry is None


def test_a_single_allowed_candidate_is_selected_per_group():
    result = registry(base(), cal(), cal(version=CAL_V2, base_version=BASE_V2, key=KEY_3))
    assert select_base(result).outcome is SelectionOutcome.SELECTED
    assert select_base(result).entry.model_version == BASE_V
    assert select_calibrator(result, BASE_V).entry.model_version == CAL_V
    assert select_calibrator(result, BASE_V2).entry.model_version == CAL_V2
    assert select_calibrator(result, "otra_v1").outcome is SelectionOutcome.NO_CANDIDATE


def test_invalid_and_rejected_entries_do_not_make_a_group_ambiguous():
    result = registry(base(), base(version=BASE_V2, status="INVALID", key=KEY_3),
                      base(version="b3", status="REJECTED_CANDIDATE", key=KEY_4),
                      cal(), cal(version=CAL_V2, status="INVALID", key=KEY_3))
    assert select_base(result).entry.model_version == BASE_V
    assert select_calibrator(result, BASE_V).entry.model_version == CAL_V


def test_two_allowed_bases_leave_only_the_base_group_without_model():
    result = registry(base(), base(version=BASE_V2, key=KEY_3), cal(), cal(version=CAL_V2, base_version=BASE_V2, key=KEY_4))
    selection = select_base(result)
    assert selection.outcome is SelectionOutcome.AMBIGUOUS and selection.entry is None
    # los grupos de calibradores no se ven afectados
    assert select_calibrator(result, BASE_V).entry.model_version == CAL_V
    assert select_calibrator(result, BASE_V2).entry.model_version == CAL_V2


def test_two_allowed_calibrators_of_one_base_leave_only_that_group_without_model():
    result = registry(base(), cal(), cal(version=CAL_V2, base_version=BASE_V, key=KEY_3),
                      cal(version="cal_other", base_version=BASE_V2, key=KEY_4))
    ambiguous = select_calibrator(result, BASE_V)
    assert ambiguous.outcome is SelectionOutcome.AMBIGUOUS and ambiguous.entry is None
    assert select_base(result).entry.model_version == BASE_V
    assert select_calibrator(result, BASE_V2).entry.model_version == "cal_other"


def test_three_or_more_candidates_are_also_ambiguous():
    result = registry(*[base(version=f"b_{i}", key=str(i) * 64) for i in range(1, 5)])
    assert select_base(result).outcome is SelectionOutcome.AMBIGUOUS


def test_ambiguity_is_a_selection_result_not_a_format_error():
    document = doc(base(), base(version=BASE_V2, key=KEY_3), cal(), cal(version=CAL_V2, base_version=BASE_V, key=KEY_4))
    parsed = parse_package_registry(document)  # bien formado: no lanza
    assert len(parsed.entries) == 4
    assert select_base(parsed).outcome is SelectionOutcome.AMBIGUOUS
    assert select_calibrator(parsed, BASE_V).outcome is SelectionOutcome.AMBIGUOUS


def test_selection_does_not_depend_on_entry_order():
    entries = [base(), base(version=BASE_V2, key=KEY_3), cal(), cal(version=CAL_V2, base_version=BASE_V2, key=KEY_4),
               cal(version="c3", base_version=BASE_V2, key=KEY_1)]
    outcomes = set()
    for permutation in itertools.permutations(entries):
        result = registry(*permutation)
        outcomes.add((select_base(result).outcome, select_calibrator(result, BASE_V).outcome,
                      select_calibrator(result, BASE_V2).outcome))
    assert outcomes == {(SelectionOutcome.AMBIGUOUS, SelectionOutcome.SELECTED, SelectionOutcome.AMBIGUOUS)}


def test_legacy_allowed_entries_do_not_take_part_in_the_v2_groups():
    result = parse_package_registry(doc(base(), models=[LEGACY_OK, LEGACY_CAL]))
    assert select_base(result).entry.model_version == BASE_V  # el ALLOWED heredado no hace ambiguo el grupo v2
    assert select_calibrator(result, LEGACY_OK["model_version"]).outcome is SelectionOutcome.NO_CANDIDATE


def test_selection_arguments_are_validated_and_do_not_mutate_anything():
    result = registry(base(), cal())
    for bad in (None, "", "a b", 1, True, "x" * 129):
        with pytest.raises(PackageRegistryError):
            select_calibrator(result, bad)
    for not_a_registry in (None, [], {"entries": ()}, result.entries):
        with pytest.raises(PackageRegistryError):
            select_base(not_a_registry)  # type: ignore[arg-type]
        with pytest.raises(PackageRegistryError):
            select_calibrator(not_a_registry, BASE_V)  # type: ignore[arg-type]
    assert result == registry(base(), cal())


def test_selection_results_are_immutable_and_only_selected_carries_an_entry():
    result = registry(base(), base(version=BASE_V2, key=KEY_3))
    selection = select_base(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        selection.entry = result.entries[0]  # type: ignore[misc]
    assert {o.value for o in SelectionOutcome} == {"SELECTED", "NO_CANDIDATE", "AMBIGUOUS"}
    assert select_base(registry(base())).entry is not None


# =====================================================================
# C. El lector heredado ignora `package_models` y conserva su comportamiento
# =====================================================================


def _legacy_file(tmp_path: Path, name: str, **top) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"schema_version": 1, "models": [LEGACY_BAD, LEGACY_OK, LEGACY_CAL], **top}), encoding="utf-8")
    return path


V2_VARIANTS = {
    "valida": [base(), cal()],
    "valida-con-ALLOWED-duplicados": [base(), base(version=BASE_V2, key=KEY_3), cal(), cal(version=CAL_V2, key=KEY_4)],
    "vacia": [],
    "null": None,
    "objeto": {"a": 1},
    "cadena": "no es una lista",
    "numero": 7,
    "entradas-basura": [None, 1, "x", [], {}],
    "estado-desconocido": [base(status="REVOKED")],
    "rol-invalido": [base(role="otro")],
    "version-duplicada": [base(version="dup_v1"), base(version="dup_v1", key=KEY_3)],
    "version-igual-a-una-heredada": [base(version=LEGACY_OK["model_version"])],
    "claves-extra": [base(extra=1)],
}


@pytest.mark.parametrize("name", sorted(V2_VARIANTS))
def test_the_legacy_reader_ignores_package_models_whatever_it_contains(tmp_path, name):
    baseline = load_model_registry(_legacy_file(tmp_path, "sin_v2.json"))
    assert baseline.load_error is None

    policy = load_model_registry(_legacy_file(tmp_path, "con_v2.json", package_models=V2_VARIANTS[name]))

    assert policy.load_error is None
    assert policy == baseline  # mismas entradas, mismo estado
    assert sorted(policy.entries) == sorted([LEGACY_BAD["model_version"], LEGACY_OK["model_version"], LEGACY_CAL["model_version"]])


def test_legacy_decisions_are_unchanged_by_valid_v2_entries(tmp_path):
    v2_entries = [base(version="v2_base_a", key="9" * 64), cal(version="v2_cal_a", base_version=LEGACY_OK["model_version"], key="8" * 64)]
    baseline = load_model_registry(_legacy_file(tmp_path, "sin_v2.json"))
    policy = load_model_registry(_legacy_file(tmp_path, "con_v2.json", package_models=v2_entries))

    legacy_base = LEGACY_OK["model_version"]
    assert policy.check(legacy_base, LEGACY_OK["artifact_sha256"]) == baseline.check(legacy_base, LEGACY_OK["artifact_sha256"])
    assert policy.check(legacy_base, LEGACY_OK["artifact_sha256"])[0] is True
    assert policy.allowed_calibrators_for_base(legacy_base) == baseline.allowed_calibrators_for_base(legacy_base)
    assert [e.model_version for e in policy.allowed_calibrators_for_base(legacy_base)] == [LEGACY_CAL["model_version"]]
    # una entrada v2 ALLOWED nunca es activable para el lector heredado, ni con la clave del manifiesto como hash
    assert policy.check("v2_base_a", "9" * 64)[0] is False
    assert policy.check("v2_cal_a", "8" * 64)[0] is False


def test_a_status_the_legacy_reader_would_reject_inside_models_is_harmless_inside_package_models(tmp_path):
    inside_models = tmp_path / "dentro_de_models.json"
    inside_models.write_text(json.dumps({"models": [LEGACY_OK, {"model_version": "m_v2", "status": "REVOKED"}]}), encoding="utf-8")
    assert load_model_registry(inside_models).load_error is not None  # por eso no se usa `models`

    outside = _legacy_file(tmp_path, "fuera.json", package_models=[base(version="m_v2", status="REVOKED")])
    assert load_model_registry(outside).load_error is None


def test_the_two_readers_are_independent_a_bad_v2_list_does_not_affect_the_legacy_registry(tmp_path):
    path = _legacy_file(tmp_path, "mixto.json", package_models=[base(), base(version=BASE_V)])
    assert load_model_registry(path).load_error is None
    with pytest.raises(PackageRegistryError):
        parse_package_registry(json.loads(path.read_text(encoding="utf-8")))


def test_the_real_registry_file_is_valid_for_both_readers():
    # Solo comprueba que ambos lectores aceptan el archivo real tal como está hoy; no fija su contenido ni su hash.
    assert load_model_registry(DEFAULT_MODEL_REGISTRY_PATH).load_error is None
    real = json.loads(DEFAULT_MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(parse_package_registry(real), PackageRegistry)


# =====================================================================
# D. Aislamiento: sin E/S, sin verificador ni almacén, sin cablear
# =====================================================================

ALLOWED_IMPORT_MODULES = {"__future__", "re", "unicodedata", "dataclasses", "enum", "typing", "src.models.model_registry_policy"}
FORBIDDEN_TEXT = ("artifact_package", "artifact_store", "local_filesystem_store", "LocalFilesystemStore",
                  "safe_artifact_format", "safe_artifact_export")
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input"}
FORBIDDEN_ATTRIBUTES = {"read_text", "read_bytes", "write_text", "write_bytes", "open", "unlink", "mkdir", "glob", "rglob",
                        "listdir", "walk", "environ", "getenv"}


def _tree() -> ast.AST:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def test_the_module_imports_only_the_allowed_modules_and_only_the_status_enum_from_the_legacy_one():
    imported, names_from_policy = set(), set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            if node.module == "src.models.model_registry_policy":
                names_from_policy |= {alias.name for alias in node.names}
    assert imported <= ALLOWED_IMPORT_MODULES, imported - ALLOWED_IMPORT_MODULES
    assert names_from_policy == {"RegistryStatus"}


def test_the_admitted_statuses_are_enumerated_explicitly_and_never_taken_by_walking_the_legacy_enum():
    def is_status(node) -> bool:
        return isinstance(node, ast.Name) and node.id == "RegistryStatus"

    walked = []
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.comprehension, ast.For)) and is_status(node.iter):
            walked.append("iteración sobre RegistryStatus")
        if isinstance(node, ast.Call) and any(is_status(arg) for arg in node.args):
            walked.append("RegistryStatus pasado a una llamada (list, tuple, set…)")
        if isinstance(node, ast.Attribute) and is_status(node.value) and node.attr.startswith(("__members__", "_member", "_value2")):
            walked.append(f"acceso interno {node.attr}")
    assert walked == []


def test_the_module_does_no_io_and_never_mentions_the_verifier_or_the_blob_store():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert [word for word in FORBIDDEN_TEXT if word in text] == []
    called, attributes = set(), set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
        if isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    assert called & FORBIDDEN_CALLS == set()
    assert attributes & FORBIDDEN_ATTRIBUTES == set()


def test_the_module_does_not_touch_the_legacy_reader_or_the_registry_file():
    text = MODULE_PATH.read_text(encoding="utf-8")
    for word in ("load_model_registry", "DEFAULT_MODEL_REGISTRY_PATH", "model_registry.json", "ModelRegistryPolicy"):
        assert word not in text.replace("`config/model_registry.json`", "")  # solo se nombra el archivo en el docstring


def test_nothing_in_src_scripts_or_config_references_the_module_and_the_package_init_stays_empty():
    offenders = []
    for top in ("src", "scripts", "config"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            if path.resolve() == MODULE_PATH.resolve():
                continue
            if "model_registry_v2" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    assert (REPO_ROOT / "src" / "models" / "__init__.py").read_text(encoding="utf-8") == ""
