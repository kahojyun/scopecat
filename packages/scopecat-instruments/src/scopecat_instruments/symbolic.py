"""Typed instrument clients that record declarative module effects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.authoring import (
    DefinitionResource,
    DesiredState,
    ProductAxis,
    ProductRef,
    StateBinding,
    ValueRef,
)
from scopecat.measurements.results import MeasurementDType
from scopecat.sdk.instruments import (
    AcquisitionAxisSpec,
    AcquisitionRef,
    AcquisitionResultRef,
    AcquisitionSpec,
    ComponentSpec,
    InterfaceRef,
    InterfaceSpec,
    PropertyRef,
    StateDiscriminatedAcquisitionSpec,
    StatePropertyRef,
    acquisition_results,
)

from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    network_sweep_interface,
    temperature_readout_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_ACQUISITION,
    DC_SOURCE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_ACQUISITION,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_SAMPLE,
)
from scopecat_instruments.states import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
    RFOutputState,
)


class SymbolicInstrumentRecorder(Protocol):
    """The authoring operations needed by symbolic instrument clients.

    ``ModuleContext`` and ``ExperimentContext`` satisfy this protocol without
    making this package depend on either concrete context type.
    """

    def resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef],
        for_entities: Sequence[ValueRef],
    ) -> DefinitionResource: ...

    def ensure(self, resource: DefinitionResource, target: DesiredState) -> None: ...

    def product(
        self,
        id: str,
        *,
        unit: str | None,
        dtype: MeasurementDType,
        axes: Sequence[ProductAxis],
    ) -> ProductRef: ...

    def acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NetworkSweepProducts:
    """Typed logical products produced by one declarative network sweep."""

    frequency: ProductRef
    s_parameter: ProductRef


@dataclass(frozen=True, slots=True)
class DCMonitorProducts:
    """Mode-dependent logical products produced by one DC monitor sample."""

    current: ProductRef | None
    voltage: ProductRef | None


@dataclass(frozen=True, slots=True)
class TemperatureSampleProducts:
    """Typed logical products produced by one temperature sample."""

    temperature: ProductRef
    resistance: ProductRef


class _SymbolicInstrumentClient:
    __slots__ = ("_recorder", "_resource", "_state_assignments")

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        requires: Sequence[InterfaceRef],
        for_entities: Sequence[ValueRef] = (),
    ) -> None:
        self._recorder = recorder
        self._resource = recorder.resource(
            resource_id,
            requires=requires,
            for_entities=for_entities,
        )
        self._state_assignments: dict[PropertyRef, StateBinding] = {}

    @property
    def resource(self) -> DefinitionResource:
        """The logical resource declared for this typed client."""

        return self._resource

    @property
    def id(self) -> str:
        return self._resource.id

    def _ensure(self, target: DesiredState) -> None:
        assignments = target.target_assignments()
        self._recorder.ensure(self._resource, target)
        self._state_assignments.update(assignments)

    def _acquire(
        self,
        *,
        interface: InterfaceSpec,
        acquisition: AcquisitionRef,
        id: str | None,
        result_ids: Sequence[str] | None = None,
    ) -> dict[str, ProductRef]:
        acquisition_spec = _find_acquisition(interface, acquisition)
        occurrence_id = acquisition_spec.id if id is None else id
        if not occurrence_id:
            raise ValueError("symbolic acquisition id must be non-empty")
        effect_id = f"{self.id}.{occurrence_id}"
        selected_results = (
            acquisition_results(acquisition_spec)
            if result_ids is None
            else tuple(
                result
                for result in acquisition_results(acquisition_spec)
                if result.id in result_ids
            )
        )
        products = {
            result.id: self._recorder.product(
                result.id if id is None else f"{id}.{result.id}",
                unit=result.unit,
                dtype=result.dtype,
                axes=_product_axes(
                    result.axes,
                    state_assignments=self._state_assignments,
                    namespace=id,
                ),
            )
            for result in selected_results
        }
        self._recorder.acquire(
            effect_id,
            resource=self._resource,
            results={
                acquisition.result(result_id): product
                for result_id, product in products.items()
            },
        )
        return products


class SymbolicDCSourceClient(_SymbolicInstrumentClient):
    """Declarative DC-source state client backed by a logical resource."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_entities: Sequence[ValueRef] = (),
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(DC_SOURCE, DC_MONITOR),
            for_entities=for_entities,
        )

    def ensure(
        self,
        state: DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState,
    ) -> None:
        self._ensure(state)

    def monitor(self, *, id: str | None = None) -> DCMonitorProducts:
        """Declare the result active for the most recently ensured source mode."""

        interface = dc_monitor_interface()
        acquisition = _find_acquisition(interface, DC_MONITOR_ACQUISITION)
        result_ids = _active_result_ids(
            acquisition,
            state_assignments=self._state_assignments,
        )
        products = self._acquire(
            interface=interface,
            acquisition=DC_MONITOR_ACQUISITION,
            id=id,
            result_ids=result_ids,
        )
        return DCMonitorProducts(
            current=products.get("monitored_current"),
            voltage=products.get("monitored_voltage"),
        )


