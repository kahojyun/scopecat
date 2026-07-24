"""Project-scoped state for in-memory execution adapters."""

from __future__ import annotations

from threading import Lock, RLock

from scopecat.adapters.memory.config_registry import (
    MemoryConfigRegistryRepository,
    MemoryConfigRegistryUnitOfWork,
)
from scopecat.adapters.memory.execution import (
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryMeasurementDatasetRepository,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.adapters.memory.resources import MemoryResourceLeaseManager
from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    ExecutionTransition,
)


class _MemoryExecutionJournalStore:
    def __init__(self) -> None:
        self._journal = MemoryExecutionJournal()

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        return self._journal.append(entry)

    def entries(self) -> tuple[ExecutionTransition, ...]:
        return self._journal.entries


class _MemoryCollectionRecordRepository:
    def __init__(self) -> None:
        self._repository = MemoryCollectionRepository()

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        return self._repository.commit(chunk)

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        return self._repository.resolve(receipt)

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        return self._repository.receipts


class MemoryProjectExecutionState:
    """Own all execution state whose lifetime matches an in-memory project."""

    def __init__(self, runs: MemoryRunRepository) -> None:
        self._runs = runs
        self.resources = MemoryResourceLeaseManager()
        self._journals: dict[str, _MemoryExecutionJournalStore] = {}
        self._measurements: dict[str, MemoryMeasurementDatasetRepository] = {}
        self._collections: dict[str, _MemoryCollectionRecordRepository] = {}
        self._payloads: dict[str, MemoryPayloadEvidenceCommitter] = {}
        self._lock = Lock()

    def journal_for(self, run_id: str) -> _MemoryExecutionJournalStore:
        with self._lock:
            journal = self._journals.get(run_id)
            if journal is None:
                journal = _MemoryExecutionJournalStore()
                self._journals[run_id] = journal
            return journal

    def measurements_for(self, run_id: str) -> MemoryMeasurementDatasetRepository:
        with self._lock:
            measurements = self._measurements.get(run_id)
            if measurements is None:
                measurements = MemoryMeasurementDatasetRepository(
                    run_id=run_id,
                    run_repository=self._runs,
                )
                self._measurements[run_id] = measurements
            return measurements

    def collections_for(self, run_id: str) -> _MemoryCollectionRecordRepository:
        with self._lock:
            collections = self._collections.get(run_id)
            if collections is None:
                collections = _MemoryCollectionRecordRepository()
                self._collections[run_id] = collections
            return collections

    def payloads_for(self, run_id: str) -> MemoryPayloadEvidenceCommitter:
        with self._lock:
            payloads = self._payloads.get(run_id)
            if payloads is None:
                payloads = MemoryPayloadEvidenceCommitter()
                self._payloads[run_id] = payloads
            return payloads


class MemoryProjectStore:
    """Own every stateful adapter whose lifetime matches one project."""

    def __init__(self) -> None:
        self.runs = MemoryRunRepository()
        self.registry = MemoryConfigRegistryRepository()
        self.execution = MemoryProjectExecutionState(self.runs)
        self._lock = RLock()

    def unit_of_work(self) -> MemoryConfigRegistryUnitOfWork:
        return MemoryConfigRegistryUnitOfWork(
            registry=self.registry,
            runs=self.runs,
            lock=self._lock,
        )
