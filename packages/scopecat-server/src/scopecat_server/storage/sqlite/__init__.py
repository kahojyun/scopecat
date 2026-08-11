"""Lazy SQLite adapters for daemon-owned project state."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat_server.storage.sqlite.config_registry import (
        SQLiteConfigRegistryRepository,
        SQLiteConfigRegistryStore,
        SQLiteConfigRegistryUnitOfWork,
    )
    from scopecat_server.storage.sqlite.connection import SQLiteDatabase
    from scopecat_server.storage.sqlite.control_plane import (
        ControlPlaneConflict,
        ControlPlaneNotFound,
        ExecutorLeaseNotHeld,
        InstrumentSessionNotActive,
        SQLiteControlPlane,
    )
    from scopecat_server.storage.sqlite.execution import (
        SQLiteExecutionJournal,
        SQLiteMeasurementDatasetRepository,
    )
    from scopecat_server.storage.sqlite.object_store import (
        ImmutableObjectStore,
        StoredObject,
    )
    from scopecat_server.storage.sqlite.project_store import (
        ProjectStoreError,
        SchemaVersionError,
        SQLiteProjectStore,
    )
    from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

_CONFIG_REGISTRY_EXPORTS = (
    "SQLiteConfigRegistryRepository",
    "SQLiteConfigRegistryStore",
    "SQLiteConfigRegistryUnitOfWork",
)
_CONTROL_PLANE_EXPORTS = (
    "ControlPlaneConflict",
    "ControlPlaneNotFound",
    "ExecutorLeaseNotHeld",
    "InstrumentSessionNotActive",
    "SQLiteControlPlane",
)
_EXECUTION_EXPORTS = (
    "SQLiteExecutionJournal",
    "SQLiteMeasurementDatasetRepository",
)
_OBJECT_STORE_EXPORTS = (
    "ImmutableObjectStore",
    "StoredObject",
)
_PROJECT_STORE_EXPORTS = (
    "ProjectStoreError",
    "SchemaVersionError",
    "SQLiteProjectStore",
)
_EXPORTS = {
    **{
        name: ("scopecat_server.storage.sqlite.config_registry", name)
        for name in _CONFIG_REGISTRY_EXPORTS
    },
    **{
        name: ("scopecat_server.storage.sqlite.control_plane", name)
        for name in _CONTROL_PLANE_EXPORTS
    },
    **{
        name: ("scopecat_server.storage.sqlite.execution", name)
        for name in _EXECUTION_EXPORTS
    },
    **{
        name: ("scopecat_server.storage.sqlite.object_store", name)
        for name in _OBJECT_STORE_EXPORTS
    },
    **{
        name: ("scopecat_server.storage.sqlite.project_store", name)
        for name in _PROJECT_STORE_EXPORTS
    },
    "SQLiteDatabase": (
        "scopecat_server.storage.sqlite.connection",
        "SQLiteDatabase",
    ),
    "SQLiteRunRepository": (
        "scopecat_server.storage.sqlite.run_repository",
        "SQLiteRunRepository",
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
    "ControlPlaneConflict",
    "ControlPlaneNotFound",
    "ExecutorLeaseNotHeld",
    "ImmutableObjectStore",
    "InstrumentSessionNotActive",
    "ProjectStoreError",
    "SQLiteConfigRegistryRepository",
    "SQLiteConfigRegistryStore",
    "SQLiteConfigRegistryUnitOfWork",
    "SQLiteControlPlane",
    "SQLiteDatabase",
    "SQLiteExecutionJournal",
    "SQLiteMeasurementDatasetRepository",
    "SQLiteProjectStore",
    "SQLiteRunRepository",
    "SchemaVersionError",
    "StoredObject",
]
