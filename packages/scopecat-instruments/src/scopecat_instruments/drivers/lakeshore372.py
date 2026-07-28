"""Safe read-only Lake Shore Model 372 telemetry driver."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
)

from scopecat_instruments._support import (
    ScpiIdentity,
    apply_unknown,
    collect_unknown,
    not_applied,
    not_collected,
    parse_bool,
    parse_float,
    parse_identity,
    parse_int,
    state_property,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.interfaces import (
    TEMPERATURE_READOUT,
    temperature_readout_interface,
)
from scopecat_instruments.transport import ScpiTransport


@dataclass(frozen=True)
class LakeShore372Telemetry:
    scan_channel: int
    autoscan_enabled: bool
    temperature_k: float
    resistance_ohm: float
    reading_status: int
    heater_output: float
    heater_range: int
    heater_status: int


class LakeShore372:
    """Read K/R/status/scanner/sample-heater telemetry without control writes."""

    implementation_id = "scopecat.lakeshore.372"
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
            label="Lake Shore 372",
            description=(
                "Safety-first read-only telemetry driver. Heater setpoint, range, "
                "output mode, PID, and scanner writes are intentionally unsupported."
            ),
            interfaces=[temperature_readout_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        telemetry = self.read_telemetry()
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Lake Shore Cryotronics",
            "model": "372",
            "control_boundary": "read_only",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                state_property(
                    TEMPERATURE_READOUT,
                    "scan_channel",
                    telemetry.scan_channel,
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "autoscan_enabled",
                    telemetry.autoscan_enabled,
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "temperature",
                    Quantity(telemetry.temperature_k, "K"),
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "resistance",
                    Quantity(telemetry.resistance_ohm, "Ohm"),
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "reading_status",
                    telemetry.reading_status,
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "heater_output",
                    telemetry.heater_output,
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "heater_range",
                    telemetry.heater_range,
                ),
                state_property(
                    TEMPERATURE_READOUT,
                    "heater_status",
                    telemetry.heater_status,
                ),
            ],
            metadata=metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        if problems:
            return not_applied(problems)
        try:
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        try:
            telemetry = self.read_telemetry()
            values: dict[str, MeasurementValue] = {
                request.id: (
                    Quantity(telemetry.temperature_k, "K")
                    if request.result_id == "temperature"
                    else Quantity(telemetry.resistance_ohm, "Ohm")
                )
                for request in command.requests
            }
            return CollectReceipt(
                readback=InstrumentReadback(
                    values=values,
                    metadata={
                        "manufacturer": "Lake Shore Cryotronics",
                        "model": "372",
                        "scan_channel": telemetry.scan_channel,
                        "reading_status": telemetry.reading_status,
                        "heater_output": telemetry.heater_output,
                        "heater_range": telemetry.heater_range,
                        "heater_status": telemetry.heater_status,
                    },
                )
            )
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def read_telemetry(self) -> LakeShore372Telemetry:
        scan_response = self.transport.query("SCAN?").strip().split(",")
        if len(scan_response) != 2:
            raise ValueError("Lake Shore 372 returned malformed SCAN response")
        scan_channel = int(scan_response[0])
        autoscan_enabled = parse_bool(scan_response[1])
        channel = str(scan_channel)
        return LakeShore372Telemetry(
            scan_channel=scan_channel,
            autoscan_enabled=autoscan_enabled,
            temperature_k=parse_float(self.transport.query(f"KRDG? {channel}")),
            resistance_ohm=parse_float(self.transport.query(f"SRDG? {channel}")),
            reading_status=parse_int(self.transport.query(f"RDGST? {channel}")),
            heater_output=parse_float(self.transport.query("HTR?")),
            heater_range=parse_int(self.transport.query("RANGE? 0")),
            heater_status=parse_int(self.transport.query("HTRST? 0")),
        )

    def identify(self) -> ScpiIdentity:
        identity = parse_identity(self.transport.query("*IDN?"))
        manufacturer = identity.manufacturer.upper().replace(" ", "")
        model = identity.model.upper().replace(" ", "")
        if not (
            ("LSCI" in manufacturer or "LAKESHORE" in manufacturer)
            and model in {"MODEL372", "372"}
        ):
            raise ValueError(f"expected a Lake Shore 372, got {identity.raw!r}")
        self._identity = identity
        return identity

    def cleanup(self) -> None:
        """Read-only driver cleanup deliberately emits no instrument command."""

    def close(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """Read-only telemetry has no long-running operation to abort."""


__all__ = ["LakeShore372", "LakeShore372Telemetry"]
