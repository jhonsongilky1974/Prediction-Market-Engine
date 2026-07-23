"""Tests del feature registry (Fase 2, Paso 1).

Cubren el contrato exacto de PLAN_PHASE2.md §4: cada feature FULLY_SPECIFIED
declara las 10/11 dimensiones requeridas (nombre, deporte, fuente, timestamp
de disponibilidad, fórmula, unidad, tratamiento de missing, riesgo de
leakage, validación, importancia esperada, disponibilidad); ninguna feature
REFERENCE_ONLY (bloqueada/no especificada todavía) fabrica esos campos; y
las validaciones condicionales del modelo rechazan combinaciones inválidas.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.features.registry import (
    CURRENT_FEATURE_SET_VERSION,
    FEATURE_REGISTRY,
    DataAvailability,
    ExpectedImportance,
    FeatureDefinition,
    LeakageRisk,
    SpecStatus,
    get_feature,
    list_computable_features,
    list_features,
    validate_registry,
)
from src.models.schemas import Sport

REQUIRED_FULLY_SPECIFIED_FIELDS = (
    "availability_timestamp",
    "formula",
    "unit",
    "missing_treatment",
    "leakage_risk",
    "expected_importance",
    "compute_function_name",
)

EXPECTED_MLB_BASELINE_NAMES = {
    "pitcher_era_season",
    "pitcher_whip_season",
    "pitcher_k_pct",
    "pitcher_bb_pct",
    "pitcher_ip_season",
    "pitcher_form_last5",
    "pitcher_vs_opponent_handedness_ops",
    "bullpen_era_recent",
    "team_record_pct",
    "team_ops_season",
    "home_away",
    "il_flag_key_players",
}

EXPECTED_TENNIS_BASELINE_NAMES = {"rest_days", "tournament_round_context"}


# =========================================================================
# Contrato de 10/11 dimensiones (Paso 1, requisito central)
# =========================================================================

def test_every_fully_specified_feature_has_all_required_dimensions():
    for feature in list_features(spec_status=SpecStatus.FULLY_SPECIFIED):
        for field_name in REQUIRED_FULLY_SPECIFIED_FIELDS:
            value = getattr(feature, field_name)
            assert value is not None, f"'{feature.name}' le falta '{field_name}'"
            if isinstance(value, str):
                assert value.strip() != "", f"'{feature.name}'.{field_name} está vacío"


def test_every_feature_has_name_sport_source_availability():
    """Las 4 dimensiones que TODA feature debe tener, especificada o no."""
    for feature in FEATURE_REGISTRY:
        assert feature.name
        assert feature.sport in (Sport.MLB, Sport.TENNIS)
        assert feature.source
        assert feature.data_availability in (
            DataAvailability.AVAILABLE,
            DataAvailability.PARTIAL,
            DataAvailability.BLOCKED,
        )


def test_reference_only_features_never_fabricate_computation_contract():
    """Las features bloqueadas/no especificadas NUNCA declaran una función
    de cálculo -- eso sería aparentar que están listas para Paso 2 cuando
    no lo están."""
    for feature in list_features(spec_status=SpecStatus.REFERENCE_ONLY):
        assert feature.compute_function_name is None, (
            f"'{feature.name}' es REFERENCE_ONLY pero declara "
            f"compute_function_name={feature.compute_function_name!r}"
        )


def test_non_available_features_always_declare_limitation_reason():
    for feature in FEATURE_REGISTRY:
        if feature.data_availability != DataAvailability.AVAILABLE:
            assert feature.limitation_reason, (
                f"'{feature.name}' tiene data_availability="
                f"{feature.data_availability.value} sin limitation_reason"
            )


# =========================================================================
# Validaciones condicionales del modelo (adversariales)
# =========================================================================

def test_fully_specified_cannot_be_blocked():
    """Regresión directa de la regla del plan: 'no se implementa en detalle
    antes de tener la fuente verificada'."""
    with pytest.raises(ValidationError, match="no es compatible con"):
        FeatureDefinition(
            name="x_blocked_but_fully_specified",
            sport=Sport.MLB,
            data_availability=DataAvailability.BLOCKED,
            spec_status=SpecStatus.FULLY_SPECIFIED,
            limitation_reason="motivo cualquiera",
            source="fuente",
            availability_timestamp="ya",
            formula="f(x)",
            unit="u",
            missing_treatment="NULL",
            leakage_risk=LeakageRisk.NONE,
            expected_importance=ExpectedImportance.LOW,
            compute_function_name="compute_x",
        )


