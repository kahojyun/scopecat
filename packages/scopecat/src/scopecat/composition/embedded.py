"""Test/demo-only composition isolated from daemon-owned workspace state."""

from __future__ import annotations

from pathlib import Path

from scopecat.adapters.memory import MemoryResourceLeaseManager
from scopecat.adapters.sqlite import (
    SQLiteCollectionRecordRepository,
    SQLiteConfigRegistryStore,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    SQLiteRunRepository,
    bootstrap_execution_schema,
)
from scopecat.api.workspace import Workspace
from scopecat.application.services import WorkspaceServices
from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.config.resolution import ConfigProfileInput
from scopecat.execution.services import ExecutionServices
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot


def embedded_run_repository(workspace: str | Path) -> SQLiteRunRepository:
    """Open the isolated test/demo run repository."""

    database, objects = _workspace_paths(workspace)
    repository = SQLiteRunRepository(database, objects)
    repository.bootstrap()
    return repository


def embedded_config_registry_unit_of_work(
    workspace: str | Path,
) -> WorkspaceUnitOfWorkFactory:
    """Open isolated test/demo registry transactions."""

    runs = embedded_run_repository(workspace)
    store = _config_registry_store(workspace, runs=runs)
    return store.unit_of_work


def embedded_execution_services(
    workspace: str | Path,
    *,
    runs: SQLiteRunRepository | None = None,
) -> ExecutionServices:
    """Bind test/demo execution to isolated SQLite persistence."""

    selected_runs = embedded_run_repository(workspace) if runs is None else runs
    selected_runs.bootstrap()
    bootstrap_execution_schema(selected_runs)
    return ExecutionServices(
        runs=selected_runs,
        resources=MemoryResourceLeaseManager(),
        journal_for=lambda run_id: SQLiteExecutionJournal(
            selected_runs,
            run_id=run_id,
        ),
        measurements_for=lambda run_id: SQLiteMeasurementDatasetRepository(
            selected_runs,
            run_id=run_id,
        ),
        collections_for=lambda run_id: SQLiteCollectionRecordRepository(
            selected_runs,
            run_id=run_id,
        ),
        payloads_for=lambda run_id: SQLitePayloadEvidenceCommitter(
            selected_runs,
            run_id=run_id,
        ),
    )


def embedded_workspace_services(workspace: str | Path) -> WorkspaceServices:
    """Bind test/demo application ports to isolated embedded adapters."""

    runs = embedded_run_repository(workspace)
    execution = embedded_execution_services(workspace, runs=runs)
    config_registry = _config_registry_store(workspace, runs=runs)
    return WorkspaceServices(
        runs=runs,
        execution=execution,
        config_registry=config_registry.unit_of_work,
    )


def open_embedded_workspace(
    workspace: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
    reviewer: str = "operator",
    operator: str = "operator",
) -> Workspace:
    """Compose a test/demo facade that cannot write daemon-owned state."""

    return Workspace(
        _workspace=Path(workspace),
        services=embedded_workspace_services(workspace),
        _config=config,
        _config_profile=config_profile,
        _system=system,
        _reviewer=reviewer,
        _operator=operator,
    )


def _workspace_paths(workspace: str | Path) -> tuple[Path, Path]:
    # A separate root prevents this helper from becoming a second daemon writer.
    state = Path(workspace) / ".scopecat-embedded"
    return state / "workspace.sqlite3", state / "objects"


def _config_registry_store(
    workspace: str | Path,
    *,
    runs: SQLiteRunRepository,
) -> SQLiteConfigRegistryStore:
    database, _ = _workspace_paths(workspace)
    store = SQLiteConfigRegistryStore(database, runs=runs)
    store.bootstrap()
    return store
