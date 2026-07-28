from __future__ import annotations

from scopecat.config.documents import load_config_snapshot_document
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.kernel.value_types import Scalar
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentPropertyState,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
    InvokeCommand,
    InvokeReceipt,
    acquisition,
    acquisition_result,
    float_property,
    interface,
    operation,
    operation_argument,
    quantity_property,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR


class SignalInstrumentDriver:
    def __init__(self, *, instrument_id: str = "source-0") -> None:
        self._instrument_id = instrument_id
        self.implementation_id = "tests.signal_driver"
        self.implementation_version = "v0"
        self._state: dict[tuple[str, str], StateValue] = {}
        self.applied: list[InstrumentStateCommand] = []
        self.invoked: list[InvokeCommand] = []
        self.collect_commands: list[CollectCommand] = []

    @property
    def instrument_id(self) -> str:
        return self._instrument_id

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    "test.set_frequency/v1",
                    properties=[quantity_property("frequency", unit="GHz")],
                ),
                interface(
                    "test.set_gain/v1",
                    properties=[float_property("gain")],
                ),
                interface(
                    "test.play_program/v1",
                    operations=[
                        operation(
                            "play",
                            arguments=[
                                operation_argument(
                                    "program",
                                    value_type=Scalar(
                                        PayloadType(schema_id="pulse_program")
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                interface(
                    "test.scalar_signal/v1",
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("signal", unit="ratio")],
                        )
                    ],
                ),
            ],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                InstrumentPropertyState(
                    interface_id=interface_id,
                    property_id=property_id,
                    value=value,
                )
                for (interface_id, property_id), value in sorted(self._state.items())
            ],
            metadata={"mode": "test_offline"},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        for assignment in command.assignments:
            self._state[(assignment.interface_id, assignment.property_id)] = (
                assignment.value
            )
        return ApplyReceipt(status="applied")

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        self.invoked.append(command)
        return InvokeReceipt(status="invoked", state=self.read_state())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        if "signal" not in {request.id for request in command.requests}:
            return CollectReceipt(readback=InstrumentReadback())
        return CollectReceipt(
            readback=InstrumentReadback(
                values={"signal": Quantity(value=1.0, unit="ratio")},
                metadata={"implementation": self.implementation_id},
            )
        )

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


def load_config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")


def quantity_state(value: float, unit: str) -> StateValue:
    return StateValue(Quantity(value=value, unit=unit))


def number_state(value: float) -> StateValue:
    return StateValue(value)
