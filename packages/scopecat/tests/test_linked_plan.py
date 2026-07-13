from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from scopecat._compiler.binding import bind_program, materialize_local_plan
from scopecat._compiler.environment import (
    ValidatedConfigEnvironment,
    validate_config_environment,
)
from scopecat._compiler.linked import LinkedPlan, link_program
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    ResourceRouteIntent,
    TypedProgram,
    instrument_product_producer,
    product_output,
    record_product,
    set_state_field,
)
from scopecat._compiler.verification import seal_typed_program
from scopecat._point_domain_algebra import (
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
from scopecat._relation_analysis import RelationOperation
from scopecat._relation_backend import (
    ParameterRelationData,
    PreparedRelationEvaluation,
    ReferenceRelationBackend,
    RelationBackendCapabilityIssue,
    RelationPlanRequirements,
)
from scopecat._relation_verification import (
    ParameterLookupSignature,
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
    grid,
    input_ref,
    literal_rows,
    param,
    parameter_series,
    point_col,
    table,
)
from scopecat._resource_identity import logical_resource_port_id
from scopecat._value_expressions import TableValueExpr
from scopecat.errors import CheckFailed
from scopecat.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.value_types import Float, Scalar, Series, String, Table, TableColumn
from tests.support.authoring import load_config
from tests.support.relation_plans import scalar_value_expr, table_value_expr
from tests.support.workflow_fixtures import load_experiment

_FLOAT = Scalar(Float())


class _BackendProbe:
    def __init__(
        self,
        *,
        unsupported: frozenset[RelationOperation] = frozenset(),
    ) -> None:
        self.backend_id = "tests.linked-plan"
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
        raise AssertionError("linking must not materialize scalar plans")

    def materialize_series(
        self,
        evaluation: PreparedRelationEvaluation[SeriesExpr],
    ) -> list[CellValue]:
        _ = evaluation
        self.materialization_count += 1
        raise AssertionError("linking must not materialize series plans")

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _ = evaluation
        self.materialization_count += 1
        raise AssertionError("linking must not materialize relation plans")


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


def _symbolic_program() -> TypedProgram:
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
    return TypedProgram(
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
    program = TypedProgram(
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


def test_link_snapshots_program_and_environment_on_both_sides() -> None:
    program = _symbolic_program()
    environment = _environment()
    linked = link_program(program, environment)

    program.metadata["owner"] = {"name": "mutated-source"}
    program.product_defs[0].metadata["mutated-source"] = True
    program.instrument_product_producers[0].metadata["mutated-source"] = True
    program.record_uses[0].metadata["mutated-source"] = True
    environment.config.metadata["mutated-source"] = True
    environment.parameters.scalars["mutated-source"] = 1.0
    assert environment.routing is not None
    assert environment.routing.channel_lines_by_id is not None
    environment.routing.channel_lines_by_id["mutated-source"] = "line"

    assert linked.program.metadata == {"owner": {"name": "original"}}
    assert linked.product_defs[0].metadata == {"owner": "selected"}
    assert linked.instrument_product_producers[0].metadata == {
        "owner": "selected-producer"
    }
    assert linked.record_uses[0].metadata == {"owner": "record"}
    assert "mutated-source" not in linked.environment.config.metadata
    assert "mutated-source" not in linked.environment.parameters.scalars
    assert linked.environment.routing is not None
    assert "mutated-source" not in (
        linked.environment.routing.channel_lines_by_id or {}
    )

    exposed_program = linked.program
    exposed_program.metadata["owner"] = {"name": "mutated-copy"}
    exposed_environment = linked.environment
    exposed_environment.config.metadata["mutated-copy"] = True
    exposed_environment.parameters.scalars["mutated-copy"] = 2.0
    exposed_product = linked.product_defs[0]
    exposed_product.metadata["mutated-copy"] = True
    exposed_producer = linked.instrument_product_producers[0]
    exposed_producer.metadata["mutated-copy"] = True
    exposed_record = linked.record_uses[0]
    exposed_record.metadata["mutated-copy"] = True

    assert linked.program.metadata == {"owner": {"name": "original"}}
    assert "mutated-copy" not in linked.environment.config.metadata
    assert "mutated-copy" not in linked.environment.parameters.scalars
    assert linked.product_defs[0].metadata == {"owner": "selected"}
    assert linked.instrument_product_producers[0].metadata == {
        "owner": "selected-producer"
    }
    assert linked.record_uses[0].metadata == {"owner": "record"}


def test_unselected_product_definition_survives_link_without_collection() -> None:
    program = _symbolic_program()

    linked = link_program(program, _environment())
    plan = materialize_local_plan(linked)

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
    expression = grid(x=ScalarExpr(kind="literal", value=1.0) + 2.0)
    program = TypedProgram(
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

    backend = _BackendProbe()
    bound = bind_program(program, environment, relation_backend=backend)

    assert not bound.valid
    assert tuple(problem.code for problem in bound.problems) == (
        "test_environment_blocked",
    )
    assert backend.assessment_count == 0
    assert backend.materialization_count == 0


def test_link_aggregates_environment_and_program_seal_problems() -> None:
    environment_problem = blocking_problem(
        "test_environment_blocked",
        "the test environment is blocked",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config"),
    )
    environment = replace(_environment(), problems=(environment_problem,))
    program = TypedProgram(
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
    program = TypedProgram(
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
    program = TypedProgram(
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
    program = TypedProgram(
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
    program = TypedProgram(
        id="unresolved-input-link",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        state=(
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
    program = TypedProgram(
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


def test_local_materialization_is_the_existing_bound_plan_projection() -> None:
    program = load_experiment()
    environment = _environment()

    expected = bind_program(program, environment)
    actual = materialize_local_plan(link_program(program, environment))

    assert actual == expected
    assert actual.valid, actual.problems
    assert actual.point_count == 3
    assert actual.records
    assert actual.expected_dataset_schema is not None
    assert all(point.routes for point in actual.points)
    assert all(point.desired_state for point in actual.points)
    assert all(point.collect for point in actual.points)


def test_local_materialization_selects_the_complete_backend_before_evaluation() -> None:
    program = _symbolic_program()
    environment = _environment()
    backend = _BackendProbe()
    linked = link_program(program, environment)
    backend.supported_operations = backend.supported_operations - {
        RelationOperation.RELATION_LITERAL_ROWS
    }

    plan = materialize_local_plan(linked, relation_backend=backend)

    assert not plan.valid
    assert plan.points == ()
    assert backend.assessment_count == 4
    assert backend.materialization_count == 0
    assert {problem.details["capability_code"] for problem in plan.problems} == {
        RelationOperation.RELATION_LITERAL_ROWS.value
    }


def test_one_linked_plan_can_be_materialized_by_different_backends() -> None:
    linked = link_program(_symbolic_program(), _environment())
    first_backend = ReferenceRelationBackend(backend_id="tests.first")
    second_backend = ReferenceRelationBackend(backend_id="tests.second")

    first = materialize_local_plan(linked, relation_backend=first_backend)
    second = materialize_local_plan(linked, relation_backend=second_backend)

    assert first.valid, first.problems
    assert second.valid, second.problems
    assert first.relation_backend_id == "tests.first"
    assert second.relation_backend_id == "tests.second"
    assert first.points == second.points
    assert first.records == second.records


def test_backend_selection_failure_does_not_poison_linked_plan() -> None:
    linked = link_program(_symbolic_program(), _environment())
    rejected_backend = _BackendProbe(
        unsupported=frozenset({RelationOperation.RELATION_LITERAL_ROWS})
    )

    rejected = materialize_local_plan(linked, relation_backend=rejected_backend)
    accepted = materialize_local_plan(
        linked,
        relation_backend=ReferenceRelationBackend(backend_id="tests.accepted"),
    )

    assert not rejected.valid
    assert rejected.points == ()
    assert rejected_backend.materialization_count == 0
    assert accepted.valid, accepted.problems
    assert accepted.relation_backend_id == "tests.accepted"
    assert accepted.point_count == 4


def test_linked_plan_construction_is_sealed() -> None:
    program = _symbolic_program()
    environment = _environment()
    verified = seal_typed_program(program)

    with pytest.raises(TypeError, match="link_program"):
        LinkedPlan(verified, environment)
