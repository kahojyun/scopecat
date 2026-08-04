"""Compose and verify authoring invocations as canonical logical programs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from scopecat.compiler.frontend.elaboration import (
    compose_experiment,
)
from scopecat.compiler.frontend.logical_verification import (
    VerifiedLogicalProgram,
    verify_logical_program,
)
from scopecat.compiler.frontend.module_resolution import ModuleValueResolver
from scopecat.compiler.frontend.problems import frontend_problem as _problem
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.scan_lowering import (
    project_point_cloud_record,
    project_scan_record,
)
from scopecat.compiler.frontend.scan_validation import (
    PointDomainValidationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
    is_assignable,
)
from scopecat.program.definitions import ExperimentInvocation
from scopecat.program.logical import LogicalProgram
from scopecat.program.point_domain import analyze_point_domain
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    PointDomainSpec,
    PointsSpec,
)
from scopecat.program.value_refs import ValueRef
from scopecat.records.run_request import GridDomainRecord, RunRequest


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
    domain = _resolve_point_domain_module_results(
        invocation,
        invocation.point_plan.domain,
    )
    inputs = _merged_inputs(invocation)
    point_domain = _verified_point_domain(
        domain,
        inputs=inputs,
    )
    _validate_required_invocation_inputs(
        invocation,
        inputs,
    )
    request = _materialized_request(
        invocation,
        inputs=inputs,
        point_domain=point_domain,
        metadata=metadata,
        operator=operator,
    )
    logical = compose_experiment(
        invocation.definition,
        inputs=inputs,
        scans=point_domain.axes,
        point_domain_layout=point_domain.layout,
    )
    _validate_point_dependencies(logical, point_domain)
    return CompiledInvocation(
        program=verify_logical_program(logical),
        request=request,
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


def _resolve_point_domain_module_results(
    invocation: ExperimentInvocation,
    domain: PointDomainSpec,
) -> PointDomainSpec:
    """Resolve module-return edges before scan validation and request projection."""

    resolver = ModuleValueResolver(invocation.definition)
    resolved: list[AxisSpec] = []
    for axis in domain.axes:
        source = axis.source
        if isinstance(source, AroundScanSource) and isinstance(
            source.center,
            ValueRef,
        ):
            source = replace(source, center=resolver.resolve(source.center))
        overlay = axis.overlay
        if overlay is not None:
            overlay = resolver.resolve(overlay)
        resolved.append(
            replace(
                axis,
                source=source,
                overlay=overlay,
            )
        )
    return replace(domain, axes=tuple(resolved))


def _merged_inputs(
    invocation: ExperimentInvocation,
) -> dict[str, object]:
    merged: dict[str, object] = {
        input_definition.id: input_definition.default
        for input_definition in invocation.definition.inputs
        if input_definition.has_default
    }
    merged.update(invocation.input_overrides)
    return merged


def _materialized_request(
    invocation: ExperimentInvocation,
    *,
    inputs: Mapping[str, object],
    point_domain: VerifiedPointDomain,
    metadata: Mapping[str, object] | None,
    operator: str | None,
) -> RunRequest:
    request_inputs = project_run_request_inputs(inputs)
    request_point_domain = (
        project_point_cloud_record(PointsSpec(point_domain.axes), inputs=inputs)
        if point_domain.layout == "point_cloud"
        else GridDomainRecord(
            axes=[
                project_scan_record(axis, inputs=inputs) for axis in point_domain.axes
            ]
        )
    )
    return RunRequest.model_validate(
        {
            "experiment_id": invocation.definition.id,
            "inputs": request_inputs,
            "point_domain": request_point_domain,
            "operator": operator,
            "metadata": dict(metadata or {}),
        }
    )


def _verified_point_domain(
    domain: PointDomainSpec,
    *,
    inputs: Mapping[str, object],
) -> VerifiedPointDomain:
    try:
        return verify_point_domain(
            domain,
            inputs=inputs,
        )
    except PointDomainValidationError as error:
        raise CheckFailed(
            [
                _problem(
                    issue.code,
                    issue.message,
                    "point_domain",
                    path=issue.path,
                )
                for issue in error.issues
            ]
        ) from error


def _validate_point_dependencies(
    program: LogicalProgram,
    point_domain: VerifiedPointDomain,
) -> None:
    domain_type = analyze_point_domain(
        program.point_domain,
        layout=program.point_domain_layout,
    ).value_type
    point_types = {
        **{column.id: column.value_type for column in domain_type.columns},
        **{axis.id: axis.value_type for axis in point_domain.axes},
    }
    problems: list[Problem] = []
    for dependency in program.point_dependencies:
        actual = point_types.get(dependency.id)
        if actual is None:
            problems.append(
                _problem(
                    "experiment_point_dependency_missing",
                    f"module requires point {dependency.id!r}, but no point "
                    "domain provides it",
                    "point_domain",
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
                "point_domain",
                path=(dependency.id,),
            )
        )
    if problems:
        raise CheckFailed(problems)
