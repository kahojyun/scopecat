"""Public building blocks for lab-owned capability compositions."""

# This module is the sanctioned boundary around context recorder internals.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast, overload

from scopecat.authoring._module_context import DefinitionResource
from scopecat.authoring.entity_selection import EachEntity, OneEntity, PerEntity, one
from scopecat.authoring.member_projection import StateTarget
from scopecat.kernel.resource_identity import ResourceRoleInput
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.program.products import ProductRef
from scopecat.program.state import StateBinding
from scopecat.program.value_refs import ValueRef, internal_literal_value_ref
from scopecat.program.values import ComputeInput
from scopecat.sdk.instruments.members import (
    AcquisitionResultRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)


class _CapabilityRecorder(Protocol):
    def _allocate_resource_id(self, name_hint: str) -> str: ...

    def _allocate_effect_id(self, name_hint: str, *, explicit: bool = False) -> str: ...

    def _resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef],
        for_entities: Sequence[ValueRef],
        role: ResourceRoleInput = None,
    ) -> DefinitionResource: ...

    def _ensure(
        self,
        resource: DefinitionResource,
        assignments: Mapping[PropertyRef, StateBinding],
    ) -> None: ...

    def _ensure_many(self, targets: Sequence[StateTarget]) -> None: ...

    def _invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, ComputeInput] | None = None,
    ) -> None: ...

    def _acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
    ) -> None: ...


class CapabilityResource:
    """A logical resource used to compose lab-owned capability facades.

    Generated clients remain the convenient interface-specific frontend. This
    lower-level object is for small lab extensions that combine several
    interfaces without importing a generator's private recorder runtime.
    """

    __slots__ = ("_namespace_hint", "_recorder", "_resource")

    def __init__(
        self,
        recorder: _CapabilityRecorder,
        resource: DefinitionResource,
        *,
        namespace_hint: str,
    ) -> None:
        self._recorder = recorder
        self._resource = resource
        self._namespace_hint = namespace_hint

    @property
    def id(self) -> str:
        return self._resource.id

    def state_target(
        self,
        assignments: Mapping[PropertyRef, StateBinding],
    ) -> StateTarget:
        """Return a target suitable for one coherent multi-resource ensure."""

        return self._resource, assignments

    def ensure(self, assignments: Mapping[PropertyRef, StateBinding]) -> None:
        """Declare persistent state for this logical resource."""

        self._recorder._ensure(self._resource, assignments)

    def invoke(
        self,
        operation: OperationRef,
        *,
        arguments: Mapping[OperationArgumentRef, ComputeInput] | None = None,
        id: str | None = None,
    ) -> None:
        """Append one atomic operation owned by this logical resource."""

        occurrence_name = operation.operation_id if id is None else id
        if not occurrence_name:
            raise ValueError("capability operation id must be non-empty")
        occurrence_id = self._recorder._allocate_effect_id(
            f"{self._namespace_hint}.{occurrence_name}",
            explicit=id is not None,
        )
        self._recorder._invoke(
            occurrence_id,
            resource=self._resource,
            operation=operation,
            arguments=arguments,
        )

    def acquire(
        self,
        results: Mapping[AcquisitionResultRef, ProductRef],
        *,
        id: str | None = None,
    ) -> None:
        """Append one acquisition owned by this logical resource."""

        if not results:
            raise ValueError("capability acquisition requires at least one result")
        [first, *_rest] = results
        occurrence_name = first.acquisition.acquisition_id if id is None else id
        if not occurrence_name:
            raise ValueError("capability acquisition id must be non-empty")
        occurrence_id = self._recorder._allocate_effect_id(
            f"{self._namespace_hint}.{occurrence_name}",
            explicit=id is not None,
        )
        self._recorder._acquire(
            occurrence_id,
            resource=self._resource,
            results=results,
        )


@overload
def capability_resource(
    context: object,
    name: str,
    *,
    requires: Sequence[InterfaceRef],
    for_: EachEntity,
    role: ResourceRoleInput = None,
) -> PerEntity[CapabilityResource]: ...


@overload
def capability_resource(
    context: object,
    name: str,
    *,
    requires: Sequence[InterfaceRef],
    for_: OneEntity | None = None,
    role: ResourceRoleInput = None,
) -> CapabilityResource: ...


def capability_resource(
    context: object,
    name: str,
    *,
    requires: Sequence[InterfaceRef],
    for_: OneEntity | EachEntity | None = None,
    role: ResourceRoleInput = None,
) -> CapabilityResource | PerEntity[CapabilityResource]:
    """Declare one capability resource, or one identity-keyed resource per entity."""

    recorder = cast("_CapabilityRecorder", context)
    resource_id = recorder._allocate_resource_id(name)
    if isinstance(for_, EachEntity):
        return PerEntity(
            (
                entity,
                _declare_capability_resource(
                    recorder,
                    f"{resource_id}.{entity.id}",
                    namespace_hint=f"{name}.{entity.id}",
                    requires=requires,
                    for_=one(entity),
                    role=role,
                ),
            )
            for entity in for_
        )
    return _declare_capability_resource(
        recorder,
        resource_id,
        namespace_hint=name,
        requires=requires,
        for_=for_,
        role=role,
    )


def ensure_state_targets(
    context: object,
    targets: Sequence[StateTarget],
) -> None:
    """Declare one coherent desired state across lab-composed resources."""

    cast("_CapabilityRecorder", context)._ensure_many(targets)


def _declare_capability_resource(
    recorder: _CapabilityRecorder,
    resource_id: str,
    *,
    namespace_hint: str,
    requires: Sequence[InterfaceRef],
    for_: OneEntity | None,
    role: ResourceRoleInput,
) -> CapabilityResource:
    entity = _one_entity_value(for_)
    resource = recorder._resource(
        resource_id,
        requires=requires,
        for_entities=() if entity is None else (entity,),
        role=role,
    )
    return CapabilityResource(
        recorder,
        resource,
        namespace_hint=namespace_hint,
    )


def _one_entity_value(selection: OneEntity | None) -> ValueRef | None:
    if selection is None:
        return None
    entity = selection.entity
    if isinstance(entity, ValueRef):
        return entity
    selected = entity
    return internal_literal_value_ref(
        selected,
        Scalar(Entity(entity_kind=selected.kind)),
        path=("for_", selected.id),
    )


__all__ = [
    "CapabilityResource",
    "capability_resource",
    "ensure_state_targets",
]
