"""Typed live and declarative clients for first-party instrument interfaces."""

from __future__ import annotations

from typing import Literal, overload

from scopecat.api._instruments import (
    InstrumentRef,
    instrument,
)
from scopecat.authoring import EachEntity, EntitySelection, OneEntity

from scopecat_instruments._generated_clients import (
    DCMonitorProducts,
    DCMonitorReadback,
    DCSourceClient,
    DCSourceMonitorClient,
    NetworkSweepClient,
    NetworkSweepProducts,
    NetworkSweepReadback,
    RFOutputClient,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicDCSourceMonitorClient,
    SymbolicDCSourceMonitorGroup,
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
from scopecat_instruments._symbolic_runtime import SymbolicInstrumentRecorder
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
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
