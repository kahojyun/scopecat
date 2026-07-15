from __future__ import annotations

from collections.abc import Callable
from typing import override

import pytest

import scopecat.compiler.relations.backend as relation_backend
from scopecat.compiler.relations.analysis import (
    PlanNode,
    RelationOperation,
)
from scopecat.compiler.relations.backend import (
    RelationBackendCapabilityDimension,
    RelationBackendCapabilityError,
    RelationBackendCapabilityIssue,
    RelationPlanRequirements,
)
from scopecat.compiler.relations.model import (
    GridColumn,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    case,
    col,
    grid,
    input_ref,
    input_series,
    input_table,
    linspace,
    lit,
    literal_rows,
    outer,
    param,
    parameter_series,
    point_col,
    range_values,
    table,
    values,
    zip_relations,
)
from scopecat.compiler.relations.reference_backend import ReferenceRelationBackend
from scopecat.compiler.relations.verification import (
    ExternalRowRequirement,
    ParameterLookupSignature,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Quantity,
    Record,
    RecordField,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.records.parameter import Quantity as QuantityValue

BOOL = Scalar(Bool())
INT = Scalar(Int())
FLOAT = Scalar(Float())
STRING = Scalar(String())
ENTITY = Scalar(Entity(entity_kind="qubit"))
FREQUENCY = Scalar(Quantity(dimension="frequency", unit="GHz"))

TABLE_INPUT = Table(
    columns=(
        TableColumn("id", STRING),
        TableColumn("flag", BOOL),
        TableColumn("value", INT),
        TableColumn("entity", ENTITY),
    ),
    primary_key=("id",),
    min_rows=1,
    max_rows=4,
)
TABLE_PARAMETER = Table(
    columns=(
        TableColumn("id", STRING),
        TableColumn("gain", FLOAT),
    ),
    primary_key=("id",),
    min_rows=0,
    max_rows=3,
)


def _scope(local_id: str) -> RowScopeId:
    return RowScopeId(SymbolId(local_id=local_id))


LOCAL_SCOPE = _scope("local")
EXTERNAL_SCOPE = _scope("external")


def _base_bindings() -> RelationTypeBindings:
    return RelationTypeBindings(
        inputs={
            "scalar": INT,
            "series": Series(INT, min_length=1, max_length=3),
            "rows": TABLE_INPUT,
        },
        parameters={
            "scalar": FLOAT,
            "series": Series(FLOAT, min_length=0, max_length=5),
            "rows": TABLE_PARAMETER,
        },
        point_row=RowType(columns=(TableColumn("point", INT),)),
        current_row=RowType(
            columns=(
                TableColumn("current", INT),
                TableColumn("id", STRING),
            )
        ),
        outer_row=RowType(columns=(TableColumn("outer", INT),)),
        row_arguments={
            EXTERNAL_SCOPE: RowType(columns=(TableColumn("external", INT),))
        },
    )


def _lookup() -> ScalarExpr:
    return param("rows", key={"id": "q0"}, column="gain")


def _filter() -> RelationExpr:
    return input_table("rows").filter(
        col("flag", row_scope_id=LOCAL_SCOPE),
        row_scope_id=LOCAL_SCOPE,
    )


def _with_columns() -> RelationExpr:
    return input_table("rows").with_columns(
        row_scope_id=LOCAL_SCOPE,
        copied=col("value", row_scope_id=LOCAL_SCOPE),
    )


def _join() -> RelationExpr:
    return input_table("rows").join(table("rows"), on={"id": "id"})


def _cross() -> RelationExpr:
    return input_table("rows").cross(grid(extra=[1, 2]))


def _lateral_cross() -> RelationExpr:
    return input_table("rows").lateral_cross(
        grid(current_copy=col("value"), outer_copy=outer("value"))
    )


def _point_cross() -> RelationExpr:
    return literal_rows([{"axis": 1}]).point_cross(grid(point_copy=point_col("axis")))


def _zip() -> RelationExpr:
    return zip_relations(
        literal_rows([{"left": 1}]),
        literal_rows([{"right": "a"}]),
    )


OperationCase = tuple[RelationOperation, Callable[[], PlanNode]]


_OPERATION_CASES: tuple[OperationCase, ...] = (
    (RelationOperation.SCALAR_LITERAL, lambda: lit(1)),
    (RelationOperation.SCALAR_CURRENT_COLUMN, lambda: col("current")),
    (RelationOperation.SCALAR_OUTER_COLUMN, lambda: outer("outer")),
    (RelationOperation.SCALAR_POINT_COLUMN, lambda: point_col("point")),
    (RelationOperation.SCALAR_INPUT, lambda: input_ref("scalar")),
    (RelationOperation.SCALAR_PARAMETER, lambda: param("scalar")),
    (RelationOperation.SCALAR_PARAMETER_LOOKUP, _lookup),
    (RelationOperation.SCALAR_BINARY, lambda: input_ref("scalar") + 1),
    (
        RelationOperation.SCALAR_CASE,
        lambda: case((lit(True), 1), fallback=2),
    ),
    (RelationOperation.SERIES_VALUES, lambda: values([1, 2])),
    (RelationOperation.SERIES_LINSPACE, lambda: linspace(0.0, 1.0, 3)),
    (RelationOperation.SERIES_RANGE, lambda: range_values(0, 3, 1)),
    (RelationOperation.SERIES_INPUT, lambda: input_series("series")),
    (RelationOperation.SERIES_PARAMETER, lambda: parameter_series("series")),
    (
        RelationOperation.SERIES_RELATION_COLUMN,
        lambda: input_table("rows").column("value"),
    ),
    (
        RelationOperation.SERIES_RELATION_ENTITIES,
        lambda: input_table("rows").entities("entity"),
    ),
    (
        RelationOperation.RELATION_LITERAL_ROWS,
        lambda: literal_rows([{"literal": 1}]),
    ),
    (RelationOperation.RELATION_PARAMETER_TABLE, lambda: table("rows")),
    (RelationOperation.RELATION_INPUT, lambda: input_table("rows")),
    (RelationOperation.RELATION_GRID, lambda: grid(axis=[1, 2])),
    (
        RelationOperation.RELATION_SELECT,
        lambda: input_table("rows").select("id", "value"),
    ),
    (RelationOperation.RELATION_FILTER, _filter),
    (RelationOperation.RELATION_JOIN, _join),
    (RelationOperation.RELATION_CROSS, _cross),
    (RelationOperation.RELATION_LATERAL_CROSS, _lateral_cross),
    (RelationOperation.RELATION_POINT_CROSS, _point_cross),
    (RelationOperation.RELATION_ZIP, _zip),
    (RelationOperation.RELATION_WITH_COLUMNS, _with_columns),
    (
        RelationOperation.RELATION_SORT,
        lambda: input_table("rows").sort("id"),
    ),
    (RelationOperation.RELATION_LIMIT, lambda: input_table("rows").limit(2)),
)


@pytest.mark.parametrize(
    ("operation", "make_root"),
    _OPERATION_CASES,
    ids=lambda value: value.value if isinstance(value, RelationOperation) else None,
)
def test_verifier_covers_every_backend_neutral_operation(
    operation: RelationOperation,
    make_root: Callable[[], PlanNode],
) -> None:
    root = make_root()

    verified = verify_relation_plan(root, bindings=_base_bindings())

    assert verified.required_operations[0] is operation
    assert (
        type(verified.certified_type)
        is {
            "scalar": Scalar,
            "series": Series,
            "relation": Table,
        }[operation.value.split(".", maxsplit=1)[0]]
    )


def test_operation_matrix_is_exhaustive() -> None:
    assert {operation for operation, _make_root in _OPERATION_CASES} == set(
        RelationOperation
    )


def test_plan_facts_use_stable_structural_paths_in_postorder() -> None:
    root = input_ref("left") + param("right")

    verified = verify_relation_plan(
        root,
        bindings=RelationTypeBindings(
            inputs={"left": INT},
            parameters={"right": FLOAT},
        ),
    )

    assert [
        (fact.path, fact.operation, fact.value_type) for fact in verified.facts
    ] == [
        (("left",), RelationOperation.SCALAR_INPUT, INT),
        (("right",), RelationOperation.SCALAR_PARAMETER, FLOAT),
        ((), RelationOperation.SCALAR_BINARY, Scalar(Float())),
    ]


def test_context_supplies_null_literal_type_without_losing_nullability() -> None:
    expected = Scalar(Quantity(dimension="frequency", unit="GHz"), nullable=True)

    verified = verify_relation_plan(lit(None), expected_type=expected)

    assert verified.certified_type == expected


@pytest.mark.parametrize(
    ("root", "code"),
    [
        (lit(None), "ambiguous_null"),
        (values([]), "ambiguous_empty_series"),
        (literal_rows([]), "ambiguous_empty_table"),
    ],
)
def test_context_dependent_literals_require_an_expected_type(
    root: PlanNode,
    code: str,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == code
    assert caught.value.path == ()


def test_empty_series_uses_context_for_items_and_refines_cardinality() -> None:
    expected = Series(ENTITY, min_length=0, max_length=10)

    verified = verify_relation_plan(values([]), expected_type=expected)

    assert verified.certified_type == expected
    assert verified.facts[-1].value_type == Series(
        ENTITY,
        min_length=0,
        max_length=0,
    )


def test_empty_relation_uses_context_for_schema_and_refines_cardinality() -> None:
    expected = Table(
        columns=(TableColumn("frequency", FREQUENCY),),
        primary_key=(),
        min_rows=0,
        max_rows=10,
    )

    verified = verify_relation_plan(literal_rows([]), expected_type=expected)

    assert verified.certified_type == expected
    assert verified.facts[-1].value_type == Table(
        columns=expected.columns,
        primary_key=(),
        min_rows=0,
        max_rows=0,
    )


def test_empty_grid_column_uses_output_schema_context() -> None:
    expected = Table(
        columns=(TableColumn("axis", INT),),
        min_rows=0,
        max_rows=10,
    )

    verified = verify_relation_plan(grid(axis=[]), expected_type=expected)

    assert verified.certified_type == expected
    assert verified.facts[-1].value_type == Table(
        columns=expected.columns,
        min_rows=0,
        max_rows=0,
    )


def test_explicit_series_unit_types_numeric_bounds_as_quantities() -> None:
    expression = SeriesExpr(
        kind="linspace",
        start=input_ref("start"),
        stop=input_ref("stop"),
        count=3,
        unit="GHz",
    )

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(inputs={"start": FLOAT, "stop": FLOAT}),
    )

    assert verified.certified_type == Series(
        Scalar(Quantity(unit="GHz")),
        min_length=3,
        max_length=3,
    )
    assert [item.code for item in verified.runtime_obligations] == [
        "series_values_finite"
    ]


def test_explicit_series_unit_is_validated_before_materialization() -> None:
    expression = SeriesExpr(
        kind="linspace",
        start=lit(0.0),
        stop=lit(1.0),
        count=2,
        unit="not-a-unit",
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(expression)

    assert caught.value.code == "invalid_series_unit"


def test_series_bounds_must_statically_guarantee_finite_values() -> None:
    expression = SeriesExpr(
        kind="linspace",
        start=input_ref("start"),
        stop=lit(1.0),
        count=2,
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            expression,
            bindings=RelationTypeBindings(
                inputs={"start": Scalar(Float(finite=False))}
            ),
        )

    assert caught.value.code == "invalid_series_bound"


def test_all_null_literal_column_is_typed_from_expected_schema() -> None:
    expected = Table(
        columns=(TableColumn("frequency", Scalar(FREQUENCY.atom, nullable=True)),),
        min_rows=1,
        max_rows=1,
    )

    verified = verify_relation_plan(
        literal_rows([{"frequency": None}]),
        expected_type=expected,
    )

    assert verified.certified_type == expected


def test_case_propagates_sibling_context_to_null_branch() -> None:
    expression = case(
        (lit(False), None),
        fallback=QuantityValue(value=5.0, unit="GHz"),
    )

    verified = verify_relation_plan(expression)

    assert verified.certified_type == Scalar(
        Quantity(unit="GHz", minimum=5.0, maximum=5.0),
        nullable=True,
    )


def test_case_common_type_does_not_invent_a_finite_guarantee() -> None:
    nonfinite = Scalar(Float(minimum=0.0, maximum=1.0, finite=False))
    finite = Scalar(Float(minimum=2.0, maximum=3.0))
    expression = case((lit(True), input_ref("left")), fallback=input_ref("right"))

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(inputs={"left": nonfinite, "right": finite}),
    )

    assert verified.certified_type == Scalar(
        Float(minimum=0.0, maximum=3.0, finite=False)
    )


def test_unbounded_integer_is_not_unsafely_widened_to_float() -> None:
    expression = case(
        (lit(True), input_ref("integer")),
        fallback=input_ref("floating"),
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            expression,
            bindings=RelationTypeBindings(inputs={"integer": INT, "floating": FLOAT}),
        )

    assert caught.value.code == "incompatible_branch_types"


def test_only_referenced_typed_imports_enter_the_proof() -> None:
    bindings = RelationTypeBindings(
        inputs={"used": INT, "unused": FLOAT},
        parameters={"unused": STRING},
    )

    verified = verify_relation_plan(input_ref("used"), bindings=bindings)

    assert len(verified.imports) == 1
    selected = verified.imports[0]
    assert selected.id == "used"
    assert selected.value_type == INT


def test_input_and_parameter_namespaces_are_typed_independently() -> None:
    bindings = RelationTypeBindings(
        inputs={"shared": INT},
        parameters={"shared": FLOAT},
    )

    verified = verify_relation_plan(
        grid(from_input=input_ref("shared"), from_parameter=param("shared")),
        bindings=bindings,
    )

    imported = {(item.namespace.value, item.id) for item in verified.imports}
    assert imported == {
        ("input", "shared"),
        ("parameter", "shared"),
    }


@pytest.mark.parametrize(
    ("root", "bindings"),
    [
        (
            input_ref("wrong"),
            RelationTypeBindings(inputs={"wrong": Series(INT)}),
        ),
        (
            input_series("wrong"),
            RelationTypeBindings(inputs={"wrong": INT}),
        ),
        (
            input_table("wrong"),
            RelationTypeBindings(inputs={"wrong": INT}),
        ),
        (
            param("wrong"),
            RelationTypeBindings(parameters={"wrong": TABLE_PARAMETER}),
        ),
        (
            parameter_series("wrong"),
            RelationTypeBindings(parameters={"wrong": FLOAT}),
        ),
        (
            table("wrong"),
            RelationTypeBindings(parameters={"wrong": FLOAT}),
        ),
    ],
)
def test_typed_imports_reject_reference_shape_mismatches(
    root: PlanNode,
    bindings: RelationTypeBindings,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root, bindings=bindings)

    assert caught.value.code == "import_shape_mismatch"
    assert caught.value.path == ()


def test_unknown_import_reports_a_stable_code_and_nested_path() -> None:
    root = grid(
        known=[1],
        missing=GridColumn(kind="series", series=input_series("missing")),
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ("columns", "missing", "series")


def test_filter_uses_its_source_row_signature_not_the_ambient_current_row() -> None:
    source = Table(
        columns=(TableColumn("keep", BOOL),),
        min_rows=0,
        max_rows=2,
    )
    ambient = RowType(columns=(TableColumn("keep", STRING),))
    local_scope = _scope("filter")
    root = input_table("rows").filter(
        col("keep", row_scope_id=local_scope),
        row_scope_id=local_scope,
    )

    verified = verify_relation_plan(
        root,
        bindings=RelationTypeBindings(
            inputs={"rows": source},
            current_row=ambient,
        ),
    )

    assert verified.certified_type == Table(
        columns=source.columns,
        min_rows=0,
        max_rows=2,
    )


def test_external_nominal_row_argument_has_its_own_typed_signature() -> None:
    scope = _scope("state-row")

    verified = verify_relation_plan(
        col("frequency", row_scope_id=scope),
        bindings=RelationTypeBindings(
            row_arguments={
                scope: RowType(columns=(TableColumn("frequency", FREQUENCY),))
            }
        ),
    )

    assert verified.certified_type == FREQUENCY


def test_plan_local_binder_cannot_shadow_an_external_row_argument() -> None:
    scope = _scope("state-row")
    root = literal_rows([{"keep": True}]).filter(
        col("keep", row_scope_id=scope),
        row_scope_id=scope,
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            root,
            bindings=RelationTypeBindings(
                row_arguments={scope: RowType(columns=(TableColumn("keep", BOOL),))}
            ),
        )

    assert caught.value.code == "row_binder_collision"
    assert caught.value.path == ()


def test_lateral_cross_introduces_current_and_outer_left_row_signatures() -> None:
    left_type = Table(
        columns=(TableColumn("value", INT),),
        min_rows=1,
        max_rows=2,
    )
    root = input_table("left").lateral_cross(
        grid(current=col("value"), lexical=outer("value"))
    )

    verified = verify_relation_plan(
        root,
        bindings=RelationTypeBindings(inputs={"left": left_type}),
    )

    assert isinstance(verified.certified_type, Table)
    assert tuple(column.id for column in verified.certified_type.columns) == (
        "value",
        "current",
        "lexical",
    )


def test_plain_cross_does_not_synthesize_a_left_row_signature() -> None:
    left_type = Table(columns=(TableColumn("value", INT),))
    root = input_table("left").cross(grid(captured=col("value")))

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            root,
            bindings=RelationTypeBindings(inputs={"left": left_type}),
        )

    assert caught.value.code == "unbound_row_reference"
    assert caught.value.path == ()


def test_point_cross_extends_only_the_right_point_signature() -> None:
    root = literal_rows([{"axis": 1}]).point_cross(grid(copy=point_col("axis")))

    verified = verify_relation_plan(root)

    assert isinstance(verified.certified_type, Table)
    assert tuple(column.id for column in verified.certified_type.columns) == (
        "axis",
        "copy",
    )
    assert verified.external_row_interface.point is None
    selected = relation_backend.select_relation_plan(
        ReferenceRelationBackend(),
        verified,
    )
    assert relation_backend.evaluate_relation(
        ReferenceRelationBackend(),
        selected,
        point_row={"undeclared": "not part of this interface"},
    ) == [{"axis": 1, "copy": 1}]


def test_external_row_interface_projects_only_free_typed_column_reads() -> None:
    point = RowType(
        (
            TableColumn("point", INT),
            TableColumn("unused_point", STRING),
        ),
        allow_extra_columns=True,
    )
    current = RowType(
        (
            TableColumn("current", INT),
            TableColumn("unused_current", STRING),
        )
    )
    outer_row = RowType((TableColumn("outer", INT),))
    argument = RowType((TableColumn("argument", INT),))
    expression = (
        point_col("point")
        + col("current")
        + outer("outer")
        + col("argument", row_scope_id=EXTERNAL_SCOPE)
    )

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(
            point_row=point,
            current_row=current,
            outer_row=outer_row,
            row_arguments={EXTERNAL_SCOPE: argument},
        ),
    )

    interface = verified.external_row_interface
    assert interface.point == ExternalRowRequirement(
        RowType((TableColumn("point", INT),), allow_extra_columns=True),
        ("point",),
    )
    assert interface.current == ExternalRowRequirement(
        RowType((TableColumn("current", INT),)),
        ("current",),
    )
    assert interface.outer == ExternalRowRequirement(outer_row, ("outer",))
    assert len(interface.arguments) == 1
    assert interface.arguments[0].row_scope_id == EXTERNAL_SCOPE
    assert interface.arguments[0].requirement == ExternalRowRequirement(
        argument,
        ("argument",),
    )


