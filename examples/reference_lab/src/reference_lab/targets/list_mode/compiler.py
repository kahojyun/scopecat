"""Pure compiler for the demo list-mode AWG and segmented digitizer target.

This laboratory-owned compiler translates canonical scheduled pulse programs
into physical list entries and acquisition windows. It validates sample-grid
alignment, signal bindings, overlap, list, and shot limits before producing an
artifact. Retained physical buffers are amplitude-checked here; compact
parameterized buffers are checked when they materialize at the AWG boundary.
No instrument effect occurs here.

Physical list and segment positions are artifact layout, never logical result
identity. Entry-qualified event and acquisition addresses survive compilation
so runtime evidence can be correlated to the exact prepared quantum work.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.kernel.content_identity import content_fingerprint
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
    SampledOutputBinding,
    SampledWaveformPlan,
    SampleGrid,
    TimingQuantizationPolicy,
    WaveformPlanningError,
    factor_phase_parameterized_waveforms,
    plan_sampled_waveforms,
)

from reference_lab.targets.list_mode.iq_semantics import (
    INTEGRATED_IQ_SEMANTICS_ID,
)
from reference_lab.targets.list_mode.model import (
    AcquisitionIntent,
    AwgChannelId,
    AwgChannelWaveform,
    AwgPhaseTemplate,
    AwgPhaseTemplateUse,
    DemodulatorSlotId,
    DeviceAcquisitionLowering,
    DigitizerAcquisitionWindow,
    IqMixerCalibration,
    ListModeArtifact,
    ListModeBudgetDimension,
    ListModeCompilationBudget,
    ListModeCompilationCacheInfo,
    ListModeCompilationKey,
    ListModeDeviceSnapshot,
    ListModeEntry,
    ListModeEventPlacement,
    ListModeHostStateRequirements,
    ListModePhysicalEndpoint,
    ListModePhysicalFootprint,
    ListModePreparation,
    ListModeProgramPlacement,
    ListModeTarget,
    OutputSignal,
    TargetAcquisitionLowering,
    acquisition_slot_identity_payload,
    awg_phase_template_identity_payload,
    awg_waveform_identity_payload,
    canonical_fingerprint,
    compilation_budget_payload,
    compilation_key_payload,
    device_snapshot_payload,
    host_state_requirements_payload,
    physical_footprint_payload,
    preparation_payload,
    program_placement_payload,
    pulse_event_identity_payload,
    signal_key,
)

_ARTIFACT_CACHE_SIZE = 32


@dataclass(frozen=True, slots=True)
class _EntryPlan:
    list_index: int
    source: TargetCompileEntry
    waveform_plan: SampledWaveformPlan
    lane_channels: tuple[AwgChannelId, ...]
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
    _artifact_cache: OrderedDict[str, ListModeArtifact] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
        compare=False,
    )
    _cache_hits: int = field(default=0, init=False, repr=False, compare=False)
    _cache_misses: int = field(default=0, init=False, repr=False, compare=False)
    _cache_evictions: int = field(default=0, init=False, repr=False, compare=False)

    @property
    def cache_info(self) -> ListModeCompilationCacheInfo:
        """Return deterministic counters for the process-local artifact LRU."""

        return ListModeCompilationCacheInfo(
            hits=self._cache_hits,
            misses=self._cache_misses,
            evictions=self._cache_evictions,
            size=len(self._artifact_cache),
            capacity=_ARTIFACT_CACHE_SIZE,
        )

    def compile(self, request: TargetCompileRequest) -> ListModeArtifact:
        """Compile one checked finite request without performing hardware effects."""

        device_snapshot = self.target.device_snapshot
        compilation_key = _compilation_key(self.id, device_snapshot, request)
        cached = self._artifact_cache.get(compilation_key.value)
        if cached is not None:
            object.__setattr__(self, "_cache_hits", self._cache_hits + 1)
            self._artifact_cache.move_to_end(compilation_key.value)
            return cached
        object.__setattr__(self, "_cache_misses", self._cache_misses + 1)

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

        compact = _compile_phase_template_sweep(plans)
        if compact is None:
            phase_templates: tuple[AwgPhaseTemplate, ...] = ()
            entries = tuple(self._render_entry(plan, issues=issues) for plan in plans)
        else:
            phase_templates, entries = compact
        if issues:
            raise TargetCompilationError(tuple(issues))
        waveform_bytes = _materialized_waveform_bytes(entries, phase_templates)
        if waveform_bytes > self.target.max_program_waveform_bytes:
            _issue(
                issues,
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="list_mode_program_waveform_memory_exceeded",
                message=(
                    f"request requires {waveform_bytes} waveform bytes; target "
                    "program-memory limit is "
                    f"{self.target.max_program_waveform_bytes}"
                ),
            )
        if issues:
            raise TargetCompilationError(tuple(issues))
        preparation = _project_preparation(self.target, entries, phase_templates)
        host_state_requirements = _project_host_state_requirements(
            self.target,
            entries,
            phase_templates,
        )
        placement = _project_program_placement(request, device_snapshot)
        physical_footprint = _project_physical_footprint(
            entries,
            phase_templates,
            timing_instrument_id=preparation.timing.trigger_instrument_id,
            waveform_bytes=waveform_bytes,
        )
        compilation_budget = _project_compilation_budget(
            self.target,
            request,
            entries,
            phase_templates,
            waveform_bytes=waveform_bytes,
        )
        artifact_fingerprint = canonical_fingerprint(
            _artifact_payload(
                compiler_id=self.id,
                target=self.target,
                request=request,
                compilation_key=compilation_key,
                compilation_budget=compilation_budget,
                device_snapshot=device_snapshot,
                placement=placement,
                physical_footprint=physical_footprint,
                preparation=preparation,
                host_state_requirements=host_state_requirements,
                entries=entries,
                phase_templates=phase_templates,
            )
        )
        digest = artifact_fingerprint.removeprefix("sha256:")
        artifact = ListModeArtifact(
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
            max_abs_amplitude=self.target.max_abs_amplitude,
            max_result_chunk_bytes=self.target.max_result_chunk_bytes,
            timing_quantization=self.target.timing_quantization,
            compilation_key=compilation_key,
            compilation_budget=compilation_budget,
            device_snapshot=device_snapshot,
            placement=placement,
            physical_footprint=physical_footprint,
            preparation=preparation,
            host_state_requirements=host_state_requirements,
            entries=entries,
            phase_templates=phase_templates,
        )
        self._artifact_cache[compilation_key.value] = artifact
        if len(self._artifact_cache) > _ARTIFACT_CACHE_SIZE:
            self._artifact_cache.popitem(last=False)
            object.__setattr__(self, "_cache_evictions", self._cache_evictions + 1)
        return artifact

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
        return _EntryPlan(
            list_index=list_index,
            source=entry,
            waveform_plan=waveform_plan,
            lane_channels=lane_channels,
            active_lanes=active_lanes,
            acquisitions=tuple(acquisitions),
        )

    def _render_entry(
        self,
        plan: _EntryPlan,
        *,
        issues: list[TargetCompilationIssue],
    ) -> ListModeEntry:
        rendered = Float64ReferenceRenderer().render(plan.waveform_plan)
        for lane in plan.active_lanes:
            peak_magnitude = rendered.lane_peaks[lane]
            if peak_magnitude > self.target.max_abs_amplitude:
                _entry_issue(
                    issues,
                    plan.source.id,
                    code="list_mode_amplitude_limit_exceeded",
                    message=(
                        f"final waveform on channel "
                        f"{plan.lane_channels[lane].value!r} has magnitude "
                        f"{peak_magnitude!r}; target limit is "
                        f"{self.target.max_abs_amplitude!r}"
                    ),
                )
        return ListModeEntry(
            list_index=plan.list_index,
            entry_id=plan.source.id,
            program_id=plan.source.program.id,
            sample_count=plan.sample_count,
            waveforms=tuple(
                AwgChannelWaveform(
                    channel_id=plan.lane_channels[lane],
                    samples=rendered.buffers[lane],
                )
                for lane in plan.active_lanes
            ),
            acquisitions=plan.acquisitions,
            event_timings=plan.waveform_plan.event_timings,
        )


def _compile_phase_template_sweep(
    plans: tuple[_EntryPlan, ...],
) -> tuple[tuple[AwgPhaseTemplate, ...], tuple[ListModeEntry, ...]] | None:
    parameterized = factor_phase_parameterized_waveforms(
        tuple(plan.waveform_plan for plan in plans)
    )
    if parameterized is None:
        return None
    reference = plans[0]
    renderer = Float64ReferenceRenderer()
    templates: list[AwgPhaseTemplate] = []
    for index, event in enumerate(parameterized.template.render_events):
        isolated = renderer.render(
            replace(parameterized.template, render_events=(event,))
        )
        selected = slice(event.timing.start_sample, event.timing.end_sample)
        physical_i = isolated.buffers[event.binding.i_lane][selected]
        physical_q = isolated.buffers[event.binding.q_lane][selected]
        mixer = event.binding.mixer
        determinant = mixer.ii * mixer.qq - mixer.iq * mixer.qi
        if math.isclose(determinant, 0.0, abs_tol=1e-15):
            return None
        templates.append(
            AwgPhaseTemplate(
                id=f"event-{index}",
                i_channel_id=reference.lane_channels[event.binding.i_lane],
                q_channel_id=reference.lane_channels[event.binding.q_lane],
                start_sample=event.timing.start_sample,
                sample_count=event.timing.sample_count,
                logical_i=(mixer.qq * physical_i - mixer.iq * physical_q) / determinant,
                logical_q=(-mixer.qi * physical_i + mixer.ii * physical_q)
                / determinant,
                mixer=IqMixerCalibration(
                    ii=mixer.ii,
                    iq=mixer.iq,
                    qi=mixer.qi,
                    qq=mixer.qq,
                    i_offset_v=0.0,
                    q_offset_v=0.0,
                ),
            )
        )
    entries = tuple(
        ListModeEntry(
            list_index=plan.list_index,
            entry_id=plan.source.id,
            program_id=plan.source.program.id,
            sample_count=plan.sample_count,
            waveforms=(),
            acquisitions=plan.acquisitions,
            event_timings=plan.waveform_plan.event_timings,
            phase_template_uses=tuple(
                AwgPhaseTemplateUse(
                    template_id=template.id,
                    phase_radians=phase,
                )
                for template, phase in zip(
                    templates,
                    phase_row,
                    strict=True,
                )
            ),
        )
        for plan, phase_row in zip(
            plans,
            parameterized.phase_rows,
            strict=True,
        )
    )
    return tuple(templates), entries


def _materialized_waveform_bytes(
    entries: tuple[ListModeEntry, ...],
    phase_templates: tuple[AwgPhaseTemplate, ...],
) -> int:
    if not phase_templates:
        return sum(
            waveform.samples.nbytes for entry in entries for waveform in entry.waveforms
        )
    template_by_id = {template.id: template for template in phase_templates}
    return sum(
        entry.sample_count
        * 8
        * len(
            {
                channel_id
                for use in entry.phase_template_uses
                for channel_id in template_by_id[use.template_id].channel_ids
            }
        )
        for entry in entries
    )


def _compilation_key(
    compiler_id: TargetCompilerId,
    snapshot: ListModeDeviceSnapshot,
    request: TargetCompileRequest,
) -> ListModeCompilationKey:
    scheduled_program_fingerprints = tuple(
        canonical_fingerprint(content_fingerprint(entry.program))
        for entry in request.entries
    )
    semantic_program_fingerprint = canonical_fingerprint(
        {
            "schema": "reference_lab.list_mode_semantic_program.v1",
            "scheduled_program_fingerprints": scheduled_program_fingerprints,
        }
    )
    placement_fingerprint = canonical_fingerprint(
        {
            "schema": "reference_lab.list_mode_placement_key.v1",
            "semantic_program_fingerprint": semantic_program_fingerprint,
            "device_snapshot_fingerprint": snapshot.snapshot_fingerprint,
        }
    )
    artifact_layout_fingerprint = canonical_fingerprint(
        {
            "schema": "reference_lab.list_mode_artifact_layout_key.v1",
            "compiler_id": compiler_id.value,
            "placement_fingerprint": placement_fingerprint,
            "source_entry_ids": [entry.id.value for entry in request.entries],
            "repetitions": request.repetitions,
            "waveform_semantics_id": SAMPLED_WAVEFORM_SEMANTICS_ID,
        }
    )
    return ListModeCompilationKey(
        compiler_id=compiler_id,
        device_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        scheduled_program_fingerprints=scheduled_program_fingerprints,
        semantic_program_fingerprint=semantic_program_fingerprint,
        placement_fingerprint=placement_fingerprint,
        artifact_layout_fingerprint=artifact_layout_fingerprint,
    )


def _project_compilation_budget(
    target: ListModeTarget,
    request: TargetCompileRequest,
    entries: tuple[ListModeEntry, ...],
    phase_templates: tuple[AwgPhaseTemplate, ...],
    *,
    waveform_bytes: int,
) -> ListModeCompilationBudget:
    template_by_id = {template.id: template for template in phase_templates}

    def entry_waveform_bytes(entry: ListModeEntry) -> int:
        if not entry.phase_template_uses:
            return sum(waveform.samples.nbytes for waveform in entry.waveforms)
        return (
            entry.sample_count
            * 8
            * len(
                {
                    channel_id
                    for use in entry.phase_template_uses
                    for channel_id in template_by_id[use.template_id].channel_ids
                }
            )
        )

    largest_entry_bytes = max(entry_waveform_bytes(entry) for entry in entries)
    point_capacities = {
        "list_entries": target.max_list_entries,
        "waveform_memory_bytes": max(
            1,
            target.max_program_waveform_bytes // max(largest_entry_bytes, 1),
        ),
    }
    next_batch_max_points = min(point_capacities.values())
    dimensions = (
        ListModeBudgetDimension(
            id="list_entries",
            scope="batch",
            usage=len(entries),
            limit=target.max_list_entries,
            projected_point_capacity=point_capacities["list_entries"],
        ),
        ListModeBudgetDimension(
            id="waveform_memory_bytes",
            scope="batch",
            usage=waveform_bytes,
            limit=target.max_program_waveform_bytes,
            projected_point_capacity=point_capacities["waveform_memory_bytes"],
        ),
        ListModeBudgetDimension(
            id="samples_per_entry",
            scope="entry",
            usage=max(entry.sample_count for entry in entries),
            limit=target.max_samples_per_entry,
        ),
        ListModeBudgetDimension(
            id="repetitions",
            scope="invocation",
            usage=request.repetitions,
            limit=target.max_repetitions,
        ),
    )
    return ListModeCompilationBudget(
        dimensions=dimensions,
        next_batch_max_points=next_batch_max_points,
        limiting_dimensions=tuple(
            dimension_id
            for dimension_id, capacity in point_capacities.items()
            if capacity == next_batch_max_points
        ),
    )


def _project_program_placement(
    request: TargetCompileRequest,
    snapshot: ListModeDeviceSnapshot,
) -> ListModeProgramPlacement:
    return ListModeProgramPlacement(
        device_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        events=tuple(
            ListModeEventPlacement(
                entry_id=entry.id,
                event_id=event.id,
                signal=snapshot.signal_placement(
                    signal_key(
                        cast(
                            "OutputSignal | AcquireSignal",
                            event.instruction.signal,
                        )
                    )
                ),
            )
            for entry in request.entries
            for event in entry.program.events
        ),
    )


def _project_physical_footprint(
    entries: tuple[ListModeEntry, ...],
    phase_templates: tuple[AwgPhaseTemplate, ...],
    *,
    timing_instrument_id: str,
    waveform_bytes: int,
) -> ListModePhysicalFootprint:
    output_channels = {
        waveform.channel_id for entry in entries for waveform in entry.waveforms
    } | {channel for template in phase_templates for channel in template.channel_ids}
    acquisition_inputs = {
        window.input_id for entry in entries for window in entry.acquisitions
    }
    waveform_outputs = tuple(
        ListModePhysicalEndpoint(
            kind="waveform_output",
            instrument_id=channel.instrument_id,
            channel_id=channel.value,
            component_path=channel.component_path,
        )
        for channel in sorted(output_channels)
    )
    selected_acquisition_inputs = tuple(
        ListModePhysicalEndpoint(
            kind="acquisition_input",
            instrument_id=input_id.instrument_id,
            channel_id=input_id.value,
            component_path=input_id.component_path,
        )
        for input_id in sorted(acquisition_inputs)
    )
    instrument_ids = tuple(
        sorted(
            {
                *(endpoint.instrument_id for endpoint in waveform_outputs),
                *(endpoint.instrument_id for endpoint in selected_acquisition_inputs),
                timing_instrument_id,
            }
        )
    )
    return ListModePhysicalFootprint(
        instrument_ids=instrument_ids,
        waveform_outputs=waveform_outputs,
        acquisition_inputs=selected_acquisition_inputs,
        timing_instrument_id=timing_instrument_id,
        waveform_bytes=waveform_bytes,
        event_count=sum(len(entry.event_timings) for entry in entries),
        acquisition_count=sum(len(entry.acquisitions) for entry in entries),
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
    phase_templates: tuple[AwgPhaseTemplate, ...],
) -> ListModePreparation:
    """Select only shared device state needed by the rendered entries."""

    channel_ids = {
        waveform.channel_id for entry in entries for waveform in entry.waveforms
    } | {
        channel_id
        for template in phase_templates
        for channel_id in template.channel_ids
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
    phase_templates: tuple[AwgPhaseTemplate, ...],
) -> ListModeHostStateRequirements:
    """Expand active channels through the configured physical coupling groups."""

    active_channel_ids = {
        waveform.channel_id for entry in entries for waveform in entry.waveforms
    } | {
        channel_id
        for template in phase_templates
        for channel_id in template.channel_ids
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
    compilation_key: ListModeCompilationKey,
    compilation_budget: ListModeCompilationBudget,
    device_snapshot: ListModeDeviceSnapshot,
    placement: ListModeProgramPlacement,
    physical_footprint: ListModePhysicalFootprint,
    preparation: ListModePreparation,
    host_state_requirements: ListModeHostStateRequirements,
    entries: tuple[ListModeEntry, ...],
    phase_templates: tuple[AwgPhaseTemplate, ...],
) -> dict[str, object]:
    return {
        "schema": "reference_lab.list_mode_artifact.v10",
        "target": {
            "id": target.id.value,
            "capability_fingerprint": target.capability_fingerprint,
            "configuration_fingerprint": target.configuration_fingerprint,
        },
        "compiler_id": compiler_id.value,
        "repetitions": request.repetitions,
        "sample_rate_hz": target.sample_rate_hz,
        "waveform_semantics_id": SAMPLED_WAVEFORM_SEMANTICS_ID,
        "max_result_chunk_bytes": target.max_result_chunk_bytes,
        "timing_quantization": target.timing_quantization,
        "source_entry_ids": [entry.id.value for entry in request.entries],
        "compilation_key": compilation_key_payload(compilation_key),
        "compilation_budget": compilation_budget_payload(compilation_budget),
        "device_snapshot": device_snapshot_payload(device_snapshot),
        "placement": program_placement_payload(placement),
        "physical_footprint": physical_footprint_payload(physical_footprint),
        "preparation": preparation_payload(preparation),
        "host_state_requirements": host_state_requirements_payload(
            host_state_requirements
        ),
        "phase_templates": [
            awg_phase_template_identity_payload(template)
            for template in phase_templates
        ],
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
                "phase_template_uses": [
                    {
                        "template_id": use.template_id,
                        "phase_radians": float(use.phase_radians).hex(),
                    }
                    for use in entry.phase_template_uses
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
