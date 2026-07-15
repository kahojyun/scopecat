"""Public execution-backend selection and unified plan boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from scopecat.compiler.linking.bound import BoundPlan
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.typed.program import TypedProgram
from scopecat.execution.local.executor import PreparedExecution, prepare_execution
from scopecat.execution.local.program import ApplyStateStage, ComputeStage
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
    BoundMeasurementProjection,
    bind_measurement_projection,
    select_measurement_projection,
)
from scopecat.measurements.values import (
    ProductValueFragmentDef,
    SelectedMeasurementValueAssembly,
    select_measurement_value_assembly,
)
from scopecat.planning.coverage import (
    ExecutionCoverage,
    ExecutionResourceClaim,
    ExecutionTask,
    program_execution_coverage,
)
from scopecat.planning.domain_placement import domain_call_execution_slices
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain._bridge import (
    DomainPlanProjection,
    make_domain_batch_context,
    offered_call,
    project_domain_plan,
)
from scopecat.sdk.domain.context import DomainExecutionOffer
from scopecat.sdk.domain.execution import (
    DomainExecutionAdapter,
    PreparedDomainExecution,
)
from scopecat.sdk.instruments.contracts import InstrumentProvider

_POINT_UNIT_ID = "point-instrument"

type FusionMode = Literal["automatic", "disabled"]


@dataclass(frozen=True, slots=True)
class ExecutionOptions:
    """Per-experiment policy limiting cross-point target fusion."""

    fusion: FusionMode = "automatic"
    max_points_per_batch: int | None = None

    def __post_init__(self) -> None:
        if self.fusion not in {"automatic", "disabled"}:
            msg = "execution fusion must be 'automatic' or 'disabled'"
            raise ValueError(msg)
        maximum = self.max_points_per_batch
        if maximum is not None and (type(maximum) is not int or maximum <= 0):
            msg = "execution max_points_per_batch must be a positive integer"
            raise ValueError(msg)
        if self.fusion == "disabled" and maximum not in {None, 1}:
            msg = "disabled execution fusion cannot use a batch limit above one"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PreparedPointInstrumentUnit:
    """Prepared point-local host compute and instrument effects."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]
    bound_plan: BoundPlan = field(repr=False)
    prepared: PreparedExecution = field(repr=False)
    provider: InstrumentProvider = field(repr=False, compare=False)

    @property
    def resource_claims(self) -> tuple[ExecutionResourceClaim, ...]:
        return tuple(
            ExecutionResourceClaim(claim.kind, claim.id)
            for claim in self.prepared.program.resource_claims
        )


