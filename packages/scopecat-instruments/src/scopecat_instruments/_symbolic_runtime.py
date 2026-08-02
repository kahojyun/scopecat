"""Shared symbolic-client runtime used by generated instrument families."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
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
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
    StatePropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredOperation,
    declared_state_target,
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

    def invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, StateBinding] | None = None,
    ) -> None: ...

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


class SymbolicInstrumentClientBase:
    __slots__ = ("_recorder", "_resource", "_state_assignments")

    def __init__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        requires: Sequence[InterfaceRef],
        for_: OneEntity | None = None,
    ) -> None:
        self._recorder = recorder
        self._resource = recorder.resource(
            resource_id,
            requires=requires,
            for_entities=(
                () if (for_entity := _one_entity_value(for_)) is None else (for_entity,)
            ),
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

    def _invoke_declared[**P](
        self,
        operation: DeclaredOperation[P],
        effect_id: str | None,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        occurrence_id = operation.spec.id if effect_id is None else effect_id
        if not occurrence_id:
            raise ValueError("symbolic operation effect id must be non-empty")
        self._recorder.invoke(
            f"{self.id}.{occurrence_id}",
            resource=self._resource,
            operation=operation.ref,
            arguments=cast(
                "Mapping[OperationArgumentRef, StateBinding]",
                operation.lower_arguments(*args, **kwargs),
            ),
        )
        self._state_assignments.clear()

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


class SymbolicInstrumentComponentClientBase(SymbolicInstrumentClientBase):
    """A component proxy sharing one symbolic root client's authoring state."""

    __slots__ = ("_owner",)

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        owner: SymbolicInstrumentClientBase,
        /,
    ) -> None:
        self._owner = owner
        self._recorder = owner._recorder
        self._resource = owner._resource
        self._state_assignments = owner._state_assignments


class DeclaredStateSymbolicClientBase[StateT](SymbolicInstrumentClientBase):
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


class _SymbolicClientFactory[ClientT: SymbolicInstrumentClientBase](Protocol):
    def __call__(
        self,
        recorder: SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> ClientT: ...


class SymbolicInstrumentGroupBase[ClientT: SymbolicInstrumentClientBase]:
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

    def _align[ValueT](
        self,
        value: ValueT | PerEntity[ValueT],
        /,
    ) -> PerEntity[ValueT]:
        return self._entities.align(value)


class SymbolicInstrumentComponentGroupBase[ComponentT]:
    """Entity-aligned scalar component proxies for one generated group."""

    __slots__ = ("_clients", "_entities")

    def __init__(
        self,
        entities: EachEntity,
        clients: PerEntity[ComponentT],
        /,
    ) -> None:
        self._entities = entities
        self._clients = entities.align(clients)

    @property
    def entities(self) -> tuple[EntityRef, ...]:
        return self._entities.entities

    @property
    def clients(self) -> PerEntity[ComponentT]:
        return self._clients

    def __getitem__(self, entity: EntityRef) -> ComponentT:
        return self._clients[entity]

    def _align[ValueT](
        self,
        value: ValueT | PerEntity[ValueT],
        /,
    ) -> PerEntity[ValueT]:
        return self._entities.align(value)


class DeclaredStateSymbolicGroupBase[
    StateT,
    ClientT: SymbolicInstrumentClientBase,
](SymbolicInstrumentGroupBase[ClientT]):
    def ensure(self, state: StateT | PerEntity[StateT]) -> None:
        for entity, target in self._align(state).items():
            self._state_client(entity).ensure(target)

    def finalization_targets(
        self,
        state: StateT | PerEntity[StateT],
        /,
    ) -> tuple[FinalizationTarget, ...]:
        return tuple(
            target
            for entity, state_for_entity in self._align(state).items()
            for target in self._state_client(entity).finalization_targets(
                state_for_entity
            )
        )

    def _state_client(
        self,
        entity: EntityRef,
    ) -> DeclaredStateSymbolicClientBase[StateT]:
        return cast(
            "DeclaredStateSymbolicClientBase[StateT]",
            self._clients[entity],
        )


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
    "DeclaredStateSymbolicClientBase",
    "DeclaredStateSymbolicGroupBase",
    "SymbolicInstrumentClientBase",
    "SymbolicInstrumentComponentClientBase",
    "SymbolicInstrumentComponentGroupBase",
    "SymbolicInstrumentGroupBase",
    "SymbolicInstrumentRecorder",
]
