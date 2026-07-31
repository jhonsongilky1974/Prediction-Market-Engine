"""Policy Validation -- Corrección H (Fase 3, Paso 3.4.5). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.4.5, y POLICY_ENGINE_SPEC.md §5.

De las 6 validaciones de Corrección H, este módulo implementa las 3
determinísticas, sin dependencia de histórico:

1. Schema validation -- ya automática vía `PolicyManifest(extra="forbid")`
   (Paso 3.0) y sus propios invariantes (`enter_global_threshold >=
   watch_global_threshold`, timestamps tz-aware) -- este módulo no la
   reimplementa, solo la reafirma como parte de la cadena de validación.
2. Range validation -- valores de `critical_minimums`/`soft_score_weights`/
   `hard_rule_parameters` en rangos razonables.
3. Cross-field consistency validation -- todo `rule_id`/`component_name`/
   parámetro referenciado existe en un catálogo cerrado ya definido en
   `hard_rules.py`/`soft_score.py`.

Las 3 restantes (regression tests, historical comparison, promotion
criteria) dependen de tener al menos un manifiesto previo publicado o
histórico real para comparar -- fuera de alcance de este paso, ver
`SHADOW_MODE_AND_PROMOTION_GATES.md` y DECISIÓN PENDIENTE D-1.

`validate_policy_manifest()` acumula TODOS los errores encontrados (no
se detiene en el primero) y los levanta juntos -- un manifiesto inválido
se rechaza antes de ejecutarse, nunca se carga parcialmente
(POLICY_ENGINE_SPEC.md §5, literal: "Una configuración inválida debe ser
rechazada antes de ejecutarse").
"""
from __future__ import annotations

from typing import List

from src.policy.hard_rules import (
    HARD_BLOCK_RULE_IDS,
    HARD_HOLD_RULE_IDS,
    KNOWN_HARD_RULE_PARAMETER_KEYS,
)
from src.policy.schemas import PolicyManifest
from src.policy.soft_score import SOFT_SCORE_COMPONENT_NAMES


def validate_policy_manifest(manifest: PolicyManifest) -> None:
    """Levanta ValueError con todos los errores encontrados si el
    manifiesto es inválido. No devuelve nada si es válido (mismo patrón
    "silencio = éxito" que las validaciones de src/quality/validators.py,
    Fase 1, adaptado aquí a levantar en vez de solo reportar, porque un
    PolicyManifest inválido nunca debe usarse)."""
    errors: List[str] = []

    # --- Cross-field consistency (rule_id / component_name / parameter keys) ---
    unknown_block_rules = set(manifest.hard_block_rules) - set(HARD_BLOCK_RULE_IDS)
    if unknown_block_rules:
        errors.append(f"hard_block_rules contiene rule_id desconocidos: {sorted(unknown_block_rules)}")

    unknown_hold_rules = set(manifest.hard_hold_rules) - set(HARD_HOLD_RULE_IDS)
    if unknown_hold_rules:
        errors.append(f"hard_hold_rules contiene rule_id desconocidos: {sorted(unknown_hold_rules)}")

    unknown_minimum_components = set(manifest.critical_minimums) - set(SOFT_SCORE_COMPONENT_NAMES)
    if unknown_minimum_components:
        errors.append(
            f"critical_minimums contiene component_name desconocidos: {sorted(unknown_minimum_components)}"
        )

    unknown_weight_components = set(manifest.soft_score_weights) - set(SOFT_SCORE_COMPONENT_NAMES)
    if unknown_weight_components:
        errors.append(
            f"soft_score_weights contiene component_name desconocidos: {sorted(unknown_weight_components)}"
        )

    unknown_hard_rule_parameters = set(manifest.hard_rule_parameters) - KNOWN_HARD_RULE_PARAMETER_KEYS
    if unknown_hard_rule_parameters:
        errors.append(
            f"hard_rule_parameters contiene claves desconocidas: {sorted(unknown_hard_rule_parameters)}"
        )

    # --- Range validation (valores, no solo claves) ---
    for component_name, minimum in manifest.critical_minimums.items():
        if not (0.0 <= minimum <= 100.0):
            errors.append(f"critical_minimums[{component_name!r}]={minimum} fuera de [0,100]")

    for component_name, weight in manifest.soft_score_weights.items():
        if weight < 0:
            errors.append(f"soft_score_weights[{component_name!r}]={weight} no puede ser negativo")

    if manifest.soft_score_weights and sum(manifest.soft_score_weights.values()) <= 0:
        errors.append("la suma de soft_score_weights debe ser > 0 cuando el diccionario no está vacío")

    for key, value in manifest.hard_rule_parameters.items():
        if value < 0:
            errors.append(f"hard_rule_parameters[{key!r}]={value} no puede ser negativo")

    if errors:
        raise ValueError("PolicyManifest inválido: " + "; ".join(errors))
