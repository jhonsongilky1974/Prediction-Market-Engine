"""Aislamiento de Phase 6 -- Tramo 5B (Position Management Advisory):
`src.advisory` nunca importa `src.policy`/`src.orchestration` ni ningún
módulo deportivo (Market Analysis) -- Tramo 5B es puramente
`src.positions` + cómputo propio. Dirección inversa: `src.positions`
tampoco importa `src.advisory` (mismo patrón que
`test_positions_never_references_matching.py`, extendido)."""
from __future__ import annotations

import ast
import glob
import importlib
from pathlib import Path

import pytest

ADVISORY_MODULES = [
    "src.advisory.config",
    "src.advisory.enums",
    "src.advisory.event_identity",
    "src.advisory.exit_planning",
    "src.advisory.exposure",
    "src.advisory.invalidation",
    "src.advisory.order_conflicts",
    "src.advisory.position_advisory_engine",
    "src.advisory.schemas",
]

FORBIDDEN_MODULE_PREFIXES = (
    "src.policy",
    "src.orchestration",
    "src.matching",
    "src.payoff",
    "src.pricing",
    "src.pipelines",
    "src.connectors",
    "src.calibration",
    "src.evidence",
    "src.health",
    "src.explainability",
    "src.uncertainty",
    "src.features",
    "src.normalization",
    "src.quality",
    "src.evaluation",
)


def _imported_modules(module_name: str) -> set[str]:
    module = importlib.import_module(module_name)
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    return imported


@pytest.mark.parametrize("module_name", ADVISORY_MODULES)
def test_advisory_module_never_imports_policy_orchestration_or_sport_modules(module_name):
    imported = _imported_modules(module_name)
    for forbidden_prefix in FORBIDDEN_MODULE_PREFIXES:
        hits = {m for m in imported if m == forbidden_prefix or m.startswith(forbidden_prefix + ".")}
        assert not hits, f"{module_name} importa {hits}, prohibido en el alcance de Tramo 5B"


def test_positions_never_references_advisory():
    """Dirección inversa: src.positions nunca debe depender de
    src.advisory -- la capa contable de Position Management es más
    fundamental y no conoce la capa de asesoría construida encima."""
    positions_files = glob.glob("src/positions/**/*.py", recursive=True)
    for file_path in positions_files:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src.advisory"), (
                    f"{file_path} importa {node.module} -- src.positions nunca debe depender de src.advisory"
                )


def test_advisory_never_references_positions_write_paths():
    """`src.advisory` puede leer `src.positions` (contratos + lecturas de
    `PositionsRepository`), pero ninguno de sus módulos de dominio debe
    invocar los métodos de ESCRITURA del repositorio -- eso solo puede
    ocurrir en `src.api.advisory_service`, y allí NUNCA debe llamarlos
    (Tramo 5B es 100% de solo lectura, cero efectos financieros)."""
    forbidden_calls = {"create_position", "create_order", "apply_fill", "update_order_status", "save_position_plan"}
    advisory_files = glob.glob("src/advisory/**/*.py", recursive=True) + ["src/api/advisory_service.py", "src/api/advisory_router.py"]
    for file_path in advisory_files:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_calls:
                pytest.fail(f"{file_path} invoca {node.attr}() -- prohibido en Tramo 5B (solo lectura)")
