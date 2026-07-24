"""Composition root for a local Scopecat daemon."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Self

from fastapi import FastAPI
from filelock import FileLock, Timeout
from scopecat.adapters.sqlite import (
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteRunRepository,
    bootstrap_execution_schema,
)
from scopecat.application import LabApplication
from scopecat.config.registry import list_config_registry_entries
from scopecat.config.resolution import (
    ConfigProfileInput,
    register_and_activate_config_profile,
    validate_config_profile,
)
from scopecat.daemon.catalog import RegisteredExperimentCatalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import config_content_hash

from .backend import SQLiteDaemonBackend
from .transport import create_app

type LabApplicationFactory = Callable[[Path], LabApplication]


class LocalDaemonRuntime:
    """Own all process-scoped services for one workspace."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        catalog: RegisteredExperimentCatalog | None = None,
        system: ExperimentSystem | None = None,
        bootstrap_config: ConfigProfileInput | None = None,
        application_factory: LabApplicationFactory | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.workspace / ".scopecat"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        self._workspace_lock = FileLock(self.state_dir / "daemon.lock")
        try:
            # This lock establishes one process owner; SQLite remains the only
            # concurrency mechanism inside that process boundary.
            self._workspace_lock.acquire(timeout=0)
        except Timeout as error:
            raise RuntimeError(
                f"workspace already has a running daemon: {self.workspace}"
            ) from error
        database = self.state_dir / "workspace.sqlite3"
        objects = self.state_dir / "objects"

        try:
            if application_factory is not None:
                if catalog is not None or system is not None:
                    raise ValueError(
                        "application_factory cannot be combined with catalog or system"
                    )
                application = application_factory(self.workspace)
                catalog = application.catalog
                system = application.system
                if bootstrap_config is None:
                    bootstrap_config = application.bootstrap_config

            self.control = SQLiteControlPlane(database)
            self.runs = SQLiteRunRepository(database, objects)
            self.config_registry = SQLiteConfigRegistryStore(
                database,
                runs=self.runs,
            )

            # Every adapter refuses unknown schemas; bootstrap is deliberately
            # explicit so opening a runtime never implies a migration.
            self.control.bootstrap()
            self.runs.bootstrap()
            bootstrap_execution_schema(self.runs)
            self.config_registry.bootstrap()

            backend = SQLiteDaemonBackend(
                workspace=self.workspace,
                control=self.control,
                runs=self.runs,
                config_registry=self.config_registry,
                catalog=catalog,
                system=system,
                lease_ttl=lease_ttl,
            )
            try:
                if bootstrap_config is not None:
                    _bootstrap_config_registry(backend, bootstrap_config)
            except BaseException:
                backend.close()
                raise
            self.backend = backend
        except BaseException:
            self._workspace_lock.release()
            raise

    def app(self, *, static_dir: str | Path | None = None) -> FastAPI:
        return create_app(self.backend, static_dir=static_dir)

    def close(self) -> None:
        try:
            self.backend.close()
        finally:
            self._workspace_lock.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


def _bootstrap_config_registry(
    backend: SQLiteDaemonBackend,
    config: ConfigProfileInput,
) -> None:
    if list_config_registry_entries(unit_of_work=backend.config_registry.unit_of_work):
        return
    validated = validate_config_profile(config).config
    digest = config_content_hash(validated).removeprefix("sha256:")
    register_and_activate_config_profile(
        config=validated,
        services=backend.services,
        entry_id=f"daemon-{digest}",
        registered_by="scopecatd",
        operator="scopecatd",
        note="imported while bootstrapping a new lab instance",
    )


__all__ = ["LabApplicationFactory", "LocalDaemonRuntime"]
