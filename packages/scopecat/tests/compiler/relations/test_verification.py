from __future__ import annotations

import pytest

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.model import (
    LiteralRowsRelationExpr,
    RelationExpr,
    RowScopeId,
    col,
    input_ref,
    input_series,
    input_table,
    lit,
    literal_rows,
    param,
    parameter_series,
    point_col,
    table,
    values,
)
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


EXTERNAL_SCOPE = _scope("external")


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


def test_empty_series_uses_context_for_items() -> None:
    expected = Series(ENTITY, min_length=0, max_length=10)

    verified = verify_relation_plan(values([]), expected_type=expected)

    assert verified.certified_type == expected


def test_empty_relation_uses_context_for_schema() -> None:
    expected = Table(
        columns=(TableColumn("frequency", FREQUENCY),),
        primary_key=(),
        min_rows=0,
        max_rows=10,
    )

    verified = verify_relation_plan(literal_rows([]), expected_type=expected)

    assert verified.certified_type == expected


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
        input_ref("shared") + param("shared"),
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
    root = literal_rows([{}]).with_columns(missing=input_ref("missing"))

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ("new_columns", "missing")


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
    argument = RowType((TableColumn("argument", INT),))
    expression = (
        point_col("point")
        + col("current")
        + col("argument", row_scope_id=EXTERNAL_SCOPE)
    )

    verified = verify_relation_plan(
        expression,
        bindings=RelationTypeBindings(
            point_row=point,
            current_row=current,
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


def test_binary_validates_operand_types_before_execution() -> None:
    bad_binary = lit("not-a-number") + 1

    with pytest.raises(RelationPlanVerificationError) as binary_error:
        verify_relation_plan(bad_binary)

    assert binary_error.value.code == "invalid_scalar_operator"


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


def test_verified_plan_defensively_copies_nested_literal_data() -> None:
    source = literal_rows([{"value": 1}]).select("value")
    verified = verify_relation_plan(source)

    assert isinstance(source.source, LiteralRowsRelationExpr)
    source.source.rows[0]["value"] = 0
    projected = verified.root
    assert isinstance(projected.source, LiteralRowsRelationExpr)
    projected.source.rows[0]["value"] = 0
    retained = verified.root
    assert isinstance(retained, RelationExpr)
    assert isinstance(retained.source, LiteralRowsRelationExpr)
    assert retained.source.rows == [{"value": 1}]
