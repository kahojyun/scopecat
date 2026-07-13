from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

from tests.testkit.paths import REPO_ROOT

CORE_SOURCE = REPO_ROOT / "packages" / "scopecat" / "src" / "scopecat"
CORE_TESTS = REPO_ROOT / "packages" / "scopecat" / "tests"
FILESYSTEM_ADAPTER_ROOTS = (CORE_SOURCE / "adapters" / "filesystem",)
CONCRETE_FILESYSTEM_MODULES = ("scopecat.adapters.filesystem",)
NOTEBOOK_FACADE_PATHS = (
    CORE_SOURCE / "api" / "analysis.py",
    CORE_SOURCE / "api" / "run.py",
    CORE_SOURCE / "api" / "workspace.py",
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
        "run_comparison",
        "run_overview",
        "runs",
    )
)
REPOSITORY_WRITE_METHODS = {
    "write_bytes",
    "write_json",
    "write_jsonl",
    "write_manifest",
    "write_model",
    "write_text",
}


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
    if path.is_relative_to(CORE_TESTS):
        relative = path.relative_to(CORE_TESTS)
        return ".".join(("tests", *relative.parts[:-1]))
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


def test_core_remains_domain_neutral() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE,),
        forbidden=("scopecat_quantum", "quantum_lab_demo"),
    )


def test_extension_production_code_uses_only_public_scopecat_modules() -> None:
    _assert_no_forbidden_imports(
        (
            REPO_ROOT / "packages" / "scopecat-quantum" / "src",
            REPO_ROOT / "examples" / "quantum" / "support" / "src",
        ),
        forbidden=("scopecat._*",),
    )


def test_test_modules_share_helpers_through_testkit() -> None:
    violations = [
        edge
        for edge in _imports(CORE_TESTS)
        if edge.path.name.startswith("test_")
        and edge.module.startswith("tests.")
        and any(part.startswith("test_") for part in edge.module.split("."))
    ]
    assert not violations, (
        "test modules must not import other test modules; move shared helpers to "
        "tests.testkit:\n" + "\n".join(edge.display() for edge in violations)
    )


def test_inward_layers_do_not_depend_on_application_or_storage() -> None:
    application_and_storage = (
        "scopecat._storage",
        "scopecat._workflows",
        "scopecat.adapters",
        "scopecat.composition",
        "scopecat.config.registry",
        "scopecat.execution",
        "scopecat.runs",
        "scopecat.api.workspace",
        "scopecat.api.analysis",
        "scopecat.api.comparison",
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


def test_relations_do_not_depend_on_semantic_ir() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "compiler" / "relations",),
        forbidden=("scopecat.compiler.semantic",),
    )


def test_compiler_sublayers_remain_inward_only() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "compiler" / "typed",),
        forbidden=(
            "scopecat.compiler.frontend",
            "scopecat.compiler.linking",
        ),
    )
    _assert_no_forbidden_imports(
        (
            CORE_SOURCE / "compiler" / "relations",
            CORE_SOURCE / "compiler" / "semantic",
        ),
        forbidden=(
            "scopecat.compiler.frontend",
            "scopecat.compiler.typed",
            "scopecat.compiler.linking",
        ),
    )


def test_filesystem_adapter_does_not_depend_on_workflows_or_facades() -> None:
    _assert_no_forbidden_imports(
        FILESYSTEM_ADAPTER_ROOTS,
        forbidden=(
            "scopecat._workflows",
            "scopecat.authoring",
            "scopecat.composition",
            "scopecat.config.resolution",
            "scopecat.planning.backend",
            "scopecat.api.workspace",
            "scopecat.api.analysis",
            "scopecat.api.comparison",
            "scopecat.api.data",
            "scopecat.api.run",
        ),
    )


def test_application_layers_do_not_select_concrete_adapters() -> None:
    _assert_no_forbidden_imports(
        APPLICATION_ROOTS,
        forbidden=("scopecat.adapters", "scopecat.composition"),
    )


def test_planning_does_not_depend_on_workspace_application_bundle() -> None:
    _assert_no_forbidden_imports(
        (CORE_SOURCE / "planning",),
        forbidden=("scopecat.application",),
    )


def test_filesystem_adapter_is_only_imported_by_its_composition_root() -> None:
    composition_roots = {"composition/local.py"}
    actual_importers = {
        edge.path.relative_to(CORE_SOURCE).as_posix()
        for edge in _imports(CORE_SOURCE)
        if any(_matches(edge.module, module) for module in CONCRETE_FILESYSTEM_MODULES)
        and not any(
            edge.path.is_relative_to(adapter_root)
            for adapter_root in FILESYSTEM_ADAPTER_ROOTS
        )
    }

    unexpected = actual_importers - composition_roots
    assert not unexpected, (
        "filesystem adapter imports outside composition are forbidden: "
        + ", ".join(sorted(unexpected))
    )


def test_notebook_facades_delegate_persistence_use_cases() -> None:
    _assert_no_forbidden_imports(
        NOTEBOOK_FACADE_PATHS,
        forbidden=(
            "scopecat.adapters",
            "scopecat.composition",
            "scopecat.runs.access",
            "scopecat.runs.manifest",
            "scopecat.runs.repository",
        ),
    )

    violations: list[str] = []
    for path in NOTEBOOK_FACADE_PATHS:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in REPOSITORY_WRITE_METHODS
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} -> "
                    f".{node.func.attr}()"
                )
    assert not violations, "\n".join(violations)
