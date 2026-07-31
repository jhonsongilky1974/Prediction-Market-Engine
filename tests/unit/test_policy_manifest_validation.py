"""Tests de validate_policy_manifest()/load_policy_manifest()/
save_policy_manifest() (Fase 3, Paso 3.4.5). Ver FASE3_EXECUTION_PLAN.md,
Paso 3.4.5, y POLICY_ENGINE_SPEC.md §5 (Corrección H) -- los 3 casos de
rechazo negativo pedidos (regla/umbral/componente desconocido), más el
caso positivo de un manifiesto válido.
"""
from __future__ import annotations

import pytest

from src.policy.manifest import load_policy_manifest, save_policy_manifest
from src.policy.schemas import PolicyManifest
from src.policy.validation import validate_policy_manifest
from tests.unit.fase3_factories import make_policy_manifest


# ---------------------------------------------------------------------
# Caso positivo
# ---------------------------------------------------------------------


def test_valid_manifest_passes():
    validate_policy_manifest(make_policy_manifest())  # no debe lanzar


def test_valid_manifest_with_hard_rule_parameters_passes():
    validate_policy_manifest(
        make_policy_manifest(hard_rule_parameters={"pending_lineup_hours_threshold": 4.0})
    )


# ---------------------------------------------------------------------
# Rechazo: rule_id desconocido
# ---------------------------------------------------------------------


def test_unknown_hard_block_rule_id_rejected():
    manifest = make_policy_manifest(hard_block_rules=["totally_made_up_rule"])
    with pytest.raises(ValueError, match="hard_block_rules contiene rule_id desconocidos"):
        validate_policy_manifest(manifest)


def test_unknown_hard_hold_rule_id_rejected():
    manifest = make_policy_manifest(hard_hold_rules=["totally_made_up_rule"])
    with pytest.raises(ValueError, match="hard_hold_rules contiene rule_id desconocidos"):
        validate_policy_manifest(manifest)


# ---------------------------------------------------------------------
# Rechazo: umbral fuera de rango
# ---------------------------------------------------------------------


def test_enter_below_watch_rejected_at_schema_level():
    """enter_global_threshold >= watch_global_threshold ya se valida en
    el propio contrato PolicyManifest (Paso 3.0) -- confirmamos que la
    cadena completa (construcción) lo rechaza antes de llegar siquiera a
    validate_policy_manifest()."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="enter_global_threshold"):
        make_policy_manifest(enter_global_threshold=30.0, watch_global_threshold=40.0)


def test_critical_minimum_out_of_range_rejected():
    manifest = make_policy_manifest(critical_minimums={"ev_neto_strength": 150.0})
    with pytest.raises(ValueError, match=r"critical_minimums\['ev_neto_strength'\]=150.0 fuera de \[0,100\]"):
        validate_policy_manifest(manifest)


def test_negative_soft_score_weight_rejected():
    manifest = make_policy_manifest(soft_score_weights={"edge_strength": -0.1})
    with pytest.raises(ValueError, match="no puede ser negativo"):
        validate_policy_manifest(manifest)


def test_zero_sum_soft_score_weights_rejected():
    manifest = make_policy_manifest(soft_score_weights={"edge_strength": 0.0})
    with pytest.raises(ValueError, match="suma de soft_score_weights debe ser > 0"):
        validate_policy_manifest(manifest)


def test_negative_hard_rule_parameter_rejected():
    manifest = make_policy_manifest(hard_rule_parameters={"pending_lineup_hours_threshold": -1.0})
    with pytest.raises(ValueError, match="no puede ser negativo"):
        validate_policy_manifest(manifest)


# ---------------------------------------------------------------------
# Rechazo: component_name / parameter key desconocido
# ---------------------------------------------------------------------


def test_unknown_critical_minimum_component_rejected():
    manifest = make_policy_manifest(critical_minimums={"not_a_real_component": 50.0})
    with pytest.raises(ValueError, match="critical_minimums contiene component_name desconocidos"):
        validate_policy_manifest(manifest)


def test_unknown_soft_score_weight_component_rejected():
    manifest = make_policy_manifest(soft_score_weights={"not_a_real_component": 0.5})
    with pytest.raises(ValueError, match="soft_score_weights contiene component_name desconocidos"):
        validate_policy_manifest(manifest)


def test_unknown_hard_rule_parameter_key_rejected():
    manifest = make_policy_manifest(hard_rule_parameters={"not_a_real_parameter": 1.0})
    with pytest.raises(ValueError, match="hard_rule_parameters contiene claves desconocidas"):
        validate_policy_manifest(manifest)


# ---------------------------------------------------------------------
# Acumulación de errores (no se detiene en el primero)
# ---------------------------------------------------------------------


def test_multiple_errors_all_reported_together():
    manifest = make_policy_manifest(
        hard_block_rules=["fake_rule"],
        critical_minimums={"fake_component": 50.0},
    )
    with pytest.raises(ValueError) as exc_info:
        validate_policy_manifest(manifest)
    message = str(exc_info.value)
    assert "hard_block_rules" in message
    assert "critical_minimums" in message


# ---------------------------------------------------------------------
# load_policy_manifest / save_policy_manifest -- "rechazado antes de ejecutarse"
# ---------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path):
    manifest = make_policy_manifest()
    path = tmp_path / "mlb_v1.json"
    save_policy_manifest(manifest, path)
    loaded = load_policy_manifest(path)
    assert loaded == manifest


def test_save_rejects_invalid_manifest_before_writing(tmp_path):
    manifest = make_policy_manifest(hard_block_rules=["fake_rule"])
    path = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match="hard_block_rules"):
        save_policy_manifest(manifest, path)
    assert not path.exists()


def test_load_rejects_invalid_manifest_content(tmp_path):
    """Un archivo con un PolicyManifest estructuralmente válido pero con
    un rule_id desconocido (nunca pudo haberse escrito vía
    save_policy_manifest, que ya lo habría rechazado) -- confirma que
    load_policy_manifest() también lo rechaza, nunca lo carga a medias."""
    manifest = PolicyManifest.model_construct(
        **{**make_policy_manifest().model_dump(), "hard_block_rules": ["fake_rule"]}
    )
    path = tmp_path / "manually_written_invalid.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="hard_block_rules"):
        load_policy_manifest(path)
