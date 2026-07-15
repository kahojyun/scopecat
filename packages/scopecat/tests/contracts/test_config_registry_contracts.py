from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.memory.workspace import MemoryWorkspaceStore
from scopecat.composition.local import local_config_registry_unit_of_work
from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from tests.contracts.config_registry_contracts import (
    ConfigRegistryUnitOfWorkContract,
)


class TestMemoryConfigRegistryUnitOfWorkContract(ConfigRegistryUnitOfWorkContract):
    @override
    def make_unit_of_work(self, tmp_path: Path) -> WorkspaceUnitOfWorkFactory:
        del tmp_path
        return MemoryWorkspaceStore().unit_of_work


class TestFilesystemConfigRegistryUnitOfWorkContract(ConfigRegistryUnitOfWorkContract):
    @override
    def make_unit_of_work(self, tmp_path: Path) -> WorkspaceUnitOfWorkFactory:
        return local_config_registry_unit_of_work(tmp_path)
