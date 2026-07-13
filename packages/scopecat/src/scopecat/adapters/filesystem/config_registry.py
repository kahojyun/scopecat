"""Filesystem persistence for the workspace configuration registry."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from types import TracebackType
from typing import Self

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.adapters.filesystem.io import (
    ensure_durable_directory,
    write_model,
)
from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.config.registry.records import (
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryIndex,
)
from scopecat.kernel.errors import (
    DataIntegrityError,
    ProblemFailure,
    StorageError,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.refs import CONFIG_REGISTRY_LOCK_REF

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_INDEX_REF = f"{CONFIG_REGISTRY_ROOT}/index.json"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"


class FilesystemConfigRegistryRepository:
    """Registry records stored beneath one local workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)

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
        ref = self.entry_ref(entry_id)
        return _path_exists(self._workspace_relative_path(ref), ref=ref)

    def read_index(self) -> ConfigRegistryIndex:
        path = self._workspace_relative_path(self.index_ref)
        if not _path_exists(path, ref=self.index_ref):
            return ConfigRegistryIndex()
        return _read_model(path, ConfigRegistryIndex, self.index_ref)

    def read_entry(self, entry_id: str) -> ConfigRegistryEntry:
        ref = self.entry_ref(entry_id)
        return _read_model(
            self._workspace_relative_path(ref),
            ConfigRegistryEntry,
            ref,
        )

    def read_config(self, ref: str) -> ConfigProfileSnapshot:
        path = self._config_path(ref)
        content = _read_registry_text(path, ref=ref)
        try:
            return ConfigProfileSnapshot.model_validate_json(content)
        except ValidationError as error:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.config_invalid",
                category=ProblemCategory.DATA_INTEGRITY,
                message=("config registry snapshot does not match its durable schema"),
                location=_registry_storage_location(ref),
            ) from error

    def read_active_state(self) -> ConfigRegistryActiveState | None:
        path = self._workspace_relative_path(self.active_ref)
        if not _path_exists(path, ref=self.active_ref):
            return None
        content = _read_registry_text(path, ref=self.active_ref)
        try:
            return ConfigRegistryActiveState.model_validate_json(content)
        except ValidationError as error:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.active_state_invalid",
                category=ProblemCategory.DATA_INTEGRITY,
                message=(
                    "config registry active state does not match its durable schema"
                ),
                location=_registry_storage_location(self.active_ref),
            ) from error

    def commit_registration(
        self,
        *,
        index: ConfigRegistryIndex,
        entry: ConfigRegistryEntry,
        config: ConfigProfileSnapshot,
    ) -> None:
        updated_index = _index_with_entry(index, entry)

        # The index is the commit marker. A crash before its replacement leaves
        # an orphan config or a complete entry/config pair. An idempotent retry
        # verifies those records and repairs the index commit.
        self._write_model(entry.config_ref, config)
        self._write_model(self.entry_ref(entry.id), entry)
        self._write_model(self.index_ref, updated_index)

    def commit_active_state(self, state: ConfigRegistryActiveState) -> None:
        self._write_model(self.active_ref, state)

    def lock(self) -> AbstractContextManager[None]:
        lock_path = self._workspace_relative_path(CONFIG_REGISTRY_LOCK_REF)
        return _registry_lock(lock_path)

    def _write_model(self, ref: str, model: BaseModel) -> None:
        path = self._workspace_relative_path(ref)
        try:
            write_model(path, model)
        except OSError as error:
            raise _registry_failure(
                StorageError,
                code="config_registry.storage_failed",
                category=ProblemCategory.STORAGE,
                message="storage could not persist a config registry record",
                location=_registry_storage_location(ref),
            ) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.record_not_serializable",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry record cannot be represented durably",
                location=_registry_storage_location(ref),
                details={"model": type(model).__name__},
            ) from error

    def _workspace_relative_path(self, ref: str) -> Path:
        relative = PurePosixPath(ref)
        if relative.is_absolute() or ".." in relative.parts:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.path_escape",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry ref escapes the workspace",
                location=_registry_model_location("ref"),
                details={"ref": ref},
            )
        candidate = self.workspace / relative.as_posix()
        try:
            workspace_root = self.workspace.resolve(strict=False)
            resolved = candidate.resolve(strict=False)
        except OSError as error:
            raise _registry_failure(
                StorageError,
                code="config_registry.storage_failed",
                category=ProblemCategory.STORAGE,
                message="storage could not resolve a config registry path",
                location=_registry_storage_location(ref),
            ) from error
        try:
            resolved.relative_to(workspace_root)
        except ValueError as error:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.path_escape",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry ref escapes the workspace",
                location=_registry_model_location("ref"),
                details={"ref": ref},
            ) from error
        return candidate

    def _config_path(self, ref: str) -> Path:
        relative = PurePosixPath(ref)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) < 2
            or relative.parts[0] != CONFIG_REGISTRY_ROOT
            or relative.parts[1] != "configs"
        ):
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.config_ref_invalid",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry config ref is outside the config store",
                location=_registry_model_location("config_ref"),
                details={"ref": ref},
            )
        return self._workspace_relative_path(ref)


