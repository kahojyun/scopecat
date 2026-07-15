"""Keep the laboratory reference adapter on the supported domain SDK surface."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_ROOT = Path(__file__).parents[2] / "src" / "quantum_lab_demo"
_FORBIDDEN_IMPORT_PREFIXES = (
    "scopecat.compiler",
    "scopecat.measurements.host_transforms",
    "scopecat.measurements.projection",
    "scopecat.measurements.transform_model",
    "scopecat.measurements.transform_verification",
    "scopecat.measurements.values",
    "scopecat.sdk.domain.invocation",
)
_FORBIDDEN_NAMES = {
    "context_adapter_id_internal",
    "context_linked_points_internal",
    "domain_receipt_identity",
    "linked_points_for_preparation_internal",
    "point_id",
    "product_def_for_preparation_internal",
    "product_use_id",
}
_FORBIDDEN_TYPE_PREFIXES = (
    "BoundDomain",
    "BoundHost",
    "ClosedDomain",
    "MaterializedLinked",
)


def test_laboratory_reference_sources_use_only_the_supported_domain_sdk() -> None:
    violations: list[str] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=path)
        relative = path.relative_to(_SOURCE_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(_FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{relative}:{node.lineno}: import {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(_FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(
                            f"{relative}:{node.lineno}: import {alias.name}"
                        )
            elif isinstance(node, ast.Attribute) and node.attr == "native_internal":
                violations.append(
                    f"{relative}:{node.lineno}: attribute native_internal"
                )
            elif isinstance(node, ast.Name):
                if node.id in _FORBIDDEN_NAMES or node.id.startswith(
                    _FORBIDDEN_TYPE_PREFIXES
                ):
                    violations.append(f"{relative}:{node.lineno}: name {node.id}")

    assert violations == []
