from __future__ import annotations

from scopecat.config.profiles import load_config_profile
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    capability,
    float_field,
    payload_field,
    product,
    quantity_field,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR


class SignalInstrumentDriver:
    def __init__(self, *, instrument_id: str = "source-0") -> None:
        self._instrument_id = instrument_id
        self.implementation_id = "tests.signal_driver"
        self.implementation_version = "v0"
        self._state: dict[tuple[str, str], StateValue] = {}
        self.applied: list[InstrumentStateCommand] = []
        self.collect_commands: list[CollectCommand] = []

    @property
    def instrument_id(self) -> str:
        return self._instrument_id

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "set_frequency",
                    fields=[quantity_field("frequency", unit="GHz")],
                ),
                capability("set_gain", fields=[float_field("gain")]),
                capability(
                    "play_program",
                    fields=[payload_field("program", schema_id="pulse_program")],
                ),
                capability(
                    "scalar_signal",
                    products=[product("signal", unit="ratio")],
                ),
            ],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=[
                InstrumentStateField(
                    capability_id=capability_id,
                    field_path=field_path,
                    value=value,
                )
                for (capability_id, field_path), value in sorted(self._state.items())
            ],
            metadata={"mode": "test_offline"},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        for field in command.fields:
            self._state[(field.capability_id, field.field_path)] = field.value
        return ApplyReceipt(status="applied")

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

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def quantity_state(value: float, unit: str) -> StateValue:
    return StateValue(Quantity(value=value, unit=unit))


def number_state(value: float) -> StateValue:
    return StateValue(value)


def payload_state(payload_id: str) -> StateValue:
    return StateValue(PayloadRef(payload_id=payload_id))
