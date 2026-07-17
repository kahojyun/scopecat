"""Effect boundaries shared by workspace-scoped use cases."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.execution.services import ExecutionServices
from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class WorkspaceServices:
    """All durable and execution ports selected for one workspace."""

    execution: ExecutionServices
    config_registry: WorkspaceUnitOfWorkFactory

    @property
    def runs(self) -> RunRepository:
        """The single run repository shared by every workspace use case."""

        return self.execution.runs
