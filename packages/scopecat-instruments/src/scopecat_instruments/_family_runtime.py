"""Shared live/symbolic family dispatch for typed instrument clients."""

from __future__ import annotations

from typing import Protocol, cast, overload

from scopecat.api._instruments import (
    InstrumentClientFactory,
    InstrumentRef,
    instrument,
)
from scopecat.authoring import (
    EachEntity,
    EntitySelection,
    ExperimentContext,
    ModuleContext,
    OneEntity,
)
from scopecat.sdk.instruments import InterfaceRef

from scopecat_instruments._symbolic_runtime import _SymbolicInstrumentRecorder

# pyright: reportPrivateUsage=false


class _SymbolicClientFactory[ClientT](Protocol):
    def __call__(
        self,
        recorder: _SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: OneEntity | None = None,
    ) -> ClientT: ...


class _SymbolicGroupFactory[GroupT](Protocol):
    def __call__(
        self,
        recorder: _SymbolicInstrumentRecorder,
        resource_id: str,
        *,
        for_: EachEntity,
    ) -> GroupT: ...


class InstrumentFamily[LiveT, SymbolicT, GroupT]:
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
    def __call__(self, context_or_id: str, /) -> InstrumentRef[LiveT]: ...

    @overload
    def __call__(
        self,
        context_or_id: ExperimentContext | ModuleContext,
        id: str,
        /,
        *,
        for_: EachEntity,
    ) -> GroupT: ...

    @overload
    def __call__(
        self,
        context_or_id: ExperimentContext | ModuleContext,
        id: str,
        /,
        *,
        for_: OneEntity | None = None,
    ) -> SymbolicT: ...

    def __call__(
        self,
        context_or_id: str | ExperimentContext | ModuleContext,
        id: str | None = None,
        /,
        *,
        for_: EntitySelection | None = None,
    ) -> InstrumentRef[LiveT] | SymbolicT | GroupT:
        if isinstance(context_or_id, str):
            if id is not None or for_ is not None:
                raise TypeError("live instrument clients only accept an instrument id")
            return instrument(
                context_or_id,
                self._live_factory,
                requires=self._requires,
            )
        if id is None:
            raise TypeError("symbolic instrument clients require a logical resource id")
        recorder = cast("_SymbolicInstrumentRecorder", context_or_id)
        if isinstance(for_, EachEntity):
            return self._group_factory(recorder, id, for_=for_)
        return self._symbolic_factory(recorder, id, for_=for_)


__all__ = ["InstrumentFamily"]
