"""Aislamiento de Phase 6 (Position Management) respecto de matching/
pipelines de MLB y tenis -- mismo patrón que
`test_opportunity_repository.py::test_does_not_import_repository_or_history_repository`
y `test_tennis_pair_matcher.py::test_mlb_pipeline_never_references_tennis_pair_matcher`.

`src.positions` consume `Opportunity`/`Side`/`Sport` (contratos de datos
ya existentes) pero nunca participa en el pipeline de matching ni en la
lógica de pricing/payoff -- ver alcance autorizado ("no tocar lógica MLB
ni tenis salvo imports estrictamente necesarios y sin cambiar
comportamiento")."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

POSITIONS_MODULES = [
    "src.positions.money",
    "src.positions.enums",
    "src.positions.exceptions",
    "src.positions.schemas",
    "src.positions.state_machine",
    "src.positions.capital_recovery",
    "src.positions.positions_repository",
]

FORBIDDEN_MODULE_PREFIXES = (
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

FORBIDDEN_REPOSITORY_MODULES = {
    "src.storage.repository",
    "src.storage.history_repository",
    "src.opportunity.opportunity_repository",
}


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


@pytest.mark.parametrize("module_name", POSITIONS_MODULES)
def test_positions_module_never_imports_matching_payoff_or_pricing(module_name):
    imported = _imported_modules(module_name)
    for forbidden_prefix in FORBIDDEN_MODULE_PREFIXES:
        hits = {m for m in imported if m == forbidden_prefix or m.startswith(forbidden_prefix + ".")}
        assert not hits, f"{module_name} importa {hits}, prohibido por aislamiento de Phase 6"


@pytest.mark.parametrize("module_name", POSITIONS_MODULES)
def test_positions_module_never_wraps_existing_repositories(module_name):
    """positions_repository.py es un componente HERMANO de Repository/
    HistoryRepository/OpportunityRepository, no un wrapper -- mismo
    principio que ya se exige a OpportunityRepository."""
    imported = _imported_modules(module_name)
    hits = imported & FORBIDDEN_REPOSITORY_MODULES
    assert not hits, f"{module_name} importa {hits} -- debe ser un componente hermano, no un wrapper"


def test_matching_pipelines_never_reference_positions_module():
    """Dirección inversa: el pipeline de matching/tenis/MLB tampoco debe
    depender de src.positions (evita acoplamiento accidental en ambos
    sentidos)."""
    import glob

    matching_files = glob.glob("src/matching/**/*.py", recursive=True) + glob.glob(
        "src/pipelines/**/*.py", recursive=True
    )
    for file_path in matching_files:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src.positions"), (
                    f"{file_path} importa {node.module} -- src.matching/src.pipelines nunca "
                    "deben depender de src.positions"
                )
