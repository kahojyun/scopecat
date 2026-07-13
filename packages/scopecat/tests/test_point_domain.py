from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scopecat._compiler.point_domain import (
    LogicalPointId,
    MaterializedPoint,
    MaterializedPointDomain,
    PointCardinality,
    PointDomain,
    PointDomainEvaluationError,
    PointDomainId,
    PointDomainValueError,
    PointDomainVerificationError,
    SelectedPointDomain,
    VerifiedPointDomain,
    bind_selected_point_domain,
    materialize_point_domain,
    select_point_domain,
    verify_point_domain,
)
from scopecat._point_domain_algebra import (
    POINT_UNIT,
    PointDomainAnalysis,
    PointRelationRows,
    point_dependent_product,
    point_product,
    point_rows,
    point_zip,
)
from scopecat._relation_analysis import RelationOperation
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    ParameterRelationData,
    PreparedRelationEvaluation,
    ReferenceRelationBackend,
)
from scopecat._relation_use import RelationUseId
from scopecat._relation_verification import RelationTypeBindings, RowType
from scopecat._relations import (
    RelationExpr,
    Row,
    grid,
    input_table,
    literal_rows,
    point_col,
)
from scopecat._value_expressions import TableValueExpr, verify_table_value_expr
from scopecat.models.entity import EntityRef
from scopecat.models.value import PayloadValue
from scopecat.value_types import Entity, Int, Payload, Scalar, Table, TableColumn

_INT = Scalar(Int())
_INT_TABLE = Table((TableColumn("x", _INT),))


def _domain(
    values: list[int],
    *,
    domain_id: str = "root",
    table_type: Table = _INT_TABLE,
) -> PointDomain:
    return PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows([{"x": value} for value in values]),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            )
        ),
        id=domain_id,
    )


def _materialize(domain: PointDomain, *, program_id: str = "experiment"):
    verified = verify_point_domain(domain, program_id=program_id)
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)
    return materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        selected,
        ParameterRelationData(),
    )


@settings(max_examples=50)
@given(
    values=st.lists(st.integers(min_value=-5, max_value=5), max_size=16),
    start=st.integers(min_value=0, max_value=20),
    width=st.integers(min_value=0, max_value=20),
)
def test_generated_point_identity_is_ordinal_and_batch_stable(
    values: list[int],
    start: int,
    width: int,
) -> None:
    first = _materialize(_domain(values))
    repeated = _materialize(_domain(values))

    assert [point.logical_ordinal for point in first.points] == list(range(len(values)))
    assert [point.row["x"] for point in first.points] == values
    assert [point.logical_id for point in first.points] == [
        point.logical_id for point in repeated.points
    ]
    assert [point.logical_id for point in first.points[start : start + width]] == [
        LogicalPointId(first.id, ordinal)
        for ordinal in range(len(values))[start : start + width]
    ]


def test_duplicate_rows_have_distinct_identity_but_same_best_effort_key() -> None:
    materialized = _materialize(_domain([7, 7]))

    left, right = materialized.points
    assert left.logical_id != right.logical_id
    assert left.row_key == right.row_key


def test_domain_namespace_participates_in_logical_identity() -> None:
    first = _materialize(_domain([1], domain_id="first"), program_id="program")
    second = _materialize(_domain([1], domain_id="second"), program_id="program")
    other_program = _materialize(
        _domain([1], domain_id="first"),
        program_id="other",
    )

    assert first.points[0].logical_id != second.points[0].logical_id
    assert first.points[0].logical_id != other_program.points[0].logical_id
    assert (
        first.points[0].logical_id.value
        == LogicalPointId(
            PointDomainId("program", "first"),
            0,
        ).value
    )


def test_zero_cardinality_is_preserved_without_synthetic_points() -> None:
    table_type = Table(
        (TableColumn("x", _INT),),
        min_rows=0,
        max_rows=0,
    )
    domain = _domain([], table_type=table_type)
    verified = verify_point_domain(domain, program_id="program")
    materialized = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        select_point_domain(REFERENCE_RELATION_BACKEND, verified),
        ParameterRelationData(),
    )

    assert verified.cardinality == PointCardinality.exact(0)
    assert materialized.points == ()
    assert materialized.cardinality == PointCardinality.exact(0)
    assert materialized.declared_cardinality == verified.cardinality


