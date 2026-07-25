"""Composition root for a local Scopecat daemon."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Self

from fastapi import FastAPI
from filelock import FileLock, Timeout
from scopecat.adapters.sqlite import (
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.application.lab import BootstrapConfigFactory
from scopecat.application.services import ProjectStateServices
from scopecat.config.resolution import ConfigProfileInput, validate_config_profile
from scopecat.daemon.catalog import RegisteredExperimentCatalog
from scopecat.daemon.wire import DirectConfigDefaultCommand
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.project import LabApplicationFactory
from scopecat.records.config import config_content_hash

from .services import (
    AdmissionService,
    ConfigService,
    DaemonApplication,
    ExecutorService,
    ManagedRunSupervisor,
    RunService,
)
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
        application_bootstrap: BootstrapConfigFactory | None = None

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
                application_bootstrap = application.bootstrap_config

            control = SQLiteControlPlane(database)
            runs = SQLiteRunRepository(database, objects)
            config_registry = SQLiteConfigRegistryStore(
                database,
                runs=runs,
            )

            project_store = SQLiteProjectStore(database, objects)
            project_store.bootstrap()

            selected_catalog = catalog or RegisteredExperimentCatalog()
            executor = ExecutorService(
                control=control,
                runs=runs,
                lease_ttl=lease_ttl,
            )
            services = ProjectStateServices(
                runs=runs,
                config_registry=config_registry.unit_of_work,
            )
            content_lock = Lock()
            config_service = ConfigService(
                control=control,
                config_registry=config_registry,
                services=services,
                run_content_lock=content_lock,
            )
            run_service = RunService(
                control=control,
                runs=runs,
                services=services,
                content_lock=content_lock,
            )
            admission = AdmissionService(
                control=control,
                runs=runs,
                services=services,
                catalog=selected_catalog,
                build_system=build_system,
            )
            project_id = _project_id(self.project_root)
            managed = ManagedRunSupervisor(
                project_id=project_id,
                control=control,
                runs=runs,
                admission=admission,
                executor=executor,
            )
            application = DaemonApplication(
                project_root=self.project_root,
                project_id=project_id,
                project_store=project_store,
                catalog=selected_catalog,
                config=config_service,
                runs=run_service,
                admission=admission,
                executor=executor,
                managed=managed,
            )
            try:
                bootstrap_source = (
                    bootstrap_config
                    if bootstrap_config is not None
                    else application_bootstrap
                )
                if bootstrap_source is not None:
                    _bootstrap_config_registry(
                        config_service,
                        bootstrap_source,
                    )
                application.start()
            except BaseException:
                application.close()
                raise
            self.application = application
        except BaseException:
            self._owner_lock.release()
            raise

    def app(self, *, static_dir: str | Path | None = None) -> FastAPI:
        return create_app(self.application, static_dir=static_dir)

    def close(self) -> None:
        try:
            self.application.close()
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
    config_service: ConfigService,
    config: ConfigProfileInput | BootstrapConfigFactory,
) -> None:
    if config_service.get_config_registry().entries:
        return
    # Resolve application-owned inputs only for a genuinely empty registry.
    selected = config() if callable(config) else config
    validated = validate_config_profile(selected).config
    digest = config_content_hash(validated).removeprefix("sha256:")
    config_service.set_direct_config_default(
        DirectConfigDefaultCommand(
            entry_id=f"daemon-{digest}",
            config=validated,
            registered_by="scopecat",
            operator="scopecat",
            expected_generation=0,
            note="imported while bootstrapping a new lab instance",
        )
    )


def _project_id(project_root: Path) -> str:
    identity = sha256(str(project_root).encode()).hexdigest()[:16]
    return f"local:{identity}"


__all__ = ["LabApplicationFactory", "LocalDaemonRuntime"]
