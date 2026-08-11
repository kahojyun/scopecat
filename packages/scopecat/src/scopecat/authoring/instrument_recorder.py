"""Supported recorder boundary for generated instrument clients."""

# This module is the only public adapter around context recorder internals.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from scopecat.authoring._module_context import DefinitionResource
from scopecat.kernel.resource_identity import ResourceRoleInput
from scopecat.program.measurement_types import MeasurementDType
from scopecat.program.products import ProductAxis, ProductRecording, ProductRef
from scopecat.program.state import StateBinding
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.members import (
    AcquisitionResultRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)


class _RecorderTarget(Protocol):
    def _allocate_resource_id(self, name_hint: str) -> str: ...

    def _allocate_effect_id(
        self,
        name_hint: str,
        *,
        explicit: bool = False,
    ) -> str: ...

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

    def _ensure_many(
        self,
        targets: Sequence[
            tuple[DefinitionResource, Mapping[PropertyRef, StateBinding]]
        ],
    ) -> None: ...

    def _invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, StateBinding] | None = None,
    ) -> None: ...

    def _product(
        self,
        id: str,
        *,
        scope: Sequence[str],
        unit: str | None,
        dtype: MeasurementDType,
        axes: Sequence[ProductAxis],
        recording: ProductRecording | None,
    ) -> ProductRef: ...

    def _acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
    ) -> None: ...


type InstrumentResource = DefinitionResource
type InstrumentStateTarget = tuple[
    InstrumentResource,
    Mapping[PropertyRef, StateBinding],
]


class InstrumentRecorder:
    """Public generated-client view over an experiment authoring context.

    Extension packages use this narrow surface instead of depending on the
    private storage and graph-building methods of ``ModuleContext`` and
    ``ExperimentContext``.
    """

    __slots__ = ("_target",)

    def __init__(self, target: object, /) -> None:
        self._target = cast("_RecorderTarget", target)

    def allocate_resource_id(self, name_hint: str) -> str:
        return self._target._allocate_resource_id(name_hint)

    def allocate_effect_id(
        self,
        name_hint: str,
        *,
        explicit: bool = False,
    ) -> str:
        return self._target._allocate_effect_id(name_hint, explicit=explicit)

    def resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef],
        for_entities: Sequence[ValueRef],
        role: ResourceRoleInput = None,
    ) -> InstrumentResource:
        return self._target._resource(
            id,
            requires=requires,
            for_entities=for_entities,
            role=role,
        )

    def ensure(
        self,
        resource: InstrumentResource,
        assignments: Mapping[PropertyRef, StateBinding],
    ) -> None:
        self._target._ensure(resource, assignments)

    def ensure_many(self, targets: Sequence[InstrumentStateTarget]) -> None:
        self._target._ensure_many(targets)

    def invoke(
        self,
        id: str,
        *,
        resource: InstrumentResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, StateBinding] | None = None,
    ) -> None:
        self._target._invoke(
            id,
            resource=resource,
            operation=operation,
            arguments=arguments,
        )

    def product(
        self,
        id: str,
        *,
        scope: Sequence[str],
        unit: str | None,
        dtype: MeasurementDType,
        axes: Sequence[ProductAxis],
        recording: ProductRecording | None,
    ) -> ProductRef:
        return self._target._product(
            id,
            scope=scope,
            unit=unit,
            dtype=dtype,
            axes=axes,
            recording=recording,
        )

    def acquire(
        self,
        id: str,
        *,
        resource: InstrumentResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
    ) -> None:
        self._target._acquire(id, resource=resource, results=results)


def instrument_recorder(context: object, /) -> InstrumentRecorder:
    """Adapt one authoring context to the supported instrument extension API."""

    return InstrumentRecorder(context)


__all__ = [
    "InstrumentRecorder",
    "InstrumentResource",
    "InstrumentStateTarget",
    "instrument_recorder",
]
