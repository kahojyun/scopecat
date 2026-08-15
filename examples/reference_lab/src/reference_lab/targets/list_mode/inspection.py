"""Bounded, host-visible inspection of compiled list-mode artifacts."""

from __future__ import annotations

from dataclasses import dataclass
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
    CompiledWaveformInspection,
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

    def __post_init__(self) -> None:
        if self.max_entries <= 0 or self.max_channels_per_entry <= 0:
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
        program=program,
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
