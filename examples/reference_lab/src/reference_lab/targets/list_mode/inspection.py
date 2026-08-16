"""Bounded, host-visible inspection of compiled list-mode artifacts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scopecat.inspection import (
    CompiledArtifactInspection,
    CompiledInspectionBounds,
    CompiledInspectionFact,
    CompiledPointInspection,
    CompiledProgramInspection,
    CompiledProgramInspectionLayer,
    CompiledProgramInspectionLink,
    CompiledProgramInspectionNode,
    CompiledWaveformInspection,
    query_compiled_program_nodes,
)

from reference_lab.targets.list_mode.model import (
    AwgChannelWaveform,
    ListModeArtifact,
    ListModeEntry,
    acquisition_slot_identity_payload,
    awg_waveform_identity_payload,
    canonical_fingerprint,
    pulse_event_identity_payload,
    signal_key,
)


@dataclass(frozen=True, slots=True)
class ArtifactInspectionBounds:
    """Hard response budgets for one transient artifact inspection."""

    max_entries: int = 1
    max_channels_per_entry: int = 12
    max_samples_per_waveform: int = 256
    max_placement_nodes: int = 128

    def __post_init__(self) -> None:
        if (
            self.max_entries <= 0
            or self.max_channels_per_entry <= 0
            or self.max_placement_nodes <= 0
        ):
            raise ValueError(
                "artifact inspection entry and channel limits must be positive"
            )
        if self.max_samples_per_waveform < 2:
            raise ValueError("waveform previews require at least two samples")


def inspect_list_mode_artifact(
    artifact: ListModeArtifact,
    *,
    bounds: ArtifactInspectionBounds | None = None,
    program: CompiledProgramInspection | None = None,
) -> CompiledArtifactInspection:
    """Return deterministic statistics and min/max waveform previews."""

    selected_bounds = bounds or ArtifactInspectionBounds()
    selected_entries = artifact.entries[: selected_bounds.max_entries]
    return CompiledArtifactInspection(
        kind="reference_lab.list_mode.v1",
        facts=(
            CompiledInspectionFact("semantics_id", artifact.waveform_semantics_id),
            CompiledInspectionFact(
                "sample_rate_hz", artifact.sample_rate_hz, unit="Hz"
            ),
            CompiledInspectionFact("timing_quantization", artifact.timing_quantization),
            CompiledInspectionFact("repetitions", artifact.repetitions),
            CompiledInspectionFact(
                "device_snapshot_fingerprint",
                artifact.device_snapshot.snapshot_fingerprint,
            ),
            CompiledInspectionFact(
                "compilation_key",
                artifact.compilation_key.value,
            ),
            CompiledInspectionFact(
                "semantic_program_fingerprint",
                artifact.compilation_key.semantic_program_fingerprint,
            ),
            CompiledInspectionFact(
                "placement_fingerprint",
                artifact.compilation_key.placement_fingerprint,
            ),
            CompiledInspectionFact(
                "next_batch_max_points",
                artifact.compilation_budget.next_batch_max_points,
            ),
            CompiledInspectionFact(
                "limiting_budget_dimensions",
                list(artifact.compilation_budget.limiting_dimensions),
            ),
            CompiledInspectionFact(
                "logical_qubit_count",
                len(artifact.placement.logical_qubit_ids),
            ),
            CompiledInspectionFact(
                "physical_instrument_count",
                len(artifact.physical_footprint.instrument_ids),
            ),
            CompiledInspectionFact(
                "waveform_bytes",
                artifact.physical_footprint.waveform_bytes,
                unit="byte",
            ),
            CompiledInspectionFact(
                "result_bytes",
                artifact.physical_footprint.result_bytes,
                unit="byte",
            ),
            CompiledInspectionFact(
                "max_abs_boundary_error_seconds",
                str(
                    max(
                        (_max_boundary_error(entry) for entry in artifact.entries),
                        default=Decimal(0),
                    )
                ),
                unit="s",
            ),
        ),
        point_count=len(artifact.entries),
        points_truncated=len(selected_entries) < len(artifact.entries),
        bounds=CompiledInspectionBounds(
            max_points=selected_bounds.max_entries,
            max_waveforms_per_point=selected_bounds.max_channels_per_entry,
            max_samples_per_waveform=selected_bounds.max_samples_per_waveform,
        ),
        points=tuple(
            _inspect_entry(artifact, entry, bounds=selected_bounds)
            for entry in selected_entries
        ),
        program=(
            _with_physical_placement_layer(
                program,
                artifact,
                max_nodes=selected_bounds.max_placement_nodes,
            )
            if program is not None
            else None
        ),
    )


def _with_physical_placement_layer(
    program: CompiledProgramInspection,
    artifact: ListModeArtifact,
    *,
    max_nodes: int,
) -> CompiledProgramInspection:
    entry_id = artifact.entries[0].entry_id
    placements = tuple(
        event for event in artifact.placement.events if event.entry_id == entry_id
    )
    logical_qubit_ids = tuple(sorted({event.signal.signal[2] for event in placements}))
    physical_resource_ids = tuple(
        sorted(
            {
                endpoint.id
                for candidate in artifact.placement.candidates
                for endpoint in candidate.route.endpoints
            }
        )
    )
    root_id = "physical:placement"
    all_nodes = (
        CompiledProgramInspectionNode(
            id=root_id,
            kind="device",
            label=f"device {artifact.target_id.value}",
            child_count=(
                len(placements)
                + len(artifact.placement.candidates)
                + len(artifact.placement.constraints)
            ),
            entity_ids=logical_qubit_ids,
            resource_ids=physical_resource_ids,
            facts=(
                CompiledInspectionFact(
                    "snapshot_fingerprint",
                    artifact.device_snapshot.snapshot_fingerprint,
                ),
                CompiledInspectionFact(
                    "configured_signal_count",
                    len(artifact.device_snapshot.signal_placements),
                ),
                CompiledInspectionFact(
                    "placement_constraint_count",
                    len(artifact.placement.constraints),
                ),
                CompiledInspectionFact(
                    "placement_candidate_count",
                    artifact.placement.candidate_count,
                ),
                CompiledInspectionFact(
                    "materialized_candidate_count",
                    len(artifact.placement.candidates),
                ),
                CompiledInspectionFact(
                    "placement_candidates_truncated",
                    artifact.placement.candidates_truncated,
                ),
                CompiledInspectionFact(
                    "materialized_rejected_candidate_count",
                    sum(
                        candidate.status == "rejected"
                        for candidate in artifact.placement.candidates
                    ),
                ),
            ),
        ),
        *(
            CompiledProgramInspectionNode(
                id=f"physical:event:{event.event_id.value}",
                kind="placement",
                label=(
                    f"{event.signal.signal[0]}({event.signal.signal[2]}) → "
                    + ", ".join(endpoint.id for endpoint in event.signal.endpoints)
                ),
                parent_id=root_id,
                entity_ids=(event.signal.signal[2],),
                resource_ids=tuple(endpoint.id for endpoint in event.signal.endpoints),
                facts=tuple(
                    fact
                    for fact in (
                        CompiledInspectionFact("lo_group_id", event.signal.lo_group_id)
                        if event.signal.lo_group_id is not None
                        else None,
                        CompiledInspectionFact(
                            "demodulator_slot_id",
                            event.signal.demodulator_slot_id,
                        )
                        if event.signal.demodulator_slot_id is not None
                        else None,
                        CompiledInspectionFact(
                            "constraint_ids",
                            list(event.constraint_ids),
                        ),
                        CompiledInspectionFact(
                            "candidate_ids",
                            list(event.candidate_ids),
                        ),
                        CompiledInspectionFact(
                            "candidate_count",
                            event.candidate_count,
                        ),
                    )
                    if fact is not None
                ),
            )
            for event in placements
        ),
        *(
            CompiledProgramInspectionNode(
                id=f"physical:{candidate.id}",
                kind=f"placement_candidate_{candidate.status}",
                label=(
                    f"{candidate.status} {candidate.signal[0]}({candidate.signal[2]}) "
                    "→ "
                    + ", ".join(endpoint.id for endpoint in candidate.route.endpoints)
                ),
                parent_id=root_id,
                entity_ids=tuple(
                    sorted({candidate.signal[2], candidate.route.signal[2]})
                ),
                resource_ids=tuple(
                    endpoint.id for endpoint in candidate.route.endpoints
                ),
                facts=(
                    CompiledInspectionFact("status", candidate.status),
                    CompiledInspectionFact(
                        "requested_signal",
                        list(candidate.signal),
                    ),
                    CompiledInspectionFact(
                        "configured_signal",
                        list(candidate.route.signal),
                    ),
                    CompiledInspectionFact(
                        "rejection_codes",
                        [rejection.code for rejection in candidate.rejections],
                    ),
                    CompiledInspectionFact(
                        "rejection_reasons",
                        [rejection.message for rejection in candidate.rejections],
                    ),
                ),
                warnings=tuple(rejection.message for rejection in candidate.rejections),
            )
            for candidate in artifact.placement.candidates
        ),
        *(
            CompiledProgramInspectionNode(
                id=f"physical:constraint:{constraint.id}",
                kind="placement_constraint",
                label=constraint.label,
                parent_id=root_id,
                entity_ids=constraint.entity_ids,
                resource_ids=constraint.resource_ids,
                facts=(
                    CompiledInspectionFact("constraint_kind", constraint.kind),
                    CompiledInspectionFact(
                        "signal_count",
                        len(constraint.signals),
                    ),
                    CompiledInspectionFact(
                        "signals",
                        [list(signal) for signal in constraint.signals],
                    ),
                ),
            )
            for constraint in artifact.placement.constraints
        ),
    )
    selected_nodes, page = query_compiled_program_nodes(
        "physical",
        all_nodes,
        query=program.query,
        default_limit=max_nodes,
        snapshot_id=program.snapshot_id,
    )
    layer = CompiledProgramInspectionLayer(
        id="physical",
        label="Physical placement",
        kind="physical",
        node_count=len(all_nodes),
        nodes_truncated=len(selected_nodes) < len(all_nodes),
        root_ids=(root_id,),
        nodes=selected_nodes,
        page=page,
        facts=(
            CompiledInspectionFact(
                "instrument_count",
                len(artifact.physical_footprint.instrument_ids),
            ),
            CompiledInspectionFact(
                "waveform_output_count",
                len(artifact.physical_footprint.waveform_outputs),
            ),
            CompiledInspectionFact(
                "acquisition_input_count",
                len(artifact.physical_footprint.acquisition_inputs),
            ),
            *(
                CompiledInspectionFact(
                    f"budget.{dimension.id}",
                    {
                        "scope": dimension.scope,
                        "usage": dimension.usage,
                        "limit": dimension.limit,
                        "projected_point_capacity": (
                            dimension.projected_point_capacity
                        ),
                        "projected_shot_capacity": (dimension.projected_shot_capacity),
                    },
                )
                for dimension in artifact.compilation_budget.dimensions
            ),
        ),
    )
    physical_node_ids = {node.id for node in selected_nodes}
    placement_links = tuple(
        CompiledProgramInspectionLink(
            source_layer_id="scheduled",
            source_node_id=f"scheduled:event:{event.event_id.value}",
            target_layer_id="physical",
            target_node_id=f"physical:event:{event.event_id.value}",
            relation="placed_on",
        )
        for event in placements
        if f"physical:event:{event.event_id.value}" in physical_node_ids
    )
    candidate_links = tuple(
        CompiledProgramInspectionLink(
            source_layer_id="physical",
            source_node_id=f"physical:event:{event.event_id.value}",
            target_layer_id="physical",
            target_node_id=f"physical:{candidate.id}",
            relation=(
                "selected_route" if candidate.status == "selected" else "rejected_route"
            ),
        )
        for event in placements
        for candidate in artifact.placement.candidates
        if candidate.id in event.candidate_ids
        and f"physical:event:{event.event_id.value}" in physical_node_ids
        and f"physical:{candidate.id}" in physical_node_ids
    )
    return replace(
        program,
        layers=(*program.layers, layer),
        links=(*program.links, *placement_links, *candidate_links),
    )


def point_realization_fingerprint(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
) -> str:
    """Identify one realization independently of target batch partitioning."""

    return _point_realization_fingerprint(
        artifact,
        entry,
        artifact.entry_waveforms(entry),
    )


def _point_realization_fingerprint(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    waveforms: tuple[AwgChannelWaveform, ...],
) -> str:
    return canonical_fingerprint(
        {
            "schema": "reference_lab.list_mode_point_realization.v1",
            "target_id": artifact.target_id.value,
            "compiler_id": artifact.compiler_id.value,
            "capability_fingerprint": artifact.capability_fingerprint,
            "configuration_fingerprint": artifact.configuration_fingerprint,
            "repetitions": artifact.repetitions,
            "sample_rate_hz": artifact.sample_rate_hz,
            "waveform_semantics_id": artifact.waveform_semantics_id,
            "timing_quantization": artifact.timing_quantization,
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
                    "realized_duration_seconds": str(timing.realized_duration_seconds),
                    "start_error_seconds": str(timing.start_error_seconds),
                    "duration_error_seconds": str(timing.duration_error_seconds),
                }
                for timing in entry.event_timings
            ],
            "waveforms": [
                awg_waveform_identity_payload(waveform) for waveform in waveforms
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
                        "output_representation": window.intent.output_representation,
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
    )


def _inspect_entry(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    bounds: ArtifactInspectionBounds,
) -> CompiledPointInspection:
    waveforms = artifact.entry_waveforms(entry)
    selected_waveforms = waveforms[: bounds.max_channels_per_entry]
    return CompiledPointInspection(
        realization_fingerprint=_point_realization_fingerprint(
            artifact,
            entry,
            waveforms,
        ),
        target_entry_id=entry.entry_id.value,
        facts=(
            CompiledInspectionFact("list_index", entry.list_index),
            CompiledInspectionFact("program_id", entry.program_id.value),
            CompiledInspectionFact("sample_count", entry.sample_count),
            CompiledInspectionFact("event_count", len(entry.event_timings)),
            CompiledInspectionFact("acquisition_count", len(entry.acquisitions)),
            CompiledInspectionFact(
                "max_abs_boundary_error_seconds",
                str(_max_boundary_error(entry)),
                unit="s",
            ),
        ),
        waveform_count=len(waveforms),
        waveforms_truncated=len(selected_waveforms) < len(waveforms),
        waveforms=tuple(
            _preview_waveform(
                waveform,
                max_samples=bounds.max_samples_per_waveform,
            )
            for waveform in selected_waveforms
        ),
    )


def _max_boundary_error(entry: ListModeEntry) -> Decimal:
    return max(
        (
            max(
                abs(timing.start_error_seconds),
                abs(timing.start_error_seconds + timing.duration_error_seconds),
            )
            for timing in entry.event_timings
        ),
        default=Decimal(0),
    )


def _preview_waveform(
    waveform: AwgChannelWaveform,
    *,
    max_samples: int,
) -> CompiledWaveformInspection:
    samples = waveform.samples
    sample_indices = _minmax_indices(samples, max_samples=max_samples)
    selected_samples = tuple(
        float(cast("np.float64", samples[index])) for index in sample_indices
    )
    return CompiledWaveformInspection(
        channel_id=waveform.channel_id.value,
        instrument_id=waveform.channel_id.instrument_id,
        peak_abs=(
            float(cast("np.float64", np.max(np.abs(samples)))) if samples.size else 0.0
        ),
        rms=(
            float(cast("np.float64", np.sqrt(np.mean(np.square(samples)))))
            if samples.size
            else 0.0
        ),
        source_sample_count=int(samples.size),
        samples_sha256=waveform.samples_sha256,
        sample_indices=sample_indices,
        samples=selected_samples,
        downsampling="none" if samples.size <= max_samples else "minmax",
    )


def _minmax_indices(
    samples: NDArray[np.float64],
    *,
    max_samples: int,
) -> tuple[int, ...]:
    if samples.size <= max_samples:
        return tuple(range(samples.size))
    bucket_count = max_samples // 2
    selected: list[int] = []
    for bucket in range(bucket_count):
        start = bucket * samples.size // bucket_count
        end = (bucket + 1) * samples.size // bucket_count
        local = samples[start:end]
        minimum = start + int(np.argmin(local))
        maximum = start + int(np.argmax(local))
        selected.extend(sorted({minimum, maximum}))
    return tuple(selected)


__all__ = [
    "ArtifactInspectionBounds",
    "inspect_list_mode_artifact",
    "point_realization_fingerprint",
]
