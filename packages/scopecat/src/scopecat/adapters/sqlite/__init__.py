"""SQLite adapters for daemon-owned project state."""

from scopecat.adapters.sqlite.config_registry import (
    SQLiteConfigRegistryRepository,
    SQLiteConfigRegistryStore,
    SQLiteConfigRegistryUnitOfWork,
)
from scopecat.adapters.sqlite.connection import SQLiteDatabase
from scopecat.adapters.sqlite.control_plane import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    InstrumentSessionNotActive,
    SQLiteControlPlane,
)
from scopecat.adapters.sqlite.execution import (
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
)
from scopecat.adapters.sqlite.object_store import (
    ImmutableObjectStore,
    StoredObject,
)
from scopecat.adapters.sqlite.project_store import (
    ProjectStoreError,
    SchemaVersionError,
    SQLiteProjectStore,
)
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository

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
