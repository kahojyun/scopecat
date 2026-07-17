"""Compose Scopecat's local filesystem application."""

from __future__ import annotations

from pathlib import Path

from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.api.workspace import Workspace
from scopecat.application.services import WorkspaceServices
from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.config.resolution import ConfigProfileInput
from scopecat.execution.services import ExecutionServices
from scopecat.planning.backend import ExecutionBackend
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.repository import RunRepository


def local_run_repository(workspace: str | Path) -> FilesystemRunRepository:
    """Open the filesystem run repository for a workspace."""

    return FilesystemRunRepository(workspace)


def local_config_registry_unit_of_work(
    workspace: str | Path,
) -> WorkspaceUnitOfWorkFactory:
    """Bind registry transactions and run reads to one local workspace."""

    from scopecat.adapters.filesystem.config_registry import (
        FilesystemWorkspaceUnitOfWork,
    )

    root = Path(workspace)
    return lambda: FilesystemWorkspaceUnitOfWork(root)


def local_execution_services(
    workspace: str | Path,
    *,
    runs: RunRepository | None = None,
) -> ExecutionServices:
    """Bind every execution port to the local filesystem adapter."""

    from scopecat.adapters.filesystem.execution import (
        FilesystemCollectionRepository,
        FilesystemExecutionJournal,
        FilesystemMeasurementRecordCommitter,
        FilesystemPayloadEvidenceCommitter,
        FilesystemResourceLeaseManager,
    )

    root = Path(workspace)
    selected_runs = FilesystemRunRepository(root) if runs is None else runs
    return ExecutionServices(
        runs=selected_runs,
        resources=FilesystemResourceLeaseManager(root),
        journal_for=lambda run_id: FilesystemExecutionJournal(root, run_id=run_id),
        measurements_for=lambda run_id: FilesystemMeasurementRecordCommitter(
            root, run_id=run_id
        ),
        collections_for=lambda run_id: FilesystemCollectionRepository(
            root, run_id=run_id
        ),
        payloads_for=lambda run_id: FilesystemPayloadEvidenceCommitter(
            root, run_id=run_id
        ),
    )


def local_workspace_services(workspace: str | Path) -> WorkspaceServices:
    """Bind every workspace-scoped application port to local adapters."""

    runs = local_run_repository(workspace)
    execution = local_execution_services(workspace, runs=runs)
    return WorkspaceServices(
        execution=execution,
        config_registry=local_config_registry_unit_of_work(workspace),
    )


def open_local_workspace(
    workspace: str | Path,
    *,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    reviewer: str = "operator",
    operator: str = "operator",
) -> Workspace:
    """Compose the public workspace facade with local filesystem services."""

    return Workspace(
        _workspace=Path(workspace),
        services=local_workspace_services(workspace),
        _config=config,
        _config_profile=config_profile,
        _execution_backend=execution_backend,
        _reviewer=reviewer,
        _operator=operator,
    )
