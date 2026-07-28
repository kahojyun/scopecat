"""Vendor-neutral virtual instruments backed by one shared world."""

from __future__ import annotations

from dataclasses import dataclass

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
    bool_value,
    execution_problem,
    int_value,
    not_applied,
    not_collected,
    quantity_value,
    state_property,
    string_value,
    unsupported_invoke,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.interfaces import (
    DC_SOURCE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)
from scopecat_instruments.virtual.world import VirtualLabWorld


class VirtualRfSource:
    implementation_id = "scopecat.virtual.rf_source"
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: VirtualLabWorld) -> None:
        self.instrument_id = instrument_id
        self.world = world
        self.world.rf_source(instrument_id)

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual RF source",
            description="Deterministic CW RF source connected to a VirtualLabWorld.",
            interfaces=[rf_output_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        with self.world.lock:
            source = self.world.rf_source(self.instrument_id)
            properties = [
                state_property(
                    RF_OUTPUT,
                    "frequency",
                    Quantity(source.frequency_hz, "Hz"),
                ),
                state_property(
                    RF_OUTPUT,
                    "power",
                    Quantity(source.power_dbm, "dBm"),
                ),
                state_property(RF_OUTPUT, "output_enabled", source.output_enabled),
                state_property(
                    RF_OUTPUT,
                    "reference_source",
                    source.reference_source,
                ),
            ]
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=properties,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        if problems:
            return not_applied(problems)
        for assignment in command.assignments:
            if assignment.property_id == "frequency":
                self.set_frequency(quantity_value(assignment.value, "Hz"))
            elif assignment.property_id == "power":
                self.set_power(quantity_value(assignment.value, "dBm"))
            elif assignment.property_id == "output_enabled":
                self.set_output(bool_value(assignment.value))
            else:
                self.set_reference_source(string_value(assignment.value))
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        return CollectReceipt(readback=InstrumentReadback())

    def set_frequency(self, frequency_hz: float) -> None:
        with self.world.lock:
            self.world.rf_source(self.instrument_id).frequency_hz = frequency_hz

    def frequency(self) -> float:
        with self.world.lock:
            return self.world.rf_source(self.instrument_id).frequency_hz

    def set_power(self, power_dbm: float) -> None:
        with self.world.lock:
            self.world.rf_source(self.instrument_id).power_dbm = power_dbm

    def power(self) -> float:
        with self.world.lock:
            return self.world.rf_source(self.instrument_id).power_dbm

    def set_output(self, enabled: bool) -> None:
        with self.world.lock:
            self.world.rf_source(self.instrument_id).output_enabled = enabled

    def output_enabled(self) -> bool:
        with self.world.lock:
            return self.world.rf_source(self.instrument_id).output_enabled

    def set_reference_source(self, source: str) -> None:
        if source not in {"internal", "external"}:
            raise ValueError("reference source must be internal or external")
        with self.world.lock:
            self.world.rf_source(self.instrument_id).reference_source = source

    def reference_source(self) -> str:
        with self.world.lock:
            return self.world.rf_source(self.instrument_id).reference_source

    def cleanup(self) -> None:
        pass

    def close(self) -> None:
        pass

    def abort(self) -> None:
        pass


class VirtualDcSource:
    implementation_id = "scopecat.virtual.dc_source"
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: VirtualLabWorld) -> None:
        self.instrument_id = instrument_id
        self.world = world
        self.world.dc_source(instrument_id)

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual DC source",
            description=(
                "Voltage/current source whose active level contributes flux and "
                "heating to the shared VirtualLabWorld."
            ),
            interfaces=[dc_source_interface(), dc_monitor_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            mode = source.source_mode
            range_property = (
                (
                    "voltage_range",
                    Quantity(source.voltage_range_v, "V"),
                )
                if mode == "voltage"
                else (
                    "current_range",
                    Quantity(source.current_range_a, "A"),
                )
            )
            level_property = (
                (
                    "voltage_level",
                    Quantity(source.voltage_level_v, "V"),
                )
                if mode == "voltage"
                else (
                    "current_level",
                    Quantity(source.current_level_a, "A"),
                )
            )
            properties = [
                state_property(DC_SOURCE, "source_mode", mode),
                state_property(
                    DC_SOURCE,
                    range_property[0],
                    range_property[1],
                ),
                state_property(
                    DC_SOURCE,
                    level_property[0],
                    level_property[1],
                ),
                state_property(
                    DC_SOURCE,
                    "voltage_protection",
                    Quantity(source.voltage_protection_v, "V"),
                ),
                state_property(
                    DC_SOURCE,
                    "current_protection",
                    Quantity(source.current_protection_a, "A"),
                ),
                state_property(DC_SOURCE, "output_enabled", source.output_enabled),
            ]
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=properties,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        properties = {
            assignment.property_id: assignment for assignment in command.assignments
        }
        if problems:
            return not_applied(problems)
        implied_modes = {
            "voltage"
            for path in properties
            if path in {"voltage_range", "voltage_level"}
        } | {
            "current"
            for path in properties
            if path in {"current_range", "current_level"}
        }
        explicit_property = properties.get("source_mode")
        explicit_mode = (
            string_value(explicit_property.value)
            if explicit_property is not None
            else None
        )
        if len(implied_modes) > 1 or (
            explicit_mode is not None
            and implied_modes
            and explicit_mode not in implied_modes
        ):
            problems.append(
                execution_problem(
                    "virtual_dc_conflicting_source_modes",
                    "one command cannot mix voltage and current source properties",
                    "instrument_state_command",
                    "assignments",
                )
            )
        if problems:
            return not_applied(problems)
        mode = explicit_mode or next(iter(implied_modes), None)
        output_property = properties.get("output_enabled")
        target_output = (
            bool_value(output_property.value) if output_property is not None else None
        )
        if target_output is False:
            self.set_output(False)
        if mode is not None:
            self.set_source_mode(mode)
        if "voltage_range" in properties:
            self.set_voltage_range(
                quantity_value(properties["voltage_range"].value, "V")
            )
        if "current_range" in properties:
            self.set_current_range(
                quantity_value(properties["current_range"].value, "A")
            )
        if "voltage_level" in properties:
            self.set_voltage_level(
                quantity_value(properties["voltage_level"].value, "V")
            )
        if "current_level" in properties:
            self.set_current_level(
                quantity_value(properties["current_level"].value, "A")
            )
        if "voltage_protection" in properties:
            self.set_voltage_protection(
                quantity_value(properties["voltage_protection"].value, "V")
            )
        if "current_protection" in properties:
            self.set_current_protection(
                quantity_value(properties["current_protection"].value, "A")
            )
        if target_output is True:
            self.set_output(True)
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            result_id = (
                "monitored_current"
                if source.source_mode == "voltage"
                else "monitored_voltage"
            )
            requested_result_ids = {request.result_id for request in command.requests}
            if requested_result_ids != {result_id}:
                return not_collected(
                    [
                        execution_problem(
                            "virtual_dc_monitor_result_inactive",
                            f"{source.source_mode} mode provides only {result_id}",
                            "collect_command",
                            "requests",
                        )
                    ]
                )
            measured = (
                Quantity(source.voltage_level_v / 1.0e3, "A")
                if source.source_mode == "voltage"
                else Quantity(source.current_level_a * 1.0e3, "V")
            )
        return CollectReceipt(
            readback=InstrumentReadback(
                values={request.id: measured for request in command.requests},
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            )
        )

    def set_source_mode(self, mode: str) -> None:
        if mode not in {"voltage", "current"}:
            raise ValueError("source mode must be voltage or current")
        with self.world.lock:
            self.world.dc_source(self.instrument_id).source_mode = mode

    def source_mode(self) -> str:
        with self.world.lock:
            return self.world.dc_source(self.instrument_id).source_mode

    def set_voltage_range(self, value_v: float) -> None:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            source.source_mode = "voltage"
            source.voltage_range_v = value_v

    def set_current_range(self, value_a: float) -> None:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            source.source_mode = "current"
            source.current_range_a = value_a

    def set_voltage_level(self, value_v: float) -> None:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            source.source_mode = "voltage"
            source.voltage_level_v = value_v

    def set_current_level(self, value_a: float) -> None:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            source.source_mode = "current"
            source.current_level_a = value_a

    def set_voltage_protection(self, value_v: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).voltage_protection_v = value_v

    def set_current_protection(self, value_a: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).current_protection_a = value_a

    def set_output(self, enabled: bool) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).output_enabled = enabled

    def output_enabled(self) -> bool:
        with self.world.lock:
            return self.world.dc_source(self.instrument_id).output_enabled

    def cleanup(self) -> None:
        pass

    def close(self) -> None:
        pass

    def abort(self) -> None:
        pass


