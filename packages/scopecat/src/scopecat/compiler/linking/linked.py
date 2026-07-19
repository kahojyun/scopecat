"""Config-linked symbolic programs before any target materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.diagnostics import CompilerProblemError, compiler_problem
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
    validate_relation_parameter_import,
)
from scopecat.compiler.relations.model import (
    LiteralScalarExpr,
    RelationExpr,
    Row,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.point_domain import PointCardinality
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
)
from scopecat.compiler.typed.parameter_overlays import resolve_point_parameters
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
    MaterializedPointDomain,
    PointDomainEvaluationError,
    PointDomainValueError,
    VerifiedPointDomain,
    materialize_point_domain,
    materialize_point_domain_ordinals,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    MeasurementTransformProductProducer,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedMeasurementTransform,
    ValueInput,
    core_actions,
    core_domain_executions,
    core_state,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.specialization import specialize_core_program
from scopecat.compiler.typed.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumer,
    VerifiedCoreProgram,
    seal_typed_program,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.product_identity import ProductUse
from scopecat.kernel.resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.kernel.value_types import TableColumn
from scopecat.kernel.value_validation import ValueValidationError, coerce_literal
from scopecat.planning.routing import RoutingError, RoutingView
from scopecat.records.entity import EntityRef


@dataclass(frozen=True, slots=True)
class LinkedPlan:
    """A successful config link retaining the complete symbolic point domain.

    The plan binds a backend-neutral, sealed compiler program to one accepted
    configuration environment. Both are trusted transient compiler artifacts;
    the plan owns no materialized points or target artifact.
    """

    verified_program: VerifiedCoreProgram
    environment: ValidatedConfigEnvironment

    @property
    def program(self) -> CoreProgram:
        """Return the sealed compiler program bound to this plan."""

        return self.verified_program.program

    @property
    def point_domain(self) -> VerifiedPointDomain:
        return self.verified_program.point_domain

    @property
    def product_defs(self) -> tuple[ProductDef, ...]:
        return self.program.product_defs

    @property
    def instrument_product_producers(
        self,
    ) -> tuple[InstrumentProductProducer, ...]:
        return self.program.instrument_product_producers

    @property
    def measurement_transforms(self) -> tuple[TypedMeasurementTransform, ...]:
        return self.program.measurement_transforms

    @property
    def measurement_transform_product_producers(
        self,
    ) -> tuple[MeasurementTransformProductProducer, ...]:
        return self.program.measurement_transform_product_producers

    @property
    def product_uses(self) -> tuple[ProductUse, ...]:
        return self.program.product_uses

    @property
    def record_uses(self) -> tuple[RecordUse, ...]:
        return self.program.record_uses

    @property
    def coordinate_columns(self) -> tuple[TableColumn, ...]:
        """Return the statically typed point-coordinate contract."""

        return self.point_domain.coordinate_columns

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return tuple(column.id for column in self.coordinate_columns)

    @property
    def cardinality(self) -> PointCardinality:
        return self.point_domain.cardinality


@dataclass(frozen=True, slots=True)
class MaterializedLinkedPoints:
    """One linked plan with canonical points and parameter bindings.

    Domain inputs are deliberately absent. Selected compilers decide which
    residual columns must be evaluated for each compiled job.
    """

    linked_plan: LinkedPlan
    point_domain: MaterializedPointDomain
    point_parameters: tuple[ParameterRelationData, ...]

    def __post_init__(self) -> None:
        if len(self.point_parameters) != len(self.point_domain.points):
            msg = "materialized points and parameter bindings must have equal length"
            raise ValueError(msg)

    @property
    def verified_program(self) -> VerifiedCoreProgram:
        return self.linked_plan.verified_program


def materialize_linked_points(
    linked: LinkedPlan,
    *,
    max_points: int | None = None,
) -> MaterializedLinkedPoints:
    """Materialize the logical point domain and parameter bindings.

    Expected point-evaluation, value, and entity errors cross this planning
    boundary as structured :class:`CheckFailed` problems.
    """

    return LinkedPointMaterializer(linked, max_points=max_points).materialize()


@dataclass(slots=True)
class LinkedPointMaterializer:
    """Budgeted shared closure of one linked symbolic point space."""

    linked: LinkedPlan
    max_points: int | None = None
    _point_domain: MaterializedPointDomain | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _point_parameters: dict[int, ParameterRelationData] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _selected_points: dict[int, MaterializedPoint] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _domain_input_values: dict[tuple[str, int, str], object] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.max_points is not None and (
            type(self.max_points) is not int or self.max_points <= 0
        ):
            raise ValueError("point materialization budget must be a positive integer")

    def point_count(self) -> int:
        """Return exact logical cardinality, evaluating the point root if needed."""

        self._check_declared_budget()
        maximum = self.linked.cardinality.maximum
        if maximum == self.linked.cardinality.minimum:
            return self.linked.cardinality.minimum
        return len(self._materialize_point_domain().points)

    def _check_declared_budget(self) -> None:
        maximum = self.linked.cardinality.maximum
        if (
            self.max_points is not None
            and maximum is not None
            and maximum > self.max_points
        ):
            raise CheckFailed(
                (
                    _point_materialization_budget_problem(
                        maximum=maximum,
                        budget=self.max_points,
                    ),
                )
            )

    def bind_domain_inputs(
        self,
        execution_id: str,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Evaluate selected domain inputs for selected logical ordinals."""

        selected_input_ids = tuple(input_ids)
        selected = tuple(ordinals)
        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain input binding budget must be positive")
        if len(selected) > max_points:
            raise ValueError("domain input binding exceeds the requested budget")
        point_count = self.point_count()
        if any(ordinal < 0 or ordinal >= point_count for ordinal in selected):
            raise ValueError("domain input binding selects an unknown ordinal")
        execution = next(
            item
            for item in core_domain_executions(self.linked.program)
            if item.id == execution_id
        )
        known_input_ids = tuple(execution.inputs)
        selected_input_set = set(selected_input_ids)
        if not selected_input_ids:
            raise ValueError("domain input binding requires at least one input")
        if selected_input_ids != tuple(
            input_id for input_id in known_input_ids if input_id in selected_input_set
        ):
            raise ValueError(
                "domain input binding must select known inputs in typed order"
            )
        selected_points = self._materialize_selected_points(
            selected,
            max_points=max_points,
        )
        problems: list[Problem] = []
        columns: dict[str, list[object]] = {
            input_id: [] for input_id in selected_input_ids
        }
        for point in selected_points:
            input_values = self._domain_inputs(
                execution,
                point,
                selected_input_ids,
                problems=problems,
            )
            if input_values is not None:
                for input_id, value in input_values:
                    columns[input_id].append(value)
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        return tuple(
            (input_id, tuple(columns[input_id])) for input_id in selected_input_ids
        )

    def materialize(self) -> MaterializedLinkedPoints:
        """Close canonical points without evaluating domain execution inputs."""

        point_domain = self._materialize_point_domain()
        problems: list[Problem] = []
        point_parameters = tuple(
            self._point_parameter(point, problems=problems)
            for point in point_domain.points
        )
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        return MaterializedLinkedPoints(
            self.linked,
            point_domain,
            point_parameters,
        )

    def _materialize_point_domain(self) -> MaterializedPointDomain:
        if self._point_domain is not None:
            return self._point_domain
        self._check_declared_budget()
        problems: list[Problem] = []
        try:
            point_domain = materialize_point_domain(
                self.linked.point_domain,
                self.linked.environment.parameters,
                row_normalizer=lambda row: _normalize_point_domain_row(
                    row,
                    program=self.linked.program,
                    environment=self.linked.environment,
                    problems=problems,
                ),
            )
        except PointDomainEvaluationError as error:
            problems.append(
                compiler_problem(
                    "experiment_points_evaluation_failed",
                    f"experiment point domain failed: {error.error}",
                    model_location("point_domain", *error.path),
                    phase=ProblemPhase.PLANNING,
                )
            )
            raise CheckFailed(problems) from error
        except PointDomainValueError as error:
            problems.append(
                compiler_problem(
                    "module_point_value_type_mismatch",
                    str(error),
                    model_location("points"),
                    phase=ProblemPhase.PLANNING,
                )
            )
            raise CheckFailed(problems) from error
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        if self.max_points is not None and len(point_domain.points) > self.max_points:
            raise CheckFailed(
                (
                    _point_materialization_budget_problem(
                        point_count=len(point_domain.points),
                        budget=self.max_points,
                    ),
                )
            )
        if self._selected_points:
            points = list(point_domain.points)
            for ordinal, selected in self._selected_points.items():
                if selected.row != points[ordinal].row:
                    raise AssertionError(
                        "selective and complete point materialization must agree"
                    )
                points[ordinal] = selected
            point_domain = MaterializedPointDomain(
                point_domain.id,
                points,
                point_domain.declared_cardinality,
            )
        self._point_domain = point_domain
        return point_domain

    def _materialize_selected_points(
        self,
        ordinals: tuple[int, ...],
        *,
        max_points: int,
    ) -> tuple[MaterializedPoint, ...]:
        if self._point_domain is not None:
            return tuple(self._point_domain.points[ordinal] for ordinal in ordinals)
        missing = tuple(
            ordinal
            for ordinal in dict.fromkeys(ordinals)
            if ordinal not in self._selected_points
        )
        if missing:
            problems: list[Problem] = []
            try:
                points = materialize_point_domain_ordinals(
                    self.linked.point_domain,
                    self.linked.environment.parameters,
                    missing,
                    max_points=max_points,
                    row_normalizer=lambda row: _normalize_point_domain_row(
                        row,
                        program=self.linked.program,
                        environment=self.linked.environment,
                        problems=problems,
                    ),
                )
            except PointDomainEvaluationError as error:
                problems.append(
                    compiler_problem(
                        "experiment_points_evaluation_failed",
                        f"experiment point domain failed: {error.error}",
                        model_location("point_domain", *error.path),
                        phase=ProblemPhase.PLANNING,
                    )
                )
                raise CheckFailed(problems) from error
            except PointDomainValueError as error:
                problems.append(
                    compiler_problem(
                        "module_point_value_type_mismatch",
                        str(error),
                        model_location("points"),
                        phase=ProblemPhase.PLANNING,
                    )
                )
                raise CheckFailed(problems) from error
            if has_blocking_problems(problems):
                raise CheckFailed(problems)
            self._selected_points.update(
                (point.logical_ordinal, point) for point in points
            )
        return tuple(self._selected_points[ordinal] for ordinal in ordinals)

    def _point_parameter(
        self,
        point: MaterializedPoint,
        *,
        problems: list[Problem],
    ) -> ParameterRelationData:
        cached = self._point_parameters.get(point.logical_ordinal)
        if cached is not None:
            return cached
        try:
            parameters = resolve_point_parameters(
                self.linked.environment.parameters,
                self.linked.program.parameter_overlays,
                point_row=point.row,
                relation_plan=self.linked.verified_program.relation_plan,
            )
        except CompilerProblemError as error:
            problems.append(error.problem)
            return ParameterRelationData()
        self._point_parameters[point.logical_ordinal] = parameters
        return parameters

    def _domain_inputs(
        self,
        execution: TypedDomainExecution,
        point: MaterializedPoint,
        input_ids: tuple[str, ...],
        *,
        problems: list[Problem],
    ) -> tuple[tuple[str, object], ...] | None:
        parameters = self._point_parameter(point, problems=problems)
        if has_blocking_problems(problems):
            return None
        input_values: list[tuple[str, object]] = []
        failed = False
        for input_name in input_ids:
            input_key = (execution.id, point.logical_ordinal, input_name)
            if input_key in self._domain_input_values:
                value = self._domain_input_values[input_key]
            else:
                success, value = _materialize_domain_execution_input(
                    execution,
                    input_name=input_name,
                    point=point,
                    verified_program=self.linked.verified_program,
                    parameters=parameters,
                    problems=problems,
                )
                if not success:
                    failed = True
                    continue
                self._domain_input_values[input_key] = value
            input_values.append((input_name, value))
        if failed:
            return None
        return tuple(input_values)


