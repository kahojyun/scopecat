"""In-memory configuration registry and workspace unit of work."""

from __future__ import annotations

from threading import RLock
from types import TracebackType
from typing import Self

from scopecat.adapters.memory.run_repository import MemoryRunRepository
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.kernel.errors import Conflict
from scopecat.kernel.problems import (
    ModelLocation,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.records.config import ConfigProfileSnapshot

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"


class MemoryConfigRegistryRepository:
    """Serialized-value semantics without filesystem effects."""

    def __init__(self) -> None:
        self._entries: dict[str, ConfigRegistryEntry] = {}
        self._configs: dict[str, ConfigProfileSnapshot] = {}
        self._active_entry_id: str | None = None
        self._activations: list[ConfigRegistryActivationRecord] = []

    @property
    def active_ref(self) -> str:
        return CONFIG_REGISTRY_ACTIVE_REF

    def entry_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/entries/{entry_id}.json"

    def config_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/configs/{entry_id}.config-profile-snapshot.json"

    def entry_exists(self, entry_id: str) -> bool:
        return entry_id in self._entries

    def list_entries(self) -> tuple[ConfigRegistryEntry, ...]:
        return tuple(
            _copy_model(entry)
            for entry in sorted(
                self._entries.values(),
                key=lambda item: (item.registered_at, item.id),
            )
        )

    def read_entry(self, entry_id: str) -> ConfigRegistryEntry:
        return _copy_model(self._entries[entry_id])

    def read_config(self, ref: str) -> ConfigProfileSnapshot:
        return _copy_model(self._configs[ref])

    def read_active_state(self) -> ConfigRegistryActiveState | None:
        if self._active_entry_id is None:
            return None
        latest = self._activations[-1]
        return ConfigRegistryActiveState(
            generation=latest.generation,
            active_entry_id=self._active_entry_id,
            active_entry_content_hash=latest.entry_content_hash,
            history=tuple(_copy_model(record) for record in self._activations),
            updated_at=latest.recorded_at,
        )

    def commit_registration(
        self,
        *,
        entry: ConfigRegistryEntry,
        config: ConfigProfileSnapshot,
    ) -> None:
        self._configs[entry.config_ref] = _copy_model(config)
        self._entries[entry.id] = _copy_model(entry)

    def commit_activation(
        self,
        *,
        expected_generation: int,
        record: ConfigRegistryActivationRecord,
    ) -> None:
        current_generation = len(self._activations)
        if (
            current_generation != expected_generation
            or record.generation != expected_generation + 1
        ):
            raise _generation_conflict(
                expected=expected_generation,
                actual=current_generation,
            )
        self._activations.append(_copy_model(record))
        self._active_entry_id = record.entry_id


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


def _copy_model[
    TModel: ConfigRegistryEntry
    | ConfigRegistryActivationRecord
    | ConfigRegistryActiveState
    | ConfigProfileSnapshot
](
    model: TModel,
) -> TModel:
    return type(model).model_validate(model.model_dump(mode="json"))


def _generation_conflict(*, expected: int, actual: int) -> Conflict:
    return Conflict(
        [
            blocking_problem(
                "config_registry.conflict",
                "config registry active state changed",
                category=ProblemCategory.CONFLICT,
                phase=ProblemPhase.CONFIGURATION,
                location=ModelLocation(
                    root="config_registry",
                    path=("expected_generation",),
                ),
                related_locations=(StorageLocation(ref=CONFIG_REGISTRY_ACTIVE_REF),),
                details={
                    "expected_generation": expected,
                    "actual_generation": actual,
                },
            )
        ]
    )
