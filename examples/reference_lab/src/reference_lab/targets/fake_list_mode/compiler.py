"""Pure compiler for the demo list-mode AWG and segmented digitizer target.

This laboratory-owned compiler translates canonical scheduled pulse programs
into physical list entries and acquisition windows. It validates sample-grid
alignment, signal bindings, overlap, amplitude, list, and shot limits before
producing an artifact; no instrument effect occurs here.

Physical list and segment positions are artifact layout, never logical result
identity. Entry-qualified event and acquisition addresses survive compilation
so runtime evidence can be correlated to the exact prepared quantum work.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from decimal import Decimal

from scopecat_quantum._ids import (
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.pulses import (
    DRAG,
    Acquire,
    AcquireSignal,
    Constant,
    Delay,
    DriveSignal,
    Play,
    ReadoutSignal,
)
from scopecat_quantum.targets import (
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntry,
    TargetCompileRequest,
)

from reference_lab.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeAwgChannelId,
    FakeChannelWaveform,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListEntry,
    FakeListTarget,
    FakeOutputBinding,
    FakeOutputSignal,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    pulse_event_identity_payload,
    signal_key,
)


@dataclass(frozen=True, slots=True)
class _PlaySpan:
    binding: FakeOutputBinding
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
        return tuple(
            sorted(
                {
                    channel_id
                    for play in self.plays
                    for channel_id in play.binding.channel_ids
                }
            )
        )


@dataclass(frozen=True, slots=True)
class FakeListTargetCompiler:
    """Compile canonical pulse schedules into finite fake-hardware list payloads."""

    id: TargetCompilerId
    target: FakeListTarget

    def compile(self, request: TargetCompileRequest) -> FakeListArtifact:
        """Compile one checked finite request without performing hardware effects."""

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
            capability_fingerprint=self.target.capability_fingerprint,
            artifact_fingerprint=artifact_fingerprint,
            source_entry_ids=tuple(entry.id for entry in request.entries),
            repetitions=request.repetitions,
            sample_rate_hz=self.target.sample_rate_hz,
            entries=entries,
        )

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

        plays: list[_PlaySpan] = []
        acquisitions: list[FakeAcquisitionWindow] = []
        output_intervals: dict[FakeAwgChannelId, list[tuple[int, int, str]]] = {}
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
                        acquisitions.append(
                            FakeAcquisitionWindow(
                                event_id=event.id,
                                slot_id=instruction.slot_id,
                                signal=instruction.signal,
                                channel_id=channel_id,
                                start_sample=start_sample,
                                sample_count=duration_sample_count,
                            )
                        )
                case Delay():
                    pass
                case _:
                    _unsupported_issue(issues, entry.id, event.id.value)
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
        issues: list[TargetCompilationIssue],
    ) -> None:
        signal = instruction.signal
        envelope = instruction.envelope
        if not isinstance(signal, DriveSignal | ReadoutSignal) or not isinstance(
            envelope, Constant | DRAG
        ):
            _unsupported_issue(issues, entry_id, event_id)
            return
        binding = self.target.output_binding(signal)
        if binding is None:
            _entry_issue(
                issues,
                entry_id,
                code="fake_list_output_signal_unbound",
                message=(f"output signal {_signal_label(signal)} has no AWG binding"),
            )
        if (
            isinstance(signal, DriveSignal)
            and binding is not None
            and start_sample is not None
            and sample_count is not None
            and sample_count > 0
        ):
            for channel_id in binding.channel_ids:
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
        if binding is None or start_sample is None:
            return
        plays.append(
            _PlaySpan(
                binding=binding,
                start_sample=start_sample,
                samples=samples,
            )
        )

    @staticmethod
    def _render_entry(plan: _EntryPlan) -> FakeListEntry:
        buffers = {
            channel_id: [0.0] * plan.sample_count
            for channel_id in plan.waveform_channels
        }
        for play in plan.plays:
            end_sample = play.start_sample + play.sample_count
            for channel_id, incoming_samples in (
                (play.binding.i_channel_id, (sample.real for sample in play.samples)),
                (play.binding.q_channel_id, (sample.imag for sample in play.samples)),
            ):
                channel = buffers[channel_id]
                channel[play.start_sample : end_sample] = (
                    existing + incoming
                    for existing, incoming in zip(
                        channel[play.start_sample : end_sample],
                        incoming_samples,
                        strict=True,
                    )
                )
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
) -> tuple[complex, ...]:
    amplitude = float(envelope.amplitude.value)
    phase_rotation = cmath.rect(1.0, float(envelope.phase.value))
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


def _unsupported_issue(
    issues: list[TargetCompilationIssue],
    entry_id: TargetCompileEntryId,
    event_id: str,
) -> None:
    _entry_capability_issue(
        issues,
        entry_id,
        code="fake_list_operation_unsupported",
        message=f"event {event_id!r} is unsupported by fake list mode",
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
        "schema": "reference_lab.fake_list_artifact.v2",
        "target": {
            "id": target.id.value,
            "capability_fingerprint": target.capability_fingerprint,
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
                        "samples": [float(sample).hex() for sample in waveform.samples],
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
                    }
                    for window in entry.acquisitions
                ],
            }
            for entry in entries
        ],
    }


__all__ = ["FakeListTargetCompiler"]
