"""Application compositions for in-process tests."""

from __future__ import annotations

from pathlib import Path

from scopecat.adapters.memory import MemoryProjectStore, MemoryResourceLeaseManager
from scopecat.adapters.sqlite import (
    SQLiteCollectionRecordRepository,
    SQLiteConfigRegistryStore,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.application.services import ProjectServices
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.execution.services import ExecutionServices


def sqlite_run_repository(project: str | Path) -> SQLiteRunRepository:
    """Open an isolated SQLite run repository."""

    database, objects = _sqlite_paths(project)
    SQLiteProjectStore(database, objects).bootstrap()
    repository = SQLiteRunRepository(database, objects)
    return repository


def sqlite_config_registry_unit_of_work(
    project: str | Path,
) -> ConfigRegistryUnitOfWorkFactory:
    """Open isolated configuration registry transactions."""

    runs = sqlite_run_repository(project)
    return _config_registry_store(project, runs=runs).unit_of_work


def sqlite_execution_services(
    project: str | Path,
    *,
    runs: SQLiteRunRepository | None = None,
) -> ExecutionServices:
    """Bind execution ports to isolated SQLite persistence."""

    selected_runs = sqlite_run_repository(project) if runs is None else runs
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


def sqlite_project_services(project: str | Path) -> ProjectServices:
    """Bind application ports to isolated SQLite adapters."""

    runs = sqlite_run_repository(project)
    execution = sqlite_execution_services(project, runs=runs)
    config_registry = _config_registry_store(project, runs=runs)
    return ProjectServices(
        runs=runs,
        execution=execution,
        config_registry=config_registry.unit_of_work,
    )


def memory_project_services(
    store: MemoryProjectStore | None = None,
) -> ProjectServices:
    """Bind application ports to stateful in-memory adapters."""

    project = store or MemoryProjectStore()
    state = project.execution
    execution = ExecutionServices(
        runs=project.runs,
        resources=state.resources,
        journal_for=state.journal_for,
        measurements_for=state.measurements_for,
        collections_for=state.collections_for,
        payloads_for=state.payloads_for,
    )
    return ProjectServices(
        runs=project.runs,
        execution=execution,
        config_registry=project.unit_of_work,
    )


def _sqlite_paths(project: str | Path) -> tuple[Path, Path]:
    state = Path(project) / ".scopecat-test"
    return state / "control.sqlite3", state / "objects"


def _config_registry_store(
    project: str | Path,
    *,
    runs: SQLiteRunRepository,
) -> SQLiteConfigRegistryStore:
    database, _ = _sqlite_paths(project)
    return SQLiteConfigRegistryStore(database, runs=runs)


__all__ = [
    "memory_project_services",
    "sqlite_config_registry_unit_of_work",
    "sqlite_execution_services",
    "sqlite_project_services",
    "sqlite_run_repository",
]
