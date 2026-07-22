"""Compile linked experiment semantics for one physical experiment system.

This boundary coordinates local target selection, domain lowering, ordered
resource barriers, and bounded coverage so placement decisions share one view
of effect order and resource ownership. Its output is the closed ``RunProgram``
accepted by execution.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    LinkedPointMaterializer,
    MaterializedLinkedPoints,
)
from scopecat.compiler.typed.domain_results import (
    domain_result_closure,
)
from scopecat.compiler.typed.program import (
    CoreEffect,
    TypedDomainExecution,
    TypedMeasurementTransform,
    core_actions,
    core_domain_executions,
    core_state,
)
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
)
from scopecat.execution.points import RunPoint, RunPointCatalog
from scopecat.execution.program import (
    RunCompute,
    RunCoverageBlock,
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
    RunHostBinding,
    RunProgram,
)
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements._bridge import (
    project_measurement_catalog_from_domain,
    project_run_point_catalog_from_domain,
)
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.local_effects import (
    LocalTargetPlan,
    MaterializedLocalEffects,
    local_operation_resource_claims,
)
from scopecat.planning.local_materialization import (
    materialize_local_execution,
    prepare_local_target,
)
from scopecat.planning.provider_binding import (
    InstrumentProviderPreflight,
    preflight_instrument_provider,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_template,
)
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledJob,
    DomainCompiler,
    DomainCompileRequest,
    DomainCompileTemplate,
    DomainInputBinder,
    validate_domain_compilation,
)
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import InstrumentProvider


@dataclass(frozen=True, slots=True)
class ExperimentSystem:
    """The physical capabilities used to lower one experiment definition.

    Pairing the host provider with an optional domain compiler lets the same
    experiment definition be lowered against one coherent capability and
    resource environment. ``compile`` remains free of provider effects and
    uses the same configuration snapshot accepted during linking. The singular
    domain compiler owns dispatch for every supported domain program in that
    environment; lower-level target compilers remain its implementation detail.
    """

    provider: InstrumentProvider | None = field(default=None, repr=False)
    domain_compiler: DomainCompiler | None = field(default=None, repr=False)
    coverage_block_size: int = 100_000

    def __post_init__(self) -> None:
        if type(self.coverage_block_size) is not int or self.coverage_block_size <= 0:
            raise ValueError("coverage_block_size must be a positive integer")
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
    domain_templates = {
        execution_id: make_domain_compile_template(
            linked,
            execution_id,
            result_closure,
        )
        for execution_id, result_closure in domain_result_closures.items()
    }
    domain_footprint = _domain_target_footprint(
        system,
        config=config,
        templates=domain_templates,
    )
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
        block_size=system.coverage_block_size,
    )
    point_count = linked.point_domain.cardinality
    point_domain = lazy_points.materialize_point_domain()
    measurement_catalog = project_measurement_catalog_from_domain(
        linked,
        point_domain,
    )
    point_catalog = project_run_point_catalog_from_domain(linked, point_domain)
    measurements = select_measurement_projection(
        measurement_catalog,
        linked.program.record_uses,
    )
    preflight = (
        preflight_instrument_provider(
            config=config,
            instrument_provider=system.provider,
        )
        if local_required and system.provider is not None
        else None
    )
    if preflight is not None and has_blocking_problems(preflight.problems):
        raise ProviderContractError(preflight.problems)
    host = _host_binding(preflight)
    host_resource_claims = (
        ()
        if preflight is None
        else tuple(ResourceClaim(item) for item in preflight.instrument_order)
    )
    resource_claims = _sorted_claims((*host_resource_claims, *domain_footprint))
    local_target = (
        prepare_local_target(
            linked,
            product_use_ids=frozenset(local_product_use_ids),
            instrument_order=preflight.instrument_order
            if preflight is not None
            else (),
        )
        if local_required
        else None
    )
    outer_regions = tuple(
        tuple(range(start, min(start + system.coverage_block_size, point_count)))
        for start in range(0, point_count, system.coverage_block_size)
    )

    def materialize_region(
        region: tuple[int, ...],
    ) -> tuple[RunCoverageBlock, ...]:
        return _compile_coverage_region(
            system=system,
            linked=linked,
            lazy_points=lazy_points,
            point_catalog=point_catalog,
            region=region,
            point_count=point_count,
            domain_templates=domain_templates,
            domain_footprint=domain_footprint,
            local_target=local_target,
            run_resource_claims=frozenset(resource_claims),
        )

    def coverage() -> Iterator[RunCoverageBlock]:
        for region in outer_regions:
            yield from materialize_region(region)

    return RunProgram(
        host=host,
        preamble=tuple(
            RunCompute(operation)
            for operation in (
                () if local_target is None else local_target.run_operations
            )
        ),
        coverage=coverage(),
        points=point_catalog,
        measurements=measurements,
        resource_claims=resource_claims,
    )


def _host_binding(
    preflight: InstrumentProviderPreflight | None,
) -> RunHostBinding | None:
    if preflight is None:
        return None
    return RunHostBinding(
        resource_order=preflight.instrument_order,
        provider_id=preflight.provider_id,
        instrument_order=preflight.instrument_order,
        advertised_descriptions=preflight.advertised_descriptions,
    )


def _domain_target_footprint(
    system: ExperimentSystem,
    *,
    config: ConfigProfileSnapshot,
    templates: dict[str, DomainCompileTemplate],
) -> tuple[ResourceClaim, ...]:
    if not templates or system.domain_compiler is None:
        return ()
    compiler = system.domain_compiler
    target = config.domain_target
    if target is None:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_missing",
                    "the accepted system configuration has no domain target",
                    category=ProblemCategory.NOT_FOUND,
                )
            ]
        )
    if compiler.target_id != target.id:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_mismatch",
                    "the domain compiler target does not match the accepted system "
                    "configuration",
                    category=ProblemCategory.INVALID_INPUT,
                    details={
                        "compiler_target_id": compiler.target_id,
                        "configured_target_id": target.id,
                    },
                )
            ]
        )
    if compiler.target_kind != target.kind:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_kind_mismatch",
                    "the domain compiler adapter does not match the accepted "
                    "system configuration",
                    category=ProblemCategory.INVALID_INPUT,
                    details={
                        "compiler_target_kind": compiler.target_kind,
                        "configured_target_kind": target.kind,
                    },
                )
            ]
        )
    for execution_id, template in templates.items():
        if not compiler.supports(template.call):
            raise CheckFailed(
                [
                    _planning_problem(
                        "domain_compiler_missing",
                        "the experiment system cannot compile domain call "
                        f"{execution_id!r}",
                        category=ProblemCategory.NOT_FOUND,
                        details={"execution_id": execution_id},
                    )
                ]
            )
    return _sorted_claims(
        (
            ResourceClaim(target.id, "target"),
            *(
                ResourceClaim(instrument_id, "instrument")
                for instrument_id in target.instrument_ids
            ),
        )
    )


def _sorted_claims(claims: tuple[ResourceClaim, ...]) -> tuple[ResourceClaim, ...]:
    return tuple(sorted(set(claims), key=lambda claim: (claim.kind, claim.id)))


def _compile_coverage_region(
    *,
    system: ExperimentSystem,
    linked: LinkedPlan,
    lazy_points: LinkedPointMaterializer,
    point_catalog: RunPointCatalog,
    region: tuple[int, ...],
    point_count: int,
    domain_templates: dict[str, DomainCompileTemplate],
    domain_footprint: tuple[ResourceClaim, ...],
    local_target: LocalTargetPlan | None,
    run_resource_claims: frozenset[ResourceClaim],
) -> tuple[RunCoverageBlock, ...]:
    catalog = point_catalog
    linked_block = lazy_points.materialize_ordinals(
        region,
        max_points=system.coverage_block_size,
    )
    if local_target is not None:
        local = materialize_local_execution(
            linked_block,
            target=local_target,
            point_count=point_count,
        )
        local_effects = local
    else:
        local_effects = None
    barriers = (
        tuple((ordinal,) for ordinal in region)
        if core_actions(linked.program)
        else (region,)
    )
    input_cache: dict[
        tuple[str, str, tuple[str, ...], tuple[int, ...]],
        tuple[tuple[str, tuple[object, ...]], ...],
    ] = {}

    def bind_domain_inputs(
        execution_id: str,
        input_kind: Literal["program", "compiler"],
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        selected_ordinals = tuple(ordinals)
        if len(selected_ordinals) > max_points:
            raise ValueError("domain input binding exceeds the requested budget")
        key = (execution_id, input_kind, tuple(input_ids), selected_ordinals)
        cached = input_cache.get(key)
        if cached is not None:
            return cached
        bound = lazy_points.bind_domain_inputs(
            execution_id,
            input_kind,
            input_ids,
            selected_ordinals,
            max_points=max_points,
            coverage=linked_block,
        )
        input_cache[key] = bound
        return bound

    def input_binder(
        execution_id: str,
        input_kind: Literal["program", "compiler"],
    ) -> DomainInputBinder:
        return lambda input_ids, ordinals, max_points: bind_domain_inputs(
            execution_id,
            input_kind,
            input_ids,
            ordinals,
            max_points,
        )

    compiled_domains: list[_CompiledDomainExecution] = []
    for effect_index, execution in enumerate(linked.program.effects):
        if not isinstance(execution, TypedDomainExecution):
            continue
        for barrier in barriers:
            ordered_barriers = _domain_acquisition_barriers(
                barrier,
                effect_index=effect_index,
                local_effects=local_effects,
                resource_claims=domain_footprint,
            )
            for ordered in ordered_barriers:
                refined_barriers = _domain_state_barriers(
                    ordered,
                    local_effects=local_effects,
                    resource_claims=domain_footprint,
                )
                for refined in refined_barriers:
                    compiled = _compile_domain_execution(
                        system.domain_compiler,
                        domain_templates[execution.id],
                        refined,
                        coverage_ordinal=refined[0],
                        bind_program_inputs=input_binder(execution.id, "program"),
                        bind_compiler_inputs=input_binder(execution.id, "compiler"),
                    )
                    if compiled is None:
                        raise CheckFailed(
                            [
                                _planning_problem(
                                    "domain_compiler_missing",
                                    "the experiment system cannot compile domain call "
                                    f"{execution.id!r}",
                                    category=ProblemCategory.NOT_FOUND,
                                    details={"execution_id": execution.id},
                                )
                            ]
                        )
                    compiled_domains.append(compiled)
    jobs_by_execution: dict[str, list[RunDomainJob]] = {}
    for compiled in compiled_domains:
        jobs_by_execution.setdefault(compiled.request.call.id, []).extend(
            _prepare_domain_jobs(compiled, linked_block)
        )
    return _coverage_blocks(
        effects=linked.program.effects,
        local_effects=local_effects,
        run_points=catalog.points,
        barriers=barriers,
        jobs_by_execution=jobs_by_execution,
        run_resource_claims=run_resource_claims,
    )


def _coverage_blocks(
    *,
    effects: tuple[CoreEffect, ...],
    local_effects: MaterializedLocalEffects | None,
    run_points: tuple[RunPoint, ...],
    barriers: tuple[tuple[int, ...], ...],
    jobs_by_execution: dict[str, list[RunDomainJob]],
    run_resource_claims: frozenset[ResourceClaim],
) -> tuple[RunCoverageBlock, ...]:
    run_point_by_ordinal = {point.ordinal: point for point in run_points}
    jobs = tuple(job for selected in jobs_by_execution.values() for job in selected)
    blocks: list[RunCoverageBlock] = []
    for barrier in barriers:
        block_jobs = tuple(job for job in jobs if job.point_ordinals[0] in barrier)
        selected_compute = _select_local_effects(
            () if local_effects is None else local_effects.compute_operations,
            barrier,
        )
        selected_effects = tuple(
            _select_local_effects(group, barrier)
            for group in (
                () if local_effects is None else local_effects.effect_operations
            )
        )
        local_regions = _local_schedule_regions(
            barrier,
            (
                *selected_compute,
                *(item for group in selected_effects for item in group),
            ),
            block_jobs,
        )
        operations: list[RunCoveredOperation] = []
        for region in local_regions:
            operations.extend(
                effect
                for effect in selected_compute
                if effect.point_indices[0] in region
            )
            for effect_index, effect in enumerate(effects):
                if local_effects is not None:
                    operations.extend(
                        item
                        for item in selected_effects[effect_index]
                        if item.point_indices[0] in region
                    )
                if isinstance(effect, TypedDomainExecution):
                    operations.extend(
                        job
                        for job in jobs_by_execution.get(effect.id, ())
                        if job.point_ordinals[0] in region
                    )
            for ordinal in region:
                operations.append(RunCoverageCheckpoint((ordinal,)))
        local_claims = tuple(
            claim
            for operation in operations
            if isinstance(operation, RunCoverageEffect)
            for claim in local_operation_resource_claims(operation.operation)
        )
        blocks.append(
            RunCoverageBlock(
                tuple(run_point_by_ordinal[ordinal] for ordinal in barrier),
                tuple(operations),
                tuple(
                    claim
                    for claim in _sorted_claims(local_claims)
                    if claim not in run_resource_claims
                ),
            )
        )
    return tuple(blocks)


def _local_schedule_regions(
    region: tuple[int, ...],
    effects: Sequence[RunCoverageEffect],
    domain_jobs: Sequence[RunDomainJob],
) -> tuple[tuple[int, ...], ...]:
    boundaries = {
        *(effect.point_indices[0] for effect in effects),
        *(job.point_ordinals[0] for job in domain_jobs),
    }
    selected: list[tuple[int, ...]] = []
    start = 0
    for offset, ordinal in enumerate(region):
        if offset and ordinal in boundaries:
            selected.append(region[start:offset])
            start = offset
    selected.append(region[start:])
    return tuple(selected)


def _select_local_effects(
    effects: Sequence[RunCoverageEffect],
    region: tuple[int, ...],
) -> tuple[RunCoverageEffect, ...]:
    selected_ordinals = frozenset(region)
    selected: list[RunCoverageEffect] = []
    for effect in effects:
        covered = tuple(
            ordinal for ordinal in effect.point_indices if ordinal in selected_ordinals
        )
        if not covered:
            continue
        selected.append(
            effect
            if covered == effect.point_indices
            else replace(effect, point_indices=covered)
        )
    return tuple(selected)


def _domain_acquisition_barriers(
    region: tuple[int, ...],
    *,
    effect_index: int,
    local_effects: MaterializedLocalEffects | None,
    resource_claims: tuple[ResourceClaim, ...],
) -> tuple[tuple[int, ...], ...]:
    """Split one domain where earlier conflicting acquisitions expose order.

    Only finalized local operations count: a symbolic acquisition can survive after
    all of its product uses have been removed by demand closure. An earlier collection
    on the same physical resource must run before this domain at each point, so its
    point starts bound the domain's compile regions. Independent collections may
    interleave safely, while a later conflicting collection can begin after one broad
    domain job finishes and therefore does not constrain that job.
    """

    target_claims = frozenset(resource_claims)
    if local_effects is None or not target_claims:
        return (region,)
    boundaries = {
        effect.point_indices[0]
        for group in local_effects.effect_operations[:effect_index]
        for effect in group
        if isinstance(effect.operation, CollectOperation)
        and frozenset(local_operation_resource_claims(effect.operation)) & target_claims
        and effect.point_indices[0] != region[0]
        and effect.point_indices[0] in region
    }
    if not boundaries:
        return (region,)
    selected: list[tuple[int, ...]] = []
    start = 0
    for offset, ordinal in enumerate(region):
        if offset and ordinal in boundaries:
            selected.append(region[start:offset])
            start = offset
    selected.append(region[start:])
    return tuple(selected)


def _domain_state_barriers(
    region: tuple[int, ...],
    *,
    local_effects: MaterializedLocalEffects | None,
    resource_claims: tuple[ResourceClaim, ...],
) -> tuple[tuple[int, ...], ...]:
    """Split domain coverage before compiling around conflicting local state.

    Exact state claims exist only after local resources are bound. Refining the
    coverage from those final claims before invoking the domain compiler avoids
    producing a broad artifact that must be discarded once the conflict is known.
    """

    boundaries: set[int] = set()
    target_claims = frozenset(resource_claims)
    if not target_claims or local_effects is None:
        return (region,)
    state_effects = (
        effect for group in local_effects.effect_operations for effect in group
    )
    for effect in state_effects:
        if not isinstance(effect.operation, ApplyStateOperation):
            continue
        start = effect.point_indices[0]
        if start == region[0] or start not in region:
            continue
        state_claims = frozenset(local_operation_resource_claims(effect.operation))
        if state_claims & target_claims:
            boundaries.add(start)
    if not boundaries:
        return (region,)
    selected: list[tuple[int, ...]] = []
    start = 0
    for offset, ordinal in enumerate(region):
        if offset and ordinal in boundaries:
            selected.append(region[start:offset])
            start = offset
    selected.append(region[start:])
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class _CompiledDomainExecution:
    request: DomainCompileRequest = field(repr=False)
    compiler: DomainCompiler = field(repr=False, compare=False)
    compilation: DomainCompilation = field(repr=False)
    coverage_ordinal: int


def _compile_domain_execution(
    compiler: DomainCompiler | None,
    template: DomainCompileTemplate,
    barrier_region: tuple[int, ...],
    *,
    coverage_ordinal: int,
    bind_program_inputs: DomainInputBinder,
    bind_compiler_inputs: DomainInputBinder,
) -> _CompiledDomainExecution | None:
    if compiler is None:
        return None
    request = template.bind_coverage(
        (barrier_region,),
        bind_program_inputs,
        bind_compiler_inputs,
    )
    compilation = compiler.compile(request)
    if compilation is None:
        return None
    validate_domain_compilation(request, compilation)
    return _CompiledDomainExecution(
        request=request,
        compiler=compiler,
        compilation=compilation,
        coverage_ordinal=coverage_ordinal,
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

        def prepare(
            *,
            compiler: DomainCompiler = domain.compiler,
            job: DomainCompiledJob = compiled,
            batch_context: DomainBatchContext = context,
        ) -> PreparedDomainExecution:
            return compiler.prepare(job, batch_context)

        jobs.append(
            RunDomainJob(
                id=(f"{execution_id}:coverage-{domain.coverage_ordinal}:{compiled.id}"),
                point_ordinals=compiled.point_ordinals,
                _prepare=prepare,
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
