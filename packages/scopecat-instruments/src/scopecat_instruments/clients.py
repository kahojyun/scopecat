"""Typed live and declarative clients for first-party instrument interfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, overload, override

from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentClientFactory,
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
    InterfaceRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    declared_state_assignments,
)

from scopecat_instruments.interface_declarations import (
    DC_MONITOR_ACQUISITION_DECLARATION,
    NETWORK_SWEEP_ACQUISITION_DECLARATION,
    TEMPERATURE_SAMPLE_DECLARATION,
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
from scopecat_instruments.symbolic import (
    DCMonitorProducts,
    NetworkSweepProducts,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicDCSourceMonitorClient,
    SymbolicDCSourceMonitorGroup,
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
class NetworkSweepReadback(
    NetworkSweepResults[MeasurementValue | None, MeasurementValue | None]
):
    """Named network-sweep results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)


@dataclass(frozen=True, slots=True)
class TemperatureReadback(TemperatureSampleResults[MeasurementValue | None]):
    """Named temperature-readout results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)


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

    def _collect_declared[DeclaredT, OutputT](
        self,
        acquisition: DeclaredAcquisition[DeclaredT],
        output_factory: Callable[..., OutputT],
    ) -> OutputT:
        requested_results = (
            ()
            if acquisition.discriminator is not None
            else tuple(field.ref for field in acquisition.active_result_fields())
        )
        receipt = self._session.collect(
            acquisition.ref,
            *requested_results,
            instrument_id=self.instrument_id,
        )
        readback = receipt.readback
        values = {
            field.python_name: (
                None if readback is None else readback.values.get(field.result_id)
            )
            for field in acquisition.result_fields
        }
        return output_factory(receipt=receipt, **values)


class _DeclaredStateClient[StateT](_InstrumentClient):
    def apply(self, patch: StateT) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )


class DCSourceClient(
    _DeclaredStateClient[DCSourceState | DCSourceVoltage | DCSourceCurrent]
):
    pass


class DCSourceMonitorClient(DCSourceClient):
    @override
    def apply(
        self,
        patch: DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState,
    ) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )

    def monitor(self) -> DCMonitorReadback:
        return self._collect_declared(
            DC_MONITOR_ACQUISITION_DECLARATION,
            DCMonitorReadback,
        )


class RFOutputClient(_DeclaredStateClient[RFOutputState]):
    pass


class NetworkSweepClient(_DeclaredStateClient[NetworkSweepState]):
    def sweep(self) -> NetworkSweepReadback:
        return self._collect_declared(
            NETWORK_SWEEP_ACQUISITION_DECLARATION,
            NetworkSweepReadback,
        )


class TemperatureReadoutClient(_InstrumentClient):
    def sample(self) -> TemperatureReadback:
        return self._collect_declared(
            TEMPERATURE_SAMPLE_DECLARATION,
            TemperatureReadback,
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


class _SymbolicClientFactory[ClientT](Protocol):
    def __call__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> ClientT: ...


class _SymbolicGroupFactory[GroupT](Protocol):
    def __call__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
    ) -> GroupT: ...


class _InstrumentFamily[LiveT, SymbolicT, GroupT]:
    """One typed factory shape shared by live, scalar, and grouped clients."""

    __slots__ = ("_group_factory", "_live_factory", "_requires", "_symbolic_factory")

    def __init__(
        self,
        live_factory: InstrumentClientFactory[LiveT],
        symbolic_factory: _SymbolicClientFactory[SymbolicT],
        group_factory: _SymbolicGroupFactory[GroupT],
        *,
        requires: tuple[InterfaceRef, ...],
    ) -> None:
        self._live_factory = live_factory
        self._symbolic_factory = symbolic_factory
        self._group_factory = group_factory
        self._requires = requires

    @overload
    def __call__(self, instrument_id: str) -> InstrumentRef[LiveT]: ...

    @overload
    def __call__(
        self,
        instrument_id: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
    ) -> GroupT: ...

    @overload
    def __call__(
        self,
        instrument_id: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> SymbolicT: ...

    def __call__(
        self,
        instrument_id: str | SymbolicInstrumentRecorder,
        resource_id: str | None = None,
        *,
        for_: EntitySelection | None = None,
    ) -> InstrumentRef[LiveT] | SymbolicT | GroupT:
        if isinstance(instrument_id, str):
            if resource_id is not None or for_ is not None:
                raise TypeError("live instrument clients only accept an instrument id")
            return instrument(
                instrument_id,
                self._live_factory,
                requires=self._requires,
            )
        if resource_id is None:
            raise TypeError("symbolic instrument clients require a logical resource id")
        if isinstance(for_, EachEntity):
            return self._group_factory(instrument_id, resource_id, for_=for_)
        return self._symbolic_factory(instrument_id, resource_id, for_=for_)


rf_output: _InstrumentFamily[
    RFOutputClient,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
] = _InstrumentFamily(
    RFOutputClient,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    requires=(RF_OUTPUT,),
)

network_sweep: _InstrumentFamily[
    NetworkSweepClient,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
] = _InstrumentFamily(
    NetworkSweepClient,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    requires=(NETWORK_SWEEP,),
)

temperature_readout: _InstrumentFamily[
    TemperatureReadoutClient,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
] = _InstrumentFamily(
    TemperatureReadoutClient,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    requires=(TEMPERATURE_READOUT,),
)


def _concrete_assignments(state: object) -> dict[PropertyRef, StateLiteral]:
    try:
        return {
            target: StateValue.model_validate(value).root
            for target, value in declared_state_assignments(state).items()
        }
    except ValueError as error:
        raise TypeError(
            "direct instrument state must contain concrete values"
        ) from error


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
    "TemperatureSampleProducts",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
]
