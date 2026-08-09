"""Virtual bare AWGs, digitizer, and oscilloscope for the reference lab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import scopecat as sc
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementUnavailable,
    MeasurementValue,
)
from scopecat.sdk.instruments import (
    AcquisitionResultRef,
    DriverAcquisition,
    DriverConnectionSpec,
    DriverOperation,
    DriverOutcome,
    DriverPayload,
    DriverReadback,
    DriverScalar,
    DriverSpec,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentDescription,
    PropertyRef,
    instrument_component,
    interface_mount,
)

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
    ANALOG_WAVEFORM_OUTPUT_ENABLED,
    ANALOG_WAVEFORM_OUTPUT_OFFSET,
    ANALOG_WAVEFORM_OUTPUT_PLAY,
    ANALOG_WAVEFORM_OUTPUT_WAVEFORM,
    AWG_RUN_MODE,
    AWG_SAMPLE_RATE,
    DIGITIZER_FETCH_TIME,
    DIGITIZER_INPUT_COUPLING,
    DIGITIZER_INPUT_ENABLED,
    DIGITIZER_INPUT_RANGE,
    DIGITIZER_RECORD_LENGTH,
    DIGITIZER_SAMPLE_RATE,
    DIGITIZER_TRIGGER_SOURCE,
    OSCILLOSCOPE_ARM,
    OSCILLOSCOPE_ARMED,
    OSCILLOSCOPE_BANDWIDTH_LIMIT,
    OSCILLOSCOPE_COUPLING,
    OSCILLOSCOPE_FETCH_TIME,
    OSCILLOSCOPE_IMPEDANCE,
    OSCILLOSCOPE_INPUT_ENABLED,
    OSCILLOSCOPE_RECORD_LENGTH,
    OSCILLOSCOPE_SAMPLE_RATE,
    OSCILLOSCOPE_TRIGGER_LEVEL,
    OSCILLOSCOPE_TRIGGER_SOURCE,
    OSCILLOSCOPE_VERTICAL_OFFSET,
    OSCILLOSCOPE_VERTICAL_SCALE,
    analog_waveform_output_interface,
    awg_sequencer_interface,
    digitizer_control_interface,
    digitizer_input_interface,
    oscilloscope_control_interface,
    oscilloscope_input_interface,
)
from reference_lab.interfaces import (
    CLOCK_REFERENCE_FREQUENCY,
    CLOCK_REFERENCE_LOCKED,
    CLOCK_REFERENCE_SOURCE,
    clock_reference_interface,
)
from reference_lab.payloads import DecodedSampledWaveform

AWG_OUTPUT_COMPONENT_IDS = tuple(f"ch{index}" for index in range(1, 9))
DIGITIZER_INPUT_COMPONENT_IDS = ("ch1", "ch2")
OSCILLOSCOPE_INPUT_COMPONENT_IDS = ("ch1", "ch2", "ch3", "ch4")
VIRTUAL_AWG_DRIVER_ID = "reference_lab.virtual.awg"
VIRTUAL_DIGITIZER_DRIVER_ID = "reference_lab.virtual.digitizer"
VIRTUAL_OSCILLOSCOPE_DRIVER_ID = "reference_lab.virtual.oscilloscope"


def _virtual_driver_spec(driver_id: str, label: str) -> DriverSpec:
    return DriverSpec(
        driver_id=driver_id,
        implementation_version="v1",
        label=label,
        connections=(
            DriverConnectionSpec(
                kind="virtual",
                options_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        ),
    )


VIRTUAL_AWG_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_AWG_DRIVER_ID,
    "Virtual eight-channel AWG",
)
VIRTUAL_DIGITIZER_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_DIGITIZER_DRIVER_ID,
    "Virtual two-channel digitizer",
)
VIRTUAL_OSCILLOSCOPE_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_OSCILLOSCOPE_DRIVER_ID,
    "Virtual four-channel oscilloscope",
)


@dataclass(frozen=True, slots=True)
class CapturedBenchTrace:
    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    source_component_path: tuple[str, ...]
    source_sample_rate_hz: float
    scope_sample_rate_hz: float


@dataclass(slots=True)
class BenchSignalWorld:
    """The temporary cable and trigger link between two virtual instruments."""

    scope_armed: bool = False
    scope_sample_rate_hz: float = 1.0e9
    scope_record_length: int = 16
    capture: CapturedBenchTrace | None = None

    def arm_scope(self, *, sample_rate_hz: float, record_length: int) -> None:
        self.scope_armed = True
        self.scope_sample_rate_hz = sample_rate_hz
        self.scope_record_length = record_length
        self.capture = None

    def emit(
        self,
        *,
        component_path: tuple[str, ...],
        normalized_samples: tuple[float, ...],
        sample_rate_hz: float,
        amplitude_v: float,
        offset_v: float,
        output_enabled: bool,
        repeat: bool,
    ) -> bool:
        if not self.scope_armed:
            return False
        times = tuple(
            index / self.scope_sample_rate_hz
            for index in range(self.scope_record_length)
        )
        normalized = _resample(
            normalized_samples,
            source_rate_hz=sample_rate_hz,
            target_rate_hz=self.scope_sample_rate_hz,
            count=self.scope_record_length,
            repeat=repeat,
        )
        voltages = tuple(
            offset_v + amplitude_v * sample if output_enabled else 0.0
            for sample in normalized
        )
        self.capture = CapturedBenchTrace(
            time_s=times,
            voltage_v=voltages,
            source_component_path=component_path,
            source_sample_rate_hz=sample_rate_hz,
            scope_sample_rate_hz=self.scope_sample_rate_hz,
        )
        self.scope_armed = False
        return True

    def abort_scope(self) -> None:
        self.scope_armed = False


class VirtualAwg:
    """Real-valued waveform outputs backed by one shared sample clock."""

    implementation_id = VIRTUAL_AWG_DRIVER_ID
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: BenchSignalWorld) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._state: dict[PropertyRef, DriverScalar] = {
            AWG_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            AWG_RUN_MODE: "once",
            CLOCK_REFERENCE_SOURCE: "external",
            CLOCK_REFERENCE_FREQUENCY: sc.Quantity(10.0e6, "Hz"),
            CLOCK_REFERENCE_LOCKED: True,
        }
        for channel_id in AWG_OUTPUT_COMPONENT_IDS:
            component_path = ("outputs", channel_id)
            self._state.update(
                {
                    _mount_property(
                        ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
                        component_path,
                    ): sc.Quantity(0.25, "V"),
                    _mount_property(
                        ANALOG_WAVEFORM_OUTPUT_OFFSET,
                        component_path,
                    ): sc.Quantity(0.0, "V"),
                    _mount_property(
                        ANALOG_WAVEFORM_OUTPUT_ENABLED,
                        component_path,
                    ): False,
                }
            )

    def describe(self) -> InstrumentDescription:
        output = analog_waveform_output_interface()
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual eight-channel AWG",
            description=(
                "A modular AWG model with an instrument-wide sample and reference "
                "clock and independently mounted real-valued DAC outputs."
            ),
            components=[
                instrument_component(
                    "outputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in AWG_OUTPUT_COMPONENT_IDS
                    ),
                ),
            ],
            interfaces=[
                awg_sequencer_interface(),
                clock_reference_interface(),
                output,
            ],
            interface_mounts=[
                interface_mount(output.id, "outputs", channel_id)
                for channel_id in AWG_OUTPUT_COMPONENT_IDS
            ],
        )

    def read_state(self) -> DriverState:
        return DriverState(values=self._state, metadata={"mode": "virtual"})

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        clock_changed = any(
            entry.target in {CLOCK_REFERENCE_SOURCE, CLOCK_REFERENCE_FREQUENCY}
            for entry in request.entries
        )
        if clock_changed:
            self._state[CLOCK_REFERENCE_LOCKED] = False
        for entry in request.entries:
            value = entry.value
            if isinstance(value, sc.Quantity):
                unit = (
                    "Hz"
                    if entry.target.property_id
                    in {
                        AWG_SAMPLE_RATE.property_id,
                        CLOCK_REFERENCE_FREQUENCY.property_id,
                    }
                    else "V"
                )
                value = value.to(unit)
            self._state[entry.target] = value
        if clock_changed:
            self._state[CLOCK_REFERENCE_LOCKED] = True
        return DriverSuccess(
            self.read_state(),
            metadata={"clock_settled": bool(self._state[CLOCK_REFERENCE_LOCKED])},
        )

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        component_path = request.target.component_path
        waveform = cast(
            "DecodedSampledWaveform",
            cast(
                "DriverPayload",
                request.arguments[ANALOG_WAVEFORM_OUTPUT_WAVEFORM.argument_id],
            ).value,
        )
        sample_rate = _quantity_value(self._state[AWG_SAMPLE_RATE], "Hz")
        amplitude = _quantity_value(
            self._state[
                _mount_property(ANALOG_WAVEFORM_OUTPUT_AMPLITUDE, component_path)
            ],
            "V",
        )
        offset = _quantity_value(
            self._state[_mount_property(ANALOG_WAVEFORM_OUTPUT_OFFSET, component_path)],
            "V",
        )
        output_enabled = cast(
            "bool",
            self._state[
                _mount_property(ANALOG_WAVEFORM_OUTPUT_ENABLED, component_path)
            ],
        )
        run_mode = cast("str", self._state[AWG_RUN_MODE])
        captured = self._world.emit(
            component_path=component_path,
            normalized_samples=waveform.samples,
            sample_rate_hz=sample_rate,
            amplitude_v=amplitude,
            offset_v=offset,
            output_enabled=output_enabled,
            repeat=run_mode == "continuous",
        )
        return DriverSuccess(
            None,
            metadata={
                "component_path": list(component_path),
                "operation_id": ANALOG_WAVEFORM_OUTPUT_PLAY.operation_id,
                "sample_count": len(waveform.samples),
                "sample_rate_hz": sample_rate,
                "output_enabled": output_enabled,
                "run_mode": run_mode,
                "signal_emitted": output_enabled,
                "captured_by_scope": captured,
            },
        )

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        del request
        raise NotImplementedError

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        for channel_id in AWG_OUTPUT_COMPONENT_IDS:
            self._state[
                _mount_property(
                    ANALOG_WAVEFORM_OUTPUT_ENABLED,
                    ("outputs", channel_id),
                )
            ] = False


class VirtualDigitizer:
    """Two physical ADC inputs sharing one acquisition engine."""

    implementation_id = VIRTUAL_DIGITIZER_DRIVER_ID
    implementation_version = "v1"

    def __init__(self, instrument_id: str) -> None:
        self.instrument_id = instrument_id
        self._armed = False
        self._state: dict[PropertyRef, DriverScalar] = {
            DIGITIZER_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            DIGITIZER_RECORD_LENGTH: 1024,
            DIGITIZER_TRIGGER_SOURCE: "external",
        }
        for channel_id in DIGITIZER_INPUT_COMPONENT_IDS:
            component_path = ("inputs", channel_id)
            self._state.update(
                {
                    _mount_property(
                        DIGITIZER_INPUT_ENABLED,
                        component_path,
                    ): channel_id == "ch1",
                    _mount_property(
                        DIGITIZER_INPUT_RANGE,
                        component_path,
                    ): sc.Quantity(0.5, "V"),
                    _mount_property(
                        DIGITIZER_INPUT_COUPLING,
                        component_path,
                    ): "dc",
                }
            )

    def describe(self) -> InstrumentDescription:
        input_interface = digitizer_input_interface()
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual two-channel digitizer",
            description=(
                "A bare ADC model; list-mode demodulation windows belong to the "
                "quantum target and reference physical inputs by route."
            ),
            components=[
                instrument_component(
                    "inputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in DIGITIZER_INPUT_COMPONENT_IDS
                    ),
                )
            ],
            interfaces=[digitizer_control_interface(), input_interface],
            interface_mounts=[
                interface_mount(input_interface.id, "inputs", channel_id)
                for channel_id in DIGITIZER_INPUT_COMPONENT_IDS
            ],
        )

    def read_state(self) -> DriverState:
        return DriverState(
            values=self._state,
            metadata={"mode": "virtual", "armed": self._armed},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        for entry in request.entries:
            value = entry.value
            if isinstance(value, sc.Quantity):
                unit = (
                    "Hz"
                    if entry.target.property_id == DIGITIZER_SAMPLE_RATE.property_id
                    else "V"
                )
                value = value.to(unit)
            self._state[entry.target] = value
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        del request
        self._armed = True
        return DriverSuccess(self.read_state(), metadata={"armed": True})

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        record_length = cast("int", self._state[DIGITIZER_RECORD_LENGTH])
        sample_rate = _quantity_value(self._state[DIGITIZER_SAMPLE_RATE], "Hz")
        values: dict[AcquisitionResultRef, MeasurementValue] = {}
        for result in request.results:
            is_time = result.result_id == DIGITIZER_FETCH_TIME.result_id
            values[result] = MeasurementArray.create(
                dtype="float64",
                unit="s" if is_time else "V",
                values=(
                    tuple(index / sample_rate for index in range(record_length))
                    if is_time
                    else (0.0,) * record_length
                ),
            )
        self._armed = False
        return DriverSuccess(
            DriverReadback(
                values=values,
                metadata={"triggered": True, "mode": "virtual"},
            )
        )

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        self._armed = False


class VirtualOscilloscope:
    """Four analog inputs sharing one timebase and trigger engine."""

    implementation_id = VIRTUAL_OSCILLOSCOPE_DRIVER_ID
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: BenchSignalWorld) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._state: dict[PropertyRef, DriverScalar] = {
            OSCILLOSCOPE_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            OSCILLOSCOPE_RECORD_LENGTH: 16,
            OSCILLOSCOPE_TRIGGER_SOURCE: "external",
            OSCILLOSCOPE_TRIGGER_LEVEL: sc.Quantity(0.0, "V"),
        }
        for channel_id in OSCILLOSCOPE_INPUT_COMPONENT_IDS:
            component_path = ("inputs", channel_id)
            self._state.update(
                {
                    _mount_property(
                        OSCILLOSCOPE_INPUT_ENABLED,
                        component_path,
                    ): channel_id == "ch1",
                    _mount_property(
                        OSCILLOSCOPE_VERTICAL_SCALE,
                        component_path,
                    ): sc.Quantity(0.1, "V"),
                    _mount_property(
                        OSCILLOSCOPE_VERTICAL_OFFSET,
                        component_path,
                    ): sc.Quantity(0.0, "V"),
                    _mount_property(
                        OSCILLOSCOPE_COUPLING,
                        component_path,
                    ): "dc",
                    _mount_property(
                        OSCILLOSCOPE_IMPEDANCE,
                        component_path,
                    ): "50_ohm",
                    _mount_property(
                        OSCILLOSCOPE_BANDWIDTH_LIMIT,
                        component_path,
                    ): sc.Quantity(500.0e6, "Hz"),
                }
            )

    def describe(self) -> InstrumentDescription:
        input_interface = oscilloscope_input_interface()
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual four-channel oscilloscope",
            description=(
                "A manual-informed scope model with an instrument-wide acquisition "
                "engine and independently mounted analog inputs."
            ),
            components=[
                instrument_component(
                    "inputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in OSCILLOSCOPE_INPUT_COMPONENT_IDS
                    ),
                ),
            ],
            interfaces=[oscilloscope_control_interface(), input_interface],
            interface_mounts=[
                interface_mount(input_interface.id, "inputs", channel_id)
                for channel_id in OSCILLOSCOPE_INPUT_COMPONENT_IDS
            ],
        )

    def read_state(self) -> DriverState:
        return DriverState(
            values={**self._state, OSCILLOSCOPE_ARMED: self._world.scope_armed},
            metadata={"mode": "virtual"},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        for entry in request.entries:
            value = entry.value
            if isinstance(value, sc.Quantity):
                unit = (
                    "Hz"
                    if entry.target.property_id
                    in {
                        OSCILLOSCOPE_SAMPLE_RATE.property_id,
                        OSCILLOSCOPE_BANDWIDTH_LIMIT.property_id,
                    }
                    else "V"
                )
                value = value.to(unit)
            self._state[entry.target] = value
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        del request
        sample_rate = _quantity_value(self._state[OSCILLOSCOPE_SAMPLE_RATE], "Hz")
        record_length = cast("int", self._state[OSCILLOSCOPE_RECORD_LENGTH])
        self._world.arm_scope(
            sample_rate_hz=sample_rate,
            record_length=record_length,
        )
        return DriverSuccess(
            self.read_state(),
            metadata={
                "operation_id": OSCILLOSCOPE_ARM.operation_id,
                "armed": True,
                "sample_rate_hz": sample_rate,
                "record_length": record_length,
            },
        )

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        capture = self._world.capture
        record_length = cast("int", self._state[OSCILLOSCOPE_RECORD_LENGTH])
        values: dict[AcquisitionResultRef, MeasurementValue] = {}
        for result in request.results:
            unit = "s" if result.result_id == OSCILLOSCOPE_FETCH_TIME.result_id else "V"
            if capture is None:
                values[result] = MeasurementUnavailable.create(
                    reason="missing",
                    dtype="float64",
                    unit=unit,
                    shape=(record_length,),
                    metadata={"detail": "no trigger arrived after the scope was armed"},
                )
                continue
            samples = (
                capture.time_s
                if result.result_id == OSCILLOSCOPE_FETCH_TIME.result_id
                else capture.voltage_v
            )
            values[result] = MeasurementArray.create(
                dtype="float64",
                unit=unit,
                values=samples,
                metadata={
                    "sample_rate_hz": capture.scope_sample_rate_hz,
                    "time_origin_s": 0.0,
                },
            )
        return DriverSuccess(
            DriverReadback(
                values=values,
                metadata=(
                    {"triggered": False}
                    if capture is None
                    else {
                        "triggered": True,
                        "source_component_path": list(capture.source_component_path),
                        "source_sample_rate_hz": capture.source_sample_rate_hz,
                    }
                ),
            )
        )

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        self._world.abort_scope()


def _mount_property(
    target: PropertyRef,
    component_path: tuple[str, ...],
) -> PropertyRef:
    return PropertyRef(target.interface_id, component_path, target.property_id)


def _quantity_value(value: DriverScalar, unit: str) -> float:
    return cast("sc.Quantity", value).to(unit).value


def _resample(
    samples: tuple[float, ...],
    *,
    source_rate_hz: float,
    target_rate_hz: float,
    count: int,
    repeat: bool,
) -> tuple[float, ...]:
    selected: list[float] = []
    for index in range(count):
        source_position = index * source_rate_hz / target_rate_hz
        if repeat:
            source_position %= len(samples)
        lower = int(source_position)
        if lower >= len(samples):
            selected.append(0.0)
            continue
        upper = min(lower + 1, len(samples) - 1)
        fraction = source_position - lower
        selected.append(samples[lower] * (1.0 - fraction) + samples[upper] * fraction)
    return tuple(selected)


__all__ = [
    "AWG_OUTPUT_COMPONENT_IDS",
    "DIGITIZER_INPUT_COMPONENT_IDS",
    "OSCILLOSCOPE_INPUT_COMPONENT_IDS",
    "VIRTUAL_AWG_DRIVER_ID",
    "VIRTUAL_AWG_DRIVER_SPEC",
    "VIRTUAL_DIGITIZER_DRIVER_ID",
    "VIRTUAL_DIGITIZER_DRIVER_SPEC",
    "VIRTUAL_OSCILLOSCOPE_DRIVER_ID",
    "VIRTUAL_OSCILLOSCOPE_DRIVER_SPEC",
    "BenchSignalWorld",
    "CapturedBenchTrace",
    "VirtualAwg",
    "VirtualDigitizer",
    "VirtualOscilloscope",
]
