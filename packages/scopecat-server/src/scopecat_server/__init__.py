"""HTTP transport for a Scopecat workspace daemon."""

from scopecat.daemon.views import DaemonHealth

from .backend import SQLiteDaemonBackend
from .errors import BackendConflict, BackendNotFound
from .project import (
    LabProject,
    ProjectManifestError,
    discover_lab_project,
    load_lab_project,
)
from .runtime import LabApplicationFactory, LocalDaemonRuntime
from .transport import (
    DaemonBackend,
    create_app,
)

__all__ = [
    "BackendConflict",
    "BackendNotFound",
    "DaemonBackend",
    "DaemonHealth",
    "LabApplicationFactory",
    "LabProject",
    "LocalDaemonRuntime",
    "ProjectManifestError",
    "SQLiteDaemonBackend",
    "create_app",
    "discover_lab_project",
    "load_lab_project",
]