def _materialize_domain_execution_input(
    execution: TypedDomainExecution,
    *,
    input_name: str,
    point: MaterializedPoint,
    verified_program: VerifiedCoreProgram,
    parameters: ParameterRelationData,
    problems: list[Problem],
) -> tuple[bool, object]:
    """Evaluate one selected domain input at one logical point."""

    context = EvalContext(params=parameters, point_row=point.row)
    input_spec = execution.inputs[input_name]
    try:
        evaluated = _evaluate_domain_input(
            input_spec,
            verified_program=verified_program,
            context=context,
        )
        value = coerce_literal(
            input_spec.value_type,
            evaluated,
            path=(
                "domain_executions",
                execution.id,
                "points",
                point.logical_ordinal,
                "inputs",
                input_name,
            ),
        )
        return True, _unwrap_domain_input(value)
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        problems.append(
            compiler_problem(
                "domain_execution_input_evaluation_failed",
                f"domain execution input {input_name!r} failed for point "
                f"{point.logical_ordinal}: {error}",
                model_location(
                    "domain_executions",
                    execution.id,
                    "points",
                    point.logical_ordinal,
                    "inputs",
                    input_name,
                ),
                phase=ProblemPhase.PLANNING,
            )
        )
        return False, None


def _point_materialization_budget_problem(
    *,
    budget: int,
    maximum: int | None = None,
    point_count: int | None = None,
) -> Problem:
    symbolic = maximum is not None
    return compiler_problem(
        "point_materialization_budget_exceeded",
        (
            "symbolic point space exceeds the explicit materialization budget"
            if symbolic
            else "materialized point space exceeds the explicit budget"
        ),
        model_location("point_domain"),
        phase=ProblemPhase.PLANNING,
        details={
            "maximum" if symbolic else "point_count": (
                maximum if symbolic else point_count
            ),
            "budget": budget,
        },
    )