@dataclass(frozen=True, slots=True)
class PreparedDomainJob:
    """One physical domain invocation for a contiguous logical-point batch."""

    id: str
    prepared: PreparedDomainExecution = field(repr=False)

    @property
    def point_indices(self) -> tuple[int, ...]:
        return self.prepared.context.linked_points.point_indices

    @property
    def resource_claims(self) -> tuple[ExecutionResourceClaim, ...]:
        claims = self.prepared.resource_claims
        if claims:
            return claims
        return (
            ExecutionResourceClaim(
                "target",
                self.prepared.invocation.intent.target_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedDomainUnit:
    """One product-owning adapter lane containing ordered physical jobs."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]
    jobs: tuple[PreparedDomainJob, ...]

    @property
    def resource_claims(self) -> tuple[ExecutionResourceClaim, ...]:
        return tuple(
            sorted(
                {claim for job in self.jobs for claim in job.resource_claims},
                key=lambda claim: (claim.kind, claim.id),
            )
        )


@dataclass(frozen=True, slots=True)
class PreparedExecutionSegment:
    """One local-state-stable point segment and its independently batched jobs."""

    point_indices: tuple[int, ...]
    domain_jobs: tuple[PreparedDomainJob, ...]


type _PreparedExecutionUnit = PreparedPointInstrumentUnit | PreparedDomainUnit


@dataclass(frozen=True, slots=True)
class PreparedExecutionPlan:
    """Trusted exact-cover plan consumed by the unified run workflow."""

    backend_id: str
    linked_points: MaterializedLinkedPoints = field(repr=False)
    point_unit: PreparedPointInstrumentUnit | None
    domain_units: tuple[PreparedDomainUnit, ...]
    segments: tuple[PreparedExecutionSegment, ...]
    value_assembly: SelectedMeasurementValueAssembly = field(repr=False)
    projection: BoundMeasurementProjection = field(repr=False)
    resource_claims: tuple[ExecutionResourceClaim, ...]


@dataclass(frozen=True, slots=True)
class ExecutionBackend:
    """The single backend combining point instruments and domain adapters."""

    provider: InstrumentProvider | None = field(default=None, repr=False)
    domain_adapters: tuple[DomainExecutionAdapter, ...] = field(
        default=(),
        repr=False,
    )
    id: str = "scopecat.execution.v2"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "execution backend id must be non-empty"
            raise ValueError(msg)
        adapters = tuple(self.domain_adapters)
        if self.provider is None and not adapters:
            msg = "execution backend requires a provider or domain adapter"
            raise ValueError(msg)
        object.__setattr__(self, "domain_adapters", adapters)

    @property
    def backend_id(self) -> str:
        return self.id

    def prepare(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
        options: ExecutionOptions | None = None,
    ) -> PreparedExecutionPlan:
        selected_options = ExecutionOptions() if options is None else options
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
            options=selected_options,
        )


def _prepare_backend_plan(
    *,
    backend: ExecutionBackend,
    linked: LinkedPlan,
    config: ConfigProfileSnapshot,
    options: ExecutionOptions,
) -> PreparedExecutionPlan:
    expected = program_execution_coverage(linked.program)
    linked_points = materialize_linked_points(linked)
    selected_adapters = _select_domain_adapters(
        backend.domain_adapters,
        linked_points,
    )
    domain_task_owners = {
        task for selected in selected_adapters for task in selected.coverage.tasks
    }
    domain_lane_product_use_ids = {
        use_id.value
        for use_ids in (
            *(
                result.product_use_ids
                for call in linked.program.domain_calls
                for result in call.results
            ),
            *(
                output.product_use_ids
                for transform in linked.program.measurement_transforms
                for output in transform.outputs
            ),
        )
        for use_id in use_ids
    }
    local_coverage = ExecutionCoverage(
        tuple(
            task
            for task in expected.tasks
            if task not in domain_task_owners
            and task.kind != "domain_call"
            and task.kind != "measurement_transform"
            and not (task.kind == "product" and task.id in domain_lane_product_use_ids)
        )
    )
    point_unit = _prepare_point_unit(
        backend,
        linked,
        config=config,
        coverage=local_coverage,
    )
    covered_units = (
        *(((_POINT_UNIT_ID, local_coverage),) if point_unit is not None else ()),
        *((selected.unit_id, selected.coverage) for selected in selected_adapters),
    )
    problems = list(
        _coverage_problems(
            expected,
            covered_units,
            program=linked.program,
        )
    )
    problems.extend(
        domain_call_affinity_problems(
            linked.program,
            tuple(
                (selected.unit_id, selected.coverage) for selected in selected_adapters
            ),
        )
    )
    if point_unit is not None and selected_adapters:
        problems.extend(_mixed_lane_point_shape_problems(point_unit))
    if problems:
        raise CheckFailed(problems)

    resolved_maximum = _resolved_batch_limit(
        options,
        has_domains=bool(selected_adapters),
    )
    state_segments = _plan_state_segments(
        linked_points,
        point_unit=point_unit,
    )
    domain_units = _prepare_domain_units(
        selected_adapters,
        state_segments,
        maximum=resolved_maximum,
    )
    units: tuple[_PreparedExecutionUnit, ...] = (
        *((point_unit,) if point_unit is not None else ()),
        *domain_units,
    )
    resource_problems = _resource_claim_problems(units)
    if resource_problems:
        raise CheckFailed(resource_problems)

    jobs_by_batch: dict[int, list[PreparedDomainJob]] = {
        segment_ordinal: [] for segment_ordinal, _segment in enumerate(state_segments)
    }
    for unit in domain_units:
        for job in unit.jobs:
            segment_ordinal = next(
                ordinal
                for ordinal, segment in enumerate(state_segments)
                if job.point_indices[0] in segment.point_indices
            )
            jobs_by_batch[segment_ordinal].append(job)
    segments = tuple(
        PreparedExecutionSegment(
            point_indices=segment.point_indices,
            domain_jobs=tuple(jobs_by_batch[segment_ordinal]),
        )
        for segment_ordinal, segment in enumerate(state_segments)
    )
    fragment_defs = tuple(
        ProductValueFragmentDef(unit.id, unit.product_use_ids)
        for unit in units
        if unit.product_use_ids
    )
    value_assembly = select_measurement_value_assembly(
        linked_points,
        required_product_use_ids=tuple(use.id for use in linked.product_uses),
        fragment_defs=fragment_defs,
    )
    projection = bind_measurement_projection(
        select_measurement_projection(linked_points),
        value_assembly,
    )
    resource_claims = tuple(
        sorted(
            (claim for unit in units for claim in unit.resource_claims),
            key=lambda claim: (claim.kind, claim.id),
        )
    )
    return PreparedExecutionPlan(
        backend_id=backend.backend_id,
        linked_points=linked_points,
        point_unit=point_unit,
        domain_units=domain_units,
        segments=segments,
        value_assembly=value_assembly,
        projection=projection,
        resource_claims=resource_claims,
    )


@dataclass(frozen=True, slots=True)
class _SelectedDomainAdapter:
    unit_id: str
    adapter_id: str
    adapter: DomainExecutionAdapter = field(repr=False, compare=False)
    offer: DomainExecutionOffer
    coverage: ExecutionCoverage
    direct_product_use_ids: tuple[ProductUseId, ...]
    projection: DomainPlanProjection = field(repr=False, compare=False)


def _select_domain_adapters(
    adapters: tuple[DomainExecutionAdapter, ...],
    linked_points: MaterializedLinkedPoints,
) -> tuple[_SelectedDomainAdapter, ...]:
    selected: list[_SelectedDomainAdapter] = []
    seen_ids: set[str] = set()
    projection = project_domain_plan(linked_points)
    view = projection.view(linked_points)
    for adapter_index, adapter in enumerate(adapters):
        adapter_id = adapter.adapter_id
        if type(adapter_id) is not str or not adapter_id:
            msg = "domain execution adapter identity must be a non-empty string"
            raise TypeError(msg)
        if adapter_id in seen_ids:
            msg = f"domain execution adapter identity {adapter_id!r} is repeated"
            raise ValueError(msg)
        seen_ids.add(adapter_id)
        candidate = cast("object", adapter.select(view))
        if candidate is None:
            continue
        if not isinstance(candidate, DomainExecutionOffer):
            msg = (
                "domain execution adapter select must return "
                "DomainExecutionOffer or None"
            )
            raise TypeError(msg)
        call = offered_call(view, candidate)
        candidate = DomainExecutionOffer.for_call(
            call,
            max_points_per_batch=candidate.max_points_per_batch,
        )
        execution_slice = projection.execution_slice(call)
        selected.append(
            _SelectedDomainAdapter(
                unit_id=f"domain-program-{adapter_index}-{adapter_id}",
                adapter_id=adapter_id,
                adapter=adapter,
                offer=candidate,
                coverage=execution_slice.coverage,
                direct_product_use_ids=execution_slice.direct_product_use_ids,
                projection=projection,
            )
        )
    return tuple(selected)


def _prepare_point_unit(
    backend: ExecutionBackend,
    linked: LinkedPlan,
    *,
    config: ConfigProfileSnapshot,
    coverage: ExecutionCoverage,
) -> PreparedPointInstrumentUnit | None:
    if not coverage.tasks or backend.provider is None:
        return None
    product_use_ids = coverage.product_use_ids
    non_product_coverage = ExecutionCoverage(
        tuple(task for task in coverage.tasks if task.kind != "product")
    )
    plan = materialize_local_plan(
        linked,
        product_use_ids=frozenset(product_use_ids),
        task_coverage=non_product_coverage,
    )
    if not plan.valid:
        raise CheckFailed(plan.problems)
    prepared = prepare_execution(
        config=config,
        plan=plan,
        instrument_provider=backend.provider,
    )
    return PreparedPointInstrumentUnit(
        id=_POINT_UNIT_ID,
        product_use_ids=coverage.product_use_ids,
        bound_plan=plan,
        prepared=prepared,
        provider=backend.provider,
    )


def _resolved_batch_limit(
    options: ExecutionOptions,
    *,
    has_domains: bool,
) -> int | None:
    if not has_domains:
        return 1
    if options.fusion == "disabled":
        return 1
    return options.max_points_per_batch


def _plan_state_segments(
    linked_points: MaterializedLinkedPoints,
    *,
    point_unit: PreparedPointInstrumentUnit | None,
) -> tuple[MaterializedLinkedPointBatch, ...]:
    points = linked_points.point_domain.points
    if not points:
        return ()
    signatures = (
        (None,) * len(points)
        if point_unit is None
        else tuple(
            tuple(
                (operation.instrument_id, operation.targets)
                for stage in point.stages
                if isinstance(stage, ApplyStateStage)
                for operation in stage.operations
            )
            for point in point_unit.prepared.program.points
        )
    )
    if len(signatures) != len(points):
        raise AssertionError("local and linked point inventories must agree")
    selected: list[MaterializedLinkedPointBatch] = []
    start = 0
    while start < len(points):
        stop = start + 1
        while stop < len(points) and signatures[stop] == signatures[start]:
            stop += 1
        selected.append(
            MaterializedLinkedPointBatch(
                linked_points,
                point_indices=tuple(range(start, stop)),
            )
        )
        start = stop
    return tuple(selected)


def _prepare_domain_units(
    selected_adapters: tuple[_SelectedDomainAdapter, ...],
    state_segments: tuple[MaterializedLinkedPointBatch, ...],
    *,
    maximum: int | None,
) -> tuple[PreparedDomainUnit, ...]:
    units: list[PreparedDomainUnit] = []
    for selected in selected_adapters:
        jobs: list[PreparedDomainJob] = []
        adapter_maximum = selected.offer.max_points_per_batch
        limits = tuple(
            limit for limit in (maximum, adapter_maximum) if limit is not None
        )
        chunk_size = min(limits) if limits else None
        batches = tuple(
            MaterializedLinkedPointBatch(
                segment.parent,
                point_indices=tuple(
                    segment.point_indices[offset : offset + selected_chunk_size]
                ),
            )
            for segment in state_segments
            for selected_chunk_size in (
                len(segment.point_indices) if chunk_size is None else chunk_size,
            )
            for offset in range(0, len(segment.point_indices), selected_chunk_size)
        )
        for batch_ordinal, batch in enumerate(batches):
            context = make_domain_batch_context(
                selected.projection,
                batch,
                selected.offer,
                adapter_id=selected.adapter_id,
                batch_ordinal=batch_ordinal,
            )
            prepared_candidate = cast("object", selected.adapter.prepare(context))
            if not isinstance(prepared_candidate, PreparedDomainExecution):
                msg = "domain execution adapter must return PreparedDomainExecution"
                raise TypeError(msg)
            prepared = prepared_candidate
            if prepared.adapter_id != selected.adapter_id:
                msg = "prepared domain execution lost its adapter identity"
                raise ValueError(msg)
            if prepared.semantic_operation_id != selected.offer.call_id:
                msg = (
                    "prepared domain execution semantic_operation_id must equal "
                    "its claimed domain call id"
                )
                raise ValueError(msg)
            if prepared.context is not context:
                msg = "prepared domain execution must retain its requested context"
                raise ValueError(msg)
            if len(prepared.product_uses) != len(context.product_uses) or any(
                prepared_use is not context_use
                for prepared_use, context_use in zip(
                    prepared.product_uses,
                    context.product_uses,
                    strict=True,
                )
            ):
                msg = "prepared domain execution changed its product ownership"
                raise ValueError(msg)
            if len(prepared.direct_product_uses) != len(
                context.direct_product_uses
            ) or any(
                prepared_use is not context_use
                for prepared_use, context_use in zip(
                    prepared.direct_product_uses,
                    context.direct_product_uses,
                    strict=True,
                )
            ):
                msg = "prepared domain execution changed its direct product ownership"
                raise ValueError(msg)
            jobs.append(
                PreparedDomainJob(
                    id=(f"{selected.unit_id}.batch-{batch_ordinal}"),
                    prepared=prepared,
                )
            )
        units.append(
            PreparedDomainUnit(
                id=selected.unit_id,
                product_use_ids=selected.coverage.product_use_ids,
                jobs=tuple(jobs),
            )
        )
    return tuple(units)


def _coverage_problems(
    expected: ExecutionCoverage,
    units: tuple[tuple[str, ExecutionCoverage], ...],
    *,
    program: TypedProgram,
) -> tuple[Problem, ...]:
    expected_set = set(expected.tasks)
    owners: dict[ExecutionTask, list[str]] = {}
    for unit_id, coverage in units:
        for task in coverage.tasks:
            owners.setdefault(task, []).append(unit_id)
    unplaced_transforms = tuple(
        transform
        for transform in program.measurement_transforms
        if ExecutionTask(
            "measurement_transform",
            transform.id.qualified_name,
        )
        not in owners
    )
    grouped_missing_tasks = {
        ExecutionTask("measurement_transform", transform.id.qualified_name)
        for transform in unplaced_transforms
    } | {
        ExecutionTask("product", use_id.value)
        for transform in unplaced_transforms
        for output in transform.outputs
        for use_id in output.product_use_ids
    }

    problems: list[Problem] = []
    for task, unit_ids in owners.items():
        if task not in expected_set:
            problems.append(
                _planning_problem(
                    "execution_task_claim_foreign",
                    f"execution unit claims unknown {task.kind} task {task.id!r}",
                    category=ProblemCategory.CONFLICT,
                    details={"task_kind": task.kind, "task_id": task.id},
                )
            )
        if len(unit_ids) > 1:
            problems.append(
                _planning_problem(
                    "execution_task_claim_overlap",
                    f"execution task {task.kind}:{task.id} has multiple owners",
                    category=ProblemCategory.CONFLICT,
                    details={"unit_ids": unit_ids},
                )
            )
    for task in expected.tasks:
        if task not in owners and task not in grouped_missing_tasks:
            problems.append(
                _planning_problem(
                    "execution_task_claim_missing",
                    f"execution task {task.kind}:{task.id} has no owner",
                    category=ProblemCategory.NOT_FOUND,
                    details={"task_kind": task.kind, "task_id": task.id},
                )
            )
    problems.extend(
        _planning_problem(
            "measurement_transform_placement_missing",
            f"measurement transform {transform.id.qualified_name!r} has no "
            "execution owner; current domain lanes can host only a transform "
            "closure fed wholly by one selected domain call",
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


def domain_call_affinity_problems(
    program: TypedProgram,
    domain_owners: tuple[tuple[str, ExecutionCoverage], ...],
) -> tuple[Problem, ...]:
    """Keep one call and all of its demanded results on one adapter lane."""

    owners: dict[ExecutionTask, list[str]] = {}
    for unit_id, coverage in domain_owners:
        for task in coverage.tasks:
            owners.setdefault(task, []).append(unit_id)
    problems: list[Problem] = []
    for execution_slice in domain_call_execution_slices(program):
        tasks = (
            ExecutionTask(
                "domain_call",
                execution_slice.call_id.qualified_name,
            ),
            *(
                ExecutionTask("product", use_id.value)
                for use_id in execution_slice.direct_product_use_ids
            ),
        )
        task_owners = tuple(owners.get(task, []) for task in tasks)
        # Missing and overlapping tasks are diagnosed by exact coverage first.
        if any(len(selected) != 1 for selected in task_owners):
            continue
        unit_ids = {selected[0] for selected in task_owners}
        if len(unit_ids) > 1:
            problems.append(
                _planning_problem(
                    "domain_call_result_affinity_split",
                    f"domain call {execution_slice.call_id.qualified_name!r} "
                    "and its demanded "
                    "product uses must have one domain execution owner",
                    category=ProblemCategory.CONFLICT,
                    details={
                        "domain_call_id": execution_slice.call_id.qualified_name,
                        "unit_ids": sorted(unit_ids),
                    },
                )
            )
    return tuple(problems)


def _resource_claim_problems(
    units: tuple[_PreparedExecutionUnit, ...],
) -> tuple[Problem, ...]:
    owners: dict[ExecutionResourceClaim, list[str]] = {}
    for unit in units:
        for claim in unit.resource_claims:
            owners.setdefault(claim, []).append(unit.id)
    return tuple(
        _planning_problem(
            "execution_resource_claim_overlap",
            f"execution resource {claim.kind}:{claim.id} has multiple owners",
            category=ProblemCategory.CONFLICT,
            details={"unit_ids": unit_ids},
        )
        for claim, unit_ids in owners.items()
        if len(unit_ids) > 1
    )


def _mixed_lane_point_shape_problems(
    unit: PreparedPointInstrumentUnit,
) -> tuple[Problem, ...]:
    """Prove the current local stages can surround ordered domain batches."""

    program = unit.prepared.program
    problems: list[Problem] = []
    compute_count = sum(
        len(stage.operations)
        for point in program.points
        for stage in point.stages
        if isinstance(stage, ComputeStage)
    )
    if compute_count:
        problems.append(
            _planning_problem(
                "mixed_lane_point_compute_crosses_domain_job",
                "point-local compute cannot surround a fused domain job",
                details={"compute_operation_count": compute_count},
            )
        )
    action_count = sum(
        len(stage.operations)
        for point in program.points
        for stage in point.stages
        if stage.kind == "action"
    )
    if action_count:
        problems.append(
            _planning_problem(
                "mixed_lane_point_action_crosses_domain_job",
                "point-local one-shot actions cannot cross a fused domain job",
                details={"action_operation_count": action_count},
            )
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


__all__ = [
    "ExecutionBackend",
    "ExecutionOptions",
    "FusionMode",
    "PreparedDomainJob",
    "PreparedDomainUnit",
    "PreparedExecutionPlan",
    "PreparedExecutionSegment",
    "PreparedPointInstrumentUnit",
]