def test_fully_specified_missing_a_required_field_is_rejected():
    with pytest.raises(ValidationError, match="le faltan campos obligatorios"):
        FeatureDefinition(
            name="x_incomplete",
            sport=Sport.MLB,
            data_availability=DataAvailability.AVAILABLE,
            spec_status=SpecStatus.FULLY_SPECIFIED,
            source="fuente",
            availability_timestamp="ya",
            formula="f(x)",
            unit="u",
            missing_treatment="NULL",
            leakage_risk=LeakageRisk.NONE,
            expected_importance=ExpectedImportance.LOW,
            compute_function_name=None,  # falta a propósito
        )


def test_reference_only_declaring_compute_function_is_rejected():
    with pytest.raises(ValidationError, match="no debe declarar compute_function_name"):
        FeatureDefinition(
            name="x_reference_with_compute",
            sport=Sport.MLB,
            data_availability=DataAvailability.BLOCKED,
            spec_status=SpecStatus.REFERENCE_ONLY,
            limitation_reason="motivo",
            source="fuente",
            compute_function_name="compute_x",  # no debería tenerlo
        )


def test_blocked_without_limitation_reason_is_rejected():
    with pytest.raises(ValidationError, match="requiere limitation_reason"):
        FeatureDefinition(
            name="x_blocked_no_reason",
            sport=Sport.MLB,
            data_availability=DataAvailability.BLOCKED,
            spec_status=SpecStatus.REFERENCE_ONLY,
            source="fuente",
        )


def test_available_reference_only_without_limitation_reason_is_valid():
    """Contraprueba: AVAILABLE nunca requiere limitation_reason."""
    feature = FeatureDefinition(
        name="x_available_reference",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.REFERENCE_ONLY,
        source="fuente",
    )
    assert feature.limitation_reason is None


def test_feature_definition_is_immutable():
    """Consistente con el espíritu append-only del Paso 0: una definición
    de feature no debe poder mutarse en memoria después de construida."""
    feature = get_feature("pitcher_era_season")
    with pytest.raises(ValidationError):
        feature.expected_importance = ExpectedImportance.LOW


# =========================================================================
# Integridad del registry completo
# =========================================================================

def test_no_duplicate_feature_names():
    names = [f.name for f in FEATURE_REGISTRY]
    assert len(names) == len(set(names))


def test_validate_registry_detects_duplicate_names():
    a = FeatureDefinition(
        name="dup", sport=Sport.MLB, data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.REFERENCE_ONLY, source="s",
    )
    b = FeatureDefinition(
        name="dup", sport=Sport.MLB, data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.REFERENCE_ONLY, source="s",
    )
    with pytest.raises(ValueError, match="duplicados"):
        validate_registry([a, b])


def test_all_features_use_current_feature_set_version():
    for feature in FEATURE_REGISTRY:
        assert feature.feature_set_version == CURRENT_FEATURE_SET_VERSION


def test_mlb_baseline_v1_names_match_approved_plan():
    """Ninguna feature del baseline v1 de MLB (PLAN_PHASE2.md §4.1) falta
    ni sobra respecto a lo aprobado."""
    actual = {f.name for f in list_computable_features(sport=Sport.MLB)}
    assert actual == EXPECTED_MLB_BASELINE_NAMES


def test_tennis_baseline_v1_names_match_approved_plan():
    actual = {f.name for f in list_computable_features(sport=Sport.TENNIS)}
    assert actual == EXPECTED_TENNIS_BASELINE_NAMES


def test_only_market_context_is_prohibited_as_model_input():
    prohibited = [f.name for f in FEATURE_REGISTRY if f.prohibited_as_model_input]
    assert prohibited == ["market_context"]


def test_importance_explicitly_approved_flag_used_only_where_documented():
    """Regresión de auditoría del Paso 1: el plan aprobado solo restablece
    explícitamente leakage/missing para el grupo pitcher_whip_season/
    pitcher_k_pct/pitcher_bb_pct/pitcher_ip_season ("Resto: Igual patrón
    que pitcher_era_season -- mismo riesgo de leakage..., mismo
    tratamiento de missing"), NUNCA la importancia -- deben tratarse con
    la misma transparencia que team_record_pct/team_ops_season/home_away,
    no con un estándar más laxo."""
    inferred = {f.name for f in FEATURE_REGISTRY if not f.importance_explicitly_approved}
    assert inferred == {
        "team_record_pct",
        "team_ops_season",
        "home_away",
        "pitcher_whip_season",
        "pitcher_k_pct",
        "pitcher_bb_pct",
        "pitcher_ip_season",
    }


