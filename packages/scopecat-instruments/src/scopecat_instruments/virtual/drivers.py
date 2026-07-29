"""Vendor-neutral virtual instruments backed by one shared world."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementScalar,
    MeasurementValue,
)
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    InstrumentDescription,
    InvokeReceipt,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    NetworkTrace,
    bool_value,
    int_value,
    not_collected,
    quantity_value,
    state_properties_by_target,
    state_property,
    state_property_problem,
    string_value,
    unsupported_invoke,
)
from scopecat_instruments.driver_ids import (
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
)
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_IF_BANDWIDTH,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_SOURCE_POWER,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.virtual.world import VirtualLabWorld


class VirtualRfSource:
    implementation_id = VIRTUAL_RF_SOURCE
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
                    RF_OUTPUT_FREQUENCY,
                    Quantity(source.frequency_hz, "Hz"),
                ),
                state_property(
                    RF_OUTPUT_POWER,
                    Quantity(source.power_dbm, "dBm"),
                ),
                state_property(RF_OUTPUT_ENABLED, source.output_enabled),
                state_property(
                    RF_OUTPUT_REFERENCE_SOURCE,
                    source.reference_source,
                ),
            ]
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=properties,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        for assignment in request.assignments:
            if assignment.target == RF_OUTPUT_FREQUENCY:
                self.set_frequency(quantity_value(assignment.value, "Hz"))
            elif assignment.target == RF_OUTPUT_POWER:
                self.set_power(quantity_value(assignment.value, "dBm"))
            elif assignment.target == RF_OUTPUT_ENABLED:
                self.set_output(bool_value(assignment.value))
            else:
                self.set_reference_source(string_value(assignment.value))
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
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

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


class VirtualDcSource:
    implementation_id = VIRTUAL_DC_SOURCE
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
                    DC_SOURCE_VOLTAGE_RANGE,
                    Quantity(source.voltage_range_v, "V"),
                )
                if mode == "voltage"
                else (
                    DC_SOURCE_CURRENT_RANGE,
                    Quantity(source.current_range_a, "A"),
                )
            )
            level_property = (
                (
                    DC_SOURCE_VOLTAGE_LEVEL,
                    Quantity(source.voltage_level_v, "V"),
                )
                if mode == "voltage"
                else (
                    DC_SOURCE_CURRENT_LEVEL,
                    Quantity(source.current_level_a, "A"),
                )
            )
            properties = [
                state_property(DC_SOURCE_MODE, mode),
                state_property(
                    range_property[0],
                    range_property[1],
                ),
                state_property(
                    level_property[0],
                    level_property[1],
                ),
                state_property(
                    DC_SOURCE_VOLTAGE_PROTECTION,
                    Quantity(source.voltage_protection_v, "V"),
                ),
                state_property(
                    DC_SOURCE_CURRENT_PROTECTION,
                    Quantity(source.current_protection_a, "A"),
                ),
                state_property(DC_SOURCE_OUTPUT_ENABLED, source.output_enabled),
                state_property(
                    DC_MONITOR_MEASUREMENT_ENABLED,
                    source.measurement_enabled,
                ),
                state_property(
                    DC_MONITOR_INTEGRATION_CYCLES,
                    source.integration_cycles,
                ),
                state_property(
                    DC_MONITOR_MEASUREMENT_DELAY,
                    Quantity(source.measurement_delay_s, "s"),
                ),
            ]
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=properties,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        baseline = self.read_state()
        properties = {
            assignment.target: assignment for assignment in request.assignments
        }
        baseline_properties = state_properties_by_target(baseline)
        current_mode = string_value(baseline_properties[DC_SOURCE_MODE].value)
        current_output = bool_value(baseline_properties[DC_SOURCE_OUTPUT_ENABLED].value)
        mode_property = properties.get(DC_SOURCE_MODE)
        target_mode = (
            string_value(mode_property.value)
            if mode_property is not None
            else current_mode
        )
        output_property = properties.get(DC_SOURCE_OUTPUT_ENABLED)
        target_output = (
            bool_value(output_property.value)
            if output_property is not None
            else current_output
        )
        changes_source_state = target_mode != current_mode or bool(
            {
                DC_SOURCE_VOLTAGE_RANGE,
                DC_SOURCE_CURRENT_RANGE,
                DC_SOURCE_VOLTAGE_LEVEL,
                DC_SOURCE_CURRENT_LEVEL,
            }
            & properties.keys()
        )
        disabled_for_update = current_output and (
            not target_output or changes_source_state
        )
        if disabled_for_update:
            self.set_output(False)
        if target_mode != current_mode:
            self.set_source_mode(target_mode)
        if DC_SOURCE_VOLTAGE_RANGE in properties:
            self.set_voltage_range(
                quantity_value(properties[DC_SOURCE_VOLTAGE_RANGE].value, "V")
            )
        if DC_SOURCE_CURRENT_RANGE in properties:
            self.set_current_range(
                quantity_value(properties[DC_SOURCE_CURRENT_RANGE].value, "A")
            )
        if DC_SOURCE_VOLTAGE_PROTECTION in properties:
            self.set_voltage_protection(
                quantity_value(
                    properties[DC_SOURCE_VOLTAGE_PROTECTION].value,
                    "V",
                )
            )
        if DC_SOURCE_CURRENT_PROTECTION in properties:
            self.set_current_protection(
                quantity_value(
                    properties[DC_SOURCE_CURRENT_PROTECTION].value,
                    "A",
                )
            )
        if DC_SOURCE_VOLTAGE_LEVEL in properties:
            self.set_voltage_level(
                quantity_value(properties[DC_SOURCE_VOLTAGE_LEVEL].value, "V")
            )
        if DC_SOURCE_CURRENT_LEVEL in properties:
            self.set_current_level(
                quantity_value(properties[DC_SOURCE_CURRENT_LEVEL].value, "A")
            )
        if DC_MONITOR_MEASUREMENT_ENABLED in properties:
            self.set_measurement_enabled(
                bool_value(properties[DC_MONITOR_MEASUREMENT_ENABLED].value)
            )
        if DC_MONITOR_INTEGRATION_CYCLES in properties:
            self.set_integration_cycles(
                int_value(properties[DC_MONITOR_INTEGRATION_CYCLES].value)
            )
        if DC_MONITOR_MEASUREMENT_DELAY in properties:
            self.set_measurement_delay(
                quantity_value(properties[DC_MONITOR_MEASUREMENT_DELAY].value, "s")
            )
        effective_output = False if disabled_for_update else current_output
        if target_output != effective_output:
            self.set_output(target_output)
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            if not source.output_enabled:
                return not_collected(
                    [
                        state_property_problem(
                            "virtual_dc_monitor_output_disabled",
                            "DC source output is disabled",
                            DC_SOURCE_OUTPUT_ENABLED,
                        )
                    ]
                )
            if not source.measurement_enabled:
                return not_collected(
                    [
                        state_property_problem(
                            "virtual_dc_monitor_disabled",
                            "DC monitor measurement is disabled",
                            DC_MONITOR_MEASUREMENT_ENABLED,
                        )
                    ]
                )
            active_result = (
                DC_MONITOR_CURRENT_RESULT
                if source.source_mode == "voltage"
                else DC_MONITOR_VOLTAGE_RESULT
            )
            requested_results = {
                request.result_target(result) for result in request.results
            }
            if requested_results != {active_result}:
                return not_collected(
                    [
                        state_property_problem(
                            "virtual_dc_monitor_result_inactive",
                            f"{source.source_mode} mode provides only "
                            f"{active_result.result_id}",
                            DC_SOURCE_MODE,
                        )
                    ]
                )
            measured = (
                MeasurementScalar.create(
                    dtype="float64",
                    unit="A",
                    value=source.voltage_level_v / 1.0e3,
                )
                if source.source_mode == "voltage"
                else MeasurementScalar.create(
                    dtype="float64",
                    unit="V",
                    value=source.current_level_a * 1.0e3,
                )
            )
        return CollectReceipt(
            readback=InstrumentReadback(
                values={result.request_id: measured for result in request.results},
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
            self.world.dc_source(self.instrument_id).voltage_range_v = value_v

    def set_current_range(self, value_a: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).current_range_a = value_a

    def set_voltage_level(self, value_v: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).voltage_level_v = value_v

    def set_current_level(self, value_a: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).current_level_a = value_a

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

    def set_measurement_enabled(self, enabled: bool) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).measurement_enabled = enabled

    def set_integration_cycles(self, cycles: int) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).integration_cycles = cycles

    def set_measurement_delay(self, delay_s: float) -> None:
        with self.world.lock:
            self.world.dc_source(self.instrument_id).measurement_delay_s = delay_s

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


@dataclass(frozen=True)
class _VirtualTemperatureSample:
    scan_channel: int
    autoscan_enabled: bool
    temperature_k: float
    resistance_ohm: float


class VirtualTemperatureMonitor:
    implementation_id = VIRTUAL_TEMPERATURE_MONITOR
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
        with self.world.lock:
            state = self.world.temperature_monitor(self.instrument_id)
            return InstrumentStateSnapshot(
                instrument_id=self.instrument_id,
                properties=[
                    state_property(
                        TEMPERATURE_READOUT_SCAN_CHANNEL,
                        state.scan_channel,
                    ),
                    state_property(
                        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
                        state.autoscan_enabled,
                    ),
                ],
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        del request
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        sample = self.read_sample()
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    result.request_id: (
                        MeasurementScalar.create(
                            dtype="float64",
                            unit="K",
                            value=sample.temperature_k,
                        )
                        if request.result_target(result)
                        == TEMPERATURE_READOUT_TEMPERATURE_RESULT
                        else MeasurementScalar.create(
                            dtype="float64",
                            unit="Ohm",
                            value=sample.resistance_ohm,
                        )
                    )
                    for result in request.results
                },
                metadata={
                    "mode": "virtual",
                    "world_seed": self.world.seed,
                    "scan_channel": sample.scan_channel,
                    "autoscan_enabled": sample.autoscan_enabled,
                    "reading_status": 0,
                },
            )
        )

    def read_sample(self) -> _VirtualTemperatureSample:
        with self.world.lock:
            state = self.world.temperature_monitor(self.instrument_id)
            return _VirtualTemperatureSample(
                scan_channel=state.scan_channel,
                autoscan_enabled=state.autoscan_enabled,
                temperature_k=self.world.temperature_k(),
                resistance_ohm=self.world.sensor_resistance_ohm(),
            )

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


class VirtualNetworkAnalyzer:
    implementation_id = VIRTUAL_VNA
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
                    NETWORK_SWEEP_START_FREQUENCY,
                    Quantity(settings.start_frequency_hz, "Hz"),
                ),
                state_property(
                    NETWORK_SWEEP_STOP_FREQUENCY,
                    Quantity(settings.stop_frequency_hz, "Hz"),
                ),
                state_property(NETWORK_SWEEP_POINTS, settings.points),
                state_property(
                    NETWORK_SWEEP_IF_BANDWIDTH,
                    Quantity(settings.if_bandwidth_hz, "Hz"),
                ),
                state_property(
                    NETWORK_SWEEP_SOURCE_POWER,
                    Quantity(settings.source_power_dbm, "dBm"),
                ),
                state_property(
                    NETWORK_SWEEP_S_PARAMETER,
                    settings.s_parameter,
                ),
            ],
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        with self.world.lock:
            state = self.world.vna(self.instrument_id)
            for assignment in request.assignments:
                if assignment.target == NETWORK_SWEEP_START_FREQUENCY:
                    state.start_frequency_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.target == NETWORK_SWEEP_STOP_FREQUENCY:
                    state.stop_frequency_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.target == NETWORK_SWEEP_POINTS:
                    state.points = int_value(assignment.value)
                elif assignment.target == NETWORK_SWEEP_IF_BANDWIDTH:
                    state.if_bandwidth_hz = quantity_value(
                        assignment.value,
                        "Hz",
                    )
                elif assignment.target == NETWORK_SWEEP_SOURCE_POWER:
                    state.source_power_dbm = quantity_value(
                        assignment.value,
                        "dBm",
                    )
                else:
                    state.s_parameter = string_value(assignment.value)
        return ApplyReceipt(status="applied", state=self.read_state())

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        trace = self.acquire_trace()
        values: dict[str, MeasurementValue] = {}
        for result in request.results:
            if request.result_target(result) == NETWORK_SWEEP_FREQUENCY_RESULT:
                values[result.request_id] = MeasurementArray.create(
                    dtype="float64",
                    unit="Hz",
                    shape=[len(trace.frequencies_hz)],
                    values=trace.frequencies_hz,
                )
            else:
                values[result.request_id] = MeasurementArray.create(
                    dtype="complex128",
                    unit="ratio",
                    shape=[len(trace.values)],
                    values=[
                        ComplexComponents(
                            real=value.real,
                            imag=value.imag,
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

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


__all__ = [
    "VirtualDcSource",
    "VirtualNetworkAnalyzer",
    "VirtualRfSource",
    "VirtualTemperatureMonitor",
]
