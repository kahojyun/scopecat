"""Config-linked symbolic programs before any target materialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.point_domain import (
    MaterializedPointDomain,
    PointDomainEvaluationError,
    PointDomainValueError,
    VerifiedPointDomain,
    materialize_point_domain,
)
from scopecat._compiler.problems import compiler_problem
from scopecat._compiler.products import InstrumentProductProducer, ProductDef
from scopecat._compiler.program import TypedProgram
from scopecat._compiler.records import RecordUse
from scopecat._compiler.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    StateSpec,
)
from scopecat._compiler.verification import (
    ProgramRelationBackendCapabilityError,
    ProgramRelationConsumer,
    SelectedTypedProgram,
    VerifiedTypedProgram,
    seal_typed_program,
    select_typed_program,
)
from scopecat._point_domain_algebra import PointCardinality
from scopecat._product_identity import ProductUse
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    ParameterRelationData,
    RelationBackend,
    validate_relation_parameter_import,
)
from scopecat._relation_verification import PlanImportNamespace
from scopecat._relations import Row
from scopecat._resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.errors import CheckFailed
from scopecat.models.entity import EntityRef
from scopecat.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.routing import RoutingError, RoutingView
from scopecat.value_types import TableColumn
from scopecat.value_validation import ValueValidationError


@dataclass(frozen=True, slots=True, init=False)
class LinkedPlan:
    """A successful config link retaining the complete symbolic point domain.

    The plan owns a backend-neutral, sealed compiler program and a defensive
    snapshot of the accepted configuration environment. It deliberately owns
    no relation-backend selection, materialized points, or target artifact.
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
        object.__setattr__(self, "_environment", deepcopy(environment))

    @property
    def program(self) -> TypedProgram:
        """Return a defensive copy of the linked compiler program."""

        return self._verified_program.program

    @property
    def environment(self) -> ValidatedConfigEnvironment:
        """Return a defensive copy of the accepted configuration environment."""

        return deepcopy(self._environment)

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
    relation_backend_id: str

    def __init__(
        self,
        linked_plan: LinkedPlan,
        selected_program: SelectedTypedProgram,
        point_domain: MaterializedPointDomain,
        relation_backend_id: str,
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
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLinkedPoints(
        linked,
        selected_program,
        point_domain,
        relation_backend.backend_id,
    )


def link_program(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Close program and config contracts without choosing an execution target."""

    environment = deepcopy(environment)
    problems: list[Problem] = list(environment.problems)
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
    try:
        verified_program = seal_typed_program(
            program,
            phase=ProblemPhase.PLANNING,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
        verified_program = None

    if verified_program is not None and environment.valid:
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
    if verified_program is None:
        raise AssertionError("successful link lost its verified compiler program")
    return LinkedPlan(
        verified_program,
        environment,
    )


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
    selected = value if isinstance(value, EntityRef) else EntityRef(id=str(value))
    known = environment.config.topology.entity(selected.id)
    if known is None:
        problems.append(
            compiler_problem(
                "unknown_authoring_entity",
                f"experiment references unknown entity {selected.id}",
                model_location("entity", selected.id),
                phase=ProblemPhase.PLANNING,
                category=ProblemCategory.NOT_FOUND,
            )
        )
        return None
    if (
        selected.kind is not None
        and known.kind is not None
        and selected.kind != known.kind
    ):
        problems.append(
            compiler_problem(
                "authoring_entity_kind_mismatch",
                f"entity {selected.id} has kind {known.kind}, not {selected.kind}",
                model_location("entity", selected.id),
                phase=ProblemPhase.PLANNING,
            )
        )
        return None
    return EntityRef(
        id=selected.id,
        kind=selected.kind or known.kind,
        metadata={**known.metadata, **selected.metadata},
    )


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
    "MaterializedLinkedPoints",
    "link_program",
    "materialize_linked_points",
    "materialize_selected_linked_points",
    "select_linked_program",
]
