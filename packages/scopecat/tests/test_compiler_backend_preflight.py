from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.parameter_overlays import PointParameterOverlay
from scopecat._compiler.point_domain import PointDomain, bind_selected_point_domain
from scopecat._compiler.program import (
    ResourceRouteIntent,
    TypedComputeNode,
    TypedComputeOutput,
    TypedProgram,
    ValueInput,
    bind_each,
    set_state_field,
)
from scopecat._compiler.relation_consumers import ProgramRelationConsumerKind
from scopecat._compiler.state import PhysicalStateResourceTarget, StateSpec
from scopecat._compiler.verification import (
    SelectedProgramRelation,
    SelectedTypedProgram,
    VerifiedTypedProgram,
    seal_typed_program,
    select_typed_program,
)
from scopecat._compute_result import ComputeResultRef
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._point_domain_algebra import (
    POINT_UNIT,
    iter_point_relation_rows,
    point_product,
    point_rows,
)
from scopecat._relation_analysis import RelationOperation
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    PreparedRelationEvaluation,
    ReferenceRelationBackend,
    RelationBackendCapabilityIssue,
    RelationPlanRequirements,
    select_relation_plan,
)
from scopecat._relation_use import RelationUse, RelationUseId, relation_use
from scopecat._relation_verification import (
    RelationRuntimeObligationKind,
    RelationTypeBindings,
    RowType,
)
from scopecat._relations import (
    CellValue,
    RelationExpr,
    Row,
    ScalarExpr,
    SeriesExpr,
    col,
    grid,
    lit,
    literal_rows,
    point_col,
)
from scopecat._resource_identity import logical_resource_port_id
from scopecat._semantic_graph import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.errors import CheckFailed
from scopecat.problems import ProblemCategory, ProblemPhase, model_location
from scopecat.value_types import Float, Scalar, String, Table, TableColumn
from tests.support.authoring import load_config
from tests.support.relation_plans import (
    point_domain,
    scalar_value_expr,
    table_value_expr,
    value_expr,
)

_FLOAT = Scalar(Float())
_STRING = Scalar(String())
_EXECUTE_POINT = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)
_POINTS = Table(
    columns=(TableColumn("x", _FLOAT),),
    min_rows=1,
    max_rows=1,
)


class _BackendProbe:
    def __init__(
        self,
        *,
        unsupported: frozenset[RelationOperation] = frozenset(),
    ) -> None:
        self.backend_id = "tests.program-preflight"
        self.supported_operations = frozenset(RelationOperation) - unsupported
        self.discharged_obligations = frozenset(RelationRuntimeObligationKind)
        self.assessment_count = 0
        self.materialization_count = 0

    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> Sequence[RelationBackendCapabilityIssue]:
        _ = requirements
        self.assessment_count += 1
        return ()

    def materialize_scalar(
        self,
        evaluation: PreparedRelationEvaluation[ScalarExpr],
    ) -> CellValue:
        _ = evaluation
        self.materialization_count += 1
        raise AssertionError("program preflight must precede scalar materialization")

    def materialize_series(
        self,
        evaluation: PreparedRelationEvaluation[SeriesExpr],
    ) -> list[CellValue]:
        _ = evaluation
        self.materialization_count += 1
        raise AssertionError("program preflight must precede series materialization")

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _ = evaluation
        self.materialization_count += 1
        raise AssertionError("program preflight must precede relation materialization")


