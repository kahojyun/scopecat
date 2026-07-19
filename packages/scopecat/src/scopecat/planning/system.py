"""Compile linked experiment semantics into the sole executable RunProgram."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    LinkedPointMaterializer,
    MaterializedLinkedPoints,
)
from scopecat.compiler.typed.domain_results import (
    DomainResultClosure,
    domain_result_closure,
)
from scopecat.compiler.typed.effect_dependencies import analyze_effect_barriers
from scopecat.compiler.typed.program import (
    TypedMeasurementTransform,
    core_actions,
    core_domain_executions,
    core_state,
)
from scopecat.execution.local.executor import (
    preflight_instrument_provider,
    validate_run_host_binding,
)
from scopecat.execution.local.program import (
    CollectStage,
    ComputeOperation,
    ComputeStage,
    PointProgram,
)
from scopecat.execution.program import (
    RunComputeStage,
    RunDomainJob,
    RunHostBinding,
    RunOperation,
    RunPointEnd,
    RunPointLoop,
    RunPointStage,
    RunPointStart,
    RunProgram,
    run_point_start,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements._bridge import project_measurement_catalog
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.local_materialization import materialize_local_execution
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_request,
)
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiler,
    DomainCompileRequest,
    validate_domain_compilation,
)
from scopecat.sdk.instruments.contracts import InstrumentProvider


@dataclass(frozen=True, slots=True)
class ExperimentSystem:
    """One explicit experiment system for point and domain execution."""

    provider: InstrumentProvider | None = field(default=None, repr=False)
    domain_compiler: DomainCompiler | None = field(default=None, repr=False)
    max_materialized_points: int = 100_000

    def __post_init__(self) -> None:
        if (
            type(self.max_materialized_points) is not int
            or self.max_materialized_points <= 0
        ):
            raise ValueError("max_materialized_points must be a positive integer")
        if self.provider is None and self.domain_compiler is None:
            msg = "experiment system requires a provider or domain compiler"
            raise ValueError(msg)

    def compile(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
    ) -> RunProgram:
        linked_config_hash = config_content_hash(linked.environment.config)
        execution_config_hash = config_content_hash(config)
        if linked_config_hash != execution_config_hash:
            raise CheckFailed(
                [
                    blocking_problem(
                        "execution_config_snapshot_mismatch",
                        (
                            "execution config does not match the snapshot bound "
                            "to the linked plan"
                        ),
                        category=ProblemCategory.INVALID_INPUT,
                        phase=ProblemPhase.PLANNING,
                        location=model_location("execution", "config"),
                        details={
                            "linked_config_content_hash": linked_config_hash,
                            "execution_config_content_hash": execution_config_hash,
                        },
                    )
                ]
            )
        return _compile_system_program(
            system=self,
            linked=linked,
            config=config,
        )


def _compile_system_program(
    *,
    system: ExperimentSystem,
    linked: LinkedPlan,
    config: ConfigProfileSnapshot,
) -> RunProgram:
    domain_result_closures = {
        execution.id: domain_result_closure(linked.program, execution.id)
        for execution in core_domain_executions(linked.program)
    }
    domain_owned_product_use_ids = frozenset(
        use_id
        for result_closure in domain_result_closures.values()
        for use_id in result_closure.product_use_ids
    )
    local_product_use_ids = tuple(
        use.id
        for use in linked.program.product_uses
        if use.id not in domain_owned_product_use_ids
    )
    local_required = bool(
        local_product_use_ids
        or linked.program.route_intents
        or linked.program.compute_nodes
        or core_state(linked.program)
        or core_actions(linked.program)
    )
    unimplemented_transforms = tuple(
        transform
        for transform in linked.program.measurement_transforms
        if all(
            transform not in result_closure.transforms
            for result_closure in domain_result_closures.values()
        )
    )
    implementation_problems = list(
        _implementation_problems(
            has_domain_call=bool(core_domain_executions(linked.program)),
            has_domain_compiler=system.domain_compiler is not None,
            local_required=local_required,
            has_local_provider=system.provider is not None,
            unimplemented_transforms=unimplemented_transforms,
        )
    )
    if implementation_problems:
        raise CheckFailed(implementation_problems)
    lazy_points = LinkedPointMaterializer(
        linked,
        max_points=system.max_materialized_points,
    )
    barrier_ordinals = _plan_barrier_ordinals(
        lazy_points.point_count(),
        requires_single_point_regions=(
            local_required
            and analyze_effect_barriers(linked.program).requires_single_point_regions
        ),
    )
    compiled_domains = tuple(
        compiled
        for execution in core_domain_executions(linked.program)
        if (
            compiled := _compile_domain_execution(
                system.domain_compiler,
                linked,
                barrier_ordinals,
                lazy_points=lazy_points,
                execution_id=execution.id,
                result_closure=domain_result_closures[execution.id],
            )
        )
        is not None
    )
    problems: list[Problem] = []
    compiled_execution_ids = {compiled.request.call.id for compiled in compiled_domains}
    problems.extend(
        _planning_problem(
            "domain_compiler_missing",
            f"the experiment system cannot compile domain call {execution.id!r}",
            category=ProblemCategory.NOT_FOUND,
            details={"execution_id": execution.id},
        )
        for execution in core_domain_executions(linked.program)
        if execution.id not in compiled_execution_ids
    )
    if problems:
        raise CheckFailed(problems)

    linked_points = lazy_points.materialize()
    (
        local_effects,
        local_points,
        local_run_compute_operations,
        local_resource_claims,
    ) = _prepare_local_effects(
        system,
        linked_points,
        config=config,
        product_use_ids=local_product_use_ids,
        required=local_required,
    )
    barrier_regions = barrier_ordinals
    domain_jobs = tuple(
        job
        for compiled in compiled_domains
        for job in _prepare_domain_jobs(
            compiled,
            linked_points,
        )
    )
    jobs_by_region: dict[int, list[RunDomainJob]] = {
        region_ordinal: [] for region_ordinal, _region in enumerate(barrier_regions)
    }
    for job in domain_jobs:
        region_ordinal = next(
            ordinal
            for ordinal, region in enumerate(barrier_regions)
            if job.point_ordinals[0] in region
        )
        jobs_by_region[region_ordinal].append(job)
    point_operations = _ordered_run_operations(
        local_points,
        barrier_regions=barrier_regions,
        jobs_by_region=jobs_by_region,
    )
    operations: tuple[RunOperation, ...] = (
        *(
            (RunComputeStage(ComputeStage(local_run_compute_operations)),)
            if local_run_compute_operations
            else ()
        ),
        *point_operations,
    )
    measurement_catalog = project_measurement_catalog(linked_points)
    measurements = select_measurement_projection(
        measurement_catalog,
        linked.record_uses,
    )
    resource_claims = tuple(
        sorted(
            {
                *local_resource_claims,
                *(claim for job in domain_jobs for claim in job.resource_claims),
            },
            key=lambda claim: (claim.kind, claim.id),
        )
    )
    return RunProgram(
        host=local_effects,
        operations=operations,
        measurements=measurements,
        resource_claims=resource_claims,
    )


@dataclass(frozen=True, slots=True)
class _CompiledDomainExecution:
    request: DomainCompileRequest = field(repr=False)
    compiler: DomainCompiler = field(repr=False, compare=False)
    compilation: DomainCompilation = field(repr=False)


def _compile_domain_execution(
    compiler: DomainCompiler | None,
    linked: LinkedPlan,
    barrier_regions: tuple[tuple[int, ...], ...],
    *,
    lazy_points: LinkedPointMaterializer,
    execution_id: str,
    result_closure: DomainResultClosure,
) -> _CompiledDomainExecution | None:
    if compiler is None:
        return None
    request = make_domain_compile_request(
        linked,
        execution_id,
        result_closure,
        barrier_regions,
        lambda input_ids, ordinals, max_points: lazy_points.bind_domain_inputs(
            execution_id,
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    compilation = compiler.compile(request)
    if compilation is None:
        return None
    validate_domain_compilation(request, compilation)
    return _CompiledDomainExecution(
        request=request,
        compiler=compiler,
        compilation=compilation,
    )


def _prepare_local_effects(
    system: ExperimentSystem,
    linked_points: MaterializedLinkedPoints,
    *,
    config: ConfigProfileSnapshot,
    product_use_ids: tuple[ProductUseId, ...],
    required: bool,
) -> tuple[
    RunHostBinding | None,
    tuple[PointProgram, ...],
    tuple[ComputeOperation, ...],
    tuple[ResourceClaim, ...],
]:
    if not required:
        return None, (), (), ()
    if system.provider is None:
        raise AssertionError(
            "local placement must require a provider before materialization"
        )
    preflight = preflight_instrument_provider(
        config=config,
        instrument_provider=system.provider,
    )
    local_execution = materialize_local_execution(
        linked_points,
        product_use_ids=frozenset(product_use_ids),
        instrument_order=preflight.instrument_order,
    )
    host = RunHostBinding(
        resource_order=local_execution.resource_order,
        provider_id=preflight.provider_id,
        instrument_order=preflight.instrument_order,
        advertised_descriptions=preflight.advertised_descriptions,
    )
    return (
        validate_run_host_binding(
            program=host,
            points=local_execution.points,
            problems=preflight.problems,
        ),
        local_execution.points,
        local_execution.run_compute_operations,
        local_execution.resource_claims,
    )


def _plan_barrier_ordinals(
    point_count: int,
    *,
    requires_single_point_regions: bool,
) -> tuple[tuple[int, ...], ...]:
    if not point_count:
        return ()
    if not requires_single_point_regions:
        return (tuple(range(point_count)),)
    return tuple((point_index,) for point_index in range(point_count))


def _ordered_run_operations(
    points: tuple[PointProgram, ...],
    *,
    barrier_regions: tuple[tuple[int, ...], ...],
    jobs_by_region: dict[int, list[RunDomainJob]],
) -> tuple[RunOperation, ...]:
    """Write the complete host/domain order into the residual program."""

    if not points:
        return tuple(
            job
            for region_ordinal in range(len(barrier_regions))
            for job in jobs_by_region[region_ordinal]
        )
    if not any(jobs_by_region.values()):
        return (RunPointLoop(points),)

    operations: list[RunOperation] = []
    for region_ordinal, region in enumerate(barrier_regions):
        for point_index in region:
            point = points[point_index]
            operations.extend(_point_prefix_operations(point))
        operations.extend(jobs_by_region[region_ordinal])
        for point_index in region:
            point = points[point_index]
            operations.extend(_point_suffix_operations(point))
    return tuple(operations)


def _point_start(point: PointProgram) -> RunPointStart:
    return run_point_start(point)


def _point_prefix_operations(point: PointProgram) -> tuple[RunOperation, ...]:
    return (
        _point_start(point),
        *(
            RunPointStage(point.point_index, stage)
            for stage in point.stages
            if not isinstance(stage, CollectStage)
        ),
    )


def _point_suffix_operations(point: PointProgram) -> tuple[RunOperation, ...]:
    return (
        *(
            RunPointStage(point.point_index, stage)
            for stage in point.stages
            if isinstance(stage, CollectStage)
        ),
        RunPointEnd(point.point_index),
    )


def _prepare_domain_jobs(
    domain: _CompiledDomainExecution,
    linked_points: MaterializedLinkedPoints,
) -> tuple[RunDomainJob, ...]:
    jobs: list[RunDomainJob] = []
    execution_id = domain.request.call.id
    for batch_ordinal, compiled in enumerate(domain.compilation.jobs):
        context = make_domain_batch_context(
            domain.request,
            linked_points,
            compiled.point_ordinals,
            batch_ordinal=batch_ordinal,
            absorbed_input_ids=domain.compilation.absorbed_input_ids,
            absorbed_transform_ids=domain.compilation.absorbed_transform_ids,
        )
        prepared = domain.compiler.prepare(compiled, context)
        resource_claims = tuple(
            dict.fromkeys((*compiled.resource_claims, *prepared.resource_claims))
        ) or (
            ResourceClaim(
                prepared.invocation.intent.target_id,
                "target",
            ),
        )
        prepared = replace(prepared, resource_claims=resource_claims)
        jobs.append(
            RunDomainJob(
                id=f"{execution_id}:{compiled.id}",
                point_ordinals=compiled.point_ordinals,
                prepared=prepared,
            )
        )
    return tuple(jobs)


def _implementation_problems(
    *,
    has_domain_call: bool,
    has_domain_compiler: bool,
    local_required: bool,
    has_local_provider: bool,
    unimplemented_transforms: tuple[TypedMeasurementTransform, ...],
) -> tuple[Problem, ...]:
    """Report missing effect/dataflow implementations directly from typed edges."""

    problems: list[Problem] = []
    if has_domain_call and not has_domain_compiler:
        problems.append(
            _planning_problem(
                "domain_compiler_missing",
                "the typed domain call has no configured compiler",
                category=ProblemCategory.NOT_FOUND,
            )
        )
    if local_required and not has_local_provider:
        problems.append(
            _planning_problem(
                "local_instrument_provider_missing",
                "local effects or products require an instrument provider",
                category=ProblemCategory.NOT_FOUND,
            )
        )
    problems.extend(
        _planning_problem(
            "measurement_transform_implementation_missing",
            f"measurement transform {transform.id.qualified_name!r} has no "
            "execution implementation; a transform must belong to a supported "
            "domain-call closure",
            details={
                "transform_id": transform.id.qualified_name,
                "input_product_ids": [
                    port.product_id.qualified_name for port in transform.inputs
                ],
                "output_product_use_ids": [
                    use_id.value
                    for output in transform.outputs
                    for use_id in output.product_use_ids
                ],
            },
        )
        for transform in unimplemented_transforms
    )
    return tuple(problems)


def _planning_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory = ProblemCategory.UNAVAILABLE,
    details: dict[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.PLANNING,
        location=model_location("experiment_system"),
        details=details or {},
    )
