"""Compile authoring invocations into canonical core programs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from scopecat.authoring._intents import ParameterScanOverlayIntent
from scopecat.authoring._parameter_contracts import merge_parameter_contracts
from scopecat.authoring._point_domain_intents import (
    PointDomainIntent,
    iter_point_domain_value_refs,
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
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_point_value_ref,
    internal_value_ref_scalar_input_ids,
)
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
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointUnit,
    point_dependent_product,
    point_product,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import VerifiedCoreProgram
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
from scopecat.records.run import ConfigRegistryRunConfigSource, RunConfigSource
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class ResolvedExperiment:
    verified_program: VerifiedCoreProgram
    request: RunRequest
    environment: ValidatedConfigEnvironment
    config_source: RunConfigSource | None = None

    @property
    def experiment(self) -> CoreProgram:
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
    request = _materialized_request(
        request_context,
        inputs=inputs,
        scans=scans,
        base_point_domain=compiled.point_domain,
    )
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
    fragments = [
        elaborate_module(
            template.module,
            **module_inputs,
        )
    ]
    if template.record_selections:
        fragments.append(
            SemanticExperimentIR(
                entity_inputs=(),
                record_selections=template.record_selections,
            )
        )
    return merge_semantic_experiments(
        experiment_id=template.id,
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
                if isinstance(config_source, ConfigRegistryRunConfigSource)
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
    base_point_domain: PointDomainIntent,
) -> RunRequest:
    template_inputs = project_run_request_inputs(context.template_inputs)
    template_inputs.update(project_run_request_inputs(inputs))
    projection_inputs = {
        **_point_provider_inputs(base_point_domain, scans),
        **inputs,
    }
    request_scans = list(context.scans)
    for scan in scans:
        request_scans.append(project_scan_record(scan, inputs=projection_inputs))
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
    consumed_point_input_ids = _consumed_point_input_ids(
        assembly,
        dependency_graph.scans,
        inputs=inputs,
    )
    point_inputs = {
        input_id: target
        for input_id, target in _point_provider_inputs(
            assembly.point_domain,
            dependency_graph.scans,
        ).items()
        if input_id in consumed_point_input_ids and input_id not in assembly.inputs
    }
    return replace(
        assembly,
        inputs={**assembly.inputs, **point_inputs},
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


def _scan_axis_inputs(scans: Sequence[Scan]) -> dict[str, ValueRef]:
    """Map each scanned coordinate to its explicit point-value handle."""

    return {
        scan_point_id(leaf): internal_point_value_ref(
            scan_point_id(leaf),
            cast("Scalar", leaf.target.value_type),
        )
        for root in scans
        for leaf in iter_scan_leaves(root)
    }


def _point_provider_inputs(
    base_point_domain: PointDomainIntent,
    scans: Sequence[Scan],
) -> dict[str, ValueRef]:
    """Map every base or scan coordinate to one explicit point-value handle."""

    base_inputs = {
        point_id: internal_point_value_ref(point_id, value_type)
        for point_id, value_type in point_domain_intent_output_types(
            base_point_domain
        ).items()
    }
    return {**base_inputs, **_scan_axis_inputs(scans)}


def _consumed_point_input_ids(
    assembly: SemanticExperimentIR,
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> set[str]:
    """Return point providers consumed through relation input syntax."""

    consumed = {port.id for port in assembly.input_ports}
    domains = (
        assembly.point_domain,
        *(lower_scan_point_domain(scan, inputs=inputs) for scan in scans),
    )
    consumed.update(
        input_id
        for domain in domains
        for _path, center in iter_point_domain_value_refs(domain)
        for input_id in internal_value_ref_scalar_input_ids(center)
    )
    return consumed


def _ordered_point_domain(
    assembly: SemanticExperimentIR,
    graph: VerifiedScanDependencyGraph,
    *,
    inputs: Mapping[str, object],
) -> PointDomainIntent:
    """Schedule every Cartesian region once, including the base-domain region."""

    dependency_edges = frozenset(
        (edge.producer_id, edge.consumer_id) for edge in graph.edges
    )
    normalized_scans = _scan_product_factors(graph.scans, graph=graph)
    scan_factors = [
        _PointDomainFactor(
            domain=lower_scan_point_domain(
                scan,
                inputs=inputs,
                dependency_edges=dependency_edges,
            ),
            axis_ids=frozenset(scan_point_id(leaf) for leaf in iter_scan_leaves(scan)),
        )
        for scan in normalized_scans
    ]
    base_domain = assembly.point_domain
    base_types = point_domain_intent_output_types(base_domain)
    base_requirements = _point_domain_requirements(assembly, inputs=inputs)
    provider_types = {
        **base_types,
        **{axis.id: axis.value_type for axis in graph.axes},
    }
    scan_axis_ids = {axis_id for factor in scan_factors for axis_id in factor.axis_ids}
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
        provider_type = provider_types.get(dependency_id)
        if dependency_id not in scan_axis_ids or provider_type is None:
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
    if requirement_problems:
        raise CheckFailed(requirement_problems)

    # The base domain is the implicit first authored factor. If it depends on a
    # scan it remains blocked until that producer is ready; its stable ordinal
    # makes it the first factor among otherwise-ready peers.
    factors: list[_PointDomainFactor] = []
    base_factor: int | None = None
    if not isinstance(base_domain, PointUnit):
        base_factor = 0
        factors.append(
            _PointDomainFactor(
                domain=base_domain,
                axis_ids=frozenset(base_types),
            ),
        )
    factors.extend(scan_factors)
    if not factors:
        return POINT_UNIT

    axis_sets = tuple(factor.axis_ids for factor in factors)
    required_factors = _factor_dependencies(axis_sets, dependency_edges)
    factor_by_axis = _factor_by_axis(axis_sets)
    for dependency_id in base_requirements:
        producer = factor_by_axis[dependency_id]
        if base_factor is not None and producer != base_factor:
            required_factors[base_factor].add(producer)

    ordered, blocked = _stable_factor_order(required_factors)
    if blocked:
        if base_factor is not None and _factor_is_in_cycle(
            base_factor,
            required_factors,
        ):
            raise CheckFailed(
                [
                    _problem(
                        "scan_dependency_composition_cycle",
                        "scans and the base point domain form a dependency cycle",
                        "point_domain",
                    )
                ]
            )
        _raise_scan_composition_cycle(
            axis_sets,
            blocked,
            graph=graph,
        )

    domain: PointDomainIntent = POINT_UNIT
    for factor_index in ordered:
        factor = factors[factor_index]
        domain = (
            point_dependent_product(domain, factor.domain)
            if required_factors[factor_index]
            else point_product(domain, factor.domain)
        )
    return domain


def _scan_product_factors(
    scans: Sequence[Scan],
    *,
    graph: VerifiedScanDependencyGraph,
) -> tuple[Scan, ...]:
    """Flatten one Cartesian region without scheduling its parent region."""

    factors: list[Scan] = []
    for scan in scans:
        if isinstance(scan, ScanGroupIntent) and scan.kind == "cartesian":
            factors.extend(_scan_product_factors(scan.scans, graph=graph))
            continue
        factors.append(_normalize_nested_scan(scan, graph=graph))
    return tuple(factors)


def _normalize_nested_scan(
    scan: Scan,
    *,
    graph: VerifiedScanDependencyGraph,
) -> Scan:
    """Schedule Cartesian regions nested below an indivisible zip boundary."""

    if not isinstance(scan, ScanGroupIntent):
        return scan
    if scan.kind == "zip":
        return replace_scan_group(
            scan,
            tuple(_normalize_nested_scan(child, graph=graph) for child in scan.scans),
        )

    factors = _scan_product_factors(scan.scans, graph=graph)
    axis_sets = tuple(_scan_axis_ids(factor) for factor in factors)
    required = _factor_dependencies(
        axis_sets,
        ((edge.producer_id, edge.consumer_id) for edge in graph.edges),
    )
    ordered, blocked = _stable_factor_order(required)
    if blocked:
        _raise_scan_composition_cycle(axis_sets, blocked, graph=graph)
    selected = tuple(factors[index] for index in ordered)
    if len(selected) == 1:
        return selected[0]
    return replace_scan_group(scan, selected)


def _scan_axis_ids(scan: Scan) -> frozenset[str]:
    return frozenset(scan_point_id(leaf) for leaf in iter_scan_leaves(scan))


def _factor_by_axis(
    axis_sets: Sequence[frozenset[str]],
) -> dict[str, int]:
    return {
        axis_id: factor_index
        for factor_index, axis_ids in enumerate(axis_sets)
        for axis_id in axis_ids
    }


def _factor_dependencies(
    axis_sets: Sequence[frozenset[str]],
    dependency_edges: Iterable[tuple[str, str]],
) -> dict[int, set[int]]:
    factor_by_axis = _factor_by_axis(axis_sets)
    required = {index: set[int]() for index in range(len(axis_sets))}
    for producer_id, consumer_id in dependency_edges:
        producer = factor_by_axis.get(producer_id)
        consumer = factor_by_axis.get(consumer_id)
        if producer is not None and consumer is not None and producer != consumer:
            required[consumer].add(producer)
    return required


def _stable_factor_order(
    required_factors: Mapping[int, set[int]],
) -> tuple[tuple[int, ...], frozenset[int]]:
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
            return tuple(ordered), frozenset(remaining)
        next_factor = min(ready)
        ordered.append(next_factor)
        del remaining[next_factor]
        for required in remaining.values():
            required.discard(next_factor)
    return tuple(ordered), frozenset()


def _factor_is_in_cycle(
    factor_index: int,
    required_factors: Mapping[int, set[int]],
) -> bool:
    pending = list(required_factors[factor_index])
    visited: set[int] = set()
    while pending:
        required = pending.pop()
        if required == factor_index:
            return True
        if required in visited:
            continue
        visited.add(required)
        pending.extend(required_factors[required])
    return False


def _raise_scan_composition_cycle(
    axis_sets: Sequence[frozenset[str]],
    blocked: frozenset[int],
    *,
    graph: VerifiedScanDependencyGraph,
) -> None:
    axes_by_id = {axis.id: axis for axis in graph.axes}
    involved = sorted(
        {
            axis_id
            for factor_index in blocked
            for axis_id in axis_sets[factor_index]
            if axis_id in axes_by_id
        },
        key=lambda item: (axes_by_id[item].declaration_ordinal, item),
    )
    first = involved[0]
    raise CheckFailed(
        [
            _problem(
                "scan_dependency_composition_cycle",
                "scan groups cannot be ordered without splitting a positional "
                "composition: " + ", ".join(involved),
                "scans",
                path=axes_by_id[first].path,
            )
        ]
    )


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
