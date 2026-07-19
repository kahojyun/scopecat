from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.frontend.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.compiler.linking.materialization import materialize_local_semantics
from scopecat.compiler.relations.evaluation import (
    ParameterRelationData,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    grid,
    input_ref,
    lit,
    literal_rows,
    param,
    parameter_series,
    point_col,
    table,
)
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointDependentProduct,
    PointProduct,
    PointRelationRows,
    PointUnit,
    PointZip,
    point_dependent_product,
    point_product,
    point_rows,
    point_zip,
)
from scopecat.compiler.relations.verification import (
    ParameterLookupSignature,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.value_expressions import TableValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    ResourceRouteIntent,
    product_output,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.records.entity import EntityRef
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import scalar_value_expr, table_value_expr
from tests.testkit.typed_program import instrument_product_producer, link_program
from tests.testkit.workflow_fixtures import load_experiment

_FLOAT = Scalar(Float())


def _table(column: str, rows: int) -> Table:
    return Table(
        columns=(TableColumn(column, _FLOAT),),
        min_rows=rows,
        max_rows=rows,
    )


def _rows(
    column: str,
    values: Sequence[float],
) -> PointRelationRows[TableValueExpr]:
    value_type = _table(column, len(values))
    return point_rows(
        table_value_expr(
            literal_rows([{column: value} for value in values]),
            expected_type=value_type,
        )
    )


def _dependent_row(
    column: str,
    *,
    source: str,
    offset: float,
) -> PointRelationRows[TableValueExpr]:
    return point_rows(
        table_value_expr(
            grid(**{column: point_col(source) + offset}),
            bindings=RelationTypeBindings(
                point_row=RowType.from_table(_table(source, 2))
            ),
            expected_type=_table(column, 1),
        )
    )


def _symbolic_program() -> CoreProgram:
    root = point_product(
        _rows("a", (1.0, 2.0)),
        point_dependent_product(
            _rows("b", (10.0, 20.0)),
            point_zip(
                _dependent_row("c", source="b", offset=100.0),
                _dependent_row("d", source="b", offset=1000.0),
            ),
        ),
    )
    selected_product = product_output(
        "signal",
        metadata={"owner": "selected"},
    )
    available_product = product_output(
        "available",
        metadata={"owner": "unselected"},
    )
    selected_use, selected_record = record_product(
        selected_product,
        metadata={"owner": "record"},
    )
    selected_producer = instrument_product_producer(
        selected_product,
        metadata={"owner": "selected-producer"},
    )
    available_producer = instrument_product_producer(
        available_product,
        metadata={"owner": "available-producer"},
    )
    return CoreProgram(
        id="symbolic-linked-plan",
        kind="compiler_test",
        point_domain=PointDomain(root=root),
        product_defs=(selected_product, available_product),
        instrument_product_producers=(selected_producer, available_producer),
        product_uses=(selected_use,),
        record_uses=(selected_record,),
        metadata={"owner": {"name": "original"}},
    )


def _environment() -> ValidatedConfigEnvironment:
    return validate_config_environment(load_config())


def test_link_retains_symbolic_backend_neutral_domain() -> None:
    program = _symbolic_program()

    linked = link_program(program, _environment())

    assert linked.program == program
    assert linked.point_domain is linked.verified_program.point_domain
    assert linked.point_domain.root == program.point_domain.root
    assert isinstance(linked.point_domain.root, PointProduct)
    second = linked.point_domain.root.factors[1]
    assert isinstance(second, PointDependentProduct)
    assert isinstance(second.right, PointZip)
    assert linked.cardinality.minimum == 4
    assert linked.cardinality.maximum == 4
    assert linked.coordinate_ids == ("a", "b", "c", "d")
    assert linked.product_defs == program.product_defs
    assert linked.instrument_product_producers == (program.instrument_product_producers)
    assert linked.product_uses == program.product_uses
    assert linked.record_uses == program.record_uses
    assert tuple(relation.path for relation in linked.point_domain.relation_leaves) == (
        ("factors", 0),
        ("factors", 1, "left"),
        ("factors", 1, "right", "sources", 0),
        ("factors", 1, "right", "sources", 1),
    )


def test_link_retains_unit_domain() -> None:
    program = CoreProgram(
        id="unit-linked-plan",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
    )

    linked = link_program(program, _environment())

    assert isinstance(linked.point_domain.root, PointUnit)
    assert linked.cardinality.minimum == 1
    assert linked.cardinality.maximum == 1
    assert linked.point_domain.relation_leaves == ()
    assert linked.coordinate_ids == ()


def test_raw_link_retains_immutable_metadata_and_accepted_environment() -> None:
    program = _symbolic_program()
    environment = _environment()
    linked = link_program(program, environment)

    assert linked.environment is environment

    for metadata in (
        program.metadata,
        program.product_defs[0].metadata,
        program.instrument_product_producers[0].metadata,
        program.record_uses[0].metadata,
    ):
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, object]", metadata)["mutated-source"] = True

    assert linked.program.metadata == {"owner": {"name": "original"}}
    assert linked.product_defs[0].metadata == {"owner": "selected"}
    assert linked.instrument_product_producers[0].metadata == {
        "owner": "selected-producer"
    }
    assert linked.record_uses[0].metadata == {"owner": "record"}


