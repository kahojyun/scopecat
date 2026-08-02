"""Vendor-neutral virtual instruments backed by one shared world."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementScalar,
    MeasurementValue,
)
from scopecat.sdk.instruments import (
    AcquisitionResultRef,
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentDescription,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    NetworkTrace,
    quantity_value,
    state_property_problem,
    unsupported_invoke,
)
from scopecat_instruments.driver_ids import (
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
)
from scopecat_instruments.driver_states import (
    decode_dc_monitor_patch,
    decode_dc_source_patch,
    decode_network_sweep_patch,
    decode_rf_output_patch,
    encode_dc_monitor_state,
    encode_dc_source_current_state,
    encode_dc_source_state,
    encode_dc_source_voltage_state,
    encode_driver_state,
    encode_network_sweep_state,
    encode_rf_output_state,
    encode_temperature_readout_observation,
)
from scopecat_instruments.interface_declarations import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
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
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    NETWORK_SWEEP_FREQUENCY_RESULT,
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

    def read_state(self) -> DriverState:
        with self.world.lock:
            source = self.world.rf_source(self.instrument_id)
            state = RFOutputState(
                frequency=Quantity(source.frequency_hz, "Hz"),
                power=Quantity(source.power_dbm, "dBm"),
                output_enabled=source.output_enabled,
                reference_source=source.reference_source,
            )
        return encode_driver_state(
            encode_rf_output_state(state),
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        patch = decode_rf_output_patch(request)
        if "frequency" in patch:
            self.set_frequency(quantity_value(patch["frequency"], "Hz"))
        if "power" in patch:
            self.set_power(quantity_value(patch["power"], "dBm"))
        if "output_enabled" in patch:
            self.set_output(patch["output_enabled"])
        if "reference_source" in patch:
            self.set_reference_source(patch["reference_source"])
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return unsupported_invoke(request, self.instrument_id)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        del request
        return DriverSuccess(DriverReadback(values={}))

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


type _VirtualDcSourceMode = Literal["voltage", "current"]
type _VirtualDcSourceCase = DCSourceVoltage | DCSourceCurrent


@dataclass(frozen=True)
class _VirtualDcSnapshot:
    common: DCSourceState
    active_case: _VirtualDcSourceCase
    monitor: DCMonitorState

    @property
    def source_mode(self) -> _VirtualDcSourceMode:
        if isinstance(self.active_case, DCSourceVoltage):
            return "voltage"
        return "current"


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

    def read_state(self) -> DriverState:
        snapshot = self._canonical_snapshot()
        active_case = snapshot.active_case
        encoded_case = (
            encode_dc_source_voltage_state(active_case)
            if isinstance(active_case, DCSourceVoltage)
            else encode_dc_source_current_state(active_case)
        )
        return encode_driver_state(
            encode_dc_source_state(snapshot.common),
            encoded_case,
            encode_dc_monitor_state(snapshot.monitor),
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def _canonical_snapshot(self) -> _VirtualDcSnapshot:
        with self.world.lock:
            source = self.world.dc_source(self.instrument_id)
            common = DCSourceState(
                voltage_protection=Quantity(source.voltage_protection_v, "V"),
                current_protection=Quantity(source.current_protection_a, "A"),
                output_enabled=source.output_enabled,
            )
            active_case: _VirtualDcSourceCase = (
                DCSourceVoltage(
                    range=Quantity(source.voltage_range_v, "V"),
                    level=Quantity(source.voltage_level_v, "V"),
                )
                if source.source_mode == "voltage"
                else DCSourceCurrent(
                    range=Quantity(source.current_range_a, "A"),
                    level=Quantity(source.current_level_a, "A"),
                )
            )
            monitor = DCMonitorState(
                measurement_enabled=source.measurement_enabled,
                integration_cycles=source.integration_cycles,
                measurement_delay=Quantity(source.measurement_delay_s, "s"),
            )
        return _VirtualDcSnapshot(
            common=common,
            active_case=active_case,
            monitor=monitor,
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        source_patch = decode_dc_source_patch(request)
        monitor_patch = decode_dc_monitor_patch(request)
        baseline = self._canonical_snapshot()
        current_mode = baseline.source_mode
        current_output = baseline.common.output_enabled
        target_mode = source_patch.get("source_mode", current_mode)
        target_output = source_patch.get("output_enabled", current_output)
        changes_source_state = target_mode != current_mode or bool(
            {
                "voltage_range",
                "current_range",
                "voltage_level",
                "current_level",
            }
            & source_patch.keys()
        )
        disabled_for_update = current_output and (
            not target_output or changes_source_state
        )
        if disabled_for_update:
            self.set_output(False)
        if target_mode != current_mode:
            self.set_source_mode(target_mode)
        if "voltage_range" in source_patch:
            self.set_voltage_range(quantity_value(source_patch["voltage_range"], "V"))
        if "current_range" in source_patch:
            self.set_current_range(quantity_value(source_patch["current_range"], "A"))
        if "voltage_protection" in source_patch:
            self.set_voltage_protection(
                quantity_value(source_patch["voltage_protection"], "V")
            )
        if "current_protection" in source_patch:
            self.set_current_protection(
                quantity_value(source_patch["current_protection"], "A")
            )
        if "voltage_level" in source_patch:
            self.set_voltage_level(quantity_value(source_patch["voltage_level"], "V"))
        if "current_level" in source_patch:
            self.set_current_level(quantity_value(source_patch["current_level"], "A"))
        if "measurement_enabled" in monitor_patch:
            self.set_measurement_enabled(monitor_patch["measurement_enabled"])
        if "integration_cycles" in monitor_patch:
            self.set_integration_cycles(monitor_patch["integration_cycles"])
        if "measurement_delay" in monitor_patch:
            self.set_measurement_delay(
                quantity_value(monitor_patch["measurement_delay"], "s")
            )
        effective_output = False if disabled_for_update else current_output
        if target_output != effective_output:
            self.set_output(target_output)
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return unsupported_invoke(request, self.instrument_id)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
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
            active_result = (
                DC_MONITOR_CURRENT_RESULT
                if source.source_mode == "voltage"
                else DC_MONITOR_VOLTAGE_RESULT
            )
            if request.results != frozenset({active_result}):
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "virtual_dc_monitor_result_inactive",
                            f"{source.source_mode} mode provides only "
                            f"{active_result.result_id}",
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
                if source.source_mode == "voltage"
                else MeasurementScalar.create(
                    dtype="float64",
                    unit="V",
                    value=source.current_level_a * 1.0e3,
                )
            )
        return DriverSuccess(
            DriverReadback(
                values=dict.fromkeys(request.results, measured),
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            ),
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

    def read_state(self) -> DriverState:
        with self.world.lock:
            state = self.world.temperature_monitor(self.instrument_id)
            observation = TemperatureReadoutObservation(
                scan_channel=state.scan_channel,
                autoscan_enabled=state.autoscan_enabled,
            )
            return encode_driver_state(
                encode_temperature_readout_observation(observation),
                metadata={"mode": "virtual", "world_seed": self.world.seed},
            )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        del request
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return unsupported_invoke(request, self.instrument_id)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        sample = self.read_sample()
        return DriverSuccess(
            DriverReadback(
                values={
                    result: (
                        MeasurementScalar.create(
                            dtype="float64",
                            unit="K",
                            value=sample.temperature_k,
                        )
                        if result == TEMPERATURE_READOUT_TEMPERATURE_RESULT
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

    def read_state(self) -> DriverState:
        settings = self.sweep_settings()
        return encode_driver_state(
            encode_network_sweep_state(
                NetworkSweepState(
                    start_frequency=Quantity(settings.start_frequency_hz, "Hz"),
                    stop_frequency=Quantity(settings.stop_frequency_hz, "Hz"),
                    points=settings.points,
                    if_bandwidth=Quantity(settings.if_bandwidth_hz, "Hz"),
                    source_power=Quantity(settings.source_power_dbm, "dBm"),
                    s_parameter=settings.s_parameter,
                )
            ),
            metadata={"mode": "virtual", "world_seed": self.world.seed},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        patch = decode_network_sweep_patch(request)
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
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return unsupported_invoke(request, self.instrument_id)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        trace = self.acquire_trace()
        values: dict[AcquisitionResultRef, MeasurementValue] = {}
        for result in request.results:
            if result == NETWORK_SWEEP_FREQUENCY_RESULT:
                values[result] = MeasurementArray.create(
                    dtype="float64",
                    unit="Hz",
                    shape=[len(trace.frequencies_hz)],
                    values=trace.frequencies_hz,
                )
            else:
                values[result] = MeasurementArray.create(
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
        return DriverSuccess(
            DriverReadback(
                values=values,
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
