from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager

import scopecat.project as project_loading


@contextmanager
def isolated_project_application_imports() -> Generator[None]:
    """Restore process-scoped project imports around loader-focused tests."""

    original_path = sys.path.copy()
    _clear_project_application_imports()
    try:
        yield
    finally:
        _clear_project_application_imports()
        sys.path[:] = original_path


def _clear_project_application_imports() -> None:
    with project_loading._application_import_lock:
        root = project_loading._loaded_application_project_root
        if root is not None:
            for module_name, module in tuple(sys.modules.items()):
                if project_loading._module_belongs_to_project(module, root):
                    sys.modules.pop(module_name, None)
        project_loading._loaded_application_project_root = None
