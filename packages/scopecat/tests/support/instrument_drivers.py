from __future__ import annotations

from pathlib import Path

from scopecat.config_profiles import load_config_profile
from scopecat.instruments import (
    CollectCommand,
    DriverDiagnostic,
    InstrumentDescription,
    InstrumentReadback,
    InstrumentResult,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    capability,
    number_field,
    payload_field,
    product,
    quantity_field,
)
from scopecat.instruments.state import StateValue
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


class SignalInstrumentDriver:
    def __init__(self, *, instrument_id: str = "source-0") -> None:
        self.instrument_id = instrument_id
        self.implementation_id = "tests.signal_driver"
        self.implementation_version = "v0"
        self._state: dict[tuple[str, str], StateValue] = {}
        self.applied: list[InstrumentStateCommand] = []
        self.collect_commands: list[CollectCommand] = []

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
                capability("set_gain", fields=[number_field("gain")]),
                capability("play_program", fields=[payload_field("program")]),
                capability(
                    "scalar_signal",
                    products=[product("signal", unit="ratio")],
                ),
            ],
            metadata={"mode": "test_offline"},
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

    def apply_state(self, command: InstrumentStateCommand) -> InstrumentResult:
        self.applied.append(command)
        for field in command.fields:
            self._state[(field.capability_id, field.field_path)] = field.value
        return InstrumentResult()

    def collect(self, command: CollectCommand) -> InstrumentReadback:
        self.collect_commands.append(command)
        if "signal" not in {request.id for request in command.requests}:
            return InstrumentReadback()
        return InstrumentReadback(
            values={"signal": Quantity(value=1.0, unit="ratio")},
            metadata={"implementation": self.implementation_id},
        )

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None


class BlockingSignalInstrumentDriver(SignalInstrumentDriver):
    def apply_state(self, command: InstrumentStateCommand) -> InstrumentResult:
        del command
        return InstrumentResult(
            diagnostics=[
                DriverDiagnostic(
                    severity="error",
                    code="instrument_driver_blocked",
                    message="driver blocked",
                    path="driver",
                ).to_diagnostic()
            ]
        )


class FailingSignalInstrumentDriver(SignalInstrumentDriver):
    def collect(self, command: CollectCommand) -> InstrumentReadback:
        del command
        raise DriverDiagnostic(
            severity="error",
            code="instrument_record_collection_failed",
            message="record collection failed",
            path="collect",
        )


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def quantity_state(value: float, unit: str) -> StateValue:
    return StateValue(kind="quantity", quantity=Quantity(value=value, unit=unit))


def number_state(value: float) -> StateValue:
    return StateValue(kind="number", value=value)


def payload_state(payload_id: str) -> StateValue:
    return StateValue(kind="payload", payload_id=payload_id)
