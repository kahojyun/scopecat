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

from dataclasses import dataclass

from scopecat_quantum._ids import (
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    Delay,
    DriveSignal,
    Play,
    ReadoutSignal,
    ShiftPhase,
)
from scopecat_quantum.targets import (
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntry,
    TargetCompileRequest,
)
from scopecat_quantum.waveforms import (
    SAMPLED_WAVEFORM_SEMANTICS_ID,
    Float64ReferenceRenderer,
    IqMatrix,
    RenderedWaveforms,
    SampledOutputBinding,
    SampledWaveformPlan,
    SampleGrid,
    TimingQuantizationPolicy,
    WaveformPlanningError,
    plan_sampled_waveforms,
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
    ListModeArtifact,
    ListModeEntry,
    ListModeHostStateRequirements,
    ListModePreparation,
    ListModeTarget,
    OutputSignal,
    TargetAcquisitionLowering,
    acquisition_slot_identity_payload,
    awg_waveform_identity_payload,
    canonical_fingerprint,
    host_state_requirements_payload,
    preparation_payload,
    pulse_event_identity_payload,
    signal_key,
)


@dataclass(frozen=True, slots=True)
class _EntryPlan:
    list_index: int
    source: TargetCompileEntry
    waveform_plan: SampledWaveformPlan
    lane_channels: tuple[AwgChannelId, ...]
    rendered: RenderedWaveforms
    active_lanes: tuple[int, ...]
    acquisitions: tuple[DigitizerAcquisitionWindow, ...]

    @property
    def sample_count(self) -> int:
        return self.waveform_plan.sample_count


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
        host_state_requirements = _project_host_state_requirements(
            self.target,
            entries,
        )
        artifact_fingerprint = canonical_fingerprint(
            _artifact_payload(
                compiler_id=self.id,
                target=self.target,
                request=request,
                preparation=preparation,
                host_state_requirements=host_state_requirements,
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
            waveform_semantics_id=SAMPLED_WAVEFORM_SEMANTICS_ID,
            timing_quantization=self.target.timing_quantization,
            preparation=preparation,
            host_state_requirements=host_state_requirements,
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
        lane_channels, sampled_bindings = _sampled_output_projection(self.target)
        try:
            waveform_plan = plan_sampled_waveforms(
                program,
                bindings=sampled_bindings,
                grid=SampleGrid(
                    sample_rate_hz=self.target.sample_rate_hz,
                    timing=TimingQuantizationPolicy(
                        mode=self.target.timing_quantization
                    ),
                ),
            )
        except WaveformPlanningError as error:
            for planning_issue in error.issues:
                _entry_issue(
                    issues,
                    entry.id,
                    code=(f"list_mode_{planning_issue.code.removeprefix('sampled_')}"),
                    message=planning_issue.message,
                )
            return None

        if waveform_plan.sample_count > self.target.max_samples_per_entry:
            _entry_issue(
                issues,
                entry.id,
                code="list_mode_samples_per_entry_limit_exceeded",
                message=(
                    f"program {program.id.value!r} requires "
                    f"{waveform_plan.sample_count} "
                    f"samples; target entry limit is "
                    f"{self.target.max_samples_per_entry}"
                ),
            )

        acquisitions: list[DigitizerAcquisitionWindow] = []
        output_intervals: dict[AwgChannelId, list[tuple[int, int, str]]] = {}
        acquisition_intervals: dict[DemodulatorSlotId, list[tuple[int, int, str]]] = {}
        for event in program.events:
            timing = waveform_plan.timing_for(event.id)
            instruction = event.instruction
            match instruction:
                case Play():
                    signal = instruction.signal
                    if not isinstance(signal, DriveSignal | ReadoutSignal):
                        _unsupported_issue(issues, entry.id, event.id.value)
                        continue
                    if instruction.envelope.amplitude.unit not in {"arb", "ratio"}:
                        _entry_capability_issue(
                            issues,
                            entry.id,
                            code="list_mode_amplitude_unit_unsupported",
                            message=(
                                f"event {event.id.value!r} uses unsupported "
                                "amplitude unit "
                                f"{instruction.envelope.amplitude.unit!r}; "
                                "list-mode mode supports 'arb' and 'ratio'"
                            ),
                        )
                    binding = self.target.output_binding(signal)
                    if isinstance(signal, DriveSignal) and binding is not None:
                        for channel_id in binding.channel_ids:
                            _claim_interval(
                                intervals=output_intervals,
                                channel_id=channel_id,
                                start_sample=timing.start_sample,
                                sample_count=timing.sample_count,
                                event_id=event.id.value,
                                entry_id=entry.id,
                                overlap_code=("list_mode_physical_output_overlap"),
                                resource_label="AWG channel",
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
                    if binding is not None and timing.sample_count > 0:
                        _claim_interval(
                            intervals=acquisition_intervals,
                            channel_id=binding.demodulator_slot_id,
                            start_sample=timing.start_sample,
                            sample_count=timing.sample_count,
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
                                start_sample=timing.start_sample,
                                sample_count=timing.sample_count,
                            )
                        )
                case Delay() | ShiftPhase():
                    pass

        rendered = Float64ReferenceRenderer().render(waveform_plan)
        active_lanes = tuple(
            sorted(
                {
                    lane
                    for render_event in waveform_plan.render_events
                    for lane in (
                        render_event.binding.i_lane,
                        render_event.binding.q_lane,
                    )
                }
            )
        )
        for lane in active_lanes:
            peak_magnitude = rendered.lane_peaks[lane]
            if peak_magnitude > self.target.max_abs_amplitude:
                _entry_issue(
                    issues,
                    entry.id,
                    code="list_mode_amplitude_limit_exceeded",
                    message=(
                        f"final waveform on channel "
                        f"{lane_channels[lane].value!r} has magnitude "
                        f"{peak_magnitude!r}; target limit is "
                        f"{self.target.max_abs_amplitude!r}"
                    ),
                )
        return _EntryPlan(
            list_index=list_index,
            source=entry,
            waveform_plan=waveform_plan,
            lane_channels=lane_channels,
            rendered=rendered,
            active_lanes=active_lanes,
            acquisitions=tuple(acquisitions),
        )

    @staticmethod
    def _render_entry(plan: _EntryPlan) -> ListModeEntry:
        return ListModeEntry(
            list_index=plan.list_index,
            entry_id=plan.source.id,
            program_id=plan.source.program.id,
            sample_count=plan.sample_count,
            waveforms=tuple(
                AwgChannelWaveform(
                    channel_id=plan.lane_channels[lane],
                    samples=plan.rendered.buffers[lane],
                )
                for lane in plan.active_lanes
            ),
            acquisitions=plan.acquisitions,
            event_timings=plan.waveform_plan.event_timings,
        )


def _sampled_output_projection(
    target: ListModeTarget,
) -> tuple[tuple[AwgChannelId, ...], tuple[SampledOutputBinding, ...]]:
    lane_channels = tuple(
        sorted(
            {
                channel_id
                for binding in target.output_bindings
                for channel_id in binding.channel_ids
            }
        )
    )
    lane_by_channel = {
        channel_id: lane for lane, channel_id in enumerate(lane_channels)
    }
    return lane_channels, tuple(
        SampledOutputBinding(
            signal=binding.signal,
            i_lane=lane_by_channel[binding.i_channel_id],
            q_lane=lane_by_channel[binding.q_channel_id],
            intermediate_frequency_hz=binding.intermediate_frequency_hz,
            mixer=IqMatrix(
                ii=binding.mixer.ii,
                iq=binding.mixer.iq,
                qi=binding.mixer.qi,
                qq=binding.mixer.qq,
            ),
        )
        for binding in target.output_bindings
    )


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
        timing=target.preparation.timing,
    )


def _project_host_state_requirements(
    target: ListModeTarget,
    entries: tuple[ListModeEntry, ...],
) -> ListModeHostStateRequirements:
    """Expand active channels through the configured physical coupling groups."""

    active_channel_ids = {
        waveform.channel_id for entry in entries for waveform in entry.waveforms
    }
    selected_groups = tuple(
        group
        for group in target.host_state_policy.coupling_groups
        if active_channel_ids & set(group.activation_channels)
    )
    return ListModeHostStateRequirements(
        policy_id=target.host_state_policy.id,
        coupling_group_ids=tuple(group.id for group in selected_groups),
        output_offsets=tuple(
            requirement
            for group in selected_groups
            for requirement in group.output_offsets
        ),
    )


def _artifact_payload(
    *,
    compiler_id: TargetCompilerId,
    target: ListModeTarget,
    request: TargetCompileRequest,
    preparation: ListModePreparation,
    host_state_requirements: ListModeHostStateRequirements,
    entries: tuple[ListModeEntry, ...],
) -> dict[str, object]:
    return {
        "schema": "reference_lab.list_mode_artifact.v7",
        "target": {
            "id": target.id.value,
            "capability_fingerprint": target.capability_fingerprint,
            "configuration_fingerprint": target.configuration_fingerprint,
        },
        "compiler_id": compiler_id.value,
        "repetitions": request.repetitions,
        "sample_rate_hz": target.sample_rate_hz,
        "waveform_semantics_id": SAMPLED_WAVEFORM_SEMANTICS_ID,
        "timing_quantization": target.timing_quantization,
        "source_entry_ids": [entry.id.value for entry in request.entries],
        "preparation": preparation_payload(preparation),
        "host_state_requirements": host_state_requirements_payload(
            host_state_requirements
        ),
        "entries": [
            {
                "list_index": entry.list_index,
                "entry_id": entry.entry_id.value,
                "program_id": entry.program_id.value,
                "sample_count": entry.sample_count,
                "event_timings": [
                    {
                        "event_id": pulse_event_identity_payload(timing.event_id),
                        "requested_start_seconds": str(timing.requested_start_seconds),
                        "requested_duration_seconds": str(
                            timing.requested_duration_seconds
                        ),
                        "start_sample": timing.start_sample,
                        "sample_count": timing.sample_count,
                        "realized_start_seconds": str(timing.realized_start_seconds),
                        "realized_duration_seconds": str(
                            timing.realized_duration_seconds
                        ),
                        "start_error_seconds": str(timing.start_error_seconds),
                        "duration_error_seconds": str(timing.duration_error_seconds),
                    }
                    for timing in entry.event_timings
                ],
                "waveforms": [
                    awg_waveform_identity_payload(waveform)
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
