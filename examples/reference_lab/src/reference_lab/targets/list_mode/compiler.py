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

from reference_lab.targets.list_mode.iq_semantics import (
    INTEGRATED_IQ_SEMANTICS_ID,
)
from reference_lab.targets.list_mode.model import (
    AcquisitionIntent,
    AwgChannelId,
    AwgChannelWaveform,
    DemodulatorSlotId,
    DeviceAcquisitionLowering,
    DigitizerAcquisitionWindow,
    IqOutputBinding,
    ListModeArtifact,
    ListModeEntry,
    ListModePreparation,
    ListModeTarget,
    OutputSignal,
    TargetAcquisitionLowering,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    preparation_payload,
    pulse_event_identity_payload,
    signal_key,
)


@dataclass(frozen=True, slots=True)
class _PlaySpan:
    binding: IqOutputBinding
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
    acquisitions: tuple[DigitizerAcquisitionWindow, ...]

    @property
    def waveform_channels(self) -> tuple[AwgChannelId, ...]:
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
class ListModeTargetCompiler:
    """Compile canonical pulse schedules into finite physical list payloads."""

    id: TargetCompilerId
    target: ListModeTarget

    def compile(self, request: TargetCompileRequest) -> ListModeArtifact:
        """Compile one checked finite request without performing hardware effects."""

        issues: list[TargetCompilationIssue] = []
        if len(request.entries) > self.target.max_list_entries:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="list_mode_entry_limit_exceeded",
                message=(
                    f"request has {len(request.entries)} list entries; target limit is "
                    f"{self.target.max_list_entries}"
                ),
            )
        if request.repetitions > self.target.max_repetitions:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="list_mode_repetition_limit_exceeded",
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
        preparation = _project_preparation(self.target, entries)
        artifact_fingerprint = canonical_fingerprint(
            _artifact_payload(
                compiler_id=self.id,
                target=self.target,
                request=request,
                preparation=preparation,
                entries=entries,
            )
        )
        digest = artifact_fingerprint.removeprefix("sha256:")
        return ListModeArtifact(
            id=TargetArtifactId(f"list-mode-artifact-{digest}"),
            target_id=self.target.id,
            compiler_id=self.id,
            capability_fingerprint=self.target.capability_fingerprint,
            configuration_fingerprint=self.target.configuration_fingerprint,
            artifact_fingerprint=artifact_fingerprint,
            source_entry_ids=tuple(entry.id for entry in request.entries),
            repetitions=request.repetitions,
            sample_rate_hz=self.target.sample_rate_hz,
            preparation=preparation,
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
                code="list_mode_program_duration_off_grid",
                message=(
                    f"program {program.id.value!r} duration is not on the exact "
                    "target sample grid"
                ),
            )
        elif duration_samples <= 0:
            _entry_issue(
                issues,
                entry.id,
                code="list_mode_program_duration_nonpositive",
                message=f"program {program.id.value!r} has no positive sample span",
            )
        elif duration_samples > self.target.max_samples_per_entry:
            _entry_issue(
                issues,
                entry.id,
                code="list_mode_samples_per_entry_limit_exceeded",
                message=(
                    f"program {program.id.value!r} requires {duration_samples} "
                    f"samples; target entry limit is "
                    f"{self.target.max_samples_per_entry}"
                ),
            )

        plays: list[_PlaySpan] = []
        acquisitions: list[DigitizerAcquisitionWindow] = []
        output_intervals: dict[AwgChannelId, list[tuple[int, int, str]]] = {}
        acquisition_intervals: dict[DemodulatorSlotId, list[tuple[int, int, str]]] = {}
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
                    code="list_mode_event_start_off_grid",
                    message=(
                        f"event {event.id.value!r} start is not on the exact target "
                        "sample grid"
                    ),
                )
            if duration_sample_count is None:
                _entry_issue(
                    issues,
                    entry.id,
                    code="list_mode_event_duration_off_grid",
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
                    binding = self.target.acquisition_binding(instruction.signal)
                    if binding is None:
                        _entry_issue(
                            issues,
                            entry.id,
                            code="list_mode_acquisition_signal_unbound",
                            message=(
                                "acquisition signal "
                                f"{_signal_label(instruction.signal)} "
                                "has no digitizer binding"
                            ),
                        )
                    if (
                        binding is not None
                        and start_sample is not None
                        and duration_sample_count is not None
                        and duration_sample_count > 0
                    ):
                        _claim_interval(
                            intervals=acquisition_intervals,
                            channel_id=binding.demodulator_slot_id,
                            start_sample=start_sample,
                            sample_count=duration_sample_count,
                            event_id=event.id.value,
                            entry_id=entry.id,
                            overlap_code="list_mode_physical_acquisition_overlap",
                            resource_label="demodulator slot",
                            issues=issues,
                        )
                        acquisitions.append(
                            DigitizerAcquisitionWindow(
                                event_id=event.id,
                                slot_id=instruction.slot_id,
                                signal=instruction.signal,
                                input_id=binding.input_id,
                                demodulator_slot_id=binding.demodulator_slot_id,
                                intent=AcquisitionIntent(
                                    semantics_id=INTEGRATED_IQ_SEMANTICS_ID,
                                    output_representation="integrated_iq",
                                    demodulation_frequency_hz=(
                                        binding.demodulation_frequency_hz
                                    ),
                                    integration_weight="rectangular",
                                    normalization="single_sideband_amplitude",
                                ),
                                lowering=(
                                    TargetAcquisitionLowering()
                                    if self.target.digitizer_result_representation
                                    == "raw_trace"
                                    else DeviceAcquisitionLowering()
                                ),
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
        intervals: dict[AwgChannelId, list[tuple[int, int, str]]],
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
                code="list_mode_output_signal_unbound",
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
                    overlap_code="list_mode_physical_output_overlap",
                    resource_label="AWG channel",
                    issues=issues,
                )
        if envelope.amplitude.unit not in {"arb", "ratio"}:
            _entry_capability_issue(
                issues,
                entry_id,
                code="list_mode_amplitude_unit_unsupported",
                message=(
                    f"event {event_id!r} uses unsupported amplitude unit "
                    f"{envelope.amplitude.unit!r}; list-mode mode supports 'arb' "
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
            start_sample=0 if start_sample is None else start_sample,
            intermediate_frequency_hz=(
                0.0 if binding is None else binding.intermediate_frequency_hz
            ),
        )
        peak_magnitude = max(
            max(abs(i_sample), abs(q_sample))
            for i_sample, q_sample in (
                _physical_iq(binding, sample)
                if binding is not None
                else (sample.real, sample.imag)
                for sample in samples
            )
        )
        if peak_magnitude > self.target.max_abs_amplitude:
            _entry_issue(
                issues,
                entry_id,
                code="list_mode_amplitude_limit_exceeded",
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
    def _render_entry(plan: _EntryPlan) -> ListModeEntry:
        buffers = {
            channel_id: [0.0] * plan.sample_count
            for channel_id in plan.waveform_channels
        }
        for play in plan.plays:
            end_sample = play.start_sample + play.sample_count
            for channel_id, incoming_samples in (
                (
                    play.binding.i_channel_id,
                    (_physical_iq(play.binding, sample)[0] for sample in play.samples),
                ),
                (
                    play.binding.q_channel_id,
                    (_physical_iq(play.binding, sample)[1] for sample in play.samples),
                ),
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
        return ListModeEntry(
            list_index=plan.list_index,
            entry_id=plan.source.id,
            program_id=plan.source.program.id,
            sample_count=plan.sample_count,
            waveforms=tuple(
                AwgChannelWaveform(
                    channel_id=channel_id,
                    samples=tuple(samples),
                )
                for channel_id, samples in sorted(buffers.items())
            ),
            acquisitions=plan.acquisitions,
        )


def _physical_iq(binding: IqOutputBinding, sample: complex) -> tuple[float, float]:
    mixer = binding.mixer
    return (
        mixer.ii * sample.real + mixer.iq * sample.imag,
        mixer.qi * sample.real + mixer.qq * sample.imag,
    )


def _sample_index(seconds: Decimal, target: ListModeTarget) -> int | None:
    scaled = seconds * Decimal(target.sample_rate_hz)
    integral = scaled.to_integral_value()
    return int(integral) if scaled == integral else None


def _render_envelope_samples(
    envelope: Constant | DRAG,
    *,
    sample_count: int,
    sample_rate_hz: int,
    start_sample: int,
    intermediate_frequency_hz: float,
) -> tuple[complex, ...]:
    amplitude = float(envelope.amplitude.value)
    phase_rotation = cmath.rect(1.0, float(envelope.phase.value))
    carrier_samples = tuple(
        cmath.rect(
            1.0,
            math.tau
            * intermediate_frequency_hz
            * (start_sample + sample_index + 0.5)
            / sample_rate_hz,
        )
        for sample_index in range(sample_count)
    )
    if isinstance(envelope, Constant):
        return tuple(
            phase_rotation * amplitude * carrier for carrier in carrier_samples
        )

    duration_seconds = float(envelope.duration.value)
    sigma_seconds = float(envelope.sigma.value)
    beta_seconds = float(envelope.beta.value)
    center_seconds = duration_seconds / 2.0
    return tuple(
        phase_rotation
        * carrier_samples[sample_index]
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


def _claim_interval[ChannelIdT: AwgChannelId | DemodulatorSlotId](
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


def _signal_label(signal: OutputSignal | AcquireSignal) -> str:
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
        code="list_mode_operation_unsupported",
        message=f"event {event_id!r} is unsupported by list mode",
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


def _project_preparation(
    target: ListModeTarget,
    entries: tuple[ListModeEntry, ...],
) -> ListModePreparation:
    """Select only shared device state needed by the rendered entries."""

    channel_ids = {
        waveform.channel_id for entry in entries for waveform in entry.waveforms
    }
    awg_instrument_ids = {channel_id.instrument_id for channel_id in channel_ids}
    lo_group_ids = {
        binding.lo_group_id
        for binding in target.output_bindings
        if channel_ids.intersection(binding.channel_ids)
    }
    return ListModePreparation(
        clocks=tuple(
            clock
            for clock in target.preparation.clocks
            if clock.instrument_id in awg_instrument_ids
        ),
        outputs=tuple(
            output
            for output in target.preparation.outputs
            if output.channel_id in channel_ids
        ),
        local_oscillators=tuple(
            oscillator
            for oscillator in target.preparation.local_oscillators
            if oscillator.group_id in lo_group_ids
        ),
        timing=target.preparation.timing,
    )


def _artifact_payload(
    *,
    compiler_id: TargetCompilerId,
    target: ListModeTarget,
    request: TargetCompileRequest,
    preparation: ListModePreparation,
    entries: tuple[ListModeEntry, ...],
) -> dict[str, object]:
    return {
        "schema": "reference_lab.list_mode_artifact.v4",
        "target": {
            "id": target.id.value,
            "capability_fingerprint": target.capability_fingerprint,
            "configuration_fingerprint": target.configuration_fingerprint,
        },
        "compiler_id": compiler_id.value,
        "repetitions": request.repetitions,
        "source_entry_ids": [entry.id.value for entry in request.entries],
        "preparation": preparation_payload(preparation),
        "entries": [
            {
                "list_index": entry.list_index,
                "entry_id": entry.entry_id.value,
                "program_id": entry.program_id.value,
                "sample_count": entry.sample_count,
                "waveforms": [
                    {
                        "channel_id": waveform.channel_id.value,
                        "instrument_id": waveform.channel_id.instrument_id,
                        "component_path": list(waveform.channel_id.component_path),
                        "samples": [float(sample).hex() for sample in waveform.samples],
                    }
                    for waveform in entry.waveforms
                ],
                "acquisitions": [
                    {
                        "event_id": pulse_event_identity_payload(window.event_id),
                        "slot_id": acquisition_slot_identity_payload(window.slot_id),
                        "signal": signal_key(window.signal),
                        "input_id": window.input_id.value,
                        "instrument_id": window.input_id.instrument_id,
                        "component_path": list(window.input_id.component_path),
                        "demodulator_slot_id": window.demodulator_slot_id.value,
                        "intent": {
                            "semantics_id": window.intent.semantics_id,
                            "output_representation": (
                                window.intent.output_representation
                            ),
                            "demodulation_frequency_hz": float(
                                window.intent.demodulation_frequency_hz
                            ).hex(),
                            "integration_weight": window.intent.integration_weight,
                            "normalization": window.intent.normalization,
                        },
                        "lowering": {
                            "execution": window.lowering.execution,
                            "device_result_representation": (
                                window.lowering.device_result_representation
                            ),
                        },
                        "start_sample": window.start_sample,
                        "sample_count": window.sample_count,
                    }
                    for window in entry.acquisitions
                ],
            }
            for entry in entries
        ],
    }


__all__ = ["ListModeTargetCompiler"]
