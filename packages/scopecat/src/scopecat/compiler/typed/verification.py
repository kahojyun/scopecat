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
from scopecat.compiler.relations.model import RowScopeId
from scopecat.compiler.relations.point_domain import iter_point_axis_linear
from scopecat.compiler.relations.uses import RelationUseId
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RowType,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.dependencies import (
    ComputePlan,
    VariationAnalysis,
    analyze_compute_plan,
    analyze_variation_support,
)
from scopecat.compiler.typed.iteration import (
    PointIterationLayout,
    analyze_point_iteration_layout,
)
from scopecat.compiler.typed.measurement_transforms import (
    typed_measurement_transform_problems,
)
from scopecat.compiler.typed.point_domain import (
    PointDomainVerificationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    ValueInput,
    core_acquisitions,
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
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import Payload, Scalar


def verify_core_program(program: CoreProgram) -> CoreProgram:
    """Return a topologically ordered program after pure IR verification."""

    verified, _, _ = _verify_core_program(program)
    return verified


def _verified_resource_capabilities(
    program: CoreProgram,
) -> tuple[dict[LogicalResourcePortId, set[str]], tuple[Problem, ...]]:
    resource_problems: list[Problem] = []
    resource_capabilities: dict[LogicalResourcePortId, set[str]] = {}
    duplicate_requirements: set[LogicalResourcePortId] = set()
    for requirement in program.resource_requirements:
        if requirement.port_id in resource_capabilities:
            duplicate_requirements.add(requirement.port_id)
            continue
        resource_capabilities[requirement.port_id] = set(requirement.capabilities)
    for port_id in sorted(
        duplicate_requirements,
        key=lambda item: item.qualified_name,
    ):
        resource_problems.append(
            _problem(
                "resource_requirement_duplicate",
                f"resource port {port_id.qualified_name!r} is declared more than once",
                model_location("resource_requirements", port_id.qualified_name),
            )
        )

    return resource_capabilities, tuple(resource_problems)


def _domain_resource_problems(
    program: CoreProgram,
    resource_capabilities: Mapping[LogicalResourcePortId, set[str]],
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for execution_index, execution in enumerate(core_domain_executions(program)):
        resource_ports = {port.id: port for port in execution.program.resource_ports}
        for role, resource_id in execution.resources.items():
            port = resource_ports[role]
            for capability in port.capabilities or (None,):
                problems.extend(
                    _logical_resource_port_problems(
                        resource_id,
                        required_capability=capability,
                        resource_capabilities=resource_capabilities,
                        location=model_location(
                            "domain_executions",
                            execution_index,
                            "resources",
                            role,
                        ),
                        missing_code="domain_resource_port_missing",
                        capability_code="domain_resource_port_capability_missing",
                        consumer="domain resource",
                    )
                )
    return tuple(problems)


def _product_owner_problems(program: CoreProgram) -> tuple[Problem, ...]:
    """Validate direct product owners across acquisition, domain, and transforms."""

    problems: list[Problem] = []
    acquisitions = core_acquisitions(program)
    acquisition_ids = tuple(acquisition.id for acquisition in acquisitions)
    if len(acquisition_ids) != len(set(acquisition_ids)):
        problems.append(
            _problem(
                "product_acquire_id_duplicate",
                "acquisition ids must be unique",
                model_location("acquisitions"),
            )
        )
    acquired_products = [
        product.product_id
        for acquisition in acquisitions
        for product in acquisition.products
    ]
    domain_products = {
        result.product_id
        for execution in core_domain_executions(program)
        for result in execution.results
    }
    transform_products = {
        output.product_id
        for transform in program.measurement_transforms
        for output in transform.outputs
    }
    external_products = domain_products | transform_products
    defined_products = {product.id for product in program.product_defs}
    owned_products = set(acquired_products) | external_products
    for product_id in sorted(
        {use.product_id for use in program.product_uses} - owned_products,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "product_acquire_missing",
                f"product {product_id.qualified_name!r} is selected but has no "
                "acquisition, domain, or transform owner",
                model_location("product_uses", product_id.qualified_name),
            )
        )
    repeated = {
        product_id
        for product_id in acquired_products
        if acquired_products.count(product_id) > 1
    }
    for product_id in sorted(repeated, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "product_acquire_duplicate",
                f"instrument product {product_id.qualified_name!r} is acquired "
                "more than once per point",
                model_location("acquisitions", product_id.qualified_name),
            )
        )
    for product_id in sorted(
        set(acquired_products) - defined_products,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "product_acquire_definition_missing",
                f"acquisition references unknown product {product_id.qualified_name!r}",
                model_location("acquisitions", product_id.qualified_name),
            )
        )
    for product_id in sorted(
        set(acquired_products) & external_products,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "product_owner_conflict",
                f"product {product_id.qualified_name!r} is owned by both an "
                "acquisition and a domain or transform producer",
                model_location("acquisitions", product_id.qualified_name),
            )
        )
    for product_id in sorted(
        domain_products & transform_products,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "measurement_transform_product_domain_producer_conflict",
                f"transform-derived product {product_id.qualified_name!r} also "
                "has a domain producer",
                model_location("product_defs", product_id.qualified_name),
            )
        )
    return tuple(problems)


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
        consumer_roles = tuple(
            _program_relation_consumers_with_roles(
                program,
                point_domain=verified_point_domain,
            )
        )
        for consumer, role in consumer_roles:
            _verify_plan_role(
                consumer.plan,
                role=role,
                location=consumer.location,
                phase=ProblemPhase.AUTHORING,
                problems=problems,
            )
        consumers = (
            *tuple(_point_axis_center_consumers(verified_point_domain)),
            *(consumer for consumer, _role in consumer_roles),
        )
        problems.extend(_relation_use_identity_problems(consumers))

    resource_capabilities, resource_problems = _verified_resource_capabilities(program)
    problems.extend(resource_problems)

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
                resource_capabilities=resource_capabilities,
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
    problems.extend(_domain_resource_problems(program, resource_capabilities))
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
        problems.extend(
            _logical_resource_port_problems(
                state.resource_target.port_id,
                required_capability=state.capability_id,
                resource_capabilities=resource_capabilities,
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

    for acquisition_index, acquisition in enumerate(core_acquisitions(program)):
        problems.extend(
            _logical_resource_port_problems(
                acquisition.resource_port_id,
                required_capability=acquisition.capability_id,
                resource_capabilities=resource_capabilities,
                location=model_location(
                    "acquisitions",
                    acquisition_index,
                    "resource_port_id",
                ),
                missing_code="acquire_resource_port_missing",
                capability_code="acquire_resource_port_capability_missing",
                consumer="acquisition",
            )
        )

    product_schema_problems = validate_product_defs(
        program.product_defs,
        phase=ProblemPhase.AUTHORING,
    )
    product_graph_problems = validate_product_graph(
        program.product_defs,
        program.product_uses,
        program.record_uses,
        phase=ProblemPhase.AUTHORING,
    )
    problems.extend(product_schema_problems)
    problems.extend(product_graph_problems)
    problems.extend(_product_owner_problems(program))
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
    iteration_layout: PointIterationLayout = dc_field(init=False)
    relation_consumers: tuple[ProgramRelationConsumer, ...] = dc_field(init=False)
    compute_plan: ComputePlan = dc_field(init=False)
    variation_analysis: VariationAnalysis = dc_field(init=False)
    _relation_plan_by_use: Mapping[RelationUseId, VerifiedRelationPlan[PlanNode]] = (
        dc_field(init=False, repr=False)
    )

    def __post_init__(self) -> None:
        program, point_domain, consumers = _verify_core_program(self.program)
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "point_domain", point_domain)
        object.__setattr__(
            self,
            "iteration_layout",
            analyze_point_iteration_layout(point_domain),
        )
        compute_plan = analyze_compute_plan(program)
        object.__setattr__(self, "compute_plan", compute_plan)
        object.__setattr__(
            self,
            "variation_analysis",
            analyze_variation_support(program, compute_plan),
        )
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


@dataclass(frozen=True, slots=True)
class _PlanConsumerRole:
    point: RowType | None = None
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


def _point_axis_center_consumers(
    point_domain: VerifiedPointDomain,
) -> Iterator[ProgramRelationConsumer]:
    """Index centers already checked in their exact structural row roles."""

    for path, source in iter_point_axis_linear(point_domain.root):
        center = source.center
        yield _consumer(
            center.id,
            ProgramRelationConsumerKind.POINT_AXIS_CENTER,
            center.value,
            model_location("point_domain", *path, "source", "center"),
        )


def _program_relation_consumers_with_roles(
    program: CoreProgram,
    *,
    point_domain: VerifiedPointDomain,
) -> Iterator[tuple[ProgramRelationConsumer, _PlanConsumerRole]]:
    """Enumerate consumers verified under one generic compiler row role."""

    point_row = RowType.from_table(point_domain.value_type)
    point_role = _PlanConsumerRole(point=point_row)

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

    for requirement_index, requirement in enumerate(program.resource_requirements):
        for expression_index, use in enumerate(requirement.entity_uses):
            yield (
                _consumer(
                    use.id,
                    ProgramRelationConsumerKind.RESOURCE_ENTITY,
                    use.value,
                    model_location(
                        "resource_requirements",
                        requirement_index,
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
        reverified.imports != plan.imports
        or reverified.external_row_interface != plan.external_row_interface
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
        for index, use in enumerate(state.target_entity_uses):
            yield (
                _consumer(
                    use.id,
                    ProgramRelationConsumerKind.STATE_TARGET_ENTITY,
                    use.value,
                    model_location(
                        location.root,
                        *location.path,
                        "target_entities",
                        index,
                    ),
                ),
                role,
            )
        return

    relation_role = _PlanConsumerRole(
        point=role.point,
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
    row_arguments[state.row_scope_id] = row
    child_role = _PlanConsumerRole(
        point=role.point,
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
    resource_capabilities: Mapping[LogicalResourcePortId, set[str]],
    location: ModelLocation,
    missing_code: str,
    capability_code: str,
    consumer: str,
) -> tuple[Problem, ...]:
    declared = resource_capabilities.get(port_id)
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
    "verify_core_program",
]