def test_verified_link_reuses_proof_and_accepted_environment() -> None:
    verified = seal_typed_program(_symbolic_program())
    environment = _environment()

    linked = link_verified_program(verified, environment)

    assert linked.verified_program is verified
    assert linked.program is verified.program
    assert linked.environment is environment


def test_unselected_product_definition_survives_link_without_collection() -> None:
    program = _symbolic_program()

    linked = link_program(program, _environment())
    plan = materialize_local_semantics(linked)

    selected_id, unselected_id = (product.id for product in linked.product_defs)
    assert linked.product_defs == program.product_defs
    assert tuple(use.product_id for use in linked.product_uses) == (selected_id,)
    assert tuple(record.product_use_id for record in linked.record_uses) == (
        linked.product_uses[0].id,
    )
    assert plan.valid, plan.problems
    assert {
        request.product_id
        for point in plan.points
        for collect in point.collect
        for request in collect.requests
    } == {selected_id}
    assert unselected_id not in {
        request.product_id
        for point in plan.points
        for collect in point.collect
        for request in collect.requests
    }


def test_link_reports_environment_problems_without_target_selection() -> None:
    environment_problem = blocking_problem(
        "test_environment_blocked",
        "the test environment is blocked",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config"),
    )
    environment = replace(
        _environment(),
        routing=None,
        problems=(environment_problem,),
    )
    expression = grid(x=lit(1.0) + 2.0)
    program = CoreProgram(
        id="rejected-linked-plan",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(table_value_expr(expression, expected_type=_table("x", 1)))
        ),
    )
    with pytest.raises(CheckFailed) as caught:
        link_program(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "test_environment_blocked",
    )


def test_link_aggregates_environment_and_program_seal_problems() -> None:
    environment_problem = blocking_problem(
        "test_environment_blocked",
        "the test environment is blocked",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config"),
    )
    environment = replace(_environment(), problems=(environment_problem,))
    program = CoreProgram(
        id="invalid-program-link",
        kind="compiler_test",
        point_domain=PointDomain(root=point_product()),
        route_intents=(
            ResourceRouteIntent(port_id=logical_resource_port_id("duplicate")),
            ResourceRouteIntent(port_id=logical_resource_port_id("duplicate")),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "test_environment_blocked",
        "resource_route_duplicate",
    )
    assert caught.value.problems[1].phase is ProblemPhase.PLANNING


def test_link_rejects_a_missing_routing_view_as_a_check_problem() -> None:
    environment = replace(_environment(), routing=None)

    with pytest.raises(CheckFailed) as caught:
        link_program(_symbolic_program(), environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "config_routing_unavailable",
    )


@pytest.mark.parametrize(
    ("expression", "bindings", "value_type"),
    (
        (
            grid(value=param("definitely_missing")),
            RelationTypeBindings(parameters={"definitely_missing": _FLOAT}),
            _table("value", 1),
        ),
        (
            grid(value=parameter_series("definitely_missing")),
            RelationTypeBindings(
                parameters={
                    "definitely_missing": Series(
                        _FLOAT,
                        min_length=1,
                        max_length=1,
                    )
                }
            ),
            _table("value", 1),
        ),
        (
            table("definitely_missing"),
            RelationTypeBindings(parameters={"definitely_missing": _table("value", 1)}),
            _table("value", 1),
        ),
        (
            grid(
                value=param(
                    "definitely_missing",
                    key={"key": "selected"},
                    column="value",
                )
            ),
            RelationTypeBindings(
                parameter_lookups=(
                    ParameterLookupSignature(
                        table_id="definitely_missing",
                        key_input_types=(("key", Scalar(String())),),
                        column_id="value",
                        result_type=_FLOAT,
                    ),
                )
            ),
            _table("value", 1),
        ),
    ),
    ids=("scalar", "series", "table", "lookup"),
)
def test_link_closes_every_used_parameter_import(
    expression: RelationExpr,
    bindings: RelationTypeBindings,
    value_type: Table,
) -> None:
    program = CoreProgram(
        id="missing-parameter-link",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    expression,
                    bindings=bindings,
                    expected_type=value_type,
                )
            )
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_missing",
    )
    assert caught.value.problems[0].phase is ProblemPhase.PLANNING
    assert caught.value.problems[0].category is ProblemCategory.NOT_FOUND
    assert caught.value.problems[0].details["parameter_id"] == "definitely_missing"


