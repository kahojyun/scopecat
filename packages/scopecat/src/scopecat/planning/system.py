"""Compile bound experiment semantics for one physical experiment system.

This boundary coordinates local target selection, domain lowering, and bounded
coverage so placement decisions share one view of effect order and resource
ownership. Its output is the closed ``RunProgram`` accepted by execution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.bind import BoundDomainTarget, BoundPlan
from scopecat.execution.local.program import LocalOperation
from scopecat.execution.program import (
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
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.resource_identity import (
    DomainTargetRequirement,
    ResourceRequirement,
)
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.domain_bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from scopecat.planning.domain_results import (
    domain_result_product_use_ids,
)
from scopecat.planning.local_effects import (
    MaterializedLocalEffects,
    local_operation_resource_requirements,
)
from scopecat.planning.local_materialization import (
    materialize_local_execution,
    materialize_local_final_state,
    prepare_local_target,
)
from scopecat.planning.measurement_projection import (
    project_measurement_catalog_from_domain,
    project_run_point_catalog_from_domain,
    project_static_value_record_candidates,
)
from scopecat.planning.point_materialization import (
    MaterializedBoundPoints,
    materialize_bound_points,
)
from scopecat.planning.provider_binding import (
    validate_run_host_binding,
)
from scopecat.program.logical import LogicalDomainExecution, LogicalEffect
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain.compiler import (
    DomainCompiler,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView
from scopecat.sdk.payloads import PayloadCodecRegistry


@dataclass(frozen=True, slots=True)
class ExperimentSystem:
    """The physical interfaces used to lower one experiment definition.

    The daemon-resolved instrument catalog is immutable planning input. Domain
    compilers and payload codecs remain local code because they lower and encode
    author-authored values without opening instrument connections.
    """

    instrument_catalog: InstrumentContractCatalog = field(repr=False)
    domain_compiler: DomainCompiler | None = field(default=None, repr=False)
    payload_codecs: PayloadCodecRegistry = field(
        default_factory=PayloadCodecRegistry,
        repr=False,
        compare=False,
    )

    def compile(
        self,
        bound: BoundPlan,
    ) -> RunProgram:
        return _compile_system_program(
            system=self,
            bound=bound,
        )


type ExperimentSystemBuilder = Callable[
    [ConfigProfileSnapshot, InstrumentContractCatalog],
    ExperimentSystem,
]


def build_experiment_system(
    builder: ExperimentSystemBuilder | None,
    config: ConfigProfileSnapshot,
    instrument_catalog: InstrumentContractCatalog,
) -> ExperimentSystem:
    """Build a config-bound experiment system at the planning boundary."""

    if builder is None:
        return ExperimentSystem(instrument_catalog=instrument_catalog)
    system = builder(config, instrument_catalog)
    if system.instrument_catalog != instrument_catalog:
        raise ValueError(
            "experiment system builder must retain the daemon instrument catalog"
        )
    return system


def _compile_system_program(
    *,
    system: ExperimentSystem,
    bound: BoundPlan,
) -> RunProgram:
    config = bound.environment.config
    catalog = system.instrument_catalog
    expected_config_hash = config_content_hash(config)
    if catalog.config_content_hash != expected_config_hash:
        raise ProviderContractError(
            (
                problem(
                    "instrument_catalog_config_mismatch",
                    "instrument contracts do not match the planning configuration",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "instrument_catalog",
                        "config_content_hash",
                    ),
                    details={
                        "expected": expected_config_hash,
                        "actual": catalog.config_content_hash,
                    },
                ),
            )
        )
    domain_use_ids_by_execution = {
        execution.id: domain_result_product_use_ids(bound.bindings, execution)
        for execution in bound.program.program.domain_executions
    }
    domain_calls = {
        execution_id: make_domain_call_view(
            bound,
            execution_id,
            product_use_ids,
        )
        for execution_id, product_use_ids in domain_use_ids_by_execution.items()
    }
    _validate_domain_compiler(
        system.domain_compiler,
        target=bound.domain_target,
    )
    domain_target_requirement = _domain_target_requirement(bound.domain_target)
    domain_footprint = _domain_target_footprint(domain_target_requirement)
    domain_owned_product_use_ids = frozenset(
        use_id
        for product_use_ids in domain_use_ids_by_execution.values()
        for use_id in product_use_ids
    )
    postprocessor_output_use_ids = frozenset(
        use_id
        for postprocessor in bound.bindings.measurement_postprocessors
        for output in postprocessor.outputs
        for use_id in output.product_use_ids
    )
    local_product_use_ids = tuple(
        use.id
        for use in bound.bindings.product_uses
        if use.id not in domain_owned_product_use_ids
        and use.id not in postprocessor_output_use_ids
    )
    local_instrument_required = bool(
        local_product_use_ids
        or bound.program.program.bindings
        or bound.program.program.invocations
    )
    local_execution_required = bool(
        local_instrument_required or bound.bindings.live_compute_ids
    )
    implementation_problems = list(
        _implementation_problems(
            has_domain_call=bool(bound.program.program.domain_executions),
            has_domain_compiler=system.domain_compiler is not None,
            local_instrument_required=local_instrument_required,
            has_local_instrument_catalog=catalog.provider_id is not None,
        )
    )
    if implementation_problems:
        raise CheckFailed(implementation_problems)
    if local_instrument_required and catalog.problems:
        raise ProviderContractError(catalog.problems)
    bound_points = materialize_bound_points(bound)
    point_domain = bound_points.point_domain
    point_count = len(point_domain.points)
    measurement_catalog = project_measurement_catalog_from_domain(
        bound,
        point_domain,
    )
    point_catalog = project_run_point_catalog_from_domain(bound, point_domain)
    measurements = select_measurement_projection(
        measurement_catalog,
        bound.bindings.record_uses,
        static_value_candidates=project_static_value_record_candidates(bound_points),
    )
    local_target = (
        prepare_local_target(
            bound,
            product_use_ids=frozenset(local_product_use_ids),
            instrument_order=tuple(item.instrument_id for item in catalog.instruments),
        )
        if local_execution_required
        else None
    )
    local_effects = (
        materialize_local_execution(
            bound_points,
            target=local_target,
        )
        if local_target is not None
        else None
    )
    local_final_state = (
        materialize_local_final_state(
            bound,
            target=local_target,
        )
        if local_target is not None
        else ()
    )
    local_requirements = _local_resource_requirements(
        local_effects,
        final_state=local_final_state,
    )
    _reject_local_domain_overlap(
        local_requirements=local_requirements,
        domain_footprint=domain_footprint,
    )
    coverage = _compile_coverage(
        system=system,
        bound=bound,
        bound_points=bound_points,
        point_count=point_count,
        domain_calls=domain_calls,
        local_effects=local_effects,
    )
    resource_requirements = _sorted_requirements(
        (*local_requirements, *domain_footprint)
    )
    local_instrument_ids = frozenset(
        requirement.id for requirement in local_requirements
    )
    host = _host_binding(
        catalog,
        instrument_ids=local_instrument_ids,
        payload_codecs=system.payload_codecs,
    )
    if host is not None:
        validate_run_host_binding(
            host=host,
            effect_blocks=(
                ()
                if local_effects is None
                else (
                    tuple(
                        effect.operation for effect in local_effects.compute_operations
                    ),
                    *(
                        tuple(effect.operation for effect in effects)
                        for effects in local_effects.effect_operations
                    ),
                    local_final_state,
                )
            ),
            problems=(),
        )

    return RunProgram(
        config_content_hash=config_content_hash(config),
        host=host,
        coverage=coverage,
        final_state=local_final_state,
        points=point_catalog,
        measurements=measurements,
        measurement_postprocessors=bound.bindings.measurement_postprocessors,
        resource_requirements=resource_requirements,
        domain_target_requirement=domain_target_requirement,
    )


def _host_binding(
    catalog: InstrumentContractCatalog,
    *,
    instrument_ids: frozenset[str],
    payload_codecs: PayloadCodecRegistry,
) -> RunHostBinding | None:
    provider_id = catalog.provider_id
    if provider_id is None or not instrument_ids:
        return None
    instrument_order = tuple(
        description.instrument_id
        for description in catalog.instruments
        if description.instrument_id in instrument_ids
    )
    return RunHostBinding(
        resource_order=instrument_order,
        provider_id=provider_id,
        advertised_descriptions={
            description.instrument_id: description
            for description in catalog.instruments
        },
        payload_codecs=payload_codecs,
    )


def _validate_domain_compiler(
    compiler: DomainCompiler | None,
    *,
    target: BoundDomainTarget | None,
) -> None:
    if target is None or compiler is None:
        return
    if compiler.target_id != target.id:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_mismatch",
                    "the domain compiler target does not match the bound target",
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
                    "the domain compiler adapter does not match the bound target",
                    details={
                        "compiler_target_kind": compiler.target_kind,
                        "configured_target_kind": target.kind,
                    },
                )
            ]
        )


def _domain_target_requirement(
    target: BoundDomainTarget | None,
) -> DomainTargetRequirement | None:
    if target is None:
        return None
    return DomainTargetRequirement(
        id=target.id,
        kind=target.kind,
        instrument_ids=tuple(sorted(target.instrument_ids)),
    )


def _domain_target_footprint(
    target: DomainTargetRequirement | None,
) -> tuple[ResourceRequirement, ...]:
    if target is None:
        return ()
    return _sorted_requirements(
        (
            ResourceRequirement(target.id, "target"),
            *(
                ResourceRequirement(instrument_id, "instrument")
                for instrument_id in target.instrument_ids
            ),
        )
    )


def _sorted_requirements(
    requirements: tuple[ResourceRequirement, ...],
) -> tuple[ResourceRequirement, ...]:
    return tuple(
        sorted(
            set(requirements),
            key=lambda requirement: (requirement.kind, requirement.id),
        )
    )


def _local_resource_requirements(
    local_effects: MaterializedLocalEffects | None,
    *,
    final_state: Sequence[LocalOperation] = (),
) -> tuple[ResourceRequirement, ...]:
    if local_effects is None and not final_state:
        return ()
    effect_operations = (
        ()
        if local_effects is None
        else (
            *(effect.operation for effect in local_effects.compute_operations),
            *(
                effect.operation
                for group in local_effects.effect_operations
                for effect in group
            ),
        )
    )
    return _sorted_requirements(
        tuple(
            requirement
            for operation in (*effect_operations, *final_state)
            for requirement in local_operation_resource_requirements(operation)
        )
    )


def _reject_local_domain_overlap(
    *,
    local_requirements: tuple[ResourceRequirement, ...],
    domain_footprint: tuple[ResourceRequirement, ...],
) -> None:
    """Keep one owner for every physical instrument during a Run."""

    local_instruments = {
        requirement.id
        for requirement in local_requirements
        if requirement.kind == "instrument"
    }
    domain_instruments = {
        requirement.id
        for requirement in domain_footprint
        if requirement.kind == "instrument"
    }
    overlap = sorted(local_instruments & domain_instruments)
    if overlap:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_local_instrument_overlap",
                    "local operations cannot use instruments owned by the "
                    "domain target",
                    details={"instrument_ids": overlap},
                )
            ]
        )


def _compile_coverage(
    *,
    system: ExperimentSystem,
    bound: BoundPlan,
    bound_points: MaterializedBoundPoints,
    point_count: int,
    domain_calls: dict[str, DomainCallView],
    local_effects: MaterializedLocalEffects | None,
) -> tuple[RunCoveredOperation, ...]:
    region = tuple(range(point_count))
    if not region:
        return ()
    compiler = cast("DomainCompiler", system.domain_compiler)
    jobs_by_execution: dict[str, list[RunDomainJob]] = {}
    for execution in bound.program.program.effects:
        if not isinstance(execution, LogicalDomainExecution):
            continue
        jobs_by_execution[execution.id] = list(
            _compile_domain_batches(
                compiler,
                domain_calls[execution.id],
                bound_points,
                region,
            )
        )
    return _coverage_operations(
        effects=bound.program.program.effects,
        local_effects=local_effects,
        region=region,
        jobs_by_execution=jobs_by_execution,
    )


def _coverage_operations(
    *,
    effects: tuple[LogicalEffect, ...],
    local_effects: MaterializedLocalEffects | None,
    region: tuple[int, ...],
    jobs_by_execution: dict[str, list[RunDomainJob]],
) -> tuple[RunCoveredOperation, ...]:
    jobs = tuple(job for selected in jobs_by_execution.values() for job in selected)
    selected_compute = () if local_effects is None else local_effects.compute_operations
    selected_effects = () if local_effects is None else local_effects.effect_operations
    local_regions = _local_schedule_regions(
        region,
        (
            *selected_compute,
            *(item for group in selected_effects for item in group),
        ),
        jobs,
    )
    operations: list[RunCoveredOperation] = []
    for local_region in local_regions:
        operations.extend(
            effect for effect in selected_compute if effect.point_index in local_region
        )
        for effect_index, effect in enumerate(effects):
            if local_effects is not None:
                operations.extend(
                    item
                    for item in selected_effects[effect_index]
                    if item.point_index in local_region
                )
            if isinstance(effect, LogicalDomainExecution):
                operations.extend(
                    job
                    for job in jobs_by_execution.get(effect.id, ())
                    if job.point_ordinals[0] in local_region
                )
        for ordinal in local_region:
            operations.append(RunCoverageCheckpoint(ordinal))
    return tuple(operations)


def _local_schedule_regions(
    region: tuple[int, ...],
    effects: Sequence[RunCoverageEffect],
    domain_jobs: Sequence[RunDomainJob],
) -> tuple[tuple[int, ...], ...]:
    boundaries = {
        *(effect.point_index for effect in effects),
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


def _compile_domain_batches(
    compiler: DomainCompiler,
    call: DomainCallView,
    bound_points: MaterializedBoundPoints,
    point_ordinals: tuple[int, ...],
) -> tuple[RunDomainJob, ...]:
    max_points = compiler.max_points_per_batch
    if type(max_points) is not int or max_points <= 0:
        raise ValueError("domain batch capacity must be a positive integer")
    jobs: list[RunDomainJob] = []
    for batch_ordinal, offset in enumerate(range(0, len(point_ordinals), max_points)):
        batch_points = point_ordinals[offset : offset + max_points]
        request = make_domain_batch_request(
            call,
            bound_points,
            batch_points,
            batch_ordinal=batch_ordinal,
        )
        execution_candidate = cast(
            "object",
            compiler.compile_batch(request),
        )
        if not isinstance(execution_candidate, PreparedDomainExecution):
            raise TypeError(
                "domain compiler compile_batch must return PreparedDomainExecution"
            )

        jobs.append(
            RunDomainJob(
                id=f"{call.id}:batch-{batch_ordinal}",
                point_ordinals=batch_points,
                execution=execution_candidate,
            )
        )
    return tuple(jobs)


def _implementation_problems(
    *,
    has_domain_call: bool,
    has_domain_compiler: bool,
    local_instrument_required: bool,
    has_local_instrument_catalog: bool,
) -> tuple[Problem, ...]:
    """Report missing effect/dataflow implementations directly from typed edges."""

    problems: list[Problem] = []
    if has_domain_call and not has_domain_compiler:
        problems.append(
            _planning_problem(
                "domain_compiler_missing",
                "the typed domain call has no configured compiler",
            )
        )
    if local_instrument_required and not has_local_instrument_catalog:
        problems.append(
            _planning_problem(
                "local_instrument_catalog_missing",
                "local effects or products require an instrument contract catalog",
            )
        )
    return tuple(problems)


def _planning_problem(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PLANNING,
        location=model_location("experiment_system"),
        details=details or {},
    )
