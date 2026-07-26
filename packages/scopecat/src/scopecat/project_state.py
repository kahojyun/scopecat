"""Project-scoped durable service ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
    from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class ProjectStateServices:
    """Durable ports shared by config and run workflows."""

    runs: RunRepository
    config_registry: ConfigRegistryUnitOfWorkFactory
