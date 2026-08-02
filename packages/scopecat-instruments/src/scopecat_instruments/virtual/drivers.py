"""Vendor-neutral virtual instruments backed by one shared world."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override

from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementScalar,
)
from scopecat.sdk.instruments import (
    DriverOutcome,
    DriverRejected,
    DriverSuccess,
    InstrumentDescription,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    NetworkTrace,
    invoke_unknown,
    quantity_value,
    state_property_problem,
)
from scopecat_instruments.driver_handlers import (
    DCMonitorMeasureCurrentDriverReadback,
    DCMonitorMeasureVoltageDriverReadback,
    DCSourceMonitorDriverAdapter,
    DCSourceMonitorDriverPatch,
    DCSourceMonitorDriverSnapshot,
    NetworkSweepDriverAdapter,
    NetworkSweepDriverSnapshot,
    NetworkSweepSweepDriverReadback,
    RFOutputDriverAdapter,
    RFOutputDriverSnapshot,
    TemperatureReadoutDriverAdapter,
    TemperatureReadoutDriverSnapshot,
    TemperatureReadoutSampleDriverReadback,
)
from scopecat_instruments.driver_states import (
    NetworkSweepDriverPatch,
    RFOutputDriverPatch,
)
from scopecat_instruments.interface_declarations import (
    DCMonitorState,
    DCSourceObservation,
    DCSourceState,
    NetworkSweepState,
    ReferenceSource,
    RFOutputState,
    TemperatureReadoutObservation,
)
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
)
from scopecat_instruments.package_manifest import (
    VIRTUAL_DC_SOURCE_DRIVER,
    VIRTUAL_RF_SOURCE_DRIVER,
    VIRTUAL_TEMPERATURE_MONITOR_DRIVER,
    VIRTUAL_VNA_DRIVER,
)
from scopecat_instruments.virtual.world import VirtualLabWorld


class VirtualRfSource(RFOutputDriverAdapter):
    implementation_id = VIRTUAL_RF_SOURCE_DRIVER.id
    implementation_version = VIRTUAL_RF_SOURCE_DRIVER.implementation_version

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

    @override
    def read_rf_output_state(self) -> RFOutputDriverSnapshot:
        with self.world.lock:
            source = self.world.rf_source(self.instrument_id)
            state = RFOutputState(
                frequency=Quantity(source.frequency_hz, "Hz"),
                power=Quantity(source.power_dbm, "dBm"),
                output_enabled=source.output_enabled,
                reference_source=source.reference_source,
            )
        return RFOutputDriverSnapshot(
            state=state,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    @override
    def apply_rf_output_state(
        self,
        patch: RFOutputDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        if "frequency" in patch:
            self.set_frequency(quantity_value(patch["frequency"], "Hz"))
        if "power" in patch:
            self.set_power(quantity_value(patch["power"], "dBm"))
        if "output_enabled" in patch:
            self.set_output(patch["output_enabled"])
        if "reference_source" in patch:
            self.set_reference_source(patch["reference_source"])
        return DriverSuccess(None)

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

    def set_reference_source(self, source: ReferenceSource) -> None:
        if source not in {"internal", "external"}:
            raise ValueError("reference source must be internal or external")
        with self.world.lock:
            self.world.rf_source(self.instrument_id).reference_source = source

    def reference_source(self) -> ReferenceSource:
        with self.world.lock:
            return self.world.rf_source(self.instrument_id).reference_source

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


class VirtualDcSource(DCSourceMonitorDriverAdapter):
    implementation_id = VIRTUAL_DC_SOURCE_DRIVER.id
    implementation_version = VIRTUAL_DC_SOURCE_DRIVER.implementation_version

    def __init__(self, instrument_id: str, world: VirtualLabWorld) -> None:
        super().__init__(monitor=True)
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

    @override
    def read_dc_source_monitor_state(self) -> DCSourceMonitorDriverSnapshot:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            source_state = DCSourceState(
                voltage_protection=Quantity(source.voltage_protection_v, "V"),
                current_protection=Quantity(source.current_protection_a, "A"),
                output_enabled=source.output_enabled,
            )
            source_observation = DCSourceObservation(source_mode=source.source_mode)
            monitor = DCMonitorState(
                measurement_enabled=source.measurement_enabled,
                integration_cycles=source.integration_cycles,
                measurement_delay=Quantity(source.measurement_delay_s, "s"),
            )
        return DCSourceMonitorDriverSnapshot(
            dc_source=source_state,
            dc_source_observation=source_observation,
            dc_monitor=monitor,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    @override
    def apply_dc_source_monitor_state(
        self,
        patch: DCSourceMonitorDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        source_patch = patch.dc_source
        monitor_patch = patch.dc_monitor
        current_output = self.output_enabled()
        target_output = source_patch.get("output_enabled", current_output)
        if "voltage_protection" in source_patch:
            self.set_voltage_protection(
                quantity_value(source_patch["voltage_protection"], "V")
            )
        if "current_protection" in source_patch:
            self.set_current_protection(
                quantity_value(source_patch["current_protection"], "A")
            )
        if "measurement_enabled" in monitor_patch:
            self.set_measurement_enabled(monitor_patch["measurement_enabled"])
        if "integration_cycles" in monitor_patch:
            self.set_integration_cycles(monitor_patch["integration_cycles"])
        if "measurement_delay" in monitor_patch:
            self.set_measurement_delay(
                quantity_value(monitor_patch["measurement_delay"], "s")
            )
        if target_output != current_output:
            self.set_output(target_output)
        return DriverSuccess(None)

    @override
    def handle_source_voltage(
        self,
        *,
        range: Quantity,
        level: Quantity,
    ) -> DriverOutcome[None]:
        try:
            with self.world.lock:
                source = self.world.dc_source(self.instrument_id)
                source.source_mode = "voltage"
                source.voltage_range_v = quantity_value(range, "V")
                source.voltage_level_v = quantity_value(level, "V")
            return DriverSuccess(None)
        except Exception as error:
            return invoke_unknown(self.instrument_id, error)

    @override
    def handle_source_current(
        self,
        *,
        range: Quantity,
        level: Quantity,
    ) -> DriverOutcome[None]:
        try:
            with self.world.lock:
                source = self.world.dc_source(self.instrument_id)
                source.source_mode = "current"
                source.current_range_a = quantity_value(range, "A")
                source.current_level_a = quantity_value(level, "A")
            return DriverSuccess(None)
        except Exception as error:
            return invoke_unknown(self.instrument_id, error)

    @override
    def handle_measure_current(
        self,
    ) -> DriverOutcome[DCMonitorMeasureCurrentDriverReadback]:
        outcome = self._measure_monitor(expected_mode="voltage")
        if not isinstance(outcome, DriverSuccess):
            return outcome
        return DriverSuccess(
            DCMonitorMeasureCurrentDriverReadback(
                current=outcome.value,
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            ),
            metadata=outcome.metadata,
        )

    @override
    def handle_measure_voltage(
        self,
    ) -> DriverOutcome[DCMonitorMeasureVoltageDriverReadback]:
        outcome = self._measure_monitor(expected_mode="current")
        if not isinstance(outcome, DriverSuccess):
            return outcome
        return DriverSuccess(
            DCMonitorMeasureVoltageDriverReadback(
                voltage=outcome.value,
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            ),
            metadata=outcome.metadata,
        )

    def _measure_monitor(
        self,
        *,
        expected_mode: Literal["voltage", "current"],
    ) -> DriverOutcome[MeasurementScalar]:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            if not source.output_enabled:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "virtual_dc_monitor_output_disabled",
                            "DC source output is disabled",
                            DC_SOURCE_OUTPUT_ENABLED,
                        ),
                    )
                )
            if not source.measurement_enabled:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "virtual_dc_monitor_disabled",
                            "DC monitor measurement is disabled",
                            DC_MONITOR_MEASUREMENT_ENABLED,
                        ),
                    )
                )
            if source.source_mode != expected_mode:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "virtual_dc_monitor_source_mode_mismatch",
                            (
                                f"measurement requires {expected_mode} source mode, "
                                f"got {source.source_mode}"
                            ),
                            DC_SOURCE_MODE,
                        ),
                    )
                )
            measured = (
                MeasurementScalar.create(
                    dtype="float64",
                    unit="A",
                    value=source.voltage_level_v / 1.0e3,
                )
                if expected_mode == "voltage"
                else MeasurementScalar.create(
                    dtype="float64",
                    unit="V",
                    value=source.current_level_a * 1.0e3,
                )
            )
        return DriverSuccess(measured)

    def set_source_mode(self, mode: Literal["voltage", "current"]) -> None:
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


class VirtualTemperatureMonitor(TemperatureReadoutDriverAdapter):
    implementation_id = VIRTUAL_TEMPERATURE_MONITOR_DRIVER.id
    implementation_version = VIRTUAL_TEMPERATURE_MONITOR_DRIVER.implementation_version

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

    @override
    def read_temperature_readout_state(self) -> TemperatureReadoutDriverSnapshot:
        with self.world.lock:
            state = self.world.temperature_monitor(self.instrument_id)
            observation = TemperatureReadoutObservation(
                scan_channel=state.scan_channel,
                autoscan_enabled=state.autoscan_enabled,
            )
        return TemperatureReadoutDriverSnapshot(
            observation=observation,
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    @override
    def handle_sample(
        self,
    ) -> DriverOutcome[TemperatureReadoutSampleDriverReadback]:
        sample = self.read_sample()
        return DriverSuccess(
            TemperatureReadoutSampleDriverReadback(
                temperature=MeasurementScalar.create(
                    dtype="float64",
                    unit="K",
                    value=sample.temperature_k,
                ),
                resistance=MeasurementScalar.create(
                    dtype="float64",
                    unit="Ohm",
                    value=sample.resistance_ohm,
                ),
                metadata={
                    "mode": "virtual",
                    "world_seed": self.world.seed,
                    "scan_channel": sample.scan_channel,
                    "autoscan_enabled": sample.autoscan_enabled,
                    "reading_status": 0,
                },
            ),
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


class VirtualNetworkAnalyzer(NetworkSweepDriverAdapter):
    implementation_id = VIRTUAL_VNA_DRIVER.id
    implementation_version = VIRTUAL_VNA_DRIVER.implementation_version

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

    @override
    def read_network_sweep_state(self) -> NetworkSweepDriverSnapshot:
        settings = self.sweep_settings()
        return NetworkSweepDriverSnapshot(
            state=NetworkSweepState(
                start_frequency=Quantity(settings.start_frequency_hz, "Hz"),
                stop_frequency=Quantity(settings.stop_frequency_hz, "Hz"),
                points=settings.points,
                if_bandwidth=Quantity(settings.if_bandwidth_hz, "Hz"),
                source_power=Quantity(settings.source_power_dbm, "dBm"),
                s_parameter=settings.s_parameter,
            ),
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    @override
    def apply_network_sweep_state(
        self,
        patch: NetworkSweepDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        with self.world.lock:
            state = self.world.vna(self.instrument_id)
            if "start_frequency" in patch:
                state.start_frequency_hz = quantity_value(
                    patch["start_frequency"],
                    "Hz",
                )
            if "stop_frequency" in patch:
                state.stop_frequency_hz = quantity_value(
                    patch["stop_frequency"],
                    "Hz",
                )
            if "points" in patch:
                state.points = patch["points"]
            if "if_bandwidth" in patch:
                state.if_bandwidth_hz = quantity_value(
                    patch["if_bandwidth"],
                    "Hz",
                )
            if "source_power" in patch:
                state.source_power_dbm = quantity_value(
                    patch["source_power"],
                    "dBm",
                )
            if "s_parameter" in patch:
                state.s_parameter = patch["s_parameter"]
        return DriverSuccess(None)

    @override
    def handle_sweep(
        self,
    ) -> DriverOutcome[NetworkSweepSweepDriverReadback]:
        trace = self.acquire_trace()
        return DriverSuccess(
            NetworkSweepSweepDriverReadback(
                frequency=MeasurementArray.create(
                    dtype="float64",
                    unit="Hz",
                    shape=[len(trace.frequencies_hz)],
                    values=trace.frequencies_hz,
                ),
                s_parameter=MeasurementArray.create(
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
                ),
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            ),
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