def test_external_row_interface_excludes_plan_local_row_binders() -> None:
    scope = _scope("local-interface")
    expression = literal_rows([{"keep": True}]).filter(
        col("keep", row_scope_id=scope),
        row_scope_id=scope,
    )

    verified = verify_relation_plan(expression)

    assert verified.external_row_interface.point is None
    assert verified.external_row_interface.current is None
    assert verified.external_row_interface.outer is None
    assert verified.external_row_interface.arguments == ()


def test_external_row_interface_retains_nested_path_and_root_column_type() -> None:
    device = Scalar(Record(fields=(RecordField("rank", INT),)))
    current = RowType(
        (
            TableColumn("device", device),
            TableColumn("unused", STRING),
        ),
        allow_extra_columns=True,
    )

    verified = verify_relation_plan(
        col("device.rank"),
        bindings=RelationTypeBindings(current_row=current),
    )

    assert verified.external_row_interface.current == ExternalRowRequirement(
        RowType(
            (TableColumn("device", device),),
            allow_extra_columns=True,
        ),
        ("device.rank",),
    )


def test_point_cross_requires_full_external_point_row_but_not_local_columns() -> None:
    device = Scalar(Record(fields=(RecordField("rank", INT),)))
    point = RowType(
        (
            TableColumn("device", device),
            TableColumn("unused", STRING),
        ),
        allow_extra_columns=True,
    )
    expression = literal_rows([{"axis": 1}]).point_cross(
        grid(
            inherited=point_col("device.rank"),
            local=point_col("axis"),
        )
    )

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(point_row=point),
    )

    assert verified.external_row_interface.point == ExternalRowRequirement(
        row_type=point,
        column_references=("device.rank",),
        requires_full_row=True,
    )


