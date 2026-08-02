"""Shared live/symbolic family dispatch for typed instrument clients."""

from __future__ import annotations

from typing import Protocol, overload

from scopecat.api._instruments import (
    InstrumentClientFactory,
    InstrumentRef,
    instrument,
)
from scopecat.authoring import EachEntity, EntitySelection, OneEntity
from scopecat.sdk.instruments import InterfaceRef

from scopecat_instruments._symbolic_runtime import SymbolicInstrumentRecorder


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


__all__ = ["InstrumentFamily"]
