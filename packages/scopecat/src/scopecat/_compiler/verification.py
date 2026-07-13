"""Config-free verification for closed transient compiler programs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import cast

from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.implementations import validate_local_implementation_catalog
from scopecat._compiler.point_domain import (
    PointDomainVerificationError,
    SelectedPointDomain,
    VerifiedPointDomain,
    bind_selected_point_domain,
    verify_point_domain,
)
from scopecat._compiler.problems import compiler_problem
from scopecat._compiler.program import (
    RouteInput,
    TypedComputeNode,
    TypedProgram,
    ValueInput,
)
from scopecat._compiler.records import (
    plan_records,
    validate_product_defs,
    validate_product_graph,
    validate_record_plan,
)
from scopecat._compiler.relation_consumers import ProgramRelationConsumerKind
from scopecat._compiler.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    StateSpec,
)
from scopecat._compute_result import ComputeResultRef
from scopecat._operation_contract import (
    ScalarBinarySemantics,
    operation_contract_issues,
)
from scopecat._relation_analysis import PlanNode
from scopecat._relation_backend import (
    RelationBackend,
    RelationBackendCapabilityError,
    RelationBackendCapabilityIssue,
    SelectedRelationPlan,
    select_relation_plan,
)
from scopecat._relation_use import RelationUseId
from scopecat._relation_verification import (
    RelationPlanVerificationError,
    RowType,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat._relations import RelationExpr, RowScopeId, ScalarExpr
from scopecat._resource_identity import (
    LogicalResourcePortId,
)
from scopecat._scalar_operators import scalar_operator_result_type
from scopecat._value_expressions import ValueExpr
from scopecat.errors import CheckFailed
from scopecat.problems import ModelLocation, Problem, ProblemPhase, model_location
from scopecat.value_types import Payload, Scalar, String


def verify_typed_program(program: TypedProgram) -> TypedProgram:
    """Return a topologically ordered program after pure IR verification."""

    problems: list[Problem] = []
    verified_point_domain: VerifiedPointDomain | None = None
    try:
        verified_point_domain = verify_point_domain(
            program.point_domain,
            program_id=program.id,
        )
    except PointDomainVerificationError as error:
        problems.extend(
            _problem(
                issue.code,
                issue.message,
                model_location("point_domain", *issue.path),
            )
            for issue in error.issues
        )
    try:
        compute_nodes = order_compute_nodes(program.compute_nodes)
    except ComputeGraphError as error:
        problems.append(_problem(error.code, str(error), error.location))
        compute_nodes = program.compute_nodes
    problems.extend(_typed_compute_contract_problems(compute_nodes))
    implementation_problems = validate_local_implementation_catalog(
        compute_nodes,
        program.implementation_catalog,
        phase=ProblemPhase.AUTHORING,
    )
    problems.extend(implementation_problems)
    if verified_point_domain is not None:
        problems.extend(
            typed_program_proof_role_problems(
                program,
                _point_domain=verified_point_domain,
            )
        )
        consumers = tuple(
            consumer
            for consumer, _role in _program_relation_consumers_with_roles(
                program,
                point_domain=verified_point_domain,
            )
        )
        problems.extend(_relation_use_identity_problems(consumers))

    route_capabilities: dict[LogicalResourcePortId, set[str]] = {}
    duplicate_routes: set[LogicalResourcePortId] = set()
    for route in program.route_intents:
        if route.port_id in route_capabilities:
            duplicate_routes.add(route.port_id)
            continue
        route_capabilities[route.port_id] = set(route.capabilities)
    for port_id in sorted(
        duplicate_routes,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "resource_route_duplicate",
                f"route port {port_id.qualified_name!r} is declared more than once",
                model_location("route_intents", port_id.qualified_name),
            )
        )

    for node in compute_nodes:
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, RouteInput):
                continue
            location = model_location(
                "compute_nodes",
                *node.id.scope,
                node.id.local_id,
                "inputs",
                input_name,
            )
            declared = route_capabilities.get(input_value.port_id)
            if declared is None:
                problems.append(
                    _problem(
                        "compute_route_port_missing",
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} references undeclared route port "
                        f"{input_value.port_id.qualified_name!r}",
                        location,
                    )
                )
                continue
            missing = sorted(set(input_value.value_type.capabilities) - declared)
            if missing:
                problems.append(
                    _problem(
                        "compute_route_capability_missing",
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} requires capabilities not declared by "
                        f"route port {input_value.port_id.qualified_name!r}: "
                        f"{', '.join(missing)}",
                        location,
                    )
                )

    compute_outputs = {node.result.id: node.result for node in compute_nodes}
    action_ids = tuple(action.id for action in program.actions)
    if len(action_ids) != len(set(action_ids)):
        problems.append(
            _problem(
                "instrument_action_duplicate",
                "instrument action ids must be unique",
                model_location("actions"),
            )
        )
    for action_index, action in enumerate(program.actions):
        problems.extend(
            _logical_resource_port_problems(
                action.resource_port_id,
                required_capability=action.capability_id,
                route_capabilities=route_capabilities,
                location=model_location(
                    "actions",
                    action_index,
                    "resource_port_id",
                ),
                missing_code="action_resource_port_missing",
                capability_code="action_resource_port_capability_missing",
                consumer="action",
            )
        )
        for field_index, field in enumerate(action.fields):
            value = field.value_use
            if not isinstance(value, ComputeResultRef):
                continue
            output = compute_outputs.get(value.value_id)
            location = model_location(
                "actions",
                action_index,
                "fields",
                field_index,
                "value",
            )
            if output is None:
                problems.append(
                    _problem(
                        "compute_payload_unknown_output",
                        "action references unknown compute output "
                        f"{value.value_id.qualified_name!r}",
                        location,
                    )
                )
            elif not _is_payload_type(output.value_type):
                problems.append(
                    _problem(
                        "compute_payload_unavailable",
                        "action compute output is not an available payload: "
                        f"{value.value_id.qualified_name!r}",
                        location,
                    )
                )
    for location, state in _state_specs(program.state):
        if state.kind == "set" and (not state.capability_id or not state.field_path):
            problems.append(
                _problem(
                    "state_field_requires_capability",
                    "state capability and field path must be non-empty",
                    model_location(location.root, *location.path, "field"),
                )
            )
        target = state.resource_target
        if isinstance(target, LogicalStateResourceTarget):
            problems.extend(
                _logical_resource_port_problems(
                    target.port_id,
                    required_capability=state.capability_id,
                    route_capabilities=route_capabilities,
                    location=model_location(
                        location.root,
                        *location.path,
                        "resource_port_id",
                    ),
                    missing_code="state_resource_port_missing",
                    capability_code="state_resource_port_capability_missing",
                    consumer="state",
                )
            )
        elif isinstance(target, PhysicalStateResourceTarget) and not isinstance(
            target.use.value.value_type.atom,
            String,
        ):
            problems.append(
                _problem(
                    "state_physical_resource_type_invalid",
                    "physical state resource expressions must have string scalar type",
                    model_location(
                        location.root,
                        *location.path,
                        "physical_resource_id",
                    ),
                )
            )
        elif isinstance(target, PhysicalStateResourceTarget):
            root = target.use.value.plan.root
            if root.kind == "literal" and (
                not isinstance(root.value, str) or not root.value
            ):
                problems.append(
                    _problem(
                        "state_physical_resource_id_invalid",
                        "literal physical state resource ids must be non-empty strings",
                        model_location(
                            location.root,
                            *location.path,
                            "physical_resource_id",
                        ),
                    )
                )
        value = state.value_use
        if not isinstance(value, ComputeResultRef):
            continue
        output = compute_outputs.get(value.value_id)
        if output is None:
            problems.append(
                _problem(
                    "compute_payload_unknown_output",
                    "state references unknown compute output "
                    f"{value.value_id.qualified_name!r}",
                    model_location(location.root, *location.path, "value"),
                )
            )
        elif not _is_payload_type(output.value_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{value.value_id.qualified_name!r}",
                    model_location(location.root, *location.path, "value"),
                )
            )

    for producer_index, producer in enumerate(program.instrument_product_producers):
        if not isinstance(producer.resource_target, LogicalResourcePortId):
            continue
        problems.extend(
            _logical_resource_port_problems(
                producer.resource_target,
                required_capability=producer.capability,
                route_capabilities=route_capabilities,
                location=model_location(
                    "instrument_product_producers",
                    producer_index,
                    "resource_port_id",
                ),
                missing_code="product_resource_port_missing",
                capability_code="product_resource_port_capability_missing",
                consumer="product",
            )
        )

    product_schema_problems = validate_product_defs(
        program.product_defs,
        phase=ProblemPhase.AUTHORING,
    )
    product_graph_problems = validate_product_graph(
        program.product_defs,
        program.instrument_product_producers,
        program.product_uses,
        program.record_uses,
        phase=ProblemPhase.AUTHORING,
    )
    problems.extend(product_schema_problems)
    problems.extend(product_graph_problems)
    coordinate_ids = (
        tuple(column.id for column in verified_point_domain.coordinate_columns)
        if verified_point_domain is not None
        else ()
    )
    if not product_graph_problems:
        problems.extend(
            validate_record_plan(
                plan_records(
                    program.product_defs,
                    program.product_uses,
                    program.record_uses,
                    point_count=1,
                ),
                coordinate_ids=coordinate_ids,
                phase=ProblemPhase.AUTHORING,
            )
        )

    if problems:
        raise CheckFailed(problems)
    if compute_nodes == program.compute_nodes:
        return program
    return program.model_copy(update={"compute_nodes": compute_nodes})


def _typed_compute_contract_problems(
    nodes: Sequence[TypedComputeNode],
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for node in nodes:
        location = model_location(
            "compute_nodes",
            *node.id.scope,
            node.id.local_id,
        )
        contract_issues = operation_contract_issues(node.contract)
        problems.extend(
            _problem(issue.code, issue.message, location) for issue in contract_issues
        )
        semantics = node.contract.semantics
        if not isinstance(semantics, ScalarBinarySemantics):
            continue
        inputs = node.inputs
        if set(inputs) != {"left", "right"}:
            problems.append(
                _problem(
                    "semantic_scalar_binary_shape_invalid",
                    "scalar binary operation requires left/right inputs and one "
                    "result output",
                    location,
                )
            )
            continue
        left = inputs["left"]
        right = inputs["right"]
        if not isinstance(left.value_type, Scalar) or not isinstance(
            right.value_type,
            Scalar,
        ):
            problems.append(
                _problem(
                    "semantic_scalar_binary_input_type_invalid",
                    "scalar binary operation inputs must be scalar-shaped",
                    location,
                )
            )
            continue
        if any(
            issue.code == "semantic_scalar_binary_operator_invalid"
            for issue in contract_issues
        ):
            continue
        try:
            expected_type = scalar_operator_result_type(
                left.value_type,
                right.value_type,
                semantics.operator,
                left_is_null_literal=_is_null_value_input(left),
                right_is_null_literal=_is_null_value_input(right),
            )
        except (TypeError, ValueError) as error:
            problems.append(
                _problem(
                    "semantic_scalar_binary_input_type_invalid",
                    str(error),
                    location,
                )
            )
            continue
        if node.result.value_type != expected_type:
            problems.append(
                _problem(
                    "semantic_scalar_binary_result_type_mismatch",
                    f"scalar operation result type {node.result.value_type!r} does not "
                    f"match inferred type {expected_type!r}",
                    location,
                )
            )
    return tuple(problems)


def _is_null_value_input(value: object) -> bool:
    if not isinstance(value, ValueInput):
        return False
    root = value.value.plan.root
    return (
        isinstance(root, ScalarExpr) and root.kind == "literal" and root.value is None
    )


@dataclass(frozen=True, slots=True)
class ProgramRelationConsumer:
    """One executable value envelope and the consumer that owns its proof."""

    id: RelationUseId
    kind: ProgramRelationConsumerKind
    value: ValueExpr
    location: ModelLocation


@dataclass(frozen=True, slots=True, init=False)
class VerifiedTypedProgram:
    """A normalized TypedProgram whose complete executable surface was checked."""

    _program: TypedProgram
    _point_domain: VerifiedPointDomain
    relation_consumers: tuple[ProgramRelationConsumer, ...]

    def __init__(
        self,
        program: TypedProgram,
        relation_consumers: Sequence[ProgramRelationConsumer],
        point_domain: VerifiedPointDomain | None = None,
    ) -> None:
        if point_domain is None:
            raise AssertionError("verified typed program point domain is missing")
        object.__setattr__(self, "_program", program)
        object.__setattr__(self, "_point_domain", point_domain)
        object.__setattr__(self, "relation_consumers", tuple(relation_consumers))

    @property
    def program(self) -> TypedProgram:
        return self._program.model_copy(deep=True)

    @property
    def point_domain(self) -> VerifiedPointDomain:
        return self._point_domain


@dataclass(frozen=True, slots=True)
class ProgramRelationBackendFailure:
    """One backend capability issue attributed to its program consumer."""

    consumer: ProgramRelationConsumer
    issue: RelationBackendCapabilityIssue


class ProgramRelationBackendCapabilityError(ValueError):
    """A backend rejected one or more plans in a verified typed program."""

    def __init__(
        self,
        backend_id: str,
        failures: Sequence[ProgramRelationBackendFailure],
    ) -> None:
        self.backend_id = backend_id
        self.failures = tuple(failures)
        rendered = "; ".join(
            f"{failure.consumer.kind.value}@{failure.consumer.location}: "
            f"{failure.issue.dimension.value}:{failure.issue.code}"
            for failure in self.failures
        )
        super().__init__(
            f"relation backend {backend_id!r} rejected typed program: {rendered}"
        )


@dataclass(frozen=True, slots=True)
class SelectedProgramRelation:
    """One program consumer paired with its backend-selected relation proof."""

    consumer: ProgramRelationConsumer
    selected_plan: SelectedRelationPlan[PlanNode]


@dataclass(frozen=True, slots=True, init=False)
class SelectedTypedProgram:
    """A verified program whose every executable relation targets one backend."""

    _verified_program: VerifiedTypedProgram
    _point_domain: SelectedPointDomain
    backend_id: str
    relation_selections: tuple[SelectedProgramRelation, ...]
    _selection_by_use: Mapping[
        RelationUseId,
        SelectedProgramRelation,
    ]

    def __init__(
        self,
        verified_program: VerifiedTypedProgram,
        backend_id: str,
        relation_selections: Sequence[SelectedProgramRelation],
        point_domain: SelectedPointDomain | None = None,
    ) -> None:
        if point_domain is None:
            raise AssertionError("selected typed program point domain is missing")
        if not backend_id:
            msg = "selected typed-program backend id must be non-empty"
            raise ValueError(msg)
        if point_domain.verified is not verified_program.point_domain:
            msg = "selected point domain must belong to the verified typed program"
            raise ValueError(msg)
        if point_domain.backend_id != backend_id:
            msg = "selected point domain and typed program must use one backend"
            raise ValueError(msg)
        selected = tuple(relation_selections)
        by_use = {selection.consumer.id: selection for selection in selected}
        if len(by_use) != len(selected):
            msg = "typed-program relation-use identities must be unique"
            raise ValueError(msg)
        expected = verified_program.relation_consumers
        expected_by_id = {consumer.id: consumer for consumer in expected}
        if len(expected_by_id) != len(expected):
            msg = "verified typed-program relation identities must be unique"
            raise ValueError(msg)
        if set(by_use) != set(expected_by_id):
            msg = "selected relations must exactly cover verified program consumers"
            raise ValueError(msg)
        for relation_use_id, selection in by_use.items():
            consumer = expected_by_id[relation_use_id]
            if selection.consumer is not consumer:
                msg = "selected relation must use its verified program consumer"
                raise ValueError(msg)
            if selection.selected_plan.backend_id != backend_id:
                msg = "selected program relations must use one backend"
                raise ValueError(msg)
            if selection.selected_plan.verified_plan is not consumer.value.plan:
                msg = "selected relation plan does not own its consumer proof"
                raise ValueError(msg)
        for point_selection in point_domain.relation_selections:
            program_selection = by_use.get(point_selection.relation.id)
            if (
                program_selection is None
                or program_selection.selected_plan is not point_selection.selected_plan
            ):
                msg = "selected point-domain leaf must reuse whole-program selection"
                raise ValueError(msg)
        canonical = tuple(by_use[consumer.id] for consumer in expected)
        object.__setattr__(self, "_verified_program", verified_program)
        object.__setattr__(self, "_point_domain", point_domain)
        object.__setattr__(self, "backend_id", backend_id)
        object.__setattr__(self, "relation_selections", canonical)
        object.__setattr__(
            self,
            "_selection_by_use",
            MappingProxyType(by_use),
        )

    @property
    def verified_program(self) -> VerifiedTypedProgram:
        return self._verified_program

    @property
    def program(self) -> TypedProgram:
        return self._verified_program.program

    @property
    def point_domain(self) -> SelectedPointDomain:
        return self._point_domain

    def selected_plan(
        self,
        relation_use_id: RelationUseId,
    ) -> SelectedRelationPlan[PlanNode]:
        """Return the preflighted plan owned by an exact program consumer."""

        try:
            return self._selection_by_use[relation_use_id].selected_plan
        except KeyError as error:
            msg = f"no selected relation plan for relation use {relation_use_id}"
            raise KeyError(msg) from error


def seal_typed_program(
    program: TypedProgram,
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> VerifiedTypedProgram:
    """Verify, normalize, snapshot, and seal a complete transient program."""

    try:
        normalized = verify_typed_program(program)
    except CheckFailed as error:
        if phase is ProblemPhase.AUTHORING:
            raise
        raise CheckFailed(
            tuple(
                problem.model_copy(update={"phase": phase})
                for problem in error.problems
            )
        ) from error
    snapshot = normalized.model_copy(deep=True)
    point_domain = verify_point_domain(snapshot.point_domain, program_id=snapshot.id)
    consumers = tuple(
        consumer
        for consumer, _role in _program_relation_consumers_with_roles(
            snapshot,
            point_domain=point_domain,
        )
    )
    return VerifiedTypedProgram(
        snapshot,
        consumers,
        point_domain,
    )


def select_typed_program(
    backend: RelationBackend,
    verified_program: VerifiedTypedProgram,
) -> SelectedTypedProgram:
    """Preflight every relation consumer before any program materialization."""

    if not isinstance(cast("object", verified_program), VerifiedTypedProgram):
        msg = "program backend selection requires a VerifiedTypedProgram"
        raise TypeError(msg)
    selections: list[SelectedProgramRelation] = []
    failures: list[ProgramRelationBackendFailure] = []
    for consumer in verified_program.relation_consumers:
        try:
            selected = select_relation_plan(backend, consumer.value.plan)
        except RelationBackendCapabilityError as error:
            failures.extend(
                ProgramRelationBackendFailure(consumer=consumer, issue=issue)
                for issue in error.issues
            )
            continue
        selections.append(
            SelectedProgramRelation(
                consumer=consumer,
                selected_plan=selected,
            )
        )
    if failures:
        raise ProgramRelationBackendCapabilityError(backend.backend_id, failures)
    point_domain_selections = {
        selection.consumer.id: cast(
            "SelectedRelationPlan[RelationExpr]",
            selection.selected_plan,
        )
        for selection in selections
        if selection.consumer.kind is ProgramRelationConsumerKind.POINT_DOMAIN_ROWS
    }
    selected_point_domain = bind_selected_point_domain(
        verified_program.point_domain,
        backend_id=backend.backend_id,
        selections=point_domain_selections,
    )
    return SelectedTypedProgram(
        verified_program,
        backend.backend_id,
        selections,
        selected_point_domain,
    )


def typed_program_proof_role_problems(
    program: TypedProgram,
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
    _point_domain: VerifiedPointDomain | None = None,
) -> tuple[Problem, ...]:
    """Return proof failures under the exact row roles supplied by consumers."""

    if _point_domain is None:
        try:
            _point_domain = verify_point_domain(
                program.point_domain,
                program_id=program.id,
            )
        except PointDomainVerificationError as error:
            return tuple(
                compiler_problem(
                    issue.code,
                    issue.message,
                    model_location("point_domain", *issue.path),
                    phase=phase,
                )
                for issue in error.issues
            )
    problems: list[Problem] = []
    for consumer, role in _program_relation_consumers_with_roles(
        program,
        point_domain=_point_domain,
    ):
        if consumer.kind is ProgramRelationConsumerKind.POINT_DOMAIN_ROWS:
            # VerifiedPointDomain owns each leaf's exact structural row role.
            continue
        _verify_plan_role(
            consumer.value.plan,
            role=role,
            location=consumer.location,
            phase=phase,
            problems=problems,
        )
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class _PlanConsumerRole:
    point: RowType | None = None
    current: RowType | None = None
    outer: RowType | None = None
    row_arguments: tuple[tuple[RowScopeId, RowType], ...] = ()


def _consumer(
    id: RelationUseId,  # noqa: A002
    kind: ProgramRelationConsumerKind,
    value: ValueExpr,
    location: ModelLocation,
) -> ProgramRelationConsumer:
    return ProgramRelationConsumer(
        id=id,
        kind=kind,
        value=value,
        location=location,
    )


def _program_relation_consumers_with_roles(
    program: TypedProgram,
    *,
    point_domain: VerifiedPointDomain,
) -> Iterator[tuple[ProgramRelationConsumer, _PlanConsumerRole]]:
    """Enumerate the complete proof-owning executable surface exactly once."""

    point_row = point_domain.row_type
    root_role = _PlanConsumerRole()
    point_role = _PlanConsumerRole(point=point_row)
    for relation in point_domain.relation_leaves:
        yield (
            _consumer(
                relation.id,
                ProgramRelationConsumerKind.POINT_DOMAIN_ROWS,
                relation.value,
                model_location("point_domain", *relation.path, "rows"),
            ),
            root_role,
        )

    for overlay_index, overlay in enumerate(program.parameter_overlays):
        for column_id, use in overlay.key_uses.items():
            yield (
                _consumer(
                    use.id,
                    ProgramRelationConsumerKind.PARAMETER_OVERLAY_KEY,
                    use.value,
                    model_location(
                        "parameter_overlays",
                        overlay_index,
                        "key",
                        column_id,
                    ),
                ),
                point_role,
            )
        yield (
            _consumer(
                overlay.value_use.id,
                ProgramRelationConsumerKind.PARAMETER_OVERLAY_VALUE,
                overlay.value_use.value,
                model_location("parameter_overlays", overlay_index, "value"),
            ),
            point_role,
        )

    for route_index, route in enumerate(program.route_intents):
        for expression_index, use in enumerate(route.entity_uses):
            yield (
                _consumer(
                    use.id,
                    ProgramRelationConsumerKind.ROUTE_ENTITY,
                    use.value,
                    model_location(
                        "route_intents",
                        route_index,
                        "entity_exprs",
                        expression_index,
                    ),
                ),
                point_role,
            )

    for node in program.compute_nodes:
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, ValueInput):
                continue
            yield (
                _consumer(
                    input_value.relation_use_id,
                    ProgramRelationConsumerKind.COMPUTE_INPUT,
                    input_value.value,
                    model_location(
                        "compute_nodes",
                        *node.id.scope,
                        node.id.local_id,
                        "inputs",
                        input_name,
                    ),
                ),
                point_role,
            )

    for state_index, state in enumerate(program.state):
        yield from _state_relation_consumers_with_roles(
            state,
            role=point_role,
            location=model_location("state", state_index),
        )
    for action_index, action in enumerate(program.actions):
        for field_index, field in enumerate(action.fields):
            if isinstance(field.value_use, ComputeResultRef):
                continue
            yield (
                _consumer(
                    field.value_use.id,
                    ProgramRelationConsumerKind.ACTION_VALUE,
                    field.value_use.value,
                    model_location(
                        "actions",
                        action_index,
                        "fields",
                        field_index,
                        "value",
                    ),
                ),
                point_role,
            )


def _verify_plan_role[NodeT: PlanNode](
    plan: VerifiedRelationPlan[NodeT],
    *,
    role: _PlanConsumerRole,
    location: ModelLocation,
    phase: ProblemPhase,
    problems: list[Problem],
) -> None:
    """Recheck one sealed proof under the row bindings its consumer supplies."""

    try:
        reverified = verify_relation_plan(
            plan.root,
            bindings=replace(
                plan.bindings,
                point_row=role.point,
                current_row=role.current,
                outer_row=role.outer,
                row_arguments=dict(role.row_arguments),
            ),
            expected_type=plan.certified_type,
        )
    except RelationPlanVerificationError as error:
        problems.append(
            compiler_problem(
                "compiler_relation_proof_role_mismatch",
                (
                    "verified relation plan is not valid in its consumer context: "
                    f"{error.reason}"
                ),
                model_location(location.root, *location.path, *error.path),
                phase=phase,
            )
        )
        return

    if (
        reverified.facts != plan.facts
        or reverified.imports != plan.imports
        or reverified.external_row_interface != plan.external_row_interface
        or reverified.required_operations != plan.required_operations
        or reverified.runtime_obligations != plan.runtime_obligations
    ):
        problems.append(
            compiler_problem(
                "compiler_relation_proof_role_mismatch",
                (
                    "consumer row roles change the stored relation proof; "
                    "the plan must be freshly verified in its consumer context"
                ),
                location,
                phase=phase,
            )
        )


def _relation_use_identity_problems(
    consumers: Sequence[ProgramRelationConsumer],
) -> tuple[Problem, ...]:
    """Reject occurrence aliasing before relation selection can collapse it."""

    first_by_id: dict[RelationUseId, ProgramRelationConsumer] = {}
    problems: list[Problem] = []
    for consumer in consumers:
        first = first_by_id.setdefault(consumer.id, consumer)
        if first is consumer:
            continue
        problems.append(
            compiler_problem(
                "compiler_relation_use_duplicate",
                (
                    f"{consumer.kind.value} aliases the relation-use identity "
                    f"already owned by {first.kind.value} at {first.location}"
                ),
                consumer.location,
                phase=ProblemPhase.AUTHORING,
                details={
                    "relation_use_id": consumer.id.value,
                    "first_kind": first.kind.value,
                    "first_location": {
                        "root": first.location.root,
                        "path": list(first.location.path),
                    },
                },
            )
        )
    return tuple(problems)


def _state_relation_consumers_with_roles(
    state: StateSpec,
    *,
    role: _PlanConsumerRole,
    location: ModelLocation,
) -> Iterator[tuple[ProgramRelationConsumer, _PlanConsumerRole]]:
    if state.kind == "set":
        resource_target = state.resource_target
        if isinstance(resource_target, PhysicalStateResourceTarget):
            yield (
                _consumer(
                    resource_target.use.id,
                    ProgramRelationConsumerKind.STATE_RESOURCE,
                    resource_target.use.value,
                    model_location(
                        location.root,
                        *location.path,
                        "physical_resource_id",
                    ),
                ),
                role,
            )
        if state.value_use is not None and not isinstance(
            state.value_use, ComputeResultRef
        ):
            yield (
                _consumer(
                    state.value_use.id,
                    ProgramRelationConsumerKind.STATE_VALUE,
                    state.value_use.value,
                    model_location(location.root, *location.path, "value"),
                ),
                role,
            )
        for index, use in enumerate(state.route_entity_uses):
            yield (
                _consumer(
                    use.id,
                    ProgramRelationConsumerKind.STATE_ROUTE_ENTITY,
                    use.value,
                    model_location(
                        location.root,
                        *location.path,
                        "route_entities",
                        index,
                    ),
                ),
                role,
            )
        return

    relation_role = _PlanConsumerRole(
        point=role.point,
        outer=role.current if role.current is not None else role.outer,
        row_arguments=role.row_arguments,
    )
    relation_use = state.relation_use
    if relation_use is None:
        return
    relation = relation_use.value
    yield (
        _consumer(
            relation_use.id,
            ProgramRelationConsumerKind.STATE_RELATION,
            relation,
            model_location(location.root, *location.path, "relation"),
        ),
        relation_role,
    )
    row = RowType.from_table(relation.value_type)
    row_arguments = dict(role.row_arguments)
    if state.row_scope_id is not None:
        row_arguments[state.row_scope_id] = row
    child_role = _PlanConsumerRole(
        point=role.point,
        current=row,
        outer=relation_role.outer,
        row_arguments=tuple(row_arguments.items()),
    )
    for index, child in enumerate(state.state or ()):
        yield from _state_relation_consumers_with_roles(
            child,
            role=child_role,
            location=model_location(location.root, *location.path, "state", index),
        )


def _state_specs(
    roots: Sequence[StateSpec],
) -> Iterator[tuple[ModelLocation, StateSpec]]:
    def visit(
        location: ModelLocation,
        state: StateSpec,
    ) -> Iterator[tuple[ModelLocation, StateSpec]]:
        yield location, state
        for index, child in enumerate(state.state or ()):
            yield from visit(
                model_location(location.root, *location.path, "state", index),
                child,
            )

    for index, state in enumerate(roots):
        yield from visit(model_location("state", index), state)


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)


def _logical_resource_port_problems(
    port_id: LogicalResourcePortId,
    *,
    required_capability: str | None,
    route_capabilities: Mapping[LogicalResourcePortId, set[str]],
    location: ModelLocation,
    missing_code: str,
    capability_code: str,
    consumer: str,
) -> tuple[Problem, ...]:
    declared = route_capabilities.get(port_id)
    if declared is None:
        return (
            _problem(
                missing_code,
                f"{consumer} references undeclared logical resource port "
                f"{port_id.qualified_name!r}",
                location,
            ),
        )
    if required_capability is None or required_capability in declared:
        return ()
    return (
        _problem(
            capability_code,
            f"{consumer} requires capability {required_capability!r} not declared "
            f"by logical resource port {port_id.qualified_name!r}",
            location,
        ),
    )


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        phase=ProblemPhase.AUTHORING,
    )


__all__ = [
    "ProgramRelationBackendCapabilityError",
    "ProgramRelationBackendFailure",
    "ProgramRelationConsumer",
    "ProgramRelationConsumerKind",
    "SelectedProgramRelation",
    "SelectedTypedProgram",
    "VerifiedTypedProgram",
    "seal_typed_program",
    "select_typed_program",
    "typed_program_proof_role_problems",
    "verify_typed_program",
]
