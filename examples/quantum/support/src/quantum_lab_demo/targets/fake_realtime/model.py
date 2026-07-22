"""Immutable instruction and capability model for the fake realtime target."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from scopecat_quantum import (
    AcquireSignal,
    PlaySignal,
    RealtimeResultProvenance,
    TargetAcquisitionAddress,
    TargetAcquisitionLayout,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_positive(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True, order=True)
class FakeRealtimeOutputId:
    """One physical waveform-output lane."""

    value: str

    def __post_init__(self) -> None:
        _require_text(self.value, field_name="realtime output id")


@dataclass(frozen=True, slots=True, order=True)
class FakeRealtimeInputId:
    """One physical acquisition lane."""

    value: str

    def __post_init__(self) -> None:
        _require_text(self.value, field_name="realtime input id")


@dataclass(frozen=True, slots=True, order=True)
class FakeRealtimeRegister:
    """One target-local integer register."""

    value: str

    def __post_init__(self) -> None:
        _require_text(self.value, field_name="realtime register")


@dataclass(frozen=True, slots=True)
class FakeRealtimeOutputBinding:
    signal: PlaySignal
    output: FakeRealtimeOutputId


@dataclass(frozen=True, slots=True)
class FakeRealtimeInputBinding:
    signal: AcquireSignal
    input: FakeRealtimeInputId


@dataclass(frozen=True, slots=True)
class FakeFeedbackRoute:
    """A static measurement-to-control route and its minimum latency."""

    source: FakeRealtimeInputId
    destination: FakeRealtimeOutputId
    latency_ticks: int

    def __post_init__(self) -> None:
        _require_positive(self.latency_ticks, field_name="feedback route latency")


@dataclass(frozen=True, slots=True)
class FakeRealtimeTarget:
    """Finite capabilities of one deterministic realtime control processor."""

    id: TargetId
    clock_hz: int
    max_instructions: int
    max_waveforms: int
    max_registers: int
    max_result_records: int
    max_loop_iterations: int
    classical_instruction_ticks: int
    discrimination_latency_ticks: int
    discriminator_ids: tuple[str, ...]
    outputs: tuple[FakeRealtimeOutputId, ...]
    inputs: tuple[FakeRealtimeInputId, ...]
    output_bindings: tuple[FakeRealtimeOutputBinding, ...]
    input_bindings: tuple[FakeRealtimeInputBinding, ...]
    feedback_routes: tuple[FakeFeedbackRoute, ...]
    _capability_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("clock_hz", self.clock_hz),
            ("max_instructions", self.max_instructions),
            ("max_waveforms", self.max_waveforms),
            ("max_registers", self.max_registers),
            ("max_result_records", self.max_result_records),
            ("max_loop_iterations", self.max_loop_iterations),
            ("classical_instruction_ticks", self.classical_instruction_ticks),
            ("discrimination_latency_ticks", self.discrimination_latency_ticks),
        ):
            _require_positive(value, field_name=field_name)
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("realtime target outputs must be unique")
        if len(set(self.discriminator_ids)) != len(self.discriminator_ids):
            raise ValueError("realtime target discriminator ids must be unique")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError("realtime target inputs must be unique")
        if len({binding.signal for binding in self.output_bindings}) != len(
            self.output_bindings
        ):
            raise ValueError("realtime output signals must be bound exactly once")
        if len({binding.signal for binding in self.input_bindings}) != len(
            self.input_bindings
        ):
            raise ValueError("realtime input signals must be bound exactly once")
        if any(binding.output not in self.outputs for binding in self.output_bindings):
            raise ValueError("realtime output bindings require configured outputs")
        if any(binding.input not in self.inputs for binding in self.input_bindings):
            raise ValueError("realtime input bindings require configured inputs")
        routes = {(route.source, route.destination) for route in self.feedback_routes}
        if len(routes) != len(self.feedback_routes):
            raise ValueError("realtime feedback routes must be unique")
        if any(route.source not in self.inputs for route in self.feedback_routes):
            raise ValueError("realtime feedback routes require configured inputs")
        if any(route.destination not in self.outputs for route in self.feedback_routes):
            raise ValueError("realtime feedback routes require configured outputs")
        object.__setattr__(
            self,
            "_capability_fingerprint",
            _fingerprint(self._capability_payload()),
        )

    @property
    def capability_fingerprint(self) -> str:
        return self._capability_fingerprint

    def feedback_latency(
        self,
        source: FakeRealtimeInputId,
        destination: FakeRealtimeOutputId,
    ) -> int | None:
        for route in self.feedback_routes:
            if route.source == source and route.destination == destination:
                return route.latency_ticks
        return None

    def output_for(self, signal: PlaySignal) -> FakeRealtimeOutputId | None:
        for binding in self.output_bindings:
            if binding.signal == signal:
                return binding.output
        return None

    def input_for(self, signal: AcquireSignal) -> FakeRealtimeInputId | None:
        for binding in self.input_bindings:
            if binding.signal == signal:
                return binding.input
        return None

    def _capability_payload(self) -> object:
        return {
            "schema": "quantum_lab_demo.fake_realtime.capabilities.v1",
            "target_id": self.id.value,
            "clock_hz": self.clock_hz,
            "max_instructions": self.max_instructions,
            "max_waveforms": self.max_waveforms,
            "max_registers": self.max_registers,
            "max_result_records": self.max_result_records,
            "max_loop_iterations": self.max_loop_iterations,
            "classical_instruction_ticks": self.classical_instruction_ticks,
            "discrimination_latency_ticks": self.discrimination_latency_ticks,
            "discriminator_ids": list(self.discriminator_ids),
            "outputs": [item.value for item in self.outputs],
            "inputs": [item.value for item in self.inputs],
            "output_bindings": [
                {"signal": repr(binding.signal), "output": binding.output.value}
                for binding in self.output_bindings
            ],
            "input_bindings": [
                {"signal": repr(binding.signal), "input": binding.input.value}
                for binding in self.input_bindings
            ],
            "feedback_routes": [
                {
                    "source": route.source.value,
                    "destination": route.destination.value,
                    "latency_ticks": route.latency_ticks,
                }
                for route in self.feedback_routes
            ],
        }


@dataclass(frozen=True, slots=True)
class RtLabel:
    name: str

    def __post_init__(self) -> None:
        _require_text(self.name, field_name="realtime label")


@dataclass(frozen=True, slots=True)
class RtMove:
    destination: FakeRealtimeRegister
    source: int | FakeRealtimeRegister


@dataclass(frozen=True, slots=True)
class RtXor:
    destination: FakeRealtimeRegister
    left: FakeRealtimeRegister
    right: FakeRealtimeRegister


@dataclass(frozen=True, slots=True)
class RtScheduledPlay:
    output: FakeRealtimeOutputId
    waveform_id: str
    start_ticks: int
    duration_ticks: int

    def __post_init__(self) -> None:
        _require_text(self.waveform_id, field_name="waveform id")
        if isinstance(self.start_ticks, bool) or self.start_ticks < 0:
            raise ValueError("scheduled play start must be a non-negative integer")
        _require_positive(self.duration_ticks, field_name="scheduled play duration")


@dataclass(frozen=True, slots=True)
class RtScheduledAcquire:
    input: FakeRealtimeInputId
    result_id: str
    destination: FakeRealtimeRegister
    start_ticks: int
    duration_ticks: int
    record: bool = True

    def __post_init__(self) -> None:
        _require_text(self.result_id, field_name="acquisition result id")
        if isinstance(self.start_ticks, bool) or self.start_ticks < 0:
            raise ValueError("scheduled acquire start must be a non-negative integer")
        _require_positive(
            self.duration_ticks,
            field_name="scheduled acquire duration",
        )


@dataclass(frozen=True, slots=True)
class RtPulseTimeline:
    duration_ticks: int
    plays: tuple[RtScheduledPlay, ...] = ()
    acquisitions: tuple[RtScheduledAcquire, ...] = ()

    def __post_init__(self) -> None:
        _require_positive(self.duration_ticks, field_name="pulse timeline duration")
        if not self.plays and not self.acquisitions:
            raise ValueError("pulse timelines require at least one physical action")
        if any(
            item.start_ticks + item.duration_ticks > self.duration_ticks
            for item in (*self.plays, *self.acquisitions)
        ):
            raise ValueError("scheduled actions must fit within their pulse timeline")


@dataclass(frozen=True, slots=True)
class RtWait:
    duration_ticks: int

    def __post_init__(self) -> None:
        _require_positive(self.duration_ticks, field_name="wait duration")


@dataclass(frozen=True, slots=True)
class RtJump:
    target: str

    def __post_init__(self) -> None:
        _require_text(self.target, field_name="jump target")


@dataclass(frozen=True, slots=True)
class RtJumpIf:
    source: FakeRealtimeRegister
    equals: int
    target: str

    def __post_init__(self) -> None:
        _require_text(self.target, field_name="conditional jump target")


@dataclass(frozen=True, slots=True)
class RtDecrementAndJump:
    counter: FakeRealtimeRegister
    target: str

    def __post_init__(self) -> None:
        _require_text(self.target, field_name="loop jump target")


@dataclass(frozen=True, slots=True)
class RtEmit:
    result_id: str
    source: FakeRealtimeRegister

    def __post_init__(self) -> None:
        _require_text(self.result_id, field_name="emitted result id")


@dataclass(frozen=True, slots=True)
class RtHalt:
    pass


type FakeRealtimeInstruction = (
    RtLabel
    | RtMove
    | RtXor
    | RtPulseTimeline
    | RtWait
    | RtJump
    | RtJumpIf
    | RtDecrementAndJump
    | RtEmit
    | RtHalt
)


@dataclass(frozen=True, slots=True)
class FakeRealtimeProgram:
    """One target-owned linear microprogram with symbolic branch labels."""

    id: str
    instructions: tuple[FakeRealtimeInstruction, ...]

    def __post_init__(self) -> None:
        _require_text(self.id, field_name="realtime program id")
        if not self.instructions:
            raise ValueError("realtime programs require instructions")


@dataclass(frozen=True, slots=True)
class FakeRealtimeCompileRequest:
    """Closed target-owned request retaining one realtime executable."""

    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    entry_id: TargetCompileEntryId
    program: FakeRealtimeProgram
    result_layouts: tuple[TargetAcquisitionLayout, ...]
    repetitions: int
    realtime_result_provenance: tuple[RealtimeResultProvenance, ...] = ()

    def __post_init__(self) -> None:
        _require_text(
            self.capability_fingerprint,
            field_name="realtime capability fingerprint",
        )
        _require_positive(self.repetitions, field_name="realtime repetitions")
        if any(layout.entry_id != self.entry_id for layout in self.result_layouts):
            raise ValueError("realtime result layouts must belong to the request entry")
        addresses = self.acquisition_addresses
        if len(set(addresses)) != len(addresses):
            raise ValueError("realtime result layouts must have unique leaf addresses")
        provenance_ids = tuple(
            item.result_id for item in self.realtime_result_provenance
        )
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("realtime emitted result provenance must be unique")
        declared = {layout.slot_id.local_id for layout in self.result_layouts}
        if {item.local_id for item in provenance_ids} - declared:
            raise ValueError("realtime emitted result provenance requires a layout")

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]:
        return (self.entry_id,)

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(
            address
            for layout in self.result_layouts
            for address in layout.acquisition_addresses
        )


@dataclass(frozen=True, slots=True)
class FakeRealtimeArtifact:
    """Immutable executable and provenance returned by the target compiler."""

    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int
    program: FakeRealtimeProgram
    result_layouts: tuple[TargetAcquisitionLayout, ...]
    labels: tuple[tuple[str, int], ...]
    realtime_result_provenance: tuple[RealtimeResultProvenance, ...] = ()


def instruction_payload(instruction: FakeRealtimeInstruction) -> object:
    """Project one instruction to canonical fingerprint data."""

    match instruction:
        case RtLabel(name=name):
            return {"op": "label", "name": name}
        case RtMove(destination=destination, source=source):
            return {
                "op": "move",
                "destination": destination.value,
                "source": source.value
                if isinstance(source, FakeRealtimeRegister)
                else source,
            }
        case RtXor(destination=destination, left=left, right=right):
            return {
                "op": "xor",
                "destination": destination.value,
                "left": left.value,
                "right": right.value,
            }
        case RtPulseTimeline(
            duration_ticks=duration,
            plays=plays,
            acquisitions=acquisitions,
        ):
            return {
                "op": "pulse_timeline",
                "duration_ticks": duration,
                "plays": [
                    {
                        "output": item.output.value,
                        "waveform_id": item.waveform_id,
                        "start_ticks": item.start_ticks,
                        "duration_ticks": item.duration_ticks,
                    }
                    for item in plays
                ],
                "acquisitions": [
                    {
                        "input": item.input.value,
                        "result_id": item.result_id,
                        "destination": item.destination.value,
                        "start_ticks": item.start_ticks,
                        "duration_ticks": item.duration_ticks,
                        "record": item.record,
                    }
                    for item in acquisitions
                ],
            }
        case RtWait(duration_ticks=duration):
            return {"op": "wait", "duration_ticks": duration}
        case RtJump(target=target):
            return {"op": "jump", "target": target}
        case RtJumpIf(source=source, equals=equals, target=target):
            return {
                "op": "jump_if",
                "source": source.value,
                "equals": equals,
                "target": target,
            }
        case RtDecrementAndJump(counter=counter, target=target):
            return {
                "op": "decrement_and_jump",
                "counter": counter.value,
                "target": target,
            }
        case RtEmit(result_id=result_id, source=source):
            return {"op": "emit", "result_id": result_id, "source": source.value}
        case RtHalt():
            return {"op": "halt"}


__all__ = [
    "FakeFeedbackRoute",
    "FakeRealtimeArtifact",
    "FakeRealtimeCompileRequest",
    "FakeRealtimeInputBinding",
    "FakeRealtimeInputId",
    "FakeRealtimeInstruction",
    "FakeRealtimeOutputBinding",
    "FakeRealtimeOutputId",
    "FakeRealtimeProgram",
    "FakeRealtimeRegister",
    "FakeRealtimeTarget",
    "RtDecrementAndJump",
    "RtEmit",
    "RtHalt",
    "RtJump",
    "RtJumpIf",
    "RtLabel",
    "RtMove",
    "RtPulseTimeline",
    "RtScheduledAcquire",
    "RtScheduledPlay",
    "RtWait",
    "RtXor",
    "instruction_payload",
]
