from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.filesystem.execution import (
    FilesystemExecutionJournal,
    FilesystemMeasurementRecordCommitter,
    FilesystemPayloadEvidenceCommitter,
)
from scopecat.adapters.memory import (
    MemoryExecutionJournal,
    MemoryMeasurementRecordCommitter,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.execution.ports.journal import (
    ExecutionJournal,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementRecordCommitter
from scopecat.records.execution_journal import ExecutionTransition
from tests.contracts.execution_port_contracts import (
    ExecutionJournalContract,
    MeasurementRecordCommitterContract,
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


class TestMemoryMeasurementRecordCommitterContract(MeasurementRecordCommitterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementRecordCommitter:
        del tmp_path, run_id
        return MemoryMeasurementRecordCommitter()


class TestFilesystemMeasurementRecordCommitterContract(
    MeasurementRecordCommitterContract
):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementRecordCommitter:
        return FilesystemMeasurementRecordCommitter(tmp_path, run_id=run_id)


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
