"""Minimal Keysight E5080B linear S-parameter sweep driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
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
    LinearSweepSettings,
    NetworkTrace,
    ScpiIdentity,
    apply_unknown,
    collect_unknown,
    format_number,
    int_value,
    not_applied,
    not_collected,
    parse_bool,
    parse_csv_floats,
    parse_float,
    parse_identity,
    parse_int,
    quantity_value,
    state_property,
    string_value,
    strip_scpi_string,
    unsupported_invoke,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.driver_ids import KEYSIGHT_E5080B
from scopecat_instruments.interfaces import (
    NETWORK_SWEEP,
    network_sweep_interface,
)
from scopecat_instruments.transport import ScpiTransport


class KeysightE5080B:
    """Two-port linear sweep configuration and ASCII complex data retrieval."""

    implementation_id = KEYSIGHT_E5080B
    implementation_version = "v1"

    def __init__(
        self,
        instrument_id: str,
        transport: ScpiTransport,
        *,
        channel: int = 1,
        measurement: int = 1,
    ) -> None:
        if channel < 1 or measurement < 1:
            raise ValueError("VNA channel and measurement numbers must be positive")
        self.instrument_id = instrument_id
        self.transport = transport
        self.channel = channel
        self.measurement = measurement
        self._identity: ScpiIdentity | None = None

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Keysight E5080B",
            description=(
                "Minimal two-port linear S-parameter sweep driver using one "
                "existing standard measurement. Calibration management and "
                "option-dependent applications are outside the v1 boundary."
            ),
            interfaces=[network_sweep_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        settings = self.sweep_settings()
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Keysight",
            "model": "E5080B",
            "channel": self.channel,
            "measurement": self.measurement,
            "sweep_type": "linear",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                state_property(
                    NETWORK_SWEEP,
                    "start_frequency",
                    Quantity(settings.start_frequency_hz, "Hz"),
                ),
                state_property(
                    NETWORK_SWEEP,
                    "stop_frequency",
                    Quantity(settings.stop_frequency_hz, "Hz"),
                ),
                state_property(NETWORK_SWEEP, "points", settings.points),
                state_property(
                    NETWORK_SWEEP,
                    "if_bandwidth",
                    Quantity(settings.if_bandwidth_hz, "Hz"),
                ),
                state_property(
                    NETWORK_SWEEP,
                    "source_power",
                    Quantity(settings.source_power_dbm, "dBm"),
                ),
                state_property(
                    NETWORK_SWEEP,
                    "s_parameter",
                    settings.s_parameter,
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
        try:
            self.transport.write(f"SENS{self.channel}:SWE:TYPE LIN")
            if "start_frequency" in properties:
                self.set_start_frequency(
                    quantity_value(properties["start_frequency"].value, "Hz")
                )
            if "stop_frequency" in properties:
                self.set_stop_frequency(
                    quantity_value(properties["stop_frequency"].value, "Hz")
                )
            if "points" in properties:
                self.set_points(int_value(properties["points"].value))
            if "if_bandwidth" in properties:
                self.set_if_bandwidth(
                    quantity_value(properties["if_bandwidth"].value, "Hz")
                )
            if "source_power" in properties:
                self.set_source_power(
                    quantity_value(properties["source_power"].value, "dBm")
                )
            if "s_parameter" in properties:
                self.set_s_parameter(string_value(properties["s_parameter"].value))
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        try:
            trace = self.acquire_trace()
            values: dict[str, MeasurementValue] = {}
            for request in command.requests:
                if request.result_id == "frequency":
                    values[request.id] = MeasurementArray(
                        dtype="float64",
                        unit="Hz",
                        shape=[len(trace.frequencies_hz)],
                        values=[
                            Quantity(frequency_hz, "Hz")
                            for frequency_hz in trace.frequencies_hz
                        ],
                    )
                else:
                    values[request.id] = MeasurementArray(
                        dtype="complex128",
                        unit="ratio",
                        shape=[len(trace.values)],
                        values=[
                            ComplexQuantity(
                                real=value.real,
                                imag=value.imag,
                                unit="ratio",
                            )
                            for value in trace.values
                        ],
                    )
            return CollectReceipt(
                readback=InstrumentReadback(
                    values=values,
                    metadata={
                        "manufacturer": "Keysight",
                        "model": "E5080B",
                        "channel": self.channel,
                        "measurement": self.measurement,
                        "transfer_format": "ASCII",
                    },
                )
            )
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def configure_linear_sweep(self, settings: LinearSweepSettings) -> None:
        if settings.start_frequency_hz >= settings.stop_frequency_hz:
            raise ValueError(
                "linear sweep start frequency must be below stop frequency"
            )
        if settings.points < 2:
            raise ValueError("linear sweep requires at least two points")
        self.transport.write(f"SENS{self.channel}:SWE:TYPE LIN")
        self.set_start_frequency(settings.start_frequency_hz)
        self.set_stop_frequency(settings.stop_frequency_hz)
        self.set_points(settings.points)
        self.set_if_bandwidth(settings.if_bandwidth_hz)
        self.set_source_power(settings.source_power_dbm)
        self.set_s_parameter(settings.s_parameter)

    def sweep_settings(self) -> LinearSweepSettings:
        return LinearSweepSettings(
            start_frequency_hz=parse_float(
                self.transport.query(f"SENS{self.channel}:FREQ:STAR?")
            ),
            stop_frequency_hz=parse_float(
                self.transport.query(f"SENS{self.channel}:FREQ:STOP?")
            ),
            points=parse_int(self.transport.query(f"SENS{self.channel}:SWE:POIN?")),
            if_bandwidth_hz=parse_float(
                self.transport.query(f"SENS{self.channel}:BWID?")
            ),
            source_power_dbm=parse_float(
                self.transport.query(f"SOUR{self.channel}:POW?")
            ),
            s_parameter=self.s_parameter(),
        )

    def set_start_frequency(self, frequency_hz: float) -> None:
        self.transport.write(
            f"SENS{self.channel}:FREQ:STAR {format_number(frequency_hz)}"
        )

    def set_stop_frequency(self, frequency_hz: float) -> None:
        self.transport.write(
            f"SENS{self.channel}:FREQ:STOP {format_number(frequency_hz)}"
        )

    def set_points(self, points: int) -> None:
        if points < 2:
            raise ValueError("linear sweep requires at least two points")
        self.transport.write(f"SENS{self.channel}:SWE:POIN {points}")

    def set_if_bandwidth(self, bandwidth_hz: float) -> None:
        self.transport.write(f"SENS{self.channel}:BWID {format_number(bandwidth_hz)}")

    def set_source_power(self, power_dbm: float) -> None:
        self.transport.write(f"SOUR{self.channel}:POW {format_number(power_dbm)}")

    def set_s_parameter(self, s_parameter: str) -> None:
        if s_parameter not in {"S11", "S21", "S12", "S22"}:
            raise ValueError("v1 E5080B driver supports S11, S21, S12, or S22")
        self.transport.write(
            f'CALC{self.channel}:MEAS{self.measurement}:PAR "{s_parameter}"'
        )

    def s_parameter(self) -> str:
        response = strip_scpi_string(
            self.transport.query(f"CALC{self.channel}:MEAS{self.measurement}:PAR?")
        )
        if response not in {"S11", "S21", "S12", "S22"}:
            raise ValueError(f"E5080B returned unsupported parameter {response!r}")
        return response

    def single_trigger(self) -> None:
        self.transport.write(f"INIT{self.channel}:IMM;*WAI")

    def set_continuous_trigger(self, enabled: bool) -> None:
        self.transport.write(f"INIT{self.channel}:CONT {'ON' if enabled else 'OFF'}")

    def continuous_trigger_enabled(self) -> bool:
        return parse_bool(self.transport.query(f"INIT{self.channel}:CONT?"))

    def read_trace_ascii(self) -> NetworkTrace:
        self.transport.write("FORM:DATA ASC,0")
        frequencies = parse_csv_floats(
            self.transport.query(f"CALC{self.channel}:MEAS{self.measurement}:X?")
        )
        interleaved = parse_csv_floats(
            self.transport.query(
                f"CALC{self.channel}:MEAS{self.measurement}:DATA:SDAT?"
            )
        )
        if len(interleaved) % 2:
            raise ValueError("E5080B returned an odd number of complex components")
        values = tuple(
            complex(interleaved[index], interleaved[index + 1])
            for index in range(0, len(interleaved), 2)
        )
        return NetworkTrace(frequencies_hz=frequencies, values=values)

    def acquire_trace(self) -> NetworkTrace:
        restore_continuous = self.continuous_trigger_enabled()
        try:
            if restore_continuous:
                self.set_continuous_trigger(False)
            self.single_trigger()
            return self.read_trace_ascii()
        finally:
            if restore_continuous:
                self.set_continuous_trigger(True)

    def identify(self) -> ScpiIdentity:
        identity = parse_identity(self.transport.query("*IDN?"))
        if (
            "KEYSIGHT" not in identity.manufacturer.upper()
            or identity.model.upper() != "E5080B"
        ):
            raise ValueError(f"expected a Keysight E5080B, got {identity.raw!r}")
        self._identity = identity
        return identity

    def disconnect(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        self.transport.write("ABOR")


__all__ = ["KeysightE5080B", "LinearSweepSettings"]
