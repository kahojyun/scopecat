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
    FinalizationTarget,
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
    AcquisitionResultRef,
    InterfaceRef,
    PropertyRef,
    StatePropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    declared_state_target,
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

type _DCSourceState = DCSourceState | DCSourceVoltage | DCSourceCurrent
type _DCSourceMonitorState = _DCSourceState | DCMonitorState


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
class NetworkSweepProducts(NetworkSweepResults[ProductRef, ProductRef]):
    """Typed logical products produced by one declarative network sweep."""


@dataclass(frozen=True, slots=True)
class DCMonitorProducts:
    """Mode-dependent logical products produced by one DC monitor sample."""

    current: ProductRef | None
    voltage: ProductRef | None


@dataclass(frozen=True, slots=True)
class TemperatureSampleProducts(TemperatureSampleResults[ProductRef]):
    """Typed logical products produced by one temperature sample."""


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

    def _acquire_declared[DeclaredT, OutputT](
        self,
        acquisition: DeclaredAcquisition[DeclaredT],
        output_factory: Callable[..., OutputT],
        *,
        id: str | None,
    ) -> OutputT:
        case_value: str | None = None
        if acquisition.discriminator is not None:
            selected_case = self._state_assignments.get(acquisition.discriminator)
            if not isinstance(selected_case, str):
                raise ValueError(
                    f"acquisition {acquisition.spec.id!r} has state-dependent "
                    "results; ensure a concrete discriminator state before "
                    "declaring it"
                )
            case_value = selected_case
        active_fields = acquisition.active_result_fields(case_value)
        occurrence_id = acquisition.spec.id if id is None else id
        if not occurrence_id:
            raise ValueError("symbolic acquisition id must be non-empty")
        effect_id = f"{self.id}.{occurrence_id}"
        products = {
            field.python_name: self._recorder.product(
                _join_id(id, field.result_id),
                scope=(self.id,),
                unit=field.spec.unit,
                dtype=field.spec.dtype,
                axes=_product_axes(
                    field.spec.axes,
                    state_assignments=self._state_assignments,
                    namespace=id,
                ),
            )
            for field in active_fields
        }
        self._recorder.acquire(
            effect_id,
            resource=self._resource,
            results={field.ref: products[field.python_name] for field in active_fields},
        )
        values: dict[str, ProductRef | None] = {
            field.python_name: None for field in acquisition.result_fields
        }
        values.update(products)
        return output_factory(**values)


class _DeclaredStateSymbolicClient[StateT](_SymbolicInstrumentClient):
    def ensure(self, state: StateT) -> None:
        self._ensure(self._desired_state_target(state))

    def finalization_targets(
        self,
        state: StateT,
        /,
    ) -> tuple[FinalizationTarget, ...]:
        return ((self.resource, self._desired_state_target(state)),)

    def _desired_state_target(self, state: StateT) -> DesiredState:
        return declared_state_target(state)


class SymbolicDCSourceClient(_DeclaredStateSymbolicClient[_DCSourceState]):
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
            for_entity=_one_entity_value(for_),
        )


class SymbolicDCSourceMonitorClient(
    _DeclaredStateSymbolicClient[_DCSourceMonitorState]
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
            for_entity=_one_entity_value(for_),
        )

    def monitor(self, *, id: str | None = None) -> DCMonitorProducts:
        """Declare the result active for the most recently ensured source mode."""

        return self._acquire_declared(
            DC_MONITOR_ACQUISITION_DECLARATION,
            DCMonitorProducts,
            id=id,
        )


class SymbolicRFOutputClient(_DeclaredStateSymbolicClient[RFOutputState]):
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


class SymbolicNetworkSweepClient(_DeclaredStateSymbolicClient[NetworkSweepState]):
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

    def sweep(self, *, id: str | None = None) -> NetworkSweepProducts:
        """Declare a sweep and derive its product schemas from the interface."""

        return self._acquire_declared(
            NETWORK_SWEEP_ACQUISITION_DECLARATION,
            NetworkSweepProducts,
            id=id,
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

        return self._acquire_declared(
            TEMPERATURE_SAMPLE_DECLARATION,
            TemperatureSampleProducts,
            id=id,
        )


class _SymbolicClientFactory[ClientT: _SymbolicInstrumentClient](Protocol):
    def __call__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> ClientT: ...


class _SymbolicInstrumentGroup[ClientT: _SymbolicInstrumentClient]:
    __slots__ = ("_clients", "_entities", "_id")

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
        client_factory: _SymbolicClientFactory[ClientT],
    ) -> None:
        self._id = resource_id
        self._entities = for_
        self._clients = PerEntity(
            (
                entity,
                client_factory(
                    recorder,
                    f"{resource_id}.{_entity_token(entity)}",
                    for_=one(entity),
                ),
            )
            for entity in for_
        )

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


class _DeclaredStateSymbolicGroup[
    StateT,
    ClientT: _SymbolicInstrumentClient,
](_SymbolicInstrumentGroup[ClientT]):
    def ensure(self, state: StateT | PerEntity[StateT]) -> None:
        for entity, target in self._entities.align(state).items():
            self._state_client(entity).ensure(target)

    def finalization_targets(
        self,
        state: StateT | PerEntity[StateT],
        /,
    ) -> tuple[FinalizationTarget, ...]:
        return tuple(
            target
            for entity, state_for_entity in self._entities.align(state).items()
            for target in self._state_client(entity).finalization_targets(
                state_for_entity
            )
        )

    def _state_client(
        self,
        entity: EntityRef,
    ) -> _DeclaredStateSymbolicClient[StateT]:
        return cast("_DeclaredStateSymbolicClient[StateT]", self._clients[entity])


class SymbolicDCSourceGroup(
    _DeclaredStateSymbolicGroup[_DCSourceState, SymbolicDCSourceClient]
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
    _DeclaredStateSymbolicGroup[
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
    _DeclaredStateSymbolicGroup[RFOutputState, SymbolicRFOutputClient]
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
    _DeclaredStateSymbolicGroup[NetworkSweepState, SymbolicNetworkSweepClient]
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


def _join_id(namespace: str | None, id: str | None) -> str:
    if not namespace:
        return id or ""
    return f"{namespace}.{id}" if id else namespace


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
