from __future__ import annotations

from pathlib import Path

from scopecat.config_profiles import load_config_profile
from scopecat.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    DriverFault,
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
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

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


class BlockingSignalInstrumentDriver(SignalInstrumentDriver):
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        del command
        return ApplyReceipt(
            status="not_applied",
            problems=(
                blocking_problem(
                    code="instrument_driver_blocked",
                    message="driver blocked",
                    category=ProblemCategory.EXTERNAL_FAILURE,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("driver", "apply_state"),
                ),
            ),
        )


class FailingSignalInstrumentDriver(SignalInstrumentDriver):
    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        raise DriverFault(
            blocking_problem(
                code="instrument_record_collection_failed",
                message="record collection failed",
                category=ProblemCategory.EXTERNAL_FAILURE,
                phase=ProblemPhase.EXECUTION,
                location=model_location("driver", "collect"),
            )
        )


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def quantity_state(value: float, unit: str) -> StateValue:
    return StateValue(Quantity(value=value, unit=unit))


def number_state(value: float) -> StateValue:
    return StateValue(value)


def payload_state(payload_id: str) -> StateValue:
    return StateValue(PayloadRef(payload_id=payload_id))
