"""Typed instrument clients that record declarative module effects."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.authoring import (
    DefinitionResource,
    DesiredState,
    EachEntity,
    EntityType,
    OneEntity,
    PerEntity,
    ProductAxis,
    ProductRef,
    ScalarType,
    StateBinding,
    ValueRef,
    one,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.entity import EntityRef, entity_identity
from scopecat.measurements.results import MeasurementDType
from scopecat.program.value_refs import (
    internal_literal_value_ref,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)
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
from scopecat.sdk.instruments.declarations import declared_state_target

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
        scope: Sequence[str],
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
        for_entity: ValueRef | None = None,
    ) -> None:
        self._recorder = recorder
        self._resource = recorder.resource(
            resource_id,
            requires=requires,
            for_entities=() if for_entity is None else (for_entity,),
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
                _join_id(id, result.id),
                scope=(self.id,),
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

    __slots__ = ("_monitor_enabled",)

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
        monitor: bool = False,
    ) -> None:
        self._monitor_enabled = monitor
        super().__init__(
            recorder,
            resource_id,
            requires=(DC_SOURCE, DC_MONITOR) if monitor else (DC_SOURCE,),
            for_entity=_one_entity_value(for_),
        )

    def ensure(
        self,
        state: DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState,
    ) -> None:
        if isinstance(state, DCMonitorState) and not self._monitor_enabled:
            raise ValueError("DC monitor state requires dc_source(..., monitor=True)")
        self._ensure(state)

    def monitor(self, *, id: str | None = None) -> DCMonitorProducts:
        """Declare the result active for the most recently ensured source mode."""

        if not self._monitor_enabled:
            raise ValueError("DC monitoring requires dc_source(..., monitor=True)")
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
        for_: OneEntity | None = None,
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(RF_OUTPUT,),
            for_entity=_one_entity_value(for_),
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
        for_: OneEntity | None = None,
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(NETWORK_SWEEP,),
            for_entity=_one_entity_value(for_),
        )

    def ensure(self, state: NetworkSweepState) -> None:
        self._ensure(declared_state_target(state))

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
        for_: OneEntity | None = None,
    ) -> None:
        super().__init__(
            recorder,
            resource_id,
            requires=(TEMPERATURE_READOUT,),
            for_entity=_one_entity_value(for_),
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


class _SymbolicInstrumentGroup[ClientT: _SymbolicInstrumentClient]:
    __slots__ = ("_clients", "_entities", "_id")

    def __init__(
        self,
        resource_id: str,
        entities: EachEntity,
        clients: PerEntity[ClientT],
    ) -> None:
        self._id = resource_id
        self._entities = entities
        self._clients = clients

    @property
    def id(self) -> str:
        """The common authoring id before entity-specific namespacing."""

        return self._id

    @property
    def entities(self) -> tuple[EntityRef, ...]:
        """Concrete entities in declaration order."""

        return self._entities.entities

    @property
    def clients(self) -> PerEntity[ClientT]:
        """The scalar symbolic client for each exact entity identity."""

        return self._clients

    def __getitem__(self, entity: EntityRef) -> ClientT:
        """Select one scalar client by complete entity identity."""

        return self._clients[entity]

    @property
    def resources(self) -> PerEntity[DefinitionResource]:
        """The independently routable logical resource for each entity."""

        return self._clients.map(lambda client: client.resource)


type _DCSourceDesiredState = (
    DCSourceState | DCSourceVoltage | DCSourceCurrent | DCMonitorState
)


class SymbolicDCSourceGroup(_SymbolicInstrumentGroup[SymbolicDCSourceClient]):
    """Entity-keyed declarative DC-source clients with broadcast state."""

    __slots__ = ()

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
        monitor: bool = False,
    ) -> None:
        super().__init__(
            resource_id,
            for_,
            _fanout_clients(
                for_,
                lambda entity, child_id: SymbolicDCSourceClient(
                    recorder,
                    child_id,
                    for_=one(entity),
                    monitor=monitor,
                ),
                resource_id=resource_id,
            ),
        )

    def ensure[StateT: _DCSourceDesiredState](
        self,
        state: StateT | PerEntity[StateT],
    ) -> None:
        for entity, target in _align_per_entity(self._entities, state).items():
            self._clients[entity].ensure(target)

    def monitor(self, *, id: str | None = None) -> PerEntity[DCMonitorProducts]:
        return self._clients.map(lambda client: client.monitor(id=id))


class SymbolicRFOutputGroup(_SymbolicInstrumentGroup[SymbolicRFOutputClient]):
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
            resource_id,
            for_,
            _fanout_clients(
                for_,
                lambda entity, child_id: SymbolicRFOutputClient(
                    recorder,
                    child_id,
                    for_=one(entity),
                ),
                resource_id=resource_id,
            ),
        )

    def ensure(self, state: RFOutputState | PerEntity[RFOutputState]) -> None:
        for entity, target in _align_per_entity(self._entities, state).items():
            self._clients[entity].ensure(target)


class SymbolicNetworkSweepGroup(_SymbolicInstrumentGroup[SymbolicNetworkSweepClient]):
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
            resource_id,
            for_,
            _fanout_clients(
                for_,
                lambda entity, child_id: SymbolicNetworkSweepClient(
                    recorder,
                    child_id,
                    for_=one(entity),
                ),
                resource_id=resource_id,
            ),
        )

    def ensure(
        self,
        state: NetworkSweepState | PerEntity[NetworkSweepState],
    ) -> None:
        for entity, target in _align_per_entity(self._entities, state).items():
            self._clients[entity].ensure(target)

    def sweep(self, *, id: str | None = None) -> PerEntity[NetworkSweepProducts]:
        return self._clients.map(lambda client: client.sweep(id=id))


class SymbolicTemperatureReadoutGroup(
    _SymbolicInstrumentGroup[SymbolicTemperatureReadoutClient]
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
            resource_id,
            for_,
            _fanout_clients(
                for_,
                lambda entity, child_id: SymbolicTemperatureReadoutClient(
                    recorder,
                    child_id,
                    for_=one(entity),
                ),
                resource_id=resource_id,
            ),
        )

    def sample(
        self,
        *,
        id: str | None = None,
    ) -> PerEntity[TemperatureSampleProducts]:
        return self._clients.map(lambda client: client.sample(id=id))


def _fanout_clients[ClientT: _SymbolicInstrumentClient](
    entities: EachEntity,
    factory: Callable[[EntityRef, str], ClientT],
    *,
    resource_id: str,
) -> PerEntity[ClientT]:
    return PerEntity(
        (
            entity,
            factory(entity, f"{resource_id}.{_entity_token(entity)}"),
        )
        for entity in entities
    )


def _align_per_entity[ValueT](
    entities: EachEntity,
    value: ValueT | PerEntity[ValueT],
) -> PerEntity[ValueT]:
    if not isinstance(value, PerEntity):
        return PerEntity((entity, value) for entity in entities)

    selected = cast("PerEntity[ValueT]", value)
    expected = {entity_identity(entity) for entity in entities}
    actual = {entity_identity(entity) for entity in selected}
    if expected != actual:
        missing = sorted(expected - actual, key=_identity_sort_key)
        extra = sorted(actual - expected, key=_identity_sort_key)
        details: list[str] = []
        if missing:
            details.append(
                "missing "
                + ", ".join(_format_identity(identity) for identity in missing)
            )
        if extra:
            details.append(
                "extra " + ", ".join(_format_identity(identity) for identity in extra)
            )
        raise ValueError(
            "PerEntity state must exactly match group entities: " + "; ".join(details)
        )
    return PerEntity((entity, selected[entity]) for entity in entities)


def _one_entity_value(selection: OneEntity | None) -> ValueRef | None:
    if selection is None:
        return None
    entity = selection.entity
    if isinstance(entity, ValueRef):
        return entity
    return internal_literal_value_ref(
        entity,
        ScalarType(EntityType(entity_kind=entity.kind)),
        path=("for_", entity.id),
    )


def _entity_token(entity: EntityRef) -> str:
    identity = entity_identity(entity)
    readable = "-".join(part for part in identity if part is not None)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", readable).strip("-").lower()
    slug = slug[:40].rstrip("-") or "entity"
    digest = stable_content_hash({"kind": identity[0], "id": identity[1]})[:12]
    return f"{slug}-{digest}"


def _identity_sort_key(identity: tuple[str | None, str]) -> tuple[str, str]:
    return identity[0] or "", identity[1]


def _format_identity(identity: tuple[str | None, str]) -> str:
    kind, id = identity
    return f"{kind}:{id}" if kind is not None else id


def _join_id(namespace: str | None, id: str | None) -> str:
    if not namespace:
        return id or ""
    return f"{namespace}.{id}" if id else namespace


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
    if isinstance(value, ValueRef) and (
        internal_value_ref_point_dependencies(value)
        or internal_value_ref_requires_execution(value)
    ):
        raise ValueError(
            f"acquisition axis {axis.id!r} is sized by {size.property_id!r}; "
            "output-shaping state must resolve during configuration binding, "
            "before point execution"
        )
    return cast("int | ValueRef", value)


__all__ = [
    "DCMonitorProducts",
    "NetworkSweepProducts",
    "SymbolicDCSourceClient",
    "SymbolicDCSourceGroup",
    "SymbolicInstrumentRecorder",
    "SymbolicNetworkSweepClient",
    "SymbolicNetworkSweepGroup",
    "SymbolicRFOutputClient",
    "SymbolicRFOutputGroup",
    "SymbolicTemperatureReadoutClient",
    "SymbolicTemperatureReadoutGroup",
    "TemperatureSampleProducts",
]