def test_exact_dotted_column_takes_precedence_over_record_traversal() -> None:
    row = RowType(
        columns=(
            TableColumn("device.rank", INT),
            TableColumn(
                "device",
                Scalar(
                    Record(
                        fields=(RecordField("rank", STRING),),
                    )
                ),
            ),
        )
    )

    verified = verify_relation_plan(
        col("device.rank"),
        bindings=RelationTypeBindings(current_row=row),
    )

    assert verified.certified_type == INT


def test_unknown_column_reports_the_condition_path() -> None:
    scope = _scope("filter")
    root = literal_rows([{"keep": True}]).filter(
        col("missing", row_scope_id=scope),
        row_scope_id=scope,
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == "unknown_column"
    assert caught.value.path == ("condition",)


def test_binary_and_case_validate_operand_types_before_execution() -> None:
    bad_binary = lit("not-a-number") + 1
    bad_case = case((lit(1), "yes"), fallback="no")

    with pytest.raises(RelationPlanVerificationError) as binary_error:
        verify_relation_plan(bad_binary)
    with pytest.raises(RelationPlanVerificationError) as case_error:
        verify_relation_plan(bad_case)

    assert binary_error.value.code == "invalid_scalar_operator"
    assert case_error.value.code == "non_boolean_condition"
    assert case_error.value.path == ("cases", 0, "condition")


def test_floating_arithmetic_records_its_finite_result_obligation() -> None:
    verified = verify_relation_plan(
        input_ref("left") + input_ref("right"),
        bindings=RelationTypeBindings(inputs={"left": FLOAT, "right": FLOAT}),
    )

    assert [item.code for item in verified.runtime_obligations] == [
        "scalar_result_finite"
    ]


def test_join_allows_only_same_named_join_key_overlap() -> None:
    left = Table(
        columns=(TableColumn("id", STRING), TableColumn("left", INT)),
        primary_key=("id",),
        min_rows=1,
        max_rows=2,
    )
    right = Table(
        columns=(TableColumn("id", STRING), TableColumn("right", FLOAT)),
        primary_key=("id",),
        min_rows=1,
        max_rows=3,
    )

    verified = verify_relation_plan(
        input_table("left").join(input_table("right"), on={"id": "id"}),
        bindings=RelationTypeBindings(inputs={"left": left, "right": right}),
    )

    assert verified.certified_type == Table(
        columns=(*left.columns, right.columns[1]),
        primary_key=("id",),
        min_rows=0,
        max_rows=6,
    )


def test_join_consumer_contract_does_not_retype_dropped_right_key() -> None:
    left = Table(columns=(TableColumn("id", INT),))
    right = Table(columns=(TableColumn("id", FLOAT),))
    expected = Table(columns=(TableColumn("id", INT),))

    verified = verify_relation_plan(
        input_table("left").join(input_table("right"), on={"id": "id"}),
        bindings=RelationTypeBindings(inputs={"left": left, "right": right}),
        expected_type=expected,
    )

    assert verified.certified_type == expected
    assert verified.facts[-2].path == ("right",)
    assert verified.facts[-2].value_type == right


def test_join_rejects_nullable_keys_before_materialization() -> None:
    left = Table(
        columns=(TableColumn("id", Scalar(String(), nullable=True)),),
    )
    right = Table(columns=(TableColumn("id", STRING),))

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            input_table("left").join(input_table("right"), on={"id": "id"}),
            bindings=RelationTypeBindings(inputs={"left": left, "right": right}),
        )

    assert caught.value.code == "nullable_join_key"
    assert caught.value.path == ("on", "id")


