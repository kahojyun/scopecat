"""Public composition helpers that cannot write daemon-owned storage."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.composition.memory import memory_workspace_services


_EXPORTS: dict[str, tuple[str, str]] = {
    "memory_workspace_services": (
        "scopecat.composition.memory",
        "memory_workspace_services",
    ),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "memory_workspace_services",
]
