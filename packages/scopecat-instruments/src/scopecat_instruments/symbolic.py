"""Typed instrument clients that record declarative module effects."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.authoring import (
    EachEntity,
    OneEntity,
    PerEntity,
    ProductRef,
)

from scopecat_instruments._symbolic_runtime import (
    DeclaredStateSymbolicClientBase,
    DeclaredStateSymbolicGroupBase,
    SymbolicInstrumentClientBase,
    SymbolicInstrumentGroupBase,
    SymbolicInstrumentRecorder,
)
from scopecat_instruments.interface_declarations import (
    DC_MONITOR_ACQUISITION_DECLARATION,
    NETWORK_SWEEP_ACQUISITION_DECLARATION,
    TEMPERATURE_SAMPLE_DECLARATION,
    DCMonitorResults,
    NetworkSweepResults,
    TemperatureSampleResults,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
)
from scopecat_instruments.states import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
    RFOutputState,
)

type _DCSourceState = DCSourceState | DCSourceVoltage | DCSourceCurrent
type _DCSourceMonitorState = _DCSourceState | DCMonitorState


@dataclass(frozen=True, slots=True)
class NetworkSweepProducts(NetworkSweepResults[ProductRef, ProductRef]):
    """Typed logical products produced by one declarative network sweep."""


@dataclass(frozen=True, slots=True)
class DCMonitorProducts(DCMonitorResults[ProductRef]):
    """Mode-dependent logical products produced by one DC monitor sample."""


@dataclass(frozen=True, slots=True)
class TemperatureSampleProducts(TemperatureSampleResults[ProductRef]):
    """Typed logical products produced by one temperature sample."""


class SymbolicDCSourceClient(DeclaredStateSymbolicClientBase[_DCSourceState]):
    """Declarative DC-source state client backed by a logical resource."""

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
            requires=(DC_SOURCE,),
            for_=for_,
        )


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


class SymbolicRFOutputClient(DeclaredStateSymbolicClientBase[RFOutputState]):
    """Declarative RF-output state client backed by a logical resource."""

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
            requires=(RF_OUTPUT,),
            for_=for_,
        )


class SymbolicNetworkSweepClient(DeclaredStateSymbolicClientBase[NetworkSweepState]):
    """Declarative network-analyzer state and acquisition client."""

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
            requires=(NETWORK_SWEEP,),
            for_=for_,
        )

    def sweep(self, *, id: str | None = None) -> NetworkSweepProducts:
        """Declare a sweep and derive its product schemas from the interface."""

        return self._acquire_declared(
            NETWORK_SWEEP_ACQUISITION_DECLARATION,
            NetworkSweepProducts,
            id=id,
        )


class SymbolicTemperatureReadoutClient(SymbolicInstrumentClientBase):
    """Declarative temperature acquisition client."""

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
            requires=(TEMPERATURE_READOUT,),
            for_=for_,
        )

    def sample(self, *, id: str | None = None) -> TemperatureSampleProducts:
        """Declare a sample and derive its products from the interface."""

        return self._acquire_declared(
            TEMPERATURE_SAMPLE_DECLARATION,
            TemperatureSampleProducts,
            id=id,
        )


class SymbolicDCSourceGroup(
    DeclaredStateSymbolicGroupBase[_DCSourceState, SymbolicDCSourceClient]
):
    """Entity-keyed declarative DC-source clients with broadcast state."""

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
            client_factory=SymbolicDCSourceClient,
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


class SymbolicRFOutputGroup(
    DeclaredStateSymbolicGroupBase[RFOutputState, SymbolicRFOutputClient]
):
    """Entity-keyed declarative RF-output clients with broadcast state."""

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
            client_factory=SymbolicRFOutputClient,
        )


class SymbolicNetworkSweepGroup(
    DeclaredStateSymbolicGroupBase[NetworkSweepState, SymbolicNetworkSweepClient]
):
    """Entity-keyed declarative network sweeps with broadcast state."""

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
            client_factory=SymbolicNetworkSweepClient,
        )

    def sweep(self, *, id: str | None = None) -> PerEntity[NetworkSweepProducts]:
        return self._clients.map(lambda client: client.sweep(id=id))


class SymbolicTemperatureReadoutGroup(
    SymbolicInstrumentGroupBase[SymbolicTemperatureReadoutClient]
):
    """Entity-keyed declarative temperature samples."""

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
            client_factory=SymbolicTemperatureReadoutClient,
        )

    def sample(
        self,
        *,
        id: str | None = None,
    ) -> PerEntity[TemperatureSampleProducts]:
        return self._clients.map(lambda client: client.sample(id=id))


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
