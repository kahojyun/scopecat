"""Effect boundaries shared by project-scoped use cases."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.execution.services import ExecutionServices
from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class ProjectStateServices:
    """Durable ports used by planning, config, and run-content workflows."""

    runs: RunRepository
    config_registry: ConfigRegistryUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class ProjectServices(ProjectStateServices):
    """Project state plus the effects required for local execution."""

    execution: ExecutionServices
