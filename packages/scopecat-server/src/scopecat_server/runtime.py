"""Composition root for a local Scopecat daemon."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Self

from fastapi import FastAPI
from filelock import FileLock, Timeout
from scopecat.application.lab import BootstrapConfigFactory
from scopecat.config.resolution import validate_config_profile
from scopecat.daemon.wire import (
    ConfigPublishCommand,
    DirectConfigRevisionSource,
)
from scopecat.project import load_application_factory
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash

from scopecat_server.command_payloads import CommandPayloadService
from scopecat_server.services.admission import AdmissionService
from scopecat_server.services.application import DaemonApplication
from scopecat_server.services.config import ConfigService
from scopecat_server.services.executor import ExecutorService
from scopecat_server.services.leases import OwnershipLeaseSupervisor
from scopecat_server.services.runs import RunService
from scopecat_server.storage.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.control_plane import SQLiteControlPlane
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

from .http.transport import create_app
from .instruments.actors import InstrumentActorRegistry
from .instruments.backend import InstrumentBackendEndpoint
from .instruments.service import InstrumentService
from .instruments.worker import SubprocessInstrumentBackendEndpoint

_DEFAULT_INSTRUMENT_SHUTDOWN_GRACE = timedelta(seconds=5)
_DEFAULT_INSTRUMENT_SESSION_LEASE_TTL = timedelta(seconds=90)


class LocalDaemonRuntime:
    """Own all process-scoped services for one project."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        bootstrap_config: ConfigProfileSnapshot | BootstrapConfigFactory | None = None,
        application_spec: str | None = None,
        instrument_backend_spec: str | None = None,
        instrument_endpoint: InstrumentBackendEndpoint | None = None,
        instrument_shutdown_grace: timedelta = _DEFAULT_INSTRUMENT_SHUTDOWN_GRACE,
        instrument_session_lease_ttl: timedelta = (
            _DEFAULT_INSTRUMENT_SESSION_LEASE_TTL
        ),
        lease_ttl: timedelta | None = None,
    ) -> None:
        self._close_lock = Lock()
        if instrument_backend_spec is not None and instrument_endpoint is not None:
            raise ValueError(
                "instrument_backend_spec and instrument_endpoint cannot be combined"
            )
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
            if application_spec is not None:
                lab_application = load_application_factory(
                    application_spec,
                    self.project_root,
                )(self.project_root)
                application_bootstrap = lab_application.bootstrap_config
            if instrument_backend_spec is not None:
                instrument_endpoint = SubprocessInstrumentBackendEndpoint(
                    self.project_root,
                    instrument_backend_spec,
                )

            sqlite = SQLiteDatabase(database)
            project_store = SQLiteProjectStore(sqlite, objects)
            project_store.bootstrap()

            control = SQLiteControlPlane(sqlite)
            runs = SQLiteRunRepository(sqlite, objects)
            config_registry = SQLiteConfigRegistryStore(
                sqlite,
                runs=runs,
            )
            payloads = CommandPayloadService()

            services = ProjectStateServices(
                runs=runs,
                config_registry=config_registry.read_unit_of_work,
            )
            instrument_actors = InstrumentActorRegistry()
            config_service = ConfigService(
                control=control,
                config_registry=config_registry,
                runs=runs,
                services=services,
                actors=instrument_actors,
            )
            run_service = RunService(
                control=control,
                runs=runs,
                services=services,
            )
            admission = AdmissionService(
                control=control,
                runs=runs,
                services=services,
            )
            instruments = InstrumentService(
                control=control,
                runs=runs,
                config=config_service,
                endpoint=instrument_endpoint,
                payloads=payloads,
                actors=instrument_actors,
                shutdown_grace_seconds=instrument_shutdown_grace.total_seconds(),
                session_lease_ttl=instrument_session_lease_ttl,
            )
            executor = ExecutorService(
                control=control,
                runs=runs,
                instruments=instruments,
                lease_ttl=lease_ttl,
            )
            project_id = _project_id(self.project_root)
            lease_supervisor = OwnershipLeaseSupervisor(
                instruments=instruments,
                shutdown_timeout_seconds=instrument_shutdown_grace.total_seconds(),
            )
            application = DaemonApplication(
                project_root=self.project_root,
                project_id=project_id,
                project_store=project_store,
                config=config_service,
                runs=run_service,
                admission=admission,
                executor=executor,
                instruments=instruments,
                payloads=payloads,
                lease_supervisor=lease_supervisor,
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
            self._closed = False
        except BaseException:
            if instrument_endpoint is not None:
                with suppress(Exception):
                    instrument_endpoint.shutdown()
            self._owner_lock.release()
            raise

    def app(
        self,
        *,
        static_dir: str | Path | None = None,
        request_shutdown: Callable[[str], bool] | None = None,
    ) -> FastAPI:
        return create_app(
            self.application,
            static_dir=static_dir,
            request_shutdown=request_shutdown,
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self.application.close()
            self._owner_lock.release()
            self._closed = True

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
    config: ConfigProfileSnapshot | BootstrapConfigFactory,
) -> None:
    if config_service.get_config_registry().entries:
        return
    # Resolve application-owned inputs only for a genuinely empty registry.
    selected = config() if callable(config) else config
    validated = validate_config_profile(selected)
    digest = config_content_hash(validated).removeprefix("sha256:")
    config_service.publish_config(
        ConfigPublishCommand(
            source=DirectConfigRevisionSource(config=validated),
            entry_id=f"daemon-{digest}",
            actor="scopecat",
            expected_generation=0,
            note="imported while bootstrapping a new lab instance",
        )
    )


def _project_id(project_root: Path) -> str:
    identity = sha256(str(project_root).encode()).hexdigest()[:16]
    return f"local:{identity}"


__all__ = ["LocalDaemonRuntime"]