@pytest.mark.parametrize(
    ("root", "expected_path"),
    [
        (
            literal_rows([{"same": 1}]).cross(literal_rows([{"same": 2}])),
            (),
        ),
        (
            literal_rows([{"same": 1}]).lateral_cross(literal_rows([{"same": 2}])),
            (),
        ),
        (
            literal_rows([{"same": 1}]).point_cross(literal_rows([{"same": 2}])),
            (),
        ),
        (
            zip_relations(
                literal_rows([{"same": 1}]),
                literal_rows([{"same": 2}]),
            ),
            ("sources", 1),
        ),
    ],
)
def test_relation_combinators_reject_static_column_collisions(
    root: RelationExpr,
    expected_path: tuple[str | int, ...],
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == "duplicate_columns"
    assert caught.value.path == expected_path


def test_relational_operators_preserve_cardinality_facts() -> None:
    source = Table(
        columns=(
            TableColumn("group", INT),
            TableColumn("item", INT),
            TableColumn("keep", BOOL),
        ),
        primary_key=("group", "item"),
        min_rows=3,
        max_rows=5,
    )
    bindings = RelationTypeBindings(inputs={"rows": source})
    selected = verify_relation_plan(
        input_table("rows").select("group", "keep"), bindings=bindings
    )
    filtered = verify_relation_plan(
        _scoped_filter(input_table("rows")),
        bindings=bindings,
    )
    overwritten = verify_relation_plan(
        _scoped_with_column(input_table("rows"), "item", 0),
        bindings=bindings,
    )
    crossed = verify_relation_plan(
        input_table("rows").cross(literal_rows([{"side": 1}, {"side": 2}])),
        bindings=bindings,
    )
    limited = verify_relation_plan(input_table("rows").limit(4), bindings=bindings)

    assert isinstance(selected.certified_type, Table)
    assert selected.certified_type.primary_key == ()
    assert (selected.certified_type.min_rows, selected.certified_type.max_rows) == (
        3,
        5,
    )
    assert isinstance(filtered.certified_type, Table)
    assert (filtered.certified_type.min_rows, filtered.certified_type.max_rows) == (
        0,
        5,
    )
    assert isinstance(overwritten.certified_type, Table)
    assert overwritten.certified_type.primary_key == ()
    assert isinstance(crossed.certified_type, Table)
    assert (crossed.certified_type.min_rows, crossed.certified_type.max_rows) == (
        6,
        10,
    )
    assert isinstance(limited.certified_type, Table)
    assert (limited.certified_type.min_rows, limited.certified_type.max_rows) == (
        3,
        4,
    )


def _scoped_filter(source: RelationExpr) -> RelationExpr:
    scope = _scope("filter-cardinality")
    return source.filter(col("keep", row_scope_id=scope), row_scope_id=scope)


def _scoped_with_column(
    source: RelationExpr,
    column: str,
    value: object,
) -> RelationExpr:
    scope = _scope("columns-cardinality")
    return source.with_columns(row_scope_id=scope, **{column: value})


def test_zip_rejects_disjoint_cardinality_ranges_before_execution() -> None:
    left = Table(columns=(TableColumn("left", INT),), min_rows=0, max_rows=1)
    right = Table(columns=(TableColumn("right", INT),), min_rows=2, max_rows=3)

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            zip_relations(input_table("left"), input_table("right")),
            bindings=RelationTypeBindings(inputs={"left": left, "right": right}),
        )

    assert caught.value.code == "zip_cardinality_mismatch"


