"""Minimal Rohde & Schwarz SGS100A continuous-wave source driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
    InvokeCommand,
    InvokeReceipt,
)

from scopecat_instruments._support import (
    ScpiIdentity,
    apply_unknown,
    bool_value,
    format_number,
    not_applied,
    not_collected,
    parse_bool,
    parse_float,
    parse_identity,
    quantity_value,
    state_property,
    string_value,
    unsupported_invoke,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.driver_ids import ROHDE_SCHWARZ_SGS100A
from scopecat_instruments.interfaces import RF_OUTPUT, rf_output_interface
from scopecat_instruments.transport import ScpiTransport


class RohdeSchwarzSGS100A:
    """CW frequency, power, RF output, and reference source controls."""

    implementation_id = ROHDE_SCHWARZ_SGS100A
    implementation_version = "v1"

    def __init__(self, instrument_id: str, transport: ScpiTransport) -> None:
        self.instrument_id = instrument_id
        self.transport = transport
        self._identity: ScpiIdentity | None = None

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="R&S SGS100A",
            description=(
                "Minimal continuous-wave RF source driver. Modulation and "
                "option-dependent features are outside the v1 boundary."
            ),
            interfaces=[rf_output_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Rohde & Schwarz",
            "model": "SGS100A",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                state_property(
                    RF_OUTPUT,
                    "frequency",
                    Quantity(self.frequency(), "Hz"),
                ),
                state_property(
                    RF_OUTPUT,
                    "power",
                    Quantity(self.power(), "dBm"),
                ),
                state_property(RF_OUTPUT, "output_enabled", self.output_enabled()),
                state_property(
                    RF_OUTPUT,
                    "reference_source",
                    self.reference_source(),
                ),
            ],
            metadata=metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        if problems:
            return not_applied(problems)
        properties = {
            assignment.property_id: assignment for assignment in command.assignments
        }
        output_property = properties.get("output_enabled")
        target_output = (
            bool_value(output_property.value) if output_property is not None else None
        )
        try:
            if target_output is False:
                self.set_output(False)
            if "reference_source" in properties:
                self.set_reference_source(
                    string_value(properties["reference_source"].value)
                )
            if "frequency" in properties:
                self.set_frequency(quantity_value(properties["frequency"].value, "Hz"))
            if "power" in properties:
                self.set_power(quantity_value(properties["power"].value, "dBm"))
            if target_output is True:
                self.set_output(True)
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        return CollectReceipt(readback=InstrumentReadback())

    def set_frequency(self, frequency_hz: float) -> None:
        self.transport.write(f":SOUR:FREQ {format_number(frequency_hz)}")

    def frequency(self) -> float:
        return parse_float(self.transport.query(":SOUR:FREQ?"))

    def set_power(self, power_dbm: float) -> None:
        self.transport.write(f":SOUR:POW {format_number(power_dbm)}")

    def power(self) -> float:
        return parse_float(self.transport.query(":SOUR:POW?"))

    def set_output(self, enabled: bool) -> None:
        self.transport.write(f":OUTP {'ON' if enabled else 'OFF'}")

    def output_enabled(self) -> bool:
        return parse_bool(self.transport.query(":OUTP?"))

    def set_reference_source(self, source: str) -> None:
        command = {"internal": "INT", "external": "EXT"}.get(source)
        if command is None:
            raise ValueError("SGS100A reference source must be internal or external")
        self.transport.write(f":SOUR:ROSC:SOUR {command}")

    def reference_source(self) -> str:
        response = self.transport.query(":SOUR:ROSC:SOUR?").strip().upper()
        if response.startswith("INT"):
            return "internal"
        if response.startswith("EXT"):
            return "external"
        raise ValueError(f"SGS100A returned unknown reference source {response!r}")

    def identify(self) -> ScpiIdentity:
        identity = parse_identity(self.transport.query("*IDN?"))
        manufacturer = identity.manufacturer.upper().replace(" ", "")
        if "ROHDE&SCHWARZ" not in manufacturer or identity.model.upper() != "SGS100A":
            raise ValueError(f"expected an R&S SGS100A, got {identity.raw!r}")
        self._identity = identity
        return identity

    def disconnect(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """The CW source has no acquisition operation to abort."""


__all__ = ["RohdeSchwarzSGS100A"]
