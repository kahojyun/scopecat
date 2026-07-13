"""Application composition roots."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scopecat.composition.local import (
        local_config_registry_unit_of_work,
        local_execution_services,
        local_run_repository,
        local_workspace_services,
        open_local_workspace,
    )
    from scopecat.composition.memory import memory_workspace_services


_EXPORTS: dict[str, tuple[str, str]] = {
    "local_config_registry_unit_of_work": (
        "scopecat.composition.local",
        "local_config_registry_unit_of_work",
    ),
    "local_execution_services": (
        "scopecat.composition.local",
        "local_execution_services",
    ),
    "local_run_repository": (
        "scopecat.composition.local",
        "local_run_repository",
    ),
    "local_workspace_services": (
        "scopecat.composition.local",
        "local_workspace_services",
    ),
    "memory_workspace_services": (
        "scopecat.composition.memory",
        "memory_workspace_services",
    ),
    "open_local_workspace": (
        "scopecat.composition.local",
        "open_local_workspace",
    ),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "local_config_registry_unit_of_work",
    "local_execution_services",
    "local_run_repository",
    "local_workspace_services",
    "memory_workspace_services",
    "open_local_workspace",
]
