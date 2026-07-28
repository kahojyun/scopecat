from __future__ import annotations

from datetime import UTC, datetime
from typing import override

import pytest
from scopecat.api._instruments import InstrumentSessionHandle
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    InstrumentConfiguredDefaultsApplyCommand,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
)
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import (
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    AcquisitionResultRef,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
)

from scopecat_instruments.drivers import YokogawaGS200
from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_VOLTAGE_RESULT,
)
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld


class _CollectingDaemon(DaemonClient):
    def __init__(
        self,
        description: InstrumentDescription,
        state: InstrumentStateSnapshot,
    ) -> None:
        super().__init__("http://unused.test")
        self.description = description
        self.state = state
        self.state_reads = 0
        self.collect_command: CollectCommand | None = None

    @override
    def open_instrument_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        return InstrumentSessionOpenReceipt(
            session_id="session-1",
            actor=command.actor,
            config_entry_id="config-1",
            config_content_hash=f"sha256:{'0' * 64}",
            instrument_ids=command.instrument_ids,
            configured_default_instrument_ids=(),
            descriptions=(self.description,),
            observed_state=(self.state,),
            opened_at=datetime(2026, 7, 29, tzinfo=UTC),
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
        command: CollectCommand,
    ) -> CollectReceipt:
        assert session_id == "session-1"
        assert instrument_id == self.description.instrument_id
        self.collect_command = command
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    request.id: Quantity(0.0, request.unit or "ratio")
                    for request in command.requests
                }
            )
        )


class _ConfiguredDefaultsDaemon(DaemonClient):
    def __init__(self) -> None:
        super().__init__("http://unused.test")
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
                )
                for instrument_id in command.instrument_ids
            ),
            observed_state=tuple(
                InstrumentStateSnapshot(instrument_id=instrument_id)
                for instrument_id in command.instrument_ids
            ),
            opened_at=datetime(2026, 7, 29, tzinfo=UTC),
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


def test_apply_configured_defaults_lazily_opens_and_generates_operation_id() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        assert daemon.open_commands == []

        receipt = handle.apply_configured_defaults()

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
        observed = handle.observed_state()

        assert observed == state
        assert observed is not state
        assert daemon.state_reads == 0
        assert handle.read_state() == state
        assert daemon.state_reads == 1
    finally:
        daemon.close()


def test_apply_configured_defaults_preserves_explicit_operation_id() -> None:
    daemon = _ConfiguredDefaultsDaemon()
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("source-a",),
        actor="test",
    )

    try:
        handle.apply_configured_defaults(operation_id="defaults.manual-1")

        [(_, _, command)] = daemon.apply_calls
        assert command.operation_id == "defaults.manual-1"
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
            handle.apply_configured_defaults()

        assert daemon.open_commands == []

        receipt = handle.apply_configured_defaults(instrument_id="source-b")

        assert receipt.instrument_id == "source-b"
        [(_, instrument_id, _)] = daemon.apply_calls
        assert instrument_id == "source-b"
        assert daemon.open_commands[0].instrument_ids == ("source-a", "source-b")
    finally:
        daemon.close()


def test_gs200_notebook_monitor_defaults_to_the_current_mode_result() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":SOUR:RANG?", "0.01"),
            ScriptedExchange.query(":SOUR:LEV?", "0.001"),
            ScriptedExchange.query(":SOUR:PROT:VOLT?", "10"),
            ScriptedExchange.query(":SOUR:PROT:CURR?", "0.01"),
            ScriptedExchange.query(":OUTP?", "1"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    _assert_default_monitor_result(
        driver.describe(),
        driver.read_state(),
        expected_result=DC_MONITOR_VOLTAGE_RESULT,
    )
    transport.assert_complete()


def test_virtual_notebook_monitor_defaults_to_the_voltage_mode_result() -> None:
    driver = VirtualDcSource("bias", VirtualLabWorld(seed=7))

    _assert_default_monitor_result(
        driver.describe(),
        driver.read_state(),
        expected_result=DC_MONITOR_CURRENT_RESULT,
    )


def _assert_default_monitor_result(
    description: InstrumentDescription,
    state: InstrumentStateSnapshot,
    *,
    expected_result: AcquisitionResultRef,
) -> None:
    daemon = _CollectingDaemon(description, state)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=(description.instrument_id,),
        actor="test",
    )

    try:
        receipt = handle.collect(DC_MONITOR_ACQUISITION)
    finally:
        daemon.close()

    assert receipt.status == "collected"
    assert daemon.state_reads == 1
    assert daemon.collect_command is not None
    assert [request.result_id for request in daemon.collect_command.requests] == [
        expected_result.result_id
    ]
