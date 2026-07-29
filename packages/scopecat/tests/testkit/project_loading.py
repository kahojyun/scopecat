from __future__ import annotations

import sys
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import scopecat.project as project_loading


@contextmanager
def isolated_project_imports(
    *,
    clear_roots: Iterable[Path] = (),
) -> Generator[None]:
    """Restore process-scoped project imports around loader-focused tests."""

    selected_roots = tuple(root.resolve() for root in clear_roots)
    displaced = _remove_modules_from(selected_roots)
    original_path = sys.path.copy()
    _clear_project_imports()
    try:
        yield
    finally:
        _clear_project_imports()
        _remove_modules_from(selected_roots)
        sys.modules.update(displaced)
        sys.path[:] = original_path


def _clear_project_imports() -> None:
    with project_loading._project_import_lock:
        root = project_loading._loaded_project_code_root
        if root is not None:
            for module_name, module in tuple(sys.modules.items()):
                if project_loading._module_belongs_to_project(module, root):
                    sys.modules.pop(module_name, None)
        project_loading._loaded_project_code_root = None


def _remove_modules_from(roots: tuple[Path, ...]) -> dict[str, ModuleType]:
    removed: dict[str, ModuleType] = {}
    for module_name, module in tuple(sys.modules.items()):
        if any(
            project_loading._module_belongs_to_project(module, root) for root in roots
        ):
            removed[module_name] = module
            sys.modules.pop(module_name, None)
    return removed