@dataclass(frozen=True)
class VirtualTemperatureTelemetry:
    scan_channel: int
    autoscan_enabled: bool
    temperature_k: float
    resistance_ohm: float
    reading_status: int
    heater_output: float
    heater_range: int
    heater_status: int


class VirtualTemperatureMonitor:
    implementation_id = "scopecat.virtual.temperature_monitor"
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: VirtualLabWorld) -> None:
        self.instrument_id = instrument_id
        self.world = world
        self.world.temperature_monitor(instrument_id)

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual temperature monitor",
            description="Read-only cryogenic telemetry from a VirtualLabWorld.",
            interfaces=[temperature_readout_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        telemetry = self.read_telemetry()
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
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        if problems:
            return not_applied(problems)
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        telemetry = self.read_telemetry()
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    request.id: (
                        Quantity(telemetry.temperature_k, "K")
                        if request.result_id == "temperature"
                        else Quantity(telemetry.resistance_ohm, "Ohm")
                    )
                    for request in command.requests
                },
                metadata={
                    "mode": "virtual",
                    "world_seed": self.world.seed,
                    "scan_channel": telemetry.scan_channel,
                    "reading_status": telemetry.reading_status,
                },
            )
        )

    def read_telemetry(self) -> VirtualTemperatureTelemetry:
        with self.world.lock:
            state = self.world.temperature_monitor(self.instrument_id)
            return VirtualTemperatureTelemetry(
                scan_channel=state.scan_channel,
                autoscan_enabled=state.autoscan_enabled,
                temperature_k=self.world.temperature_k(),
                resistance_ohm=self.world.sensor_resistance_ohm(),
                reading_status=state.reading_status,
                heater_output=state.heater_output,
                heater_range=state.heater_range,
                heater_status=state.heater_status,
            )

    def cleanup(self) -> None:
        pass

    def close(self) -> None:
        pass

    def abort(self) -> None:
        pass


