"""Typed live and declarative clients for first-party instrument interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import overload

from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    instrument,
)
from scopecat.authoring import EachEntity, EntitySelection, OneEntity
from scopecat.daemon.wire import InstrumentConfiguredDefaultsApplyReceipt
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentDescription,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import declared_state_assignments

from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_VOLTAGE_RESULT,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    TEMPERATURE_READOUT_RESISTANCE_RESULT,
    TEMPERATURE_READOUT_SAMPLE,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.states import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
    RFOutputState,
)
from scopecat_instruments.symbolic import (
    DCMonitorProducts,
    NetworkSweepProducts,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicInstrumentRecorder,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    TemperatureSampleProducts,
)


@dataclass(frozen=True, slots=True)
class NetworkSweepReadback:
    """Named network-sweep results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    frequency: MeasurementValue | None
    s_parameter: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class TemperatureReadback:
    """Named temperature-readout results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    temperature: MeasurementValue | None
    resistance: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class DCMonitorReadback:
    """Named mode-dependent monitor results plus their effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    current: MeasurementValue | None
    voltage: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class _InstrumentClient:
    _session: InstrumentClientChannel = field(repr=False)
    instrument_id: str

    def describe(self) -> InstrumentDescription:
        return self._session.describe(self.instrument_id)

    def observed_state(self) -> InstrumentStateSnapshot:
        return self._session.observed_state(self.instrument_id)

    def refresh(self) -> InstrumentStateSnapshot:
        return self._session.read_state(self.instrument_id)

    def apply_defaults(self) -> InstrumentConfiguredDefaultsApplyReceipt:
        """Apply the configured sparse default state for this instrument."""

        return self._session.apply_configured_defaults(self.instrument_id)


class DCSourceClient(_InstrumentClient):
    def apply(
        self,
        patch: (DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState),
    ) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )

    def monitor(self) -> DCMonitorReadback:
        receipt = self._session.collect(
            DC_MONITOR_ACQUISITION,
            instrument_id=self.instrument_id,
        )
        return DCMonitorReadback(
            receipt=receipt,
            current=_readback_value(receipt, DC_MONITOR_CURRENT_RESULT.result_id),
            voltage=_readback_value(receipt, DC_MONITOR_VOLTAGE_RESULT.result_id),
        )


class RFOutputClient(_InstrumentClient):
    def apply(self, patch: RFOutputState) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )


class NetworkSweepClient(_InstrumentClient):
    def apply(self, patch: NetworkSweepState) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )

    def sweep(self) -> NetworkSweepReadback:
        receipt = self._session.collect(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_FREQUENCY_RESULT,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
            instrument_id=self.instrument_id,
        )
        return NetworkSweepReadback(
            receipt=receipt,
            frequency=_readback_value(
                receipt,
                NETWORK_SWEEP_FREQUENCY_RESULT.result_id,
            ),
            s_parameter=_readback_value(
                receipt,
                NETWORK_SWEEP_S_PARAMETER_RESULT.result_id,
            ),
        )


class TemperatureReadoutClient(_InstrumentClient):
    def sample(self) -> TemperatureReadback:
        receipt = self._session.collect(
            TEMPERATURE_READOUT_SAMPLE,
            instrument_id=self.instrument_id,
        )
        return TemperatureReadback(
            receipt=receipt,
            temperature=_readback_value(
                receipt,
                TEMPERATURE_READOUT_TEMPERATURE_RESULT.result_id,
            ),
            resistance=_readback_value(
                receipt,
                TEMPERATURE_READOUT_RESISTANCE_RESULT.result_id,
            ),
        )


@overload
def dc_source(instrument_id: str) -> InstrumentRef[DCSourceClient]: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
    monitor: bool = False,
) -> SymbolicDCSourceGroup: ...


@overload
def dc_source(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
    monitor: bool = False,
) -> SymbolicDCSourceClient: ...


def dc_source(
    instrument_id: str | SymbolicInstrumentRecorder,
    resource_id: str | None = None,
    *,
    for_: EntitySelection | None = None,
    monitor: bool = False,
) -> InstrumentRef[DCSourceClient] | SymbolicDCSourceClient | SymbolicDCSourceGroup:
    if isinstance(instrument_id, str):
        if resource_id is not None or for_ is not None or monitor:
            raise TypeError("live instrument clients only accept an instrument id")
        return instrument(instrument_id, DCSourceClient)
    if resource_id is None:
        raise TypeError("symbolic instrument clients require a logical resource id")
    if isinstance(for_, EachEntity):
        return SymbolicDCSourceGroup(
            instrument_id,
            resource_id,
            for_=for_,
            monitor=monitor,
        )
    return SymbolicDCSourceClient(
        instrument_id,
        resource_id,
        for_=for_,
        monitor=monitor,
    )


@overload
def rf_output(instrument_id: str) -> InstrumentRef[RFOutputClient]: ...