def test_zip_with_overlapping_unknown_cardinalities_emits_runtime_obligation() -> None:
    left = Table(columns=(TableColumn("left", INT),), min_rows=0, max_rows=5)
    right = Table(columns=(TableColumn("right", INT),), min_rows=2, max_rows=8)

    verified = verify_relation_plan(
        zip_relations(input_table("left"), input_table("right")),
        bindings=RelationTypeBindings(inputs={"left": left, "right": right}),
    )

    assert isinstance(verified.certified_type, Table)
    assert (verified.certified_type.min_rows, verified.certified_type.max_rows) == (
        2,
        5,
    )
    assert [obligation.code for obligation in verified.runtime_obligations] == [
        "zip_equal_length"
    ]
    assert verified.runtime_obligations[0].path == ()


def test_dynamic_range_step_and_parameter_lookup_emit_runtime_obligations() -> None:
    bounds = RelationTypeBindings(
        inputs={"step": FLOAT},
        parameters={"rows": TABLE_PARAMETER},
    )
    dynamic_range = verify_relation_plan(
        SeriesExpr(
            kind="range",
            start=lit(0.0),
            stop=lit(1.0),
            step=input_ref("step"),
        ),
        bindings=bounds,
    )
    lookup = verify_relation_plan(
        param("rows", key={"id": "q0"}, column="gain"),
        bindings=bounds,
    )

    assert [item.code for item in dynamic_range.runtime_obligations] == [
        "range_step_nonzero",
        "range_progress",
    ]
    assert [item.code for item in lookup.runtime_obligations] == [
        "parameter_lookup_exactly_one"
    ]


