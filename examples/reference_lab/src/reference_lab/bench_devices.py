"""Virtual bare AWGs, digitizer, and oscilloscope for the reference lab."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

import numpy as np
import scopecat as sc
from numpy.typing import NDArray
from scopecat.kernel.numpy_storage import freeze_ndarray
from scopecat.program.measurement_types import MeasurementDType
from scopecat.records.measurement import (
    MeasurementAcquisitionValue,
    MeasurementArray,
    MeasurementUnavailable,
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
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    InstrumentDescription,
    PropertyRef,
    instrument_component,
    interface_mount,
    state_readback,
)

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
    ANALOG_WAVEFORM_OUTPUT_ENABLED,
    ANALOG_WAVEFORM_OUTPUT_OFFSET,
    ANALOG_WAVEFORM_OUTPUT_PLAY,
    ANALOG_WAVEFORM_OUTPUT_RESET,
    ANALOG_WAVEFORM_OUTPUT_WAVEFORM,
    AWG_ARM_PROGRAM,
    AWG_LOAD_PROGRAM,
    AWG_PROGRAM,
    AWG_RUN_MODE,
    AWG_SAMPLE_RATE,
    DIGITIZER_ARM_PROGRAM,
    DIGITIZER_FETCH_PROGRAM_IQ,
    DIGITIZER_INPUT_COUPLING,
    DIGITIZER_INPUT_ENABLED,
    DIGITIZER_INPUT_RANGE,
    DIGITIZER_LOAD_PROGRAM,
    DIGITIZER_PROGRAM,
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
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
    analog_waveform_output_interface,
    awg_sequencer_interface,
    digitizer_control_interface,
    digitizer_input_interface,
    oscilloscope_control_interface,
    oscilloscope_input_interface,
    trigger_coordinator_interface,
)
from reference_lab.interfaces import (
    CLOCK_REFERENCE_FREQUENCY,
    CLOCK_REFERENCE_LOCKED,
    CLOCK_REFERENCE_SOURCE,
    clock_reference_interface,
)
from reference_lab.payloads import (
    DecodedAwgEntry,
    DecodedAwgProgram,
    DecodedDigitizerProgram,
    DecodedMaterializedAwgProgram,
    DecodedSampledWaveform,
    DecodedTriggerProgram,
    materialize_awg_program,
)
from reference_lab.targets.list_mode.iq_semantics import (
    integrate_rectangular_iq,
)
from reference_lab.virtual_lab.capture_payload import DecodedVirtualCaptureQueue
from reference_lab.virtual_lab.capture_plant import (
    VIRTUAL_CAPTURE_LOAD,
    VIRTUAL_CAPTURE_QUEUE,
    virtual_capture_source_interface,
)

AWG_OUTPUT_COMPONENT_IDS = tuple(f"ch{index}" for index in range(1, 9))
DIGITIZER_INPUT_COMPONENT_IDS = ("ch1", "ch2")
OSCILLOSCOPE_INPUT_COMPONENT_IDS = ("ch1", "ch2", "ch3", "ch4")
type BenchSamples = NDArray[np.float64]
VIRTUAL_AWG_DRIVER_ID = "reference_lab.virtual.awg"
VIRTUAL_DIGITIZER_DRIVER_ID = "reference_lab.virtual.digitizer"
VIRTUAL_OSCILLOSCOPE_DRIVER_ID = "reference_lab.virtual.oscilloscope"
VIRTUAL_TIMING_CONTROLLER_DRIVER_ID = "reference_lab.virtual.timing_controller"


def _virtual_driver_spec(
    driver_id: str,
    label: str,
    *,
    channel_option: str,
) -> DriverSpec:
    return DriverSpec(
        driver_id=driver_id,
        implementation_version="v1",
        label=label,
        connections=(
            DriverConnectionSpec(
                kind="virtual",
                options_schema={
                    "type": "object",
                    "properties": {
                        channel_option: {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
            ),
        ),
    )


VIRTUAL_AWG_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_AWG_DRIVER_ID,
    "Virtual configurable-channel AWG",
    channel_option="output_count",
)
VIRTUAL_DIGITIZER_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_DIGITIZER_DRIVER_ID,
    "Virtual configurable-channel digitizer",
    channel_option="input_count",
)
VIRTUAL_OSCILLOSCOPE_DRIVER_SPEC = _virtual_driver_spec(
    VIRTUAL_OSCILLOSCOPE_DRIVER_ID,
    "Virtual configurable-channel oscilloscope",
    channel_option="input_count",
)
VIRTUAL_TIMING_CONTROLLER_DRIVER_SPEC = DriverSpec(
    driver_id=VIRTUAL_TIMING_CONTROLLER_DRIVER_ID,
    implementation_version="v1",
    label="Virtual timing controller",
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


@dataclass(frozen=True, slots=True)
class CapturedBenchTrace:
    time_s: NDArray[np.float64] = field(repr=False, compare=False)
    voltage_v: NDArray[np.float64] = field(repr=False, compare=False)
    source_component_path: tuple[str, ...]
    source_sample_rate_hz: float
    scope_sample_rate_hz: float


@dataclass(frozen=True, slots=True)
class ArmedAwgWaveform:
    component_path: tuple[str, ...]
    normalized_samples: tuple[float, ...] | np.ndarray = field(
        repr=False,
        compare=False,
    )
    sample_rate_hz: float
    amplitude_v: float
    offset_v: float
    output_enabled: bool
    repeat: bool


@dataclass(slots=True)
class BenchSignalWorld:
    """Shared trigger and analog-signal world for the virtual bench."""

    scope_armed: bool = False
    scope_sample_rate_hz: float = 1.0e9
    scope_record_length: int = 16
    capture: CapturedBenchTrace | None = None
    armed_awg_programs: dict[str, tuple[tuple[ArmedAwgWaveform, ...], ...]] = field(
        default_factory=dict
    )
    armed_digitizer_programs: dict[str, DecodedDigitizerProgram] = field(
        default_factory=dict
    )
    digitizer_program_captures: dict[
        tuple[str, tuple[str, ...]], tuple[tuple[int, BenchSamples], ...]
    ] = field(default_factory=dict)
    capture_queue: list[dict[tuple[str, tuple[str, ...]], BenchSamples]] = field(
        default_factory=list
    )
    trigger_count: int = 0

    def arm_scope(self, *, sample_rate_hz: float, record_length: int) -> None:
        self.scope_armed = True
        self.scope_sample_rate_hz = sample_rate_hz
        self.scope_record_length = record_length
        self.capture = None

    def emit(
        self,
        *,
        component_path: tuple[str, ...],
        normalized_samples: Sequence[float] | np.ndarray,
        sample_rate_hz: float,
        amplitude_v: float,
        offset_v: float,
        output_enabled: bool,
        repeat: bool,
    ) -> bool:
        if not self.scope_armed:
            return False
        times = np.arange(self.scope_record_length, dtype=np.float64) / (
            self.scope_sample_rate_hz
        )
        normalized = _resample(
            normalized_samples,
            source_rate_hz=sample_rate_hz,
            target_rate_hz=self.scope_sample_rate_hz,
            count=self.scope_record_length,
            repeat=repeat,
        )
        voltages = (
            offset_v + amplitude_v * normalized
            if output_enabled
            else np.zeros(self.scope_record_length, dtype=np.float64)
        )
        self.capture = CapturedBenchTrace(
            time_s=cast(
                "NDArray[np.float64]",
                freeze_ndarray(cast("NDArray[np.generic]", times)),
            ),
            voltage_v=cast(
                "NDArray[np.float64]",
                freeze_ndarray(cast("NDArray[np.generic]", voltages)),
            ),
            source_component_path=component_path,
            source_sample_rate_hz=sample_rate_hz,
            scope_sample_rate_hz=self.scope_sample_rate_hz,
        )
        self.scope_armed = False
        return True

    def abort_scope(self) -> None:
        self.scope_armed = False

    def arm_awg_program(
        self,
        instrument_id: str,
        entries: tuple[tuple[ArmedAwgWaveform, ...], ...],
    ) -> None:
        self.armed_awg_programs[instrument_id] = entries

    def is_awg_program_armed(self, instrument_id: str) -> bool:
        return instrument_id in self.armed_awg_programs

    def arm_digitizer_program(
        self,
        instrument_id: str,
        program: DecodedDigitizerProgram,
    ) -> None:
        self.armed_digitizer_programs[instrument_id] = program

    def is_digitizer_program_armed(self, instrument_id: str) -> bool:
        return instrument_id in self.armed_digitizer_programs

    def load_capture_queue(self, queue: DecodedVirtualCaptureQueue) -> None:
        self.capture_queue = [
            {
                (trace.instrument_id, trace.component_path): trace.samples
                for trace in capture.traces
            }
            for capture in queue.captures
        ]

    def run_program(
        self,
        program: DecodedTriggerProgram,
    ) -> tuple[int, int]:
        expected_awgs = tuple(
            sorted(
                {
                    instrument_id
                    for entry in program.entries
                    for instrument_id in entry.awg_instrument_ids
                }
            )
        )
        expected_digitizers = tuple(
            sorted(
                {
                    instrument_id
                    for entry in program.entries
                    for instrument_id in entry.digitizer_instrument_ids
                }
            )
        )
        if tuple(sorted(self.armed_awg_programs)) != expected_awgs:
            raise ValueError("armed AWG programs do not match trigger participants")
        if tuple(sorted(self.armed_digitizer_programs)) != expected_digitizers:
            raise ValueError(
                "armed digitizer programs do not match trigger participants"
            )
        if any(
            len(entries) != len(program.entries)
            for entries in self.armed_awg_programs.values()
        ) or any(
            len(digitizer.entries) != len(program.entries)
            for digitizer in self.armed_digitizer_programs.values()
        ):
            raise ValueError("armed device programs do not match trigger entry count")

        captures: dict[tuple[str, tuple[str, ...]], list[tuple[int, BenchSamples]]] = {}
        for _shot_index in range(program.repetitions):
            for entry_index, trigger_entry in enumerate(program.entries):
                awg_ids = tuple(
                    sorted(
                        instrument_id
                        for instrument_id, entries in self.armed_awg_programs.items()
                        if entries[entry_index]
                    )
                )
                digitizer_ids = tuple(
                    sorted(
                        instrument_id
                        for instrument_id, digitizer in (
                            self.armed_digitizer_programs.items()
                        )
                        if digitizer.entries[entry_index].input_component_paths
                    )
                )
                if awg_ids != trigger_entry.awg_instrument_ids:
                    raise ValueError(
                        "AWG program entry does not match trigger participants"
                    )
                if digitizer_ids != trigger_entry.digitizer_instrument_ids:
                    raise ValueError(
                        "digitizer program entry does not match trigger participants"
                    )

                for instrument_id in trigger_entry.awg_instrument_ids:
                    for waveform in self.armed_awg_programs[instrument_id][entry_index]:
                        self.emit(
                            component_path=waveform.component_path,
                            normalized_samples=waveform.normalized_samples,
                            sample_rate_hz=waveform.sample_rate_hz,
                            amplitude_v=waveform.amplitude_v,
                            offset_v=waveform.offset_v,
                            output_enabled=waveform.output_enabled,
                            repeat=waveform.repeat,
                        )
                selected_capture = (
                    self.capture_queue.pop(0) if self.capture_queue else {}
                )
                for instrument_id in trigger_entry.digitizer_instrument_ids:
                    digitizer_entry = self.armed_digitizer_programs[
                        instrument_id
                    ].entries[entry_index]
                    for component_path in digitizer_entry.input_component_paths:
                        capture = selected_capture.get((instrument_id, component_path))
                        if capture is None:
                            capture = np.zeros(
                                digitizer_entry.sample_count,
                                dtype=np.float64,
                            )
                        captures.setdefault((instrument_id, component_path), []).append(
                            (
                                entry_index,
                                capture,
                            )
                        )
                self.trigger_count += 1

        self.digitizer_program_captures = {
            key: tuple(value) for key, value in captures.items()
        }
        awg_count = len(self.armed_awg_programs)
        digitizer_count = len(self.armed_digitizer_programs)
        self.armed_awg_programs.clear()
        self.armed_digitizer_programs.clear()
        return awg_count, digitizer_count

    def digitizer_program_segments(
        self,
        instrument_id: str,
        component_path: tuple[str, ...],
    ) -> tuple[tuple[int, BenchSamples], ...]:
        return self.digitizer_program_captures.get(
            (instrument_id, component_path),
            (),
        )

    def abort_instrument(self, instrument_id: str) -> None:
        self.armed_awg_programs.pop(instrument_id, None)
        self.armed_digitizer_programs.pop(instrument_id, None)
        self.digitizer_program_captures = {
            key: value
            for key, value in self.digitizer_program_captures.items()
            if key[0] != instrument_id
        }


class VirtualAwg:
    """Real-valued waveform outputs backed by one shared sample clock."""

    implementation_id = VIRTUAL_AWG_DRIVER_ID
    implementation_version = "v1"

    def __init__(
        self,
        instrument_id: str,
        world: BenchSignalWorld,
        *,
        output_count: int = 8,
    ) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._output_component_ids = tuple(
            f"ch{index}" for index in range(1, output_count + 1)
        )
        self._loaded_program: DecodedMaterializedAwgProgram | None = None
        self._state: dict[PropertyRef, DriverScalar] = {
            AWG_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            AWG_RUN_MODE: "once",
            CLOCK_REFERENCE_SOURCE: "external",
            CLOCK_REFERENCE_FREQUENCY: sc.Quantity(10.0e6, "Hz"),
            CLOCK_REFERENCE_LOCKED: True,
        }
        for channel_id in self._output_component_ids:
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
            label=f"Virtual {len(self._output_component_ids)}-channel AWG",
            description=(
                "A modular AWG model with an instrument-wide sample and reference "
                "clock and independently mounted real-valued DAC outputs."
            ),
            components=[
                instrument_component(
                    "outputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in self._output_component_ids
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
                for channel_id in self._output_component_ids
            ],
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        return state_readback(
            request,
            self._state,
            metadata={
                "mode": "virtual",
                "loaded_entry_count": (
                    0
                    if self._loaded_program is None
                    else len(self._loaded_program.entries)
                ),
                "program_armed": self._world.is_awg_program_armed(self.instrument_id),
            },
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        clock_changed = any(
            entry.target in {CLOCK_REFERENCE_SOURCE, CLOCK_REFERENCE_FREQUENCY}
            for entry in request.entries
        )
        if clock_changed:
            self._state[CLOCK_REFERENCE_LOCKED] = False
        for entry in request.entries:
            if not isinstance(entry.target, PropertyRef):
                raise ValueError("virtual AWG has no model-specific state members")
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
            None,
            metadata={"clock_settled": bool(self._state[CLOCK_REFERENCE_LOCKED])},
        )

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        if request.target.operation_id == AWG_LOAD_PROGRAM.operation_id:
            decoded = cast(
                "DecodedAwgProgram",
                cast("DriverPayload", request.arguments[AWG_PROGRAM.argument_id]).value,
            )
            self._loaded_program = materialize_awg_program(decoded)
            for channel_id in self._output_component_ids:
                self._state[
                    _mount_property(
                        ANALOG_WAVEFORM_OUTPUT_OFFSET,
                        ("outputs", channel_id),
                    )
                ] = sc.Quantity(0.0, "V")
            return DriverSuccess(
                None,
                metadata={
                    "operation_id": AWG_LOAD_PROGRAM.operation_id,
                    "entry_count": len(self._loaded_program.entries),
                },
            )

        if request.target.operation_id == AWG_ARM_PROGRAM.operation_id:
            if self._loaded_program is None:
                raise ValueError("AWG has no loaded program")
            self._world.arm_awg_program(
                self.instrument_id,
                tuple(
                    self._armed_waveforms(entry)
                    for entry in self._loaded_program.entries
                ),
            )
            return DriverSuccess(
                None,
                metadata={
                    "operation_id": AWG_ARM_PROGRAM.operation_id,
                    "entry_count": len(self._loaded_program.entries),
                },
            )

        component_path = request.target.component_path
        if request.target.operation_id == ANALOG_WAVEFORM_OUTPUT_RESET.operation_id:
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
            return DriverSuccess(
                None,
                metadata={"operation_id": ANALOG_WAVEFORM_OUTPUT_RESET.operation_id},
            )
        waveform = cast(
            "DecodedSampledWaveform",
            cast(
                "DriverPayload",
                request.arguments[ANALOG_WAVEFORM_OUTPUT_WAVEFORM.argument_id],
            ).value,
        )
        emitted, captured = self._play_waveform(
            component_path=component_path,
            samples=waveform.samples,
        )
        sample_rate = _quantity_value(self._state[AWG_SAMPLE_RATE], "Hz")
        run_mode = cast("str", self._state[AWG_RUN_MODE])
        return DriverSuccess(
            None,
            metadata={
                "component_path": list(component_path),
                "operation_id": ANALOG_WAVEFORM_OUTPUT_PLAY.operation_id,
                "sample_count": len(waveform.samples),
                "sample_rate_hz": sample_rate,
                "output_enabled": emitted,
                "run_mode": run_mode,
                "signal_emitted": emitted,
                "captured_by_scope": captured,
            },
        )

    def _armed_waveforms(
        self,
        entry: DecodedAwgEntry,
    ) -> tuple[ArmedAwgWaveform, ...]:
        sample_rate = _quantity_value(self._state[AWG_SAMPLE_RATE], "Hz")
        run_mode = cast("str", self._state[AWG_RUN_MODE])
        return tuple(
            ArmedAwgWaveform(
                component_path=waveform.component_path,
                normalized_samples=waveform.samples,
                sample_rate_hz=sample_rate,
                amplitude_v=_quantity_value(
                    self._state[
                        _mount_property(
                            ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
                            waveform.component_path,
                        )
                    ],
                    "V",
                ),
                offset_v=_quantity_value(
                    self._state[
                        _mount_property(
                            ANALOG_WAVEFORM_OUTPUT_OFFSET,
                            waveform.component_path,
                        )
                    ],
                    "V",
                ),
                output_enabled=cast(
                    "bool",
                    self._state[
                        _mount_property(
                            ANALOG_WAVEFORM_OUTPUT_ENABLED,
                            waveform.component_path,
                        )
                    ],
                ),
                repeat=run_mode == "continuous",
            )
            for waveform in entry.waveforms
        )

    def _play_waveform(
        self,
        *,
        component_path: tuple[str, ...],
        samples: tuple[float, ...],
    ) -> tuple[bool, bool]:
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
            normalized_samples=samples,
            sample_rate_hz=sample_rate,
            amplitude_v=amplitude,
            offset_v=offset,
            output_enabled=output_enabled,
            repeat=run_mode == "continuous",
        )
        return output_enabled, captured

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        del request
        raise NotImplementedError

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        self._world.abort_instrument(self.instrument_id)
        for channel_id in self._output_component_ids:
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

    def __init__(
        self,
        instrument_id: str,
        world: BenchSignalWorld,
        *,
        input_count: int = 2,
    ) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._loaded_program: DecodedDigitizerProgram | None = None
        self._input_component_ids = tuple(
            f"ch{index}" for index in range(1, input_count + 1)
        )
        self._state: dict[PropertyRef, DriverScalar] = {
            DIGITIZER_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            DIGITIZER_RECORD_LENGTH: 1024,
            DIGITIZER_TRIGGER_SOURCE: "external",
        }
        for channel_id in self._input_component_ids:
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
            label=f"Virtual {len(self._input_component_ids)}-channel digitizer",
            description=(
                "A bare ADC model; list-mode demodulation windows belong to the "
                "quantum target and reference physical inputs by route."
            ),
            components=[
                instrument_component(
                    "inputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in self._input_component_ids
                    ),
                )
            ],
            interfaces=[digitizer_control_interface(), input_interface],
            interface_mounts=[
                interface_mount(input_interface.id, "inputs", channel_id)
                for channel_id in self._input_component_ids
            ],
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        return state_readback(
            request,
            self._state,
            metadata={
                "mode": "virtual",
                "program_armed": self._world.is_digitizer_program_armed(
                    self.instrument_id
                ),
                "loaded_entry_count": (
                    0
                    if self._loaded_program is None
                    else len(self._loaded_program.entries)
                ),
            },
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        for entry in request.entries:
            if not isinstance(entry.target, PropertyRef):
                raise ValueError("digitizer has no model-specific state members")
            value = entry.value
            if isinstance(value, sc.Quantity):
                unit = (
                    "Hz"
                    if entry.target.property_id == DIGITIZER_SAMPLE_RATE.property_id
                    else "V"
                )
                value = value.to(unit)
            self._state[entry.target] = value
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        if request.target.operation_id == DIGITIZER_LOAD_PROGRAM.operation_id:
            self._loaded_program = cast(
                "DecodedDigitizerProgram",
                cast(
                    "DriverPayload",
                    request.arguments[DIGITIZER_PROGRAM.argument_id],
                ).value,
            )
            return DriverSuccess(
                None,
                metadata={"entry_count": len(self._loaded_program.entries)},
            )
        if request.target.operation_id == DIGITIZER_ARM_PROGRAM.operation_id:
            if self._loaded_program is None:
                raise ValueError("digitizer has no loaded program")
            self._world.arm_digitizer_program(
                self.instrument_id,
                self._loaded_program,
            )
            return DriverSuccess(
                None,
                metadata={
                    "program_armed": True,
                    "entry_count": len(self._loaded_program.entries),
                },
            )
        raise ValueError(
            f"unsupported digitizer operation {request.target.operation_id!r}"
        )

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        sample_rate = _quantity_value(self._state[DIGITIZER_SAMPLE_RATE], "Hz")
        values: dict[AcquisitionResultRef, MeasurementAcquisitionValue] = {}
        assert self._loaded_program is not None
        segments = self._world.digitizer_program_segments(
            self.instrument_id,
            request.target.component_path,
        )
        if request.target.acquisition_id == DIGITIZER_FETCH_PROGRAM_IQ.acquisition_id:
            block: NDArray[np.float64] | NDArray[np.complex128] = np.fromiter(
                (
                    integrate_rectangular_iq(
                        trace,
                        start_sample=window.start_sample,
                        sample_count=window.sample_count,
                        sample_rate_hz=sample_rate,
                        demodulation_frequency_hz=(window.demodulation_frequency_hz),
                    )
                    for entry_index, trace in segments
                    for window in self._loaded_program.entries[entry_index].windows
                    if window.component_path == request.target.component_path
                ),
                dtype=np.complex128,
            )
            dtype: MeasurementDType = "complex128"
        else:
            traces = tuple(trace for _entry_index, trace in segments)
            block = (
                np.empty(0, dtype=np.float64)
                if not traces
                else traces[0]
                if len(traces) == 1
                else np.concatenate(traces)
            )
            dtype = "float64"
        if request.results:
            result = next(iter(request.results))
            dimensions = request.dimensions.get(result, ())
            if dimensions:
                [dimension] = dimensions
                if dimension.size is not None:
                    block = block[
                        (dimension.offset or 0) : (dimension.offset or 0)
                        + dimension.size
                    ]
        if request.results:
            measurement = MeasurementArray.create(
                dtype=dtype,
                unit="V",
                values=block,
            )
            values.update(dict.fromkeys(request.results, measurement))
        return DriverSuccess(
            DriverReadback(
                values=values,
                metadata={
                    "triggered": True,
                    "mode": "virtual",
                    "segment_count": len(segments),
                },
            )
        )

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        self._world.abort_instrument(self.instrument_id)


class VirtualTimingController:
    """A programmable shared-trigger source plus a test-only virtual plant input."""

    implementation_id = VIRTUAL_TIMING_CONTROLLER_DRIVER_ID
    implementation_version = "v1"

    def __init__(self, instrument_id: str, world: BenchSignalWorld) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._loaded_program: DecodedTriggerProgram | None = None
        self._started_programs: dict[str, DecodedTriggerProgram] = {}

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual timing controller",
            description=(
                "A single shared trigger edge for armed AWGs and digitizers. "
                "The virtual capture interface is a test-plant input."
            ),
            interfaces=[
                trigger_coordinator_interface(),
                virtual_capture_source_interface(),
            ],
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        return state_readback(
            request,
            {},
            metadata={
                "mode": "virtual",
                "trigger_count": self._world.trigger_count,
                "loaded_program_id": (
                    None
                    if self._loaded_program is None
                    else self._loaded_program.program_id
                ),
            },
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        del request
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        if request.target.operation_id == VIRTUAL_CAPTURE_LOAD.operation_id:
            queue = cast(
                "DecodedVirtualCaptureQueue",
                cast(
                    "DriverPayload",
                    request.arguments[VIRTUAL_CAPTURE_QUEUE.argument_id],
                ).value,
            )
            self._world.load_capture_queue(queue)
            return DriverSuccess(
                None,
                metadata={"capture_count": len(queue.captures)},
            )
        if request.target.operation_id == TRIGGER_LOAD_PROGRAM.operation_id:
            self._loaded_program = cast(
                "DecodedTriggerProgram",
                cast(
                    "DriverPayload",
                    request.arguments[TRIGGER_PROGRAM.argument_id],
                ).value,
            )
            return DriverSuccess(
                None,
                metadata={
                    "program_id": self._loaded_program.program_id,
                    "entry_count": len(self._loaded_program.entries),
                    "repetitions": self._loaded_program.repetitions,
                },
            )
        if request.target.operation_id in {
            TRIGGER_START_PROGRAM.operation_id,
            TRIGGER_START_PROGRAM_IDEMPOTENT.operation_id,
        }:
            if self._loaded_program is None:
                raise ValueError("timing controller has no loaded program")
            idempotent = (
                request.target.operation_id
                == TRIGGER_START_PROGRAM_IDEMPOTENT.operation_id
            )
            cached = self._started_programs.get(self._loaded_program.program_id)
            if idempotent and cached is not None:
                if cached != self._loaded_program:
                    raise ValueError(
                        "trigger program id was reused with different contents"
                    )
                awg_count, digitizer_count, replayed = 0, 0, True
            else:
                awg_count, digitizer_count = self._world.run_program(
                    self._loaded_program
                )
                replayed = False
                if idempotent:
                    self._started_programs[self._loaded_program.program_id] = (
                        self._loaded_program
                    )
            return DriverSuccess(
                None,
                metadata={
                    "armed_awg_count": awg_count,
                    "armed_digitizer_count": digitizer_count,
                    "trigger_count": self._world.trigger_count,
                    "trigger_program_id": self._loaded_program.program_id,
                    "replayed": replayed,
                },
            )
        raise ValueError(
            f"unsupported timing operation {request.target.operation_id!r}"
        )

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        del request
        raise NotImplementedError

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


class VirtualOscilloscope:
    """Four analog inputs sharing one timebase and trigger engine."""

    implementation_id = VIRTUAL_OSCILLOSCOPE_DRIVER_ID
    implementation_version = "v1"

    def __init__(
        self,
        instrument_id: str,
        world: BenchSignalWorld,
        *,
        input_count: int = 4,
    ) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._input_component_ids = tuple(
            f"ch{index}" for index in range(1, input_count + 1)
        )
        self._state: dict[PropertyRef, DriverScalar] = {
            OSCILLOSCOPE_SAMPLE_RATE: sc.Quantity(1.0e9, "Hz"),
            OSCILLOSCOPE_RECORD_LENGTH: 16,
            OSCILLOSCOPE_TRIGGER_SOURCE: "external",
            OSCILLOSCOPE_TRIGGER_LEVEL: sc.Quantity(0.0, "V"),
        }
        for channel_id in self._input_component_ids:
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
            label=f"Virtual {len(self._input_component_ids)}-channel oscilloscope",
            description=(
                "A manual-informed scope model with an instrument-wide acquisition "
                "engine and independently mounted analog inputs."
            ),
            components=[
                instrument_component(
                    "inputs",
                    components=tuple(
                        instrument_component(channel_id)
                        for channel_id in self._input_component_ids
                    ),
                ),
            ],
            interfaces=[oscilloscope_control_interface(), input_interface],
            interface_mounts=[
                interface_mount(input_interface.id, "inputs", channel_id)
                for channel_id in self._input_component_ids
            ],
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        return state_readback(
            request,
            {**self._state, OSCILLOSCOPE_ARMED: self._world.scope_armed},
            metadata={"mode": "virtual"},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        for entry in request.entries:
            if not isinstance(entry.target, PropertyRef):
                raise ValueError("oscilloscope has no model-specific state members")
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
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        del request
        sample_rate = _quantity_value(self._state[OSCILLOSCOPE_SAMPLE_RATE], "Hz")
        record_length = cast("int", self._state[OSCILLOSCOPE_RECORD_LENGTH])
        self._world.arm_scope(
            sample_rate_hz=sample_rate,
            record_length=record_length,
        )
        return DriverSuccess(
            None,
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
        values: dict[AcquisitionResultRef, MeasurementAcquisitionValue] = {}
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
    samples: Sequence[float] | np.ndarray,
    *,
    source_rate_hz: float,
    target_rate_hz: float,
    count: int,
    repeat: bool,
) -> NDArray[np.float64]:
    source = np.asarray(samples, dtype=np.float64)
    selected = np.zeros(count, dtype=np.float64)
    if source.size == 0 or count == 0:
        return selected
    positions = np.arange(count, dtype=np.float64) * source_rate_hz / target_rate_hz
    if repeat:
        positions %= source.size
    valid = positions < source.size
    selected_positions = positions[valid]
    lower = selected_positions.astype(np.int64)
    upper = np.minimum(lower + 1, source.size - 1)
    fraction = selected_positions - lower
    selected[valid] = source[lower] * (1.0 - fraction) + source[upper] * fraction
    return selected


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
    "VIRTUAL_TIMING_CONTROLLER_DRIVER_ID",
    "VIRTUAL_TIMING_CONTROLLER_DRIVER_SPEC",
    "ArmedAwgWaveform",
    "BenchSignalWorld",
    "CapturedBenchTrace",
    "VirtualAwg",
    "VirtualDigitizer",
    "VirtualOscilloscope",
    "VirtualTimingController",
]
