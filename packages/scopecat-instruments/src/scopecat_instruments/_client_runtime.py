"""Shared live-client runtime used by generated instrument families."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.api._instruments import (
    InstrumentClientChannel,
    OperationArgumentValue,
)
from scopecat.daemon.wire import InstrumentConfiguredDefaultsApplyReceipt
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    InstrumentDescription,
    InvokeReceipt,
    OperationArgumentRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredOperation,
    state_projection_assignments,
)


@dataclass(frozen=True, slots=True)
class InstrumentClientBase:
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

    def _apply_declared(self, patch: object, /) -> ApplyReceipt:
        return self._session.apply(
            _concrete_assignments(patch),
            instrument_id=self.instrument_id,
        )

    def _invoke_declared[**P](
        self,
        operation: DeclaredOperation[P],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> InvokeReceipt:
        return self._session.invoke(
            operation.ref,
            cast(
                "Mapping[OperationArgumentRef, OperationArgumentValue]",
                operation.lower_arguments(*args, **kwargs),
            ),
            instrument_id=self.instrument_id,
        )

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


class InstrumentComponentClientBase(InstrumentClientBase):
    """A component proxy sharing one live root client's session target."""

    __slots__ = ("_owner",)
    _owner: InstrumentClientBase

    def __init__(self, owner: InstrumentClientBase, /) -> None:
        super().__init__(owner._session, owner.instrument_id)
        self._owner = owner


class DeclaredStateClientBase[StateT](InstrumentClientBase):
    def apply(self, patch: StateT) -> ApplyReceipt:
        return self._apply_declared(patch)

    def _apply_projected(
        self,
        patch: StateT | None,
        projection_factory: Callable[..., StateT],
        fields: Mapping[str, object],
        /,
    ) -> ApplyReceipt:
        if patch is not None and fields:
            raise TypeError("apply accepts either a patch or keyword fields")
        projected = projection_factory(**fields) if patch is None else patch
        return self._apply_declared(projected)


def _concrete_assignments(state: object) -> dict[PropertyRef, StateLiteral]:
    try:
        return {
            target: StateValue.model_validate(value).root
            for target, value in state_projection_assignments(state).items()
        }
    except ValueError as error:
        raise TypeError(
            "direct instrument patch must contain concrete values"
        ) from error


__all__ = [
    "DeclaredStateClientBase",
    "InstrumentClientBase",
    "InstrumentComponentClientBase",
]
