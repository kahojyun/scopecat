"""Minimal Rohde & Schwarz SGS100A continuous-wave source driver."""

from __future__ import annotations

from typing import override

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    Change,
    DriverOutcome,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    ObjectInstrumentDriver,
    instrument_driver,
    read,
    update,
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
        return readback.with_observation_metadata(metadata)

    @update(
        RFOutputInterface.frequency,
        RFOutputInterface.power,
        RFOutputInterface.output_enabled,
        RFOutputInterface.reference_source,
    )
    def update_output(
        self,
        *,
        frequency: Change[Quantity],
        power: Change[Quantity],
        output_enabled: Change[bool],
        reference_source: Change[ReferenceSource],
    ) -> DriverOutcome[None]:
        try:
            observed_output = self.read_output_enabled()
            if observed_output:
                self.write_output_enabled(False)
            self._establish_cw_state()
            if reference_source.requested:
                self.write_reference_source(reference_source.value)
            if frequency.requested:
                self.write_frequency(frequency.value)
            if power.requested:
                self.write_power(power.value)
            final_output = (
                output_enabled.value if output_enabled.requested else observed_output
            )
            if final_output:
                self.write_output_enabled(True)
            return DriverSuccess(None)
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    @read(RFOutputInterface.frequency)
    def read_frequency(self) -> Quantity:
        # FREQ? includes the downstream display offset, which does not shift RF.
        displayed = query_float(self.transport, ":SOUR:FREQ?")
        offset = query_float(self.transport, ":SOUR:FREQ:OFFS?")
        return Quantity(displayed - offset, "Hz")

    def write_frequency(self, value: Quantity) -> None:
        self.transport.write(f":SOUR:FREQ {format_number(quantity_value(value, 'Hz'))}")

    @read(RFOutputInterface.power)
    def read_power(self) -> Quantity:
        return Quantity(query_float(self.transport, ":SOUR:POW:POW?"), "dBm")

    def set_frequency(self, frequency_hz: float) -> None:
        self.write_frequency(Quantity(frequency_hz, "Hz"))

    def set_power(self, power_dbm: float) -> None:
        self.write_power(Quantity(power_dbm, "dBm"))

    def set_output(self, enabled: bool) -> None:
        self.write_output_enabled(enabled)

    def set_reference_source(self, source: ReferenceSource) -> None:
        self.write_reference_source(source)

    def write_power(self, value: Quantity) -> None:
        self.transport.write(
            f":SOUR:POW:POW {format_number(quantity_value(value, 'dBm'))}"
        )

    @read(RFOutputInterface.output_enabled)
    def read_output_enabled(self) -> bool:
        return query_bool(self.transport, ":OUTP?")

    def write_output_enabled(self, value: bool) -> None:
        self.transport.write(f":OUTP {'ON' if value else 'OFF'}")

    @read(RFOutputInterface.reference_source)
    def read_reference_source(self) -> ReferenceSource:
        response = query_text(self.transport, ":SOUR:ROSC:SOUR?").upper()
        if response.startswith("INT"):
            return "internal"
        if response.startswith("EXT"):
            return "external"
        raise ValueError(f"SGS100A returned unknown reference source {response!r}")

    def write_reference_source(self, value: ReferenceSource) -> None:
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
