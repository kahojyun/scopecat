"""Minimal Rohde & Schwarz SGS100A continuous-wave source driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    InstrumentDescription,
    InvokeReceipt,
)
from scopecat.sdk.instruments.scpi import (
    ScpiIdentity,
    ScpiTransport,
    format_number,
    query_bool,
    query_float,
    query_identity,
    query_text,
)

from scopecat_instruments._support import (
    apply_unknown,
    bool_value,
    quantity_value,
    state_property,
    string_value,
    unsupported_invoke,
)
from scopecat_instruments.driver_ids import ROHDE_SCHWARZ_SGS100A
from scopecat_instruments.interfaces import rf_output_interface
from scopecat_instruments.members import (
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
)


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
        self._require_cw_state()
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
                    RF_OUTPUT_FREQUENCY,
                    Quantity(self.frequency(), "Hz"),
                ),
                state_property(
                    RF_OUTPUT_POWER,
                    Quantity(self.power(), "dBm"),
                ),
                state_property(RF_OUTPUT_ENABLED, self.output_enabled()),
                state_property(
                    RF_OUTPUT_REFERENCE_SOURCE,
                    self.reference_source(),
                ),
            ],
            metadata=metadata,
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        properties = {
            assignment.target: assignment for assignment in request.assignments
        }
        output_property = properties.get(RF_OUTPUT_ENABLED)
        target_output = (
            bool_value(output_property.value) if output_property is not None else None
        )
        try:
            observed_output = self.output_enabled()
            if observed_output:
                self.set_output(False)
            self._establish_cw_state()
            if RF_OUTPUT_REFERENCE_SOURCE in properties:
                self.set_reference_source(
                    string_value(properties[RF_OUTPUT_REFERENCE_SOURCE].value)
                )
            if RF_OUTPUT_FREQUENCY in properties:
                self.set_frequency(
                    quantity_value(properties[RF_OUTPUT_FREQUENCY].value, "Hz")
                )
            if RF_OUTPUT_POWER in properties:
                self.set_power(quantity_value(properties[RF_OUTPUT_POWER].value, "dBm"))
            final_output = observed_output if target_output is None else target_output
            if final_output:
                self.set_output(True)
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
        return CollectReceipt(readback=InstrumentReadback())

    def set_frequency(self, frequency_hz: float) -> None:
        self.transport.write(f":SOUR:FREQ {format_number(frequency_hz)}")

    def frequency(self) -> float:
        # FREQ? includes the downstream display offset, which does not shift RF.
        displayed = query_float(self.transport, ":SOUR:FREQ?")
        offset = query_float(self.transport, ":SOUR:FREQ:OFFS?")
        return displayed - offset

    def set_power(self, power_dbm: float) -> None:
        self.transport.write(f":SOUR:POW:POW {format_number(power_dbm)}")

    def power(self) -> float:
        return query_float(self.transport, ":SOUR:POW:POW?")

    def set_output(self, enabled: bool) -> None:
        self.transport.write(f":OUTP {'ON' if enabled else 'OFF'}")

    def output_enabled(self) -> bool:
        return query_bool(self.transport, ":OUTP?")

    def set_reference_source(self, source: str) -> None:
        command = {"internal": "INT", "external": "EXT"}.get(source)
        if command is None:
            raise ValueError("SGS100A reference source must be internal or external")
        self.transport.write(f":SOUR:ROSC:SOUR {command}")

    def reference_source(self) -> str:
        response = query_text(self.transport, ":SOUR:ROSC:SOUR?").upper()
        if response.startswith("INT"):
            return "internal"
        if response.startswith("EXT"):
            return "external"
        raise ValueError(f"SGS100A returned unknown reference source {response!r}")

    def _establish_cw_state(self) -> None:
        self.transport.write(":SOUR:OPM NORM")
        self.transport.write(":SOUR:IQ:STAT OFF")
        self.transport.write(":SOUR:PULM:STAT OFF")

    def _require_cw_state(self) -> None:
        operation_mode = query_text(self.transport, ":SOUR:OPM?").upper()
        iq_modulation = query_bool(self.transport, ":SOUR:IQ:STAT?")
        pulse_modulation = query_bool(self.transport, ":SOUR:PULM:STAT?")
        incompatible: list[str] = []
        if operation_mode not in {"NORM", "NORMAL"}:
            incompatible.append(f"mode={operation_mode}")
        if iq_modulation:
            incompatible.append("iq_modulation=ON")
        if pulse_modulation:
            incompatible.append("pulse_modulation=ON")
        if incompatible:
            raise ValueError(
                "SGS100A is outside the CW adapter state: " + ", ".join(incompatible)
            )

    def identify(self) -> ScpiIdentity:
        identity = query_identity(self.transport)
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
