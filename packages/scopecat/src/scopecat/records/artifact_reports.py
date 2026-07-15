"""Artifact completion and availability reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION = "scopecat.chunked_artifact_manifest.v2"


class ArtifactChunk(BaseModel):
    """One ordered payload fragment for a larger data artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: str
    index: int
    values: tuple[object, ...] = ()
    final: bool = False


class ChunkedArtifactManifest(BaseModel):
    """Completion report for a chunked data artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.chunked_artifact_manifest.v2"] = (
        CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION
    )
    artifact_ref: str
    chunks: tuple[ArtifactChunk, ...] = ()
    value_count: int = 0
    complete: bool
    problems: tuple[Problem, ...] = ()


class ArtifactRequirement(BaseModel):
    """Artifact slot required or accepted before downstream analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    required: bool = True


class PointArtifactStatus(BaseModel):
    """Artifact eligibility for one logical point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_index: int
    available: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    eligible: bool


class ArtifactAvailabilityReport(BaseModel):
    """Point eligibility report based on required artifact refs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.artifact_availability_report.v3"] = (
        "scopecat.artifact_availability_report.v3"
    )
    points: tuple[PointArtifactStatus, ...] = ()
    eligible_point_indices: tuple[int, ...] = ()
    partial_point_indices: tuple[int, ...] = ()
    problems: tuple[Problem, ...] = ()


def assemble_chunked_artifact(
    artifact_ref: str,
    chunks: Sequence[ArtifactChunk],
    *,
    expected_chunks: int | None = None,
) -> ChunkedArtifactManifest:
    if expected_chunks is not None and expected_chunks <= 0:
        msg = "expected_chunks must be positive"
        raise ValueError(msg)

    problems: list[Problem] = []
    by_index: dict[int, ArtifactChunk] = {}
    for input_index, chunk in enumerate(chunks):
        if chunk.artifact_ref != artifact_ref:
            problems.append(
                blocking_problem(
                    "chunk_artifact_mismatch",
                    f"chunk {chunk.index} belongs to {chunk.artifact_ref!r}",
                    category=ProblemCategory.DATA_INTEGRITY,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "chunked_artifact",
                        "chunks",
                        input_index,
                        "artifact_ref",
                    ),
                    details={
                        "expected_artifact_ref": artifact_ref,
                        "actual_artifact_ref": chunk.artifact_ref,
                        "chunk_index": chunk.index,
                    },
                )
            )
            continue
        if chunk.index < 0:
            problems.append(
                blocking_problem(
                    "invalid_artifact_chunk",
                    f"chunk index {chunk.index} is negative",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "chunked_artifact",
                        "chunks",
                        input_index,
                        "index",
                    ),
                    details={"chunk_index": chunk.index},
                )
            )
            continue
        if chunk.index in by_index:
            first_index = next(
                index
                for index, selected in enumerate(chunks)
                if selected.index == chunk.index
            )
            problems.append(
                blocking_problem(
                    "duplicate_artifact_chunk",
                    f"duplicate chunk index {chunk.index}",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "chunked_artifact",
                        "chunks",
                        input_index,
                        "index",
                    ),
                    related_locations=(
                        model_location(
                            "chunked_artifact",
                            "chunks",
                            first_index,
                            "index",
                        ),
                    ),
                    details={"chunk_index": chunk.index},
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
            problems.append(
                blocking_problem(
                    "multiple_final_artifact_chunks",
                    f"artifact {artifact_ref!r} has multiple final chunks",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("chunked_artifact", "chunks"),
                    details={
                        "artifact_ref": artifact_ref,
                        "final_chunk_indices": [chunk.index for chunk in final_chunks],
                    },
                )
            )

    if expected is not None:
        missing = [index for index in range(expected) if index not in by_index]
        if missing:
            problems.append(
                blocking_problem(
                    "missing_artifact_chunks",
                    f"missing chunks {missing!r}",
                    category=ProblemCategory.UNAVAILABLE,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("chunked_artifact", "chunks"),
                    details={"missing_chunk_indices": missing},
                )
            )

    complete = expected is not None and not problems and len(ordered) == expected
    return ChunkedArtifactManifest(
        artifact_ref=artifact_ref,
        chunks=tuple(ordered),
        value_count=sum(len(chunk.values) for chunk in ordered),
        complete=complete,
        problems=tuple(problems),
    )


def evaluate_artifact_availability(
    rows: Sequence[Mapping[str, object]],
    requirements: Sequence[ArtifactRequirement],
    *,
    point_count: int,
) -> ArtifactAvailabilityReport:
    problems: list[Problem] = []
    by_point: dict[int, Mapping[str, object]] = {}
    for row_index, row in enumerate(rows):
        point_index = row.get("point_index")
        if not isinstance(point_index, int) or isinstance(point_index, bool):
            problems.append(
                blocking_problem(
                    "invalid_artifact_point",
                    f"row {row_index} has invalid point_index {point_index!r}",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "artifact_availability",
                        "rows",
                        row_index,
                        "point_index",
                    ),
                )
            )
            continue
        if point_index < 0 or point_index >= point_count:
            problems.append(
                blocking_problem(
                    "invalid_artifact_point",
                    f"row {row_index} point_index {point_index} is out of range",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "artifact_availability",
                        "rows",
                        row_index,
                        "point_index",
                    ),
                    details={"point_index": point_index, "point_count": point_count},
                )
            )
            continue
        if point_index in by_point:
            first_row_index = next(
                index
                for index, selected in enumerate(rows)
                if selected.get("point_index") == point_index
            )
            problems.append(
                blocking_problem(
                    "duplicate_artifact_point",
                    f"row {row_index} repeats point_index {point_index}",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "artifact_availability",
                        "rows",
                        row_index,
                        "point_index",
                    ),
                    related_locations=(
                        model_location(
                            "artifact_availability",
                            "rows",
                            first_row_index,
                            "point_index",
                        ),
                    ),
                    details={"point_index": point_index},
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
                problems.append(
                    blocking_problem(
                        "missing_required_artifact",
                        (
                            f"point {point_index} is missing required artifact "
                            f"{requirement.label!r}"
                        ),
                        category=ProblemCategory.UNAVAILABLE,
                        phase=ProblemPhase.ANALYSIS,
                        location=model_location(
                            "artifact_availability",
                            "points",
                            point_index,
                            requirement.label,
                        ),
                        details={
                            "point_index": point_index,
                            "artifact_label": requirement.label,
                        },
                    )
                )
            else:
                missing_optional.append(requirement.label)
        point_statuses.append(
            PointArtifactStatus(
                point_index=point_index,
                available=tuple(available),
                missing_required=tuple(missing_required),
                missing_optional=tuple(missing_optional),
                eligible=not missing_required,
            )
        )

    return ArtifactAvailabilityReport(
        points=tuple(point_statuses),
        eligible_point_indices=tuple(
            point.point_index for point in point_statuses if point.eligible
        ),
        partial_point_indices=tuple(
            point.point_index
            for point in point_statuses
            if point.eligible and point.missing_optional
        ),
        problems=tuple(problems),
    )


def _has_artifact_ref(value: object) -> bool:
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