class VirtualNetworkAnalyzer:
    implementation_id = "scopecat.virtual.vna"
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: VirtualLabWorld) -> None:
        self.instrument_id = instrument_id
        self.world = world
        self.world.vna(instrument_id)

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual VNA",
            description=(
                "Deterministic complex notch response whose resonance and linewidth "
                "follow shared flux and temperature state."
            ),
            interfaces=[network_sweep_interface()],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        settings = self.sweep_settings()
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
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_writable_command(command, self.describe())
        if problems:
            return not_applied(problems)
        with self.world.lock:
            state = self.world.vna(self.instrument_id)
            for assignment in command.assignments:
                if assignment.property_id == "start_frequency":
                    state.start_frequency_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.property_id == "stop_frequency":
                    state.stop_frequency_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.property_id == "points":
                    state.points = int_value(assignment.value)
                elif assignment.property_id == "if_bandwidth":
                    state.if_bandwidth_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.property_id == "source_power":
                    state.source_power_dbm = quantity_value(
                        assignment.value,
                        "dBm",
                    )
                else:
                    state.s_parameter = string_value(assignment.value)
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
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
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            )
        )

    def configure_linear_sweep(self, settings: LinearSweepSettings) -> None:
        if settings.start_frequency_hz >= settings.stop_frequency_hz:
            raise ValueError(
                "linear sweep start frequency must be below stop frequency"
            )
        if settings.points < 2:
            raise ValueError("linear sweep requires at least two points")
        if settings.s_parameter not in {"S11", "S21", "S12", "S22"}:
            raise ValueError("virtual VNA supports S11, S21, S12, or S22")
        with self.world.lock:
            state = self.world.vna(self.instrument_id)
            state.start_frequency_hz = settings.start_frequency_hz
            state.stop_frequency_hz = settings.stop_frequency_hz
            state.points = settings.points
            state.if_bandwidth_hz = settings.if_bandwidth_hz
            state.source_power_dbm = settings.source_power_dbm
            state.s_parameter = settings.s_parameter

    def sweep_settings(self) -> LinearSweepSettings:
        with self.world.lock:
            state = self.world.vna(self.instrument_id)
            return LinearSweepSettings(
                start_frequency_hz=state.start_frequency_hz,
                stop_frequency_hz=state.stop_frequency_hz,
                points=state.points,
                if_bandwidth_hz=state.if_bandwidth_hz,
                source_power_dbm=state.source_power_dbm,
                s_parameter=state.s_parameter,
            )

    def single_trigger(self) -> None:
        pass

    def read_trace_ascii(self) -> NetworkTrace:
        return self.world.network_trace(self.instrument_id)

    def acquire_trace(self) -> NetworkTrace:
        self.single_trigger()
        return self.read_trace_ascii()

    def cleanup(self) -> None:
        pass

    def close(self) -> None:
        pass

    def abort(self) -> None:
        pass


__all__ = [
    "VirtualDcSource",
    "VirtualNetworkAnalyzer",
    "VirtualRfSource",
    "VirtualTemperatureMonitor",
    "VirtualTemperatureTelemetry",
]
