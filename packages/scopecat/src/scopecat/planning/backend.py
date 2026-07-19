"""Compile linked experiment semantics into the sole executable RunProgram."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.linking.materialization import (
    materialize_local_semantics_from_points,
)
from scopecat.compiler.typed.program import (
    TypedMeasurementTransform,
    core_actions,
    core_domain_executions,
    core_state,
)
from scopecat.execution.local.executor import lower_run_local_effects
from scopecat.execution.local.program import ActionStage, ApplyStateStage
from scopecat.execution.program import (
    RunDomainJob,
    RunLocalEffects,
    RunPointRegion,
    RunProgram,
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
from scopecat.measurements.projection import (
    bind_measurement_projection,
    select_measurement_projection,
)
from scopecat.measurements.values import select_measurement_values
from scopecat.planning.domain_placement import domain_execution_slice
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain._bridge import (
    DomainPlanProjection,
    make_domain_batch_context,
    make_domain_compile_request,
    project_domain_plan,
)
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiler,
    DomainCompileRequest,
    validate_domain_compilation,
)
from scopecat.sdk.instruments.contracts import InstrumentProvider

_POINT_UNIT_ID = "point-instrument"


@dataclass(frozen=True, slots=True)
class ExecutionBackend:
    """The single backend combining point instruments and domain compilers."""

    provider: InstrumentProvider | None = field(default=None, repr=False)
    domain_compilers: tuple[DomainCompiler, ...] = field(
        default=(),
        repr=False,
    )
    max_materialized_points: int = 100_000
    id: str = "scopecat.execution.v3"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "execution backend id must be non-empty"
            raise ValueError(msg)
        if (
            type(self.max_materialized_points) is not int
            or self.max_materialized_points <= 0
        ):
            raise ValueError("max_materialized_points must be a positive integer")
        compilers = tuple(self.domain_compilers)
        if self.provider is None and not compilers:
            msg = "execution backend requires a provider or domain compiler"
            raise ValueError(msg)
        object.__setattr__(self, "domain_compilers", compilers)

    @property
    def backend_id(self) -> str:
        return self.id

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
        return _prepare_backend_plan(
            backend=self,
            linked=linked,
            config=config,
        )


def _prepare_backend_plan(
    *,
    backend: ExecutionBackend,
    linked: LinkedPlan,
    config: ConfigProfileSnapshot,
) -> RunProgram:
    linked_points = materialize_linked_points(
        linked,
        max_points=backend.max_materialized_points,
    )
    domain_slices = tuple(
        domain_execution_slice(linked.program, execution.id)
        for execution in core_domain_executions(linked.program)
    )
    domain_product_use_ids = frozenset(
        use_id
        for execution_slice in domain_slices
        for use_id in execution_slice.product_use_ids
    )
    local_product_use_ids = tuple(
        use.id
        for use in linked.program.product_uses
        if use.id not in domain_product_use_ids
    )
    local_required = bool(
        local_product_use_ids
        or linked.program.route_intents
        or linked.program.compute_nodes
        or core_state(linked.program)
        or core_actions(linked.program)
    )
    unplaced_transforms = tuple(
        transform
        for transform in linked.program.measurement_transforms
        if all(
            transform not in execution_slice.transforms
            for execution_slice in domain_slices
        )
    )
    placement_problems = list(
        _placement_problems(
            has_domain_call=bool(core_domain_executions(linked.program)),
            has_domain_compiler=bool(backend.domain_compilers),
            local_required=local_required,
            has_local_provider=backend.provider is not None,
            unplaced_transforms=unplaced_transforms,
        )
    )
    if placement_problems:
        raise CheckFailed(placement_problems)
    local_effects = _prepare_local_effects(
        backend,
        linked_points,
        config=config,
        product_use_ids=local_product_use_ids,
        required=local_required,
    )
    barrier_regions = _plan_barrier_regions(
        linked_points,
        local_effects=local_effects,
    )
    selected_compilers = tuple(
        selected
        for execution in core_domain_executions(linked.program)
        if (
            selected := _select_domain_compiler(
                backend.domain_compilers,
                linked_points,
                barrier_regions,
                execution_id=execution.id,
            )
        )
        is not None
    )
    problems: list[Problem] = []
    selected_execution_ids = {
        selected.projection.execution_id for selected in selected_compilers
    }
    problems.extend(
        _planning_problem(
            "domain_compiler_missing",
            f"no configured domain compiler accepts domain call {execution.id!r}",
            category=ProblemCategory.NOT_FOUND,
            details={"execution_id": execution.id},
        )
        for execution in core_domain_executions(linked.program)
        if execution.id not in selected_execution_ids
    )
    if problems:
        raise CheckFailed(problems)

    domain_jobs = tuple(
        job for selected in selected_compilers for job in _prepare_domain_jobs(selected)
    )
    jobs_by_region: dict[int, list[RunDomainJob]] = {
        region_ordinal: [] for region_ordinal, _region in enumerate(barrier_regions)
    }
    for job in domain_jobs:
        region_ordinal = next(
            ordinal
            for ordinal, region in enumerate(barrier_regions)
            if job.point_indices[0] in region.point_indices
        )
        jobs_by_region[region_ordinal].append(job)
    point_regions = tuple(
        RunPointRegion(
            point_indices=region.point_indices,
            domain_jobs=tuple(jobs_by_region[region_ordinal]),
        )
        for region_ordinal, region in enumerate(barrier_regions)
    )
    values = select_measurement_values(
        linked_points,
        required_product_use_ids=tuple(use.id for use in linked.product_uses),
    )
    projection = bind_measurement_projection(
        select_measurement_projection(linked_points),
        values,
    )
    resource_claims = tuple(
        sorted(
            {
                *(() if local_effects is None else local_effects.resource_claims),
                *(claim for job in domain_jobs for claim in job.resource_claims),
            },
            key=lambda claim: (claim.kind, claim.id),
        )
    )
    return RunProgram(
        backend_id=backend.backend_id,
        linked_points=linked_points,
        operations=(
            *((local_effects,) if local_effects is not None else ()),
            *point_regions,
        ),
        values=values,
        projection=projection,
        resource_claims=resource_claims,
    )


@dataclass(frozen=True, slots=True)
class _SelectedDomainCompiler:
    unit_id: str
    compiler: DomainCompiler = field(repr=False, compare=False)
    request: DomainCompileRequest = field(repr=False, compare=False)
    compilation: DomainCompilation = field(repr=False)
    product_use_ids: tuple[ProductUseId, ...]
    projection: DomainPlanProjection = field(repr=False, compare=False)


def _select_domain_compiler(
    compilers: tuple[DomainCompiler, ...],
    linked_points: MaterializedLinkedPoints,
    barrier_regions: tuple[MaterializedLinkedPointBatch, ...],
    *,
    execution_id: str,
) -> _SelectedDomainCompiler | None:
    selected: list[_SelectedDomainCompiler] = []
    seen_ids: set[str] = set()
    projection = project_domain_plan(linked_points, execution_id)
    view = projection.view(linked_points)
    if view.execution is None:
        return None
    request = make_domain_compile_request(projection, barrier_regions)
    for compiler in compilers:
        compiler_id = compiler.compiler_id
        target_id = compiler.target_id
        if type(compiler_id) is not str or not compiler_id:
            msg = "domain compiler identity must be a non-empty string"
            raise TypeError(msg)
        if type(target_id) is not str or not target_id:
            msg = "domain target identity must be a non-empty string"
            raise TypeError(msg)
        if compiler_id in seen_ids:
            msg = f"domain compiler identity {compiler_id!r} is repeated"
            raise ValueError(msg)
        seen_ids.add(compiler_id)
        candidate = compiler.compile(request)
        if candidate is None:
            continue
        if candidate.compiler_id != compiler_id or candidate.target_id != target_id:
            msg = "domain compilation identity must match its selected compiler"
            raise ValueError(msg)
        validate_domain_compilation(request, candidate)
        execution_slice = projection.execution_slice()
        selected.append(
            _SelectedDomainCompiler(
                unit_id=f"domain-{execution_id}-{target_id}",
                compiler=compiler,
                request=request,
                compilation=candidate,
                product_use_ids=execution_slice.product_use_ids,
                projection=projection,
            )
        )
    if len(selected) > 1:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_compiler_selection_ambiguous",
                    f"multiple compilers selected domain execution {execution_id!r}",
                    category=ProblemCategory.CONFLICT,
                    details={
                        "compiler_ids": [
                            candidate.compilation.compiler_id for candidate in selected
                        ],
                        "execution_id": execution_id,
                    },
                )
            ]
        )
    return selected[0] if selected else None


def _prepare_local_effects(
    backend: ExecutionBackend,
    linked_points: MaterializedLinkedPoints,
    *,
    config: ConfigProfileSnapshot,
    product_use_ids: tuple[ProductUseId, ...],
    required: bool,
) -> RunLocalEffects | None:
    if not required:
        return None
    if backend.provider is None:
        raise AssertionError("local placement must require a provider before lowering")
    semantics = materialize_local_semantics_from_points(
        linked_points,
        product_use_ids=frozenset(product_use_ids),
    )
    if not semantics.valid:
        raise CheckFailed(semantics.problems)
    return lower_run_local_effects(
        operation_id=_POINT_UNIT_ID,
        product_use_ids=product_use_ids,
        config=config,
        semantics=semantics,
        instrument_provider=backend.provider,
    )


def _plan_barrier_regions(
    linked_points: MaterializedLinkedPoints,
    *,
    local_effects: RunLocalEffects | None,
) -> tuple[MaterializedLinkedPointBatch, ...]:
    points = linked_points.point_domain.points
    if not points:
        return ()
    if local_effects is None:
        return (MaterializedLinkedPointBatch(linked_points, tuple(range(len(points)))),)
    signatures = tuple(
        tuple(
            (operation.instrument_id, operation.targets)
            for stage in point.stages
            if isinstance(stage, ApplyStateStage)
            for operation in stage.operations
        )
        for point in local_effects.points
    )
    if len(signatures) != len(points):
        raise AssertionError("local and linked point inventories must agree")
    has_actions = any(
        isinstance(stage, ActionStage)
        for point in local_effects.points
        for stage in point.stages
    )
    if not has_actions and all(signature == signatures[0] for signature in signatures):
        return (
            MaterializedLinkedPointBatch(
                linked_points,
                tuple(range(len(points))),
            ),
        )
    return tuple(
        MaterializedLinkedPointBatch(linked_points, (point_index,))
        for point_index in range(len(points))
    )


def _prepare_domain_jobs(
    selected: _SelectedDomainCompiler,
) -> tuple[RunDomainJob, ...]:
    jobs: list[RunDomainJob] = []
    for batch_ordinal, compiled in enumerate(selected.compilation.jobs):
        batch = MaterializedLinkedPointBatch(
            selected.projection.linked_points,
            point_indices=compiled.point_ordinals,
        )
        context = make_domain_batch_context(
            selected.projection,
            batch,
            compiler_id=selected.compilation.compiler_id,
            batch_ordinal=batch_ordinal,
            pushed_transform_ids=selected.compilation.pushed_transform_ids,
        )
        prepared = selected.compiler.prepare(compiled, context)
        if prepared.context is not context:
            msg = "prepared domain execution must retain its compiler job context"
            raise ValueError(msg)
        jobs.append(
            RunDomainJob(
                id=f"{selected.projection.execution_id}:{compiled.id}",
                source_id=selected.unit_id,
                compiled=compiled,
                prepared=prepared,
            )
        )
    return tuple(jobs)


def _placement_problems(
    *,
    has_domain_call: bool,
    has_domain_compiler: bool,
    local_required: bool,
    has_local_provider: bool,
    unplaced_transforms: tuple[TypedMeasurementTransform, ...],
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
            "measurement_transform_placement_missing",
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
        for transform in unplaced_transforms
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
        location=model_location("execution_backend"),
        details=details or {},
    )