def test_symbolic_and_actual_cardinality_are_retained_separately() -> None:
    verified = verify_point_domain(_domain([1, 2]), program_id="program")
    materialized = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        select_point_domain(REFERENCE_RELATION_BACKEND, verified),
        ParameterRelationData(),
    )

    assert verified.cardinality == PointCardinality(0, None)
    assert materialized.declared_cardinality == verified.cardinality
    assert materialized.cardinality == PointCardinality.exact(2)


def _integer_rows(column_id: str, values: list[int]) -> TableValueExpr:
    value_type = Table(
        (TableColumn(column_id, _INT),),
        min_rows=len(values),
        max_rows=len(values),
    )
    return verify_table_value_expr(
        literal_rows([{column_id: value} for value in values]),
        bindings=RelationTypeBindings(),
        expected_type=value_type,
    )


def test_unit_has_no_relation_selection_or_backend_materialization() -> None:
    backend = _SelectionOnlyBackend()
    verified = verify_point_domain(
        PointDomain(root=POINT_UNIT),
        program_id="program",
    )

    selected = select_point_domain(backend, verified)
    materialized = materialize_point_domain(
        backend,
        selected,
        ParameterRelationData(),
    )

    assert verified.relation_leaves == ()
    assert selected.relation_selections == ()
    assert materialized.cardinality == PointCardinality.exact(1)
    assert materialized.points[0].row == {}


def test_product_materialization_is_left_major_and_selects_each_leaf_once() -> None:
    domain = PointDomain(
        root=point_product(
            point_rows(_integer_rows("left", [1, 2])),
            point_rows(_integer_rows("right", [3, 4])),
        )
    )
    verified = verify_point_domain(domain, program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)

    materialized = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        selected,
        ParameterRelationData(),
    )

    assert [relation.path for relation in verified.relation_leaves] == [
        ("factors", 0),
        ("factors", 1),
    ]
    assert len(selected.relation_selections) == 2
    assert all(
        RelationOperation.RELATION_POINT_CROSS
        not in selection.selected_plan.required_operations
        and RelationOperation.RELATION_ZIP
        not in selection.selected_plan.required_operations
        for selection in selected.relation_selections
    )
    assert [point.row for point in materialized.points] == [
        {"left": 1, "right": 3},
        {"left": 1, "right": 4},
        {"left": 2, "right": 3},
        {"left": 2, "right": 4},
    ]


def test_relation_use_identity_is_independent_of_structural_path() -> None:
    leaf = point_rows(_integer_rows("value", [1]))
    standalone = verify_point_domain(PointDomain(root=leaf), program_id="program")
    nested = verify_point_domain(
        PointDomain(
            root=point_product(
                point_rows(_integer_rows("prefix", [0])),
                leaf,
            )
        ),
        program_id="program",
    )

    assert standalone.relation_leaves[0].id == leaf.relation_use_id
    assert standalone.relation_leaves[0].path == ()
    assert nested.relation_leaves[1].id == leaf.relation_use_id
    assert nested.relation_leaves[1].path == ("factors", 1)


def test_dependent_product_right_reads_the_accumulated_left_row() -> None:
    left = _integer_rows("left", [1, 2])
    right_type = Table(
        (TableColumn("right", _INT),),
        min_rows=1,
        max_rows=1,
    )
    right = verify_table_value_expr(
        grid(right=point_col("left") + 10),
        bindings=RelationTypeBindings(point_row=RowType((TableColumn("left", _INT),))),
        expected_type=right_type,
    )
    domain = PointDomain(
        root=point_dependent_product(point_rows(left), point_rows(right))
    )

    materialized = _materialize(domain, program_id="program")

    assert [point.row for point in materialized.points] == [
        {"left": 1, "right": 11},
        {"left": 2, "right": 12},
    ]


