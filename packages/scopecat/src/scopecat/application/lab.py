"""User-owned composition root shared by the daemon and notebook clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.daemon.catalog import RegisteredExperimentCatalog
from scopecat.planning.system import ExperimentSystemBuilder

if TYPE_CHECKING:
    from scopecat.api.lab import LabClient


@dataclass(frozen=True, slots=True)
class LabApplication:
    """Version-controlled executable composition for one lab project.

    Configuration bootstrap belongs to ``scopecat.toml`` so the project has one
    declarative seed source. Later activation state belongs to the daemon.
    """

    catalog: RegisteredExperimentCatalog = field(
        default_factory=RegisteredExperimentCatalog
    )
    build_system: ExperimentSystemBuilder | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def connect(
        self,
        daemon: str,
    ) -> LabClient:
        """Connect notebook code while retaining local scratch capabilities."""

        from scopecat.api.lab import LabClient
        from scopecat.daemon.connection import DaemonConnection

        return LabClient(
            DaemonConnection(daemon, build_system=self.build_system),
        )


__all__ = ["LabApplication"]
