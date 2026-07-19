"""Config-free verification for closed transient compiler programs.

Semantic operation contracts and implementation sidecars arrive through the
verified assembly proof.  This pass owns only invariants introduced by typed
lowering and does not re-verify those source facts.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from types import MappingProxyType

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.model import (
    LiteralScalarExpr,
    RowScopeId,
)
from scopecat.compiler.relations.uses import RelationUseId
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RowType,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.measurement_transforms import (
    typed_measurement_transform_problems,
)
from scopecat.compiler.typed.point_domain import (
    PointDomainVerificationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.compiler.typed.products import (
    DomainProductProducer,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    RouteInput,
    ValueInput,
    core_actions,
    core_domain_executions,
    core_state,
)
from scopecat.compiler.typed.records import (
    plan_records,
    validate_product_defs,
    validate_product_graph,
    validate_record_plan,
)
from scopecat.compiler.typed.relation_consumers import ProgramRelationConsumerKind
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductProducerId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import Payload, Scalar, String


def verify_core_program(program: CoreProgram) -> CoreProgram:
    """Return a topologically ordered program after pure IR verification."""

    verified, _, _ = _verify_core_program(program)
    return verified


def _verified_route_capabilities(
    program: CoreProgram,
) -> tuple[dict[LogicalResourcePortId, set[str]], tuple[Problem, ...]]:
    route_problems: list[Problem] = []
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
        route_problems.append(
            _problem(
                "resource_route_duplicate",
                f"route port {port_id.qualified_name!r} is declared more than once",
                model_location("route_intents", port_id.qualified_name),
            )
        )

    return route_capabilities, tuple(route_problems)


def _verify_core_program(
    program: CoreProgram,
) -> tuple[
    CoreProgram,
    VerifiedPointDomain,
    tuple[ProgramRelationConsumer, ...],
]:
    """Normalize once and retain every proof derived during verification."""

    problems: list[Problem] = []
    verified_point_domain: VerifiedPointDomain | None = None
    consumers: tuple[ProgramRelationConsumer, ...] | None = None
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
    compute_nodes = program.compute_nodes
    problems.extend(_core_domain_problems(program))
    measurement_transforms, transform_problems = typed_measurement_transform_problems(
        program
    )
    problems.extend(transform_problems)
    if measurement_transforms != program.measurement_transforms:
        program = replace(
            program,
            measurement_transforms=measurement_transforms,
        )
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

    route_capabilities, route_problems = _verified_route_capabilities(program)
    problems.extend(route_problems)

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
    action_ids = tuple(action.id for action in core_actions(program))
    if len(action_ids) != len(set(action_ids)):
        problems.append(
            _problem(
                "instrument_action_duplicate",
                "instrument action ids must be unique",
                model_location("actions"),
            )
        )
    for action_index, action in enumerate(core_actions(program)):
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
    for location, state in _state_specs(core_state(program)):
        if not isinstance(state, SetStateSpec):
            continue
        if not state.capability_id or not state.field_path:
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
        elif not isinstance(target.use.value.value_type.atom, String):
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
        else:
            root = target.use.value.plan.root
            if isinstance(root, LiteralScalarExpr) and (
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
        (
            *program.instrument_product_producers,
            *program.domain_product_producers,
            *program.measurement_transform_product_producers,
        ),
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
    if verified_point_domain is None or consumers is None:
        raise AssertionError("successful typed verification lost its program proof")
    return program, verified_point_domain, consumers


def _core_domain_problems(program: CoreProgram) -> tuple[Problem, ...]:
    problems: list[Problem] = []

    products = {item.id for item in program.product_defs}
    uses = {item.id: item for item in program.product_uses}
    producers_by_result: dict[tuple[str, str], DomainProductProducer] = {}
    producer_ids: set[ProductProducerId] = set()
    for producer in program.domain_product_producers:
        if producer.id in producer_ids:
            problems.append(
                _problem(
                    "domain_product_producer_duplicate",
                    "domain product producer "
                    f"{producer.id.qualified_name!r} is duplicated",
                    model_location(
                        "domain_product_producers",
                        producer.id.qualified_name,
                    ),
                )
            )
        producer_ids.add(producer.id)
        key = (producer.execution_id, producer.result_id)
        if key in producers_by_result:
            problems.append(
                _problem(
                    "domain_result_producer_duplicate",
                    "one domain result has more than one product producer",
                    model_location(
                        "domain_product_producers",
                        producer.id.qualified_name,
                    ),
                )
            )
        producers_by_result[key] = producer

    declared_result_ids: set[tuple[str, str]] = set()
    produced_products: set[ProductId] = set()
    execution_ids = tuple(execution.id for execution in core_domain_executions(program))
    if len(execution_ids) != len(set(execution_ids)):
        problems.append(
            _problem(
                "domain_execution_id_duplicate",
                "typed domain execution ids must be unique",
                model_location("domain_executions"),
            )
        )
    for execution_index, execution in enumerate(core_domain_executions(program)):
        location = model_location("domain_executions", execution_index)
        declared = execution.program
        input_ports = {port.id: port for port in declared.input_ports}
        if tuple(execution.inputs) != tuple(input_ports):
            problems.append(
                _problem(
                    "domain_execution_input_contract_mismatch",
                    "domain execution inputs do not match the program port order",
                    model_location(location.root, *location.path, "inputs"),
                )
            )
        for name, value in execution.inputs.items():
            port = input_ports.get(name)
            if port is not None and not is_assignable(
                value.value_type,
                port.value_type,
            ):
                problems.append(
                    _problem(
                        "domain_execution_input_type_mismatch",
                        f"domain execution input {name!r} does not match its port type",
                        model_location(
                            location.root,
                            *location.path,
                            "inputs",
                            name,
                        ),
                    )
                )
        if tuple(result.id for result in execution.results) != tuple(
            port.id for port in declared.result_ports
        ):
            problems.append(
                _problem(
                    "domain_execution_result_contract_mismatch",
                    "domain execution results do not match the program port order",
                    model_location(location.root, *location.path, "results"),
                )
            )
        for result in execution.results:
            result_location = model_location(
                location.root,
                *location.path,
                "results",
                result.id,
            )
            key = (execution.id, result.id)
            declared_result_ids.add(key)
            if result.product_id in produced_products:
                problems.append(
                    _problem(
                        "domain_product_producer_duplicate",
                        f"logical product {result.product_id.qualified_name!r} has "
                        "more than one domain result producer",
                        result_location,
                    )
                )
            produced_products.add(result.product_id)
            if result.product_id not in products:
                problems.append(
                    _problem(
                        "domain_result_product_missing",
                        "domain result references unknown product "
                        f"{result.product_id.qualified_name!r}",
                        result_location,
                    )
                )
            producer = producers_by_result.get(key)
            if (
                producer is None
                or producer.id != result.producer_id
                or producer.product_id != result.product_id
            ):
                problems.append(
                    _problem(
                        "domain_result_producer_mismatch",
                        "domain result does not have one matching producer declaration",
                        result_location,
                    )
                )
            for use_id in result.product_use_ids:
                use = uses.get(use_id)
                if use is None or use.product_id != result.product_id:
                    problems.append(
                        _problem(
                            "domain_result_product_use_mismatch",
                            "domain result references a missing or foreign "
                            f"product use {use_id.value!r}",
                            result_location,
                        )
                    )
            expected_use_ids = tuple(
                use.id
                for use in program.product_uses
                if use.product_id == result.product_id
            )
            if result.product_use_ids != expected_use_ids:
                problems.append(
                    _problem(
                        "domain_result_product_use_coverage_mismatch",
                        "domain result does not retain every exact product use "
                        "occurrence",
                        result_location,
                    )
                )

    for key, producer in producers_by_result.items():
        if key not in declared_result_ids:
            problems.append(
                _problem(
                    "domain_product_producer_orphan",
                    "domain product producer references an unknown execution result",
                    model_location(
                        "domain_product_producers",
                        producer.id.qualified_name,
                    ),
                )
            )
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class ProgramRelationConsumer:
    """Diagnostic index entry for one verified relation-plan use."""

    id: RelationUseId
    kind: ProgramRelationConsumerKind
    plan: VerifiedRelationPlan[PlanNode]
    location: ModelLocation


@dataclass(frozen=True, slots=True)
class VerifiedCoreProgram:
    """A normalized CoreProgram whose complete executable surface was checked."""

    program: CoreProgram
    point_domain: VerifiedPointDomain = dc_field(init=False)
    relation_consumers: tuple[ProgramRelationConsumer, ...] = dc_field(init=False)
    _relation_plan_by_use: Mapping[RelationUseId, VerifiedRelationPlan[PlanNode]] = (
        dc_field(init=False, repr=False)
    )

    def __post_init__(self) -> None:
        program, point_domain, consumers = _verify_core_program(self.program)
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "point_domain", point_domain)
        object.__setattr__(
            self,
            "relation_consumers",
            consumers,
        )
        relation_plan_by_use = {consumer.id: consumer.plan for consumer in consumers}
        if len(relation_plan_by_use) != len(consumers):
            raise AssertionError("verified relation-use ids must be unique")
        object.__setattr__(
            self,
            "_relation_plan_by_use",
            MappingProxyType(relation_plan_by_use),
        )

    def relation_plan(
        self,
        relation_use_id: RelationUseId,
    ) -> VerifiedRelationPlan[PlanNode]:
        """Return the verified plan owned by an exact program consumer."""

        try:
            return self._relation_plan_by_use[relation_use_id]
        except KeyError:
            msg = f"no verified relation plan for relation use {relation_use_id}"
            raise KeyError(msg) from None


def seal_typed_program(
    program: CoreProgram,
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> VerifiedCoreProgram:
    """Verify, normalize, and seal one trusted transient program."""

    try:
        return VerifiedCoreProgram(program)
    except CheckFailed as error:
        if phase is ProblemPhase.AUTHORING:
            raise
        raise CheckFailed(
            tuple(
                problem.model_copy(update={"phase": phase})
                for problem in error.problems
            )
        ) from error


def typed_program_proof_role_problems(
    program: CoreProgram,
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
            consumer.plan,
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
        plan=value.plan,
        location=location,
    )


def _program_relation_consumers_with_roles(
    program: CoreProgram,
    *,
    point_domain: VerifiedPointDomain,
) -> Iterator[tuple[ProgramRelationConsumer, _PlanConsumerRole]]:
    """Enumerate the complete executable relation surface exactly once."""

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

    for execution_index, execution in enumerate(core_domain_executions(program)):
        for input_name, input_value in execution.inputs.items():
            yield (
                _consumer(
                    input_value.relation_use_id,
                    ProgramRelationConsumerKind.DOMAIN_EXECUTION_INPUT,
                    input_value.value,
                    model_location(
                        "domain_executions",
                        execution_index,
                        "inputs",
                        input_name,
                    ),
                ),
                point_role,
            )

    for state_index, state in enumerate(core_state(program)):
        yield from _state_relation_consumers_with_roles(
            state,
            role=point_role,
            location=model_location("state", state_index),
        )
    for action_index, action in enumerate(core_actions(program)):
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
    """Reject occurrence aliasing before plans are indexed by relation-use id."""

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
    state: StateSpecVariant,
    *,
    role: _PlanConsumerRole,
    location: ModelLocation,
) -> Iterator[tuple[ProgramRelationConsumer, _PlanConsumerRole]]:
    if isinstance(state, SetStateSpec):
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
        if not isinstance(state.value_use, ComputeResultRef):
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
    for index, child in enumerate(state.state):
        yield from _state_relation_consumers_with_roles(
            child,
            role=child_role,
            location=model_location(location.root, *location.path, "state", index),
        )


def _state_specs(
    roots: Sequence[StateSpecVariant],
) -> Iterator[tuple[ModelLocation, StateSpecVariant]]:
    def visit(
        location: ModelLocation,
        state: StateSpecVariant,
    ) -> Iterator[tuple[ModelLocation, StateSpecVariant]]:
        yield location, state
        if not isinstance(state, ForEachStateSpec):
            return
        for index, child in enumerate(state.state):
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
    "ProgramRelationConsumer",
    "ProgramRelationConsumerKind",
    "VerifiedCoreProgram",
    "seal_typed_program",
    "typed_program_proof_role_problems",
    "verify_core_program",
]
