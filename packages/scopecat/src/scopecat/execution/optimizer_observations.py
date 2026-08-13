"""Project durable-shaped measurements into bounded optimizer observations."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.kernel.points import AcceptedRunPoint
from scopecat.optimization import (
    CompletedPointObservation,
    OptimizerMeasurementObservation,
    OptimizerObservationValue,
    OptimizerScalarObservation,
    OptimizerUnavailableObservation,
)
from scopecat.records.measurement import (
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
)


def project_completed_point_observation(
    point: AcceptedRunPoint,
    records: Sequence[MeasurementRecord],
) -> CompletedPointObservation:
    """Drop arrays, evidence, and metadata before retaining optimizer context."""

    return CompletedPointObservation(
        point=point,
        measurements=tuple(
            _project_optimizer_measurement(record) for record in records
        ),
    )


def _project_optimizer_measurement(
    record: MeasurementRecord,
) -> OptimizerMeasurementObservation:
    observables: dict[str, OptimizerObservationValue] = {}
    omitted_array_ids: list[str] = []
    for observable_id, value in record.observables.items():
        if isinstance(value, MeasurementScalar):
            observables[observable_id] = OptimizerScalarObservation(
                value=value.value,
                dtype=value.dtype,
                unit=value.unit,
            )
        elif isinstance(value, MeasurementUnavailable):
            observables[observable_id] = OptimizerUnavailableObservation(
                reason=value.reason,
                dtype=value.dtype,
                unit=value.unit,
                shape=value.shape,
            )
        else:
            omitted_array_ids.append(observable_id)
    return OptimizerMeasurementObservation(
        run_id=record.run_id,
        logical_point_id=record.logical_point_id,
        observables=observables,
        omitted_array_ids=tuple(omitted_array_ids),
    )


__all__ = ["project_completed_point_observation"]
