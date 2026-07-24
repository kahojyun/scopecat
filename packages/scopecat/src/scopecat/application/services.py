"""Effect boundaries shared by workspace-scoped use cases."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.execution.services import ExecutionServices
from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class WorkspaceStateServices:
    """Durable ports used by planning, config, and run-content workflows."""

    runs: RunRepository
    config_registry: WorkspaceUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class WorkspaceServices(WorkspaceStateServices):
    """Workspace state plus the effects required for local execution."""

    execution: ExecutionServices