def _evaluate_domain_input(
    input_spec: ValueInput,
    *,
    verified_program: VerifiedCoreProgram,
    context: EvalContext,
) -> object:
    value = input_spec.value
    verified_plan = verified_program.relation_plan(input_spec.relation_use_id)
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            cast("VerifiedRelationPlan[ScalarExpr]", verified_plan),
            context,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            cast("VerifiedRelationPlan[SeriesExpr]", verified_plan),
            context,
        )
    return evaluate_relation_in_context(
        cast("VerifiedRelationPlan[RelationExpr]", verified_plan),
        context,
    )


def _unwrap_domain_input(value: object) -> object:
    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        return [_unwrap_domain_input(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return tuple(_unwrap_domain_input(item) for item in selected)
    if isinstance(value, Mapping):
        return {
            name: _unwrap_domain_input(item)
            for name, item in cast("Mapping[object, object]", value).items()
        }
    return value


def link_verified_program(
    verified_program: VerifiedCoreProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Bind config contracts to an already verified transient program."""

    problems = list(_environment_link_problems(environment))
    if environment.valid:
        problems.extend(
            _relation_import_problems(
                verified_program,
                environment.parameters,
            )
        )
        if environment.routing is not None:
            problems.extend(
                _static_resource_problems(
                    verified_program.program,
                    environment.routing,
                )
            )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return LinkedPlan(
        verified_program,
        environment,
    )


def specialize_linked_program(linked: LinkedPlan) -> LinkedPlan:
    """Partially evaluate one accepted config link before system lowering."""

    return LinkedPlan(
        seal_typed_program(
            specialize_core_program(
                linked.program,
                parameters=linked.environment.parameters,
            ),
            phase=ProblemPhase.PLANNING,
        ),
        linked.environment,
    )


def _environment_link_problems(
    environment: ValidatedConfigEnvironment,
) -> tuple[Problem, ...]:
    problems = list(environment.problems)
    if environment.valid and environment.routing is None:
        problems.append(
            compiler_problem(
                "config_routing_unavailable",
                "a linked plan requires a validated configuration routing view",
                model_location("config", "routing"),
                phase=ProblemPhase.PLANNING,
                category=ProblemCategory.UNAVAILABLE,
            )
        )
    return tuple(problems)


def _relation_import_problems(
    verified_program: VerifiedCoreProgram,
    parameters: ParameterRelationData,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for consumer in verified_program.relation_consumers:
        plan = consumer.plan
        for imported in plan.imports:
            if imported.namespace is PlanImportNamespace.INPUT:
                problems.append(_unresolved_input_problem(consumer, imported.id))
                continue
            try:
                validate_relation_parameter_import(
                    plan,
                    imported,
                    parameters,
                )
            except ValueValidationError as error:
                problems.append(_parameter_import_problem(consumer, error))
    return tuple(problems)


def _static_resource_problems(
    program: CoreProgram,
    routing: RoutingView,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    instrument_port_ids = _instrument_resource_port_ids(program)
    for route_index, intent in enumerate(program.route_intents):
        if intent.fixed_resource_id is None:
            continue
        problems.extend(
            _physical_resource_problems(
                routing,
                intent.fixed_resource_id,
                capabilities=intent.capabilities,
                require_instrument=intent.port_id in instrument_port_ids,
                location=model_location(
                    "route_intents",
                    route_index,
                    "fixed_resource_id",
                ),
            )
        )
    for state_index, state in enumerate(core_state(program)):
        problems.extend(
            _static_state_resource_problems(
                state,
                routing=routing,
                location=model_location("state", state_index),
            )
        )
    return tuple(problems)


def _instrument_resource_port_ids(
    program: CoreProgram,
) -> frozenset[LogicalResourcePortId]:
    selected: set[LogicalResourcePortId] = set()

    def visit(state: StateSpecVariant) -> None:
        if isinstance(state, SetStateSpec):
            if isinstance(state.resource_target, LogicalStateResourceTarget):
                selected.add(state.resource_target.port_id)
            return
        for child in state.state:
            visit(child)

    for state in core_state(program):
        visit(state)
    selected.update(action.resource_port_id for action in core_actions(program))
    return frozenset(selected)


def _static_state_resource_problems(
    state: StateSpecVariant,
    *,
    routing: RoutingView,
    location: ModelLocation,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    if isinstance(state, SetStateSpec):
        target = state.resource_target
        if isinstance(target, PhysicalStateResourceTarget):
            root = target.use.value.plan.root
            if (
                isinstance(root, LiteralScalarExpr)
                and isinstance(root.value, str)
                and root.value
            ):
                problems.extend(
                    _physical_resource_problems(
                        routing,
                        PhysicalResourceId(root.value),
                        capabilities=(state.capability_id,),
                        require_instrument=True,
                        location=model_location(
                            location.root,
                            *location.path,
                            "physical_resource_id",
                        ),
                    )
                )
        return tuple(problems)
    for child_index, child in enumerate(state.state):
        problems.extend(
            _static_state_resource_problems(
                child,
                routing=routing,
                location=model_location(
                    location.root,
                    *location.path,
                    "state",
                    child_index,
                ),
            )
        )
    return tuple(problems)


def _physical_resource_problems(
    routing: RoutingView,
    resource_id: PhysicalResourceId,
    *,
    capabilities: tuple[str, ...],
    location: ModelLocation,
    require_instrument: bool = False,
) -> tuple[Problem, ...]:
    try:
        binding = routing.bind_physical(
            resource_id=resource_id,
            capabilities=capabilities,
        )
    except RoutingError as error:
        return (
            compiler_problem(
                error.code,
                str(error),
                location,
                phase=ProblemPhase.PLANNING,
                category=(
                    ProblemCategory.NOT_FOUND
                    if error.code.endswith("not_found")
                    else ProblemCategory.UNAVAILABLE
                ),
            ),
        )
    if require_instrument and binding.resource_kind != "instrument":
        return (
            compiler_problem(
                "physical_resource_kind_unsupported",
                f"physical resource {resource_id.value!r} has kind "
                f"{binding.resource_kind!r}; local state and collection require "
                "an instrument",
                location,
                phase=ProblemPhase.PLANNING,
                category=ProblemCategory.UNAVAILABLE,
            ),
        )
    return ()


def _unresolved_input_problem(
    consumer: ProgramRelationConsumer,
    input_id: str,
) -> Problem:
    return compiler_problem(
        "linked_input_unresolved",
        f"linked relation still depends on unresolved input {input_id!r}",
        model_location(
            consumer.location.root,
            *consumer.location.path,
            "inputs",
            input_id,
        ),
        phase=ProblemPhase.PLANNING,
        category=ProblemCategory.NOT_FOUND,
        details={
            "consumer_kind": consumer.kind.value,
            "input_id": input_id,
        },
    )


def _parameter_import_problem(
    consumer: ProgramRelationConsumer,
    error: ValueValidationError,
) -> Problem:
    missing = error.code == "unknown_parameter"
    parameter_id = (
        error.path[1]
        if len(error.path) > 1 and isinstance(error.path[1], str)
        else None
    )
    return compiler_problem(
        "linked_parameter_missing" if missing else "linked_parameter_contract_mismatch",
        (
            "accepted configuration cannot satisfy relation "
            f"parameter import: {error.reason}"
        ),
        model_location(
            consumer.location.root,
            *consumer.location.path,
            *error.path,
        ),
        phase=ProblemPhase.PLANNING,
        category=(
            ProblemCategory.NOT_FOUND if missing else ProblemCategory.INVALID_INPUT
        ),
        details={
            "consumer_kind": consumer.kind.value,
            **({"parameter_id": parameter_id} if parameter_id is not None else {}),
            "value_path": list(error.path),
        },
    )


def _normalize_point_domain_row(
    row: Row,
    *,
    program: CoreProgram,
    environment: ValidatedConfigEnvironment,
    problems: list[Problem],
) -> Row:
    selected = dict(row)
    for column_id in program.point_domain.entity_columns:
        value = selected.get(column_id)
        if value is None:
            continue
        entity = _resolve_entity(value, environment, problems)
        if entity is not None:
            selected[column_id] = entity
    return selected


def _resolve_entity(
    value: object,
    environment: ValidatedConfigEnvironment,
    problems: list[Problem],
) -> EntityRef | None:
    selected = value if isinstance(value, EntityRef) else str(value)
    try:
        return resolve_entity(environment.config.topology, selected)
    except EntityResolutionError as error:
        issue = error.issue
    if issue.code == "unknown_entity":
        problems.append(
            compiler_problem(
                "unknown_authoring_entity",
                f"experiment references unknown entity {issue.entity_id}",
                model_location("entity", issue.entity_id),
                phase=ProblemPhase.PLANNING,
                category=ProblemCategory.NOT_FOUND,
            )
        )
        return None
    problems.append(
        compiler_problem(
            "authoring_entity_kind_mismatch",
            f"entity {issue.entity_id} has kind {issue.actual_kind}, "
            f"not {issue.requested_kind}",
            model_location("entity", issue.entity_id),
            phase=ProblemPhase.PLANNING,
        )
    )
    return None
