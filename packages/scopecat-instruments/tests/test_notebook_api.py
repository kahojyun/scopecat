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
from scopecat.kernel.state import StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InterfaceRef,
    acquisition,
    acquisition_precondition,
    acquisition_result,
    bool_property,
    interface,
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
        self.collect_commands: list[CollectCommand] = []

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
        self.collect_commands.append(command)
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    request.id: MeasurementScalar.create(
                        dtype="float64",
                        value=0.0,
                        unit=request.unit,
                    )
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
            ScriptedExchange.query(":SENS:REM?", "0"),
            ScriptedExchange.query(":SENS:GUAR?", "0"),
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":SOUR:RANG?", "0.01"),
            ScriptedExchange.query(":SOUR:LEV?", "0.001"),
            ScriptedExchange.query(":SOUR:PROT:VOLT?", "10"),
            ScriptedExchange.query(":SOUR:PROT:CURR?", "0.01"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SENS:NPLC?", "1"),
            ScriptedExchange.query(":SENS:DEL?", "0"),
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
    driver.set_output(True)

    _assert_default_monitor_result(
        driver.describe(),
        driver.read_state(),
        expected_result=DC_MONITOR_CURRENT_RESULT,
    )


def test_notebook_monitor_checks_explicit_results_against_the_current_mode() -> None:
    driver = VirtualDcSource("bias", VirtualLabWorld(seed=11))
    driver.set_output(True)
    daemon = _CollectingDaemon(driver.describe(), driver.read_state())
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        receipt = handle.collect(
            DC_MONITOR_ACQUISITION,
            DC_MONITOR_CURRENT_RESULT,
        )
    finally:
        daemon.close()

    assert receipt.status == "collected"
    assert daemon.state_reads == 1
    assert daemon.collect_command is not None
    assert [request.result_id for request in daemon.collect_command.requests] == [
        DC_MONITOR_CURRENT_RESULT.result_id
    ]


def test_notebook_monitor_rejects_an_inactive_explicit_result() -> None:
    driver = VirtualDcSource("bias", VirtualLabWorld(seed=13))
    driver.set_output(True)
    daemon = _CollectingDaemon(driver.describe(), driver.read_state())
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        with pytest.raises(ValueError, match="has no active results"):
            handle.collect(
                DC_MONITOR_ACQUISITION,
                DC_MONITOR_VOLTAGE_RESULT,
            )
    finally:
        daemon.close()

    assert daemon.state_reads == 1
    assert daemon.collect_command is None


def test_notebook_replay_id_requires_an_explicit_discriminated_result() -> None:
    driver = VirtualDcSource("bias", VirtualLabWorld(seed=17))
    daemon = _CollectingDaemon(driver.describe(), driver.read_state())
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("bias",),
        actor="test",
    )

    try:
        with pytest.raises(
            ValueError,
            match="with command_id requires an explicit result",
        ):
            handle.collect(
                DC_MONITOR_ACQUISITION,
                command_id="collect-replay",
            )
    finally:
        daemon.close()

    assert daemon.state_reads == 0
    assert daemon.collect_command is None


def test_notebook_replay_id_sends_the_same_explicit_command_after_state_changes() -> (
    None
):
    description, enabled_state, sample, reading = _fixed_acquisition_contract(
        precondition=True,
        enabled=True,
    )
    daemon = _CollectingDaemon(description, enabled_state)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("sensor",),
        actor="test",
    )

    try:
        handle.collect(sample, reading, command_id="collect-replay")
        daemon.state = _fixed_acquisition_contract(
            precondition=True,
            enabled=False,
        )[1]
        handle.collect(sample, reading, command_id="collect-replay")
    finally:
        daemon.close()

    assert daemon.state_reads == 0
    assert len(daemon.collect_commands) == 2
    assert daemon.collect_commands[0] == daemon.collect_commands[1]


@pytest.mark.parametrize(
    ("precondition", "expected_state_reads"),
    [(False, 0), (True, 1)],
)
def test_fixed_notebook_acquisition_reads_state_only_for_preconditions(
    precondition: bool,
    expected_state_reads: int,
) -> None:
    description, state, sample, _ = _fixed_acquisition_contract(
        precondition=precondition,
        enabled=True,
    )
    daemon = _CollectingDaemon(description, state)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("sensor",),
        actor="test",
    )

    try:
        receipt = handle.collect(sample)
    finally:
        daemon.close()

    assert receipt.status == "collected"
    assert daemon.state_reads == expected_state_reads


def test_notebook_collect_blocks_before_daemon_collect() -> None:
    description, state, sample, _ = _fixed_acquisition_contract(
        precondition=True,
        enabled=False,
    )
    daemon = _CollectingDaemon(description, state)
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("sensor",),
        actor="test",
    )

    try:
        with pytest.raises(
            ValueError,
            match="is unavailable: sensor output must be enabled",
        ):
            handle.collect(sample)
    finally:
        daemon.close()

    assert daemon.state_reads == 1
    assert daemon.collect_command is None


def test_notebook_collect_rejects_unknown_readiness_before_daemon_collect() -> None:
    description, _, sample, _ = _fixed_acquisition_contract(
        precondition=True,
        enabled=True,
    )
    daemon = _CollectingDaemon(
        description,
        InstrumentStateSnapshot(instrument_id="sensor"),
    )
    handle = InstrumentSessionHandle(
        client=daemon,
        instrument_ids=("sensor",),
        actor="test",
    )

    try:
        with pytest.raises(
            ValueError,
            match="readiness is unknown: sensor output must be enabled",
        ):
            handle.collect(sample)
    finally:
        daemon.close()

    assert daemon.state_reads == 1
    assert daemon.collect_command is None


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


def _fixed_acquisition_contract(
    *,
    precondition: bool,
    enabled: bool,
) -> tuple[
    InstrumentDescription,
    InstrumentStateSnapshot,
    AcquisitionRef,
    AcquisitionResultRef,
]:
    sensor = InterfaceRef("tests.notebook_sensor/v1")
    output_enabled = sensor.property("output_enabled")
    sample = sensor.acquisition("sample")
    reading = sample.result("reading")
    requirements = (
        (
            acquisition_precondition(
                output_enabled,
                operator="equal",
                value=True,
                unavailable_reason="sensor output must be enabled",
            ),
        )
        if precondition
        else ()
    )
    description = InstrumentDescription(
        instrument_id="sensor",
        implementation_id="tests.notebook_sensor",
        implementation_version="1",
        interfaces=[
            interface(
                sensor.interface_id,
                properties=[bool_property(output_enabled.property_id)],
                acquisitions=[
                    acquisition(
                        sample.acquisition_id,
                        results=[acquisition_result(reading.result_id)],
                        preconditions=requirements,
                    )
                ],
            )
        ],
    )
    state = InstrumentStateSnapshot(
        instrument_id="sensor",
        properties=[
            InstrumentPropertyState(
                interface_id=output_enabled.interface_id,
                component_path=list(output_enabled.component_path),
                property_id=output_enabled.property_id,
                value=StateValue(enabled),
            )
        ],
    )
    return description, state, sample, reading
