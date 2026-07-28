from __future__ import annotations

from datetime import UTC, datetime
from typing import override

from scopecat.api._instruments import InstrumentSessionHandle
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
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
            descriptions=(self.description,),
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
