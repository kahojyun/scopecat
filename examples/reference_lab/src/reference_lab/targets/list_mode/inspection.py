"""Bounded, host-visible inspection of compiled list-mode artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.json_types import JsonValue
from scopecat_quantum.waveforms import TimingQuantizationMode

from reference_lab.targets.list_mode.model import (
    AwgChannelWaveform,
    ListModeArtifact,
    ListModeEntry,
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


@dataclass(frozen=True, slots=True)
class WaveformPreview:
    """One physical channel's statistics and bounded plot samples."""

    channel_id: str
    instrument_id: str
    peak_abs: float
    rms: float
    source_sample_count: int
    samples_sha256: str
    sample_indices: tuple[int, ...]
    samples: tuple[float, ...]
    downsampling: Literal["none", "minmax"]

    def payload(self) -> dict[str, JsonValue]:
        return cast(
            "dict[str, JsonValue]",
            {
                "channel_id": self.channel_id,
                "instrument_id": self.instrument_id,
                "peak_abs": self.peak_abs,
                "rms": self.rms,
                "source_sample_count": self.source_sample_count,
                "samples_sha256": self.samples_sha256,
                "sample_indices": list(self.sample_indices),
                "samples": list(self.samples),
                "downsampling": self.downsampling,
            },
        )


@dataclass(frozen=True, slots=True)
class EntryInspection:
    """Bounded physical realization summary for one list entry."""

    list_index: int
    entry_id: str
    program_id: str
    sample_count: int
    event_count: int
    acquisition_count: int
    max_abs_boundary_error_seconds: Decimal
    waveform_count: int
    waveforms_truncated: bool
    waveforms: tuple[WaveformPreview, ...]

    def payload(self) -> dict[str, JsonValue]:
        return cast(
            "dict[str, JsonValue]",
            {
                "list_index": self.list_index,
                "entry_id": self.entry_id,
                "program_id": self.program_id,
                "sample_count": self.sample_count,
                "event_count": self.event_count,
                "acquisition_count": self.acquisition_count,
                "max_abs_boundary_error_seconds": str(
                    self.max_abs_boundary_error_seconds
                ),
                "waveform_count": self.waveform_count,
                "waveforms_truncated": self.waveforms_truncated,
                "waveforms": [waveform.payload() for waveform in self.waveforms],
            },
        )


@dataclass(frozen=True, slots=True)
class ListModeArtifactInspection:
    """Compact target facts intended for a selected-point preview only."""

    semantics_id: str
    sample_rate_hz: int
    timing_quantization: TimingQuantizationMode
    repetitions: int
    entry_count: int
    max_abs_boundary_error_seconds: Decimal
    entries_truncated: bool
    bounds: ArtifactInspectionBounds
    entries: tuple[EntryInspection, ...]

    def payload(self) -> dict[str, JsonValue]:
        return cast(
            "dict[str, JsonValue]",
            {
                "schema": "reference_lab.list_mode_artifact_inspection.v1",
                "semantics_id": self.semantics_id,
                "sample_rate_hz": self.sample_rate_hz,
                "timing_quantization": self.timing_quantization,
                "repetitions": self.repetitions,
                "entry_count": self.entry_count,
                "max_abs_boundary_error_seconds": str(
                    self.max_abs_boundary_error_seconds
                ),
                "preview_bounds": {
                    "max_entries": self.bounds.max_entries,
                    "max_channels_per_entry": self.bounds.max_channels_per_entry,
                    "max_samples_per_waveform": self.bounds.max_samples_per_waveform,
                },
                "entries_truncated": self.entries_truncated,
                "warnings": [],
                "entries": [entry.payload() for entry in self.entries],
            },
        )


def inspect_list_mode_artifact(
    artifact: ListModeArtifact,
    *,
    bounds: ArtifactInspectionBounds | None = None,
) -> ListModeArtifactInspection:
    """Return deterministic statistics and min/max waveform previews."""

    selected_bounds = bounds or ArtifactInspectionBounds()
    selected_entries = artifact.entries[: selected_bounds.max_entries]
    entries = tuple(
        _inspect_entry(entry, bounds=selected_bounds) for entry in selected_entries
    )
    return ListModeArtifactInspection(
        semantics_id=artifact.waveform_semantics_id,
        sample_rate_hz=artifact.sample_rate_hz,
        timing_quantization=artifact.timing_quantization,
        repetitions=artifact.repetitions,
        entry_count=len(artifact.entries),
        max_abs_boundary_error_seconds=max(
            (_max_boundary_error(entry) for entry in artifact.entries),
            default=Decimal(0),
        ),
        entries_truncated=len(selected_entries) < len(artifact.entries),
        bounds=selected_bounds,
        entries=entries,
    )


def _inspect_entry(
    entry: ListModeEntry,
    *,
    bounds: ArtifactInspectionBounds,
) -> EntryInspection:
    selected_waveforms = entry.waveforms[: bounds.max_channels_per_entry]
    return EntryInspection(
        list_index=entry.list_index,
        entry_id=entry.entry_id.value,
        program_id=entry.program_id.value,
        sample_count=entry.sample_count,
        event_count=len(entry.event_timings),
        acquisition_count=len(entry.acquisitions),
        max_abs_boundary_error_seconds=_max_boundary_error(entry),
        waveform_count=len(entry.waveforms),
        waveforms_truncated=len(selected_waveforms) < len(entry.waveforms),
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
) -> WaveformPreview:
    samples = waveform.samples
    sample_indices = _minmax_indices(samples, max_samples=max_samples)
    selected_samples = tuple(
        float(cast("np.float64", samples[index])) for index in sample_indices
    )
    return WaveformPreview(
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
    "EntryInspection",
    "ListModeArtifactInspection",
    "WaveformPreview",
    "inspect_list_mode_artifact",
]
