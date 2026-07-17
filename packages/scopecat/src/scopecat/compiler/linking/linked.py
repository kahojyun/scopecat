"""Config-linked symbolic programs before any target materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
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
from scopecat.compiler.typed.point_domain import (
    LogicalPointId,
    MaterializedPoint,
    MaterializedPointDomain,
    PointDomainEvaluationError,
    PointDomainId,
    PointDomainValueError,
    VerifiedPointDomain,
    materialize_point_domain,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    MeasurementTransformProductProducer,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedMeasurementTransform,
    TypedProgram,
    ValueInput,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumer,
    VerifiedTypedProgram,
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

    verified_program: VerifiedTypedProgram
    environment: ValidatedConfigEnvironment

    @property
    def program(self) -> TypedProgram:
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
class MaterializedDomainExecutionPoint:
    """One logical point's closed inputs for the domain execution."""

    logical_id: LogicalPointId
    logical_ordinal: int
    inputs: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        names = tuple(name for name, _value in self.inputs)
        if any(not name for name in names) or len(names) != len(set(names)):
            msg = "materialized domain execution input ids must be non-empty and unique"
            raise ValueError(msg)

    def input(self, name: str) -> object:
        """Return one named input value or raise a precise lookup error."""

        for input_name, value in self.inputs:
            if input_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class MaterializedDomainExecution:
    """The typed domain execution with concrete prepare-stage inputs."""

    execution: TypedDomainExecution
    points: tuple[MaterializedDomainExecutionPoint, ...]

    def __post_init__(self) -> None:
        ordinals = tuple(point.logical_ordinal for point in self.points)
        if len(ordinals) != len(set(ordinals)):
            msg = "materialized domain execution points need unique logical ordinals"
            raise ValueError(msg)

    def select(self, ordinals: frozenset[int]) -> MaterializedDomainExecution:
        """Project this materialized execution onto a canonical batch."""

        return MaterializedDomainExecution(
            execution=self.execution,
            points=tuple(
                point for point in self.points if point.logical_ordinal in ordinals
            ),
        )


@dataclass(frozen=True, slots=True)
class MaterializedLinkedPoints:
    """One linked plan with canonical points and materialized domain execution.

    This artifact is deliberately narrower than a local bound plan: it retains
    the exact linked program and materialized logical point domain while owning
    no local compute or product realization.
    """

    linked_plan: LinkedPlan
    point_domain: MaterializedPointDomain
    domain_execution: MaterializedDomainExecution | None = None

    @property
    def verified_program(self) -> VerifiedTypedProgram:
        return self.linked_plan.verified_program


@dataclass(frozen=True, slots=True)
class MaterializedPointDomainView:
    """A canonical contiguous view over an already materialized point domain.

    A view never renumbers points or creates a second logical identity space.
    Its points are the exact frozen point values retained by the complete
    materialization, while its cardinality describes only the selected batch.
    """

    source: MaterializedPointDomain
    points: tuple[MaterializedPoint, ...]

    @property
    def id(self) -> PointDomainId:
        """Retain the parent domain namespace used by every logical point."""

        return self.source.id

    @property
    def cardinality(self) -> PointCardinality:
        return PointCardinality.exact(len(self.points))

    @property
    def declared_cardinality(self) -> PointCardinality:
        return self.cardinality


@dataclass(frozen=True, slots=True, init=False)
class MaterializedLinkedPointBatch:
    """One non-empty contiguous batch selected from complete linked points.

    The complete parent proof is retained exactly. Selection changes only the
    point-domain view presented to a target adapter; logical point identities,
    ordinals, and the linked program are shared with the parent.
    """

    _parent: MaterializedLinkedPoints
    _point_domain: MaterializedPointDomainView
    point_indices: tuple[int, ...]

    def __init__(
        self,
        parent: MaterializedLinkedPoints,
        point_indices: Sequence[int],
    ) -> None:
        indices = tuple(point_indices)
        if not indices:
            msg = "linked point batches require at least one point index"
            raise ValueError(msg)
        if any(type(index) is not int for index in indices):
            msg = "linked point batch indices must be integers"
            raise TypeError(msg)
        if indices != tuple(range(indices[0], indices[0] + len(indices))):
            msg = "linked point batch indices must be canonical and contiguous"
            raise ValueError(msg)
        if indices[0] < 0 or indices[-1] >= len(parent.point_domain.points):
            msg = "linked point batch indices are outside the materialized domain"
            raise ValueError(msg)
        points = tuple(parent.point_domain.points[index] for index in indices)
        if tuple(point.logical_ordinal for point in points) != indices:
            msg = "linked point batch indices must preserve logical ordinals"
            raise ValueError(msg)
        object.__setattr__(self, "_parent", parent)
        object.__setattr__(
            self,
            "_point_domain",
            MaterializedPointDomainView(parent.point_domain, points),
        )
        object.__setattr__(self, "point_indices", indices)

    @property
    def parent(self) -> MaterializedLinkedPoints:
        return self._parent

    @property
    def linked_plan(self) -> LinkedPlan:
        return self._parent.linked_plan

    @property
    def verified_program(self) -> VerifiedTypedProgram:
        return self._parent.verified_program

    @property
    def point_domain(self) -> MaterializedPointDomainView:
        return self._point_domain

    @property
    def domain_execution(self) -> MaterializedDomainExecution | None:
        """Return the parent execution restricted to this canonical batch."""

        execution = self._parent.domain_execution
        if execution is None:
            return None
        ordinals = frozenset(self.point_indices)
        return execution.select(ordinals)