def _operation_id(local_id: str) -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _inventory_program() -> TypedProgram:
    point_bindings = RelationTypeBindings(point_row=RowType.from_table(_POINTS))
    row_type = Table(
        columns=(
            TableColumn("resource", _STRING),
            TableColumn("offset", _FLOAT),
        ),
        min_rows=1,
        max_rows=1,
    )
    row_bindings = RelationTypeBindings(current_row=RowType.from_table(row_type))
    child = set_state_field(
        scalar_value_expr(
            col("resource"),
            bindings=row_bindings,
            expected_type=_STRING,
        ),
        capability_id="set_offset",
        field_path="offset",
        value=scalar_value_expr(
            col("offset"),
            bindings=row_bindings,
            expected_type=_FLOAT,
        ),
        route_entities=(
            scalar_value_expr(
                col("resource"),
                bindings=row_bindings,
                expected_type=_STRING,
            ),
        ),
    )
    operation_id = _operation_id("consume")
    return TypedProgram(
        id="relation-consumer-inventory",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{"x": 1.0}]),
            expected_type=_POINTS,
        ),
        parameter_overlays=(
            PointParameterOverlay(
                table_id="calibration",
                key_uses={
                    "x": relation_use(
                        scalar_value_expr(
                            point_col("x"),
                            bindings=point_bindings,
                            expected_type=_FLOAT,
                        )
                    )
                },
                column_id="offset",
                value_use=relation_use(scalar_value_expr(2.0, expected_type=_FLOAT)),
            ),
        ),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("drive"),
                entity_uses=(
                    relation_use(
                        scalar_value_expr(
                            point_col("x"),
                            bindings=point_bindings,
                            expected_type=_FLOAT,
                        )
                    ),
                ),
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                inputs={
                    "x": ValueInput(
                        value=value_expr(
                            point_col("x"),
                            bindings=point_bindings,
                            expected_type=_FLOAT,
                        )
                    )
                },
                result=TypedComputeOutput(
                    id=operation_result_id(operation_id),
                    value_type=_FLOAT,
                    availability=_EXECUTE_POINT,
                ),
            ),
        ),
        implementation_catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python.consume.v1"),
                    operation_id=operation_id,
                    operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=lambda *, x: x,
                ),
            )
        ),
        state=(
            bind_each(
                table_value_expr(
                    literal_rows([{"resource": "source-0", "offset": 1.0}]),
                    expected_type=row_type,
                ),
                child,
            ),
        ),
    )


def test_program_seal_has_one_complete_recursive_relation_inventory() -> None:
    program = _inventory_program()

    verified = seal_typed_program(program)

    assert verified.point_domain.id.program_id == program.id
    assert verified.point_domain.domain == program.point_domain

    assert tuple(
        (consumer.kind, consumer.location) for consumer in verified.relation_consumers
    ) == (
        (
            ProgramRelationConsumerKind.POINT_DOMAIN_ROWS,
            model_location("point_domain", "rows"),
        ),
        (
            ProgramRelationConsumerKind.PARAMETER_OVERLAY_KEY,
            model_location("parameter_overlays", 0, "key", "x"),
        ),
        (
            ProgramRelationConsumerKind.PARAMETER_OVERLAY_VALUE,
            model_location("parameter_overlays", 0, "value"),
        ),
        (
            ProgramRelationConsumerKind.ROUTE_ENTITY,
            model_location("route_intents", 0, "entity_exprs", 0),
        ),
        (
            ProgramRelationConsumerKind.COMPUTE_INPUT,
            model_location("compute_nodes", "consume", "inputs", "x"),
        ),
        (
            ProgramRelationConsumerKind.STATE_RELATION,
            model_location("state", 0, "relation"),
        ),
        (
            ProgramRelationConsumerKind.STATE_RESOURCE,
            model_location("state", 0, "state", 0, "physical_resource_id"),
        ),
        (
            ProgramRelationConsumerKind.STATE_VALUE,
            model_location("state", 0, "state", 0, "value"),
        ),
        (
            ProgramRelationConsumerKind.STATE_ROUTE_ENTITY,
            model_location("state", 0, "state", 0, "route_entities", 0),
        ),
    )
    point_leaf = next(iter_point_relation_rows(program.point_domain.root))[1]
    overlay = program.parameter_overlays[0]
    route = program.route_intents[0]
    compute = program.compute_nodes[0].inputs["x"]
    assert isinstance(compute, ValueInput)
    root_state = program.state[0]
    assert root_state.relation_use is not None
    assert root_state.state is not None
    child_state = root_state.state[0]
    assert isinstance(child_state.resource_target, PhysicalStateResourceTarget)
    assert child_state.value_use is not None
    assert not isinstance(child_state.value_use, ComputeResultRef)
    assert tuple(consumer.id for consumer in verified.relation_consumers) == (
        point_leaf.relation_use_id,
        overlay.key_uses["x"].id,
        overlay.value_use.id,
        route.entity_uses[0].id,
        compute.relation_use_id,
        root_state.relation_use.id,
        child_state.resource_target.use.id,
        child_state.value_use.id,
        child_state.route_entity_uses[0].id,
    )
    assert len({consumer.id for consumer in verified.relation_consumers}) == 9

    with pytest.raises(ValidationError, match="frozen"):
        program.route_intents[0].entity_uses = ()

    copied = verified.program
    copied = copied.model_copy(
        update={
            "route_intents": (
                copied.route_intents[0].model_copy(update={"entity_uses": ()}),
            )
        }
    )
    assert not copied.route_intents[0].entity_uses
    assert verified.program.route_intents[0].entity_uses


