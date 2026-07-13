from __future__ import annotations

import ast
from pathlib import Path

import scopecat_quantum as sq


def test_public_surface_disambiguates_circuit_and_pulse_composition() -> None:
    assert sq.CircuitSequence is sq.circuits.Sequence
    assert sq.CircuitParallel is sq.circuits.Parallel
    assert sq.PulseSequence is sq.pulses.Sequence
    assert sq.PulseParallel is sq.pulses.Parallel


def test_public_facade_covers_module_exports_except_disambiguated_composition() -> None:
    facade_names = set(sq.__all__)

    assert set(sq.acquisitions.__all__) <= facade_names
    assert set(sq.calibrations.__all__) <= facade_names
    assert set(sq.circuits.__all__) - {"Parallel", "Sequence"} <= facade_names
    assert set(sq.pulses.__all__) - {"Parallel", "Sequence"} <= facade_names
    assert set(sq.circuit_pulses.__all__) <= facade_names
    assert set(sq.circuit_results.__all__) <= facade_names
    assert set(sq.circuit_targets.__all__) <= facade_names
    assert set(sq.gates.__all__) <= facade_names
    assert set(sq.measurement_calibrations.__all__) <= facade_names
    assert set(sq.targets.__all__) <= facade_names


def test_public_surface_contains_no_concrete_laboratory_target() -> None:
    names = set(sq.__all__)

    assert not {name for name in names if "awg" in name.lower()}
    assert not {name for name in names if "digitizer" in name.lower()}
    assert not {name for name in names if "channel" in name.lower()}
    assert not {name for name in names if "trigger" in name.lower()}


def test_public_surface_exports_only_real_unique_attributes() -> None:
    assert len(sq.__all__) == len(set(sq.__all__))
    assert all(hasattr(sq, name) for name in sq.__all__)


def test_quantum_source_never_imports_core_private_modules() -> None:
    source_root = Path(__file__).parents[1] / "src" / "scopecat_quantum"
    violations: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path.name}:{node.lineno}:{alias.name}"
                    for alias in node.names
                    if alias.name.startswith("scopecat._")
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("scopecat._"):
                    violations.append(f"{path.name}:{node.lineno}:{module}")
                elif module == "scopecat":
                    violations.extend(
                        f"{path.name}:{node.lineno}:scopecat.{alias.name}"
                        for alias in node.names
                        if alias.name.startswith("_")
                    )
    assert violations == []
