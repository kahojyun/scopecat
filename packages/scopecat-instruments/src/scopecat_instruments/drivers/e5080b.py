"""Minimal Keysight E5080B linear S-parameter sweep driver."""

from __future__ import annotations

from typing import override

import numpy as np
from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import MeasurementArray
from scopecat.sdk.instruments import (
    DriverOutcome,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    ObjectInstrumentDriver,
    implements,
    instrument_driver,
    read,
    write,
)
from scopecat.sdk.instruments.scpi import (
    ScpiIdentity,
    ScpiTransport,
    format_number,
    query_bool,
    query_csv_floats,
    query_float,
    query_identity,
    query_int,
    query_string,
    query_text,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    NetworkTrace,
    apply_unknown,
    collect_unknown,
    quantity_value,
)
from scopecat_instruments.driver_observations import NetworkSweepObservation
from scopecat_instruments.interface_declarations import (
    NetworkSweepInterface,
    SParameter,
)
from scopecat_instruments.package_manifest import KEYSIGHT_E5080B_DRIVER


@instrument_driver(
    KEYSIGHT_E5080B_DRIVER.id,
    KEYSIGHT_E5080B_DRIVER.implementation_version,
    interfaces=(NetworkSweepInterface,),
    label="Keysight E5080B",
    description="Minimal two-port linear S-parameter sweep driver.",
)
class KeysightE5080B(ObjectInstrumentDriver):
    """Two-port linear sweep configuration and ASCII complex data retrieval."""

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

    @override
    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        self._require_linear_sweep()
        readback = super().read_state(request)
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Keysight",
            "model": "E5080B",
            "channel": self.channel,
            "measurement": self.measurement,
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return readback.with_observation_metadata(metadata)

    @override
    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        try:
            self._establish_linear_sweep()
            return super().apply_state(request)
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    @implements(NetworkSweepInterface.sweep)
    def sweep(self) -> DriverOutcome[NetworkSweepObservation]:
        try:
            trace = self.acquire_trace()
            return DriverSuccess(
                NetworkSweepObservation(
                    frequency=MeasurementArray.create(
                        dtype="float64",
                        unit="Hz",
                        values=np.asarray(trace.frequencies_hz, dtype=np.float64),
                    ),
                    s_parameter=MeasurementArray.create(
                        dtype="complex128",
                        unit="ratio",
                        values=np.asarray(trace.values, dtype=np.complex128),
                    ),
                    evidence={
                        "manufacturer": "Keysight",
                        "model": "E5080B",
                        "channel": self.channel,
                        "measurement": self.measurement,
                        "transfer_format": "ASCII",
                    },
                ),
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
        self._establish_linear_sweep()
        self.set_start_frequency(settings.start_frequency_hz)
        self.set_stop_frequency(settings.stop_frequency_hz)
        self.set_points(settings.points)
        self.set_if_bandwidth(settings.if_bandwidth_hz)
        self.set_source_power(settings.source_power_dbm)
        self.set_s_parameter(settings.s_parameter)

    def sweep_settings(self) -> LinearSweepSettings:
        return LinearSweepSettings(
            start_frequency_hz=query_float(
                self.transport,
                f"SENS{self.channel}:FREQ:STAR?",
            ),
            stop_frequency_hz=query_float(
                self.transport,
                f"SENS{self.channel}:FREQ:STOP?",
            ),
            points=query_int(self.transport, f"SENS{self.channel}:SWE:POIN?"),
            if_bandwidth_hz=query_float(
                self.transport,
                f"SENS{self.channel}:BWID?",
            ),
            source_power_dbm=query_float(
                self.transport,
                f"SOUR{self.channel}:POW?",
            ),
            s_parameter=self.read_s_parameter(),
        )

    @read(NetworkSweepInterface.start_frequency)
    def read_start_frequency(self) -> Quantity:
        return Quantity(
            query_float(self.transport, f"SENS{self.channel}:FREQ:STAR?"), "Hz"
        )

    @write(NetworkSweepInterface.start_frequency)
    def write_start_frequency(self, value: Quantity) -> None:
        self.set_start_frequency(quantity_value(value, "Hz"))

    @read(NetworkSweepInterface.stop_frequency)
    def read_stop_frequency(self) -> Quantity:
        return Quantity(
            query_float(self.transport, f"SENS{self.channel}:FREQ:STOP?"), "Hz"
        )

    @write(NetworkSweepInterface.stop_frequency)
    def write_stop_frequency(self, value: Quantity) -> None:
        self.set_stop_frequency(quantity_value(value, "Hz"))

    @read(NetworkSweepInterface.points)
    def read_points(self) -> int:
        return query_int(self.transport, f"SENS{self.channel}:SWE:POIN?")

    @write(NetworkSweepInterface.points)
    def write_points(self, value: int) -> None:
        self.set_points(value)

    @read(NetworkSweepInterface.if_bandwidth)
    def read_if_bandwidth(self) -> Quantity:
        return Quantity(query_float(self.transport, f"SENS{self.channel}:BWID?"), "Hz")

    @write(NetworkSweepInterface.if_bandwidth)
    def write_if_bandwidth(self, value: Quantity) -> None:
        self.set_if_bandwidth(quantity_value(value, "Hz"))

    @read(NetworkSweepInterface.source_power)
    def read_source_power(self) -> Quantity:
        return Quantity(query_float(self.transport, f"SOUR{self.channel}:POW?"), "dBm")

    @write(NetworkSweepInterface.source_power)
    def write_source_power(self, value: Quantity) -> None:
        self.set_source_power(quantity_value(value, "dBm"))

    @read(NetworkSweepInterface.s_parameter)
    def read_s_parameter(self) -> SParameter:
        return self._read_s_parameter()

    @write(NetworkSweepInterface.s_parameter)
    def write_s_parameter(self, value: SParameter) -> None:
        self.set_s_parameter(value)

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

    def set_s_parameter(self, s_parameter: SParameter) -> None:
        if s_parameter not in {"S11", "S21", "S12", "S22"}:
            raise ValueError("v1 E5080B driver supports S11, S21, S12, or S22")
        self.transport.write(
            f'CALC{self.channel}:MEAS{self.measurement}:PAR "{s_parameter}"'
        )

    def _read_s_parameter(self) -> SParameter:
        response = query_string(
            self.transport,
            f"CALC{self.channel}:MEAS{self.measurement}:PAR?",
        )
        match response:
            case "S11" | "S21" | "S12" | "S22":
                return response
            case _:
                raise ValueError(f"E5080B returned unsupported parameter {response!r}")

    def single_trigger(self) -> None:
        self.transport.write(f"INIT{self.channel}:IMM;*WAI")

    def read_trace_ascii(self) -> NetworkTrace:
        self.transport.write("FORM:DATA ASC,0")
        frequencies = query_csv_floats(
            self.transport,
            f"CALC{self.channel}:MEAS{self.measurement}:X?",
        )
        interleaved = query_csv_floats(
            self.transport,
            f"CALC{self.channel}:MEAS{self.measurement}:DATA:SDAT?",
        )
        if len(interleaved) % 2:
            raise ValueError("E5080B returned an odd number of complex components")
        values = tuple(
            complex(interleaved[index], interleaved[index + 1])
            for index in range(0, len(interleaved), 2)
        )
        return NetworkTrace(frequencies_hz=frequencies, values=values)

    def acquire_trace(self) -> NetworkTrace:
        self._require_linear_sweep()
        trigger_source = self._trigger_source()
        try:
            self._set_trigger_source("MAN")
            averaging_enabled = self._averaging_enabled()
            try:
                # v1 returns one fresh sweep; averaging is outside its contract.
                if averaging_enabled:
                    self._set_averaging(False)
                self.single_trigger()
                return self.read_trace_ascii()
            finally:
                if averaging_enabled:
                    self._set_averaging(True)
        finally:
            self._set_trigger_source(trigger_source)

    def _establish_linear_sweep(self) -> None:
        self.transport.write(f"SENS{self.channel}:SWE:TYPE LIN")

    def _require_linear_sweep(self) -> None:
        sweep_type = query_text(
            self.transport,
            f"SENS{self.channel}:SWE:TYPE?",
        ).upper()
        if sweep_type not in {"LIN", "LINEAR"}:
            raise ValueError(
                f"E5080B linear-sweep profile does not support {sweep_type!r}"
            )

    def _trigger_source(self) -> str:
        response = query_string(self.transport, "TRIG:SOUR?").upper()
        source = {
            "EXTERNAL": "EXT",
            "EXT": "EXT",
            "IMMEDIATE": "IMM",
            "IMM": "IMM",
            "MANUAL": "MAN",
            "MAN": "MAN",
        }.get(response)
        if source is None:
            raise ValueError(f"E5080B returned unknown trigger source {response!r}")
        return source

    def _set_trigger_source(self, source: str) -> None:
        self.transport.write(f"TRIG:SOUR {source}")

    def _averaging_enabled(self) -> bool:
        return query_bool(self.transport, f"SENS{self.channel}:AVER?")

    def _set_averaging(self, enabled: bool) -> None:
        self.transport.write(f"SENS{self.channel}:AVER {'ON' if enabled else 'OFF'}")

    def identify(self) -> ScpiIdentity:
        identity = query_identity(self.transport)
        if (
            "KEYSIGHT" not in identity.manufacturer.upper()
            or identity.model.upper() != "E5080B"
        ):
            raise ValueError(f"expected a Keysight E5080B, got {identity.raw!r}")
        self._identity = identity
        return identity

    @override
    def disconnect(self) -> None:
        self.transport.close()

    @override
    def abort(self) -> None:
        self.transport.write("ABOR")


__all__ = ["KeysightE5080B", "LinearSweepSettings"]