def test_relation_use_identity_survives_reordering_and_insertion() -> None:
    first_use = relation_use(scalar_value_expr("first", expected_type=_STRING))
    second_use = relation_use(scalar_value_expr("second", expected_type=_STRING))
    program = TypedProgram(
        id="relation-use-reordering",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("first"),
                entity_uses=(first_use,),
            ),
            ResourceRouteIntent(
                port_id=logical_resource_port_id("second"),
                entity_uses=(second_use,),
            ),
        ),
    )

    before = seal_typed_program(program)
    after = seal_typed_program(
        program.model_copy(
            update={"route_intents": tuple(reversed(program.route_intents))}
        )
    )
    inserted_use = relation_use(scalar_value_expr("inserted", expected_type=_STRING))
    after_insertion = seal_typed_program(
        program.model_copy(
            update={
                "route_intents": (
                    ResourceRouteIntent(
                        port_id=logical_resource_port_id("inserted"),
                        entity_uses=(inserted_use,),
                    ),
                    *program.route_intents,
                )
            }
        )
    )

    before_by_id = {consumer.id: consumer for consumer in before.relation_consumers}
    after_by_id = {consumer.id: consumer for consumer in after.relation_consumers}
    inserted_by_id = {
        consumer.id: consumer for consumer in after_insertion.relation_consumers
    }
    assert set(before_by_id) == set(after_by_id) == {first_use.id, second_use.id}
    assert before_by_id[first_use.id].location == model_location(
        "route_intents", 0, "entity_exprs", 0
    )
    assert after_by_id[first_use.id].location == model_location(
        "route_intents", 1, "entity_exprs", 0
    )
    assert inserted_by_id[first_use.id].location == model_location(
        "route_intents", 1, "entity_exprs", 0
    )
    assert before_by_id[first_use.id].value == first_use.value
    assert after_by_id[first_use.id].value == first_use.value
    assert inserted_by_id[first_use.id].value == first_use.value


