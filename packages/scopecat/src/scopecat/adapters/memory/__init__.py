"""Deterministic in-memory adapters for embedded execution and tests."""

from scopecat.adapters.memory.config_registry import (
    MemoryConfigRegistryRepository,
    MemoryWorkspaceUnitOfWork,
)
from scopecat.adapters.memory.execution import (
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryMeasurementDatasetRepository,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.adapters.memory.resources import MemoryResourceLeaseManager
from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.adapters.memory.workspace import MemoryWorkspaceStore

__all__ = [
    "MemoryCollectionRepository",
    "MemoryConfigRegistryRepository",
    "MemoryExecutionJournal",
    "MemoryMeasurementDatasetRepository",
    "MemoryPayloadEvidenceCommitter",
    "MemoryResourceLeaseManager",
    "MemoryRunRepository",
    "MemoryWorkspaceStore",
    "MemoryWorkspaceUnitOfWork",
]
