from __future__ import annotations

# pyright: reportPrivateUsage=false
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from gc import collect as collect_garbage
from threading import Event
from typing import assert_type, override
from weakref import ref

import pytest
from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    InstrumentSessionHandle,
    LabInstrumentOperations,
    instrument,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    InstrumentConfiguredDefaultsApplyCommand,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentSessionEndReceipt,
    InstrumentSessionLeaseReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
)
from scopecat.records.instrument import (
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    CollectReceipt,
    InstrumentDescription,
    InterfaceRef,
    interface,
)
from scopecat.sdk.instruments.commands import InteractiveCollectIntent

from scopecat_instruments import NetworkSweepReadback, network_sweep
from scopecat_instruments.interfaces import network_sweep_interface
from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
)

_DEFAULT_LEASE_DURATION = timedelta(seconds=30)
_HEARTBEAT_LEASE_DURATION = timedelta(milliseconds=30)


@dataclass(frozen=True, slots=True)
class _TypedSourceClient:
    session: InstrumentClientChannel
    instrument_id: str


class _CollectingDaemon(DaemonClient):
    def __init__(
        self,
        description: InstrumentDescription,
        state: InstrumentStateSnapshot,
        *,
        lease_duration: timedelta = _DEFAULT_LEASE_DURATION,
        initial_renewed_at: datetime | None = None,
    ) -> None:
        super().__init__("http://unused.test")
        self.description = description
        self.state = state
        self.lease_duration = lease_duration
        self.initial_renewed_at = initial_renewed_at
        self.state_reads = 0
        self.collect_intent: InteractiveCollectIntent | None = None

    @override
    def open_instrument_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        renewed_at = self.initial_renewed_at or datetime.now(UTC)
        return InstrumentSessionOpenReceipt(
            session_id="session-1",
            actor=command.actor,
            config_entry_id="config-1",
            config_content_hash=f"sha256:{'0' * 64}",
            instrument_ids=command.instrument_ids,
            configured_default_instrument_ids=(),
            descriptions=(self.description,),
            observed_state=(self.state,),
            opened_at=renewed_at,
            renewed_at=renewed_at,
            expires_at=renewed_at + self.lease_duration,
        )

    @override
    def read_instrument_state(
        self,
        session_id: str,
        instrument_id: str,
    ) -> InstrumentStateSnapshot:
        assert session_id == "session-1"
        assert instrument_id == self.description.instrument_id
        self.state_reads += 1
        return self.state

    @override
    def collect_instrument(
        self,
        session_id: str,
        instrument_id: str,
        intent: InteractiveCollectIntent,
    ) -> CollectReceipt:
        assert session_id == "session-1"
        assert instrument_id == self.description.instrument_id
        self.collect_intent = intent
        return CollectReceipt(readback=InstrumentReadback())

    @override
    def close_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return InstrumentSessionEndReceipt(session_id=session_id, status="closed")


class _ConfiguredDefaultsDaemon(DaemonClient):
    def __init__(self, *, interface_ids: tuple[str, ...] = ()) -> None:
        super().__init__("http://unused.test")
        self.interface_ids = interface_ids
        self.open_commands: list[InstrumentSessionOpenCommand] = []
        self.apply_calls: list[
            tuple[str, str, InstrumentConfiguredDefaultsApplyCommand]
        ] = []

    @override
    def open_instrument_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        self.open_commands.append(command)
        renewed_at = datetime.now(UTC)
        return InstrumentSessionOpenReceipt(
            session_id="session-1",
            actor=command.actor,
            config_entry_id="config-1",
            config_content_hash=f"sha256:{'0' * 64}",
            instrument_ids=command.instrument_ids,
            configured_default_instrument_ids=command.instrument_ids,
            descriptions=tuple(
                InstrumentDescription(
                    instrument_id=instrument_id,
                    implementation_id="tests.instrument",
                    implementation_version="1",
                    interfaces=[interface(id) for id in self.interface_ids],
                )
                for instrument_id in command.instrument_ids
            ),
            observed_state=tuple(
                InstrumentStateSnapshot(instrument_id=instrument_id)
                for instrument_id in command.instrument_ids
            ),
            opened_at=renewed_at,
            renewed_at=renewed_at,
            expires_at=renewed_at + timedelta(seconds=30),
        )

    @override
    def apply_instrument_configured_defaults(
        self,
        session_id: str,
        instrument_id: str,
        command: InstrumentConfiguredDefaultsApplyCommand,
    ) -> InstrumentConfiguredDefaultsApplyReceipt:
        self.apply_calls.append((session_id, instrument_id, command))
        return InstrumentConfiguredDefaultsApplyReceipt(
            session_id=session_id,
            operation_id=command.operation_id,
            instrument_id=instrument_id,
            config_entry_id="config-1",
            status="unchanged",
            state=InstrumentStateSnapshot(instrument_id=instrument_id),
        )

    @override
    def close_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return InstrumentSessionEndReceipt(session_id=session_id, status="closed")