def test_relation_use_identity_survives_overlay_and_state_sibling_reordering() -> None:
    overlays = tuple(
        PointParameterOverlay(
            table_id=f"parameters-{index}",
            key_uses={
                "id": relation_use(
                    scalar_value_expr(f"row-{index}", expected_type=_STRING)
                )
            },
            column_id="value",
            value_use=relation_use(
                scalar_value_expr(float(index), expected_type=_FLOAT)
            ),
        )
        for index in range(2)
    )
    states = tuple(
        set_state_field(
            scalar_value_expr(f"resource-{index}", expected_type=_STRING),
            capability_id="set_value",
            field_path="value",
            value=scalar_value_expr(float(index), expected_type=_FLOAT),
        )
        for index in range(2)
    )
    program = TypedProgram(
        id="relation-use-nested-reordering",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        parameter_overlays=overlays,
        state=states,
    )

    before = seal_typed_program(program)
    after = seal_typed_program(
        program.model_copy(
            update={
                "parameter_overlays": tuple(reversed(overlays)),
                "state": tuple(reversed(states)),
            }
        )
    )

    before_by_id = {
        consumer.id: (consumer.kind, consumer.value)
        for consumer in before.relation_consumers
    }
    after_by_id = {
        consumer.id: (consumer.kind, consumer.value)
        for consumer in after.relation_consumers
    }
    assert before_by_id == after_by_id

    for verified in (before, after):
        selected = select_typed_program(REFERENCE_RELATION_BACKEND, verified)
        assert all(
            selection.selected_plan.verified_plan is selection.consumer.value.plan
            for selection in selected.relation_selections
        )


def test_relation_use_aliasing_is_rejected_before_backend_selection() -> None:
    shared_use = relation_use(scalar_value_expr("shared", expected_type=_STRING))
    program = TypedProgram(
        id="relation-use-alias",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("first"),
                entity_uses=(shared_use,),
            ),
            ResourceRouteIntent(
                port_id=logical_resource_port_id("second"),
                entity_uses=(shared_use,),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        seal_typed_program(program)

    problem = next(
        problem
        for problem in caught.value.problems
        if problem.code == "compiler_relation_use_duplicate"
    )
    assert problem.location == model_location("route_intents", 1, "entity_exprs", 0)
    assert problem.details["relation_use_id"] == shared_use.id.value


def test_relation_use_aliasing_is_rejected_across_carrier_kinds() -> None:
    point_leaf = point_rows(
        table_value_expr(
            literal_rows([{"x": 1.0}]),
            expected_type=_POINTS,
        )
    )
    route_use = RelationUse(
        scalar_value_expr("shared", expected_type=_STRING),
        id=point_leaf.relation_use_id,
    )
    program = TypedProgram(
        id="relation-use-cross-carrier-alias",
        kind="compiler_test",
        point_domain=PointDomain(root=point_leaf),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("route"),
                entity_uses=(route_use,),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        seal_typed_program(program)

    problem = next(
        problem
        for problem in caught.value.problems
        if problem.code == "compiler_relation_use_duplicate"
    )
    assert problem.location == model_location("route_intents", 0, "entity_exprs", 0)
    assert problem.details["first_kind"] == (
        ProgramRelationConsumerKind.POINT_DOMAIN_ROWS.value
    )


def test_same_plan_can_back_distinct_relation_use_occurrences() -> None:
    expression = scalar_value_expr("shared-plan", expected_type=_STRING)
    first_use = relation_use(expression)
    second_use = relation_use(expression)
    program = TypedProgram(
        id="relation-use-shared-plan",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("first"),
                entity_uses=(first_use,),
            ),
            ResourceRouteIntent(
                port_id=logical_resource_port_id("second"),
                entity_uses=(second_use,),
            ),
        ),
    )

    verified = seal_typed_program(program)

    assert first_use.id != second_use.id
    assert tuple(consumer.id for consumer in verified.relation_consumers) == (
        first_use.id,
        second_use.id,
    )

    selected = select_typed_program(REFERENCE_RELATION_BACKEND, verified)
    assert tuple(
        selection.consumer.id for selection in selected.relation_selections
    ) == (first_use.id, second_use.id)


