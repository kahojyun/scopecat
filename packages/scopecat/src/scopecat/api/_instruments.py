"""Notebook-facing direct instrument interaction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from types import TracebackType
from typing import Self
from uuid import uuid4
from weakref import finalize

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
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InteractiveCollectIntent,
    InvokeCommand,
    InvokeReceipt,
)
from scopecat.sdk.instruments.contracts import InstrumentDescription
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

_HEARTBEAT_JOIN_SECONDS = 0.2


class _InstrumentSessionHeartbeat:
    def __init__(
        self,
        client: DaemonClient,
        session: InstrumentSessionOpenReceipt,
    ) -> None:
        self._client = client
        self._session_id = session.session_id
        self._initial_renewal_at = (
            session.renewed_at + (session.expires_at - session.renewed_at) / 3
        )
        self._stop = Event()
        self._lock = Lock()
        self._failure: Exception | None = None
        self._thread = Thread(
            target=self._run,
            name="scopecat-instrument-session-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def require_live(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise RuntimeError("instrument session lease renewal failed") from failure

    def request_stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self.request_stop()
        self._thread.join(timeout=_HEARTBEAT_JOIN_SECONDS)

    def _run(self) -> None:
        renewal_at = self._initial_renewal_at
        while not self._stop.wait(
            max((renewal_at - datetime.now(UTC)).total_seconds(), 0.0)
        ):
            try:
                lease = self._client.renew_instrument_session(self._session_id)
            except Exception as error:
                with self._lock:
                    self._failure = error
                return
            renewal_at = lease.renewed_at + (lease.expires_at - lease.renewed_at) / 3


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

    def open(
        self,
        instrument_id: str,
        *additional_instrument_ids: str,
    ) -> InstrumentSessionHandle:
        return InstrumentSessionHandle(
            client=self._client,
            instrument_ids=(instrument_id, *additional_instrument_ids),
            actor=self._operator,
        )


class InstrumentSessionHandle:
    """Context-managed direct ownership of one or more instruments."""

    def __init__(
        self,
        *,
        client: DaemonClient,
        instrument_ids: tuple[str, ...],
        actor: str,
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
        self._open_operation_id = _new_command_id("open", instrument_ids[0])
        self._session: InstrumentSessionOpenReceipt | None = None
        self._heartbeat: _InstrumentSessionHeartbeat | None = None
        self._heartbeat_finalizer: finalize[[], Self] | None = None
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
    ) -> InstrumentConfiguredDefaultsApplyReceipt:
        """Apply sparse defaults pinned at session open without resetting hardware."""

        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        return self._client.apply_instrument_configured_defaults(
            session.session_id,
            selected,
            InstrumentConfiguredDefaultsApplyCommand(
                operation_id=_new_command_id("configured_defaults", selected)
            ),
        )

    def apply(
        self,
        values: Mapping[PropertyRef, StateLiteral | StateValue],
        /,
        *,
        instrument_id: str | None = None,
    ) -> ApplyReceipt:
        if not values:
            raise ValueError("interactive apply requires at least one property")
        selected = self._selected_instrument_id(instrument_id)
        session = self._require_session()
        command = InstrumentStateCommand(
            command_id=_new_command_id("apply", selected),
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
            command_id=_new_command_id("invoke", selected),
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
    ) -> CollectReceipt:
        selected = self._selected_instrument_id(instrument_id)
        if any(result.acquisition != acquisition for result in results):
            raise ValueError("collect results must belong to the selected acquisition")

        session = self._require_session()
        intent = InteractiveCollectIntent(
            command_id=_new_command_id("collect", selected),
            instrument_id=selected,
            interface_id=acquisition.interface_id,
            component_path=list(acquisition.component_path),
            acquisition_id=acquisition.acquisition_id,
            result_ids=[result.result_id for result in results],
        )
        return self._client.collect_instrument(
            session.session_id,
            selected,
            intent,
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
        self._stop_heartbeat()
        return receipt

    def _ensure_open(self) -> InstrumentSessionOpenReceipt:
        if self._ended:
            raise RuntimeError("instrument session is already closed")
        session = self._session
        if session is None:
            session = self._client.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id=self._open_operation_id,
                    actor=self._actor,
                    instrument_ids=self._instrument_ids,
                )
            )
            heartbeat = _InstrumentSessionHeartbeat(self._client, session)
            self._session = session
            self._heartbeat = heartbeat
            self._heartbeat_finalizer = finalize(self, heartbeat.request_stop)
            heartbeat.start()
        else:
            heartbeat = self._heartbeat
            assert heartbeat is not None
            heartbeat.require_live()
        return session

    def _stop_heartbeat(self) -> None:
        heartbeat = self._heartbeat
        if heartbeat is None:
            return
        heartbeat.close()
        finalizer = self._heartbeat_finalizer
        if finalizer is not None:
            finalizer.detach()
        self._heartbeat = None
        self._heartbeat_finalizer = None

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


__all__ = [
    "InstrumentSessionHandle",
    "LabInstrumentOperations",
    "OperationArgumentValue",
]
