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

    selected = program.measurements
    catalog = program.points
    return ExperimentPreview(
        experiment_id=catalog.experiment_id,
        experiment_kind=catalog.experiment_kind,
        schema=selected.schema,
        coordinate_ids=tuple(selected.coordinate_ids),
        points=tuple(
            ExperimentPreviewPoint(
                point_index=resolved.ordinal,
                coordinates=dict(resolved.coordinates),
            )
            for resolved in catalog.points
        ),
        records=tuple(
            ExperimentPreviewRecord(
                id=record.id,
                role=record.role,
                recording_group_id=record.recording_group_id,
                unit=record.unit,
                dtype=record.dtype,
                dims=("point", *(axis.id for axis in record.axes)),
                shape=(
                    len(catalog.points),
                    *(axis.size for axis in record.axes),
                ),
            )
            for record in selected.records
        ),
    )
