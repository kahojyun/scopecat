"""User-owned composition root shared by the daemon and notebook clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments import InstrumentBackend

if TYPE_CHECKING:
    from scopecat.api.lab import LabClient

type BootstrapConfigFactory = Callable[[], ConfigProfileSnapshot]
type InstrumentBackendFactory = Callable[[], InstrumentBackend]


@dataclass(frozen=True, slots=True)
class LabApplication:
    """Version-controlled executable composition for one lab project.

    The application owns the initial snapshot because constructing configuration
    may require Python. Its factory stays lazy so ordinary notebook connections
    do not read seed inputs. Later accepted entries and activation state belong
    to the daemon. The instrument backend factory is daemon-only so loading this
    composition in a notebook does not import concrete drivers or transports.
    """

    build_experiment_system: ExperimentSystemBuilder | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    create_instrument_backend: InstrumentBackendFactory | None = field(
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
        """Connect notebook code while retaining local scratch capabilities."""

        from scopecat.api.lab import LabClient

        return LabClient(
            daemon,
            build_experiment_system=self.build_experiment_system,
            operator=operator,
        )


__all__ = [
    "BootstrapConfigFactory",
    "InstrumentBackendFactory",
    "LabApplication",
]
