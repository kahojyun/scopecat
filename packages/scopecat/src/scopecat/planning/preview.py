"""Projection of a RunProgram into stable user-visible facts."""

from __future__ import annotations

from scopecat.execution.program import RunProgram
from scopecat.planning.preview_models import (
    ExperimentPreview,
    ExperimentPreviewPoint,
    ExperimentPreviewRecord,
)


def build_run_program_preview(
    program: RunProgram,
) -> ExperimentPreview:
    """Project stable user-visible facts from a closed RunProgram."""

    selected = program.projection.projection
    core_program = program.linked_points.linked_plan.program
    points = program.linked_points.point_domain.points
    return ExperimentPreview(
        experiment_id=core_program.id,
        experiment_kind=core_program.kind,
        schema=selected.schema,
        coordinate_ids=tuple(selected.coordinate_ids),
        points=tuple(
            ExperimentPreviewPoint(
                point_index=resolved.logical_ordinal,
                coordinates={
                    coordinate_id: resolved.row[coordinate_id]
                    for coordinate_id in selected.coordinate_ids
                },
            )
            for resolved in points
        ),
        records=tuple(
            ExperimentPreviewRecord(
                id=record.id,
                kind=record.kind,
                unit=record.unit,
                dtype=record.dtype,
                dims=tuple(record.dims),
                shape=tuple(record.shape),
            )
            for record in selected.records
        ),
    )