def test_get_feature_raises_for_unknown_name():
    with pytest.raises(KeyError):
        get_feature("no_existe_esta_feature")


def test_get_feature_returns_exact_match():
    feature = get_feature("rest_days")
    assert feature.name == "rest_days"
    assert feature.sport == Sport.TENNIS


def test_list_features_filters_combine_correctly():
    result = list_features(
        sport=Sport.TENNIS,
        spec_status=SpecStatus.REFERENCE_ONLY,
        data_availability=DataAvailability.BLOCKED,
    )
    assert result  # hay varias (ranking_a, surface, h2h, ...)
    for f in result:
        assert f.sport == Sport.TENNIS
        assert f.spec_status == SpecStatus.REFERENCE_ONLY
        assert f.data_availability == DataAvailability.BLOCKED


def test_leakage_high_features_have_explicit_leakage_notes():
    """Las features de más riesgo (HIGH) deben traer una nota explicando
    por qué, no solo la etiqueta -- son las más peligrosas para leakage
    silencioso (riesgo #4 del plan)."""
    high_risk = [f for f in FEATURE_REGISTRY if f.leakage_risk == LeakageRisk.HIGH]
    assert len(high_risk) >= 2  # pitcher_form_last5, bullpen_era_recent
    for f in high_risk:
        assert f.leakage_notes, f"'{f.name}' es HIGH leakage sin leakage_notes"


def test_registry_import_does_not_raise():
    """El propio import ya corre validate_registry() (fail-fast); si el
    módulo se pudo importar en conftest/otros tests, esto ya lo prueba
    implícitamente, pero se deja explícito como test nombrado."""
    from src.features import registry as registry_module

    assert len(registry_module.FEATURE_REGISTRY) > 0


# =========================================================================
# Regresión de la auditoría del Paso 1
# =========================================================================

def test_feature_registry_container_is_immutable():
    """Hallazgo 1: FEATURE_REGISTRY era una list mutable; un
    .append()/.clear() externo la corrompía en silencio."""
    assert isinstance(FEATURE_REGISTRY, tuple)
    with pytest.raises(AttributeError):
        FEATURE_REGISTRY.append("x")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        FEATURE_REGISTRY.clear()  # type: ignore[attr-defined]


def test_list_features_without_filters_returns_a_defensive_copy():
    """Hallazgo 2: list_features() sin argumentos devolvía la propia
    FEATURE_REGISTRY por referencia; mutar el resultado corrompía el
    registry real."""
    result = list_features()
    assert result is not FEATURE_REGISTRY
    assert result == list(FEATURE_REGISTRY)

    before = len(FEATURE_REGISTRY)
    result.append(get_feature("rest_days"))  # mutar el resultado
    assert len(FEATURE_REGISTRY) == before  # el registry real no cambia


def test_list_features_with_filters_also_returns_defensive_copies():
    result = list_features(sport=Sport.MLB)
    before = len(FEATURE_REGISTRY)
    result.clear()
    assert len(FEATURE_REGISTRY) == before


def test_home_away_has_no_leakage_risk():
    """Hallazgo 4: home_away heredaba LOW de una fila agrupada del plan
    cuya justificación (estadística acumulada, requiere fijar cutoff) no
    aplica a este campo -- es un hecho estructural fijo del calendario."""
    feature = get_feature("home_away")
    assert feature.leakage_risk == LeakageRisk.NONE


def test_pitcher_secondary_stats_importance_is_flagged_as_inferred():
    """Hallazgo 3: el plan solo restablece explícitamente leakage/missing
    para este grupo ('Resto: Igual patrón que pitcher_era_season'), nunca
    la importancia -- debe marcarse como inferida, igual que el grupo de
    stats de equipo."""
    for name in ("pitcher_whip_season", "pitcher_k_pct", "pitcher_bb_pct", "pitcher_ip_season"):
        feature = get_feature(name)
        assert feature.importance_explicitly_approved is False, (
            f"'{name}' debería estar marcada como importancia inferida"
        )


def test_no_duplicate_compute_function_names():
    """Dos features con el mismo compute_function_name colisionarían en
    Paso 2 (una función sobrescribiría el contrato de la otra)."""
    names = [f.compute_function_name for f in FEATURE_REGISTRY if f.compute_function_name]
    assert len(names) == len(set(names))