class SymbolicRFOutputClient(_SymbolicInstrumentClient):
    """Declarative RF-output state client backed by a logical resource."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_entities: Sequence[ValueRef] = (),
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(RF_OUTPUT,),
            for_entities=for_entities,
        )

    def ensure(self, state: RFOutputState) -> None:
        self._ensure(state)


class SymbolicNetworkSweepClient(_SymbolicInstrumentClient):
    """Declarative network-analyzer state and acquisition client."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_entities: Sequence[ValueRef] = (),
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(NETWORK_SWEEP,),
            for_entities=for_entities,
        )

    def ensure(self, state: NetworkSweepState) -> None:
        self._ensure(state)

    def sweep(self, *, id: str | None = None) -> NetworkSweepProducts:
        """Declare a sweep and derive its product schemas from the interface."""

        products = self._acquire(
            interface=network_sweep_interface(),
            acquisition=NETWORK_SWEEP_ACQUISITION,
            id=id,
        )
        return NetworkSweepProducts(
            frequency=products["frequency"],
            s_parameter=products["s_parameter"],
        )


class SymbolicTemperatureReadoutClient(_SymbolicInstrumentClient):
    """Declarative temperature acquisition client."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_entities: Sequence[ValueRef] = (),
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(TEMPERATURE_READOUT,),
            for_entities=for_entities,
        )

    def sample(self, *, id: str | None = None) -> TemperatureSampleProducts:
        """Declare a sample and derive its products from the interface."""

        products = self._acquire(
            interface=temperature_readout_interface(),
            acquisition=TEMPERATURE_READOUT_SAMPLE,
            id=id,
        )
        return TemperatureSampleProducts(
            temperature=products["temperature"],
            resistance=products["resistance"],
        )


def _find_acquisition(
    interface: InterfaceSpec,
    target: AcquisitionRef,
) -> AcquisitionSpec:
    if interface.id != target.interface_id:
        raise ValueError(
            f"acquisition interface {target.interface_id!r} does not match "
            f"contract {interface.id!r}"
        )
    component: InterfaceSpec | ComponentSpec = interface
    for component_id in target.component_path:
        component = next(
            item for item in component.components if item.id == component_id
        )
    return next(
        item for item in component.acquisitions if item.id == target.acquisition_id
    )


def _product_axes(
    axes: Sequence[AcquisitionAxisSpec],
    *,
    state_assignments: Mapping[PropertyRef, StateBinding],
    namespace: str | None,
) -> tuple[ProductAxis, ...]:
    return tuple(
        ProductAxis(
            id=axis.id,
            size=_product_axis_size(axis, state_assignments=state_assignments),
            kind=axis.kind,
            unit=axis.unit,
            shared_as=axis.id if namespace is None else f"{namespace}.{axis.id}",
        )
        for axis in axes
    )


def _active_result_ids(
    acquisition: AcquisitionSpec,
    *,
    state_assignments: Mapping[PropertyRef, StateBinding],
) -> tuple[str, ...]:
    if not isinstance(acquisition, StateDiscriminatedAcquisitionSpec):
        return tuple(result.id for result in acquisition_results(acquisition))
    discriminator = acquisition.discriminator
    property = PropertyRef(
        discriminator.interface_id,
        tuple(discriminator.component_path),
        discriminator.property_id,
    )
    mode = state_assignments.get(property)
    if not isinstance(mode, str):
        raise ValueError(
            f"acquisition {acquisition.id!r} has state-dependent results; "
            "ensure a concrete discriminator state before declaring it"
        )
    selected_case = next(
        (case for case in acquisition.cases if case.value == mode),
        None,
    )
    if selected_case is None:
        raise ValueError(f"acquisition {acquisition.id!r} has no state case {mode!r}")
    return tuple(result.id for result in selected_case.results)


def _product_axis_size(
    axis: AcquisitionAxisSpec,
    *,
    state_assignments: Mapping[PropertyRef, StateBinding],
) -> int | ValueRef:
    size = axis.size
    if not isinstance(size, StatePropertyRef):
        return size
    property = PropertyRef(
        size.interface_id,
        tuple(size.component_path),
        size.property_id,
    )
    try:
        value = state_assignments[property]
    except KeyError:
        raise ValueError(
            f"acquisition axis {axis.id!r} is sized by {size.property_id!r}; "
            "ensure that state before declaring the acquisition"
        ) from None
    return cast("int | ValueRef", value)


__all__ = [
    "DCMonitorProducts",
    "NetworkSweepProducts",
    "SymbolicDCSourceClient",
    "SymbolicInstrumentRecorder",
    "SymbolicNetworkSweepClient",
    "SymbolicRFOutputClient",
    "SymbolicTemperatureReadoutClient",
    "TemperatureSampleProducts",
]
