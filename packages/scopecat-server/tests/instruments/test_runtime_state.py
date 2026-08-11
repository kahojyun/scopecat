from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import InterfaceRef
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    InstrumentStateAssignment,
    InstrumentStateCommand,
)

from scopecat_server.instruments._runtime_state import (
    INTERACTIVE_REPLAY_LIMIT,
    ApplyReplay,
    InstrumentOperationLedger,
)

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1").property("frequency")


def test_interactive_replay_ledger_keeps_only_the_recent_window() -> None:
    ledger = InstrumentOperationLedger()
    replay = ApplyReplay(
        command=InstrumentStateCommand(
            command_id="replay-window",
            instrument_id="source-0",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="source-0",
                    interface_id=_SET_FREQUENCY.interface_id,
                    component_path=[],
                    property_id=_SET_FREQUENCY.property_id,
                    value=StateValue(1.0),
                )
            ],
        ),
        receipt=ApplyReceipt(),
    )

    for index in range(INTERACTIVE_REPLAY_LIMIT + 1):
        ledger.remember(f"command-{index}", replay)

    assert ledger.replay("command-0") is None
    assert ledger.replay("command-1") is replay
