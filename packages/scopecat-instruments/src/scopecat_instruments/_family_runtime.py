"""Shared live/symbolic family dispatch for typed instrument clients."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, overload

from scopecat.api.instruments import (
    InstrumentClientFactory,
    InstrumentRef,
    instrument,
)
from scopecat.authoring import (
    EachEntity,
    EntitySelection,
    ExperimentContext,
    InstrumentRecorder,
    ModuleContext,
    OneEntity,
    ResourceRoleInput,
    instrument_recorder,
)
from scopecat.sdk.instruments import InstrumentCapabilityRef, InterfaceRef


class _SymbolicClientFactory[ClientT](Protocol):
    def __call__(
        self,
        recorder: InstrumentRecorder,
        resource_id: str,
        *,
        namespace_hint: str,
        requires: tuple[InstrumentCapabilityRef, ...],
        for_: OneEntity | None = None,
        role: ResourceRoleInput = None,
    ) -> ClientT: ...


class _SymbolicGroupFactory[GroupT](Protocol):
    def __call__(
        self,
        recorder: InstrumentRecorder,
        resource_id: str,
        *,
        namespace_hint: str,
        requires: tuple[InstrumentCapabilityRef, ...],
        for_: EachEntity,
        role: ResourceRoleInput = None,
    ) -> GroupT: ...


class InstrumentFamily[LiveT, SymbolicT, GroupT]:
    """One full-contract client family with fixed symbolic resource views.

    Generated families default to their complete interface contracts. Symbolic
    authoring may replace that default with an explicit member requirement set
    when a composition intentionally uses only a narrower capability view.
    """

    __slots__ = (
        "_group_factory",
        "_live_factory",
        "_name",
        "_requires",
        "_symbolic_factory",
    )

    def __init__(
        self,
        live_factory: InstrumentClientFactory[LiveT],
        symbolic_factory: _SymbolicClientFactory[SymbolicT],
        group_factory: _SymbolicGroupFactory[GroupT],
        *,
        name: str,
        requires: tuple[InterfaceRef, ...],
    ) -> None:
        self._live_factory = live_factory
        self._symbolic_factory = symbolic_factory
        self._group_factory = group_factory
        self._name = name
        self._requires = requires

    @overload
    def __call__(
        self,
        context_or_id: str,
        /,
        *,
        component_path: Sequence[str] = (),
    ) -> InstrumentRef[LiveT]: ...

    @overload
    def __call__(
        self,
        context_or_id: ExperimentContext | ModuleContext,
        /,
        *,
        for_: EachEntity,
        role: ResourceRoleInput = None,
        name: str | None = None,
        requires: Sequence[InstrumentCapabilityRef] | None = None,
    ) -> GroupT: ...

    @overload
    def __call__(
        self,
        context_or_id: ExperimentContext | ModuleContext,
        /,
        *,
        for_: OneEntity | None = None,
        role: ResourceRoleInput = None,
        name: str | None = None,
        requires: Sequence[InstrumentCapabilityRef] | None = None,
    ) -> SymbolicT: ...

    def __call__(
        self,
        context_or_id: str | ExperimentContext | ModuleContext,
        /,
        *,
        for_: EntitySelection | None = None,
        role: ResourceRoleInput = None,
        name: str | None = None,
        requires: Sequence[InstrumentCapabilityRef] | None = None,
        component_path: Sequence[str] = (),
    ) -> InstrumentRef[LiveT] | SymbolicT | GroupT:
        if isinstance(context_or_id, str):
            if (
                for_ is not None
                or role is not None
                or name is not None
                or requires is not None
            ):
                raise TypeError(
                    "live instrument clients accept only an instrument id and "
                    "component_path"
                )
            return instrument(
                context_or_id,
                self._live_factory,
                requires=self._requires,
                component_path=component_path,
            )
        if component_path:
            raise TypeError("symbolic instrument component paths come from routing")
        recorder = instrument_recorder(context_or_id)
        resource_name = self._name if name is None else name
        resource_id = recorder.allocate_resource_id(resource_name)
        selected_requirements = self._requires if requires is None else tuple(requires)
        if isinstance(for_, EachEntity):
            return self._group_factory(
                recorder,
                resource_id,
                namespace_hint=resource_name,
                requires=selected_requirements,
                for_=for_,
                role=role,
            )
        return self._symbolic_factory(
            recorder,
            resource_id,
            namespace_hint=resource_name,
            requires=selected_requirements,
            for_=for_,
            role=role,
        )


__all__ = ["InstrumentFamily"]
