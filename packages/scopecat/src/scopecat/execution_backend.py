"""Public execution-backend selection and composite plan boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, cast

from scopecat._compiler.binding import materialize_local_plan
from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat._compiler.run_plan import (
    build_domain_run_plan_record,
    build_run_plan_record,
)
from scopecat._execution.executor import PreparedExecution, prepare_execution
from scopecat._execution.program import ApplyStateStage, ComputeStage
from scopecat._product_identity import ProductUseId
from scopecat.domain_execution import (
    DomainExecutionAdapter,
    PreparedDomainExecution,
    project_domain_run_plan_execution,
)
from scopecat.errors import CheckFailed
from scopecat.execution_coverage import (
    ExecutionCoverage,
    ExecutionResourceClaim,
    ExecutionTask,
    product_execution_coverage,
    program_execution_coverage,
)
from scopecat.instruments.sdk import InstrumentProvider
from scopecat.measurement_projection import (
    BoundMeasurementProjection,
    bind_measurement_projection,
    select_measurement_projection,
)
from scopecat.measurement_values import (
    ProductValueFragmentDef,
    SelectedMeasurementValueAssembly,
    select_measurement_value_assembly,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run_plan import (
    RunPlanDomainExecution,
    RunPlanOutput,
    RunPlanPointInstrumentExecution,
    RunPlanProducerKind,
    RunPlanRecord,
)
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

_POINT_UNIT_ID = "point-instrument"


@dataclass(frozen=True, slots=True)
class PreparedPointInstrumentUnit:
    """Prepared point-local host compute and instrument effects."""

    id: str
    backend_id: str
    coverage: ExecutionCoverage
    bound_plan: BoundPlan = field(repr=False)
    prepared: PreparedExecution = field(repr=False)
    provider: InstrumentProvider = field(repr=False, compare=False)

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return self.coverage.product_use_ids

    @property
    def resource_claims(self) -> tuple[ExecutionResourceClaim, ...]:
        return tuple(
            ExecutionResourceClaim(claim.kind, claim.id)
            for claim in self.prepared.program.resource_claims
        )


@dataclass(frozen=True, slots=True)
class PreparedDomainJobUnit:
    """One closed domain-program invocation in a composite plan."""

    id: str
    backend_id: str
    coverage: ExecutionCoverage
    prepared: PreparedDomainExecution = field(repr=False)

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return self.coverage.product_use_ids

    @property
    def resource_claims(self) -> tuple[ExecutionResourceClaim, ...]:
        if self.prepared.resource_claims:
            return self.prepared.resource_claims
        return (
            ExecutionResourceClaim(
                "target",
                self.prepared.invocation.intent.target_id,
            ),
        )


type PreparedExecutionUnit = PreparedPointInstrumentUnit | PreparedDomainJobUnit


@dataclass(frozen=True, slots=True)
class PreparedExecutionPlan:
    """Trusted exact-cover plan consumed by the unified run workflow."""

    backend_id: str
    linked_points: MaterializedLinkedPoints = field(repr=False)
    units: tuple[PreparedExecutionUnit, ...]
    coverage: ExecutionCoverage
    value_assembly: SelectedMeasurementValueAssembly = field(repr=False)
    projection: BoundMeasurementProjection = field(repr=False)
    resource_claims: tuple[ExecutionResourceClaim, ...]

    @property
    def point_unit(self) -> PreparedPointInstrumentUnit | None:
        return next(
            (
                unit
                for unit in self.units
                if isinstance(unit, PreparedPointInstrumentUnit)
            ),
            None,
        )

    @property
    def domain_units(self) -> tuple[PreparedDomainJobUnit, ...]:
        return tuple(
            unit for unit in self.units if isinstance(unit, PreparedDomainJobUnit)
        )

    def run_plan_record(self) -> RunPlanRecord:
        """Project the exact selected unit graph into durable evidence."""

        point = self.point_unit
        domains = self.domain_units
        point_execution = (
            RunPlanPointInstrumentExecution(
                unit_id=point.id,
                backend_id=point.backend_id,
                provider_id=point.prepared.provider_id,
            )
            if point is not None
            else None
        )
        if not domains:
            if point is None or point_execution is None:
                raise AssertionError("prepared execution plan lost every unit")
            return build_run_plan_record(
                point.bound_plan,
                execution=point_execution,
            )

        domain_executions = tuple(
            project_domain_run_plan_execution(unit.prepared, unit_id=unit.id)
            for unit in domains
        )
        base = build_domain_run_plan_record(
            self.linked_points,
            self.projection,
            execution=domain_executions[0],
            domain_product_use_ids=frozenset(
                use_id
                for unit in domains
                for use_id in unit.prepared.domain_product_use_ids
            ),
        )
        local = (
            build_run_plan_record(point.bound_plan, execution=point_execution)
            if point is not None and point_execution is not None
            else None
        )
        owner_by_use = {
            use_id: unit for unit in self.units for use_id in unit.product_use_ids
        }
        local_outputs = (
            {} if local is None else {output.id: output for output in local.records}
        )
        records: list[RunPlanOutput] = []
        for record_plan, output in zip(
            self.projection.projection.records,
            base.records,
            strict=True,
        ):
            owner = owner_by_use[record_plan.product_use_id]
            producer_kind: RunPlanProducerKind
            if isinstance(owner, PreparedPointInstrumentUnit):
                producer_kind = "instrument"
                retained_output = local_outputs.get(record_plan.id)
                if retained_output is None:
                    raise AssertionError(
                        "point-owned output is missing from its local run plan"
                    )
            elif record_plan.product_use_id in owner.prepared.domain_product_use_ids:
                producer_kind = "domain"
                retained_output = output
            else:
                producer_kind = "host_transform"
                retained_output = output
            records.append(
                retained_output.model_copy(
                    update={
                        "producer_kind": producer_kind,
                        "producer_unit_id": owner.id,
                    }
                )
            )
        execution_units: list[
            RunPlanPointInstrumentExecution | RunPlanDomainExecution
        ] = [
            *((point_execution,) if point_execution is not None else ()),
            *domain_executions,
        ]
        return RunPlanRecord.model_validate(
            {
                **base.model_dump(mode="python"),
                "execution_units": [
                    unit.model_dump(mode="python") for unit in execution_units
                ],
                "records": [record.model_dump(mode="python") for record in records],
                "state_changes": (
                    []
                    if local is None
                    else [
                        change.model_dump(mode="python")
                        for change in local.state_changes
                    ]
                ),
                "routes": (
                    []
                    if local is None
                    else [route.model_dump(mode="python") for route in local.routes]
                ),
            }
        )


class ExecutionBackend(Protocol):
    """Pure selector from one linked program to an exact executable plan."""

    @property
    def backend_id(self) -> str: ...

    def prepare(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
    ) -> PreparedExecutionPlan: ...


@dataclass(frozen=True, slots=True)
class PointInstrumentBackend:
    """Built-in point-at-a-time, host-compute, no-fusion backend."""

    provider: InstrumentProvider = field(repr=False)
    id: str = "scopecat.point-instrument.v1"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "point instrument backend id must be non-empty"
            raise ValueError(msg)

    @property
    def backend_id(self) -> str:
        return self.id

    def prepare(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
    ) -> PreparedExecutionPlan:
        return _prepare_backend_plan(
            backend_id=self.backend_id,
            linked=linked,
            config=config,
            point_backend=self,
            domain_backends=(),
        )

    def prepare_unit(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
        product_use_ids: tuple[ProductUseId, ...],
        non_product_coverage: ExecutionCoverage,
    ) -> PreparedPointInstrumentUnit:
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
            instrument_provider=self.provider,
        )
        products = product_execution_coverage(product_use_ids)
        return PreparedPointInstrumentUnit(
            id=_POINT_UNIT_ID,
            backend_id=self.backend_id,
            coverage=ExecutionCoverage((*non_product_coverage.tasks, *products.tasks)),
            bound_plan=plan,
            prepared=prepared,
            provider=self.provider,
        )


@dataclass(frozen=True, slots=True)
class DomainProgramBackend:
    """Expose one domain adapter as a composable execution backend."""

    adapter: DomainExecutionAdapter = field(repr=False)

    @property
    def backend_id(self) -> str:
        return self.adapter.adapter_id

    def prepare(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
    ) -> PreparedExecutionPlan:
        return _prepare_backend_plan(
            backend_id=self.backend_id,
            linked=linked,
            config=config,
            point_backend=None,
            domain_backends=(self,),
        )

    def prepare_unit(
        self,
        linked: LinkedPlan,
        *,
        ordinal: int,
    ) -> PreparedDomainJobUnit:
        adapter_id = self.adapter.adapter_id
        if type(adapter_id) is not str or not adapter_id:
            msg = "domain execution adapter identity must be a non-empty string"
            raise TypeError(msg)
        prepared_candidate = cast("object", self.adapter.prepare(linked))
        if not isinstance(prepared_candidate, PreparedDomainExecution):
            msg = "domain execution adapter must return PreparedDomainExecution"
            raise TypeError(msg)
        prepared = prepared_candidate
        if prepared.adapter_id != adapter_id:
            msg = "prepared domain execution does not retain its adapter identity"
            raise ValueError(msg)
        return PreparedDomainJobUnit(
            id=f"domain-job-{ordinal}-{adapter_id}",
            backend_id=adapter_id,
            coverage=prepared.coverage,
            prepared=prepared,
        )


@dataclass(frozen=True, slots=True)
class CompositeExecutionBackend:
    """Compose a point backend with zero or more explicit domain jobs."""

    point: PointInstrumentBackend | None = None
    domains: tuple[DomainProgramBackend, ...] = ()
    id: str = "scopecat.composite.v1"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "composite execution backend id must be non-empty"
            raise ValueError(msg)
        if self.point is None and not self.domains:
            msg = "composite execution backend requires at least one target"
            raise ValueError(msg)

    @property
    def backend_id(self) -> str:
        return self.id

    def prepare(
        self,
        linked: LinkedPlan,
        *,
        config: ConfigProfileSnapshot,
    ) -> PreparedExecutionPlan:
        return _prepare_backend_plan(
            backend_id=self.backend_id,
            linked=linked,
            config=config,
            point_backend=self.point,
            domain_backends=self.domains,
        )


def _prepare_backend_plan(
    *,
    backend_id: str,
    linked: LinkedPlan,
    config: ConfigProfileSnapshot,
    point_backend: PointInstrumentBackend | None,
    domain_backends: tuple[DomainProgramBackend, ...],
) -> PreparedExecutionPlan:
    expected = program_execution_coverage(linked.program)
    domain_units = tuple(
        backend.prepare_unit(linked, ordinal=index)
        for index, backend in enumerate(domain_backends)
    )
    _require_domain_plan_identity(linked, domain_units)

    domain_product_ids = {
        use_id for unit in domain_units for use_id in unit.product_use_ids
    }
    local_product_ids = tuple(
        use.id for use in linked.product_uses if use.id not in domain_product_ids
    )
    domain_non_product_tasks = {
        task
        for unit in domain_units
        for task in unit.coverage.tasks
        if task.kind != "product"
    }
    non_product_tasks = ExecutionCoverage(
        tuple(
            task
            for task in expected.tasks
            if task.kind != "product" and task not in domain_non_product_tasks
        )
    )
    point_unit = (
        point_backend.prepare_unit(
            linked,
            config=config,
            product_use_ids=local_product_ids,
            non_product_coverage=non_product_tasks,
        )
        if point_backend is not None and (local_product_ids or non_product_tasks.tasks)
        else None
    )
    units: tuple[PreparedExecutionUnit, ...] = (
        *((point_unit,) if point_unit is not None else ()),
        *domain_units,
    )
    problems = [
        *_coverage_problems(expected, units),
        *_resource_claim_problems(units),
    ]
    if point_unit is not None and domain_units:
        problems.extend(_composite_point_shape_problems(point_unit))
    if problems:
        raise CheckFailed(problems)

    linked_points = (
        domain_units[0].prepared.linked_points
        if domain_units
        else materialize_linked_points(linked)
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
        backend_id=backend_id,
        linked_points=linked_points,
        units=units,
        coverage=expected,
        value_assembly=value_assembly,
        projection=projection,
        resource_claims=resource_claims,
    )


def _require_domain_plan_identity(
    linked: LinkedPlan,
    units: tuple[PreparedDomainJobUnit, ...],
) -> None:
    for unit in units:
        if unit.prepared.linked_points.linked_plan.verified_program is not (
            linked.verified_program
        ):
            msg = "domain execution unit belongs to a different linked program"
            raise ValueError(msg)


def _coverage_problems(
    expected: ExecutionCoverage,
    units: tuple[PreparedExecutionUnit, ...],
) -> tuple[Problem, ...]:
    expected_set = set(expected.tasks)
    owners: dict[ExecutionTask, list[str]] = {}
    for unit in units:
        for task in unit.coverage.tasks:
            owners.setdefault(task, []).append(unit.id)
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
        if task not in owners:
            problems.append(
                _planning_problem(
                    "execution_task_claim_missing",
                    f"execution task {task.kind}:{task.id} has no owner",
                    category=ProblemCategory.NOT_FOUND,
                    details={"task_kind": task.kind, "task_id": task.id},
                )
            )
    return tuple(problems)


def _resource_claim_problems(
    units: tuple[PreparedExecutionUnit, ...],
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


def _composite_point_shape_problems(
    unit: PreparedPointInstrumentUnit,
) -> tuple[Problem, ...]:
    """Prove the local lane can safely surround one fused point-set job."""

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
                "composite_point_compute_crosses_domain_job",
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
                "composite_point_action_crosses_domain_job",
                "point-local one-shot actions cannot cross a fused domain job",
                details={"action_operation_count": action_count},
            )
        )
    state_shapes = tuple(
        tuple(
            (operation.instrument_id, operation.targets)
            for stage in point.stages
            if isinstance(stage, ApplyStateStage)
            for operation in stage.operations
        )
        for point in program.points
    )
    if state_shapes and any(shape != state_shapes[0] for shape in state_shapes[1:]):
        problems.append(
            _planning_problem(
                "composite_point_state_varies_across_domain_job",
                (
                    "point-varying instrument state cannot be hoisted around a "
                    "fused domain job"
                ),
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
    "CompositeExecutionBackend",
    "DomainProgramBackend",
    "ExecutionBackend",
    "PointInstrumentBackend",
    "PreparedDomainJobUnit",
    "PreparedExecutionPlan",
    "PreparedExecutionUnit",
    "PreparedPointInstrumentUnit",
]
