"""Projection of a prepared execution plan into stable user-visible facts."""

from __future__ import annotations

from scopecat.planning.backend import PreparedExecutionPlan
from scopecat.planning.preview_models import (
    ExperimentPreview,
    ExperimentPreviewPoint,
    ExperimentPreviewRecord,
)


def build_execution_plan_preview(
    prepared: PreparedExecutionPlan,
) -> ExperimentPreview:
    """Project stable user-visible facts from a prepared execution plan."""

    selected = prepared.projection.projection
    program = prepared.linked_points.linked_plan.program
    points = prepared.linked_points.point_domain.points
    return ExperimentPreview(
        experiment_id=program.id,
        experiment_kind=program.kind,
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


__all__ = ["build_execution_plan_preview"]
