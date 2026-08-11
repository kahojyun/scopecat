"""User-owned composition root shared by the daemon and notebook clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.records.config import ConfigProfileSnapshot

if TYPE_CHECKING:
    from scopecat.api.lab import LabClient
    from scopecat.planning.system import ExperimentSystemBuilder

type BootstrapConfigFactory = Callable[[], ConfigProfileSnapshot]


@dataclass(frozen=True, slots=True)
class LabApplication:
    """Version-controlled executable composition for one lab project.

    The application owns the initial snapshot because constructing configuration
    may require Python. Its factory stays lazy so ordinary notebook connections
    do not read seed inputs. Later accepted entries and activation state belong
    to the daemon. Instrument backend composition is declared separately in the
    project manifest and loaded only by the isolated worker.
    """

    build_experiment_system: ExperimentSystemBuilder | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    bootstrap_config: BootstrapConfigFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def connect(
        self,
        daemon: str,
        *,
        operator: str = "operator",
    ) -> LabClient:
        """Connect notebook code while retaining locally authored closures."""

        from scopecat.api.lab import LabClient

        return LabClient(
            daemon,
            build_experiment_system=self.build_experiment_system,
            operator=operator,
        )


__all__ = [
    "BootstrapConfigFactory",
    "LabApplication",
]
