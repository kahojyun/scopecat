"""Composition root for a local Scopecat daemon."""

from __future__ import annotations

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
from scopecat.config.registry import list_config_registry_entries
from scopecat.config.resolution import (
    ConfigProfileInput,
    register_and_activate_config_profile,
    validate_config_profile,
)
from scopecat.daemon.catalog import RegisteredExperimentCatalog
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.project import LabApplicationFactory
from scopecat.records.config import config_content_hash

from .backend import SQLiteDaemonBackend
from .transport import create_app


class LocalDaemonRuntime:
    """Own all process-scoped services for one project."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        catalog: RegisteredExperimentCatalog | None = None,
        build_system: ExperimentSystemBuilder | None = None,
        bootstrap_config: ConfigProfileInput | None = None,
        application_factory: LabApplicationFactory | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.project_root / ".scopecat"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        self._owner_lock = FileLock(self.state_dir / "daemon.lock")
        try:
            # This lock establishes one process owner; SQLite remains the only
            # concurrency mechanism inside that process boundary.
            self._owner_lock.acquire(timeout=0)
        except Timeout as error:
            raise RuntimeError(
                f"project already has a running daemon: {self.project_root}"
            ) from error
        database = self.state_dir / "control.sqlite3"
        objects = self.state_dir / "objects"

        try:
            if application_factory is not None:
                if catalog is not None or build_system is not None:
                    raise ValueError(
                        "application_factory cannot be combined with catalog or "
                        "build_system"
                    )
                application = application_factory(self.project_root)
                catalog = application.catalog
                build_system = application.build_system

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
                project_root=self.project_root,
                control=self.control,
                runs=self.runs,
                config_registry=self.config_registry,
                catalog=catalog,
                build_system=build_system,
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
            self._owner_lock.release()
            raise

    def app(self, *, static_dir: str | Path | None = None) -> FastAPI:
        return create_app(self.backend, static_dir=static_dir)

    def close(self) -> None:
        try:
            self.backend.close()
        finally:
            self._owner_lock.release()

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
        registered_by="scopecat",
        operator="scopecat",
        note="imported while bootstrapping a new lab instance",
    )


__all__ = ["LabApplicationFactory", "LocalDaemonRuntime"]
