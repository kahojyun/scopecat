"""Leaf persistence ports for the workspace configuration registry."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from scopecat.config.registry.records import (
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryIndex,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.repository import RunRepository


class ConfigRegistryRepository(Protocol):
    """Persistence boundary for registry records and commit markers."""

    @property
    def index_ref(self) -> str: ...

    @property
    def active_ref(self) -> str: ...

    def entry_ref(self, entry_id: str) -> str: ...

    def config_ref(self, entry_id: str) -> str: ...

    def entry_exists(self, entry_id: str) -> bool: ...

    def read_index(self) -> ConfigRegistryIndex: ...

    def read_entry(self, entry_id: str) -> ConfigRegistryEntry: ...

    def read_config(self, ref: str) -> ConfigProfileSnapshot: ...

    def read_active_state(self) -> ConfigRegistryActiveState | None: ...

    def commit_registration(
        self,
        *,
        index: ConfigRegistryIndex,
        entry: ConfigRegistryEntry,
        config: ConfigProfileSnapshot,
    ) -> None: ...

    def commit_active_state(self, state: ConfigRegistryActiveState) -> None: ...


class WorkspaceUnitOfWork(Protocol):
    """One configuration-registry transaction with run evidence access."""

    @property
    def registry(self) -> ConfigRegistryRepository: ...

    @property
    def runs(self) -> RunRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


type WorkspaceUnitOfWorkFactory = Callable[[], WorkspaceUnitOfWork]
