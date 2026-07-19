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
        schema=selected.schema_for(catalog.points),
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
                kind=record.kind,
                unit=record.unit,
                dtype=record.dtype,
                dims=tuple(record.dims),
                shape=tuple(record.shape),
            )
            for record in selected.records
        ),
    )
