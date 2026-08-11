"""SQLite adapters for daemon-owned project state."""

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
