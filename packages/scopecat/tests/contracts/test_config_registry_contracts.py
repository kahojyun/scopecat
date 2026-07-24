from __future__ import annotations

from pathlib import Path
from typing import override

from scopecat.adapters.memory.project import MemoryProjectStore
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.testing import sqlite_config_registry_unit_of_work
from tests.contracts.config_registry_contracts import (
    ConfigRegistryUnitOfWorkContract,
)


class TestMemoryConfigRegistryUnitOfWorkContract(ConfigRegistryUnitOfWorkContract):
    @override
    def make_unit_of_work(self, tmp_path: Path) -> ConfigRegistryUnitOfWorkFactory:
        del tmp_path
        return MemoryProjectStore().unit_of_work


class TestSQLiteConfigRegistryUnitOfWorkContract(ConfigRegistryUnitOfWorkContract):
    @override
    def make_unit_of_work(self, tmp_path: Path) -> ConfigRegistryUnitOfWorkFactory:
        return sqlite_config_registry_unit_of_work(tmp_path)