class _HeartbeatDaemon(_CollectingDaemon):
    def __init__(
        self,
        *,
        renew_error: Exception | None = None,
        close_error: Exception | None = None,
        lease_duration: timedelta = _HEARTBEAT_LEASE_DURATION,
        initial_renewed_at: datetime | None = None,
    ) -> None:
        description = InstrumentDescription(
            instrument_id="source-a",
            implementation_id="tests.source",
            implementation_version="1",
        )
        super().__init__(
            description,
            InstrumentStateSnapshot(instrument_id="source-a"),
            lease_duration=lease_duration,
            initial_renewed_at=initial_renewed_at,
        )
        self.renew_error = renew_error
        self.close_error = close_error
        self.renew_attempted = Event()
        self.renew_calls = 0
        self.close_calls = 0

    @override
    def renew_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionLeaseReceipt:
        assert session_id == "session-1"
        self.renew_calls += 1
        self.renew_attempted.set()
        if self.renew_error is not None:
            raise self.renew_error
        renewed_at = datetime.now(UTC)
        return InstrumentSessionLeaseReceipt(
            session_id=session_id,
            renewed_at=renewed_at,
            expires_at=renewed_at + self.lease_duration,
        )

    @override
    def close_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        assert session_id == "session-1"
        self.close_calls += 1
        if self.close_error is not None:
            error = self.close_error
            self.close_error = None
            raise error
        return InstrumentSessionEndReceipt(session_id=session_id, status="closed")


def test_session_handle_renews_lease_in_background() -> None:
    daemon = _HeartbeatDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle._observed_state()

        assert daemon.renew_attempted.wait(timeout=1)
        assert daemon.renew_calls >= 1
    finally:
        handle.close()
        daemon.close()


def test_typed_instrument_ref_binds_a_statically_known_client() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    source = instrument("source-a", _TypedSourceClient)
    assert_type(source, InstrumentRef[_TypedSourceClient])

    handle = LabInstrumentOperations(
        daemon,
        operator="test",
    ).open(source)

    client = handle[source]
    assert_type(client, _TypedSourceClient)
    assert isinstance(client.session, InstrumentClientChannel)
    assert client.instrument_id == "source-a"
    assert handle.instrument_ids == ("source-a",)
    assert daemon.open_commands == []
    daemon.close()


def test_typed_instrument_ref_validates_required_capabilities_when_bound() -> None:
    required = InterfaceRef("test.source/v1")
    source = instrument(
        "source-a",
        _TypedSourceClient,
        requires=(required,),
    )
    assert source.requires == (required,)

    supported_daemon = _ConfiguredDefaultsDaemon(
        interface_ids=(required.interface_id,),
    )
    supported = LabInstrumentOperations(
        supported_daemon,
        operator="test",
    ).open(source)
    assert isinstance(supported[source], _TypedSourceClient)
    supported.close()
    supported_daemon.close()

    unsupported_daemon = _ConfiguredDefaultsDaemon()
    unsupported = LabInstrumentOperations(
        unsupported_daemon,
        operator="test",
    ).open(source)
    with pytest.raises(
        ValueError,
        match=r"source-a.*required interfaces.*test.source/v1",
    ):
        unsupported[source]
    unsupported.close()
    unsupported_daemon.close()


