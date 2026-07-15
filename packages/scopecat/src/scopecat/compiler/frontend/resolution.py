"""Compile authoring invocations into transient typed programs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from scopecat.authoring._intents import ParameterScanOverlayIntent
from scopecat.authoring._parameter_contracts import merge_parameter_contracts
from scopecat.authoring._point_domain_intents import (
    PointDomainIntent,
    point_domain_intent_free_point_dependencies,
    point_domain_intent_free_point_input_ids,
    point_domain_intent_output_types,
)
from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    ScanGroupIntent,
    ScanLeafIntent,
    inherit_default_scan_fields,
    iter_scan_leaves,
    replace_scan_group,
    scan_parameter_contracts,
    scan_point_id,
)
from scopecat.authoring._validation import validate_invocation_scans
from scopecat.authoring.scans import Scan
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.authoring.values import ModuleInput, module_input_is_valid
from scopecat.compiler.frontend.assembly_linking import (
    bind_verified_assembly,
)
from scopecat.compiler.frontend.assembly_verification import verify_assembly
from scopecat.compiler.frontend.elaboration import (
    SemanticExperimentIR,
    elaborate_module,
    merge_semantic_experiments,
)
from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.frontend.graph_validation import VerifiedAssembly
from scopecat.compiler.frontend.invocation import (
    InvocationRequestContext,
    PreparedInvocation,
)
from scopecat.compiler.frontend.problems import frontend_problem as _problem
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.scan_dependencies import (
    ScanDependencyError,
    VerifiedScanDependencyGraph,
    verify_scan_dependencies,
)
from scopecat.compiler.frontend.scan_lowering import (
    lower_scan_point_domain,
    project_scan_record,
)
from scopecat.compiler.relations.backend import ParameterRelationData
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointUnit,
    point_dependent_product,
    point_product,
)
from scopecat.compiler.typed.program import TypedProgram
from scopecat.compiler.typed.verification import VerifiedTypedProgram
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
    is_assignable,
    require_assignable,
)
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class ResolvedExperiment:
    verified_program: VerifiedTypedProgram
    request: RunRequest
    environment: ValidatedConfigEnvironment
    config_source: RunConfigSource | None = None

    @property
    def experiment(self) -> TypedProgram:
        return self.verified_program.program

    @property
    def template_id(self) -> str | None:
        return self.request.template_id

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.environment.config

    @property
    def parameters(self) -> ParameterRelationData:
        return self.environment.parameters

    @property
    def problems(self) -> tuple[Problem, ...]:
        return self.environment.problems


@dataclass(frozen=True, slots=True)
class CompiledInvocation:
    """Config-free result of compiling one prepared DSL invocation."""

    assembly: VerifiedAssembly
    request: RunRequest


@dataclass(frozen=True)
class _PointDomainFactor:
    """One indivisible domain in the scan/base composition DAG."""

    domain: PointDomainIntent
    axis_ids: frozenset[str]


def resolve_prepared_invocation(
    prepared: PreparedInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    compiled = compile_prepared_invocation(prepared)
    return resolve_compiled_invocation(
        compiled,
        environment=environment,
        config_source=config_source,
    )


def resolve_compiled_invocation(
    compiled: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    return link_assembly(
        compiled.assembly,
        request=compiled.request,
        environment=environment,
        config_source=config_source,
    )


def compile_prepared_invocation(
    prepared: PreparedInvocation,
) -> CompiledInvocation:
    invocation = prepared.invocation
    request_context = prepared.request_context
    scans = _effective_scans(invocation)
    inputs = _merged_inputs(invocation)
    compiled = _compile_invocation_template(invocation, inputs)
    _validate_invocation_inputs(
        invocation,
        compiled,
        inputs,
        scans=scans,
    )
    validate_invocation_scans(scans)
    request = _materialized_request(request_context, inputs=inputs, scans=scans)
    merged_inputs = {**compiled.inputs, **inputs}
    assembly = replace(
        compiled,
        inputs=merged_inputs,
    )
    _validate_point_dependencies(assembly, scans)
    assembly = apply_scans(
        assembly,
        scans,
        inputs=inputs,
    )
    return CompiledInvocation(
        assembly=verify_assembly(assembly),
        request=request,
    )


def _compile_invocation_template(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> SemanticExperimentIR:
    template = invocation.template
    if template.module is None:
        msg = "experiment template requires a module"
        raise ValueError(msg)
    exposed_inputs = {
        port.id: port.value_type for port in template.module.ir.interface.imports
    }
    module_inputs: dict[str, ModuleInput] = {}
    for input_id, value in inputs.items():
        if input_id not in exposed_inputs:
            continue
        if not module_input_is_valid(value):
            msg = f"module input {input_id!r} is not typed or closed literal data"
            raise TypeError(msg)
        module_inputs[input_id] = cast("ModuleInput", value)
    fragments = [elaborate_module(template.module, **module_inputs)]
    if template.record_selections:
        fragments.append(
            SemanticExperimentIR(
                entity_inputs=(),
                record_selections=template.record_selections,
            )
        )
    return merge_semantic_experiments(
        experiment_id=template.experiment_id or template.id,
        kind=template.kind or template.id,
        fragments=fragments,
        metadata=template.metadata,
    )


def _validate_invocation_inputs(
    invocation: ExperimentInvocation,
    assembly: SemanticExperimentIR,
    inputs: Mapping[str, object],
    *,
    scans: Sequence[Scan],
) -> None:
    allowed = {description.id for description in invocation.template.inputs} | {
        port.id for port in assembly.input_ports
    }
    unknown = sorted(set(inputs) - allowed)
    scan_inputs = {
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    }
    missing = [
        description.id
        for description in invocation.template.inputs
        if description.id not in inputs and description.id not in scan_inputs
    ]
    problems: list[Problem] = []
    if unknown:
        problems.append(
            _problem(
                "experiment_template_unknown_input",
                "experiment template received unknown input: " + ", ".join(unknown),
                "template",
                path=("inputs",),
            )
        )
    if missing:
        problems.append(
            _problem(
                "experiment_template_missing_input",
                "experiment template missing required input: " + ", ".join(missing),
                "template",
                path=("inputs",),
            )
        )
    if problems:
        raise CheckFailed(problems)


def link_assembly(
    assembly: VerifiedAssembly,
    *,
    request: RunRequest,
    environment: ValidatedConfigEnvironment,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    verified_program = bind_verified_assembly(assembly, environment)
    resolved_request = request.model_copy(
        update={
            "config_source": (
                config_source.selector
                if config_source is not None
                else request.config_source
            )
        }
    )
    return ResolvedExperiment(
        verified_program=verified_program,
        request=resolved_request,
        environment=environment,
        config_source=config_source,
    )


def _effective_scans(invocation: ExperimentInvocation) -> tuple[Scan, ...]:
    defaults = invocation.template.default_scans
    overrides = tuple(invocation.scans)
    override_axis_ids = [
        scan_point_id(leaf) for scan in overrides for leaf in iter_scan_leaves(scan)
    ]
    duplicate_overrides = sorted(
        {
            axis_id
            for axis_id in override_axis_ids
            if override_axis_ids.count(axis_id) > 1
        }
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
    if not defaults:
        _validate_group_override_shape((), overrides)
        return overrides
    default_axis_ids = {
        scan_point_id(leaf) for scan in defaults for leaf in iter_scan_leaves(scan)
    }
    _validate_group_override_shape(default_axis_ids, overrides)
    override_leaves = {
        scan_point_id(leaf): leaf
        for scan in overrides
        for leaf in iter_scan_leaves(scan)
        if scan_point_id(leaf) in default_axis_ids
    }
    replaced = tuple(_replace_scan_leaves(scan, override_leaves) for scan in defaults)
    covered = set(override_leaves)
    additions = tuple(
        scan
        for scan in overrides
        if not any(scan_point_id(leaf) in covered for leaf in iter_scan_leaves(scan))
    )
    return (*replaced, *additions)


def _replace_scan_leaves(
    scan: Scan,
    replacements: Mapping[str, ScanLeafIntent],
) -> Scan:
    if isinstance(scan, ScanGroupIntent):
        return replace_scan_group(
            scan,
            tuple(_replace_scan_leaves(child, replacements) for child in scan.scans),
        )
    if not isinstance(scan, PointScanIntent | ParameterScanIntent):
        msg = "invalid scan handle"
        raise TypeError(msg)
    replacement = replacements.get(scan_point_id(scan))
    if replacement is None:
        return scan
    return inherit_default_scan_fields(scan, replacement)


def _validate_group_override_shape(
    default_axis_ids: set[str] | tuple[()],
    overrides: Sequence[Scan],
) -> None:
    known = set(default_axis_ids)
    for scan in overrides:
        if not isinstance(scan, ScanGroupIntent):
            continue
        axis_ids = {scan_point_id(leaf) for leaf in iter_scan_leaves(scan)}
        existing = axis_ids & known
        if existing and existing != axis_ids:
            raise CheckFailed(
                [
                    _problem(
                        "scan_group_mixed_override",
                        (
                            "scan group cannot mix overridden default axes with "
                            "new axes: " + ", ".join(sorted(axis_ids))
                        ),
                        "scans",
                    )
                ]
            )


def _merged_inputs(
    invocation: ExperimentInvocation,
) -> dict[str, object]:
    merged: dict[str, object] = {
        input_description.id: input_description.default
        for input_description in invocation.template.inputs
        if input_description.has_default
    }
    merged.update(invocation.inputs)
    return merged


def _materialized_request(
    context: InvocationRequestContext,
    *,
    inputs: Mapping[str, object],
    scans: Sequence[Scan],
) -> RunRequest:
    template_inputs = project_run_request_inputs(context.template_inputs)
    template_inputs.update(project_run_request_inputs(inputs))
    request_scans = list(context.scans)
    for scan in scans:
        request_scans.append(project_scan_record(scan, inputs=inputs))
    return RunRequest.model_validate(
        {
            "id": context.id,
            "template_id": context.template_id,
            "template_inputs": template_inputs,
            "scans": request_scans,
            "operator": context.operator,
            "metadata": dict(context.metadata),
        }
    )


def apply_scans(
    assembly: SemanticExperimentIR,
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> SemanticExperimentIR:
    _validate_scans(scans)
    _validate_scan_target_types(assembly, scans)
    try:
        dependency_graph = verify_scan_dependencies(
            scans,
            inputs=inputs,
            input_types={port.id: port.value_type for port in assembly.input_ports},
            external_point_types=point_domain_intent_output_types(
                assembly.point_domain
            ),
        )
    except ScanDependencyError as error:
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
    point_domain = _ordered_point_domain(
        assembly,
        dependency_graph,
        inputs=inputs,
    )
    return replace(
        assembly,
        point_domain=point_domain,
        parameter_contracts=merge_parameter_contracts(
            assembly.parameter_contracts,
            *(scan_parameter_contracts(scan) for scan in scans),
        ),
        parameter_overlays=(
            *assembly.parameter_overlays,
            *tuple(
                _runtime_parameter_overlay_intent(scan)
                for root in scans
                for scan in iter_scan_leaves(root)
                if isinstance(scan, ParameterScanIntent)
            ),
        ),
    )


def _ordered_point_domain(
    assembly: SemanticExperimentIR,
    graph: VerifiedScanDependencyGraph,
    *,
    inputs: Mapping[str, object],
) -> PointDomainIntent:
    """Topologically compose scans and the base domain as peer factors."""

    dependency_edges = frozenset(
        (edge.producer_id, edge.consumer_id) for edge in graph.edges
    )
    scan_factors = [
        _PointDomainFactor(
            domain=lower_scan_point_domain(
                scan,
                inputs=inputs,
                dependency_edges=dependency_edges,
            ),
            axis_ids=frozenset(scan_point_id(leaf) for leaf in iter_scan_leaves(scan)),
        )
        for scan in graph.scans
    ]
    base_domain = assembly.point_domain
    base_types = point_domain_intent_output_types(base_domain)
    base_requirements = _point_domain_requirements(assembly, inputs=inputs)
    scan_factor_by_axis = {
        axis_id: factor_index
        for factor_index, factor in enumerate(scan_factors)
        for axis_id in factor.axis_ids
    }
    provider_types = {
        **base_types,
        **{axis.id: axis.value_type for axis in graph.axes},
    }
    requirement_providers: dict[str, int] = {}
    requirement_problems: list[Problem] = []
    for dependency_id, required_type in sorted(base_requirements.items()):
        if dependency_id in base_types:
            requirement_problems.append(
                _problem(
                    "scan_dependency_self",
                    f"base point domain depends on its own point {dependency_id!r}",
                    "point_domain",
                )
            )
            continue
        provider_factor = scan_factor_by_axis.get(dependency_id)
        provider_type = provider_types.get(dependency_id)
        if provider_factor is None or provider_type is None:
            requirement_problems.append(
                _problem(
                    "scan_dependency_missing",
                    "base point domain depends on missing scanned point "
                    f"{dependency_id!r}",
                    "point_domain",
                )
            )
            continue
        if required_type is None:
            requirement_problems.append(
                _problem(
                    "scan_dependency_type_unknown",
                    "base point domain depends on scanned point "
                    f"{dependency_id!r} without a scalar type",
                    "point_domain",
                )
            )
            continue
        if not is_assignable(provider_type, required_type):
            requirement_problems.append(
                _problem(
                    "scan_dependency_type_mismatch",
                    "base point domain requires scanned point "
                    f"{dependency_id!r} with an incompatible value type",
                    "point_domain",
                )
            )
        requirement_providers[dependency_id] = provider_factor
    if requirement_problems:
        raise CheckFailed(requirement_problems)

    factors = list(scan_factors)
    base_factor: int | None = None
    if not isinstance(base_domain, PointUnit):
        insertion_index = (
            max(requirement_providers.values()) + 1 if requirement_providers else 0
        )
        factors.insert(
            insertion_index,
            _PointDomainFactor(
                domain=base_domain,
                axis_ids=frozenset(base_types),
            ),
        )
        base_factor = insertion_index
    if not factors:
        return POINT_UNIT

    factor_by_axis = {
        axis_id: factor_index
        for factor_index, factor in enumerate(factors)
        for axis_id in factor.axis_ids
    }
    required_factors = {index: set[int]() for index in range(len(factors))}
    for edge in graph.edges:
        producer = factor_by_axis[edge.producer_id]
        consumer = factor_by_axis[edge.consumer_id]
        if producer != consumer:
            required_factors[consumer].add(producer)
    for dependency_id in base_requirements:
        producer = factor_by_axis[dependency_id]
        if base_factor is not None and producer != base_factor:
            required_factors[base_factor].add(producer)

    remaining = {
        factor_index: set(required)
        for factor_index, required in required_factors.items()
    }
    ordered: list[int] = []
    while remaining:
        ready = [
            factor_index for factor_index, required in remaining.items() if not required
        ]
        if not ready:
            raise CheckFailed(
                [
                    _problem(
                        "scan_dependency_composition_cycle",
                        "scans and the base point domain form a dependency cycle",
                        "point_domain",
                    )
                ]
            )
        next_factor = min(ready)
        ordered.append(next_factor)
        del remaining[next_factor]
        for required in remaining.values():
            required.discard(next_factor)

    domain: PointDomainIntent = POINT_UNIT
    for factor_index in ordered:
        factor = factors[factor_index]
        domain = (
            point_dependent_product(domain, factor.domain)
            if required_factors[factor_index]
            else point_product(domain, factor.domain)
        )
    return domain


def _point_domain_requirements(
    assembly: SemanticExperimentIR,
    *,
    inputs: Mapping[str, object],
) -> dict[str, Scalar | None]:
    requirements: dict[str, Scalar | None] = {
        dependency.id: dependency.value_type
        for dependency in point_domain_intent_free_point_dependencies(
            assembly.point_domain
        )
    }
    input_types = {port.id: port.value_type for port in assembly.input_ports}
    free_scalar_inputs = (
        point_domain_intent_free_point_input_ids(assembly.point_domain) - inputs.keys()
    )
    for input_id in free_scalar_inputs:
        value_type = input_types.get(input_id)
        requirements.setdefault(
            input_id,
            value_type if isinstance(value_type, Scalar) else None,
        )
    return requirements


def _validate_scans(scans: Sequence[Scan]) -> None:
    axis_ids = [
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    ]
    duplicates = sorted(
        {axis_id for axis_id in axis_ids if axis_ids.count(axis_id) > 1}
    )
    if duplicates:
        raise CheckFailed(
            [
                _problem(
                    "scan_axis_duplicate",
                    "duplicate scan axis: " + ", ".join(duplicates),
                    "scans",
                )
            ]
        )


def _validate_scan_target_types(
    assembly: SemanticExperimentIR,
    scans: Sequence[Scan],
) -> None:
    input_types = {port.id: port.value_type for port in assembly.input_ports}
    for root in scans:
        for scan in iter_scan_leaves(root):
            expected = input_types.get(scan_point_id(scan))
            if expected is None:
                continue
            input_id = scan_point_id(scan)
            try:
                require_assignable(
                    scan.target.value_type,
                    expected,
                    path=("scans", input_id),
                )
            except ValueValidationError as error:
                raise CheckFailed(
                    [
                        _problem(
                            "module_input_type_mismatch",
                            str(error),
                            "scans",
                            path=(input_id,),
                        )
                    ]
                ) from error


def _validate_point_dependencies(
    assembly: SemanticExperimentIR,
    scans: Sequence[Scan],
) -> None:
    point_types = {
        **point_domain_intent_output_types(assembly.point_domain),
        **{
            scan_point_id(scan): scan.target.value_type
            for root in scans
            for scan in iter_scan_leaves(root)
        },
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


def _runtime_parameter_overlay_intent(
    scan: ParameterScanIntent,
) -> ParameterScanOverlayIntent:
    return ParameterScanOverlayIntent(
        table_id=scan.table_id,
        key=scan.key,
        column_id=scan.column,
        point_id=scan.point_id,
    )


__all__ = [
    "CompiledInvocation",
    "ResolvedExperiment",
    "compile_prepared_invocation",
    "resolve_compiled_invocation",
    "resolve_prepared_invocation",
]
