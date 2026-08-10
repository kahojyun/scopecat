"""Projection of a RunProgram into stable user-visible facts."""

from __future__ import annotations

from typing import Literal

from scopecat.authoring.experiments import ExperimentInvocation
from scopecat.execution.local.program import ComputeOperation, OutputInput
from scopecat.execution.program import RunCoverageEffect, RunProgram
from scopecat.measurements.records import RecordPlan, ValueRecordPlan
from scopecat.planning.preview_models import (
    ExperimentPreview,
    ExperimentPreviewBinding,
    ExperimentPreviewBindingEdge,
    ExperimentPreviewBindingRef,
    ExperimentPreviewCompute,
    ExperimentPreviewPoint,
    ExperimentPreviewRecord,
)
from scopecat.program.parameters import ParameterContract, ParameterValueContract
from scopecat.program.scans import AroundScanSource, RangeScanSource, ValuesScanSource
from scopecat.program.value_refs import ValueRef, internal_value_ref_parameter_contracts

type _BindingKind = Literal["input", "coordinate", "parameter"]
type _BindingKey = tuple[_BindingKind, str]


def build_run_program_preview(
    program: RunProgram,
    *,
    invocation: ExperimentInvocation | None = None,
) -> ExperimentPreview:
    """Project stable user-visible facts from a closed RunProgram."""

    selected = program.measurements
    catalog = program.points
    bindings, binding_edges = (
        ((), ()) if invocation is None else _preview_binding_graph(invocation)
    )
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
        bindings=bindings,
        binding_edges=binding_edges,
    )


def _preview_binding_graph(
    invocation: ExperimentInvocation,
) -> tuple[
    tuple[ExperimentPreviewBinding, ...],
    tuple[ExperimentPreviewBindingEdge, ...],
]:
    bindings: dict[_BindingKey, ExperimentPreviewBinding] = {
        ("input", input_definition.id): ExperimentPreviewBinding(
            id=input_definition.id,
            kind="input",
            owner="invocation",
            origin=(
                "override"
                if input_definition.id in invocation.input_overrides
                else "default"
            ),
        )
        for input_definition in invocation.definition.inputs
    }
    edges: list[ExperimentPreviewBindingEdge] = []
    for axis in invocation.point_plan.domain.axes:
        source = axis.source
        origin = (
            "values"
            if isinstance(source, ValuesScanSource)
            else "range"
            if isinstance(source, RangeScanSource)
            else "around"
        )
        coordinate_ref = ExperimentPreviewBindingRef(id=axis.id, kind="coordinate")
        bindings[("coordinate", axis.id)] = ExperimentPreviewBinding(
            id=axis.id,
            kind="coordinate",
            owner="point-plan",
            origin=origin,
        )
        if isinstance(source, AroundScanSource) and isinstance(source.center, ValueRef):
            _add_parameter_edges(
                bindings,
                edges,
                source.center,
                target=coordinate_ref,
                relation="centers",
            )
        if axis.overlay is not None:
            _add_parameter_edges(
                bindings,
                edges,
                axis.overlay,
                target=coordinate_ref,
                relation="overlays",
            )
    return tuple(bindings.values()), tuple(edges)


def _add_parameter_edges(
    bindings: dict[_BindingKey, ExperimentPreviewBinding],
    edges: list[ExperimentPreviewBindingEdge],
    value: ValueRef,
    *,
    target: ExperimentPreviewBindingRef,
    relation: Literal["centers", "overlays"],
) -> None:
    for contract in internal_value_ref_parameter_contracts(value):
        parameter_id = _parameter_contract_id(contract)
        parameter_ref = ExperimentPreviewBindingRef(
            id=parameter_id,
            kind="parameter",
        )
        bindings[("parameter", parameter_id)] = ExperimentPreviewBinding(
            id=parameter_id,
            kind="parameter",
            owner="configuration",
            origin=None,
        )
        edges.append(
            ExperimentPreviewBindingEdge(
                source=parameter_ref,
                target=target,
                relation=relation,
            )
        )


def _parameter_contract_id(contract: ParameterContract) -> str:
    if isinstance(contract, ParameterValueContract):
        return contract.parameter_id
    return f"{contract.table_id}.{contract.column_id}"


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
                implementation=operation.implementation_id,
                deterministic=operation.deterministic,
                inputs=tuple(operation.inputs),
                outputs=(operation.logical_compute_node_id,),
                demanded_by=demands or ("experiment-effects",),
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
                implementation=(
                    postprocessor.implementation
                    or f"python:{postprocessor.id.qualified_name}"
                ),
                deterministic=postprocessor.deterministic,
                inputs=(
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
