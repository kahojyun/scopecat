from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.memory.resources import MemoryResourceLeaseManager
from scopecat.execution.ports.resources import ResourceLeaseManager
from tests.contracts.resource_lease_contracts import ResourceLeaseManagerContract


class TestMemoryResourceLeaseManagerContract(ResourceLeaseManagerContract):
    @override
    def make_manager(self, tmp_path: Path) -> ResourceLeaseManager:
        del tmp_path
        return MemoryResourceLeaseManager()
