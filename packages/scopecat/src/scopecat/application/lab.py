"""User-owned composition root shared by the daemon and notebook clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.daemon.catalog import RegisteredExperimentCatalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot

if TYPE_CHECKING:
    from scopecat.daemon.workspace import DaemonWorkspace


@dataclass(frozen=True, slots=True)
class LabApplication:
    """Executable lab code and the seed for a new Scopecat instance.

    The catalog and system remain ordinary version-controlled Python objects.
    ``bootstrap_config`` is imported only when the daemon opens an empty config
    registry; later activation state belongs to the daemon.
    """

    catalog: RegisteredExperimentCatalog = field(
        default_factory=RegisteredExperimentCatalog
    )
    system: ExperimentSystem | None = None
    bootstrap_config: ConfigProfileSnapshot | None = None

    def connect(
        self,
        daemon: str = "http://127.0.0.1:8765",
    ) -> DaemonWorkspace:
        """Connect notebook code while retaining local scratch capabilities."""

        from scopecat.daemon.workspace import DaemonWorkspace

        return DaemonWorkspace(daemon, system=self.system)


__all__ = ["LabApplication"]
