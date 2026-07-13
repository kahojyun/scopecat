from __future__ import annotations

from pathlib import Path

from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.runs.repository import RunRepository
from tests.contracts.run_repository_contracts import RunRepositoryContract


class TestMemoryRunRepositoryContract(RunRepositoryContract):
    def make_repository(self, tmp_path: Path) -> RunRepository:
        del tmp_path
        return MemoryRunRepository()


class TestFilesystemRunRepositoryContract(RunRepositoryContract):
    def make_repository(self, tmp_path: Path) -> RunRepository:
        return FilesystemRunRepository(tmp_path)
