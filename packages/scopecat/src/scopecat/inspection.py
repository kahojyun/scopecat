"""Typed, target-neutral views of compiled physical realizations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.kernel.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class CompiledInspectionFact:
    """One named target fact suitable for display and transport."""

    id: str
    value: JsonValue
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledWaveformInspection:
    """Bounded samples and stable identity for one physical waveform."""

    channel_id: str
    instrument_id: str
    peak_abs: float
    rms: float
    source_sample_count: int
    samples_sha256: str
    sample_indices: tuple[int, ...]
    samples: tuple[float, ...]
    downsampling: Literal["none", "minmax"]


@dataclass(frozen=True, slots=True)
class CompiledPointInspection:
    """One batch-independent physical realization of a point candidate."""

    realization_fingerprint: str
    target_entry_id: str
    facts: tuple[CompiledInspectionFact, ...]
    waveform_count: int
    waveforms_truncated: bool
    waveforms: tuple[CompiledWaveformInspection, ...]
    warnings: tuple[str, ...] = ()

    def fact(self, fact_id: str) -> CompiledInspectionFact:
        return next(fact for fact in self.facts if fact.id == fact_id)


@dataclass(frozen=True, slots=True)
class CompiledInspectionBounds:
    """Hard response budgets applied to one transient inspection."""

    max_points: int
    max_waveforms_per_point: int
    max_samples_per_waveform: int


@dataclass(frozen=True, slots=True)
class CompiledArtifactInspection:
    """Common inspection envelope shared by pre-run and running views."""

    kind: str
    facts: tuple[CompiledInspectionFact, ...]
    point_count: int
    points_truncated: bool
    bounds: CompiledInspectionBounds
    points: tuple[CompiledPointInspection, ...]
    warnings: tuple[str, ...] = ()
    schema_id: Literal["scopecat.compiled_artifact_inspection.v1"] = (
        "scopecat.compiled_artifact_inspection.v1"
    )

    def fact(self, fact_id: str) -> CompiledInspectionFact:
        return next(fact for fact in self.facts if fact.id == fact_id)


__all__ = [
    "CompiledArtifactInspection",
    "CompiledInspectionBounds",
    "CompiledInspectionFact",
    "CompiledPointInspection",
    "CompiledWaveformInspection",
]
