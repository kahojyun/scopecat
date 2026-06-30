from __future__ import annotations

import ast
from pathlib import Path

import scopecat as sc
import scopecat.experiments as experiments


def test_experiment_kernel_uses_results_facade_for_result_contracts() -> None:
    source_paths = [
        Path(experiments.__file__),
        Path(experiments.__file__).with_name("_planning_acquisition.py"),
    ]
    imported_modules = set[str]()
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text())
        imported_modules.update(
            imported for node in ast.walk(tree) for imported in _imported_modules(node)
        )

    assert "scopecat.results" in imported_modules
    assert "scopecat.models.measurement" not in imported_modules


def test_core_modules_do_not_import_example_or_spike_packages() -> None:
    source_root = Path(sc.__file__).parent
    forbidden_prefixes = (
        "examples",
        "lab_system",
        "quantum_lab_demo",
        "scopecat_spike",
    )

    offenders: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        imported_modules = {
            imported for node in ast.walk(tree) for imported in _imported_modules(node)
        }
        forbidden_imports = sorted(
            imported
            for imported in imported_modules
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        )
        if forbidden_imports:
            offenders[str(path.relative_to(source_root))] = forbidden_imports

    assert not offenders


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
