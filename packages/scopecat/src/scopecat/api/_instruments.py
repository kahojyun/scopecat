"""Notebook-facing direct instrument interaction."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Self
from uuid import uuid4

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import InstrumentListView, InstrumentView
from scopecat.daemon.wire import (
    InstrumentConfiguredDefaultsApplyCommand,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentSessionEndReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateLiteral, StateValue
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
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
    StatePropertyRef,
    acquisition_results,
    evaluate_acquisition_readiness,
    resolve_acquisition_dimensions,
)
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)

type OperationArgumentValue = (
    bool | int | float | str | Quantity | StateValue | CommandPayload
)
type _CollectIntent = tuple[str, AcquisitionRef, tuple[str, ...]]


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
    """Context-managed direct ownership of one or more instruments."""

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
        self._collect_commands: dict[str, tuple[_CollectIntent, CollectCommand]] = {}

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

    def observed_state(
        self,
        instrument_id: str | None = None,
    ) -> InstrumentStateSnapshot:
        """Return the state observed when this session opened."""

        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return next(
            state.model_copy(deep=True)
            for state in session.observed_state
            if state.instrument_id == selected
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

    def apply_configured_defaults(
        self,
        *,
        instrument_id: str | None = None,
        operation_id: str | None = None,
    ) -> InstrumentConfiguredDefaultsApplyReceipt:
        """Apply sparse defaults pinned at session open without resetting hardware."""

        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return self._client.apply_instrument_configured_defaults(
            session.session_id,
            selected,
            InstrumentConfiguredDefaultsApplyCommand(
                operation_id=_select_command_id(
                    operation_id,
                    kind="configured_defaults",
                    subject=selected,
                )
            ),
        )

    def apply(
        self,
        values: Mapping[PropertyRef, StateLiteral | StateValue],
        /,
        *,
        instrument_id: str | None = None,
        command_id: str | None = None,
    ) -> ApplyReceipt:
        if not values:
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
                    interface_id=target.interface_id,
                    component_path=list(target.component_path),
                    property_id=target.property_id,
                    value=(
                        value if isinstance(value, StateValue) else StateValue(value)
                    ),
                )
                for target, value in values.items()
            ],
        )
        return self._client.apply_instrument_state(
            session.session_id,
            selected,
            command,
        )

    def invoke(
        self,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = None,
        /,
        *,
        instrument_id: str | None = None,
        command_id: str | None = None,
    ) -> InvokeReceipt:
        selected_arguments = dict(arguments or {})
        if any(target.operation != operation for target in selected_arguments):
            raise ValueError(
                "operation arguments must belong to the selected operation"
            )
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
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
            interface_id=operation.interface_id,
            component_path=list(operation.component_path),
            operation_id=operation.operation_id,
            arguments=[
                InstrumentOperationArgument(
                    id=target.argument_id,
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
                for target, value in selected_arguments.items()
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
        acquisition: AcquisitionRef,
        *results: AcquisitionResultRef,
        instrument_id: str | None = None,
        command_id: str | None = None,
    ) -> CollectReceipt:
        selected = self._selected_instrument_id(instrument_id)
        description = self.describe(selected)
        interface = next(
            (
                item
                for item in description.interfaces
                if item.id == acquisition.interface_id
            ),
            None,
        )
        if interface is None:
            raise ValueError(
                f"instrument {selected} has no interface {acquisition.interface_id!r}"
            )
        component: InterfaceSpec | ComponentSpec = interface
        for component_id in acquisition.component_path:
            nested = next(
                (item for item in component.components if item.id == component_id),
                None,
            )
            if nested is None:
                raise ValueError(
                    f"interface {acquisition.interface_id!r} has no component path "
                    f"{'/'.join(acquisition.component_path)!r}"
                )
            component = nested
        acquisition_spec = next(
            (
                item
                for item in component.acquisitions
                if item.id == acquisition.acquisition_id
            ),
            None,
        )
        if acquisition_spec is None:
            raise ValueError(
                f"interface {acquisition.interface_id!r} has no acquisition "
                f"{acquisition.acquisition_id!r}"
            )
        if any(result.acquisition != acquisition for result in results):
            raise ValueError("collect results must belong to the selected acquisition")

        requested_result_ids = tuple(result.result_id for result in results)
        if (
            command_id is not None
            and not requested_result_ids
            and acquisition_spec.kind == "state_discriminated"
        ):
            raise ValueError(
                "state-discriminated collection with command_id requires "
                "an explicit result"
            )
        intent: _CollectIntent = (selected, acquisition, requested_result_ids)
        if command_id is not None:
            selected_command_id = _select_command_id(
                command_id,
                kind="collect",
                subject=selected,
            )
            cached = self._collect_commands.get(selected_command_id)
            if cached is not None:
                cached_intent, cached_command = cached
                if cached_intent != intent:
                    raise ValueError(
                        f"instrument command id {selected_command_id!r} has "
                        "different collect content"
                    )
                session = self._require_session()
                return self._client.collect_instrument(
                    session.session_id,
                    selected,
                    cached_command,
                )
        else:
            selected_command_id = _select_command_id(
                None,
                kind="collect",
                subject=selected,
            )
        declared_results = {
            item.id: item for item in acquisition_results(acquisition_spec)
        }
        selected_results = declared_results
        state: InstrumentStateSnapshot | None = None
        state_required = (
            acquisition_spec.kind == "state_discriminated"
            or bool(acquisition_spec.preconditions)
            or any(
                isinstance(axis.size, StatePropertyRef)
                for result_spec in declared_results.values()
                for axis in result_spec.axes
                if not requested_result_ids or result_spec.id in requested_result_ids
            )
        )
        if state_required:
            state = self.read_state(selected)
            readiness = evaluate_acquisition_readiness(
                description=description,
                acquisition=acquisition_spec,
                state=state,
            )
            if readiness.status != "ready":
                reasons = "; ".join(
                    dict.fromkeys(issue.reason for issue in readiness.issues)
                )
                if readiness.status == "blocked":
                    message = (
                        f"acquisition {acquisition.acquisition_id!r} is unavailable"
                    )
                else:
                    message = (
                        f"acquisition {acquisition.acquisition_id!r} "
                        "readiness is unknown"
                    )
                raise ValueError(f"{message}: {reasons}" if reasons else message)
            selected_results = {item.id: item for item in readiness.results}
        selected_result_ids = requested_result_ids or tuple(selected_results)
        inactive = tuple(
            result_id
            for result_id in selected_result_ids
            if result_id not in selected_results
        )
        if inactive:
            raise ValueError(
                f"acquisition {acquisition.acquisition_id!r} has no active results: "
                f"{', '.join(inactive)}"
            )
        session = self._require_session()
        requests: list[CollectResultRequest] = []
        for result_id in selected_result_ids:
            result_spec = selected_results[result_id]
            dimensions = resolve_acquisition_dimensions(
                description=description,
                result=result_spec,
                state=state,
            )
            if dimensions is None:
                raise ValueError(
                    f"acquisition {acquisition.acquisition_id!r} result "
                    f"{result_id!r} axis size state is not synchronized"
                )
            requests.append(
                CollectResultRequest(
                    id=result_id,
                    interface_id=acquisition.interface_id,
                    component_path=list(acquisition.component_path),
                    acquisition_id=acquisition.acquisition_id,
                    result_id=result_id,
                    unit=result_spec.unit,
                    dtype=result_spec.dtype,
                    dimensions=list(dimensions),
                )
            )
        command = CollectCommand(
            command_id=selected_command_id,
            instrument_id=selected,
            point_index=0,
            point_count=1,
            requests=requests,
        )
        if command_id is not None:
            self._collect_commands[selected_command_id] = (intent, command)
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
