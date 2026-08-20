"""Minimal Rohde & Schwarz SGS100A continuous-wave source driver."""

from __future__ import annotations

from typing import cast, override

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    DriverOutcome,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    ObjectInstrumentDriver,
    instrument_driver,
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
    quantity_value,
)
from scopecat_instruments.interface_declarations import (
    ReferenceSource,
    RFOutputInterface,
)
from scopecat_instruments.members import (
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
)
from scopecat_instruments.package_manifest import ROHDE_SCHWARZ_SGS100A_DRIVER


@instrument_driver(
    ROHDE_SCHWARZ_SGS100A_DRIVER.id,
    ROHDE_SCHWARZ_SGS100A_DRIVER.implementation_version,
    interfaces=(RFOutputInterface,),
    label="R&S SGS100A",
    description="Minimal continuous-wave RF source driver.",
)
class RohdeSchwarzSGS100A(ObjectInstrumentDriver):
    """CW frequency, power, RF output, and reference source controls."""

    def __init__(self, instrument_id: str, transport: ScpiTransport) -> None:
        self.instrument_id = instrument_id
        self.transport = transport
        self._identity: ScpiIdentity | None = None

    @override
    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        self._require_cw_state()
        readback = super().read_state(request)
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Rohde & Schwarz",
            "model": "SGS100A",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return DriverStateReadback(
            observations=readback.observations,
            metadata=metadata,
        )

    @override
    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        values = request.values
        target_output = cast("bool | None", values.get(RF_OUTPUT_ENABLED))
        try:
            observed_output = self.output_enabled
            if observed_output:
                self.output_enabled = False
            self._establish_cw_state()
            if RF_OUTPUT_REFERENCE_SOURCE in values:
                self.reference_source = cast(
                    "ReferenceSource", values[RF_OUTPUT_REFERENCE_SOURCE]
                )
            if RF_OUTPUT_FREQUENCY in values:
                self.frequency = cast("Quantity", values[RF_OUTPUT_FREQUENCY])
            if RF_OUTPUT_POWER in values:
                self.power = cast("Quantity", values[RF_OUTPUT_POWER])
            final_output = observed_output if target_output is None else target_output
            if final_output:
                self.output_enabled = True
            return DriverSuccess(None)
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    @property
    def frequency(self) -> Quantity:
        # FREQ? includes the downstream display offset, which does not shift RF.
        displayed = query_float(self.transport, ":SOUR:FREQ?")
        offset = query_float(self.transport, ":SOUR:FREQ:OFFS?")
        return Quantity(displayed - offset, "Hz")

    @frequency.setter
    def frequency(self, value: Quantity) -> None:
        self.transport.write(f":SOUR:FREQ {format_number(quantity_value(value, 'Hz'))}")

    @property
    def power(self) -> Quantity:
        return Quantity(query_float(self.transport, ":SOUR:POW:POW?"), "dBm")

    def set_frequency(self, frequency_hz: float) -> None:
        self.frequency = Quantity(frequency_hz, "Hz")

    def set_power(self, power_dbm: float) -> None:
        self.power = Quantity(power_dbm, "dBm")

    def set_output(self, enabled: bool) -> None:
        self.output_enabled = enabled

    def set_reference_source(self, source: ReferenceSource) -> None:
        self.reference_source = source

    @power.setter
    def power(self, value: Quantity) -> None:
        self.transport.write(
            f":SOUR:POW:POW {format_number(quantity_value(value, 'dBm'))}"
        )

    @property
    def output_enabled(self) -> bool:
        return query_bool(self.transport, ":OUTP?")

    @output_enabled.setter
    def output_enabled(self, value: bool) -> None:
        self.transport.write(f":OUTP {'ON' if value else 'OFF'}")

    @property
    def reference_source(self) -> ReferenceSource:
        response = query_text(self.transport, ":SOUR:ROSC:SOUR?").upper()
        if response.startswith("INT"):
            return "internal"
        if response.startswith("EXT"):
            return "external"
        raise ValueError(f"SGS100A returned unknown reference source {response!r}")

    @reference_source.setter
    def reference_source(self, value: ReferenceSource) -> None:
        command = {"internal": "INT", "external": "EXT"}.get(value)
        if command is None:
            raise ValueError("SGS100A reference source must be internal or external")
        self.transport.write(f":SOUR:ROSC:SOUR {command}")

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

    @override
    def disconnect(self) -> None:
        self.transport.close()

    @override
    def abort(self) -> None:
        """The CW source has no acquisition operation to abort."""


__all__ = ["RohdeSchwarzSGS100A"]