def test_nested_dependent_product_right_reads_all_accumulated_columns() -> None:
    first = _integer_rows("first", [1, 2])
    second_type = Table(
        (TableColumn("second", _INT),),
        min_rows=1,
        max_rows=1,
    )
    second = verify_table_value_expr(
        grid(second=point_col("first") + 10),
        bindings=RelationTypeBindings(point_row=RowType((TableColumn("first", _INT),))),
        expected_type=second_type,
    )
    third_type = Table(
        (TableColumn("third", _INT),),
        min_rows=1,
        max_rows=1,
    )
    third = verify_table_value_expr(
        grid(third=point_col("first") + point_col("second")),
        bindings=RelationTypeBindings(
            point_row=RowType((TableColumn("first", _INT), TableColumn("second", _INT)))
        ),
        expected_type=third_type,
    )
    domain = PointDomain(
        root=point_dependent_product(
            point_dependent_product(point_rows(first), point_rows(second)),
            point_rows(third),
        )
    )

    materialized = _materialize(domain, program_id="program")

    assert [point.row for point in materialized.points] == [
        {"first": 1, "second": 11, "third": 12},
        {"first": 2, "second": 12, "third": 14},
    ]


def test_dependent_zip_branches_share_the_outer_ambient_row() -> None:
    left = _integer_rows("left", [1, 2])

    def branch(column_id: str, offset: int) -> TableValueExpr:
        value_type = Table(
            (TableColumn(column_id, _INT),),
            min_rows=1,
            max_rows=1,
        )
        return verify_table_value_expr(
            grid(**{column_id: point_col("left") + offset}),
            bindings=RelationTypeBindings(
                point_row=RowType((TableColumn("left", _INT),))
            ),
            expected_type=value_type,
        )

    domain = PointDomain(
        root=point_dependent_product(
            point_rows(left),
            point_zip(
                point_rows(branch("first", 10)),
                point_rows(branch("second", 20)),
            ),
        )
    )

    materialized = _materialize(domain, program_id="program")

    assert [point.row for point in materialized.points] == [
        {"left": 1, "first": 11, "second": 21},
        {"left": 2, "first": 12, "second": 22},
    ]


