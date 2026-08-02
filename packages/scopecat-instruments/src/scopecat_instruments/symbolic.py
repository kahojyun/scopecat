"""Typed instrument clients that record declarative module effects."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.authoring import (
    EachEntity,
    OneEntity,
    PerEntity,
    ProductRef,
)

from scopecat_instruments._generated_clients import (
    NetworkSweepProducts,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    TemperatureSampleProducts,
)
from scopecat_instruments._symbolic_runtime import (
    DeclaredStateSymbolicClientBase,
    DeclaredStateSymbolicGroupBase,
    SymbolicInstrumentRecorder,
)
from scopecat_instruments.interface_declarations import (
    DC_MONITOR_ACQUISITION_DECLARATION,
    DCMonitorResults,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
)
from scopecat_instruments.states import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
)

type _DCSourceMonitorState = (
    DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState
)


@dataclass(frozen=True, slots=True)
class DCMonitorProducts(DCMonitorResults[ProductRef]):
    """Mode-dependent logical products produced by one DC monitor sample."""


class SymbolicDCSourceMonitorClient(
    DeclaredStateSymbolicClientBase[_DCSourceMonitorState]
):
    """Declarative source and monitor client requiring both capabilities."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(DC_SOURCE, DC_MONITOR),
            for_=for_,
        )

    def monitor(self, *, id: str | None = None) -> DCMonitorProducts:
        """Declare the result active for the most recently ensured source mode."""

        return self._acquire_declared(
            DC_MONITOR_ACQUISITION_DECLARATION,
            DCMonitorProducts,
            id=id,
        )


class SymbolicDCSourceMonitorGroup(
    DeclaredStateSymbolicGroupBase[
        _DCSourceMonitorState,
        SymbolicDCSourceMonitorClient,
    ]
):
    """Entity-keyed source and monitor clients with broadcast state."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            for_=for_,
            client_factory=SymbolicDCSourceMonitorClient,
        )

    def monitor(self, *, id: str | None = None) -> PerEntity[DCMonitorProducts]:
        return self._clients.map(lambda client: client.monitor(id=id))


__all__ = [
    "DCMonitorProducts",
    "NetworkSweepProducts",
    "SymbolicDCSourceClient",
    "SymbolicDCSourceGroup",
    "SymbolicDCSourceMonitorClient",
    "SymbolicDCSourceMonitorGroup",
    "SymbolicInstrumentRecorder",
    "SymbolicNetworkSweepClient",
    "SymbolicNetworkSweepGroup",
    "SymbolicRFOutputClient",
    "SymbolicRFOutputGroup",
    "SymbolicTemperatureReadoutClient",
    "SymbolicTemperatureReadoutGroup",
    "TemperatureSampleProducts",
]