def test_lookup_signature_closes_a_projection_without_faking_a_table_schema() -> None:
    signature = ParameterLookupSignature(
        table_id="calibration",
        key_input_types=(("device", STRING), ("mode", INT)),
        column_id="gain",
        result_type=FLOAT,
    )
    expression = param(
        "calibration",
        key={"mode": 1, "device": "q0"},
        column="gain",
    )

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(parameter_lookups=(signature,)),
    )

    assert verified.certified_type == FLOAT
    assert verified.imports[0].lookup == signature
    assert verified.imports[0].value_type == FLOAT


def test_lookup_signatures_allow_distinct_literal_key_input_types() -> None:
    signatures = (
        ParameterLookupSignature(
            table_id="calibration",
            key_input_types=(("device", Scalar(String(min_length=2, max_length=2))),),
            column_id="gain",
            result_type=FLOAT,
        ),
        ParameterLookupSignature(
            table_id="calibration",
            key_input_types=(("device", Scalar(String(min_length=9, max_length=9))),),
            column_id="gain",
            result_type=FLOAT,
        ),
    )

    verified = verify_relation_plan(
        param("calibration", key={"device": "long-name"}, column="gain"),
        bindings=RelationTypeBindings(parameter_lookups=signatures),
    )

    assert verified.imports[0].lookup == signatures[1]


def test_single_lookup_signature_preserves_key_expression_errors() -> None:
    signature = ParameterLookupSignature(
        table_id="calibration",
        key_input_types=(("device", STRING),),
        column_id="gain",
        result_type=FLOAT,
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            param(
                "calibration",
                key={"device": input_ref("missing")},
                column="gain",
            ),
            bindings=RelationTypeBindings(parameter_lookups=(signature,)),
        )

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ("key", "device")