@pytest.mark.parametrize("compose", [point_product, point_zip])
def test_independent_composition_rejects_sibling_point_capture(compose) -> None:
    left = _integer_rows("left", [1])
    right_type = Table(
        (TableColumn("right", _INT),),
        min_rows=1,
        max_rows=1,
    )
    right = verify_table_value_expr(
        grid(right=point_col("left")),
        bindings=RelationTypeBindings(point_row=RowType((TableColumn("left", _INT),))),
        expected_type=right_type,
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        verify_point_domain(
            PointDomain(root=compose(point_rows(left), point_rows(right))),
            program_id="program",
        )

    assert [issue.code for issue in caught.value.issues] == [
        "point_domain_open_row_interface"
    ]
    expected_path = (
        ("factors", 1, "rows") if compose is point_product else ("sources", 1, "rows")
    )
    assert caught.value.issues[0].path == expected_path


def test_zip_materialization_merges_rows_by_position() -> None:
    domain = PointDomain(
        root=point_zip(
            point_rows(_integer_rows("left", [1, 2])),
            point_rows(_integer_rows("right", [3, 4])),
        )
    )

    materialized = _materialize(domain, program_id="program")

    assert [point.row for point in materialized.points] == [
        {"left": 1, "right": 3},
        {"left": 2, "right": 4},
    ]


def test_zip_checks_runtime_lengths_when_static_bounds_overlap() -> None:
    left_type = Table(
        (TableColumn("left", _INT),),
        min_rows=0,
        max_rows=3,
    )
    right_type = Table(
        (TableColumn("right", _INT),),
        min_rows=0,
        max_rows=3,
    )
    domain = PointDomain(
        root=point_zip(
            point_rows(
                verify_table_value_expr(
                    literal_rows([{"left": 1}]),
                    bindings=RelationTypeBindings(),
                    expected_type=left_type,
                )
            ),
            point_rows(
                verify_table_value_expr(
                    literal_rows([{"right": 2}, {"right": 3}]),
                    bindings=RelationTypeBindings(),
                    expected_type=right_type,
                )
            ),
        )
    )

    with pytest.raises(PointDomainEvaluationError, match="unequal lengths") as caught:
        _materialize(domain, program_id="program")

    assert caught.value.path == ()


def test_runtime_extra_column_collision_is_reported_at_composition() -> None:
    left_type = Table(
        (TableColumn("left", _INT),),
        min_rows=1,
        max_rows=1,
        allow_extra_columns=True,
    )
    right_type = Table(
        (TableColumn("right", _INT),),
        min_rows=1,
        max_rows=1,
        allow_extra_columns=True,
    )
    domain = PointDomain(
        root=point_product(
            point_rows(
                verify_table_value_expr(
                    literal_rows([{"left": 1, "extra": 10}]),
                    bindings=RelationTypeBindings(),
                    expected_type=left_type,
                )
            ),
            point_rows(
                verify_table_value_expr(
                    literal_rows([{"right": 2, "extra": 20}]),
                    bindings=RelationTypeBindings(),
                    expected_type=right_type,
                )
            ),
        )
    )

    with pytest.raises(PointDomainEvaluationError, match="duplicate columns") as caught:
        _materialize(domain, program_id="program")

    assert caught.value.path == ()


@dataclass(frozen=True, slots=True)
class _SelectionOnlyBackend(ReferenceRelationBackend):
    backend_id: str = "test.selection-only"

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _ = evaluation
        raise AssertionError("selection must not materialize the relation")


def test_selection_does_not_materialize_rows() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")

    selected = select_point_domain(_SelectionOnlyBackend(), verified)

    assert selected.id == PointDomainId("program", "root")
    assert selected.backend_id == "test.selection-only"


def test_existing_relation_selection_can_be_bound_without_reselection() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")
    relation_selection = (
        select_point_domain(
            REFERENCE_RELATION_BACKEND,
            verified,
        )
        .relation_selections[0]
        .selected_plan
    )

    selected = bind_selected_point_domain(
        verified,
        backend_id=REFERENCE_RELATION_BACKEND.backend_id,
        selections={verified.relation_leaves[0].id: relation_selection},
    )

    assert selected.relation_selections[0].selected_plan is relation_selection


def test_selected_domain_requires_exact_single_backend_leaf_coverage() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)
    relation_id = verified.relation_leaves[0].id
    selected_plan = selected.relation_selections[0].selected_plan

    with pytest.raises(ValueError, match="exactly cover"):
        bind_selected_point_domain(
            verified,
            backend_id=REFERENCE_RELATION_BACKEND.backend_id,
            selections={},
        )
    with pytest.raises(ValueError, match="exactly cover"):
        bind_selected_point_domain(
            verified,
            backend_id=REFERENCE_RELATION_BACKEND.backend_id,
            selections={
                relation_id: selected_plan,
                RelationUseId.fresh(): selected_plan,
            },
        )

    other_backend = ReferenceRelationBackend(backend_id="other-backend")
    other_plan = (
        select_point_domain(other_backend, verified)
        .relation_selections[0]
        .selected_plan
    )
    with pytest.raises(ValueError, match="one backend"):
        bind_selected_point_domain(
            verified,
            backend_id=REFERENCE_RELATION_BACKEND.backend_id,
            selections={relation_id: other_plan},
        )


def test_point_domain_stages_reject_wrong_artifacts_and_backend() -> None:
    domain = _domain([1])
    verified = verify_point_domain(domain, program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)
    other_verified = verify_point_domain(_domain([2]), program_id="program")

    with pytest.raises(TypeError, match="VerifiedPointDomain"):
        select_point_domain(
            REFERENCE_RELATION_BACKEND,
            cast("VerifiedPointDomain", domain),
        )
    with pytest.raises(TypeError, match="SelectedPointDomain"):
        materialize_point_domain(
            REFERENCE_RELATION_BACKEND,
            cast("SelectedPointDomain", verified),
            ParameterRelationData(),
        )
    with pytest.raises(ValueError, match="does not own"):
        bind_selected_point_domain(
            other_verified,
            backend_id=REFERENCE_RELATION_BACKEND.backend_id,
            selections={
                other_verified.relation_leaves[0].id: (
                    selected.relation_selections[0].selected_plan
                )
            },
        )
    with pytest.raises(ValueError, match="cannot be materialized"):
        materialize_point_domain(
            ReferenceRelationBackend(backend_id="other-backend"),
            selected,
            ParameterRelationData(),
        )


