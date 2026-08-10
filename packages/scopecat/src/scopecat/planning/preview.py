"""Projection of a RunProgram into stable user-visible facts."""

from __future__ import annotations

from scopecat.execution.local.program import ComputeOperation, OutputInput
from scopecat.execution.program import RunCoverageEffect, RunProgram
from scopecat.measurements.records import RecordPlan, ValueRecordPlan
from scopecat.planning.preview_models import (
    ExperimentPreview,
    ExperimentPreviewCompute,
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
        computes=_preview_computes(program),
    )


def _preview_computes(program: RunProgram) -> tuple[ExperimentPreviewCompute, ...]:
    host_operations: dict[str, ComputeOperation] = {}
    for covered in program.coverage:
        if isinstance(covered, RunCoverageEffect) and isinstance(
            covered.operation, ComputeOperation
        ):
            host_operations.setdefault(
                covered.operation.logical_compute_node_id,
                covered.operation,
            )

    value_record_demands = {
        record.value_id: f"record:{record.id}"
        for record in program.measurements.records
        if isinstance(record, ValueRecordPlan)
    }
    product_record_demands: dict[object, list[str]] = {}
    for record in program.measurements.records:
        if isinstance(record, RecordPlan):
            product_record_demands.setdefault(record.product_id, []).append(
                f"record:{record.id}"
            )
    observation_value_demands: dict[object, list[str]] = {}
    observation_product_demands: dict[object, list[str]] = {}
    for postprocessor in program.measurement_postprocessors:
        demand = f"compute:{postprocessor.id.qualified_name}"
        for value_input in postprocessor.value_inputs:
            observation_value_demands.setdefault(value_input.value_id, []).append(
                demand
            )
        for product_input in postprocessor.inputs:
            observation_product_demands.setdefault(product_input.product_id, []).append(
                demand
            )

    host_result_demands: dict[object, list[str]] = {}
    for operation in host_operations.values():
        demand = f"compute:{operation.logical_compute_node_id}"
        for input_value in operation.inputs.values():
            if isinstance(input_value, OutputInput):
                host_result_demands.setdefault(input_value.value_id, []).append(demand)

    computes: list[ExperimentPreviewCompute] = []
    for operation in host_operations.values():
        demands = tuple(
            dict.fromkeys(
                (
                    *(host_result_demands.get(operation.result.id, ())),
                    *(observation_value_demands.get(operation.result.id, ())),
                    *(
                        (value_record_demands[operation.result.id],)
                        if operation.result.id in value_record_demands
                        else ()
                    ),
                    *(
                        ("effect-payload",)
                        if operation.payload_slot is not None
                        else ()
                    ),
                )
            )
        )
        computes.append(
            ExperimentPreviewCompute(
                id=operation.logical_compute_node_id,
                placement="host",
                input_names=tuple(operation.inputs),
                outputs=(operation.logical_compute_node_id,),
                demanded_by=demands or ("experiment-effects",),
                implementation_id=operation.implementation_id,
            )
        )

    for postprocessor in program.measurement_postprocessors:
        demands = tuple(
            dict.fromkeys(
                demand
                for output in postprocessor.outputs
                for demand in (
                    *product_record_demands.get(output.product_id, ()),
                    *observation_product_demands.get(output.product_id, ()),
                )
            )
        )
        computes.append(
            ExperimentPreviewCompute(
                id=postprocessor.id.qualified_name,
                placement="observation",
                input_names=(
                    *(input.id for input in postprocessor.inputs),
                    *(input.id for input in postprocessor.value_inputs),
                ),
                outputs=tuple(
                    output.product_id.qualified_name for output in postprocessor.outputs
                ),
                demanded_by=demands,
            )
        )
    return tuple(computes)