def test_changing_a_relation_use_plan_requires_fresh_selection() -> None:
    import scopecat._compiler.verification as verification_module

    original_use = relation_use(scalar_value_expr("before", expected_type=_STRING))
    program = TypedProgram(
        id="relation-use-plan-change",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("route"),
                entity_uses=(original_use,),
            ),
        ),
    )
    original = select_typed_program(
        REFERENCE_RELATION_BACKEND,
        seal_typed_program(program),
    )
    changed_use = RelationUse(
        scalar_value_expr("after", expected_type=_STRING),
        id=original_use.id,
    )
    changed_verified = seal_typed_program(
        program.model_copy(
            update={
                "route_intents": (
                    ResourceRouteIntent(
                        port_id=logical_resource_port_id("route"),
                        entity_uses=(changed_use,),
                    ),
                )
            }
        )
    )
    changed = select_typed_program(REFERENCE_RELATION_BACKEND, changed_verified)

    with pytest.raises(ValueError, match="verified program consumer"):
        SelectedTypedProgram(
            changed_verified,
            changed.backend_id,
            original.relation_selections,
            changed.point_domain,
            _token=verification_module._SELECTED_TYPED_PROGRAM_TOKEN,  # pyright: ignore[reportPrivateUsage]
        )

    assert changed.relation_selections[0].consumer.value == changed_use.value


def test_relation_use_wrappers_revalidate_value_shape_at_ir_boundaries() -> None:
    table_use = relation_use(
        table_value_expr(
            literal_rows([{"x": 1.0}]),
            expected_type=_POINTS,
        )
    )
    malformed_use = cast("Any", table_use)
    scalar_use = relation_use(scalar_value_expr("valid", expected_type=_STRING))

    with pytest.raises(ValidationError):
        ResourceRouteIntent(
            port_id=logical_resource_port_id("route"),
            entity_uses=(malformed_use,),
        )
    with pytest.raises(ValidationError):
        PointParameterOverlay(
            table_id="parameters",
            key_uses={"x": malformed_use},
            column_id="value",
            value_use=scalar_use,
        )
    with pytest.raises(ValidationError):
        StateSpec(
            kind="set",
            resource_target=PhysicalStateResourceTarget(use=malformed_use),
            capability_id="set_value",
            field_path="value",
            value_use=scalar_use,
        )

    route = ResourceRouteIntent(
        port_id=logical_resource_port_id("valid"),
        entity_uses=(scalar_use,),
    )
    assert route.entity_uses[0].id == scalar_use.id


def test_selected_program_seals_exact_owners_backend_and_proofs() -> None:
    import scopecat._compiler.verification as verification_module

    verified = seal_typed_program(_inventory_program())
    selected = select_typed_program(REFERENCE_RELATION_BACKEND, verified)
    token = verification_module._SELECTED_TYPED_PROGRAM_TOKEN  # pyright: ignore[reportPrivateUsage]

    reordered = SelectedTypedProgram(
        verified,
        selected.backend_id,
        tuple(reversed(selected.relation_selections)),
        selected.point_domain,
        _token=token,
    )
    assert reordered.relation_selections == selected.relation_selections

    with pytest.raises(ValueError, match="exactly cover"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            selected.relation_selections[:-1],
            selected.point_domain,
            _token=token,
        )

    first, second, *rest = selected.relation_selections
    with pytest.raises(ValueError, match="identities must be unique"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            (first, first, *rest),
            selected.point_domain,
            _token=token,
        )

    extra_consumer = replace(first.consumer, id=RelationUseId.fresh())
    with pytest.raises(ValueError, match="exactly cover"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            (
                *selected.relation_selections,
                SelectedProgramRelation(
                    consumer=extra_consumer,
                    selected_plan=first.selected_plan,
                ),
            ),
            selected.point_domain,
            _token=token,
        )

    wrong_owner = SelectedProgramRelation(
        consumer=replace(first.consumer),
        selected_plan=first.selected_plan,
    )
    with pytest.raises(ValueError, match="verified program consumer"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            (wrong_owner, second, *rest),
            selected.point_domain,
            _token=token,
        )

    point_relation = verified.point_domain.relation_leaves[0]
    alternate_point_plan = select_relation_plan(
        REFERENCE_RELATION_BACKEND,
        point_relation.value.plan,
    )
    assert (
        alternate_point_plan
        is not selected.point_domain.relation_selections[0].selected_plan
    )
    alternate_point_domain = bind_selected_point_domain(
        verified.point_domain,
        backend_id=selected.backend_id,
        selections={point_relation.id: alternate_point_plan},
    )
    with pytest.raises(ValueError, match="reuse whole-program selection"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            selected.relation_selections,
            alternate_point_domain,
            _token=token,
        )

    wrong_proof = replace(first, selected_plan=second.selected_plan)
    with pytest.raises(ValueError, match="does not own"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            (wrong_proof, second, *rest),
            selected.point_domain,
            _token=token,
        )

    other_backend = ReferenceRelationBackend(backend_id="tests.other-program-backend")
    wrong_backend = replace(
        first,
        selected_plan=select_relation_plan(
            other_backend,
            first.consumer.value.plan,
        ),
    )
    with pytest.raises(ValueError, match="one backend"):
        SelectedTypedProgram(
            verified,
            selected.backend_id,
            (wrong_backend, second, *rest),
            selected.point_domain,
            _token=token,
        )