def test_duplicate_relation_use_identity_fails_before_leaf_verification() -> None:
    relation_use_id = RelationUseId.fresh()
    domain = PointDomain(
        root=point_product(
            PointRelationRows(
                _integer_rows("left", [1]),
                relation_use_id=relation_use_id,
            ),
            PointRelationRows(
                _integer_rows("right", [2]),
                relation_use_id=relation_use_id,
            ),
        )
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        verify_point_domain(domain, program_id="program")

    assert [issue.code for issue in caught.value.issues] == [
        "point_domain_relation_use_duplicate"
    ]
    assert caught.value.issues[0].path == ("factors", 1, "rows")


def test_materialization_coerces_normalized_rows_before_assigning_ids() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)

    materialized = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        selected,
        ParameterRelationData(),
        row_normalizer=lambda _row: {"x": 2},
    )

    assert materialized.points[0].row == {"x": 2}
    assert materialized.points[0].logical_ordinal == 0


def test_invalid_normalized_row_has_a_domain_value_error() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)

    with pytest.raises(PointDomainValueError):
        materialize_point_domain(
            REFERENCE_RELATION_BACKEND,
            selected,
            ParameterRelationData(),
            row_normalizer=lambda _row: {"x": "not-an-integer"},
        )


@dataclass(frozen=True, slots=True)
class _FailingBackend(ReferenceRelationBackend):
    backend_id: str = "test.failing"

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _ = evaluation
        raise ValueError("backend failure")


def test_backend_evaluation_failure_has_a_domain_error() -> None:
    backend = _FailingBackend()
    verified = verify_point_domain(_domain([1]), program_id="program")

    with pytest.raises(PointDomainEvaluationError, match="backend failure"):
        materialize_point_domain(
            backend,
            select_point_domain(backend, verified),
            ParameterRelationData(),
        )


class _Opaque:
    def __deepcopy__(self, _memo: dict[int, object]) -> _Opaque:
        return self

    def __scopecat_fingerprint__(self) -> object:
        raise RuntimeError("opaque fingerprint unavailable")


def test_opaque_row_value_never_prevents_logical_identity() -> None:
    opaque = _Opaque()
    table_type = Table(
        (TableColumn("payload", Scalar(Payload("opaque"))),),
        min_rows=1,
        max_rows=1,
    )
    domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    [{"payload": PayloadValue(schema_id="opaque", payload=opaque)}]
                ),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            ),
        )
    )

    point = _materialize(domain).points[0]

    assert point.logical_id == LogicalPointId(PointDomainId("experiment", "root"), 0)
    assert point.row_key is None
    assert cast("PayloadValue", point.row["payload"]).payload is opaque


def test_point_rows_are_defensive_snapshots_including_payload_containers() -> None:
    payload = {"nested": [1]}
    table_type = Table(
        (TableColumn("payload", Scalar(Payload("opaque"))),),
        min_rows=1,
        max_rows=1,
    )
    domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    [{"payload": PayloadValue(schema_id="opaque", payload=payload)}]
                ),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            ),
        )
    )
    point = _materialize(domain).points[0]
    exposed = cast("PayloadValue", point.row["payload"])
    cast("dict[str, list[int]]", exposed.payload)["nested"].append(2)

    captured = cast("PayloadValue", point.row["payload"])
    assert captured.payload == {"nested": [1]}


class _MutableRowsBackend(ReferenceRelationBackend):
    returned_rows: list[Row]

    def __init__(self) -> None:
        super().__init__(backend_id="test.mutable-rows")
        object.__setattr__(self, "returned_rows", [{"x": 1}])

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _ = evaluation
        return self.returned_rows


def test_backend_row_mutation_cannot_change_materialized_domain() -> None:
    backend = _MutableRowsBackend()
    verified = verify_point_domain(_domain([1]), program_id="program")
    materialized = materialize_point_domain(
        backend,
        select_point_domain(backend, verified),
        ParameterRelationData(),
    )

    backend.returned_rows[0]["x"] = 9

    assert materialized.points[0].row == {"x": 1}


