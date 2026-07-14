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
from scopecat.compiler.relations.backend import (
    EvalContext,
    ParameterRelationData,
    RelationBackend,
    SelectedRelationPlan,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
    validate_relation_parameter_import,
)
from scopecat.compiler.relations.model import RelationExpr, Row, ScalarExpr, SeriesExpr
from scopecat.compiler.relations.point_domain import PointCardinality
from scopecat.compiler.relations.reference_backend import REFERENCE_RELATION_BACKEND
from scopecat.compiler.relations.verification import PlanImportNamespace
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
    TypedDomainCall,
    TypedDomainProgram,
    TypedMeasurementTransform,
    TypedProgram,
    ValueInput,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    StateSpec,
)
from scopecat.compiler.typed.verification import (
    ProgramRelationBackendCapabilityError,
    ProgramRelationConsumer,
    SelectedTypedProgram,
    VerifiedTypedProgram,
    seal_typed_program,
    select_typed_program,
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


@dataclass(frozen=True, slots=True, init=False)
class LinkedPlan:
    """A successful config link retaining the complete symbolic point domain.

    The plan binds a backend-neutral, sealed compiler program to one accepted
    configuration environment. Both are trusted transient compiler artifacts;
    the plan owns no relation-backend selection, materialized points, or target
    artifact.
    """

    _verified_program: VerifiedTypedProgram
    _environment: ValidatedConfigEnvironment

    def __init__(
        self,
        verified_program: VerifiedTypedProgram,
        environment: ValidatedConfigEnvironment,
    ) -> None:
        if not environment.valid:
            msg = "linked plans require a valid configuration environment"
            raise ValueError(msg)
        if environment.routing is None:
            msg = "linked plans require a validated routing view"
            raise ValueError(msg)
        object.__setattr__(self, "_verified_program", verified_program)
        object.__setattr__(self, "_environment", environment)

    @property
    def program(self) -> TypedProgram:
        """Return the sealed compiler program bound to this plan."""

        return self._verified_program.program

    @property
    def environment(self) -> ValidatedConfigEnvironment:
        """Return the accepted configuration environment bound to this plan."""

        return self._environment

    @property
    def verified_program(self) -> VerifiedTypedProgram:
        """Return the sealed target-neutral compiler program."""

        return self._verified_program

    @property
    def point_domain(self) -> VerifiedPointDomain:
        return self._verified_program.point_domain

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
class MaterializedDomainCallPoint:
    """One logical point's closed inputs for a domain call."""

    logical_id: LogicalPointId
    logical_ordinal: int
    inputs: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        names = tuple(name for name, _value in self.inputs)
        if any(not name for name in names) or len(names) != len(set(names)):
            msg = "materialized domain call input ids must be non-empty and unique"
            raise ValueError(msg)

    def input(self, name: str) -> object:
        """Return one named input value or raise a precise lookup error."""

        for input_name, value in self.inputs:
            if input_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class MaterializedDomainCall:
    """A typed domain call whose prepare-stage inputs are concrete per point."""

    program: TypedDomainProgram
    call: TypedDomainCall
    points: tuple[MaterializedDomainCallPoint, ...]

    def __post_init__(self) -> None:
        if self.call.program_id != self.program.id:
            msg = "materialized domain call must retain its declared program"
            raise ValueError(msg)
        ordinals = tuple(point.logical_ordinal for point in self.points)
        if len(ordinals) != len(set(ordinals)):
            msg = "materialized domain call points must have unique logical ordinals"
            raise ValueError(msg)

    def select(self, ordinals: frozenset[int]) -> MaterializedDomainCall:
        """Project this already materialized call onto a canonical batch."""

        return MaterializedDomainCall(
            program=self.program,
            call=self.call,
            points=tuple(
                point for point in self.points if point.logical_ordinal in ordinals
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class MaterializedLinkedPoints:
    """One linked plan with a complete backend selection and canonical points.

    This proof is deliberately narrower than a local bound plan: it retains the
    exact linked program, the whole-program relation-backend selection, and the
    materialized logical point domain, while owning no local compute or product
    realization.
    """

    _linked_plan: LinkedPlan
    _selected_program: SelectedTypedProgram
    _point_domain: MaterializedPointDomain
    _domain_calls: tuple[MaterializedDomainCall, ...]
    relation_backend_id: str

    def __init__(
        self,
        linked_plan: LinkedPlan,
        selected_program: SelectedTypedProgram,
        point_domain: MaterializedPointDomain,
        relation_backend_id: str,
        domain_calls: Sequence[MaterializedDomainCall] = (),
    ) -> None:
        if selected_program.verified_program is not linked_plan.verified_program:
            msg = "selected program must belong to the linked plan"
            raise ValueError(msg)
        if selected_program.backend_id != relation_backend_id:
            msg = "selected program and materialized linked points must use one backend"
            raise ValueError(msg)
        if point_domain.id != linked_plan.point_domain.id:
            msg = "materialized point domain must belong to the linked plan"
            raise ValueError(msg)
        object.__setattr__(self, "_linked_plan", linked_plan)
        object.__setattr__(self, "_selected_program", selected_program)
        object.__setattr__(self, "_point_domain", point_domain)
        object.__setattr__(self, "_domain_calls", tuple(domain_calls))
        object.__setattr__(self, "relation_backend_id", relation_backend_id)

    @property
    def linked_plan(self) -> LinkedPlan:
        return self._linked_plan

    @property
    def selected_program(self) -> SelectedTypedProgram:
        return self._selected_program

    @property
    def point_domain(self) -> MaterializedPointDomain:
        return self._point_domain

    @property
    def domain_calls(self) -> tuple[MaterializedDomainCall, ...]:
        """Return domain calls with every plan-stage input already evaluated."""

        return self._domain_calls


@dataclass(frozen=True, slots=True, init=False)
class MaterializedPointDomainView:
    """A canonical contiguous view over an already materialized point domain.

    A view never renumbers points or creates a second logical identity space.
    Its points are the exact frozen point values retained by the complete
    materialization, while its cardinality describes only the selected batch.
    """

    _source: MaterializedPointDomain
    points: tuple[MaterializedPoint, ...]
    cardinality: PointCardinality
    declared_cardinality: PointCardinality

    def __init__(
        self,
        source: MaterializedPointDomain,
        points: tuple[MaterializedPoint, ...],
    ) -> None:
        if not points:
            msg = "materialized point-domain views require at least one point"
            raise ValueError(msg)
        source_by_ordinal = {point.logical_ordinal: point for point in source.points}
        if any(
            source_by_ordinal.get(point.logical_ordinal) is not point
            for point in points
        ):
            msg = "materialized point-domain views must retain source points"
            raise ValueError(msg)
        ordinals = tuple(point.logical_ordinal for point in points)
        if ordinals != tuple(range(ordinals[0], ordinals[0] + len(ordinals))):
            msg = "materialized point-domain views require contiguous canonical points"
            raise ValueError(msg)
        exact = PointCardinality.exact(len(points))
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "cardinality", exact)
        object.__setattr__(self, "declared_cardinality", exact)

    @property
    def id(self) -> PointDomainId:
        """Retain the parent domain namespace used by every logical point."""

        return self._source.id

    @property
    def source(self) -> MaterializedPointDomain:
        return self._source


@dataclass(frozen=True, slots=True, init=False)
class MaterializedLinkedPointBatch:
    """One non-empty contiguous batch selected from complete linked points.

    The complete parent proof is retained exactly. Selection changes only the
    point-domain view presented to a target adapter; logical point identities,
    ordinals, the selected relation backend, and the linked program are shared
    with the parent.
    """

    _parent: MaterializedLinkedPoints
    _point_domain: MaterializedPointDomainView
    point_indices: tuple[int, ...]

    def __init__(
        self,
        parent: MaterializedLinkedPoints,
        point_indices: Sequence[int],
    ) -> None:
        if not isinstance(cast("object", parent), MaterializedLinkedPoints):
            msg = "linked point batches require MaterializedLinkedPoints"
            raise TypeError(msg)
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
    def selected_program(self) -> SelectedTypedProgram:
        return self._parent.selected_program

    @property
    def relation_backend_id(self) -> str:
        return self._parent.relation_backend_id

    @property
    def point_domain(self) -> MaterializedPointDomainView:
        return self._point_domain

    @property
    def domain_calls(self) -> tuple[MaterializedDomainCall, ...]:
        """Return the parent calls restricted to this canonical point batch."""

        ordinals = frozenset(self.point_indices)
        return tuple(call.select(ordinals) for call in self._parent.domain_calls)


type MaterializedLinkedPointSet = (
    MaterializedLinkedPoints | MaterializedLinkedPointBatch
)


def materialize_linked_points(
    linked: LinkedPlan,
    *,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
) -> MaterializedLinkedPoints:
    """Select every relation, then materialize only the logical point domain.

    Whole-program backend preflight completes before the first relation is
    evaluated. Expected capability, point-evaluation, value, and entity errors
    cross this planning boundary as structured :class:`CheckFailed` problems.
    """

    selected_program = select_linked_program(linked, relation_backend)
    return materialize_selected_linked_points(
        linked,
        selected_program,
        relation_backend,
    )


def select_linked_program(
    linked: LinkedPlan,
    relation_backend: RelationBackend,
) -> SelectedTypedProgram:
    """Preflight every linked relation without evaluating any of them."""

    if not isinstance(cast("object", linked), LinkedPlan):
        msg = "linked point materialization requires a LinkedPlan"
        raise TypeError(msg)
    try:
        return select_typed_program(
            relation_backend,
            linked.verified_program,
        )
    except ProgramRelationBackendCapabilityError as error:
        raise CheckFailed(_relation_backend_capability_problems(error)) from error


def materialize_selected_linked_points(
    linked: LinkedPlan,
    selected_program: SelectedTypedProgram,
    relation_backend: RelationBackend,
) -> MaterializedLinkedPoints:
    """Materialize points from an exact whole-program backend selection."""

    if selected_program.verified_program is not linked.verified_program:
        msg = "selected program must belong to the linked plan"
        raise ValueError(msg)
    if selected_program.backend_id != relation_backend.backend_id:
        msg = "selected program and point materializer must use one backend"
        raise ValueError(msg)
    program = linked.program
    environment = linked.environment
    problems: list[Problem] = []
    try:
        point_domain = materialize_point_domain(
            relation_backend,
            selected_program.point_domain,
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
    domain_calls = _materialize_domain_calls(
        program.domain_programs,
        program.domain_calls,
        points=point_domain.points,
        selected_program=selected_program,
        parameters=environment.parameters,
        relation_backend=relation_backend,
        problems=problems,
    )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLinkedPoints(
        linked,
        selected_program,
        point_domain,
        relation_backend.backend_id,
        domain_calls,
    )


def _materialize_domain_calls(
    programs: Sequence[TypedDomainProgram],
    calls: Sequence[TypedDomainCall],
    *,
    points: Sequence[MaterializedPoint],
    selected_program: SelectedTypedProgram,
    parameters: ParameterRelationData,
    relation_backend: RelationBackend,
    problems: list[Problem],
) -> tuple[MaterializedDomainCall, ...]:
    """Evaluate verified plan-stage call inputs using the selected backend."""

    programs_by_id = {program.id: program for program in programs}
    materialized: list[MaterializedDomainCall] = []
    for call in calls:
        program = programs_by_id.get(call.program_id)
        if program is None:
            raise AssertionError("verified domain call lost its program declaration")
        call_points: list[MaterializedDomainCallPoint] = []
        failed = False
        for point in points:
            input_values: list[tuple[str, object]] = []
            context = EvalContext(params=parameters, point_row=point.row)
            for input_name, input_spec in call.inputs.items():
                try:
                    evaluated = _evaluate_domain_input(
                        input_spec,
                        selected_program=selected_program,
                        context=context,
                        relation_backend=relation_backend,
                    )
                    value = coerce_literal(
                        input_spec.value_type,
                        evaluated,
                        path=(
                            "domain_calls",
                            call.id.qualified_name,
                            "points",
                            point.logical_ordinal,
                            "inputs",
                            input_name,
                        ),
                    )
                    input_values.append((input_name, _unwrap_domain_input(value)))
                except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                    failed = True
                    problems.append(
                        compiler_problem(
                            "domain_call_input_evaluation_failed",
                            f"domain call input {input_name!r} failed for point "
                            f"{point.logical_ordinal}: {error}",
                            model_location(
                                "domain_calls",
                                call.id.qualified_name,
                                "points",
                                point.logical_ordinal,
                                "inputs",
                                input_name,
                            ),
                            phase=ProblemPhase.PLANNING,
                        )
                    )
            call_points.append(
                MaterializedDomainCallPoint(
                    logical_id=point.logical_id,
                    logical_ordinal=point.logical_ordinal,
                    inputs=tuple(input_values),
                )
            )
        if not failed:
            materialized.append(
                MaterializedDomainCall(
                    program=program,
                    call=call,
                    points=tuple(call_points),
                )
            )
    return tuple(materialized)


def _evaluate_domain_input(
    input_spec: ValueInput,
    *,
    selected_program: SelectedTypedProgram,
    context: EvalContext,
    relation_backend: RelationBackend,
) -> object:
    value = input_spec.value
    selected_plan = selected_program.selected_plan(input_spec.relation_use_id)
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            relation_backend,
            cast("SelectedRelationPlan[ScalarExpr]", selected_plan),
            context,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            relation_backend,
            cast("SelectedRelationPlan[SeriesExpr]", selected_plan),
            context,
        )
    return evaluate_relation_in_context(
        relation_backend,
        cast("SelectedRelationPlan[RelationExpr]", selected_plan),
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


def link_program(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Snapshot and seal an external program, then bind its config contracts."""

    try:
        verified_program = seal_typed_program(
            program.model_copy(deep=True),
            phase=ProblemPhase.PLANNING,
        )
    except CheckFailed as error:
        problems = [*_environment_link_problems(environment), *error.problems]
        if has_blocking_problems(problems):
            raise CheckFailed(problems) from error
        raise AssertionError(
            "failed program seal produced no blocking problem"
        ) from error
    return link_verified_program(verified_program, environment)


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

    def visit(state: StateSpec) -> None:
        if isinstance(state.resource_target, LogicalStateResourceTarget):
            selected.add(state.resource_target.port_id)
        for child in state.state or ():
            visit(child)

    for state in program.state:
        visit(state)
    selected.update(action.resource_port_id for action in program.actions)
    return frozenset(selected)


def _static_state_resource_problems(
    state: StateSpec,
    *,
    routing: RoutingView,
    location: ModelLocation,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    target = state.resource_target
    if isinstance(target, PhysicalStateResourceTarget):
        root = target.use.value.plan.root
        if isinstance(root.value, str) and root.kind == "literal" and root.value:
            problems.extend(
                _physical_resource_problems(
                    routing,
                    PhysicalResourceId(root.value),
                    capabilities=(
                        () if state.capability_id is None else (state.capability_id,)
                    ),
                    require_instrument=True,
                    location=model_location(
                        location.root,
                        *location.path,
                        "physical_resource_id",
                    ),
                )
            )
    for child_index, child in enumerate(state.state or ()):
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


def _relation_backend_capability_problems(
    error: ProgramRelationBackendCapabilityError,
) -> tuple[Problem, ...]:
    return tuple(
        compiler_problem(
            "relation_backend_capability_unsupported",
            (
                f"relation backend {error.backend_id!r} cannot execute "
                f"{failure.consumer.kind.value}: {failure.issue.message}"
            ),
            model_location(
                failure.consumer.location.root,
                *failure.consumer.location.path,
                *failure.issue.path,
            ),
            phase=ProblemPhase.PLANNING,
            category=ProblemCategory.UNAVAILABLE,
            details={
                "backend_id": error.backend_id,
                "consumer_kind": failure.consumer.kind.value,
                "consumer_location": {
                    "root": failure.consumer.location.root,
                    "path": list(failure.consumer.location.path),
                },
                "capability_dimension": failure.issue.dimension.value,
                "capability_code": failure.issue.code,
                "plan_path": list(failure.issue.path),
            },
        )
        for failure in error.failures
    )


__all__ = [
    "LinkedPlan",
    "MaterializedDomainCall",
    "MaterializedDomainCallPoint",
    "MaterializedLinkedPointBatch",
    "MaterializedLinkedPointSet",
    "MaterializedLinkedPoints",
    "MaterializedPointDomainView",
    "link_program",
    "link_verified_program",
    "materialize_linked_points",
    "materialize_selected_linked_points",
    "select_linked_program",
]