def test_program_proof_and_backend_artifacts_have_sealed_construction() -> None:
    program = _inventory_program()
    verified = seal_typed_program(program)

    with pytest.raises(TypeError, match="seal_typed_program"):
        VerifiedTypedProgram(program, ())
    with pytest.raises(TypeError, match="select_typed_program"):
        SelectedTypedProgram(verified, "tests", ())
    with pytest.raises(TypeError, match="VerifiedTypedProgram"):
        select_typed_program(REFERENCE_RELATION_BACKEND, program)  # type: ignore[arg-type]


def test_program_backend_selection_selects_every_consumer_once() -> None:
    verified = seal_typed_program(_inventory_program())
    backend = _BackendProbe()

    selected = select_typed_program(backend, verified)

    assert backend.assessment_count == len(verified.relation_consumers)
    assert len(selected.relation_selections) == len(verified.relation_consumers)
    assert tuple(
        selection.consumer.id for selection in selected.relation_selections
    ) == tuple(consumer.id for consumer in verified.relation_consumers)
    assert selected.point_domain.backend_id == backend.backend_id
    point_selection = next(
        selection
        for selection in selected.relation_selections
        if selection.consumer.kind is ProgramRelationConsumerKind.POINT_DOMAIN_ROWS
    )
    assert (
        selected.point_domain.selected_plan(point_selection.consumer.id)
        is point_selection.selected_plan
    )


def test_unit_point_domain_needs_no_relation_backend_selection() -> None:
    program = TypedProgram(
        id="unit-domain",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
    )
    backend = _BackendProbe()

    selected = select_typed_program(backend, seal_typed_program(program))
    plan = bind_program(
        program,
        validate_config_environment(load_config()),
        relation_backend=backend,
    )

    assert selected.point_domain.relation_selections == ()
    assert backend.assessment_count == 0
    assert backend.materialization_count == 0
    assert plan.valid, plan.problems
    assert plan.point_count == 1


