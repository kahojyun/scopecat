"""Compose and verify authoring invocations as canonical logical programs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

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
    project_axis_record,
    project_point_cloud_record,
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
from scopecat.optimization import AdaptiveDomainPlan
from scopecat.program.definitions import ExperimentInvocation
from scopecat.program.logical import LogicalProgram
from scopecat.program.point_domain import analyze_point_domain
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    PointDomainSpec,
    PointGrouping,
    PointPlan,
    PointsSpec,
    expand_point_plan,
)
from scopecat.program.value_refs import ValueRef
from scopecat.records.run_request import (
    AdaptiveDomainPlanRecord,
    GridDomainRecord,
    PointGroupingRecord,
    PointPlanRecord,
    PointScheduleRecord,
    RunRequest,
)
from scopecat.records.sample import SampleSelector


@dataclass(frozen=True, slots=True)
class CompiledInvocation:
    """Config-free result of compiling one DSL invocation."""

    program: VerifiedLogicalProgram
    request: RunRequest
    adaptive_domain_plan: AdaptiveDomainPlan | None = field(
        default=None,
        repr=False,
    )


def compile_invocation(
    invocation: ExperimentInvocation,
    *,
    display_name: str | None = None,
    tags: tuple[str, ...] = (),
    description: str | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
    samples: tuple[SampleSelector, ...] = (),
) -> CompiledInvocation:
    base_plan = replace(
        invocation.point_plan,
        domain=_resolve_point_domain_module_results(
            invocation,
            invocation.point_plan.domain,
        ),
    )
    inputs = _merged_inputs(invocation)
    base_domain = _verified_point_domain(
        base_plan.domain,
        inputs=inputs,
    )
    _validate_required_invocation_inputs(
        invocation,
        inputs,
    )
    request = _materialized_request(
        invocation,
        inputs=inputs,
        point_plan=base_plan,
        base_domain=base_domain,
        display_name=display_name,
        tags=tags,
        description=description,
        metadata=metadata,
        operator=operator,
        samples=samples,
    )
    expanded_domain = _verified_point_domain(
        expand_point_plan(base_plan),
        inputs=inputs,
    )
    _validate_point_grouping(
        base_plan.schedule.grouping,
        expanded_domain,
        adaptive=invocation.adaptive_domain_plan is not None,
    )
    logical = compose_experiment(
        invocation.definition,
        inputs=inputs,
        scans=expanded_domain.axes,
        point_domain_layout=expanded_domain.layout,
        point_repeat=base_plan.repeat,
        point_repeat_mode=base_plan.repeat_mode,
        point_schedule=base_plan.schedule,
    )
    _validate_point_dependencies(logical, expanded_domain)
    return CompiledInvocation(
        program=verify_logical_program(logical),
        request=request,
        adaptive_domain_plan=invocation.adaptive_domain_plan,
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
    point_plan: PointPlan,
    base_domain: VerifiedPointDomain,
    display_name: str | None,
    tags: tuple[str, ...],
    description: str | None,
    metadata: Mapping[str, object] | None,
    operator: str | None,
    samples: tuple[SampleSelector, ...],
) -> RunRequest:
    request_inputs = project_run_request_inputs(inputs)
    request_point_domain = (
        project_point_cloud_record(PointsSpec(base_domain.axes), inputs=inputs)
        if base_domain.layout == "point_cloud"
        else GridDomainRecord(
            axes=[project_axis_record(axis, inputs=inputs) for axis in base_domain.axes]
        )
    )
    return RunRequest.model_validate(
        {
            "experiment_id": invocation.definition.id,
            "display_name": display_name,
            "tags": tags,
            "description": description,
            "inputs": request_inputs,
            "point_plan": PointPlanRecord(
                domain=request_point_domain,
                repeat=point_plan.repeat,
                repeat_mode=point_plan.repeat_mode,
                schedule=PointScheduleRecord(
                    traversal=point_plan.schedule.traversal,
                    grouping=(
                        None
                        if point_plan.schedule.grouping is None
                        else PointGroupingRecord(
                            id=point_plan.schedule.grouping.id,
                            varying_coordinate_ids=(
                                point_plan.schedule.grouping.varying_coordinate_ids
                            ),
                            scheduling=point_plan.schedule.grouping.scheduling,
                            on_interruption=(
                                point_plan.schedule.grouping.on_interruption
                            ),
                        )
                    ),
                ),
            ),
            "adaptive_domain_plan": (
                None
                if invocation.adaptive_domain_plan is None
                else AdaptiveDomainPlanRecord(
                    optimizer_id=invocation.adaptive_domain_plan.optimizer_id,
                    total_point_limit=(
                        invocation.adaptive_domain_plan.total_point_limit
                    ),
                    adaptive_coordinate_ids=(
                        invocation.adaptive_domain_plan.adaptive_coordinate_ids
                    ),
                    scope=invocation.adaptive_domain_plan.scope,
                    per_region_point_limit=(
                        invocation.adaptive_domain_plan.per_region_point_limit
                    ),
                )
            ),
            "operator": operator,
            "samples": samples,
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


def _validate_point_grouping(
    grouping: PointGrouping | None,
    point_domain: VerifiedPointDomain,
    *,
    adaptive: bool,
) -> None:
    if grouping is None:
        return
    coordinate_ids = {axis.id for axis in point_domain.axes}
    missing = sorted(set(grouping.varying_coordinate_ids) - coordinate_ids)
    problems: list[Problem] = []
    if missing:
        problems.append(
            _problem(
                "point_grouping_coordinate_missing",
                "point grouping references coordinates not present in the point "
                "domain: " + ", ".join(missing),
                "point_plan",
                path=("grouping", "varying_coordinate_ids"),
                details={"missing_coordinate_ids": missing},
            )
        )
    if adaptive:
        problems.append(
            _problem(
                "adaptive_point_grouping_unsupported",
                "adaptive point plans cannot yet restart coordinate groups as a unit",
                "point_plan",
                path=("grouping",),
                details={"grouping_id": grouping.id},
            )
        )
    if problems:
        raise CheckFailed(problems)


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
                f"axis for point {dependency.id!r} provides "
                f"{describe_value_type(actual)}, but the module requires "
                f"{describe_value_type(dependency.value_type)}",
                "point_domain",
                path=(dependency.id,),
            )
        )
    if problems:
        raise CheckFailed(problems)
