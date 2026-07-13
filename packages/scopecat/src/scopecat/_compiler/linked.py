"""Config-linked symbolic programs before any target materialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.point_domain import VerifiedPointDomain
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
    ProgramRelationConsumer,
    VerifiedTypedProgram,
    seal_typed_program,
)
from scopecat._point_domain_algebra import PointCardinality
from scopecat._product_identity import ProductUse
from scopecat._relation_backend import (
    ParameterRelationData,
    validate_relation_parameter_import,
)
from scopecat._relation_verification import PlanImportNamespace
from scopecat._resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.errors import CheckFailed
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

_LINKED_PLAN_TOKEN = object()


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
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _LINKED_PLAN_TOKEN:
            msg = "LinkedPlan can only be created by link_program"
            raise TypeError(msg)
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
        _token=_LINKED_PLAN_TOKEN,
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


__all__ = ["LinkedPlan", "link_program"]