def test_lookup_signatures_reject_conflicting_result_contracts() -> None:
    with pytest.raises(ValueError, match="result signatures conflict"):
        RelationTypeBindings(
            parameter_lookups=(
                ParameterLookupSignature(
                    table_id="calibration",
                    key_input_types=(("device", STRING),),
                    column_id="gain",
                    result_type=FLOAT,
                ),
                ParameterLookupSignature(
                    table_id="calibration",
                    key_input_types=(("device", STRING),),
                    column_id="gain",
                    result_type=INT,
                ),
            )
        )


def test_literal_zero_range_step_is_rejected_statically() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(range_values(0, 1, 0))

    assert caught.value.code == "range_step_zero"
    assert caught.value.path == ("step",)


def test_open_schema_cross_records_a_runtime_disjointness_obligation() -> None:
    open_rows = Table(
        columns=(TableColumn("known", INT),),
        allow_extra_columns=True,
    )

    verified = verify_relation_plan(
        input_table("open").cross(literal_rows([{"other": 1}])),
        bindings=RelationTypeBindings(inputs={"open": open_rows}),
    )

    assert [item.code for item in verified.runtime_obligations] == [
        "no_extra_column_collision"
    ]


def test_open_schema_merge_omits_impossible_column_collision_obligation() -> None:
    open_rows = Table(
        columns=(TableColumn("id", STRING),),
        allow_extra_columns=True,
    )
    empty_rows = Table(columns=())
    shared_key_rows = Table(columns=(TableColumn("id", STRING),))
    bindings = RelationTypeBindings(
        inputs={
            "open": open_rows,
            "empty": empty_rows,
            "shared": shared_key_rows,
        }
    )

    empty_cross = verify_relation_plan(
        input_table("open").cross(input_table("empty")),
        bindings=bindings,
    )
    shared_key_join = verify_relation_plan(
        input_table("open").join(input_table("shared"), on={"id": "id"}),
        bindings=bindings,
    )

    assert empty_cross.runtime_obligations == ()
    assert shared_key_join.runtime_obligations == ()


def test_two_empty_open_schemas_record_column_collision_obligation() -> None:
    open_rows = Table(columns=(), allow_extra_columns=True)

    verified = verify_relation_plan(
        input_table("left").cross(input_table("right")),
        bindings=RelationTypeBindings(inputs={"left": open_rows, "right": open_rows}),
    )

    assert [item.code for item in verified.runtime_obligations] == [
        "no_extra_column_collision"
    ]


def test_statically_empty_merge_omits_column_collision_obligation() -> None:
    empty_open = Table(columns=(), max_rows=0, allow_extra_columns=True)
    known = Table(
        columns=(TableColumn("value", INT),),
        min_rows=1,
        max_rows=1,
    )
    bindings = RelationTypeBindings(inputs={"empty": empty_open, "known": known})

    left_empty = verify_relation_plan(
        input_table("empty").cross(input_table("known")),
        bindings=bindings,
    )
    right_empty = verify_relation_plan(
        input_table("known").cross(input_table("empty")),
        bindings=bindings,
    )

    assert left_empty.runtime_obligations == ()
    assert right_empty.runtime_obligations == ()


def test_statically_empty_point_cross_omits_point_collision_obligation() -> None:
    empty = Table(
        columns=(TableColumn("axis", INT),),
        max_rows=0,
    )

    verified = verify_relation_plan(
        input_table("empty").point_cross(literal_rows([{}])),
        bindings=RelationTypeBindings(
            inputs={"empty": empty},
            point_row=RowType(allow_extra_columns=True),
        ),
    )

    assert verified.runtime_obligations == ()
    assert verified.external_row_interface.point is None


def test_verified_plan_defensively_copies_the_source_root() -> None:
    source = literal_rows([{"value": 1}]).limit(1)
    verified = verify_relation_plan(source)

    source.limit_count = 0
    projected = verified.root
    projected.limit_count = 0
    assert isinstance(verified.root, RelationExpr)
    assert verified.root.limit_count == 1