@overload
def rf_output(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
) -> SymbolicRFOutputGroup: ...


@overload
def rf_output(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
) -> SymbolicRFOutputClient: ...


def rf_output(
    instrument_id: str | SymbolicInstrumentRecorder,
    resource_id: str | None = None,
    *,
    for_: EntitySelection | None = None,
) -> InstrumentRef[RFOutputClient] | SymbolicRFOutputClient | SymbolicRFOutputGroup:
    if isinstance(instrument_id, str):
        if resource_id is not None or for_ is not None:
            raise TypeError("live instrument clients only accept an instrument id")
        return instrument(instrument_id, RFOutputClient)
    if resource_id is None:
        raise TypeError("symbolic instrument clients require a logical resource id")
    if isinstance(for_, EachEntity):
        return SymbolicRFOutputGroup(instrument_id, resource_id, for_=for_)
    return SymbolicRFOutputClient(instrument_id, resource_id, for_=for_)


@overload
def network_sweep(instrument_id: str) -> InstrumentRef[NetworkSweepClient]: ...


@overload
def network_sweep(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
) -> SymbolicNetworkSweepGroup: ...


@overload
def network_sweep(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
) -> SymbolicNetworkSweepClient: ...


def network_sweep(
    instrument_id: str | SymbolicInstrumentRecorder,
    resource_id: str | None = None,
    *,
    for_: EntitySelection | None = None,
) -> (
    InstrumentRef[NetworkSweepClient]
    | SymbolicNetworkSweepClient
    | SymbolicNetworkSweepGroup
):
    if isinstance(instrument_id, str):
        if resource_id is not None or for_ is not None:
            raise TypeError("live instrument clients only accept an instrument id")
        return instrument(instrument_id, NetworkSweepClient)
    if resource_id is None:
        raise TypeError("symbolic instrument clients require a logical resource id")
    if isinstance(for_, EachEntity):
        return SymbolicNetworkSweepGroup(instrument_id, resource_id, for_=for_)
    return SymbolicNetworkSweepClient(instrument_id, resource_id, for_=for_)


@overload
def temperature_readout(
    instrument_id: str,
) -> InstrumentRef[TemperatureReadoutClient]: ...


@overload
def temperature_readout(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: EachEntity,
) -> SymbolicTemperatureReadoutGroup: ...


@overload
def temperature_readout(
    instrument_id: SymbolicInstrumentRecorder,
    resource_id: str,
    *,
    for_: OneEntity | None = None,
) -> SymbolicTemperatureReadoutClient: ...


def temperature_readout(
    instrument_id: str | SymbolicInstrumentRecorder,
    resource_id: str | None = None,
    *,
    for_: EntitySelection | None = None,
) -> (
    InstrumentRef[TemperatureReadoutClient]
    | SymbolicTemperatureReadoutClient
    | SymbolicTemperatureReadoutGroup
):
    if isinstance(instrument_id, str):
        if resource_id is not None or for_ is not None:
            raise TypeError("live instrument clients only accept an instrument id")
        return instrument(instrument_id, TemperatureReadoutClient)
    if resource_id is None:
        raise TypeError("symbolic instrument clients require a logical resource id")
    if isinstance(for_, EachEntity):
        return SymbolicTemperatureReadoutGroup(instrument_id, resource_id, for_=for_)
    return SymbolicTemperatureReadoutClient(instrument_id, resource_id, for_=for_)


def _concrete_assignments(
    state: (
        DCSourceState
        | DCSourceVoltage
        | DCSourceCurrent
        | DCMonitorState
        | NetworkSweepState
        | RFOutputState
    ),
) -> dict[PropertyRef, StateLiteral]:
    try:
        return {
            target: StateValue.model_validate(value).root
            for target, value in declared_state_assignments(state).items()
        }
    except ValueError as error:
        raise TypeError(
            "direct instrument state must contain concrete values"
        ) from error


def _readback_value(
    receipt: CollectReceipt,
    result_id: str,
) -> MeasurementValue | None:
    readback = receipt.readback
    return None if readback is None else readback.values.get(result_id)


__all__ = [
    "DCMonitorProducts",
    "DCMonitorReadback",
    "DCSourceClient",
    "NetworkSweepClient",
    "NetworkSweepProducts",
    "NetworkSweepReadback",
    "RFOutputClient",
    "SymbolicDCSourceClient",
    "SymbolicDCSourceGroup",
    "SymbolicInstrumentRecorder",
    "SymbolicNetworkSweepClient",
    "SymbolicNetworkSweepGroup",
    "SymbolicRFOutputClient",
    "SymbolicRFOutputGroup",
    "SymbolicTemperatureReadoutClient",
    "SymbolicTemperatureReadoutGroup",
    "TemperatureReadback",
    "TemperatureReadoutClient",
    "TemperatureSampleProducts",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
]
