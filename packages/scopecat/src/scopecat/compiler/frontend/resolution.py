"""Compose and verify authoring invocations as canonical logical programs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from scopecat.compiler.frontend.elaboration import (
    compose_experiment,
)
from scopecat.compiler.frontend.logical_verification import (
    VerifiedLogicalProgram,
    verify_logical_program,
)
from scopecat.compiler.frontend.problems import frontend_problem as _problem
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.scan_lowering import (
    lower_scans_point_domain,
    project_scan_record,
)
from scopecat.compiler.frontend.scan_validation import (
    ScanValidationError,
    verify_scans,
)
from scopecat.graph.relations.point_domain import analyze_point_domain
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
    is_assignable,
)
from scopecat.program.definitions import ExperimentInvocation
from scopecat.program.logical import LogicalProgram
from scopecat.program.parameters import merge_parameter_contracts
from scopecat.program.scans import (
    AxisSpec,
    Scan,
    scan_parameter_contracts,
)
from scopecat.program.values import ModuleInput
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class CompiledInvocation:
    """Config-free result of compiling one DSL invocation."""

    program: VerifiedLogicalProgram
    request: RunRequest


def compile_invocation(
    invocation: ExperimentInvocation,
    *,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> CompiledInvocation:
    scans = _effective_scans(invocation)
    inputs = _merged_inputs(invocation)
    compiled = _compile_invocation_definition(invocation, inputs)
    scan_axes = _verified_scans(
        scans,
        inputs=inputs,
    )
    _validate_required_invocation_inputs(
        invocation,
        inputs,
    )
    request = _materialized_request(
        invocation,
        inputs=inputs,
        scan_axes=scan_axes,
        metadata=metadata,
        operator=operator,
    )
    merged_inputs = {**compiled.inputs, **inputs}
    logical = replace(
        compiled,
        inputs=merged_inputs,
    )
    _validate_point_dependencies(logical, scan_axes)
    logical = _apply_scans(
        logical,
        scan_axes,
        inputs=inputs,
    )
    return CompiledInvocation(
        program=verify_logical_program(logical),
        request=request,
    )


def _compile_invocation_definition(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> LogicalProgram:
    definition = invocation.definition
    program_input_ids = {port.id for port in definition.interface.imports}
    program_inputs: dict[str, ModuleInput] = {}
    for input_id, value in inputs.items():
        if input_id not in program_input_ids:
            continue
        program_inputs[input_id] = cast("ModuleInput", value)
    assembly = compose_experiment(
        definition,
        inputs=program_inputs,
    )
    return replace(
        assembly,
        record_selections=(
            *assembly.record_selections,
            *definition.record_selections,
        ),
    )


def _validate_required_invocation_inputs(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> None:
    missing = [
        definition.id
        for definition in invocation.definition.inputs
        if definition.required and definition.id not in inputs
    ]
    if missing:
        raise CheckFailed(
            [
                _problem(
                    "experiment_missing_input",
                    "experiment missing required input: " + ", ".join(missing),
                    "experiment",
                    path=("inputs",),
                )
            ]
        )


def _effective_scans(invocation: ExperimentInvocation) -> tuple[AxisSpec, ...]:
    defaults = tuple(
        cast("AxisSpec", scan) for scan in invocation.definition.default_scans
    )
    overrides = tuple(cast("AxisSpec", scan) for scan in invocation.scans)
    override_axis_ids = [axis.id for axis in overrides]
    # Validate before indexing so repeated overrides cannot silently collapse.
    duplicate_overrides = sorted(
        axis_id for axis_id, count in Counter(override_axis_ids).items() if count > 1
    )
    if duplicate_overrides:
        raise CheckFailed(
            [
                _problem(
                    "scan_axis_duplicate",
                    "duplicate scan axis: " + ", ".join(duplicate_overrides),
                    "scans",
                )
            ]
        )
    default_axis_ids = {axis.id for axis in defaults}
    override_by_id = {axis.id: axis for axis in overrides}
    replaced = tuple(override_by_id.get(default.id, default) for default in defaults)
    additions = tuple(axis for axis in overrides if axis.id not in default_axis_ids)
    return (*replaced, *additions)


def _merged_inputs(
    invocation: ExperimentInvocation,
) -> dict[str, object]:
    merged: dict[str, object] = {
        input_definition.id: input_definition.default
        for input_definition in invocation.definition.inputs
        if input_definition.has_default
    }
    merged.update(invocation.inputs)
    return merged


def _materialized_request(
    invocation: ExperimentInvocation,
    *,
    inputs: Mapping[str, object],
    scan_axes: Sequence[AxisSpec],
    metadata: Mapping[str, object] | None,
    operator: str | None,
) -> RunRequest:
    request_inputs = project_run_request_inputs(inputs)
    request_scans = [project_scan_record(axis, inputs=inputs) for axis in scan_axes]
    return RunRequest.model_validate(
        {
            "experiment_id": invocation.definition.id,
            "inputs": request_inputs,
            "scans": request_scans,
            "operator": operator,
            "metadata": dict(metadata or {}),
        }
    )


def _verified_scans(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> tuple[AxisSpec, ...]:
    try:
        return verify_scans(
            scans,
            inputs=inputs,
        )
    except ScanValidationError as error:
        raise CheckFailed(
            [
                _problem(
                    issue.code,
                    issue.message,
                    "scans",
                    path=issue.path,
                )
                for issue in error.issues
            ]
        ) from error


def _apply_scans(
    assembly: LogicalProgram,
    scan_axes: Sequence[AxisSpec],
    *,
    inputs: Mapping[str, object],
) -> LogicalProgram:
    point_domain = lower_scans_point_domain(
        scan_axes,
        inputs=inputs,
    )
    return replace(
        assembly,
        point_domain=point_domain,
        parameter_contracts=merge_parameter_contracts(
            assembly.parameter_contracts,
            *(scan_parameter_contracts(axis) for axis in scan_axes),
        ),
        parameter_overlays=(
            *assembly.parameter_overlays,
            *(axis for axis in scan_axes if axis.parameter_lookup is not None),
        ),
    )


def _validate_point_dependencies(
    assembly: LogicalProgram,
    scan_axes: Sequence[AxisSpec],
) -> None:
    domain_type = analyze_point_domain(assembly.point_domain).value_type
    point_types = {
        **{column.id: column.value_type for column in domain_type.columns},
        **{axis.id: axis.value_type for axis in scan_axes},
    }
    problems: list[Problem] = []
    for dependency in assembly.point_dependencies:
        actual = point_types.get(dependency.id)
        if actual is None:
            problems.append(
                _problem(
                    "experiment_point_dependency_missing",
                    f"module requires point {dependency.id!r}, but no point "
                    "domain provides it",
                    "scans",
                    path=(dependency.id,),
                )
            )
            continue
        if is_assignable(actual, dependency.value_type):
            continue
        problems.append(
            _problem(
                "experiment_point_dependency_type_mismatch",
                f"scan for point {dependency.id!r} provides "
                f"{describe_value_type(actual)}, but the module requires "
                f"{describe_value_type(dependency.value_type)}",
                "scans",
                path=(dependency.id,),
            )
        )
    if problems:
        raise CheckFailed(problems)