def test_verified_domain_is_a_defensive_snapshot() -> None:
    verified = verify_point_domain(_domain([1]), program_id="program")
    exposed_root = verified.relation_leaves[0].value.plan.root
    assert exposed_root.rows is not None
    exposed_root.rows[0]["x"] = 99

    captured_root = verified.relation_leaves[0].value.plan.root
    assert captured_root.rows == [{"x": 1}]


def test_point_domain_artifacts_are_sealed() -> None:
    domain = _domain([1])
    verified = verify_point_domain(domain, program_id="program")
    logical_id = LogicalPointId(verified.id, 0)

    with pytest.raises(TypeError, match="verify_point_domain"):
        VerifiedPointDomain(
            verified.id,
            domain,
            cast("PointDomainAnalysis", object()),
            (),
        )
    with pytest.raises(TypeError, match="point-domain selection"):
        SelectedPointDomain(verified, "test", ())
    with pytest.raises(TypeError, match="point-domain materialization"):
        MaterializedPoint(logical_id, {"x": 1}, None)
    with pytest.raises(TypeError, match="point-domain materialization"):
        MaterializedPointDomain(verified.id, (), verified.cardinality)


def test_entity_columns_must_be_unique_present_and_entity_typed() -> None:
    domain = PointDomain(
        root=_domain([1]).root,
        entity_columns=("missing", "x", "x"),
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        verify_point_domain(domain, program_id="program")

    assert {issue.code for issue in caught.value.issues} == {
        "point_domain_entity_column_duplicate",
        "point_domain_entity_column_missing",
        "point_domain_entity_column_type",
    }


def test_entity_column_accepts_entity_type() -> None:
    table_type = Table(
        (TableColumn("entity", Scalar(Entity("qubit"))),),
        min_rows=1,
        max_rows=1,
    )
    domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows([{"entity": EntityRef(id="q0", kind="qubit")}]),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            )
        ),
        entity_columns=("entity",),
    )

    verified = verify_point_domain(domain, program_id="program")

    assert verified.entity_columns == ("entity",)
    assert verified.value_type == table_type
    assert [column.id for column in verified.coordinate_columns] == ["entity"]


def test_entity_metadata_does_not_change_row_key_or_logical_identity() -> None:
    table_type = Table(
        (TableColumn("entity", Scalar(Entity("qubit"))),),
        min_rows=1,
        max_rows=1,
    )
    domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows([{"entity": EntityRef(id="q0", kind="qubit")}]),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            )
        ),
        entity_columns=("entity",),
    )
    verified = verify_point_domain(domain, program_id="program")
    selected = select_point_domain(REFERENCE_RELATION_BACKEND, verified)

    first = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        selected,
        ParameterRelationData(),
        row_normalizer=lambda _row: {
            "entity": EntityRef(id="q0", kind="qubit", metadata={"slot": 1})
        },
    ).points[0]
    second = materialize_point_domain(
        REFERENCE_RELATION_BACKEND,
        selected,
        ParameterRelationData(),
        row_normalizer=lambda _row: {
            "entity": EntityRef(id="q0", kind="qubit", metadata={"slot": 2})
        },
    ).points[0]

    assert first.logical_id == second.logical_id
    assert first.row_key == second.row_key
    assert verified.row_type == RowType.from_table(table_type)


def test_point_root_rejects_external_row_dependencies() -> None:
    rows = verify_table_value_expr(
        grid(x=point_col("source")),
        bindings=RelationTypeBindings(
            point_row=RowType((TableColumn("source", _INT),))
        ),
        expected_type=_INT_TABLE,
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        verify_point_domain(
            PointDomain(root=point_rows(rows)),
            program_id="program",
        )

    assert [issue.code for issue in caught.value.issues] == [
        "point_domain_open_row_interface"
    ]


def test_point_root_rejects_unresolved_input_imports() -> None:
    rows = verify_table_value_expr(
        input_table("points"),
        bindings=RelationTypeBindings(inputs={"points": _INT_TABLE}),
        expected_type=_INT_TABLE,
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        verify_point_domain(
            PointDomain(root=point_rows(rows)),
            program_id="program",
        )

    assert [issue.code for issue in caught.value.issues] == ["point_domain_open_input"]