def test_link_checks_parameter_values_against_each_used_proof_contract() -> None:
    parameter_id = "linked-contract-value"
    program = CoreProgram(
        id="parameter-contract-link",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    grid(value=param(parameter_id)),
                    bindings=RelationTypeBindings(parameters={parameter_id: _FLOAT}),
                    expected_type=_table("value", 1),
                )
            )
        ),
    )
    environment = replace(
        _environment(),
        parameters=ParameterRelationData(scalars={parameter_id: "not-a-float"}),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_contract_mismatch",
    )
    assert "expected float" in caught.value.problems[0].message


def test_link_classifies_a_lookup_bound_to_the_wrong_parameter_shape() -> None:
    parameter_id = "lookup-bound-as-scalar"
    program = CoreProgram(
        id="lookup-parameter-shape-link",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    grid(
                        value=param(
                            parameter_id,
                            key={"key": "selected"},
                            column="value",
                        )
                    ),
                    bindings=RelationTypeBindings(
                        parameter_lookups=(
                            ParameterLookupSignature(
                                table_id=parameter_id,
                                key_input_types=(("key", Scalar(String())),),
                                column_id="value",
                                result_type=_FLOAT,
                            ),
                        )
                    ),
                    expected_type=_table("value", 1),
                )
            )
        ),
    )
    environment = replace(
        _environment(),
        parameters=ParameterRelationData(scalars={parameter_id: 1.0}),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_contract_mismatch",
    )
    assert "expected table parameter, got scalar" in caught.value.problems[0].message


def test_link_rejects_remaining_relation_input_imports() -> None:
    input_id = "unresolved"
    program = CoreProgram(
        id="unresolved-input-link",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        effects=(
            set_state_field(
                scalar_value_expr(
                    "source-0",
                    expected_type=Scalar(String()),
                ),
                capability_id="set_frequency",
                field_path="value",
                value=scalar_value_expr(
                    input_ref(input_id),
                    bindings=RelationTypeBindings(inputs={input_id: _FLOAT}),
                    expected_type=_FLOAT,
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_input_unresolved",
    )
    assert caught.value.problems[0].details == {
        "consumer_kind": "state_value",
        "input_id": input_id,
    }


def test_link_reports_every_missing_import_in_one_relation_consumer() -> None:
    missing_ids = ("missing-left", "missing-right")
    value_type = Table(
        columns=(
            TableColumn("left", _FLOAT),
            TableColumn("right", _FLOAT),
        ),
        min_rows=1,
        max_rows=1,
    )
    program = CoreProgram(
        id="multiple-missing-parameter-link",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    grid(
                        left=param(missing_ids[0]),
                        right=param(missing_ids[1]),
                    ),
                    bindings=RelationTypeBindings(
                        parameters=dict.fromkeys(missing_ids, _FLOAT)
                    ),
                    expected_type=value_type,
                )
            )
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_missing",
        "linked_parameter_missing",
    )
    assert {
        problem.details["parameter_id"] for problem in caught.value.problems
    } == set(missing_ids)


def test_local_materialization_builds_the_executable_bound_plan() -> None:
    program = load_experiment()
    environment = _environment()

    expected = materialize_local_semantics(link_program(program, environment))
    actual = materialize_local_semantics(link_program(program, environment))

    assert actual == expected
    assert actual.valid, actual.problems
    assert actual.point_count == 3
    assert all(point.routes for point in actual.points)
    assert all(point.desired_state for point in actual.points)
    assert all(point.collect for point in actual.points)


def test_linked_points_retain_exact_proofs_and_only_materialize_the_domain() -> None:
    linked = link_program(_symbolic_program(), _environment())
    materialized = materialize_linked_points(linked)

    assert materialized.linked_plan is linked
    assert materialized.verified_program is linked.verified_program
    assert materialized.point_domain.id == linked.point_domain.id
    assert [point.logical_ordinal for point in materialized.point_domain.points] == [
        0,
        1,
        2,
        3,
    ]


def test_linked_point_batch_retains_parent_identity_and_original_ordinals() -> None:
    linked = link_program(_symbolic_program(), _environment())
    materialized = materialize_linked_points(linked)

    batch = MaterializedLinkedPointBatch(materialized, (1, 2))

    assert batch.parent is materialized
    assert batch.linked_plan is materialized.linked_plan
    assert batch.verified_program is materialized.verified_program
    assert batch.point_indices == (1, 2)
    assert batch.point_domain.id == materialized.point_domain.id
    assert batch.point_domain.source is materialized.point_domain
    assert batch.point_domain.points == materialized.point_domain.points[1:3]
    assert all(
        selected is original
        for selected, original in zip(
            batch.point_domain.points,
            materialized.point_domain.points[1:3],
            strict=True,
        )
    )
    assert [point.logical_ordinal for point in batch.point_domain.points] == [1, 2]
    assert [point.logical_id for point in batch.point_domain.points] == [
        point.logical_id for point in materialized.point_domain.points[1:3]
    ]
    assert batch.point_domain.cardinality.minimum == 2
    assert batch.point_domain.cardinality.maximum == 2


@pytest.mark.parametrize(
    ("indices", "error_type"),
    [
        ((), ValueError),
        ((0, 2), ValueError),
        ((2, 1), ValueError),
        ((-1,), ValueError),
        ((4,), ValueError),
        ((True,), TypeError),
    ],
)
def test_linked_point_batch_rejects_noncanonical_selections(
    indices: tuple[object, ...],
    error_type: type[Exception],
) -> None:
    materialized = materialize_linked_points(
        link_program(_symbolic_program(), _environment())
    )

    with pytest.raises(error_type):
        MaterializedLinkedPointBatch(
            materialized,
            cast("Sequence[int]", indices),
        )


def test_linked_points_normalize_entities_before_point_identity_is_sealed() -> None:
    point_type = Table(
        columns=(TableColumn("subject", Scalar(Entity())),),
        min_rows=1,
        max_rows=1,
    )
    program = CoreProgram(
        id="linked-entity-points",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows([{"subject": "q0"}]),
                    expected_type=point_type,
                )
            ),
            entity_columns=("subject",),
        ),
    )

    materialized = materialize_linked_points(link_program(program, _environment()))

    assert materialized.point_domain.points[0].row["subject"] == EntityRef(
        id="q0",
        kind="logical_device",
    )


