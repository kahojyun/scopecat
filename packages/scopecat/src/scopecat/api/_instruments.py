"""Notebook-facing direct instrument interaction."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Self
from uuid import uuid4

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import InstrumentListView, InstrumentView
from scopecat.daemon.wire import (
    InstrumentSessionEndReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateLiteral, StateValue
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectAxisRequest,
    CollectCommand,
    CollectReceipt,
    CollectResultRequest,
    ComponentSpec,
    InstrumentDescription,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InterfaceSpec,
    InvokeCommand,
    InvokeReceipt,
)

type OperationArgumentValue = (
    bool | int | float | str | Quantity | StateValue | CommandPayload
)


class LabInstrumentOperations:
    """Discover configured instruments and create daemon-owned live sessions."""

    def __init__(
        self,
        client: DaemonClient,
        *,
        operator: str,
    ) -> None:
        self._client = client
        self._operator = operator

    def list(self) -> InstrumentListView:
        return self._client.list_instruments()

    def get(self, instrument_id: str) -> InstrumentView:
        return self._client.get_instrument(instrument_id)

    def abort_session(self, session_id: str) -> InstrumentSessionEndReceipt:
        """Abort and release a daemon-owned session by id."""

        return self._client.abort_instrument_session(session_id)

    def open(
        self,
        instrument_id: str,
        *additional_instrument_ids: str,
        actor: str | None = None,
        command_id: str | None = None,
    ) -> InstrumentSessionHandle:
        return InstrumentSessionHandle(
            client=self._client,
            instrument_ids=(instrument_id, *additional_instrument_ids),
            actor=actor or self._operator,
            open_command_id=command_id,
        )


class InstrumentSessionHandle:
    """Context-managed direct access to one or more live drivers."""

    def __init__(
        self,
        *,
        client: DaemonClient,
        instrument_ids: tuple[str, ...],
        actor: str,
        open_command_id: str | None = None,
    ) -> None:
        if not instrument_ids or any(not item for item in instrument_ids):
            raise ValueError("direct interaction requires non-empty instrument ids")
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("direct interaction instrument ids must be unique")
        if not actor:
            raise ValueError("direct interaction actor must be non-empty")
        self._client = client
        self._instrument_ids = instrument_ids
        self._actor = actor
        self._open_command_id = _select_command_id(
            open_command_id,
            kind="open",
            subject=instrument_ids[0],
        )
        self._session: InstrumentSessionOpenReceipt | None = None
        self._ended = False

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is None:
            self.close()
        else:
            self.abort()

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return self._instrument_ids

    @property
    def session_id(self) -> str:
        return self._require_session().session_id

    def describe(
        self,
        instrument_id: str | None = None,
    ) -> InstrumentDescription:
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return next(
            description
            for description in session.descriptions
            if description.instrument_id == selected
        )

    def read_state(
        self,
        instrument_id: str | None = None,
    ) -> InstrumentStateSnapshot:
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return self._client.read_instrument_state(
            session.session_id,
            selected,
        )

    def apply(
        self,
        interface_id: InterfaceId,
        values: Mapping[str, StateLiteral | StateValue] | None = None,
        /,
        *,
        component_path: tuple[str, ...] = (),
        instrument_id: str | None = None,
        command_id: str | None = None,
        **properties: StateLiteral | StateValue,
    ) -> ApplyReceipt:
        if values is not None and properties:
            raise ValueError("pass properties as a mapping or keyword values")
        selected_values = dict(values or properties)
        if not selected_values:
            raise ValueError("interactive apply requires at least one property")
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        selected_command_id = _select_command_id(
            command_id,
            kind="apply",
            subject=selected,
        )
        command = InstrumentStateCommand(
            command_id=selected_command_id,
            instrument_id=selected,
            assignments=[
                InstrumentStateAssignment(
                    resource_id=selected,
                    interface_id=interface_id,
                    component_path=list(component_path),
                    property_id=property_id,
                    value=(
                        value if isinstance(value, StateValue) else StateValue(value)
                    ),
                )
                for property_id, value in selected_values.items()
            ],
        )
        return self._client.apply_instrument_state(
            session.session_id,
            selected,
            command,
        )

    def invoke(
        self,
        interface_id: InterfaceId,
        operation_id: str,
        arguments: Mapping[str, OperationArgumentValue] | None = None,
        /,
        *,
        component_path: tuple[str, ...] = (),
        instrument_id: str | None = None,
        command_id: str | None = None,
        **argument_values: OperationArgumentValue,
    ) -> InvokeReceipt:
        if arguments is not None and argument_values:
            raise ValueError("pass operation arguments as a mapping or keyword values")
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        selected_arguments = dict(arguments or argument_values)
        payloads: dict[str, CommandPayload] = {}
        for value in selected_arguments.values():
            if not isinstance(value, CommandPayload):
                continue
            previous = payloads.setdefault(value.id, value)
            if previous != value:
                raise ValueError(
                    f"operation payload id {value.id!r} has different content"
                )
        command = InvokeCommand(
            command_id=_select_command_id(
                command_id,
                kind="invoke",
                subject=selected,
            ),
            instrument_id=selected,
            resource_id=selected,
            interface_id=interface_id,
            component_path=list(component_path),
            operation_id=operation_id,
            arguments=[
                InstrumentOperationArgument(
                    id=argument_id,
                    value=(
                        value
                        if isinstance(value, StateValue)
                        else (
                            StateValue(PayloadRef(payload_id=value.id))
                            if isinstance(value, CommandPayload)
                            else StateValue(value)
                        )
                    ),
                )
                for argument_id, value in selected_arguments.items()
            ],
            payloads=payloads,
        )
        return self._client.invoke_instrument(
            session.session_id,
            selected,
            command,
        )

    def collect(
        self,
        interface_id: InterfaceId,
        acquisition_id: str,
        *result_ids: str,
        component_path: tuple[str, ...] = (),
        instrument_id: str | None = None,
        command_id: str | None = None,
    ) -> CollectReceipt:
        selected = self._selected_instrument_id(instrument_id)
        description = self.describe(selected)
        interface = next(
            (item for item in description.interfaces if item.id == interface_id),
            None,
        )
        if interface is None:
            raise ValueError(f"instrument {selected} has no interface {interface_id!r}")
        component: InterfaceSpec | ComponentSpec = interface
        for component_id in component_path:
            nested = next(
                (item for item in component.components if item.id == component_id),
                None,
            )
            if nested is None:
                raise ValueError(
                    f"interface {interface_id!r} has no component path "
                    f"{'/'.join(component_path)!r}"
                )
            component = nested
        acquisition = next(
            (item for item in component.acquisitions if item.id == acquisition_id),
            None,
        )
        if acquisition is None:
            raise ValueError(
                f"interface {interface_id!r} has no acquisition {acquisition_id!r}"
            )
        results = {item.id: item for item in acquisition.results}
        selected_result_ids = result_ids or tuple(results)
        missing = tuple(
            result_id for result_id in selected_result_ids if result_id not in results
        )
        if missing:
            raise ValueError(
                f"acquisition {acquisition_id!r} has no results: {', '.join(missing)}"
            )
        session = self._require_session()
        command = CollectCommand(
            command_id=_select_command_id(
                command_id,
                kind="collect",
                subject=selected,
            ),
            instrument_id=selected,
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id=result_id,
                    interface_id=interface_id,
                    component_path=list(component_path),
                    acquisition_id=acquisition_id,
                    result_id=result_id,
                    unit=results[result_id].unit,
                    dtype=results[result_id].dtype,
                    dimensions=[
                        CollectAxisRequest(
                            id=axis.id,
                            kind=axis.kind,
                            size=axis.size,
                            unit=axis.unit,
                        )
                        for axis in results[result_id].axes
                        if axis.size is not None
                    ],
                )
                for result_id in selected_result_ids
            ],
        )
        return self._client.collect_instrument(
            session.session_id,
            selected,
            command,
        )

    def close(
        self,
    ) -> InstrumentSessionEndReceipt | None:
        return self._end(abort=False)

    def abort(
        self,
    ) -> InstrumentSessionEndReceipt | None:
        return self._end(abort=True)

    def _end(
        self,
        *,
        abort: bool,
    ) -> InstrumentSessionEndReceipt | None:
        if self._ended:
            return None
        session = self._session
        if session is None:
            self._ended = True
            return None
        receipt = (
            self._client.abort_instrument_session(session.session_id)
            if abort
            else self._client.close_instrument_session(session.session_id)
        )
        self._ended = True
        return receipt

    def _ensure_open(self) -> InstrumentSessionOpenReceipt:
        if self._ended:
            raise RuntimeError("instrument session is already closed")
        if self._session is None:
            self._session = self._client.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id=self._open_command_id,
                    actor=self._actor,
                    instrument_ids=self._instrument_ids,
                )
            )
        return self._session

    def _require_session(self) -> InstrumentSessionOpenReceipt:
        return self._ensure_open()

    def _selected_instrument_id(self, instrument_id: str | None) -> str:
        if instrument_id is None:
            if len(self._instrument_ids) != 1:
                raise ValueError("multi-instrument sessions require an instrument_id")
            return self._instrument_ids[0]
        if instrument_id not in self._instrument_ids:
            raise ValueError(f"instrument {instrument_id!r} is not in this session")
        return instrument_id


def _new_command_id(kind: str, subject: str) -> str:
    return f"interactive.{kind}.{subject}.{uuid4().hex}"


def _select_command_id(
    requested: str | None,
    *,
    kind: str,
    subject: str,
) -> str:
    if requested is None:
        return _new_command_id(kind, subject)
    if not requested:
        raise ValueError("instrument command id must be non-empty")
    return requested


__all__ = [
    "InstrumentSessionHandle",
    "LabInstrumentOperations",
    "OperationArgumentValue",
]
