"""SQLite adapters for daemon-owned workspace state."""

from scopecat.adapters.sqlite.config_registry import (
    SQLiteConfigRegistryRepository,
    SQLiteConfigRegistryStore,
    SQLiteWorkspaceUnitOfWork,
)
from scopecat.adapters.sqlite.control_plane import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    SchemaVersionError,
    SQLiteControlPlane,
)
from scopecat.adapters.sqlite.execution import (
    SQLiteCollectionRecordRepository,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    bootstrap_execution_schema,
)
from scopecat.adapters.sqlite.object_store import (
    ImmutableObjectStore,
    StoredObject,
)
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository

__all__ = [
    "ControlPlaneConflict",
    "ControlPlaneNotFound",
    "ExecutorLeaseNotHeld",
    "ImmutableObjectStore",
    "SQLiteCollectionRecordRepository",
    "SQLiteConfigRegistryRepository",
    "SQLiteConfigRegistryStore",
    "SQLiteControlPlane",
    "SQLiteExecutionJournal",
    "SQLiteMeasurementDatasetRepository",
    "SQLitePayloadEvidenceCommitter",
    "SQLiteRunRepository",
    "SQLiteWorkspaceUnitOfWork",
    "SchemaVersionError",
    "StoredObject",
    "bootstrap_execution_schema",
]
