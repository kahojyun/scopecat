"""Compile linked experiment semantics for one physical experiment system.

This boundary coordinates local target selection, domain lowering, and bounded
coverage so placement decisions share one view of effect order and resource
ownership. Its output is the closed ``RunProgram`` accepted by execution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.measurement_projection import (
    project_measurement_catalog_from_domain,
    project_run_point_catalog_from_domain,
)
from scopecat.compiler.typed.domain_results import (
    domain_result_closure,
)
from scopecat.compiler.typed.program import (
    CoreEffect,
    TypedDomainExecution,
    core_domain_executions,
    core_state,
)
from scopecat.execution.program import (
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
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.points import RunPoint, RunPointCatalog
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.local_effects import (
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
    validate_run_host_binding,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from scopecat.sdk.domain.compiler import (
    DomainCompiler,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView
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

    def __post_init__(self) -> None:
        if self.provider is None and self.domain_compiler is None:
            msg = "experiment system requires a provider or domain compiler"
            raise ValueError(msg)

    def compile(
        self,
        linked: LinkedPlan,
    ) -> RunProgram:
        return _compile_system_program(
            system=self,
            linked=linked,
        )


type ExperimentSystemBuilder = Callable[[ConfigProfileSnapshot], ExperimentSystem]


def build_experiment_system(
    builder: ExperimentSystemBuilder | None,
    config: ConfigProfileSnapshot,
) -> ExperimentSystem | None:
    """Build config-bound capabilities at the planning boundary."""

    if builder is None:
        return None
    return builder(config)


def _compile_system_program(
    *,
    system: ExperimentSystem,
    linked: LinkedPlan,
) -> RunProgram:
    config = linked.environment.config
    domain_result_closures = {
        execution.id: domain_result_closure(linked.program, execution.id)
        for execution in core_domain_executions(linked.program)
    }
    domain_calls = {
        execution_id: make_domain_call_view(
            linked,
            execution_id,
            result_closure,
        )
        for execution_id, result_closure in domain_result_closures.items()
    }
    domain_footprint = _domain_target_footprint(
        system,
        config=config,
        has_domain_calls=bool(domain_calls),
    )
    domain_owned_product_use_ids = frozenset(
        use_id
        for result_closure in domain_result_closures.values()
        for use_id in result_closure.product_use_ids
    )
    postprocessor_output_use_ids = frozenset(
        use_id
        for postprocessor in linked.program.measurement_postprocessors
        for output in postprocessor.outputs
        for use_id in output.product_use_ids
    )
    local_product_use_ids = tuple(
        use.id
        for use in linked.program.product_uses
        if use.id not in domain_owned_product_use_ids
        and use.id not in postprocessor_output_use_ids
    )
    local_required = bool(
        local_product_use_ids
        or linked.program.compute_nodes
        or core_state(linked.program)
    )
    implementation_problems = list(
        _implementation_problems(
            has_domain_call=bool(core_domain_executions(linked.program)),
            has_domain_compiler=system.domain_compiler is not None,
            local_required=local_required,
            has_local_provider=system.provider is not None,
        )
    )
    if implementation_problems:
        raise CheckFailed(implementation_problems)
    linked_points = materialize_linked_points(linked)
    point_domain = linked_points.point_domain
    point_count = len(point_domain.points)
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
    if preflight is not None and bool(preflight.problems):
        raise ProviderContractError(preflight.problems)
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
    local_effects = (
        materialize_local_execution(
            linked_points,
            target=local_target,
        )
        if local_target is not None
        else None
    )
    local_claims = _local_resource_claims(local_effects)
    _reject_local_domain_overlap(
        local_claims=local_claims,
        domain_footprint=domain_footprint,
    )
    coverage = _compile_coverage(
        system=system,
        linked=linked,
        linked_points=linked_points,
        point_catalog=point_catalog,
        point_count=point_count,
        domain_calls=domain_calls,
        local_effects=local_effects,
    )
    resource_claims = _sorted_claims((*local_claims, *domain_footprint))
    local_instrument_ids = frozenset(claim.id for claim in local_claims)
    host = _host_binding(preflight, instrument_ids=local_instrument_ids)
    if host is not None:
        validate_run_host_binding(
            host=host,
            preamble_operations=(
                () if local_target is None else local_target.run_operations
            ),
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
                )
            ),
            problems=(),
        )

    return RunProgram(
        config_content_hash=config_content_hash(config),
        host=host,
        preamble=(() if local_target is None else local_target.run_operations),
        coverage=coverage,
        points=point_catalog,
        measurements=measurements,
        measurement_postprocessors=linked.program.measurement_postprocessors,
        resource_claims=resource_claims,
    )


def _host_binding(
    preflight: InstrumentProviderPreflight | None,
    *,
    instrument_ids: frozenset[str],
) -> RunHostBinding | None:
    if preflight is None or not instrument_ids:
        return None
    instrument_order = tuple(
        item for item in preflight.instrument_order if item in instrument_ids
    )
    return RunHostBinding(
        resource_order=instrument_order,
        provider_id=preflight.provider_id,
        advertised_descriptions=preflight.advertised_descriptions,
    )


def _domain_target_footprint(
    system: ExperimentSystem,
    *,
    config: ConfigProfileSnapshot,
    has_domain_calls: bool,
) -> tuple[ResourceClaim, ...]:
    if not has_domain_calls or system.domain_compiler is None:
        return ()
    compiler = system.domain_compiler
    target = config.domain_target
    if target is None:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_missing",
                    "the accepted system configuration has no domain target",
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
                    details={
                        "compiler_target_kind": compiler.target_kind,
                        "configured_target_kind": target.kind,
                    },
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


def _local_resource_claims(
    local_effects: MaterializedLocalEffects | None,
) -> tuple[ResourceClaim, ...]:
    if local_effects is None:
        return ()
    return _sorted_claims(
        tuple(
            claim
            for effect in (
                *local_effects.compute_operations,
                *(item for group in local_effects.effect_operations for item in group),
            )
            for claim in local_operation_resource_claims(effect.operation)
        )
    )


def _reject_local_domain_overlap(
    *,
    local_claims: tuple[ResourceClaim, ...],
    domain_footprint: tuple[ResourceClaim, ...],
) -> None:
    """Keep one owner for every physical instrument during a Run."""

    local_instruments = {
        claim.id for claim in local_claims if claim.kind == "instrument"
    }
    domain_instruments = {
        claim.id for claim in domain_footprint if claim.kind == "instrument"
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
    linked: LinkedPlan,
    linked_points: MaterializedLinkedPoints,
    point_catalog: RunPointCatalog,
    point_count: int,
    domain_calls: dict[str, DomainCallView],
    local_effects: MaterializedLocalEffects | None,
) -> tuple[RunCoverageBlock, ...]:
    region = tuple(range(point_count))
    if not region:
        return ()
    compiler = cast("DomainCompiler", system.domain_compiler)
    jobs_by_execution: dict[str, list[RunDomainJob]] = {}
    for execution in linked.program.effects:
        if not isinstance(execution, TypedDomainExecution):
            continue
        jobs_by_execution[execution.id] = list(
            _compile_domain_batches(
                compiler,
                domain_calls[execution.id],
                linked_points,
                region,
            )
        )
    return _coverage_blocks(
        effects=linked.program.effects,
        local_effects=local_effects,
        run_points=point_catalog.points,
        region=region,
        jobs_by_execution=jobs_by_execution,
    )


def _coverage_blocks(
    *,
    effects: tuple[CoreEffect, ...],
    local_effects: MaterializedLocalEffects | None,
    run_points: tuple[RunPoint, ...],
    region: tuple[int, ...],
    jobs_by_execution: dict[str, list[RunDomainJob]],
) -> tuple[RunCoverageBlock, ...]:
    run_point_by_ordinal = {point.ordinal: point for point in run_points}
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
            effect
            for effect in selected_compute
            if effect.point_indices[0] in local_region
        )
        for effect_index, effect in enumerate(effects):
            if local_effects is not None:
                operations.extend(
                    item
                    for item in selected_effects[effect_index]
                    if item.point_indices[0] in local_region
                )
            if isinstance(effect, TypedDomainExecution):
                operations.extend(
                    job
                    for job in jobs_by_execution.get(effect.id, ())
                    if job.point_ordinals[0] in local_region
                )
        for ordinal in local_region:
            operations.append(RunCoverageCheckpoint(ordinal))
    return (
        RunCoverageBlock(
            tuple(run_point_by_ordinal[ordinal] for ordinal in region),
            tuple(operations),
        ),
    )


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


def _compile_domain_batches(
    compiler: DomainCompiler,
    call: DomainCallView,
    linked_points: MaterializedLinkedPoints,
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
            linked_points,
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
    local_required: bool,
    has_local_provider: bool,
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
    if local_required and not has_local_provider:
        problems.append(
            _planning_problem(
                "local_instrument_provider_missing",
                "local effects or products require an instrument provider",
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
