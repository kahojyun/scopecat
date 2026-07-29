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
from scopecat.records.instrument import (
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    CollectReceipt,
    InstrumentDescription,
    InteractiveCollectIntent,
)

from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    NETWORK_SWEEP_FREQUENCY_RESULT,
)


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
        self.collect_intent: InteractiveCollectIntent | None = None
        self.collect_intents: list[InteractiveCollectIntent] = []

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
        intent: InteractiveCollectIntent,
    ) -> CollectReceipt:
        assert session_id == "session-1"
        assert instrument_id == self.description.instrument_id
        self.collect_intent = intent
        self.collect_intents.append(intent)
        return CollectReceipt(readback=InstrumentReadback())


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
        receipt = handle.collect(
            DC_MONITOR_ACQUISITION,
            command_id="collect-1",
        )
    finally:
        daemon.close()

    assert receipt.status == "collected"
    assert daemon.state_reads == 0
    assert daemon.collect_intent == InteractiveCollectIntent(
        command_id="collect-1",
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
        handle.collect(
            DC_MONITOR_ACQUISITION,
            DC_MONITOR_CURRENT_RESULT,
        )
    finally:
        daemon.close()

    assert daemon.state_reads == 0
    assert daemon.collect_intent is not None
    assert daemon.collect_intent.result_ids == [DC_MONITOR_CURRENT_RESULT.result_id]


def test_notebook_retries_send_the_same_high_level_intent() -> None:
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
        handle.collect(
            DC_MONITOR_ACQUISITION,
            command_id="collect-replay",
        )
        handle.collect(
            DC_MONITOR_ACQUISITION,
            command_id="collect-replay",
        )
    finally:
        daemon.close()

    assert daemon.state_reads == 0
    assert len(daemon.collect_intents) == 2
    assert daemon.collect_intents[0] == daemon.collect_intents[1]


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
            handle.collect(
                DC_MONITOR_ACQUISITION,
                NETWORK_SWEEP_FREQUENCY_RESULT,
            )
    finally:
        daemon.close()

    assert daemon.collect_intent is None