def test_late_point_domain_leaf_rejection_precedes_all_materialization() -> None:
    left_type = Table(
        columns=(TableColumn("left", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    right_type = Table(
        columns=(TableColumn("right", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    program = TypedProgram(
        id="multi-leaf-preflight",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_product(
                point_rows(
                    table_value_expr(
                        literal_rows([{"left": 1.0}]),
                        expected_type=left_type,
                    )
                ),
                point_rows(
                    table_value_expr(
                        grid(right=lit(1.0) + 2.0),
                        expected_type=right_type,
                    )
                ),
            )
        ),
    )
    backend = _BackendProbe(unsupported=frozenset({RelationOperation.SCALAR_BINARY}))

    plan = bind_program(
        program,
        validate_config_environment(load_config()),
        relation_backend=backend,
    )

    assert backend.assessment_count == 2
    assert backend.materialization_count == 0
    assert plan.points == ()
    assert [problem.location for problem in plan.problems] == [
        model_location(
            "point_domain",
            "factors",
            1,
            "rows",
            "columns",
            "right",
            "scalar",
        )
    ]


def test_unreachable_leaf_after_empty_factor_still_participates_in_preflight() -> None:
    empty_type = Table(
        columns=(TableColumn("empty", _FLOAT),),
        min_rows=0,
        max_rows=0,
    )
    late_type = Table(
        columns=(TableColumn("late", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    program = TypedProgram(
        id="empty-multi-leaf-preflight",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_product(
                point_rows(
                    table_value_expr(
                        literal_rows([]),
                        expected_type=empty_type,
                    )
                ),
                point_rows(
                    table_value_expr(
                        grid(late=lit(1.0) + 2.0),
                        expected_type=late_type,
                    )
                ),
            )
        ),
    )
    backend = _BackendProbe(unsupported=frozenset({RelationOperation.SCALAR_BINARY}))

    plan = bind_program(
        program,
        validate_config_environment(load_config()),
        relation_backend=backend,
    )

    assert backend.assessment_count == 2
    assert backend.materialization_count == 0
    assert plan.points == ()
    assert [problem.location for problem in plan.problems] == [
        model_location(
            "point_domain",
            "factors",
            1,
            "rows",
            "columns",
            "late",
            "scalar",
        )
    ]


def test_binding_reports_all_backend_rejections_before_point_materialization() -> None:
    point_bindings = RelationTypeBindings(point_row=RowType.from_table(_POINTS))
    program = TypedProgram(
        id="backend-preflight",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{"x": 1.0}]),
            expected_type=_POINTS,
        ),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("drive"),
                entity_uses=(
                    relation_use(
                        scalar_value_expr(
                            point_col("x") + 1.0,
                            bindings=point_bindings,
                            expected_type=_FLOAT,
                        )
                    ),
                ),
            ),
        ),
        state=(
            set_state_field(
                scalar_value_expr("source-0", expected_type=_STRING),
                capability_id="set_frequency",
                field_path="offset",
                value=scalar_value_expr(
                    lit(1.0) + 2.0,
                    expected_type=_FLOAT,
                ),
            ),
        ),
    )
    backend = _BackendProbe(unsupported=frozenset({RelationOperation.SCALAR_BINARY}))

    plan = bind_program(
        program,
        validate_config_environment(load_config()),
        relation_backend=backend,
    )

    assert plan.points == ()
    assert backend.materialization_count == 0
    assert tuple(problem.code for problem in plan.problems) == (
        "relation_backend_capability_unsupported",
        "relation_backend_capability_unsupported",
    )
    assert tuple(problem.phase for problem in plan.problems) == (
        ProblemPhase.PLANNING,
        ProblemPhase.PLANNING,
    )
    assert tuple(problem.category for problem in plan.problems) == (
        ProblemCategory.UNAVAILABLE,
        ProblemCategory.UNAVAILABLE,
    )
    assert tuple(problem.location for problem in plan.problems) == (
        model_location("route_intents", 0, "entity_exprs", 0),
        model_location("state", 0, "value"),
    )
    assert tuple(
        (
            problem.details["backend_id"],
            problem.details["consumer_kind"],
            problem.details["capability_dimension"],
            problem.details["capability_code"],
        )
        for problem in plan.problems
    ) == (
        (
            backend.backend_id,
            ProgramRelationConsumerKind.ROUTE_ENTITY.value,
            "operation",
            RelationOperation.SCALAR_BINARY.value,
        ),
        (
            backend.backend_id,
            ProgramRelationConsumerKind.STATE_VALUE.value,
            "operation",
            RelationOperation.SCALAR_BINARY.value,
        ),
    )
