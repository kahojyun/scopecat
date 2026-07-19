from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.filesystem.execution import (
    FilesystemExecutionJournal,
    FilesystemMeasurementDatasetRepository,
    FilesystemPayloadEvidenceCommitter,
)
from scopecat.adapters.memory import (
    MemoryExecutionJournal,
    MemoryMeasurementDatasetRepository,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.execution.ports.journal import (
    ExecutionJournal,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.records.execution_journal import ExecutionTransition
from tests.contracts.execution_port_contracts import (
    ExecutionJournalContract,
    MeasurementDatasetWriterContract,
    PayloadEvidenceCommitterContract,
)


class TestMemoryExecutionJournalContract(ExecutionJournalContract):
    @override
    def make_journal(self, tmp_path: Path, *, run_id: str) -> ExecutionJournal:
        del tmp_path, run_id
        return MemoryExecutionJournal()

    @override
    def read_entries(
        self,
        journal: ExecutionJournal,
    ) -> tuple[ExecutionTransition, ...]:
        assert isinstance(journal, MemoryExecutionJournal)
        return journal.entries


class TestFilesystemExecutionJournalContract(ExecutionJournalContract):
    @override
    def make_journal(self, tmp_path: Path, *, run_id: str) -> ExecutionJournal:
        return FilesystemExecutionJournal(tmp_path, run_id=run_id)

    @override
    def read_entries(
        self,
        journal: ExecutionJournal,
    ) -> tuple[ExecutionTransition, ...]:
        assert isinstance(journal, FilesystemExecutionJournal)
        return journal.entries()


class TestMemoryMeasurementDatasetRepositoryContract(MeasurementDatasetWriterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementDatasetWriter:
        del tmp_path, run_id
        return MemoryMeasurementDatasetRepository()


class TestFilesystemMeasurementDatasetRepositoryContract(
    MeasurementDatasetWriterContract
):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementDatasetWriter:
        return FilesystemMeasurementDatasetRepository(tmp_path, run_id=run_id)


class TestMemoryPayloadEvidenceCommitterContract(PayloadEvidenceCommitterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> PayloadEvidenceCommitter:
        del tmp_path, run_id
        return MemoryPayloadEvidenceCommitter()


class TestFilesystemPayloadEvidenceCommitterContract(PayloadEvidenceCommitterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> PayloadEvidenceCommitter:
        return FilesystemPayloadEvidenceCommitter(tmp_path, run_id=run_id)
