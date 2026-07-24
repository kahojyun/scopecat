from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.runs.repository import RunRepository
from tests.contracts.run_repository_contracts import RunRepositoryContract


class TestMemoryRunRepositoryContract(RunRepositoryContract):
    @override
    def make_repository(self, tmp_path: Path) -> RunRepository:
        del tmp_path
        return MemoryRunRepository()
