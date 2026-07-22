"""Observable preparation and execution evidence for the demo quantum lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from scopecat_quantum import Play, PreparedQuantumTargetEntry, PulseEventId
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListDomainRuntime,
    FakeListTarget,
)


@dataclass(frozen=True, slots=True)
class QuantumLabPointValues:
    """Resolved program and compiler inputs for one logical point."""

    ordinal: int
    values: tuple[tuple[str, object], ...]
    compiler_parameter_fingerprint: str

    def value(self, name: str) -> object:
        for input_name, value in self.values:
            if input_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class QuantumLabPreparationEvidence:
    """Typed fake-target preparation evidence for one compiled batch."""

    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]
    _target: FakeListTarget = field(repr=False)
    entries: tuple[PreparedQuantumTargetEntry, ...]
    artifact: FakeListArtifact
    artifact_fingerprint: str

    @property
    def program_id(self) -> str:
        return self.program.id

    def event_samples(
        self,
        entry: PreparedQuantumTargetEntry,
        event_id: PulseEventId,
    ) -> tuple[complex, ...]:
        """Return compiled output samples for one prepared drive event."""

        [event] = tuple(item for item in entry.scheduled.events if item.id == event_id)
        if not isinstance(event.instruction, Play):
            msg = "quantum lab event evidence requires a Play instruction"
            raise ValueError(msg)
        channel = self._target.output_channel(event.instruction.signal)
        if channel is None:
            msg = "quantum lab event signal is not bound to an output channel"
            raise ValueError(msg)
        [artifact_entry] = tuple(
            item for item in self.artifact.entries if item.entry_id == entry.id
        )
        [waveform] = tuple(
            item for item in artifact_entry.waveforms if item.channel_id == channel
        )
        rate = Decimal(self.artifact.sample_rate_hz)
        start = event.start_seconds * rate
        count = event.duration_seconds * rate
        if start != start.to_integral_value() or count != count.to_integral_value():
            msg = "compiled quantum lab event is not aligned to the sample grid"
            raise ValueError(msg)
        first = int(start)
        return waveform.samples[first : first + int(count)]


class QuantumLabTrace:
    """Collect lab observability without making it compiler policy.

    The compiler emits immutable evidence and registers the runtimes it uses;
    notebooks and tests inspect this collaborator instead of turning compiler
    state into part of the domain-compilation contract.
    """

    def __init__(self) -> None:
        self._preparations: list[QuantumLabPreparationEvidence] = []
        self._runtimes: list[FakeListDomainRuntime] = []

    @property
    def physical_execution_count(self) -> int:
        return sum(runtime.physical_execution_count for runtime in self._runtimes)

    @property
    def all_preparations(self) -> tuple[QuantumLabPreparationEvidence, ...]:
        return tuple(self._preparations)

    def preparations(
        self,
        program_id: str,
    ) -> tuple[QuantumLabPreparationEvidence, ...]:
        """Return immutable preparation evidence for one authored Program id."""

        return tuple(
            preparation
            for preparation in self._preparations
            if preparation.program.id == program_id
        )

    def record_preparation(self, evidence: QuantumLabPreparationEvidence) -> None:
        self._preparations.append(evidence)

    def register_runtime(self, runtime: FakeListDomainRuntime) -> None:
        self._runtimes.append(runtime)


__all__ = [
    "QuantumLabPointValues",
    "QuantumLabPreparationEvidence",
    "QuantumLabTrace",
]
