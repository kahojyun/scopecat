from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

from tests.testkit.paths import REPO_ROOT

CORE_SOURCE = REPO_ROOT / "packages" / "scopecat" / "src" / "scopecat"
NOTEBOOK_FACADE_PATHS = (
    CORE_SOURCE / "api" / "analysis.py",
    CORE_SOURCE / "api" / "run.py",
    CORE_SOURCE / "api" / "lab.py",
)
APPLICATION_ROOTS = tuple(
    CORE_SOURCE / name
    for name in (
        "api",
        "application",
        "analysis",
        "config",
        "execution",
        "measurements",
        "planning",
        "runs",
    )
)


@dataclass(frozen=True)
class ImportEdge:
    path: Path
    line: int
    module: str

    def display(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT)}:{self.line} -> {self.module}"


def _imports(root: Path) -> tuple[ImportEdge, ...]:
    edges: list[ImportEdge] = []
    paths = (root,) if root.is_file() else tuple(sorted(root.rglob("*.py")))
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                edges.extend(
                    ImportEdge(path=path, line=node.lineno, module=alias.name)
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                edges.extend(
                    ImportEdge(path=path, line=node.lineno, module=module)
                    for module in _from_import_modules(path, node)
                )
    return tuple(edges)


def _from_import_modules(path: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    module = node.module
    if node.level:
        package = _source_package(path)
        if package is None:
            return ()
        module = resolve_name(f"{'.' * node.level}{module or ''}", package)
    if module is None:
        return ()

    imported = {module}
    imported.update(
        f"{module}.{alias.name}" for alias in node.names if alias.name != "*"
    )
    return tuple(sorted(imported))


def _source_package(path: Path) -> str | None:
    try:
        source_index = max(
            index for index, component in enumerate(path.parts) if component == "src"
        )
    except ValueError:
        return None
    package = ".".join(path.parts[source_index + 1 : -1])
    return package or None


def _matches(module: str, prefix: str) -> bool:
    if prefix.endswith("*"):
        return module.startswith(prefix.removesuffix("*"))
    return module == prefix or module.startswith(prefix + ".")


def _assert_no_forbidden_imports(
    roots: tuple[Path, ...],
    *,
    forbidden: tuple[str, ...],
) -> None:
    violations = [
        edge
        for root in roots
        for edge in _imports(root)
        if any(_matches(edge.module, prefix) for prefix in forbidden)
    ]
    assert not violations, "\n".join(edge.display() for edge in violations)


def test_core_remains_domain_neutral_and_offline() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE,),
        forbidden=(
            "labrad",
            "numpy",
            "pandas",
            "pyvisa",
            "quantum_lab_demo",
            "requests",
            "scipy",
            "scopecat_quantum",
            "serial",
        ),
    )


def test_extension_production_code_uses_only_public_scopecat_modules() -> None:
    _assert_no_forbidden_imports(
        (
            REPO_ROOT / "packages" / "scopecat-quantum" / "src",
            REPO_ROOT / "examples" / "quantum" / "support" / "src",
        ),
        forbidden=("scopecat._*",),
    )


def test_inward_layers_do_not_depend_on_application_or_storage() -> None:
    application_and_storage = (
        "scopecat.adapters",
        "scopecat.config.registry",
        "scopecat.execution",
        "scopecat.runs",
        "scopecat.api.lab",
        "scopecat.api.analysis",
        "scopecat.api.data",
        "scopecat.api.run",
    )
    _assert_no_forbidden_imports(
        (
            CORE_SOURCE / "kernel",
            CORE_SOURCE / "records",
            CORE_SOURCE / "compiler",
        ),
        forbidden=application_and_storage,
    )


def test_records_do_not_depend_on_sdk_contracts() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "records",),
        forbidden=("scopecat.sdk",),
    )


def test_authoring_does_not_depend_on_later_compiler_or_planning_layers() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "authoring",),
        forbidden=(
            "scopecat.compiler.frontend",
            "scopecat.compiler.linking",
            "scopecat.compiler.typed",
            "scopecat.planning",
        ),
    )


def test_application_layers_do_not_select_concrete_adapters() -> None:
    _assert_no_forbidden_imports(
        APPLICATION_ROOTS,
        forbidden=("scopecat.adapters",),
    )


def test_planning_does_not_depend_on_project_application_bundle() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "planning",),
        forbidden=("scopecat.application",),
    )


def test_notebook_facades_delegate_persistence_use_cases() -> None:
    _assert_no_forbidden_imports(
        NOTEBOOK_FACADE_PATHS,
        forbidden=(
            "scopecat.adapters",
            "scopecat.runs.access",
            "scopecat.runs.repository",
        ),
    )
