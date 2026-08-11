"""HTTP transport for a Scopecat project daemon.

The package facade stays cold so importing a CLI or worker submodule does not
also construct the complete FastAPI and daemon runtime dependency graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.daemon.health import DaemonHealth

    from .errors import BackendConflict, BackendNotFound
    from .http.transport import create_app
    from .runtime import LocalDaemonRuntime

_EXPORTS: dict[str, tuple[str, str]] = {
    "BackendConflict": ("scopecat_server.errors", "BackendConflict"),
    "BackendNotFound": ("scopecat_server.errors", "BackendNotFound"),
    "DaemonHealth": ("scopecat.daemon.health", "DaemonHealth"),
    "LocalDaemonRuntime": ("scopecat_server.runtime", "LocalDaemonRuntime"),
    "create_app": ("scopecat_server.http.transport", "create_app"),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


__all__ = [
    "BackendConflict",
    "BackendNotFound",
    "DaemonHealth",
    "LocalDaemonRuntime",
    "create_app",
]
