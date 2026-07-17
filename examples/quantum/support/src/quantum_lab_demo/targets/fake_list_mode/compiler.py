"""Pure compiler for the demo list-mode AWG and segmented digitizer target.

This laboratory-owned compiler translates canonical scheduled pulse programs
into physical list entries and acquisition windows. It validates sample-grid
alignment, signal bindings, overlap, amplitude, memory, list, shot, and frame
limits before producing an artifact; no instrument effect occurs here.

Physical list and segment positions are artifact layout, never logical result
identity. Entry-qualified event and acquisition addresses survive compilation
so runtime evidence can be correlated to the exact prepared quantum work.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from decimal import Decimal

from scopecat_quantum import (
    DRAG,
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    Barrier,
    Constant,
    Delay,
    DriveSignal,
    FrameSignal,
    Gaussian,
    Play,
    ReadoutSignal,
    ShiftPhase,
    TargetArtifactId,
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntry,
    TargetCompileEntryId,
    TargetCompileRequest,
    TargetCompilerId,
    TargetId,
)

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeAwgChannelId,
    FakeChannelWaveform,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListEntry,
    FakeListTarget,
    FakeOutputSignal,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    pulse_event_identity_payload,
    signal_key,
)


@dataclass(frozen=True, slots=True)
class _PlaySpan:
    channel_id: FakeAwgChannelId
    start_sample: int
    samples: tuple[complex, ...]

    @property
    def sample_count(self) -> int:
        return len(self.samples)


@dataclass(frozen=True, slots=True)
class _EntryPlan:
    list_index: int
    source: TargetCompileEntry
    sample_count: int
    plays: tuple[_PlaySpan, ...]
    acquisitions: tuple[FakeAcquisitionWindow, ...]

    @property
    def waveform_channels(self) -> tuple[FakeAwgChannelId, ...]:
        return tuple(sorted({play.channel_id for play in self.plays}))

    @property
    def waveform_memory_samples(self) -> int:
        return self.sample_count * len(self.waveform_channels)

    @property
    def capture_samples_per_repetition(self) -> int:
        return sum(window.sample_count for window in self.acquisitions)


@dataclass(frozen=True, slots=True)
class FakeListTargetCompiler:
    """Compile canonical pulse schedules into finite fake-hardware list payloads."""

    id: TargetCompilerId
    target: FakeListTarget

    @property
    def target_id(self) -> TargetId:
        return self.target.id

    @property
    def capability_fingerprint(self) -> str:
        return self.target.capability_fingerprint

    def compile(self, request: TargetCompileRequest) -> FakeListArtifact:
        """Compile one checked finite request without performing hardware effects."""

        self._validate_dispatch(request)

        issues: list[TargetCompilationIssue] = []
        if len(request.entries) > self.target.max_list_entries:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_entry_limit_exceeded",
                message=(
                    f"request has {len(request.entries)} list entries; target limit is "
                    f"{self.target.max_list_entries}"
                ),
            )
        if request.repetitions > self.target.max_repetitions:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_repetition_limit_exceeded",
                message=(
                    f"request has {request.repetitions} repetitions; target limit is "
                    f"{self.target.max_repetitions}"
                ),
            )

        plans = tuple(
            plan
            for list_index, entry in enumerate(request.entries)
            if (
                plan := self._plan_entry(
                    entry,
                    list_index=list_index,
                    issues=issues,
                )
            )
            is not None
        )
        waveform_memory_samples = sum(plan.waveform_memory_samples for plan in plans)
        capture_samples_per_repetition = sum(
            plan.capture_samples_per_repetition for plan in plans
        )
        capture_memory_samples = capture_samples_per_repetition * request.repetitions
        frame_count = (
            sum(len(plan.acquisitions) for plan in plans) * request.repetitions
        )

        if waveform_memory_samples > self.target.max_waveform_memory_samples:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_waveform_memory_limit_exceeded",
                message=(
                    f"compiled list requires {waveform_memory_samples} AWG samples; "
                    f"target memory limit is "
                    f"{self.target.max_waveform_memory_samples}"
                ),
            )
        if capture_memory_samples > self.target.max_capture_memory_samples:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_capture_memory_limit_exceeded",
                message=(
                    f"compiled list requires {capture_memory_samples} capture "
                    f"samples; target memory limit is "
                    f"{self.target.max_capture_memory_samples}"
                ),
            )
        if frame_count > self.target.max_frames:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_frame_limit_exceeded",
                message=(
                    f"compiled list produces {frame_count} frames; target limit is "
                    f"{self.target.max_frames}"
                ),
            )
        if issues:
            raise TargetCompilationError(tuple(issues))

        entries = tuple(self._render_entry(plan) for plan in plans)
        artifact_fingerprint = canonical_fingerprint(
            _artifact_payload(
                compiler_id=self.id,
                target=self.target,
                request=request,
                entries=entries,
            )
        )
        digest = artifact_fingerprint.removeprefix("sha256:")
        return FakeListArtifact(
            id=TargetArtifactId(f"fake-list-artifact-{digest}"),
            target_id=self.target.id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_fingerprint=artifact_fingerprint,
            source_entry_ids=tuple(entry.id for entry in request.entries),
            repetitions=request.repetitions,
            sample_rate_hz=self.target.sample_rate_hz,
            entries=entries,
        )

    def _validate_dispatch(self, request: TargetCompileRequest) -> None:
        issues: list[TargetCompilationIssue] = []
        if request.target_id != self.target.id:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="fake_list_target_mismatch",
                message="compile request selects another target",
            )
        if request.compiler_id != self.id:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="fake_list_compiler_mismatch",
                message="compile request selects another compiler",
            )
        if request.capability_fingerprint != self.capability_fingerprint:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="fake_list_capability_fingerprint_mismatch",
                message="compile request has a stale target capability fingerprint",
            )
        if issues:
            raise TargetCompilationError(tuple(issues))

    def _plan_entry(
        self,
        entry: TargetCompileEntry,
        *,
        list_index: int,
        issues: list[TargetCompilationIssue],
    ) -> _EntryPlan | None:
        program = entry.program
        duration_samples = _sample_index(program.duration_seconds, self.target)
        if duration_samples is None:
            _entry_issue(
                issues,
                entry.id,
                code="fake_list_program_duration_off_grid",
                message=(
                    f"program {program.id.value!r} duration is not on the exact "
                    "target sample grid"
                ),
            )
        elif duration_samples <= 0:
            _entry_issue(
                issues,
                entry.id,
                code="fake_list_program_duration_nonpositive",
                message=f"program {program.id.value!r} has no positive sample span",
            )
        elif duration_samples > self.target.max_samples_per_entry:
            _entry_issue(
                issues,
                entry.id,
                code="fake_list_samples_per_entry_limit_exceeded",
                message=(
                    f"program {program.id.value!r} requires {duration_samples} "
                    f"samples; target entry limit is "
                    f"{self.target.max_samples_per_entry}"
                ),
            )

        slots_by_id = {slot.id: slot for slot in program.acquisition_slots}
        plays: list[_PlaySpan] = []
        acquisitions: list[FakeAcquisitionWindow] = []
        output_intervals: dict[FakeAwgChannelId, list[tuple[int, int, str]]] = {}
        frame_phases: dict[FrameSignal, float] = {}
        acquisition_intervals: dict[
            FakeDigitizerChannelId, list[tuple[int, int, str]]
        ] = {}
        for event in program.events:
            start_sample = _sample_index(event.start_seconds, self.target)
            duration_sample_count = _sample_index(
                event.duration_seconds,
                self.target,
            )
            if start_sample is None:
                _entry_issue(
                    issues,
                    entry.id,
                    code="fake_list_event_start_off_grid",
                    message=(
                        f"event {event.id.value!r} start is not on the exact target "
                        "sample grid"
                    ),
                )
            if duration_sample_count is None:
                _entry_issue(
                    issues,
                    entry.id,
                    code="fake_list_event_duration_off_grid",
                    message=(
                        f"event {event.id.value!r} duration is not on the exact "
                        "target sample grid"
                    ),
                )
            instruction = event.instruction
            match instruction:
                case Play():
                    self._plan_play(
                        entry_id=entry.id,
                        event_id=event.id.value,
                        instruction=instruction,
                        start_sample=start_sample,
                        sample_count=duration_sample_count,
                        intervals=output_intervals,
                        plays=plays,
                        phase_offset=(
                            frame_phases.get(instruction.signal, 0.0)
                            if isinstance(
                                instruction.signal, DriveSignal | ReadoutSignal
                            )
                            else 0.0
                        ),
                        issues=issues,
                    )
                case Acquire():
                    channel_id = self.target.acquisition_channel(instruction.signal)
                    if channel_id is None:
                        _entry_issue(
                            issues,
                            entry.id,
                            code="fake_list_acquisition_signal_unbound",
                            message=(
                                "acquisition signal "
                                f"{_signal_label(instruction.signal)} "
                                "has no digitizer binding"
                            ),
                        )
                    slot = slots_by_id.get(instruction.slot_id)
                    if slot is None:
                        _entry_issue(
                            issues,
                            entry.id,
                            code="fake_list_acquisition_slot_missing",
                            message=(
                                f"event {event.id.value!r} references undeclared "
                                f"acquisition slot {instruction.slot_id.value!r}"
                            ),
                        )
                    if (
                        channel_id is not None
                        and start_sample is not None
                        and duration_sample_count is not None
                        and duration_sample_count > 0
                    ):
                        _claim_interval(
                            intervals=acquisition_intervals,
                            channel_id=channel_id,
                            start_sample=start_sample,
                            sample_count=duration_sample_count,
                            event_id=event.id.value,
                            entry_id=entry.id,
                            overlap_code="fake_list_physical_acquisition_overlap",
                            resource_label="digitizer channel",
                            issues=issues,
                        )
                        if slot is not None:
                            acquisitions.append(
                                FakeAcquisitionWindow(
                                    event_id=event.id,
                                    slot_id=instruction.slot_id,
                                    signal=instruction.signal,
                                    channel_id=channel_id,
                                    start_sample=start_sample,
                                    sample_count=duration_sample_count,
                                    kind=slot.kind,
                                )
                            )
                case Delay():
                    self._validate_signal_binding(
                        entry_id=entry.id,
                        signal=instruction.signal,
                        issues=issues,
                    )
                case ShiftPhase():
                    self._validate_signal_binding(
                        entry_id=entry.id,
                        signal=instruction.signal,
                        issues=issues,
                    )
                    frame_phases[instruction.signal] = _wrapped_phase(
                        frame_phases.get(instruction.signal, 0.0)
                        + _wrapped_phase(float(instruction.phase.value))
                    )
                case Barrier():
                    for signal in instruction.signals:
                        self._validate_signal_binding(
                            entry_id=entry.id,
                            signal=signal,
                            issues=issues,
                        )

        if duration_samples is None or duration_samples <= 0:
            return None
        return _EntryPlan(
            list_index=list_index,
            source=entry,
            sample_count=duration_samples,
            plays=tuple(plays),
            acquisitions=tuple(acquisitions),
        )

    def _plan_play(
        self,
        *,
        entry_id: TargetCompileEntryId,
        event_id: str,
        instruction: Play,
        start_sample: int | None,
        sample_count: int | None,
        intervals: dict[FakeAwgChannelId, list[tuple[int, int, str]]],
        plays: list[_PlaySpan],
        phase_offset: float,
        issues: list[TargetCompilationIssue],
    ) -> None:
        channel_id = self.target.output_channel(instruction.signal)
        if channel_id is None:
            _entry_issue(
                issues,
                entry_id,
                code="fake_list_output_signal_unbound",
                message=(
                    f"output signal {_signal_label(instruction.signal)} has no AWG "
                    "binding"
                ),
            )
        if (
            channel_id is not None
            and start_sample is not None
            and sample_count is not None
            and sample_count > 0
        ):
            _claim_interval(
                intervals=intervals,
                channel_id=channel_id,
                start_sample=start_sample,
                sample_count=sample_count,
                event_id=event_id,
                entry_id=entry_id,
                overlap_code="fake_list_physical_output_overlap",
                resource_label="AWG channel",
                issues=issues,
            )

        envelope = instruction.envelope
        if isinstance(envelope, Gaussian):
            _entry_capability_issue(
                issues,
                entry_id,
                code="fake_list_envelope_unsupported",
                message=(
                    f"event {event_id!r} uses unsupported Gaussian envelope; "
                    "fake list mode supports Constant and DRAG"
                ),
            )
            return
        if envelope.amplitude.unit not in {"arb", "ratio"}:
            _entry_capability_issue(
                issues,
                entry_id,
                code="fake_list_amplitude_unit_unsupported",
                message=(
                    f"event {event_id!r} uses unsupported amplitude unit "
                    f"{envelope.amplitude.unit!r}; fake list mode supports 'arb' "
                    "and 'ratio'"
                ),
            )
            return

        if sample_count is None or sample_count <= 0:
            return
        samples = _render_envelope_samples(
            envelope,
            sample_count=sample_count,
            sample_rate_hz=self.target.sample_rate_hz,
            phase_offset=phase_offset,
        )
        peak_magnitude = max(abs(sample) for sample in samples)
        if peak_magnitude > self.target.max_abs_amplitude:
            _entry_issue(
                issues,
                entry_id,
                code="fake_list_amplitude_limit_exceeded",
                message=(
                    f"event {event_id!r} has sample magnitude "
                    f"{peak_magnitude!r}; target limit is "
                    f"{self.target.max_abs_amplitude!r}"
                ),
            )
        if channel_id is None or start_sample is None:
            return
        plays.append(
            _PlaySpan(
                channel_id=channel_id,
                start_sample=start_sample,
                samples=samples,
            )
        )

    def _validate_signal_binding(
        self,
        *,
        entry_id: TargetCompileEntryId,
        signal: FakeOutputSignal | AcquireSignal,
        issues: list[TargetCompilationIssue],
    ) -> None:
        if isinstance(signal, AcquireSignal):
            if self.target.acquisition_channel(signal) is None:
                _entry_issue(
                    issues,
                    entry_id,
                    code="fake_list_acquisition_signal_unbound",
                    message=(
                        f"acquisition signal {_signal_label(signal)} has no "
                        "digitizer binding"
                    ),
                )
            return
        if self.target.output_channel(signal) is None:
            _entry_issue(
                issues,
                entry_id,
                code="fake_list_output_signal_unbound",
                message=(f"output signal {_signal_label(signal)} has no AWG binding"),
            )

    @staticmethod
    def _render_entry(plan: _EntryPlan) -> FakeListEntry:
        buffers = {
            channel_id: [0j] * plan.sample_count
            for channel_id in plan.waveform_channels
        }
        for play in plan.plays:
            end_sample = play.start_sample + play.sample_count
            buffers[play.channel_id][play.start_sample : end_sample] = play.samples
        return FakeListEntry(
            list_index=plan.list_index,
            entry_id=plan.source.id,
            program_id=plan.source.program.id,
            sample_count=plan.sample_count,
            waveforms=tuple(
                FakeChannelWaveform(
                    channel_id=channel_id,
                    samples=tuple(samples),
                )
                for channel_id, samples in sorted(buffers.items())
            ),
            acquisitions=plan.acquisitions,
        )


def _sample_index(seconds: Decimal, target: FakeListTarget) -> int | None:
    scaled = seconds * Decimal(target.sample_rate_hz)
    integral = scaled.to_integral_value()
    return int(integral) if scaled == integral else None


def _render_envelope_samples(
    envelope: Constant | DRAG,
    *,
    sample_count: int,
    sample_rate_hz: int,
    phase_offset: float = 0.0,
) -> tuple[complex, ...]:
    amplitude = float(envelope.amplitude.value)
    phase_rotation = cmath.rect(
        1.0,
        _wrapped_phase(
            _wrapped_phase(float(envelope.phase.value)) + _wrapped_phase(phase_offset)
        ),
    )
    if isinstance(envelope, Constant):
        return (phase_rotation * amplitude,) * sample_count

    duration_seconds = float(envelope.duration.value)
    sigma_seconds = float(envelope.sigma.value)
    beta_seconds = float(envelope.beta.value)
    center_seconds = duration_seconds / 2.0
    return tuple(
        phase_rotation
        * _drag_sample(
            time_seconds=(sample_index + 0.5) / sample_rate_hz,
            center_seconds=center_seconds,
            sigma_seconds=sigma_seconds,
            amplitude=amplitude,
            beta_seconds=beta_seconds,
        )
        for sample_index in range(sample_count)
    )


def _wrapped_phase(value: float) -> float:
    return math.remainder(value, math.tau)


def _drag_sample(
    *,
    time_seconds: float,
    center_seconds: float,
    sigma_seconds: float,
    amplitude: float,
    beta_seconds: float,
) -> complex:
    offset_seconds = time_seconds - center_seconds
    gaussian = amplitude * math.exp(
        -(offset_seconds * offset_seconds) / (2.0 * sigma_seconds * sigma_seconds)
    )
    derivative = -offset_seconds * gaussian / (sigma_seconds * sigma_seconds)
    return complex(gaussian, beta_seconds * derivative)


def _claim_interval[ChannelIdT: FakeAwgChannelId | FakeDigitizerChannelId](
    *,
    intervals: dict[ChannelIdT, list[tuple[int, int, str]]],
    channel_id: ChannelIdT,
    start_sample: int,
    sample_count: int,
    event_id: str,
    entry_id: TargetCompileEntryId,
    overlap_code: str,
    resource_label: str,
    issues: list[TargetCompilationIssue],
) -> None:
    end_sample = start_sample + sample_count
    selected = intervals.setdefault(channel_id, [])
    for other_start, other_end, other_event_id in selected:
        if start_sample < other_end and other_start < end_sample:
            _entry_issue(
                issues,
                entry_id,
                code=overlap_code,
                message=(
                    f"events {other_event_id!r} and {event_id!r} overlap on "
                    f"{resource_label} {channel_id.value!r}"
                ),
            )
    selected.append((start_sample, end_sample, event_id))


def _signal_label(signal: FakeOutputSignal | AcquireSignal) -> str:
    return "/".join(signal_key(signal))


def _entry_issue(
    issues: list[TargetCompilationIssue],
    entry_id: TargetCompileEntryId,
    *,
    code: str,
    message: str,
) -> None:
    _issue(
        issues,
        dimension=TargetCompilationIssueDimension.PROGRAM,
        code=code,
        message=message,
        entry_id=entry_id,
    )


def _entry_capability_issue(
    issues: list[TargetCompilationIssue],
    entry_id: TargetCompileEntryId,
    *,
    code: str,
    message: str,
) -> None:
    _issue(
        issues,
        dimension=TargetCompilationIssueDimension.CAPABILITY,
        code=code,
        message=message,
        entry_id=entry_id,
    )


def _issue(
    issues: list[TargetCompilationIssue],
    *,
    dimension: TargetCompilationIssueDimension,
    code: str,
    message: str,
    entry_id: TargetCompileEntryId | None = None,
) -> None:
    issues.append(
        TargetCompilationIssue(
            dimension=dimension,
            code=code,
            message=message,
            entry_id=entry_id,
        )
    )


def _artifact_payload(
    *,
    compiler_id: TargetCompilerId,
    target: FakeListTarget,
    request: TargetCompileRequest,
    entries: tuple[FakeListEntry, ...],
) -> dict[str, object]:
    return {
        "schema": "quantum_lab_demo.fake_list_artifact.v1",
        "target": {
            "id": target.id.value,
            "capability_fingerprint": target.capability_fingerprint,
            "sample_rate_hz": target.sample_rate_hz,
            "max_list_entries": target.max_list_entries,
            "max_samples_per_entry": target.max_samples_per_entry,
            "max_waveform_memory_samples": target.max_waveform_memory_samples,
            "max_capture_memory_samples": target.max_capture_memory_samples,
            "max_repetitions": target.max_repetitions,
            "max_frames": target.max_frames,
            "max_abs_amplitude": float(target.max_abs_amplitude).hex(),
            "supported_envelopes": list(target.supported_envelopes),
            "supported_acquisition_kinds": [kind.value for kind in AcquisitionKind],
            "output_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "channel_id": binding.channel_id.value,
                }
                for binding in target.output_bindings
            ],
            "acquisition_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "channel_id": binding.channel_id.value,
                }
                for binding in target.acquisition_bindings
            ],
        },
        "compiler_id": compiler_id.value,
        "repetitions": request.repetitions,
        "source_entry_ids": [entry.id.value for entry in request.entries],
        "entries": [
            {
                "list_index": entry.list_index,
                "entry_id": entry.entry_id.value,
                "program_id": entry.program_id.value,
                "sample_count": entry.sample_count,
                "waveforms": [
                    {
                        "channel_id": waveform.channel_id.value,
                        "samples": [
                            [float(sample.real).hex(), float(sample.imag).hex()]
                            for sample in waveform.samples
                        ],
                    }
                    for waveform in entry.waveforms
                ],
                "acquisitions": [
                    {
                        "event_id": pulse_event_identity_payload(window.event_id),
                        "slot_id": acquisition_slot_identity_payload(window.slot_id),
                        "signal": signal_key(window.signal),
                        "channel_id": window.channel_id.value,
                        "start_sample": window.start_sample,
                        "sample_count": window.sample_count,
                        "kind": window.kind.value,
                    }
                    for window in entry.acquisitions
                ],
            }
            for entry in entries
        ],
    }


__all__ = ["FakeListTargetCompiler"]