def test_linked_points_reject_unknown_entities_at_the_planning_boundary() -> None:
    point_type = Table(
        columns=(TableColumn("subject", Scalar(Entity())),),
        min_rows=1,
        max_rows=1,
    )
    program = CoreProgram(
        id="unknown-linked-entity-point",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows([{"subject": "missing"}]),
                    expected_type=point_type,
                )
            ),
            entity_columns=("subject",),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "unknown_authoring_entity"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.category is ProblemCategory.NOT_FOUND
    assert problem.location == model_location("entity", "missing")
    assert dict(problem.details) == {}


def test_linked_points_preserve_entity_kind_mismatch_problem() -> None:
    point_type = Table(
        columns=(TableColumn("subject", Scalar(Entity())),),
        min_rows=1,
        max_rows=1,
    )
    program = CoreProgram(
        id="wrong-kind-linked-entity-point",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows(
                        [
                            {
                                "subject": EntityRef(
                                    id="q0",
                                    kind="logical_coupler",
                                )
                            }
                        ]
                    ),
                    expected_type=point_type,
                )
            ),
            entity_columns=("subject",),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "authoring_entity_kind_mismatch"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.category is ProblemCategory.INVALID_INPUT
    assert problem.location == model_location("entity", "q0")
    assert dict(problem.details) == {}
    assert problem.message == ("entity q0 has kind logical_device, not logical_coupler")


def test_linked_points_aggregate_entity_and_normalized_value_problems() -> None:
    point_type = Table(
        columns=(TableColumn("subject", Scalar(Entity())),),
        min_rows=3,
        max_rows=3,
        primary_key=("subject",),
    )
    program = CoreProgram(
        id="invalid-normalized-linked-entity-points",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows(
                        [
                            {"subject": "q0"},
                            {
                                "subject": EntityRef(
                                    id="q0",
                                    kind="logical_device",
                                )
                            },
                            {"subject": "missing"},
                        ]
                    ),
                    expected_type=point_type,
                )
            ),
            entity_columns=("subject",),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert [problem.code for problem in caught.value.problems] == [
        "unknown_authoring_entity",
        "module_point_value_type_mismatch",
    ]
