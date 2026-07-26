"""Effect boundaries shared by project-scoped use cases."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class ProjectStateServices:
    """Durable ports used by planning, config, and run-content workflows."""

    runs: RunRepository
    config_registry: ConfigRegistryUnitOfWorkFactory