def test_typed_instrument_ref_must_belong_to_the_session() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    source = instrument("source-a", _TypedSourceClient)
    other = instrument("source-b", _TypedSourceClient)
    handle = LabInstrumentOperations(
        daemon,
        operator="test",
    ).open(source)

    with pytest.raises(ValueError, match="is not in this session"):
        handle[other]

    assert daemon.open_commands == []
    daemon.close()


def test_session_handle_immediately_renews_a_late_open_lease() -> None:
    daemon = _HeartbeatDaemon(
        lease_duration=timedelta(seconds=30),
        initial_renewed_at=datetime.now(UTC) - timedelta(seconds=15),
    )
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle._observed_state()

        assert daemon.renew_attempted.wait(timeout=1)
    finally:
        handle.close()
        daemon.close()


def test_session_handle_close_stops_heartbeat() -> None:
    daemon = _HeartbeatDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle._observed_state()
        heartbeat = handle._heartbeat
        assert heartbeat is not None
        assert daemon.renew_attempted.wait(timeout=1)

        receipt = handle.close()

        assert receipt is not None
        assert receipt.status == "closed"
        assert not heartbeat._thread.is_alive()
    finally:
        handle.close()
        daemon.close()


def test_session_handle_surfaces_renewal_failure() -> None:
    failure = RuntimeError("renewal transport failed")
    daemon = _HeartbeatDaemon(renew_error=failure)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle._observed_state()
        heartbeat = handle._heartbeat
        assert heartbeat is not None
        assert daemon.renew_attempted.wait(timeout=1)
        heartbeat._thread.join(timeout=1)

        with pytest.raises(
            RuntimeError,
            match="instrument session lease renewal failed",
        ) as caught:
            handle._read_state()

        assert caught.value.__cause__ is failure
    finally:
        handle.close()
        daemon.close()


def test_session_handle_keeps_heartbeat_after_close_failure() -> None:
    close_error = RuntimeError("close transport failed")
    daemon = _HeartbeatDaemon(close_error=close_error)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle._observed_state()
        heartbeat = handle._heartbeat
        assert heartbeat is not None

        with pytest.raises(RuntimeError, match="close transport failed") as caught:
            handle.close()

        assert caught.value is close_error
        daemon.renew_attempted.clear()
        assert daemon.renew_attempted.wait(timeout=1)
        assert heartbeat._thread.is_alive()

        receipt = handle.close()

        assert receipt is not None
        assert receipt.status == "closed"
        assert daemon.close_calls == 2
        assert not heartbeat._thread.is_alive()
    finally:
        handle.close()
        daemon.close()


def test_discarded_session_handle_requests_heartbeat_stop() -> None:
    daemon = _HeartbeatDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )
    handle._observed_state()
    heartbeat = handle._heartbeat
    assert heartbeat is not None
    handle_reference = ref(handle)

    del handle
    collect_garbage()
    heartbeat._thread.join(timeout=1)

    assert handle_reference() is None
    assert not heartbeat._thread.is_alive()
    daemon.close()


def test_apply_configured_defaults_lazily_opens_and_generates_operation_id() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        assert daemon.open_commands == []

        receipt = handle._apply_configured_defaults()

        assert len(daemon.open_commands) == 1
        [(session_id, instrument_id, command)] = daemon.apply_calls
        assert session_id == "session-1"
        assert instrument_id == "source-a"
        assert command.operation_id.startswith(
            "interactive.configured_defaults.source-a."
        )
        assert receipt.operation_id == command.operation_id
    finally:
        daemon.close()


def test_session_handle_exposes_opening_observation_without_refresh() -> None:
    description = InstrumentDescription(
        instrument_id="source-a",
        implementation_id="tests.source",
        implementation_version="1",
    )
    state = InstrumentStateSnapshot(instrument_id="source-a")
    daemon = _CollectingDaemon(description, state)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        observed = handle._observed_state()

        assert observed == state
        assert observed is not state
        assert daemon.state_reads == 0
        assert handle._read_state() == state
        assert daemon.state_reads == 1
    finally:
        daemon.close()