def test_backend_selection_consumes_proof_and_checks_capabilities() -> None:
    verified = verify_relation_plan(literal_rows([{"value": 1}]).sort("value"))
    backend = ReferenceRelationBackend(
        backend_id="tests.no-sort",
        supported_operations=(
            frozenset(RelationOperation) - {RelationOperation.RELATION_SORT}
        ),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(backend, verified)

    assert caught.value.backend_id == "tests.no-sort"
    assert tuple(issue.dimension for issue in caught.value.issues) == (
        RelationBackendCapabilityDimension.OPERATION,
    )
    assert tuple(issue.code for issue in caught.value.issues) == (
        RelationOperation.RELATION_SORT.value,
    )


def test_backend_operation_rejection_retains_each_occurrence_path() -> None:
    verified = verify_relation_plan(
        input_ref("value") + 1,
        bindings=RelationTypeBindings(inputs={"value": INT}),
    )
    backend = ReferenceRelationBackend(
        backend_id="tests.no-input-read",
        supported_operations=(
            frozenset(RelationOperation) - {RelationOperation.SCALAR_INPUT}
        ),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(backend, verified)

    assert [(issue.code, issue.path) for issue in caught.value.issues] == [
        (RelationOperation.SCALAR_INPUT.value, ("left",)),
    ]


def test_backend_selection_retains_the_certified_contract() -> None:
    verified = verify_relation_plan(lit(1), expected_type=INT)

    selected = relation_backend.select_relation_plan(
        ReferenceRelationBackend(),
        verified,
    )

    assert selected.certified_type == INT
    assert selected.required_operations == (RelationOperation.SCALAR_LITERAL,)


class _FiniteTableFactsBackend(ReferenceRelationBackend):
    @override
    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> tuple[RelationBackendCapabilityIssue, ...]:
        return tuple(
            RelationBackendCapabilityIssue(
                dimension=RelationBackendCapabilityDimension.TYPE_REQUIREMENT,
                code="unbounded_table",
                path=fact.path,
                message="backend requires every intermediate table to be bounded",
            )
            for fact in requirements.node_type_facts
            if isinstance(fact.value_type, Table) and fact.value_type.max_rows is None
        )


class _RestrictedExternalRowsBackend(ReferenceRelationBackend):
    @override
    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> tuple[RelationBackendCapabilityIssue, ...]:
        interface = requirements.external_row_interface
        rows = (
            ("point", interface.point),
            ("current", interface.current),
            ("outer", interface.outer),
            *(
                (argument.row_scope_id.qualified_name, argument.requirement)
                for argument in interface.arguments
            ),
        )
        issues: list[RelationBackendCapabilityIssue] = []
        for role, requirement in rows:
            if requirement is None:
                continue
            if requirement.requires_full_row:
                issues.append(
                    RelationBackendCapabilityIssue(
                        dimension=RelationBackendCapabilityDimension.ROW_INTERFACE,
                        code="full_external_row",
                        path=("external_rows", role),
                        message="backend requires statically projected row columns",
                    )
                )
            if requirement.row_type.allow_extra_columns:
                issues.append(
                    RelationBackendCapabilityIssue(
                        dimension=RelationBackendCapabilityDimension.ROW_INTERFACE,
                        code="open_external_row",
                        path=("external_rows", role),
                        message="backend requires closed external row schemas",
                    )
                )
        return tuple(issues)


def test_backend_acceptance_can_reject_implicit_full_point_row_access() -> None:
    verified = verify_relation_plan(
        literal_rows([{"axis": 1}]).point_cross(literal_rows([{}])),
        bindings=RelationTypeBindings(
            point_row=RowType((TableColumn("incoming", INT),))
        ),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(
            _RestrictedExternalRowsBackend(backend_id="tests.projected-rows"),
            verified,
        )

    assert [(issue.code, issue.path) for issue in caught.value.issues] == [
        ("full_external_row", ("external_rows", "point")),
    ]
    assert caught.value.issues[0].dimension is (
        RelationBackendCapabilityDimension.ROW_INTERFACE
    )


def test_backend_acceptance_can_reject_open_external_row_schema() -> None:
    verified = verify_relation_plan(
        col("value"),
        bindings=RelationTypeBindings(
            current_row=RowType(
                (TableColumn("value", INT),),
                allow_extra_columns=True,
            )
        ),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(
            _RestrictedExternalRowsBackend(backend_id="tests.closed-rows"),
            verified,
        )

    assert [(issue.code, issue.path) for issue in caught.value.issues] == [
        ("open_external_row", ("external_rows", "current")),
    ]
    assert caught.value.issues[0].dimension is (
        RelationBackendCapabilityDimension.ROW_INTERFACE
    )


def test_backend_acceptance_checks_every_intermediate_type_fact() -> None:
    unbounded = Table(columns=(TableColumn("value", INT),))
    verified = verify_relation_plan(
        input_table("rows").limit(2),
        bindings=RelationTypeBindings(inputs={"rows": unbounded}),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(
            _FiniteTableFactsBackend(backend_id="tests.finite-only"),
            verified,
        )

    assert [(issue.code, issue.path) for issue in caught.value.issues] == [
        ("unbounded_table", ("source",)),
    ]


def test_backend_acceptance_requires_runtime_obligation_discharge() -> None:
    verified = verify_relation_plan(
        input_ref("left") / input_ref("right"),
        bindings=RelationTypeBindings(inputs={"left": FLOAT, "right": FLOAT}),
    )
    backend = ReferenceRelationBackend(
        backend_id="tests.no-obligations",
        discharged_obligations=frozenset(),
    )

    with pytest.raises(RelationBackendCapabilityError) as caught:
        relation_backend.select_relation_plan(backend, verified)

    assert [issue.code for issue in caught.value.issues] == [
        "division_right_nonzero",
        "scalar_result_finite",
    ]
    assert all(
        issue.dimension is RelationBackendCapabilityDimension.RUNTIME_OBLIGATION
        for issue in caught.value.issues
    )


def test_selected_plan_retains_complete_backend_requirements() -> None:
    verified = verify_relation_plan(
        input_ref("value") / 2,
        bindings=RelationTypeBindings(inputs={"value": FLOAT}),
    )
    selected = relation_backend.select_relation_plan(
        ReferenceRelationBackend(),
        verified,
    )

    assert selected.requirements.certified_type == verified.certified_type
    assert selected.requirements.node_type_facts == verified.facts
    assert selected.requirements.typed_imports == verified.imports
    assert (
        selected.requirements.external_row_interface == verified.external_row_interface
    )
    assert selected.requirements.runtime_obligations == verified.runtime_obligations