class FilesystemWorkspaceUnitOfWork:
    """Acquire the registry lock before exposing the run repository."""

    registry: FilesystemConfigRegistryRepository
    runs: FilesystemRunRepository

    def __init__(self, workspace: str | Path) -> None:
        self.registry = FilesystemConfigRegistryRepository(workspace)
        self.runs = FilesystemRunRepository(workspace)
        self._lock: AbstractContextManager[None] | None = None

    def __enter__(self) -> Self:
        if self._lock is not None:
            msg = "workspace unit of work cannot be entered twice"
            raise RuntimeError(msg)
        self._lock = self.registry.lock()
        self._lock.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        lock = self._lock
        if lock is None:
            msg = "workspace unit of work was not entered"
            raise RuntimeError(msg)
        self._lock = None
        lock.__exit__(exc_type, exc_value, traceback)


def _index_with_entry(
    index: ConfigRegistryIndex,
    entry: ConfigRegistryEntry,
) -> ConfigRegistryIndex:
    entries = [existing for existing in index.entries if existing.id != entry.id]
    entries.append(entry)
    return ConfigRegistryIndex(
        entries=tuple(sorted(entries, key=lambda item: item.registered_at))
    )


def _read_model[TModel: BaseModel](
    path: Path,
    model_type: type[TModel],
    ref: str,
) -> TModel:
    content = _read_registry_text(path, ref=ref)
    try:
        return model_type.model_validate_json(content)
    except ValidationError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_invalid",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record does not match its durable schema",
            location=_registry_storage_location(ref),
            details={"model": model_type.__name__},
        ) from error


def _path_exists(path: Path, *, ref: str) -> bool:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not inspect a config registry record",
            location=_registry_storage_location(ref),
        ) from error
    return True


def _read_registry_text(path: Path, *, ref: str) -> str:
    try:
        path_stat = path.stat()
    except FileNotFoundError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry is missing a referenced durable record",
            location=_registry_storage_location(ref),
        ) from error
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not inspect a config registry record",
            location=_registry_storage_location(ref),
        ) from error
    if not S_ISREG(path_stat.st_mode):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_not_file",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record is not a regular file",
            location=_registry_storage_location(ref),
        )
    try:
        return path.read_text()
    except FileNotFoundError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry is missing a referenced durable record",
            location=_registry_storage_location(ref),
        ) from error
    except UnicodeError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_invalid_encoding",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record is not valid text",
            location=_registry_storage_location(ref),
        ) from error
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not read a config registry record",
            location=_registry_storage_location(ref),
        ) from error


@contextmanager
def _registry_lock(lock_path: Path) -> Generator[None]:
    lock_file = None
    try:
        ensure_durable_directory(lock_path.parent)
        lock_file = lock_path.open("a+b")
        flock(lock_file.fileno(), LOCK_EX)
    except OSError as error:
        if lock_file is not None:
            with suppress(OSError):
                lock_file.close()
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not acquire the config registry lock",
            location=_registry_storage_location(CONFIG_REGISTRY_LOCK_REF),
        ) from error
    assert lock_file is not None
    try:
        yield
    finally:
        try:
            flock(lock_file.fileno(), LOCK_UN)
            lock_file.close()
        except OSError as error:
            raise _registry_failure(
                StorageError,
                code="config_registry.storage_failed",
                category=ProblemCategory.STORAGE,
                message="storage could not release the config registry lock",
                location=_registry_storage_location(CONFIG_REGISTRY_LOCK_REF),
            ) from error


def _registry_failure(
    failure_type: type[ProblemFailure],
    *,
    code: str,
    category: ProblemCategory,
    message: str,
    location: ProblemLocation | None = None,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
) -> ProblemFailure:
    return failure_type(
        [
            Problem(
                code=code,
                impact=ProblemImpact.BLOCKING,
                category=category,
                phase=ProblemPhase.CONFIGURATION,
                message=message,
                location=location,
                related_locations=tuple(related_locations),
                details={} if details is None else details,
            )
        ]
    )


def _registry_model_location(*path: str | int) -> ModelLocation:
    return ModelLocation(root="config_registry", path=path)


def _registry_storage_location(ref: str) -> StorageLocation:
    return StorageLocation(ref=ref)


__all__ = [
    "FilesystemConfigRegistryRepository",
    "FilesystemWorkspaceUnitOfWork",
]