def test_apply_configured_defaults_requires_multi_instrument_selection() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a", "source-b"),
        actor="test",
    )

    try:
        with pytest.raises(
            ValueError,
            match="multi-instrument sessions require an instrument_id",
        ):
            handle._apply_configured_defaults()

        assert daemon.open_commands == []

        receipt = handle._apply_configured_defaults(instrument_id="source-b")

        assert receipt.instrument_id == "source-b"
        [(_, instrument_id, _)] = daemon.apply_calls
        assert instrument_id == "source-b"
        assert daemon.open_commands[0].instrument_ids == ("source-a", "source-b")
    finally:
        daemon.close()


def test_notebook_collect_sends_unspecified_results_without_reading_state() -> None:
    description = InstrumentDescription(
        instrument_id="bias",
        implementation_id="tests.source",
        implementation_version="1",
    )
    daemon = _CollectingDaemon(
        description,
        InstrumentStateSnapshot(instrument_id="bias"),
    )
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        receipt = handle._collect(DC_MONITOR_ACQUISITION)
    finally:
        daemon.close()

    assert receipt.status == "collected"
    assert daemon.state_reads == 0
    assert daemon.collect_intent is not None
    assert daemon.collect_intent.command_id.startswith("interactive.collect.bias.")
    assert daemon.collect_intent == InteractiveCollectIntent(
        command_id=daemon.collect_intent.command_id,
        instrument_id="bias",
        interface_id=DC_MONITOR_ACQUISITION.interface_id,
        component_path=list(DC_MONITOR_ACQUISITION.component_path),
        acquisition_id=DC_MONITOR_ACQUISITION.acquisition_id,
        result_ids=[],
    )


def test_notebook_collect_sends_explicit_result_identity() -> None:
    description = InstrumentDescription(
        instrument_id="bias",
        implementation_id="tests.source",
        implementation_version="1",
    )
    daemon = _CollectingDaemon(
        description,
        InstrumentStateSnapshot(instrument_id="bias"),
    )
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        handle._collect(
            DC_MONITOR_ACQUISITION,
            DC_MONITOR_CURRENT_RESULT,
        )
    finally:
        daemon.close()

    assert daemon.state_reads == 0
    assert daemon.collect_intent is not None
    assert daemon.collect_intent.result_ids == [DC_MONITOR_CURRENT_RESULT.result_id]


def test_declared_live_client_maps_named_results_and_requests_the_layout() -> None:
    description = InstrumentDescription(
        instrument_id="readout",
        implementation_id="tests.network_sweep",
        implementation_version="1",
        interfaces=[network_sweep_interface()],
    )
    daemon = _CollectingDaemon(
        description,
        InstrumentStateSnapshot(instrument_id="readout"),
    )
    target = network_sweep("readout")
    handle = LabInstrumentOperations(daemon, operator="test").open(target)

    try:
        readback = assert_type(handle[target].sweep(), NetworkSweepReadback)
    finally:
        handle.close()
        daemon.close()

    assert readback.receipt.status == "collected"
    assert readback.frequency is None
    assert readback.s_parameter is None
    assert daemon.collect_intent is not None
    assert daemon.collect_intent.acquisition_id == (
        NETWORK_SWEEP_ACQUISITION.acquisition_id
    )
    assert daemon.collect_intent.result_ids == [
        NETWORK_SWEEP_FREQUENCY_RESULT.result_id,
        NETWORK_SWEEP_S_PARAMETER_RESULT.result_id,
    ]


def test_notebook_collect_rejects_a_result_from_another_acquisition() -> None:
    description = InstrumentDescription(
        instrument_id="bias",
        implementation_id="tests.source",
        implementation_version="1",
    )
    daemon = _CollectingDaemon(
        description,
        InstrumentStateSnapshot(instrument_id="bias"),
    )
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        with pytest.raises(
            ValueError,
            match="collect results must belong to the selected acquisition",
        ):
            handle._collect(
                DC_MONITOR_ACQUISITION,
                NETWORK_SWEEP_FREQUENCY_RESULT,
            )
    finally:
        daemon.close()

    assert daemon.collect_intent is None
