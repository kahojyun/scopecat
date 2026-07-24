"""HTTP transport for a Scopecat project daemon."""

from scopecat.daemon.views import DaemonHealth

from .backend import SQLiteDaemonBackend
from .errors import BackendConflict, BackendNotFound
from .runtime import LocalDaemonRuntime
from .transport import (
    DaemonBackend,
    create_app,
)

__all__ = [
    "BackendConflict",
    "BackendNotFound",
    "DaemonBackend",
    "DaemonHealth",
    "LocalDaemonRuntime",
    "SQLiteDaemonBackend",
    "create_app",
]
