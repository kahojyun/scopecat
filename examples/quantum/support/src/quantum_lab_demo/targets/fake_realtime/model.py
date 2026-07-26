"""Physical capabilities and structured artifacts for the fake realtime target."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat_quantum._ids import (
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.programs import StructuredQuantumPulseProgram
from scopecat_quantum.pulses import AcquireSignal, PlaySignal
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetAcquisitionLayout,
)


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_positive(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


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
    """Capabilities used by structured-program validation and execution."""

    id: TargetId
    clock_hz: int
    max_result_records: int
    max_loop_iterations: int
    decision_latency_ticks: int
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
            ("max_result_records", self.max_result_records),
            ("max_loop_iterations", self.max_loop_iterations),
            ("decision_latency_ticks", self.decision_latency_ticks),
            ("discrimination_latency_ticks", self.discrimination_latency_ticks),
        ):
            _require_positive(value, field_name=field_name)
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("realtime target outputs must be unique")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError("realtime target inputs must be unique")
        if len(set(self.discriminator_ids)) != len(self.discriminator_ids):
            raise ValueError("realtime target discriminator ids must be unique")
        if len({item.signal for item in self.output_bindings}) != len(
            self.output_bindings
        ):
            raise ValueError("realtime output signals must be bound exactly once")
        if len({item.signal for item in self.input_bindings}) != len(
            self.input_bindings
        ):
            raise ValueError("realtime input signals must be bound exactly once")
        if any(item.output not in self.outputs for item in self.output_bindings):
            raise ValueError("realtime output bindings require configured outputs")
        if any(item.input not in self.inputs for item in self.input_bindings):
            raise ValueError("realtime input bindings require configured inputs")
        routes = {(item.source, item.destination) for item in self.feedback_routes}
        if len(routes) != len(self.feedback_routes):
            raise ValueError("realtime feedback routes must be unique")
        if any(item.source not in self.inputs for item in self.feedback_routes):
            raise ValueError("realtime feedback routes require configured inputs")
        if any(item.destination not in self.outputs for item in self.feedback_routes):
            raise ValueError("realtime feedback routes require configured outputs")
        object.__setattr__(
            self,
            "_capability_fingerprint",
            stable_content_hash(content_fingerprint(self._capability_payload())),
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
        return (
            "quantum_lab_demo.fake_realtime.capabilities.v2",
            self.id,
            self.clock_hz,
            self.max_result_records,
            self.max_loop_iterations,
            self.decision_latency_ticks,
            self.discrimination_latency_ticks,
            self.discriminator_ids,
            self.outputs,
            self.inputs,
            self.output_bindings,
            self.input_bindings,
            self.feedback_routes,
        )


@dataclass(frozen=True, slots=True)
class FakeRealtimeCompileRequest:
    """Closed request carrying one already-bound structured pulse program."""

    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    entry_id: TargetCompileEntryId
    program: StructuredQuantumPulseProgram
    result_layouts: tuple[TargetAcquisitionLayout, ...]
    repetitions: int

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
    """Target artifact that directly owns the verified structured program."""

    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int
    program: StructuredQuantumPulseProgram
    result_layouts: tuple[TargetAcquisitionLayout, ...]


__all__ = [
    "FakeFeedbackRoute",
    "FakeRealtimeArtifact",
    "FakeRealtimeCompileRequest",
    "FakeRealtimeInputBinding",
    "FakeRealtimeInputId",
    "FakeRealtimeOutputBinding",
    "FakeRealtimeOutputId",
    "FakeRealtimeTarget",
]
