"""In-memory configuration registry and workspace unit of work."""

from __future__ import annotations

from threading import RLock
from types import TracebackType
from typing import Self

from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.config.registry.records import (
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryIndex,
)
from scopecat.records.config import ConfigProfileSnapshot

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_INDEX_REF = f"{CONFIG_REGISTRY_ROOT}/index.json"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"


class MemoryConfigRegistryRepository:
    """Serialized-value semantics without filesystem effects."""

    def __init__(self) -> None:
        self._index = ConfigRegistryIndex()
        self._entries: dict[str, ConfigRegistryEntry] = {}
        self._configs: dict[str, ConfigProfileSnapshot] = {}
        self._active: ConfigRegistryActiveState | None = None

    @property
    def index_ref(self) -> str:
        return CONFIG_REGISTRY_INDEX_REF

    @property
    def active_ref(self) -> str:
        return CONFIG_REGISTRY_ACTIVE_REF

    def entry_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/entries/{entry_id}.json"

    def config_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/configs/{entry_id}.config-profile-snapshot.json"

    def entry_exists(self, entry_id: str) -> bool:
        return entry_id in self._entries

    def read_index(self) -> ConfigRegistryIndex:
        return _copy_model(self._index)

    def read_entry(self, entry_id: str) -> ConfigRegistryEntry:
        return _copy_model(self._entries[entry_id])

    def read_config(self, ref: str) -> ConfigProfileSnapshot:
        return _copy_model(self._configs[ref])

    def read_active_state(self) -> ConfigRegistryActiveState | None:
        return None if self._active is None else _copy_model(self._active)

    def commit_registration(
        self,
        *,
        index: ConfigRegistryIndex,
        entry: ConfigRegistryEntry,
        config: ConfigProfileSnapshot,
    ) -> None:
        self._configs[entry.config_ref] = _copy_model(config)
        self._entries[entry.id] = _copy_model(entry)
        self._index = _index_with_entry(index, entry)

    def commit_active_state(self, state: ConfigRegistryActiveState) -> None:
        self._active = _copy_model(state)


class MemoryWorkspaceUnitOfWork:
    """Share one registry lock and one run repository across transactions."""

    def __init__(
        self,
        *,
        registry: MemoryConfigRegistryRepository,
        runs: MemoryRunRepository,
        lock: RLock,
    ) -> None:
        self.registry = registry
        self.runs = runs
        self._workspace_lock = lock
        self._entered = False

    def __enter__(self) -> Self:
        if self._entered:
            msg = "workspace unit of work cannot be entered twice"
            raise RuntimeError(msg)
        self._workspace_lock.acquire()
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if not self._entered:
            msg = "workspace unit of work was not entered"
            raise RuntimeError(msg)
        self._entered = False
        self._workspace_lock.release()


def _index_with_entry(
    index: ConfigRegistryIndex,
    entry: ConfigRegistryEntry,
) -> ConfigRegistryIndex:
    entries = [existing for existing in index.entries if existing.id != entry.id]
    entries.append(entry)
    return ConfigRegistryIndex(
        entries=tuple(sorted(entries, key=lambda item: item.registered_at))
    )


def _copy_model[
    TModel: ConfigRegistryIndex
    | ConfigRegistryEntry
    | ConfigRegistryActiveState
    | ConfigProfileSnapshot
](
    model: TModel,
) -> TModel:
    return type(model).model_validate(model.model_dump(mode="json"))


__all__ = [
    "MemoryConfigRegistryRepository",
    "MemoryWorkspaceUnitOfWork",
]
