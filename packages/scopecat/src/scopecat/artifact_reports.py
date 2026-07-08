"""Artifact completion and availability reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic

CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION = "scopecat.chunked_artifact_manifest.v1"


class ArtifactChunk(BaseModel):
    """One ordered payload fragment for a larger data artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str
    index: int
    values: list[Any] = Field(default_factory=list)
    final: bool = False


class ChunkedArtifactManifest(BaseModel):
    """Completion report for a chunked data artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.chunked_artifact_manifest.v1"] = (
        CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION
    )
    artifact_ref: str
    chunks: list[ArtifactChunk] = Field(default_factory=list)
    value_count: int = 0
    complete: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ArtifactRequirement(BaseModel):
    """Artifact slot required or accepted before downstream analysis."""

    model_config = ConfigDict(extra="forbid")

    label: str
    required: bool = True


class PointArtifactStatus(BaseModel):
    """Artifact eligibility for one logical point."""

    model_config = ConfigDict(extra="forbid")

    point_index: int
    available: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    eligible: bool


class ArtifactAvailabilityReport(BaseModel):
    """Point eligibility report based on required artifact refs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.artifact_availability_report.v2"] = (
        "scopecat.artifact_availability_report.v2"
    )
    points: list[PointArtifactStatus] = Field(default_factory=list)
    eligible_point_indices: list[int] = Field(default_factory=list)
    partial_point_indices: list[int] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def assemble_chunked_artifact(
    artifact_ref: str,
    chunks: Sequence[ArtifactChunk],
    *,
    expected_chunks: int | None = None,
) -> ChunkedArtifactManifest:
    if expected_chunks is not None and expected_chunks <= 0:
        msg = "expected_chunks must be positive"
        raise ValueError(msg)

    diagnostics: list[Diagnostic] = []
    by_index: dict[int, ArtifactChunk] = {}
    for chunk in chunks:
        if chunk.artifact_ref != artifact_ref:
            diagnostics.append(
                _diagnostic(
                    "chunk_artifact_mismatch",
                    f"chunk {chunk.index} belongs to {chunk.artifact_ref!r}",
                    f"chunks.{chunk.index}.artifact_ref",
                )
            )
            continue
        if chunk.index < 0:
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_chunk",
                    f"chunk index {chunk.index} is negative",
                    f"chunks.{chunk.index}.index",
                )
            )
            continue
        if chunk.index in by_index:
            diagnostics.append(
                _diagnostic(
                    "duplicate_artifact_chunk",
                    f"duplicate chunk index {chunk.index}",
                    f"chunks.{chunk.index}.index",
                )
            )
            continue
        by_index[chunk.index] = chunk

    ordered = [chunk for _, chunk in sorted(by_index.items())]
    expected = expected_chunks
    if expected is None:
        final_chunks = [chunk for chunk in ordered if chunk.final]
        if len(final_chunks) == 1:
            expected = final_chunks[0].index + 1
        elif len(final_chunks) > 1:
            diagnostics.append(
                _diagnostic(
                    "multiple_final_artifact_chunks",
                    f"artifact {artifact_ref!r} has multiple final chunks",
                    "chunks",
                )
            )

    if expected is not None:
        missing = [index for index in range(expected) if index not in by_index]
        if missing:
            diagnostics.append(
                _diagnostic(
                    "missing_artifact_chunks",
                    f"missing chunks {missing!r}",
                    "chunks",
                )
            )

    complete = expected is not None and not diagnostics and len(ordered) == expected
    return ChunkedArtifactManifest(
        artifact_ref=artifact_ref,
        chunks=ordered,
        value_count=sum(len(chunk.values) for chunk in ordered),
        complete=complete,
        diagnostics=diagnostics,
    )


def evaluate_artifact_availability(
    rows: Sequence[Mapping[str, Any]],
    requirements: Sequence[ArtifactRequirement],
    *,
    point_count: int,
) -> ArtifactAvailabilityReport:
    diagnostics: list[Diagnostic] = []
    by_point: dict[int, Mapping[str, Any]] = {}
    for row_index, row in enumerate(rows):
        point_index = row.get("point_index")
        if not isinstance(point_index, int) or isinstance(point_index, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_point",
                    f"row {row_index} has invalid point_index {point_index!r}",
                    f"rows.{row_index}.point_index",
                )
            )
            continue
        if point_index < 0 or point_index >= point_count:
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_point",
                    f"row {row_index} point_index {point_index} is out of range",
                    f"rows.{row_index}.point_index",
                )
            )
            continue
        if point_index in by_point:
            diagnostics.append(
                _diagnostic(
                    "duplicate_artifact_point",
                    f"row {row_index} repeats point_index {point_index}",
                    f"rows.{row_index}.point_index",
                )
            )
            continue
        by_point[point_index] = row

    point_statuses: list[PointArtifactStatus] = []
    for point_index in range(point_count):
        row = by_point.get(point_index, {})
        available: list[str] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        for requirement in requirements:
            if _has_artifact_ref(row.get(requirement.label)):
                available.append(requirement.label)
            elif requirement.required:
                missing_required.append(requirement.label)
                diagnostics.append(
                    _diagnostic(
                        "missing_required_artifact",
                        (
                            f"point {point_index} is missing required artifact "
                            f"{requirement.label!r}"
                        ),
                        f"points.{point_index}.{requirement.label}",
                    )
                )
            else:
                missing_optional.append(requirement.label)
                diagnostics.append(
                    _diagnostic(
                        "missing_optional_artifact",
                        (
                            f"point {point_index} is missing optional artifact "
                            f"{requirement.label!r}"
                        ),
                        f"points.{point_index}.{requirement.label}",
                    )
                )
        point_statuses.append(
            PointArtifactStatus(
                point_index=point_index,
                available=available,
                missing_required=missing_required,
                missing_optional=missing_optional,
                eligible=not missing_required,
            )
        )

    return ArtifactAvailabilityReport(
        points=point_statuses,
        eligible_point_indices=[
            point.point_index for point in point_statuses if point.eligible
        ],
        partial_point_indices=[
            point.point_index
            for point in point_statuses
            if point.eligible and point.missing_optional
        ],
        diagnostics=diagnostics,
    )


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _has_artifact_ref(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    artifact_value = cast("Mapping[str, object]", value)
    artifact_ref = artifact_value.get("artifact_ref")
    return isinstance(artifact_ref, str) and artifact_ref.strip() != ""


__all__ = [
    "ArtifactAvailabilityReport",
    "ArtifactChunk",
    "ArtifactRequirement",
    "ChunkedArtifactManifest",
    "PointArtifactStatus",
    "assemble_chunked_artifact",
    "evaluate_artifact_availability",
]