type MaterializedLinkedPointSet = (
    MaterializedLinkedPoints | MaterializedLinkedPointBatch
)


def materialize_linked_points(
    linked: LinkedPlan,
) -> MaterializedLinkedPoints:
    """Materialize the logical point domain and plan-stage domain inputs.

    Expected point-evaluation, value, and entity errors cross this planning
    boundary as structured :class:`CheckFailed` problems.
    """

    program = linked.program
    environment = linked.environment
    problems: list[Problem] = []
    try:
        point_domain = materialize_point_domain(
            linked.point_domain,
            environment.parameters,
            row_normalizer=lambda row: _normalize_point_domain_row(
                row,
                program=program,
                environment=environment,
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
    domain_execution = _materialize_domain_execution(
        program.domain_execution,
        points=point_domain.points,
        verified_program=linked.verified_program,
        parameters=environment.parameters,
        problems=problems,
    )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLinkedPoints(
        linked,
        point_domain,
        domain_execution,
    )


def _materialize_domain_execution(
    execution: TypedDomainExecution | None,
    *,
    points: Sequence[MaterializedPoint],
    verified_program: VerifiedTypedProgram,
    parameters: ParameterRelationData,
    problems: list[Problem],
) -> MaterializedDomainExecution | None:
    """Evaluate the optional verified domain execution's plan-stage inputs."""

    if execution is None:
        return None
    execution_points: list[MaterializedDomainExecutionPoint] = []
    failed = False
    for point in points:
        input_values: list[tuple[str, object]] = []
        context = EvalContext(params=parameters, point_row=point.row)
        for input_name, input_spec in execution.inputs.items():
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
                        "domain_execution",
                        "points",
                        point.logical_ordinal,
                        "inputs",
                        input_name,
                    ),
                )
                resolved_value = _unwrap_domain_input(value)
                input_values.append((input_name, resolved_value))
            except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                failed = True
                problems.append(
                    compiler_problem(
                        "domain_execution_input_evaluation_failed",
                        f"domain execution input {input_name!r} failed for point "
                        f"{point.logical_ordinal}: {error}",
                        model_location(
                            "domain_execution",
                            "points",
                            point.logical_ordinal,
                            "inputs",
                            input_name,
                        ),
                        phase=ProblemPhase.PLANNING,
                    )
                )
        execution_points.append(
            MaterializedDomainExecutionPoint(
                logical_id=point.logical_id,
                logical_ordinal=point.logical_ordinal,
                inputs=tuple(input_values),
            )
        )
    if failed:
        return None
    return MaterializedDomainExecution(
        execution=execution,
        points=tuple(execution_points),
    )


def _evaluate_domain_input(
    input_spec: ValueInput,
    *,
    verified_program: VerifiedTypedProgram,
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
    verified_program: VerifiedTypedProgram,
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
    verified_program: VerifiedTypedProgram,
    parameters: ParameterRelationData,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for consumer in verified_program.relation_consumers:
        plan = consumer.value.plan
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
    program: TypedProgram,
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
    for state_index, state in enumerate(program.state):
        problems.extend(
            _static_state_resource_problems(
                state,
                routing=routing,
                location=model_location("state", state_index),
            )
        )
    return tuple(problems)


def _instrument_resource_port_ids(
    program: TypedProgram,
) -> frozenset[LogicalResourcePortId]:
    selected: set[LogicalResourcePortId] = set()

    def visit(state: StateSpecVariant) -> None:
        if isinstance(state, SetStateSpec):
            if isinstance(state.resource_target, LogicalStateResourceTarget):
                selected.add(state.resource_target.port_id)
            return
        for child in state.state:
            visit(child)

    for state in program.state:
        visit(state)
    selected.update(action.resource_port_id for action in program.actions)
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
    program: TypedProgram,
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
