"""Typed live and declarative clients for first-party instrument interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, overload, override

from scopecat.api._instruments import (
    InstrumentRef,
    instrument,
)
from scopecat.authoring import EachEntity, EntitySelection, OneEntity
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
)

from scopecat_instruments._generated_clients import (
    DCSourceClient,
    NetworkSweepClient,
    NetworkSweepProducts,
    NetworkSweepReadback,
    RFOutputClient,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    TemperatureReadback,
    TemperatureReadoutClient,
    TemperatureReadoutObservation,
    TemperatureSampleProducts,
    network_sweep,
    rf_output,
    temperature_readout,
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
from scopecat_instruments.symbolic import (
    DCMonitorProducts,
    SymbolicDCSourceMonitorClient,
    SymbolicDCSourceMonitorGroup,
    SymbolicInstrumentRecorder,
)


@dataclass(frozen=True, slots=True)
class DCMonitorReadback(DCMonitorResults[MeasurementValue]):
    """Named mode-dependent monitor results plus their effect receipt."""

    receipt: CollectReceipt = field(repr=False)


class DCSourceMonitorClient(DCSourceClient):
    @override
    def apply(
        self,
        patch: DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState,
    ) -> ApplyReceipt:
        return self._apply_declared(patch)

    def monitor(self) -> DCMonitorReadback:
        return self._collect_declared(
            DC_MONITOR_ACQUISITION_DECLARATION,
            DCMonitorReadback,
        )


@overload
def dc_source(
    instrument_id: str,
    *,
    monitor: Literal[False] = False,
) -> InstrumentRef[DCSourceClient]: ...


@overload
def dc_source(
    instrument_id: str,
    *,
    monitor: Literal[True],
) -> InstrumentRef[DCSourceMonitorClient]: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
    monitor: Literal[False] = False,
) -> SymbolicDCSourceGroup: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
    monitor: Literal[True],
) -> SymbolicDCSourceMonitorGroup: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
    monitor: Literal[False] = False,
) -> SymbolicDCSourceClient: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
    monitor: Literal[True],
) -> SymbolicDCSourceMonitorClient: ...


def dc_source(
    instrument_id: str | SymbolicInstrumentRecorder,
    resource_id: str | None = None,
    *,
    for_: EntitySelection | None = None,
    monitor: bool = False,
) -> (
    InstrumentRef[DCSourceClient]
    | InstrumentRef[DCSourceMonitorClient]
    | SymbolicDCSourceClient
    | SymbolicDCSourceGroup
    | SymbolicDCSourceMonitorClient
    | SymbolicDCSourceMonitorGroup
):
    if isinstance(instrument_id, str):
        if resource_id is not None or for_ is not None:
            raise TypeError("live instrument clients only accept an instrument id")
        if monitor:
            return instrument(
                instrument_id,
                DCSourceMonitorClient,
                requires=(DC_SOURCE, DC_MONITOR),
            )
        return instrument(instrument_id, DCSourceClient, requires=(DC_SOURCE,))
    if resource_id is None:
        raise TypeError("symbolic instrument clients require a logical resource id")
    if isinstance(for_, EachEntity):
        if monitor:
            return SymbolicDCSourceMonitorGroup(
                instrument_id,
                resource_id,
                for_=for_,
            )
        return SymbolicDCSourceGroup(instrument_id, resource_id, for_=for_)
    if monitor:
        return SymbolicDCSourceMonitorClient(
            instrument_id,
            resource_id,
            for_=for_,
        )
    return SymbolicDCSourceClient(instrument_id, resource_id, for_=for_)


__all__ = [
    "DCMonitorProducts",
    "DCMonitorReadback",
    "DCSourceClient",
    "DCSourceMonitorClient",
    "NetworkSweepClient",
    "NetworkSweepProducts",
    "NetworkSweepReadback",
    "RFOutputClient",
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
    "TemperatureReadback",
    "TemperatureReadoutClient",
    "TemperatureReadoutObservation",
    "TemperatureSampleProducts",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
]
